"""Candidate review queue (READ-ONLY). Shows model candidates awaiting a human decision with everything a reviewer needs:
the source headline, grounded quotes vs model inferences, resolved/unresolved tickers, provenance and the model used."""
import json


def _has_reviews_table(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='extraction_reviews' AND type='table'").one() is not None


def pending(db, limit=20):
    """Candidates with needs_human_review=1 and no decision (or latest decision 'needs_more_evidence')."""
    base = ("SELECT e.extraction_id, e.source_item_id, e.created_at_utc, e.model, e.confidence, e.extracted_json, "
            "i.title, i.source_id, s.source_type FROM event_extractions e "
            "JOIN source_items i USING(source_item_id) JOIN sources s ON s.source_id=i.source_id WHERE e.needs_human_review=1 ")
    if _has_reviews_table(db):
        base += ("AND COALESCE((SELECT r.decision FROM extraction_reviews r WHERE r.extraction_id=e.extraction_id "
                 "ORDER BY r.review_id DESC LIMIT 1),'needs_more_evidence')='needs_more_evidence' ")
    return db.execute(base + "ORDER BY e.extraction_id LIMIT ?", (limit,)).rows


def summarise(row):
    j = json.loads(row["extracted_json"])
    quotes = [c for c in j.get("claims", []) if c["kind"] == "quote"]
    infs = [c for c in j.get("claims", []) if c["kind"] == "inference"]
    return {"extraction_id": row["extraction_id"], "source": row["source_id"], "headline": row["title"], "model": row["model"],
            "event_type": j.get("event_type"), "band": j.get("confidence_band"),
            "tickers": [t["ticker"] for t in j.get("tickers", [])], "unresolved": j.get("unresolved_tickers", []),
            "quotes": [(c["claim_type"], c["text"]) for c in quotes], "inferences": [c["text"] for c in infs],
            "reviewable": bool(quotes),
            "text_basis": j.get("text_basis", "headline"),      # legacy candidates (before this field) were all headline-only
            "direct_companies": [d["ticker"] for d in j.get("entity_resolution", {}).get("direct", [])],
            "indirect_rules": [i.get("rule_id") or i.get("basis") for i in j.get("entity_resolution", {}).get("indirect", [])]}


def show(db, extraction_id):
    row = db.execute(
        "SELECT e.*, i.title, i.source_id, i.collected_at_utc AS item_collected, i.canonical_url, s.source_type "
        "FROM event_extractions e JOIN source_items i USING(source_item_id) JOIN sources s ON s.source_id=i.source_id "
        "WHERE e.extraction_id=?", (extraction_id,)).one()
    return row
