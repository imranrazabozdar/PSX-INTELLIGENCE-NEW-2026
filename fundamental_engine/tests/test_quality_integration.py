import json

import pytest

from extract.pipeline import run_news_batch
from extract.relevance import Relevance
from extract.text import item_text_basis
from llm.providers import ScriptedProvider
from llm.router import Router
from review import queue
from sources import acquire
from tests.conftest import add_company, add_source

OK = json.dumps({"event_type": "other", "tickers": [], "confidence_band": "low", "claims": []})


def reply(quote, tickers=()):
    return json.dumps({"event_type": "dividend", "tickers": list(tickers), "confidence_band": "medium",
                       "claims": [{"kind": "quote", "text": quote}]})


@pytest.fixture
def world(db):
    add_source(db, "news", stype="news_media"); add_source(db, "wire", stype="news_media")
    db.execute("UPDATE sources SET retention_mode='metadata_only'")
    add_company(db, "OGDC")
    return db


def put(db, sid, ext, title, ts="2026-11-09T00:00:00Z"):
    return db.execute("INSERT INTO source_items(source_id,external_id,title,collected_at_utc,content_sha256) VALUES(?,?,?,?,?)",
                      (sid, ext, title, ts, "a" * 64)).lastrowid


# ------------------------------------------------------------------ router: text basis + entity resolution
def test_candidate_records_text_basis_scope_and_deterministic_resolution(world):
    db = world
    i = put(db, "news", "a", "OGDC announces final cash dividend")
    Router(db, [ScriptedProvider("g", "m", [reply("OGDC announces final cash dividend", ["OGDC"])])]).extract(i, "OGDC announces final cash dividend")
    row = db.execute("select extracted_json,provenance_json,review_reasons_json from event_extractions").one()
    j = json.loads(row["extracted_json"])
    assert j["text_basis"] == "headline" and j["evidence_scope"] == "headline_only"
    assert j["entity_resolution"]["direct"][0]["ticker"] == "OGDC" and j["entity_resolution"]["resolver_version"] == "entities@v1"
    assert json.loads(row["provenance_json"])["text_basis"] == "headline"
    assert any("headline_only" in r for r in json.loads(row["review_reasons_json"]))


def test_full_text_basis_has_no_headline_only_flag(world):
    db = world
    i = put(db, "news", "a", "Budget estimates revised")
    body = "The finance ministry revised the budget estimates on Monday, reducing the primary deficit target."
    Router(db, [ScriptedProvider("g", "m", [reply("The finance ministry revised the budget estimates on Monday")])]).extract(i, body, text_basis="full_text")
    row = db.execute("select extracted_json,review_reasons_json from event_extractions").one()
    assert json.loads(row["extracted_json"])["evidence_scope"] == "full_text"
    assert not any("headline_only" in r for r in json.loads(row["review_reasons_json"]))


def test_model_proposed_ambiguous_ticker_is_flagged_and_not_resolved_directly(world):
    db = world
    add_company(db, "PPP")                                    # ticker collides with the Pakistan Peoples Party acronym
    text = "PPP calls for emergency over violence against women"
    i = put(db, "news", "a", text)
    Router(db, [ScriptedProvider("g", "m", [reply(text, ["PPP"])])]).extract(i, text)       # passes schema + grounding + DB lookup
    row = db.execute("select extracted_json,review_reasons_json from event_extractions").one()
    j = json.loads(row["extracted_json"])
    assert [t["ticker"] for t in j["tickers"]] == ["PPP"]                                       # what the model proposed is kept, labelled as such
    assert j["entity_resolution"]["direct"] == []                                               # deterministic resolution refuses it
    assert j["entity_resolution"]["unresolved"][0]["reason"] == "ambiguous_ticker_without_corroboration"
    assert any("not supported by deterministic resolution" in r and "PPP" in r for r in json.loads(row["review_reasons_json"]))


def test_indirect_exposure_kept_separate_in_stored_candidate(world):
    db = world
    db.execute("INSERT INTO sectors(sector_id,scheme,name,created_at_utc) VALUES('psx-oil-gas-exploration-companies','PSX','E&P','t')")
    db.execute("INSERT INTO company_classifications(company_id,sector_id,verified_at_utc) VALUES('cmp-ogdc','psx-oil-gas-exploration-companies','t')")
    i = put(db, "news", "a", "Brent crude jumps on supply worries")
    Router(db, [ScriptedProvider("g", "m", [OK])]).extract(i, "Brent crude jumps on supply worries")
    er = json.loads(db.execute("select extracted_json from event_extractions").one()["extracted_json"])["entity_resolution"]
    assert er["direct"] == [] and er["indirect"][0]["rule_id"] == "fuel_prices" and er["indirect"][0]["companies"] == ["OGDC"]


