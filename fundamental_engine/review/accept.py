"""Turns a REVIEWED model candidate into event records. Plan-first: build_plan() returns the exact statements; apply_plan()
runs them atomically. Nothing here is reachable from the CLI until the owner approves the workflow.

Rules (enforced here and by the schema's triggers):
  * a human reviewer (name >= 2 chars) and written notes are mandatory
  * only GROUNDED QUOTES can become event_evidence; model inferences never become evidence or part of the event
  * the event headline is the source item's own title (a public fact), not model text; no model-written summary
  * evidence claim types are the Python-assigned ones from extraction (official_statement / news_report)
  * company links are created only when the reviewer supplies a rationale, and only as reviewer_status='pending'
    (accepting a link needs a confirmed exposure candidate, which is a later workflow)
  * a decision row is appended to extraction_reviews (accept / reject / needs_more_evidence)
"""
import json
from datetime import datetime, timezone

STAGES = ("rumour", "discussion", "proposal", "consultation", "committee_recommendation", "approval", "notification",
          "implementation", "amendment", "delay", "suspension", "reversal", "confirmed_fact", "not_applicable")


class ReviewError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_reviewer(reviewer, notes):
    if len((reviewer or "").strip()) < 2:
        raise ReviewError("reviewer name (>= 2 chars) is required")
    if not (notes or "").strip():
        raise ReviewError("written review notes are required")


def build_plan(row, decision, reviewer, notes, status_stage="not_applicable", claim_indices=None, company_rationales=None, now=None):
    """row: result of review.queue.show(). Returns {'statements': [(sql, params)...], 'summary': {...}}."""
    _check_reviewer(reviewer, notes)
    now = now or _now()
    if decision not in ("accept", "reject", "needs_more_evidence"):
        raise ReviewError("decision must be accept, reject or needs_more_evidence")
    stmts = []
    summary = {"decision": decision, "extraction_id": row["extraction_id"], "evidence": 0, "company_links": 0}
    if decision != "accept":
        stmts.append(("INSERT INTO extraction_reviews(extraction_id,decision,reviewer,notes,event_id,decided_at_utc) VALUES(?,?,?,?,NULL,?)",
                      (row["extraction_id"], decision, reviewer.strip(), notes.strip(), now)))
        return {"statements": stmts, "summary": summary}
    if status_stage not in STAGES:
        raise ReviewError(f"status_stage must be one of {STAGES}")
    cand = json.loads(row["extracted_json"])
    quotes = [(i, c) for i, c in enumerate(cand.get("claims", [])) if c["kind"] == "quote" and c.get("grounded")]
    if not quotes:
        raise ReviewError("nothing to accept: the candidate has no grounded quote (inferences cannot become evidence)")
    chosen = [(i, c) for i, c in quotes if claim_indices is None or i in claim_indices]
    if not chosen:
        raise ReviewError("none of the selected claims is a grounded quote")
    headline = (row["title"] or "").strip()
    if not headline:
        raise ReviewError("source item has no title to use as the headline")
    stmts.append((
        "INSERT INTO events(event_type,headline,summary,event_date,event_date_precision,status_stage,verification_state,direction,"
        "magnitude,novelty,horizon,confidence,first_seen_at_utc,current_revision,created_at_utc,updated_at_utc) "
        "VALUES(?,?,NULL,NULL,'unknown',?,'single_source','unknown','unknown','unknown','unknown',NULL,?,1,?,?)",
        (cand["event_type"], headline, status_stage, row["item_collected"], now, now)))
    snapshot = {"source_extraction_id": row["extraction_id"], "model": row["model"], "accepted_claims": [c["text"] for _, c in chosen],
                "reviewer_notes": notes.strip()}
    stmts.append((
        "INSERT INTO event_revisions(event_id,revision_no,recorded_at_utc,status_stage,verification_state,headline,summary,snapshot_json,"
        "change_reason,changed_by,model_version,prompt_version) VALUES(last_insert_rowid(),1,?,?,'single_source',?,NULL,?,?,?,?,?)",
        (now, status_stage, headline, json.dumps(snapshot, sort_keys=True), f"created from reviewed extraction #{row['extraction_id']}",
         reviewer.strip(), row["model"], row["prompt_version"])))
    for _, c in chosen:
        stmts.append((
            "INSERT INTO event_evidence(event_id,source_item_id,claim,claim_type,relation,excerpt,verification_state,is_independent,"
            "recorded_at_utc,recorded_by) VALUES((SELECT MAX(event_id) FROM events),?,?,?,'supports',?,'unverified',NULL,?,?)",
            (row["source_item_id"], c["text"], c["claim_type"], c["text"][:1000], now, reviewer.strip())))
        summary["evidence"] += 1
    for t in cand.get("tickers", []):
        why = (company_rationales or {}).get(t["ticker"], "").strip()
        if why:
            stmts.append((
                "INSERT INTO event_companies(event_id,company_id,exposure_type,impact_direction,rationale,reviewer_status,created_at_utc) "
                "VALUES((SELECT MAX(event_id) FROM events),?,'uncertain','unknown',?,'pending',?)", (t["company_id"], why, now)))
            summary["company_links"] += 1
    stmts.append((
        "INSERT INTO extraction_reviews(extraction_id,decision,reviewer,notes,event_id,decided_at_utc) "
        "VALUES(?,'accept',?,?,(SELECT MAX(event_id) FROM events),?)", (row["extraction_id"], reviewer.strip(), notes.strip(), now)))
    return {"statements": stmts, "summary": summary}


def apply_plan(db, plan):
    """Atomic. Reachable only from tests until the workflow is approved."""
    return db.batch(plan["statements"])
