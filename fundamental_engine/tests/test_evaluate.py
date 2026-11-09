import json
from pathlib import Path

import pytest

from extract import dedup, evaluate
from llm.providers import ScriptedProvider
from llm.router import Router
from tests.conftest import add_company, add_source

SAMPLE = json.loads((Path(__file__).resolve().parent / "fixtures" / "eval_sample.json").read_text(encoding="utf-8"))


def test_controlled_sample_is_reproducible_and_exact():
    a, b = evaluate.controlled(SAMPLE), evaluate.controlled(SAMPLE)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)                  # deterministic
    d = a["dedup"]
    assert (d["tp"], d["fp"], d["fn"], d["precision"], d["recall"]) == (5, 0, 1, 1.0, 0.833)
    assert d["missed_pairs"] == [(14, 15)] and d["false_positive_pairs"] == [] and (d["stories"], d["stories_after_dedup"]) == (15, 11)
    e = a["entities"]
    assert e["invented_tickers"] == 0 and e["direct"]["precision"] == 1.0 and e["direct"]["recall"] == 1.0 and e["disagreements"] == []
    assert e["indirect_rules"]["tp"] == 6 and e["unresolved_reported"] == "3/3"
    v = a["validation"]
    assert v["agreement"] == "8/8" and v["false_accepts"] == 0 and v["false_rejects"] == 0
    assert a["eval_version"] == "eval@v1" and a["dedup_version"] == "dedup@v1" and a["entities_version"] == "entities@v1"


def test_safety_counters_catch_regressions(monkeypatch):
    # if normalisation stopped unifying currency spellings, dedup recall must drop (the evaluation would show it)
    monkeypatch.setattr(dedup, "normalize_tokens", lambda t: (t or "").lower().split())
    broken = evaluate.controlled(SAMPLE)["dedup"]
    assert broken["recall"] < 0.5
    monkeypatch.undo()
    # a validator that accepted everything would show false accepts
    monkeypatch.setattr(evaluate, "validate_candidate", lambda *a, **k: ({}, []))
    assert evaluate.controlled(SAMPLE)["validation"]["false_accepts"] > 0


def test_every_fixture_expectation_is_self_consistent():
    ids = {i["id"] for i in SAMPLE["dedup"]["items"]}
    assert all(set(p) <= ids for p in SAMPLE["dedup"]["expected_duplicate_pairs"])
    tickers = {c["ticker"] for c in SAMPLE["master"]["companies"]}
    for case in SAMPLE["entities"]:
        assert set(case["direct"]) <= tickers


def seeded(db):
    add_source(db, "news", stype="news_media"); add_company(db, "OGDC")
    db.execute("INSERT INTO sectors(sector_id,scheme,name,created_at_utc) VALUES('psx-oil-gas-exploration-companies','PSX','E&P','t')")
    db.execute("INSERT INTO company_classifications(company_id,sector_id,verified_at_utc) VALUES('cmp-ogdc','psx-oil-gas-exploration-companies','t')")
    ids = {}
    for k, t in enumerate(["OGDC announces final cash dividend", "Brent crude jumps on supply worries", "Brent crude jumps on supply worries!",
                           "Pindi courts acquit most accused", "OGDC announces final cash dividend - Dawn"]):
        ids[k] = db.execute("INSERT INTO source_items(source_id,external_id,title,collected_at_utc,content_sha256) VALUES('news',?,?,?,?)",
                            (f"e{k}", t, "2026-11-09T00:00:00Z", "a" * 64)).lastrowid
    q = lambda t, kind="quote": json.dumps({"event_type": "other", "tickers": [], "confidence_band": "low", "claims": [{"kind": kind, "text": t}]})
    rt = Router(db, [ScriptedProvider("g", "m", [q("OGDC announces final cash dividend"), q("Brent crude jumps on supply worries"),
                                                 q("Brent crude jumps on supply worries!"), json.dumps({"event_type": "other", "tickers": [], "confidence_band": "low", "claims": []})])])
    for k in (0, 1, 2, 3):
        rt.extract(ids[k], db.execute("select title from source_items where source_item_id=?", (ids[k],)).one()["title"])
    return ids


def test_production_metrics_on_seeded_db(db):
    seeded(db)
    m = evaluate.production(db)
    c, h = m["candidates"], m["stored_headlines"]
    assert c["total"] == 4 and c["text_basis"] == {"headline": 4} and c["with_grounded_quote"] == 3 and c["quotes"] == 3 and c["grounded_quotes"] == 3
    assert c["grounded_quote_rate"] == 1.0 and c["inferences_with_digits"] == 0
    assert c["company_direct_match_rate"] == 0.25 and c["sector_commodity_match_rate"] == 0.5 and c["useful_event_rate"] == 0.75
    assert c["duplicate_candidates"] == 1                                              # the "!" variant of the Brent headline
    assert h["total"] == 5 and h["duplicate_items"] == 2 and h["exact_duplicate_groups"] == 2            # Brent!, OGDC - Dawn
    assert h["relevance_pass"] == 4 and h["relevant_duplicate_items"] == 2 and h["model_calls_avoided_if_all_relevant_were_extracted"] == 2


def test_production_evaluation_is_read_only(db):
    seeded(db)
    tables = ["source_items", "event_extractions", "llm_calls", "events", "event_evidence", "story_clusters", "companies"]
    before = [db.execute(f"select count(*) n from {t}").one()["n"] for t in tables]
    evaluate.production(db)
    assert [db.execute(f"select count(*) n from {t}").one()["n"] for t in tables] == before


def test_script_is_read_only_and_makes_no_model_calls():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "eval_extraction.py").read_text()
    code = (Path(__file__).resolve().parent.parent / "extract" / "evaluate.py").read_text()
    for bad in ("INSERT", "UPDATE", "DELETE", "complete(", "requests"):
        assert bad not in src and bad not in code