def test_queue_summary_shows_basis_and_entities_and_defaults_legacy_to_headline(world):
    db = world
    i = put(db, "news", "a", "OGDC announces final cash dividend")
    Router(db, [ScriptedProvider("g", "m", [reply("OGDC announces final cash dividend")])]).extract(i, "OGDC announces final cash dividend")
    s = queue.summarise(queue.pending(db)[0])
    assert s["text_basis"] == "headline" and s["direct_companies"] == ["OGDC"]
    legacy = {"extraction_id": 1, "source_id": "x", "title": "t", "model": "m", "extracted_json": json.dumps({"event_type": "other", "claims": [], "tickers": [], "confidence_band": "low"})}
    assert queue.summarise(legacy)["text_basis"] == "headline" and queue.summarise(legacy)["direct_companies"] == []


# ------------------------------------------------------------------ pipeline: dedup
def test_exact_duplicates_skipped_across_feeds_originals_untouched_calls_counted(world):
    db = world
    a = put(db, "news", "a", "Gold rises over 1% as softer oil prices ease inflation worries")
    b = put(db, "wire", "b", "GOLD RISES OVER 1% AS SOFTER OIL PRICES EASE INFLATION WORRIES | Business Recorder")
    c = put(db, "news", "c", "Gold rises over 1% as softer oil prices ease inflation worries ")
    d = put(db, "news", "d", "Petrol price cut by Rs6.59 per litre")
    before = db.execute("select source_item_id,title,content_sha256,source_id from source_items order by 1").rows
    p = ScriptedProvider("g", "m", [OK] * 5)
    res = run_news_batch(Router(db, [p]), db, limit=10, dry_run=False)
    assert res["duplicates_skipped"] == 2 and res["model_calls_avoided"] == 2 and p.calls == 2 and res["outcomes"] == {"ok": 2}
    assert {(x["source_item_id"], x["duplicate_of"]) for x in res["duplicates"]} <= {(b, a), (c, a), (a, b), (a, c), (b, c), (c, b), (d, d)}
    assert all(x["duplicate_of"] in (a, b, c) for x in res["duplicates"])
    assert db.execute("select source_item_id,title,content_sha256,source_id from source_items order by 1").rows == before   # untouched


def test_duplicate_of_already_extracted_item_is_skipped(world):
    db = world
    a = put(db, "news", "a", "Rupee records gain against US dollar")
    rt = Router(db, [ScriptedProvider("g", "m", [OK] * 3)])
    run_news_batch(rt, db, limit=10, dry_run=False)
    b = put(db, "wire", "b", "Rupee records gain against US dollar!")
    res = run_news_batch(rt, db, limit=10, dry_run=False)
    assert res["planned"] == 0 and res["duplicates"][0] == {"source_item_id": b, "source_id": "wire", "duplicate_of": a}


def test_similar_but_distinct_and_updated_stories_are_sent(world):
    db = world
    put(db, "news", "a", "Petrol price slashed by Rs9.41 per litre")
    put(db, "news", "b", "Petrol price slashed by Rs6.59 per litre")                    # different figure
    put(db, "news", "c", "SBP keeps policy rate unchanged")
    put(db, "news", "d", "SBP cuts policy rate")                                        # opposite fact
    put(db, "news", "e", "Pakistan's forex reserves climb to $26bn")
    put(db, "news", "f", "Pakistan's forex reserves climb to $27bn")                    # updated figure
    p = ScriptedProvider("g", "m", [OK] * 8)
    res = run_news_batch(Router(db, [p]), db, limit=10, dry_run=False)
    assert res["duplicates_skipped"] == 0 and p.calls == 6


def test_near_duplicates_are_reported_but_still_sent(world):
    db = world
    put(db, "news", "a", "Government announces new tax relief package for exporters this week")
    put(db, "wire", "b", "Government announces new tax relief package for exporters this week, officials say")
    p = ScriptedProvider("g", "m", [OK] * 3)
    res = run_news_batch(Router(db, [p]), db, limit=10, dry_run=False)
    assert p.calls == 2 and res["duplicates_skipped"] == 0 and len(res["near_duplicates_reported"]) == 1


def test_dedupe_off_sends_everything_and_limit_counts_sent_items(world):
    db = world
    for k in range(4):
        put(db, "news", f"d{k}", "Same headline repeated on four feeds")
    put(db, "news", "x", "Another distinct headline about the budget")
    p = ScriptedProvider("g", "m", [OK] * 10)
    assert run_news_batch(Router(db, [p]), db, limit=10, dry_run=True, dedupe=False)["planned"] == 5
    res = run_news_batch(Router(db, [p]), db, limit=2, dry_run=True)
    assert res["planned"] == 2 and res["duplicates_skipped"] == 3                        # limit applies to items actually sent


