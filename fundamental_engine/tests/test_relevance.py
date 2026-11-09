import pytest

from core.db import sqlite_connect
from extract import registry
from extract.pipeline import run_news_batch
from extract.relevance import Relevance, company_phrases
from llm.providers import ScriptedProvider
from llm.router import Router
from tests.conftest import add_company, add_source

RULES = None


@pytest.fixture
def rel():
    return Relevance(tickers=["OGDC", "HUBC", "PPP", "MARI"], names=["hub power", "oil and gas development", "bank alfalah"],
                     watchlist=["OGDC"])


def passes(rel, text, source=None):
    return rel.score(text, source)["pass"]


@pytest.mark.parametrize("text", [                                   # the 5 irrelevant headlines that were actually extracted
    "Pindi courts acquit most accused", "PML-N's Asif backs twelve new provinces", "PML-N's Asad Hanif Jutt wins Chichawatni by-poll",
    "No vital infrastructure damaged in US attack on Qeshm island: Iranian official",
    "Israeli president tasks Eisenkot with forming new government"])
def test_irrelevant_headlines_skipped(rel, text):
    assert not passes(rel, text)


@pytest.mark.parametrize("text,reason", [
    ("OGDC announces final cash dividend", "ticker:OGDC"),
    ("Hub Power shares jump after results", "company:hub power"),
    ("SBP keeps policy rate unchanged", "regulatory:policy rate"),
    ("NEPRA raises industrial tariff", "regulatory:nepra"),
    ("PSX sheds nearly 1,500 points", "markets:psx"),
    ("Petrol price cut by Rs6 per litre", "commodities:petrol price"),
    ("Board approves interim dividend of Rs3", "corporate:interim dividend"),
])
def test_relevant_headlines_pass_with_reasons(rel, text, reason):
    r = rel.score(text)
    assert r["pass"] and any(x.startswith(reason) for x in r["reasons"]), r


def test_tickers_match_uppercase_whole_words_only(rel):
    assert not passes(rel, "Mari gold is a flower variety")            # lowercase / Title Case word is not the ticker
    assert not passes(rel, "OGDCX is not a ticker")
    assert passes(rel, "MARI gas find lifts outlook")


def test_ambiguous_ticker_needs_corroboration(rel):
    assert not passes(rel, "PPP calls for emergency over violence against women")
    r = rel.score("PPP declares dividend for shareholders")
    assert r["pass"] and any("ambiguous, corroborated" in x for x in r["reasons"])
    assert any("ignored" in x for x in rel.score("JI chief accuses PPP of stealing mandate")["reasons"])


def test_company_name_needs_whole_phrase(rel):
    assert passes(rel, "Bank Alfalah quits Kabul after 20 years")
    assert not passes(rel, "Alfalah family holds wedding")             # partial phrase


def test_context_only_signals_never_pass_alone(rel):
    assert not passes(rel, "Gold price per tola experiences no change in Pakistan", "brecorder")   # geo + small source bonus
    assert not passes(rel, "HR awards set at Avari Towers Karachi", "brecorder")
    assert passes(rel, "Pakistan's foreign exchange reserves climb")                              # geo + substantive
    assert passes(rel, "Weekly Sensitive Price Indicator for the week", "pbs")                    # official-statistics source


def test_foreign_noise_penalty(rel):
    assert not passes(rel, "Indian rupee extends rally, RBI watches")                             # 'rupee' (+2) offset by noise (-2)


def test_deterministic_and_versioned(rel):
    a, b = rel.score("SBP keeps policy rate unchanged"), rel.score("SBP keeps policy rate unchanged")
    assert a == b and a["version"].startswith("relevance@v")


def test_company_phrase_extraction():
    assert company_phrases("The Hub Power Company Limited") == "hub power"
    assert company_phrases("Systems Limited") is None                   # single word: too ambiguous
    assert company_phrases("Oil & Gas Development Company Limited") == "oil gas development"


# ------------------------------------------------------------------ pipeline integration
GOOD = '{"event_type":"dividend","tickers":["OGDC"],"confidence_band":"low","claims":[]}'


@pytest.fixture
def pipe(db):
    add_source(db, "news", stype="news_media"); add_company(db, "OGDC")
    db.execute("UPDATE sources SET retention_mode='metadata_only' WHERE source_id='news'")
    return db


def put(db, ext, title, ts):
    db.execute("INSERT INTO source_items(source_id,external_id,title,collected_at_utc,content_sha256) VALUES('news',?,?,?,?)",
               (ext, title, ts, "a" * 64))


def test_prefilter_skips_noise_without_model_calls_and_does_not_starve(pipe):
    db = pipe
    put(db, "old-relevant", "OGDC announces final cash dividend today", "2026-01-01T00:00:00Z")     # oldest
    for i in range(30):                                                                              # 30 newer irrelevant items
        put(db, f"n{i}", f"Local court hears unrelated case number {i} today", f"2026-11-0{1 + i % 9}T00:00:00Z")
    pre = Relevance.from_db(db)
    p = ScriptedProvider("groq", "m", [GOOD] * 5)
    rt = Router(db, [p])
    no_pre = run_news_batch(rt, db, limit=5, dry_run=True)                          # without prefilter: only newest 5 (all noise)
    assert all("Local court" in db.execute("select title from source_items where source_item_id=?", (x["source_item_id"],)).one()["title"]
               for x in no_pre["plan"])
    res = run_news_batch(rt, db, limit=5, dry_run=False, prefilter=pre, scan_limit=100)
    assert res["planned"] == 1 and res["skipped_irrelevant"] == 30 and p.calls == 1 and res["outcomes"] == {"ok": 1}
    assert res["prefilter"].startswith("relevance@v") and "ticker:OGDC" in res["plan"][0]["relevance"]
    assert run_news_batch(rt, db, limit=5, dry_run=False, prefilter=pre, scan_limit=100)["planned"] == 0   # relevant one now done
    assert p.calls == 1 and db.execute("select count(*) n from llm_calls").one()["n"] == 1


def test_rules_file_is_valid_and_versioned():
    from extract.relevance import load_rules
    r = load_rules()
    assert r["version"].startswith("relevance@v") and r["threshold"] >= 1 and set(r["groups"]) >= {"corporate", "regulatory", "markets", "commodities"}
    assert all(isinstance(w, int) for g in r["groups"].values() for w in g.values())
