"""Batch paths. All are dry-run by default; every item is gated by source eligibility AND the source's retention_mode.

  news/event extraction (Groq first): pending verified_permitted items -> headline/excerpt text -> Router -> candidates
  long documents / financial statements (Gemini): chunk -> per-chunk Router calls (cached per chunk hash) -> candidates
"""
from core.config import LLM_ELIGIBLE_ACCESS_STATUS
from extract.chunking import chunk_text, est_tokens, variant_tag
from extract import dedup
from extract.text import item_text, item_text_basis
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


def _extracted_titles(db, spec):
    """Items that already have a candidate for this schema/prompt version (earliest first): the dedup baseline."""
    return db.execute(
        "SELECT i.source_item_id, i.source_id, i.title FROM source_items i WHERE EXISTS (SELECT 1 FROM event_extractions e "
        "WHERE e.source_item_id=i.source_item_id AND e.schema_version LIKE ? AND e.prompt_version=?) ORDER BY i.source_item_id",
        (SCHEMA_VERSION_TAG(spec) + "%", PROMPT_VERSION_TAG(spec))).rows


def run_news_batch(router, db, limit=10, dry_run=True, min_chars=20, prefilter=None, scan_limit=300, dedupe=True, vault_root=None):
    """prefilter: extract.relevance.Relevance (or None). dedupe: skip EXACT duplicate headlines (same normalised fingerprint) of an
    item that already has a candidate or was already queued in this batch; near-duplicates are only reported. Originals are never
    modified. vault_root: when given, hash-verified acquired full text is used for sources whose registry retention permits it."""
    rows = pending_items(db, router.spec, scan_limit if (prefilter or dedupe) else limit)
    baseline = _extracted_titles(db, router.spec) if dedupe else []
    plan, results, skipped, dups = [], [], 0, []
    seen_fp = {dedup.fingerprint(x["title"]): x["source_item_id"] for x in baseline if dedup.fingerprint(x["title"])}
    for r in rows:
        acquired = None
        if vault_root is not None and r["retention_mode"] == "full_text_permitted":
            from sources.acquire import load_acquired
            acquired = (load_acquired(vault_root, r["source_item_id"]) or {}).get("text")
        text, basis = item_text_basis(r["title"], r["permitted_excerpt"], r["retention_mode"], acquired)
        if len(text) < min_chars:
            continue
        rel = prefilter.score(text, r["source_id"]) if prefilter else None
        if rel is not None and not rel["pass"]:
            skipped += 1
            continue
        if dedupe and basis == "headline":
            fp = dedup.fingerprint(r["title"])
            if fp and fp in seen_fp:
                dups.append({"source_item_id": r["source_item_id"], "source_id": r["source_id"], "duplicate_of": seen_fp[fp]})
                continue
            if fp:
                seen_fp[fp] = r["source_item_id"]
        if len(plan) >= limit:
            break
        plan.append({"source_item_id": r["source_item_id"], "source_id": r["source_id"], "chars": len(text), "text_basis": basis,
                     "est_tokens": est_tokens(text) + est_tokens(router.prompt), "retention": r["retention_mode"],
                     **({"relevance_score": rel["score"], "relevance": rel["reasons"]} if rel else {})})
        if not dry_run:
            if basis == "full_text" and len(text) > 12000:
                res = run_long_document(router, r["source_item_id"], text, dry_run=False, text_basis="full_text")
                results.append("ok" if all(o in ("ok", "cached") for _, o in res["outcomes"]) else res["outcomes"][-1][1])
            else:
                res = router.extract(r["source_item_id"], text, text_basis=basis)
                results.append(res["outcome"])
            if results[-1] in ("refused_kill_switch", "refused_budget"):
                break
    summary = {}
    for o in results:
        summary[o] = summary.get(o, 0) + 1
    near = []
    if dedupe and plan:
        ids = {p["source_item_id"] for p in plan}
        order = [{"source_item_id": x["source_item_id"], "source_id": x["source_id"], "title": x["title"]} for x in baseline] + \
                [{"source_item_id": r["source_item_id"], "source_id": r["source_id"], "title": r["title"]} for r in rows if r["source_item_id"] in ids]
        near = [{"a": a, "b": b, "jaccard": s_["jaccard"]} for a, b, s_ in dedup.group_items(order)["near"] if a in ids or b in ids]
    return {"dry_run": dry_run, "scanned": len(rows), "skipped_irrelevant": skipped, "duplicates_skipped": len(dups), "model_calls_avoided": len(dups),
            "duplicates": dups[:20], "near_duplicates_reported": near[:20], "planned": len(plan), "dedupe": dedup.VERSION if dedupe else None,
            "prefilter": prefilter.version if prefilter else None, "outcomes": summary, "plan": plan}


def run_long_document(router, source_item_id, text, max_chars=20000, overlap_chars=500, max_chunks=5, dry_run=True, text_basis="full_text"):
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
        res = router.extract(source_item_id, c["text"], variant=variant_tag(c), text_basis=text_basis)
        out["outcomes"].append((c["index"], res["outcome"]))
        if res["outcome"] != "cached":
            done += 1
        if res["outcome"] in ("refused_kill_switch", "refused_budget", "not_connected") or done >= max_chunks:
            break
    out["remaining_chunks"] = len(chunks) - len(out["outcomes"])
    return out