def test_dedupe_composes_with_prefilter(world):
    db = world
    put(db, "news", "a", "OGDC announces final cash dividend")
    put(db, "wire", "b", "OGDC announces final cash dividend - Dawn")
    put(db, "news", "c", "Local court hears unrelated case today")
    res = run_news_batch(Router(db, [ScriptedProvider("g", "m", [OK] * 3)]), db, limit=10, dry_run=True, prefilter=Relevance.from_db(db))
    assert (res["planned"], res["duplicates_skipped"], res["skipped_irrelevant"]) == (1, 1, 1)


# ------------------------------------------------------------------ text basis honesty + acquired text gating
def test_item_text_basis_never_relabels_headline_as_full_text():
    assert item_text_basis("Head", "excerpt", "metadata_only", acquired_text="BODY") == ("Head", "headline")      # registry gate
    assert item_text_basis("Head", "exc", "excerpt") == ("Head\nexc", "excerpt")
    assert item_text_basis("Head", None, "full_text_permitted") == ("Head", "headline")                            # permitted but nothing acquired
    assert item_text_basis("Head", None, "full_text_permitted", acquired_text="Body  text") == ("Body text", "full_text")


def acquired(db, tmp_path, item_id, source_id, text):
    res = {"url": "https://x/a", "status": "fetched_ok", "http_status": 200, "text": text}
    acquire.store_result(tmp_path, {"source_item_id": item_id, "source_id": source_id}, res, "full_text", now="2026-11-09T12:00:00Z")


def test_full_text_used_only_when_source_permits_and_hash_verifies(world, tmp_path):
    db = world
    db.execute("UPDATE sources SET retention_mode='full_text_permitted' WHERE source_id='news'")
    a = put(db, "news", "a", "Budget estimates revised")
    b = put(db, "wire", "b", "Another budget headline here")               # 'wire' stays metadata_only
    body = "The finance ministry revised the budget estimates on Monday, lowering the primary deficit target for the fiscal year."
    acquired(db, tmp_path, a, "news", body); acquired(db, tmp_path, b, "wire", body)
    seen = []

    class Spy(ScriptedProvider):
        def complete(self, s, t, timeout=60):
            seen.append(t); return super().complete(s, t, timeout)

    res = run_news_batch(Router(db, [Spy("g", "m", [OK] * 3)]), db, limit=10, dry_run=False, vault_root=tmp_path)
    bases = {p["source_item_id"]: p["text_basis"] for p in res["plan"]}
    assert bases == {a: "full_text", b: "headline"}                         # b has a manifest but its source only permits metadata
    assert body in seen and "Another budget headline here" in seen
    ex = {r["source_item_id"]: json.loads(r["extracted_json"])["text_basis"] for r in db.execute("select source_item_id,extracted_json from event_extractions").rows}
    assert ex == {a: "full_text", b: "headline"}


def test_tampered_acquired_text_falls_back_to_headline(world, tmp_path):
    db = world
    db.execute("UPDATE sources SET retention_mode='full_text_permitted' WHERE source_id='news'")
    a = put(db, "news", "a", "Budget estimates revised")
    acquired(db, tmp_path, a, "news", "A long enough body text. " * 5)
    man = acquire.load_manifest(tmp_path, a)
    (tmp_path / man["text_path"]).write_text("tampered", encoding="utf-8")
    res = run_news_batch(Router(db, [ScriptedProvider("g", "m", [OK])]), db, limit=5, dry_run=True, vault_root=tmp_path)
    assert res["plan"][0]["text_basis"] == "headline"


def test_very_long_full_text_goes_through_chunking_with_full_text_basis(world, tmp_path):
    db = world
    db.execute("UPDATE sources SET retention_mode='full_text_permitted' WHERE source_id='news'")
    a = put(db, "news", "a", "Annual report published")
    body = "\n\n".join(f"Section {k}: " + "The company reported operating conditions in line with expectations. " * 40 for k in range(1, 12))
    assert len(body) > 12000
    acquired(db, tmp_path, a, "news", body)
    p = ScriptedProvider("g", "m", [OK] * 20)
    res = run_news_batch(Router(db, [p]), db, limit=5, dry_run=False, vault_root=tmp_path)
    assert p.calls >= 2 and res["outcomes"] == {"ok": 1}
    rows = db.execute("select extracted_json,schema_version from event_extractions").rows
    assert len(rows) == p.calls and all(json.loads(r["extracted_json"])["text_basis"] == "full_text" and "#c" in r["schema_version"] for r in rows)
