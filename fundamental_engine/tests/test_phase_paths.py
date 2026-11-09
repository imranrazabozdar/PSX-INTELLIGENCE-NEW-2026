"""Phase 1 (Groq news/event extraction), Phase 2 (Gemini long documents + financial line items), Phase 3 (OpenRouter
per-model fallback): offline behaviour tests through scripted/fake providers."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from extract import registry
from extract.chunking import chunk_text, variant_tag
from extract.numbers import parse_number
from extract.pipeline import pending_items, run_long_document, run_news_batch
from extract.text import item_text
from llm import config as cfgmod
from llm.budget import Budget
from llm.providers import OpenAICompatProvider, ProviderError, Reply, ScriptedProvider
from llm.router import Router
from tests.conftest import add_company, add_source
from tests.test_provider_compat import FakeResp, FakeSession, enable_all


def item(db, source="news", ext="n1", title="OGDC announces final cash dividend for FY2026", excerpt=None):
    return db.execute("INSERT INTO source_items(source_id,external_id,title,permitted_excerpt,collected_at_utc,content_sha256) "
                      "VALUES(?,?,?,?,'2026-11-09T00:00:00Z',?)", (source, ext, title, excerpt, "a" * 64)).lastrowid


@pytest.fixture
def news(db):
    add_source(db, "news", stype="news_media"); add_company(db, "OGDC")
    db.execute("UPDATE sources SET retention_mode='metadata_only' WHERE source_id='news'")
    return db


EVENT_OK = json.dumps({"event_type": "dividend", "tickers": ["OGDC"], "confidence_band": "medium",
                       "claims": [{"kind": "quote", "text": "OGDC announces final cash dividend for FY2026"},
                                  {"kind": "inference", "text": "Shareholders may expect a payout"}]})


# ------------------------------------------------------------------ Phase 1: Groq news/event extraction
def test_headline_only_text_for_metadata_only_sources():
    assert item_text("  Big   headline ", "EXCERPT SHOULD NOT LEAK", "metadata_only") == "Big headline"
    assert item_text("H", "excerpt", "excerpt") == "H\nexcerpt"


def test_pending_items_only_eligible_and_not_done(news):
    add_source(news, "restricted_src", "restricted", "news_media")
    a, b = item(news, ext="a"), item(news, ext="b")
    item(news, "restricted_src", "c")
    news.execute("INSERT INTO event_extractions(source_item_id,schema_version,prompt_version,model,extracted_json,"
                 "confidence_explanation,needs_human_review,review_reasons_json,provenance_json,created_at_utc) "
                 "VALUES(?,?,?,?,?,?,1,'[]','{}','t')", (a, "event_candidate/1", "event_candidate@v1", "m", "{}", "x"))
    ids = [r["source_item_id"] for r in pending_items(news, registry.EVENT_CANDIDATE)]
    assert ids == [b]


def test_dry_run_sends_nothing_and_live_sends_headline_only(news):
    item(news, ext="a", excerpt="STORED EXCERPT")
    seen = []

    class Spy(ScriptedProvider):
        def complete(self, system_prompt, user_text, timeout=60):
            seen.append(user_text)
            return super().complete(system_prompt, user_text, timeout)

    p = Spy("groq", "m", [EVENT_OK])
    rt = Router(news, [p])
    d = run_news_batch(rt, news, dry_run=True)
    assert d["planned"] == 1 and p.calls == 0 and news.execute("select count(*) n from llm_calls").one()["n"] == 0
    live = run_news_batch(rt, news, dry_run=False)
    assert live["outcomes"] == {"ok": 1} and seen == ["OGDC announces final cash dividend for FY2026"]
    assert run_news_batch(rt, news, dry_run=False)["planned"] == 0           # already extracted -> not pending


def test_batch_stops_when_budget_refuses(news):
    for i in range(3):
        item(news, ext=f"n{i}", title=f"Pakistan headline number {i} about OGDC")
    p = ScriptedProvider("groq", "m", [EVENT_OK] * 3)
    res = run_news_batch(Router(news, [p], {"groq": Budget(max_calls_per_day=0)}), news, limit=3, dry_run=False)
    assert res["outcomes"] == {"refused_budget": 1} and p.calls == 0


@pytest.mark.parametrize("bad", [
    {"event_type": "dividend", "tickers": [], "confidence_band": "low", "claims": [{"kind": "inference", "text": "Payout could reach 5 percent"}]},
    {"event_type": "dividend", "tickers": [], "confidence_band": "low", "claims": [{"kind": "quote", "text": "OGDC will pay Rs 5"}]},
    {"event_type": "dividend", "tickers": [], "confidence_band": "low", "claims": [], "claim_type": "verified_fact"},
    {"event_type": "dividend", "tickers": [], "confidence_band": "very high", "claims": []},
])
def test_groq_style_failure_modes_are_never_stored(news, bad):
    i = item(news)
    r = Router(news, [ScriptedProvider("groq", "m", [json.dumps(bad)] * 2)]).extract(i, "OGDC announces final cash dividend for FY2026")
    assert r["outcome"] == "invalid_output" and news.execute("select count(*) n from event_extractions").one()["n"] == 0


# ------------------------------------------------------------------ Phase 2: Gemini long documents + financial statements
def test_parse_number_is_deterministic_and_strict():
    assert parse_number("1,234,567") == Decimal("1234567") and parse_number("(45,210)") == Decimal("-45210")
    assert parse_number("-5.5") == Decimal("-5.5") and parse_number("Rs. 1,000") == Decimal("1000")
    for bad in ("1.234,56", "12%", "—", "nil", "1,23", "abc", "", None, "1,2345"):
        assert parse_number(bad) is None


def test_chunking_overlap_stable_hashes_and_hard_split():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(30))
    ch = chunk_text(text, max_chars=800, overlap_chars=100)
    assert len(ch) > 1 and all(len(c["text"]) <= 900 for c in ch) and [c["index"] for c in ch] == list(range(1, len(ch) + 1))
    assert ch[1]["text"].startswith(ch[0]["text"][-100:])                    # overlap carried into the next chunk
    assert chunk_text(text, 800, 100) == ch                                   # deterministic
    assert variant_tag(ch[0]).startswith("#c1of") and len(set(variant_tag(c) for c in ch)) == len(ch)
    assert len(chunk_text("x" * 5000, 1000, 100)) >= 5


FIN_TEXT = ("Statement of Profit or Loss (Rupees in thousand)\n\nRevenue 2026 12,345,678 2025 10,111,222\n\n"
            "Profit after tax 2026 (1,250) 2025 3,400")
FIN_OK = json.dumps({"statement": "income_statement", "unit_text": "Rupees in thousand", "confidence_band": "high",
                     "items": [{"label": "Revenue", "period": "2026", "value": "12,345,678"},
                               {"label": "Profit after tax", "period": "2026", "value": "(1,250)"}]})


@pytest.fixture
def fin(db):
    add_source(db, "report", stype="exchange")
    return db, item(db, "report", "r1", "Annual report")


def test_financial_items_python_parses_numbers_and_types_claims(fin):
    db, i = fin
    r = Router(db, [ScriptedProvider("gemini", "g", [FIN_OK])], spec=registry.FINANCIAL_LINE_ITEMS).extract(i, FIN_TEXT)
    assert r["outcome"] == "ok" and r["claim_types"] == ["official_statement"] * 2
    j = json.loads(db.execute("select extracted_json from event_extractions").one()["extracted_json"])
    assert [x["value_parsed"] for x in j["items"]] == ["12345678", "-1250"] and j["record_kind"] == "model_candidate"
    assert db.execute("select count(*) n from financial_metrics").one()["n"] == 0        # never straight into metrics


@pytest.mark.parametrize("bad", [
    {"items": [{"label": "Revenue", "period": "2026", "value": "12,345,679"}]},           # value not in the text
    {"items": [{"label": "Revenue", "period": "2026", "value": "12.3 million"}]},         # not in text / not parseable
    {"items": [{"label": "Total income", "period": "2026", "value": "12,345,678"}]},      # label invented
    {"unit_text": "Rupees in millions"},                                                  # unit not verbatim
])
def test_financial_rejects_ungrounded_or_unparseable(fin, bad):
    db, i = fin
    body = {**json.loads(FIN_OK), **bad}
    r = Router(db, [ScriptedProvider("gemini", "g", [json.dumps(body)] * 2)], spec=registry.FINANCIAL_LINE_ITEMS).extract(i, FIN_TEXT)
    assert r["outcome"] == "invalid_output" and db.execute("select count(*) n from event_extractions").one()["n"] == 0


def test_financial_unparseable_but_present_value_rejected(fin):
    db, i = fin
    text = "Revenue 2026 nil"
    body = json.dumps({"statement": "income_statement", "unit_text": "", "confidence_band": "low",
                       "items": [{"label": "Revenue", "period": "2026", "value": "nil"}]})
    assert Router(db, [ScriptedProvider("g", "g", [body] * 2)], spec=registry.FINANCIAL_LINE_ITEMS).extract(i, text)["outcome"] == "invalid_output"


def test_missing_unit_is_flagged_not_guessed(fin):
    db, i = fin
    body = json.dumps({"statement": "income_statement", "unit_text": "", "confidence_band": "low",
                       "items": [{"label": "Revenue", "period": "2026", "value": "12,345,678"}]})
    r = Router(db, [ScriptedProvider("g", "g", [body])], spec=registry.FINANCIAL_LINE_ITEMS).extract(i, FIN_TEXT)
    assert r["outcome"] == "ok" and any("unit_missing" in f for f in r["flags"])


def test_long_document_chunks_cached_per_chunk_and_run_limited(fin):
    db, i = fin
    doc = "\n\n".join(f"Section {k}: Revenue 2026 {k},000 notes" + " filler" * 60 for k in range(1, 9))
    empty = json.dumps({"statement": "notes", "unit_text": "", "items": [], "confidence_band": "low"})
    p = ScriptedProvider("gemini", "g", [empty] * 20)
    rt = Router(db, [p], spec=registry.FINANCIAL_LINE_ITEMS)
    dry = run_long_document(rt, i, doc, max_chars=600, overlap_chars=50, max_chunks=3, dry_run=True)
    assert dry["chunks"] >= 5 and p.calls == 0
    first = run_long_document(rt, i, doc, max_chars=600, overlap_chars=50, max_chunks=3, dry_run=False)
    assert p.calls == 3 and first["remaining_chunks"] == dry["chunks"] - 3          # per-run chunk limit
    second = run_long_document(rt, i, doc, max_chars=600, overlap_chars=50, max_chunks=3, dry_run=False)
    assert [o for _, o in second["outcomes"][:3]] == ["cached"] * 3 and p.calls == 6    # resumes; earlier chunks are cache hits
    assert db.execute("select count(distinct schema_version) n from event_extractions").one()["n"] == 6


def test_quote_must_come_from_the_same_chunk(fin):
    db, i = fin
    chunks = chunk_text("A" * 30 + " alpha fact\n\n" + "B" * 30 + " beta fact", 40, 0)
    body = json.dumps({"event_type": "other", "tickers": [], "confidence_band": "low",
                       "claims": [{"kind": "quote", "text": "beta fact"}]})
    r = Router(db, [ScriptedProvider("g", "g", [body] * 2)]).extract(i, chunks[0]["text"], variant=variant_tag(chunks[0]))
    assert r["outcome"] == "invalid_output"


# ------------------------------------------------------------------ Phase 3: OpenRouter per-model fallback
def or_cfg(tmp_path, models, **kw):
    cfg = enable_all(json.loads(Path(cfgmod.DEFAULT_PATH).read_text()), verified=True)
    for p in cfg["providers"]:
        if p["name"] == "openrouter":
            p["models"] = models
    f = tmp_path / "c.json"; f.write_text(json.dumps(cfg))
    return f


def test_openrouter_models_expand_in_order_and_need_individual_verification(tmp_path):
    f = or_cfg(tmp_path, [{"id": "m-a:free", "verified": True, "enabled": True}, {"id": "m-b:free", "verified": False, "enabled": True},
                          {"id": "m-c:free", "verified": True, "enabled": False}, {"id": "m-d:free", "verified": True, "enabled": True}])
    provs, budgets = cfgmod.build("long_document_extraction", f)
    assert [(p.name, p.model) for p in provs] == [("gemini", "gemini-2.0-flash"), ("openrouter", "m-a:free"), ("openrouter", "m-d:free")]
    assert list(budgets) == ["gemini", "openrouter"]


def test_model_fallback_cooldown_is_per_route_and_budget_shared(news, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key-0123456789")
    i1, i2 = item(news, ext="a"), item(news, ext="b")
    s1 = FakeSession(FakeResp(429, headers={"Retry-After": "300"}))
    s2 = FakeSession(FakeResp(text_content=EVENT_OK), FakeResp(text_content=EVENT_OK))
    mk = lambda model, sess: OpenAICompatProvider("openrouter", "https://openrouter.ai/api/v1", model, "OPENROUTER_API_KEY", session=sess)
    pa, pb = mk("m-a:free", s1), mk("m-b:free", s2)
    clock = [0.0]
    rt = Router(news, [pa, pb], {"openrouter": Budget(max_calls_per_day=3)}, mono=lambda: clock[0])
    text = "OGDC announces final cash dividend for FY2026"
    assert rt.extract(i1, text)["outcome"] == "ok" and len(s1.calls) == 1 and len(s2.calls) == 1
    assert rt.extract(i2, text)["outcome"] == "ok" and len(s1.calls) == 1            # model A cooling down; model B used
    row = news.execute("select model from event_extractions order by extraction_id").rows
    assert [r["model"] for r in row] == ["m-b:free", "m-b:free"]
    # budget is per PROVIDER: 3 calls counted across both models (429 + 2 ok) -> next call refused
    i3 = item(news, ext="c")
    assert rt.extract(i3, text)["outcome"] == "refused_budget"
