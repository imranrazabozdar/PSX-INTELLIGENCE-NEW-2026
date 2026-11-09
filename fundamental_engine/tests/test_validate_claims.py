import pytest

from extract import registry
from extract.claims import BAND_TO_CONFIDENCE, claim_type
from llm.validate import ValidationError, has_number, parse_json_object, validate_candidate

SCHEMA = registry.load_schema("event_candidate", "1")
SRC = "OGDC announced a final cash dividend. The Board meeting will be held on 27 November 2026."
RES = lambda t: {"OGDC": "cmp-ogdc"}.get(t)


def cand(**kw):
    base = {"event_type": "dividend", "tickers": ["OGDC"], "claims": [{"kind": "quote", "text": "OGDC announced a final cash dividend."}],
            "confidence_band": "high"}
    base.update(kw)
    return base


def test_valid_candidate_normalised():
    out, flags = validate_candidate(cand(), SCHEMA, SRC, RES)
    assert out["tickers"] == [{"ticker": "OGDC", "company_id": "cmp-ogdc"}] and flags == []
    assert out["claims"][0]["grounded"] is True


@pytest.mark.parametrize("bad", [
    cand(extra="x"),                                                             # unexpected key
    cand(claims=[{"kind": "quote", "text": "OGDC will pay Rs 5 per share."}]),   # quote not in source
    cand(claims=[{"kind": "inference", "text": "Dividend yield is 5 percent."}]),# number in inference
    cand(claims=[{"kind": "inference", "text": "Payout rises twenty percent"}]), # number words
    cand(claims=[{"kind": "inference", "text": "Costs fall by Rs. millions"}]),  # currency
    cand(claims=[{"kind": "quote", "text": "OGDC announced a final cash dividend.", "claim_type": "verified_fact"}]),  # model sets type
    cand(confidence_band=0.9),                                                   # numeric confidence
    cand(event_type="made_up"),
    {"event_type": "other"},                                                     # missing keys
])
def test_rejects_violations(bad):
    with pytest.raises(ValidationError):
        validate_candidate(bad, SCHEMA, SRC, RES)


def test_tickers_resolved_dropped_and_flagged():
    out, flags = validate_candidate(cand(tickers=["OGDC", "ZZZZ", "PPL"]), SCHEMA, SRC, RES)
    assert [t["ticker"] for t in out["tickers"]] == ["OGDC"] and out["unresolved_tickers"] == ["ZZZZ", "PPL"]
    assert any("not found in source text" in f for f in flags)


def test_quote_matching_ignores_whitespace_only():
    out, _ = validate_candidate(cand(claims=[{"kind": "quote", "text": "Board  meeting will be held on 27 November 2026."}]), SCHEMA, SRC, RES)
    assert out["claims"][0]["text"].startswith("Board meeting")


def test_parse_json_object():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    for bad in ("nope", "[1]", ""):
        with pytest.raises(ValidationError):
            parse_json_object(bad)


def test_has_number():
    assert has_number("rose 5%") and has_number("Rs 5") and has_number("three banks") and not has_number("Profitability may improve")


def test_claim_types_assigned_by_python():
    assert claim_type("quote", True, "exchange") == "official_statement"
    assert claim_type("quote", True, "news_media") == "news_report"
    assert claim_type("inference", False, "exchange") == "model_inference"
    assert claim_type("quote", False, "exchange") == "model_inference"
    assert set(BAND_TO_CONFIDENCE) == {"low", "medium", "high"}
