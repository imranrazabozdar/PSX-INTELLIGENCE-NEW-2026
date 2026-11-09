"""Batch paths. All are dry-run by default; every item is gated by source eligibility AND the source's retention_mode.

  news/event extraction (Groq first): pending verified_permitted items -> headline/excerpt text -> Router -> candidates
  long documents / financial statements (Gemini): chunk -> per-chunk Router calls (cached per chunk hash) -> candidates
"""
from core.config import LLM_ELIGIBLE_ACCESS_STATUS
from extract.chunking import chunk_text, est_tokens, variant_tag
from extract.text import item_text
from llm.router import PROMPT_VERSION_TAG, SCHEMA_VERSION_TAG


def pending_items(db, spec, limit=10):
    """Items from verified_permitted sources that have no candidate yet for this schema/prompt version."""
    ph = ",".join("?" * len(LLM_ELIGIBLE_ACCESS_STATUS))
    return db.execute(
        f"SELECT i.source_item_id, i.source_id, i.title, i.permitted_excerpt, s.retention_mode, s.source_type "
        f"FROM source_items i JOIN sources s USING(source_id) WHERE s.access_status IN ({ph}) "
        f"AND NOT EXISTS (SELECT 1 FROM event_extractions e WHERE e.source_item_id=i.source_item_id "
        f"AND e.schema_version LIKE ? AND e.prompt_version=?) "
        f"ORDER BY i.collected_at_utc DESC, i.source_item_id DESC LIMIT ?",
        (*LLM_ELIGIBLE_ACCESS_STATUS, SCHEMA_VERSION_TAG(spec) + "%", PROMPT_VERSION_TAG(spec), limit)).rows


def run_news_batch(router, db, limit=10, dry_run=True, min_chars=20, prefilter=None, scan_limit=300):
    """prefilter: extract.relevance.Relevance (or None). With a prefilter the pending window scanned is `scan_limit` items
    (cheap, no model), and the first `limit` RELEVANT ones are sent, so irrelevant headlines cannot starve relevant older ones."""
    rows = pending_items(db, router.spec, scan_limit if prefilter else limit)
    plan, results, skipped = [], [], 0
    for r in rows:
        text = item_text(r["title"], r["permitted_excerpt"], r["retention_mode"])
        if len(text) < min_chars:
            continue
        rel = prefilter.score(text, r["source_id"]) if prefilter else None
        if rel is not None and not rel["pass"]:
            skipped += 1
            continue
        if len(plan) >= limit:
            break
        plan.append({"source_item_id": r["source_item_id"], "source_id": r["source_id"], "chars": len(text),
                     "est_tokens": est_tokens(text) + est_tokens(router.prompt), "text_basis": r["retention_mode"],
                     **({"relevance_score": rel["score"], "relevance": rel["reasons"]} if rel else {})})
        if not dry_run:
            res = router.extract(r["source_item_id"], text)
            results.append(res["outcome"])
            if res["outcome"] in ("refused_kill_switch", "refused_budget"):
                break
    summary = {}
    for o in results:
        summary[o] = summary.get(o, 0) + 1
    return {"dry_run": dry_run, "scanned": len(rows), "skipped_irrelevant": skipped, "planned": len(plan),
            "prefilter": prefilter.version if prefilter else None, "outcomes": summary, "plan": plan}


def run_long_document(router, source_item_id, text, max_chars=20000, overlap_chars=500, max_chunks=5, dry_run=True):
    """Chunk a long document and extract each chunk separately (quotes are grounded per chunk). Stops at max_chunks per run
    so a single big report cannot burn a day's free budget; re-running continues (earlier chunks are cache hits)."""
    chunks = chunk_text(text, max_chars, overlap_chars)
    plan = [{"chunk": c["index"], "of": c["of"], "chars": len(c["text"]), "est_tokens": est_tokens(c["text"]) + est_tokens(router.prompt)}
            for c in chunks]
    out = {"dry_run": dry_run, "chunks": len(chunks), "plan": plan, "outcomes": []}
    if dry_run:
        return out
    done = 0
    for c in chunks:
        res = router.extract(source_item_id, c["text"], variant=variant_tag(c))
        out["outcomes"].append((c["index"], res["outcome"]))
        if res["outcome"] != "cached":
            done += 1
        if res["outcome"] in ("refused_kill_switch", "refused_budget", "not_connected") or done >= max_chunks:
            break
    out["remaining_chunks"] = len(chunks) - len(out["outcomes"])
    return out
