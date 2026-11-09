import json

import pytest

from llm.budget import Budget
from llm.providers import ProviderError, Reply, ScriptedProvider
from llm.router import Router
from tests.conftest import add_company, add_item, add_source

TEXT = "OGDC announced a final cash dividend. The Board meeting will be held on 27 November 2026."
GOOD = json.dumps({"event_type": "dividend", "tickers": ["OGDC"], "confidence_band": "medium",
                   "claims": [{"kind": "quote", "text": "OGDC announced a final cash dividend."},
                              {"kind": "inference", "text": "Shareholders may see a payout soon"}]})
BAD_NUM = json.dumps({"event_type": "dividend", "tickers": ["OGDC"], "confidence_band": "low",
                      "claims": [{"kind": "inference", "text": "Yield near 5 percent"}]})


@pytest.fixture
def env(db):
    add_source(db); add_company(db, "OGDC")
    return db, add_item(db)


def calls(db, outcome=None):
    q = "select * from llm_calls" + (f" where outcome='{outcome}'" if outcome else "")
    return db.execute(q).rows


def test_ok_path_writes_candidate_only_with_python_claim_types(env):
    db, item = env
    p = ScriptedProvider("p1", "m1", [GOOD])
    r = Router(db, [p]).extract(item, TEXT)
    assert r["outcome"] == "ok" and r["claim_types"] == ["official_statement", "model_inference"]
    row = db.execute("select * from event_extractions").one()
    j = json.loads(row["extracted_json"])
    assert row["needs_human_review"] == 1 and row["event_id"] is None and row["confidence"] == 0.6
    assert j["record_kind"] == "model_candidate" and j["tickers"][0]["company_id"] == "cmp-ogdc"
    assert db.execute("select count(*) n from events").one()["n"] == 0          # models never create events
    assert db.execute("select count(*) n from event_evidence").one()["n"] == 0  # ...or evidence
    assert calls(db)[0]["cost_usd"] == 0 and calls(db)[0]["outcome"] == "ok" and len(calls(db)[0]["prompt_sha256"]) == 64


def test_cache_hit_makes_no_provider_call(env):
    db, item = env
    p = ScriptedProvider("p1", "m1", [GOOD])
    rt = Router(db, [p])
    rt.extract(item, TEXT)
    again = rt.extract(item, TEXT)
    assert again["outcome"] == "cached" and p.calls == 1
    assert [c["outcome"] for c in calls(db)] == ["ok", "cached"]
    assert db.execute("select count(*) n from event_extractions").one()["n"] == 1


def test_restricted_source_never_sent_to_provider(db):
    add_source(db, "inv", access="restricted", stype="news_media"); add_company(db, "OGDC")
    item = add_item(db, "inv")
    p = ScriptedProvider("p1", "m1", [GOOD])
    r = Router(db, [p]).extract(item, TEXT)
    assert r["outcome"] == "refused_source" and p.calls == 0 and calls(db) == []


def test_kill_switch(env, monkeypatch):
    db, item = env
    monkeypatch.setenv("LLM_KILL_SWITCH", "1")
    p = ScriptedProvider("p1", "m1", [GOOD])
    assert Router(db, [p]).extract(item, TEXT)["outcome"] == "refused_kill_switch"
    assert p.calls == 0 and calls(db)[0]["outcome"] == "refused_kill_switch"


def test_budget_gate_then_fallback_provider(env):
    db, item = env
    p1, p2 = ScriptedProvider("p1", "m1", [GOOD]), ScriptedProvider("p2", "m2", [GOOD])
    # p1 already used its single daily call
    db.execute("INSERT INTO llm_calls(called_at_utc,provider,model,prompt_id,prompt_version,prompt_sha256,input_sha256,"
               "input_tokens,output_tokens,outcome) VALUES(strftime('%Y-%m-%dT%H:%M:%SZ','now'),'p1','m1','x','v1',?,?,10,10,'ok')",
               ("c" * 64, "d" * 64))
    r = Router(db, [p1, p2], {"p1": Budget(max_calls_per_day=1), "p2": Budget()}).extract(item, TEXT)
    assert r["outcome"] == "ok" and p1.calls == 0 and p2.calls == 1
    assert "refused_budget" in [c["outcome"] for c in calls(db)]


def test_all_providers_over_budget(env):
    db, item = env
    p = ScriptedProvider("p1", "m1", [GOOD])
    r = Router(db, [p], {"p1": Budget(max_tokens_per_day=1)}).extract(item, TEXT)
    assert r["outcome"] == "refused_budget" and p.calls == 0


def test_invalid_output_retried_once_then_ok(env):
    db, item = env
    p = ScriptedProvider("p1", "m1", [BAD_NUM, GOOD])
    r = Router(db, [p], {"p1": Budget(max_attempts_per_item=2)}).extract(item, TEXT)
    assert r["outcome"] == "ok" and p.calls == 2
    assert [c["outcome"] for c in calls(db)] == ["invalid_output", "ok"] and calls(db)[1]["attempts"] == 2


def test_persistent_invalid_output_stores_nothing(env):
    db, item = env
    p = ScriptedProvider("p1", "m1", [BAD_NUM, BAD_NUM])
    r = Router(db, [p]).extract(item, TEXT)
    assert r["outcome"] == "invalid_output"
    assert db.execute("select count(*) n from event_extractions").one()["n"] == 0


def test_rate_limited_falls_through_without_retrying_same_provider(env):
    db, item = env
    p1 = ScriptedProvider("p1", "m1", [ProviderError("rate_limited", "HTTP 429", 30)])
    p2 = ScriptedProvider("p2", "m2", [GOOD])
    r = Router(db, [p1, p2]).extract(item, TEXT)
    assert r["outcome"] == "ok" and p1.calls == 1 and p2.calls == 1
    assert calls(db, "error")[0]["provider"] == "p1"


def test_not_connected_provider_logged(env):
    db, item = env
    p = ScriptedProvider("p1", "m1", [ProviderError("not_connected", "key missing")])
    assert Router(db, [p]).extract(item, TEXT)["outcome"] == "not_connected"
    assert calls(db)[0]["outcome"] == "not_connected"


def test_hallucinated_ticker_dropped_and_flagged(env):
    db, item = env
    bad = json.dumps({"event_type": "dividend", "tickers": ["OGDC", "PPL"], "confidence_band": "high",
                      "claims": [{"kind": "quote", "text": "OGDC announced a final cash dividend."}]})
    Router(db, [ScriptedProvider("p1", "m1", [bad])]).extract(item, TEXT)
    row = db.execute("select * from event_extractions").one()
    assert json.loads(row["extracted_json"])["unresolved_tickers"] == ["PPL"]
    assert any("PPL" in x for x in json.loads(row["review_reasons_json"]))


def test_providers_have_no_database_access():
    import inspect
    from llm import providers
    src = inspect.getsource(providers).lower()
    assert "sqlite" not in src and "turso" not in src and "execute(" not in src.replace("def complete", "")
