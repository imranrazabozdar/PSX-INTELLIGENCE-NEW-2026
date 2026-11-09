"""Provider compatibility suite.

OFFLINE (always runs): config validation, request shape per configured provider, response parsing, error mapping,
secret redaction, rate-limit fallback + cooldown, all through an injected fake HTTP session (no network, no keys).
LIVE (opt-in): `RUN_LIVE_LLM_TESTS=1 GROQ_API_KEY=... pytest -m live` validates keys, connectivity and structured JSON
extraction against the real endpoint. Live tests spend free-tier quota and are skipped otherwise.
"""
import json
import os
from pathlib import Path

import pytest
import requests

from llm import config as cfgmod
from llm.budget import Budget
from llm.providers import OpenAICompatProvider, ProviderError
from llm.router import Router
from tests.conftest import add_company, add_item, add_source

CFG = cfgmod.load_config()


def order(providers):
    """provider names in routing order, de-duplicated (a provider may expand to several model routes)"""
    return list(dict.fromkeys(p.name for p in providers))

NAMES = [p["name"] for p in CFG["providers"]]
TEXT = "OGDC announced a final cash dividend. The Board meeting will be held on 27 November 2026."
GOOD = json.dumps({"event_type": "dividend", "tickers": ["OGDC"], "confidence_band": "medium",
                   "claims": [{"kind": "quote", "text": "OGDC announced a final cash dividend."},
                              {"kind": "inference", "text": "Shareholders may see a payout soon"}]})


