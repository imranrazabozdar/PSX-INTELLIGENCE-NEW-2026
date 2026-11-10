"""Reproducible extraction-quality evaluation (eval@v1). Deterministic, no model calls, no writes.

controlled(sample)      : labelled SYNTHETIC cases -> precision/recall for de-duplication and entity resolution, validator accept/reject
                          accuracy, and the safety counters that must stay at zero (invented tickers, false accepts)
production(db, ...)     : read-only metrics over real candidates and stored headlines
"""
import json
import re
from itertools import combinations

from extract import dedup, registry
from extract.entities import Resolver, VERSION as ENT_VERSION
from extract.relevance import Relevance
from llm.validate import ValidationError, norm_ws, parse_json_object, validate_candidate

VERSION = "eval@v1"


def _pr(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": None if p is None else round(p, 3), "recall": None if r is None else round(r, 3)}


# ------------------------------------------------------------------ controlled sample
def build_resolver(master):
    comps, aliases, rels = {}, [], []
    by_ticker = {}
    for c in master["companies"]:
        cid = f"cmp-{c['ticker'].lower()}"
        by_ticker[c["ticker"]] = cid
        comps[cid] = {"ticker": c["ticker"], "legal_name": c["legal_name"], "sector_ids": [c["sector"]] if c["sector"] else []}
        aliases += [(cid, a["alias"], a["type"], a["confidence"]) for a in c.get("aliases", [])]
    for r in master.get("relationships", []):
        rels.append((by_ticker[r["parent"]], by_ticker.get(r["child_ticker"]) if r["child_ticker"] else None, r["child_name"], r["type"]))
    return Resolver(comps, aliases, rels, master["sectors"]), set(by_ticker)


def controlled(sample):
    res = {"eval_version": VERSION, "sample_version": sample["version"], "dedup_version": dedup.VERSION, "entities_version": ENT_VERSION}
    # --- de-duplication (pairwise)
    items = sample["dedup"]["items"]
    pred = {tuple(sorted((a["id"], b["id"]))) for a, b in combinations(items, 2)
            if dedup.fingerprint(a["title"]) and dedup.fingerprint(a["title"]) == dedup.fingerprint(b["title"])}
    exp = {tuple(sorted(p)) for p in sample["dedup"]["expected_duplicate_pairs"]}
    res["dedup"] = {**_pr(len(pred & exp), len(pred - exp), len(exp - pred)), "false_positive_pairs": sorted(pred - exp), "missed_pairs": sorted(exp - pred),
                    "stories": len(items), "stories_after_dedup": len(items) - len({x for p in pred for x in p[1:]})}
    # --- entity resolution
    resolver, known = build_resolver(sample["master"])
    d_tp = d_fp = d_fn = i_tp = i_fp = i_fn = u_ok = u_total = 0
    invented, wrong = 0, []
    for case in sample["entities"]:
        out = resolver.resolve(case["text"])
        got_d = {d["ticker"] for d in out["direct"]}
        got_i = {i["rule_id"] for i in out["indirect"] if i.get("rule_id")}
        got_u = {u["reason"] for u in out["unresolved"]}
        exp_d, exp_i, exp_u = set(case["direct"]), set(case["indirect_rules"]), set(case["unresolved"])
        d_tp += len(got_d & exp_d); d_fp += len(got_d - exp_d); d_fn += len(exp_d - got_d)
        i_tp += len(got_i & exp_i); i_fp += len(got_i - exp_i); i_fn += len(exp_i - got_i)
        u_total += len(exp_u); u_ok += len(exp_u & got_u)
        invented += len(got_d - known) + sum(len(set(i.get("companies", [])) - known) for i in out["indirect"])
        if (got_d, got_i) != (exp_d, exp_i) or not exp_u <= got_u:
            wrong.append({"text": case["text"], "direct": sorted(got_d), "indirect": sorted(got_i), "unresolved": sorted(got_u)})
    res["entities"] = {"cases": len(sample["entities"]), "direct": _pr(d_tp, d_fp, d_fn), "indirect_rules": _pr(i_tp, i_fp, i_fn),
                       "unresolved_reported": f"{u_ok}/{u_total}", "invented_tickers": invented, "disagreements": wrong}
    # --- extraction validation (what the pipeline would accept from model outputs)
    schema = registry.load_schema("event_candidate", "1")
    ok = bad_accept = bad_reject = 0
    detail = []
    for c in sample["candidates"]:
        try:
            raw = c["output"] if isinstance(c["output"], str) else json.dumps(c["output"])
            validate_candidate(parse_json_object(raw), schema, c["text"], lambda t: f"cmp-{t.lower()}" if t in known else None)
            verdict = "accept"
        except ValidationError:
            verdict = "reject"
        ok += verdict == c["expect"]
        bad_accept += verdict == "accept" and c["expect"] == "reject"
        bad_reject += verdict == "reject" and c["expect"] == "accept"
        if verdict != c["expect"]:
            detail.append({"id": c["id"], "got": verdict, "expected": c["expect"]})
    res["validation"] = {"cases": len(sample["candidates"]), "agreement": f"{ok}/{len(sample['candidates'])}", "false_accepts": bad_accept,
                         "false_rejects": bad_reject, "disagreements": detail}
    return res


# ------------------------------------------------------------------ production (read-only)
def production(db):
    spec = registry.EVENT_CANDIDATE
    resolver, relevance = Resolver.from_db(db), Relevance.from_db(db)
    cands = db.execute("SELECT e.extraction_id, e.source_item_id, e.extracted_json, i.title, i.source_id FROM event_extractions e "
                       "JOIN source_items i USING(source_item_id) WHERE e.schema_version LIKE ? ORDER BY e.extraction_id",
                       (f"{spec['schema_id']}/{spec['schema_version']}%",)).rows
    n = len(cands)
    quotes = grounded = infer = infer_digits = with_quote = useful = direct_hit = indirect_hit = unresolved_total = 0
    basis = {}
    seen_fp, dup_candidates = {}, []
    for c in cands:
        j = json.loads(c["extracted_json"])
        b = j.get("text_basis", "headline")                   # legacy candidates (before the field existed) were all headline-only
        basis[b] = basis.get(b, 0) + 1
        qs = [x for x in j["claims"] if x["kind"] == "quote"]
        quotes += len(qs)
        grounded += sum(1 for x in qs if norm_ws(x["text"]) in norm_ws(c["title"]))      # re-verified against the stored headline
        for x in j["claims"]:
            if x["kind"] == "inference":
                infer += 1
                infer_digits += bool(re.search(r"\d|%", x["text"]))
        with_quote += bool(qs)
        er = resolver.resolve(c["title"])
        direct_hit += bool(er["direct"]); indirect_hit += bool(er["indirect"]); unresolved_total += len(er["unresolved"])
        useful += bool(qs) and bool(er["direct"] or er["indirect"])
        fp = dedup.fingerprint(c["title"])
        if fp in seen_fp:
            dup_candidates.append({"source_item_id": c["source_item_id"], "duplicate_of": seen_fp[fp]})
        elif fp:
            seen_fp[fp] = c["source_item_id"]
    heads = db.execute("SELECT i.source_item_id, i.source_id, i.title FROM source_items i JOIN sources s USING(source_id) "
                       "WHERE s.access_status='verified_permitted' AND i.title IS NOT NULL ORDER BY i.source_item_id").rows
    g = dedup.group_items(heads)
    pass_items = [h for h in heads if relevance.score(h["title"], h["source_id"])["pass"]]
    passing = len(pass_items)
    gp = dedup.group_items(pass_items)                      # duplicates AMONG items that would be sent to a model
    rate = lambda a, b: None if not b else round(a / b, 3)
    return {"eval_version": VERSION, "dedup_version": dedup.VERSION, "entities_version": ENT_VERSION, "relevance_version": relevance.version,
            "candidates": {"total": n, "text_basis": basis, "with_grounded_quote": with_quote, "with_grounded_quote_rate": rate(with_quote, n),
                           "quotes": quotes, "grounded_quotes": grounded, "grounded_quote_rate": rate(grounded, quotes),
                           "inferences": infer, "inferences_with_digits": infer_digits,
                           "company_direct_match_rate": rate(direct_hit, n), "sector_commodity_match_rate": rate(indirect_hit, n),
                           "unresolved_mentions": unresolved_total,
                           "useful_event_rate": rate(useful, n), "useful_event_definition": "grounded quote AND (direct company match OR sector/commodity rule hit)",
                           "duplicate_candidates": len(dup_candidates), "model_calls_avoidable_in_past_runs": len(dup_candidates)},
            "stored_headlines": {"total": len(heads), "exact_duplicate_groups": len(g["exact"]), "duplicate_items": len(g["duplicate_of"]),
                                 "duplicate_rate": rate(len(g["duplicate_of"]), len(heads)), "near_duplicate_pairs_reported": len(g["near"]),
                                 "relevance_pass": passing, "relevance_pass_rate": rate(passing, len(heads)),
                                 "relevant_duplicate_items": len(gp["duplicate_of"]), "relevant_duplicate_rate": rate(len(gp["duplicate_of"]), passing),
                                 "model_calls_avoided_if_all_relevant_were_extracted": len(gp["duplicate_of"])}}