class FakeResp:
    def __init__(self, status=200, body=None, headers=None, text_content=None):
        self.status_code, self.headers = status, headers or {}
        self._body = body if body is not None else {
            "choices": [{"message": {"content": text_content if text_content is not None else GOOD}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40}}

    def json(self):
        if self._body == "BADJSON":
            raise ValueError("bad json")
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.queue, self.calls = list(responses), []

    def post(self, url, **kw):
        self.calls.append({"url": url, **kw})
        r = self.queue.pop(0) if self.queue else FakeResp()
        if isinstance(r, Exception):
            raise r
        return r


def make(name, session, **over):
    p = {x["name"]: x for x in CFG["providers"]}[name]
    return OpenAICompatProvider(name, p["base_url"], p["model"], p["api_key_env"], p.get("max_output_tokens", 800),
                                p.get("timeout_s", 60), p.get("json_mode", False), p.get("extra_headers"), session,
                                p.get("extra_body"), **over) \
        if not over else OpenAICompatProvider(name, p["base_url"], p["model"], p["api_key_env"], session=session, **over)


@pytest.fixture
def keys(monkeypatch):
    for p in CFG["providers"]:
        monkeypatch.setenv(p["api_key_env"], f"test-key-{p['name']}-0123456789")


@pytest.fixture
def env(db):
    add_source(db); add_company(db, "OGDC")
    return db, add_item(db)


# ------------------------------------------------------------------ config
def test_config_valid_and_all_three_providers_unlocked():
    assert set(NAMES) >= {"groq", "gemini", "openrouter"}
    by = {p["name"]: p for p in CFG["providers"]}
    g = by["groq"]
    assert g["enabled"] and g["model_verified"] and g["terms_reviewed_utc"] == "2026-11-09" and g["model"] == "openai/gpt-oss-20b"
    gm = by["gemini"]
    assert gm["enabled"] and gm["model_verified"] and gm["terms_reviewed_utc"] == "2026-11-09" and gm["model"] == "gemini-3.5-flash-lite" and [m["id"] for m in gm["models"] if m["verified"]] == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    assert gm["extra_body"] == {"reasoning_effort": "low"} and gm["max_output_tokens"] >= 4000 and gm["timeout_s"] >= 120
    orr = by["openrouter"]
    assert orr["enabled"] and orr["model_verified"] and orr["terms_reviewed_utc"] == "2026-11-09" and orr["max_calls_per_day"] <= 40
    assert [m["id"] for m in orr["models"] if m["verified"]] == ["google/gemma-4-26b-a4b-it:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "openrouter/free"]
    assert "nvidia/nemotron-3.5-lightning:free" not in [m["id"] for m in orr["models"]]   # returned empty content in the probe
    assert [m["id"] for m in orr["models"] if not m["verified"]] == ["google/gemma-4-31b-it:free"]
    raw = (Path(cfgmod.DEFAULT_PATH)).read_text()
    assert not cfgmod._SECRET_VALUE.search(raw)
    providers, budgets = cfgmod.build()                      # production rules: only the reviewed+verified provider is usable
    assert [(p.name, p.model) for p in providers] == [
        ("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-3.5-flash-lite"), ("gemini", "gemini-3.1-flash-lite"),
        ("openrouter", "google/gemma-4-26b-a4b-it:free"), ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"), ("openrouter", "openrouter/free")]
    assert providers[-1].model == "openrouter/free"            # the auto-router (unpredictable identity) is the LAST resort
    assert list(budgets) == ["groq", "gemini", "openrouter"]    # routes of one provider share ONE budget
    assert order(cfgmod.build("long_document_extraction")[0]) == ["gemini", "openrouter"]
    assert order(cfgmod.build("financial_line_items")[0]) == ["gemini"]


def enable_all(cfg, verified=False):
    for p in cfg["providers"]:
        p["enabled"] = True
        for m in p.get("models", []):
            m["enabled"] = True
            m["verified"] = verified
        p["model_verified"], p["terms_reviewed_utc"] = (True, "2026-11-10") if verified else (False, None)
    return cfg


def test_build_requires_enabled_and_review(tmp_path):
    cfg = enable_all(json.loads(Path(cfgmod.DEFAULT_PATH).read_text()))
    f = tmp_path / "c.json"; f.write_text(json.dumps(cfg))
    assert cfgmod.build(path=f)[0] == []                    # enabled but not reviewed/verified -> still refused
    providers, budgets = cfgmod.build(path=f, require_review=False)
    assert order(providers) == ["groq", "gemini", "openrouter"] and budgets["groq"].max_calls_per_day == 100
    assert order(cfgmod.build("long_document_extraction", f, False)[0]) == ["gemini", "openrouter"]
    assert order(cfgmod.build("financial_line_items", f, False)[0]) == ["gemini"]
    f.write_text(json.dumps(enable_all(cfg, verified=True)))
    assert order(cfgmod.build(path=f)[0]) == ["groq", "gemini", "openrouter"]


@pytest.mark.parametrize("mutate,msg", [
    (lambda c: c["providers"][0].update(api_key="sk-abcdefghijkl"), "secret-like"),
    (lambda c: c["providers"][0].update(data_use_notes="key gsk_abcdefghijklmnop"), "secret"),
    (lambda c: c["providers"][0].update(base_url="http://insecure.example"), "https"),
    (lambda c: c["providers"][0].update(api_key_env="lowercase"), "UPPER_SNAKE"),
    (lambda c: c["tasks"].update(news_event_extraction=["nope"]), "unknown provider"),
    (lambda c: c["providers"].append(dict(c["providers"][0])), "duplicate"),
    (lambda c: c["providers"][0].pop("model"), "missing"),
])
def test_config_rejects_bad_config(tmp_path, mutate, msg):
    cfg = json.loads(Path(cfgmod.DEFAULT_PATH).read_text()); mutate(cfg)
    f = tmp_path / "bad.json"; f.write_text(json.dumps(cfg))
    with pytest.raises(cfgmod.ConfigError, match=msg):
        cfgmod.load_config(f)


def test_status_never_leaks_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "super-secret-value")
    st = cfgmod.status()
    assert {s["name"]: s["key_present"] for s in st}["groq"] is True and "super-secret-value" not in json.dumps(st)
    by = {s["name"]: s for s in st}
    assert by["groq"]["usable_in_production"] is True       # key present (set above) + enabled + reviewed + verified
    assert by["gemini"]["usable_in_production"] is False        # unlocked in config, but no key in this environment
    assert by["openrouter"]["usable_in_production"] is False


# ------------------------------------------------------------------ request shape (per configured provider)
@pytest.mark.parametrize("name", NAMES)
def test_request_shape(name, keys):
    sess = FakeSession()
    prov = make(name, sess)
    prov.complete("SYSTEM PROMPT", "document text")
    call = sess.calls[0]
    pcfg = {x["name"]: x for x in CFG["providers"]}[name]
    assert call["url"] == pcfg["base_url"].rstrip("/") + "/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer test-key-{name}-0123456789"
    body = call["json"]
    assert body["model"] == pcfg["model"] and body["temperature"] == 0 and body["max_tokens"] == pcfg.get("max_output_tokens", 800)
    assert [m["role"] for m in body["messages"]] == ["system", "user"] and "untrusted" in body["messages"][1]["content"]
    assert ("response_format" in body) == pcfg.get("json_mode", False)
    for k, v in pcfg.get("extra_body", {}).items():             # provider-specific fields come from config
        assert body[k] == v
    assert "test-key" not in json.dumps(body)                  # key only in the header
    for k, v in pcfg.get("extra_headers", {}).items():
        assert call["headers"][k] == v


def test_missing_key_means_no_http_call(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    sess = FakeSession()
    with pytest.raises(ProviderError) as e:
        make("groq", sess).complete("s", "t")
    assert e.value.kind == "not_connected" and sess.calls == []


# ------------------------------------------------------------------ response parsing and error mapping
def test_usage_and_fallback_token_estimate(keys):
    r = make("groq", FakeSession(FakeResp())).complete("s", "t")
    assert (r.input_tokens, r.output_tokens) == (120, 40)
    body = {"choices": [{"message": {"content": "x" * 40}}]}
    r = make("groq", FakeSession(FakeResp(body=body))).complete("sys", "text")
    assert r.output_tokens == 10 and r.input_tokens == (len("text") + len("sys")) // 4


@pytest.mark.parametrize("resp,kind", [
    (FakeResp(429, headers={"Retry-After": "17"}), "rate_limited"),
    (FakeResp(401), "auth"), (FakeResp(403), "auth"),
    (FakeResp(500), "error"), (FakeResp(400), "error"),
    (FakeResp(502), "overloaded"), (FakeResp(503), "overloaded"), (FakeResp(504), "overloaded"),
    (FakeResp(body="BADJSON"), "error"), (FakeResp(body={"nope": 1}), "error"),
    (FakeResp(text_content="   "), "error"),
    (requests.ConnectionError("boom test-key-groq-0123456789"), "error"),
    (requests.Timeout("slow"), "error"),
])
def test_error_mapping_and_redaction(resp, kind, keys):
    with pytest.raises(ProviderError) as e:
        make("groq", FakeSession(resp)).complete("s", "t")
    assert e.value.kind == kind and "test-key-groq-0123456789" not in str(e.value)
    if kind == "rate_limited" and isinstance(resp, FakeResp) and resp.headers:
        assert e.value.retry_after == 17


# ------------------------------------------------------------------ structured JSON through the router
def test_fenced_json_extraction_end_to_end(env, keys):
    db, item = env
    sess = FakeSession(FakeResp(text_content="```json\n" + GOOD + "\n```"))
    r = Router(db, [make("groq", sess)], {"groq": Budget()}).extract(item, TEXT)
    assert r["outcome"] == "ok" and r["claim_types"] == ["official_statement", "model_inference"]
    row = db.execute("select * from llm_calls").one()
    assert (row["provider"], row["input_tokens"], row["output_tokens"], row["cost_usd"]) == ("groq", 120, 40, 0)


def test_free_text_answer_is_invalid_output_not_a_write(env, keys):
    db, item = env
    sess = FakeSession(FakeResp(text_content="Sure! OGDC will pay 5 rupees."), FakeResp(text_content="still prose"))
    r = Router(db, [make("groq", sess)], {"groq": Budget()}).extract(item, TEXT)
    assert r["outcome"] == "invalid_output" and db.execute("select count(*) n from event_extractions").one()["n"] == 0
    assert [c["outcome"] for c in db.execute("select outcome from llm_calls").rows] == ["invalid_output"] * 2


# ------------------------------------------------------------------ rate-limit fallback, cooldown, auth, key safety
def test_rate_limit_fallback_then_cooldown_skips_provider(env, keys):
    db, item = env
    item2 = add_item(db, ext="x2")
    s1, s2 = FakeSession(FakeResp(429, headers={"Retry-After": "120"})), FakeSession(FakeResp(), FakeResp())
    clock = [1000.0]
    rt = Router(db, [make("groq", s1), make("gemini", s2)], {"groq": Budget(), "gemini": Budget()}, mono=lambda: clock[0])
    assert rt.extract(item, TEXT)["outcome"] == "ok"
    assert len(s1.calls) == 1 and len(s2.calls) == 1
    clock[0] += 30                                           # still inside the provider's Retry-After window
    assert rt.extract(item2, TEXT)["outcome"] == "ok" and len(s1.calls) == 1       # groq not hammered
    assert db.execute("select error from llm_calls where provider='groq'").one()["error"].startswith("rate_limited")
    clock[0] += 200                                          # window over: groq is tried again
    item3 = add_item(db, ext="x3"); s1.queue.append(FakeResp())
    assert rt.extract(item3, TEXT)["outcome"] == "ok" and len(s1.calls) == 2


def test_auth_failure_logged_as_not_connected_and_falls_through(env, keys):
    db, item = env
    r = Router(db, [make("groq", FakeSession(FakeResp(401))), make("gemini", FakeSession(FakeResp()))]).extract(item, TEXT)
    assert r["outcome"] == "ok"
    assert [c["outcome"] for c in db.execute("select outcome from llm_calls order by call_id").rows] == ["not_connected", "ok"]


def test_all_providers_failing_returns_last_failure(env, keys):
    db, item = env
    r = Router(db, [make("groq", FakeSession(FakeResp(500))), make("gemini", FakeSession(requests.Timeout("t")))]).extract(item, TEXT)
    assert r["outcome"] == "error" and db.execute("select count(*) n from event_extractions").one()["n"] == 0


def test_key_never_reaches_database(env, keys):
    db, item = env
    leaky = requests.ConnectionError("failed auth with test-key-groq-0123456789")
    Router(db, [make("groq", FakeSession(leaky)), make("gemini", FakeSession(FakeResp()))]).extract(item, TEXT)
    dump = json.dumps([db.execute(f"select * from {t}").rows for t in ("llm_calls", "event_extractions")], default=str)
    assert "test-key" not in dump


def test_restricted_source_blocked_even_with_working_provider(db, keys):
    add_source(db, "inv", "restricted", "news_media"); add_company(db, "OGDC")
    sess = FakeSession(FakeResp())
    r = Router(db, [make("groq", sess)]).extract(add_item(db, "inv"), TEXT)
    assert r["outcome"] == "refused_source" and sess.calls == []


def test_kill_switch_blocks_http(env, keys, monkeypatch):
    db, item = env
    monkeypatch.setenv("LLM_KILL_SWITCH", "true")
    sess = FakeSession(FakeResp())
    assert Router(db, [make("groq", sess)]).extract(item, TEXT)["outcome"] == "refused_kill_switch" and sess.calls == []


def test_from_config_builds_router(env, tmp_path, keys):
    db, item = env
    cfg = enable_all(json.loads(Path(cfgmod.DEFAULT_PATH).read_text()))
    f = tmp_path / "c.json"; f.write_text(json.dumps(cfg))
    rt = Router.from_config(db, path=f, require_review=False)
    assert order(rt.providers) == ["groq", "gemini", "openrouter"]
    for p in rt.providers:
        p.session = FakeSession(FakeResp())
    assert rt.extract(item, TEXT)["outcome"] == "ok"


# ------------------------------------------------------------------ LIVE (opt-in): keys, connectivity, structured JSON
def _live_ready(name):
    env_name = {x["name"]: x for x in CFG["providers"]}[name]["api_key_env"]
    return os.environ.get("RUN_LIVE_LLM_TESTS") == "1" and bool(os.environ.get(env_name))


@pytest.mark.live
@pytest.mark.parametrize("name", NAMES)
def test_live_key_connectivity_and_structured_json(name, db):
    if not _live_ready(name):
        pytest.skip(f"live test for {name}: set RUN_LIVE_LLM_TESTS=1 and the provider's key env var")
    add_source(db); add_company(db, "OGDC"); item = add_item(db)
    pcfg = {x["name"]: x for x in CFG["providers"]}[name]
    prov = OpenAICompatProvider(name, pcfg["base_url"], pcfg["model"], pcfg["api_key_env"], pcfg.get("max_output_tokens", 800),
                                pcfg.get("timeout_s", 60), pcfg.get("json_mode", False), pcfg.get("extra_headers"), None, pcfg.get("extra_body"))
    r = Router(db, [prov], {name: Budget(max_calls_per_day=3)}).extract(item, TEXT)
    assert r["outcome"] in ("ok", "invalid_output"), r      # reachable + key accepted; invalid_output = reachable but model misbehaved
    assert r["outcome"] == "ok", f"{name} reached but did not return schema-valid, grounded JSON: {r}"
    assert "official_statement" in r["claim_types"]


# ------------------------------------------------------------------ Gemini-specific
def test_fallback_order_groq_then_gemini_then_openrouter(env, keys):
    db, item = env
    item2 = add_item(db, ext="x2")
    s_groq, s_gem = FakeSession(FakeResp(429, headers={"Retry-After": "60"})), FakeSession(FakeResp(503))
    s_or = FakeSession(FakeResp(), FakeResp())
    provs = [make("groq", s_groq), make("gemini", s_gem), make("openrouter", s_or)]
    rt = Router(db, provs, {n: Budget() for n in ("groq", "gemini", "openrouter")}, mono=lambda: 0.0)
    assert rt.extract(item, TEXT)["outcome"] == "ok"
    assert (len(s_groq.calls), len(s_gem.calls), len(s_or.calls)) == (1, 1, 1)       # tried in order, each once
    assert [r["provider"] for r in db.execute("select provider from llm_calls order by call_id").rows] == ["groq", "gemini", "openrouter"]
    assert rt.extract(item2, TEXT)["outcome"] == "ok" and len(s_groq.calls) == 1      # groq cooling down; gemini overloaded -> cooling down too
    assert len(s_gem.calls) == 1 and len(s_or.calls) == 2


def test_gemini_request_uses_configured_long_timeout_and_extra_body(keys):
    sess = FakeSession()
    prov = cfgmod.build("financial_line_items", session=sess)[0][0]
    prov.complete("sys", "x" * 150_000)                      # ~150k chars (~37k tokens) payload
    call = sess.calls[0]
    assert call["timeout"] == 120 and call["json"]["model"] == "gemini-3.5-flash-lite" and call["json"]["reasoning_effort"] == "low"
    assert call["json"]["max_tokens"] == 4000 and "x" * 150_000 in call["json"]["messages"][1]["content"]    # sent intact, not truncated
    assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


FIN_TEXT = ("Statement of Profit or Loss (Rupees in thousand)\n\nRevenue 2026 12,345,678 2025 10,111,222\n\n"
            "Profit after tax 2026 (1,250) 2025 3,400")


@pytest.mark.live
def test_live_gemini_financial_line_items(db):
    """Live: Gemini finds line items; PYTHON parses the numbers. Synthetic statement text (no third-party content)."""
    if not _live_ready("gemini"):
        pytest.skip("live test for gemini: set RUN_LIVE_LLM_TESTS=1 and GEMINI_API_KEY")
    from extract import registry
    add_source(db, "report", stype="exchange"); item = add_item(db, "report", "r1")
    provs, budgets = cfgmod.build("financial_line_items")
    rt = Router(db, provs, budgets, spec=registry.FINANCIAL_LINE_ITEMS)
    r = rt.extract(item, FIN_TEXT)
    assert r["outcome"] == "ok", r
    j = json.loads(db.execute("select extracted_json from event_extractions").one()["extracted_json"])
    got = {(i["label"], i["period"]): i["value_parsed"] for i in j["items"]}
    assert got.get(("Revenue", "2026")) == "12345678" and got.get(("Profit after tax", "2026")) == "-1250", got


# ------------------------------------------------------------------ Phase 3: the full cascade, built from the real config
class HostSession:
    """Dispatches by URL host so one session can stand in for all three providers."""
    def __init__(self, **by_host):
        self.by_host, self.calls = {k: list(v) for k, v in by_host.items()}, []

    def post(self, url, **kw):
        host = next(h for h in self.by_host if h in url)
        self.calls.append((host, kw["json"]["model"]))
        q = self.by_host[host]
        r = q.pop(0) if q else FakeResp()
        if isinstance(r, Exception):
            raise r
        return r


@pytest.mark.parametrize("groq_fail,gemini_fail", [
    (FakeResp(429, headers={"Retry-After": "60"}), FakeResp(503)),       # rate limit then capacity overload
    (FakeResp(503), FakeResp(502)),
    (requests.Timeout("t"), FakeResp(429)),
    (FakeResp(401), FakeResp(504)),
])
def test_full_cascade_fails_over_to_openrouter(env, keys, groq_fail, gemini_fail):
    db, item = env
    sess = HostSession(**{"groq.com": [groq_fail], "googleapis.com": [gemini_fail, gemini_fail], "openrouter.ai": [FakeResp()]})
    provs, budgets = cfgmod.build("news_event_extraction", session=sess)
    r = Router(db, provs, budgets, mono=lambda: 0.0).extract(item, TEXT)
    assert r["outcome"] == "ok"
    assert [h for h, _ in sess.calls] == ["groq.com", "googleapis.com", "googleapis.com", "openrouter.ai"]   # every earlier route tried once, in order
    assert sess.calls[-1][1] == "google/gemma-4-26b-a4b-it:free"
    assert db.execute("select model from event_extractions").one()["model"] == "google/gemma-4-26b-a4b-it:free"


def test_cascade_continues_through_openrouter_models_then_gives_up(env, keys):
    db, item = env
    sess = HostSession(**{"groq.com": [FakeResp(429)], "googleapis.com": [FakeResp(503)] * 2, "openrouter.ai": [FakeResp(429), FakeResp(503), FakeResp(500)]})
    provs, budgets = cfgmod.build("news_event_extraction", session=sess)
    r = Router(db, provs, budgets, mono=lambda: 0.0).extract(item, TEXT)
    assert r["outcome"] == "error" and db.execute("select count(*) n from event_extractions").one()["n"] == 0
    assert [m for h, m in sess.calls if h == "openrouter.ai"] == ["google/gemma-4-26b-a4b-it:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "openrouter/free"]
    assert db.execute("select count(*) n from llm_calls where outcome='error'").one()["n"] == 6       # each failed route logged once


def test_served_model_recorded_for_auto_router(env, keys):
    db, item = env
    body = {"model": "cohere/north-mini-code:free", "choices": [{"message": {"content": GOOD}}], "usage": {"prompt_tokens": 90, "completion_tokens": 30}}
    prov = OpenAICompatProvider("openrouter", "https://openrouter.ai/api/v1", "openrouter/free", "OPENROUTER_API_KEY", session=FakeSession(FakeResp(body=body)))
    assert Router(db, [prov]).extract(item, TEXT)["outcome"] == "ok"
    row = db.execute("select model,provenance_json from event_extractions").one()
    assert row["model"] == "openrouter/free" and json.loads(row["provenance_json"])["served_model"] == "cohere/north-mini-code:free"
    # a normal model whose served id equals the configured id adds no noise
    prov2 = OpenAICompatProvider("openrouter", "https://openrouter.ai/api/v1", "google/gemma-4-26b-a4b-it:free", "OPENROUTER_API_KEY",
                                 session=FakeSession(FakeResp(body={**body, "model": "google/gemma-4-26b-a4b-it:free"})))
    item2 = add_item(db, ext="x2")
    Router(db, [prov2]).extract(item2, TEXT)
    pj = json.loads(db.execute("select provenance_json from event_extractions where source_item_id=?", (item2,)).one()["provenance_json"])
    assert "served_model" not in pj


def test_empty_completion_from_free_model_counts_as_error_not_success(env, keys):
    db, item = env
    empty = FakeResp(body={"model": "nvidia/nemotron-3.5-lightning:free", "choices": [{"message": {"content": ""}}]})
    prov = OpenAICompatProvider("openrouter", "https://openrouter.ai/api/v1", "nvidia/nemotron-3.5-lightning:free", "OPENROUTER_API_KEY", session=FakeSession(empty))
    assert Router(db, [prov]).extract(item, TEXT)["outcome"] == "error"
