import company_master_loader as m

SAMPLE = [
    {"symbol": "SSGC", "company_name": "Sui Southern Gas Company Limited", "sector": "Gas, Water and Multiutilities",
     "listing_status": "Active", "isin": "PK0035010103", "fiscal_year_end": "June 30"},
    {"symbol": "OGDC", "company_name": "Oil & Gas Development Company Limited", "sector": "Oil and Gas Exploration Companies",
     "listing_status": "Active", "isin": "PK0037010100", "fiscal_year_end": "June 30"},
    {"symbol": "TPLP", "company_name": "TPL Properties Ltd", "sector": "Real Estate Investment Trust",
     "listing_status": "Active", "isin": None, "fiscal_year_end": "June 30"},
]
EXISTING = {
    "companies": {
        "SSGC": {"legal_name": "Sui Southern Gas Company Limited", "listing_status": "listed", "fiscal_year_end_month": 6,
                 "sector_name": "OIL & GAS MARKETING COMPANIES"},
        "OGDC": {"legal_name": "Oil & Gas Development Company Limited", "listing_status": "listed", "fiscal_year_end_month": 6,
                 "sector_name": "OIL & GAS EXPLORATION COMPANIES"}},
    "sectors": {m.norm_sector("OIL & GAS EXPLORATION COMPANIES"): "psx-oil-gas-exploration-companies"},
    "isins": set()}


def test_isin_checksum():
    assert not m.isin_valid("PK0035010103") and not m.isin_valid("PK0037010100")
    assert m.isin_valid("US0378331005")  # Apple Inc., known-valid ISIN
    assert not m.isin_valid("") and not m.isin_valid(None)


def test_sector_and_fy_normalisation():
    assert m.norm_sector("Oil and Gas Exploration Companies") == m.norm_sector("OIL & GAS EXPLORATION COMPANIES")
    assert m.fy_month("June 30") == 6 and m.fy_month("December 31") == 12 and m.fy_month("garbage") is None


def test_plan_overlap_conflict_and_new():
    p = m.plan(SAMPLE, EXISTING)
    assert [c["ticker"] for c in p["new"]] == ["TPLP"]
    assert [t for t, _ in p["overlap_conflict"]] == ["SSGC"] and [t for t, _ in p["overlap_same"]] == ["OGDC"]
    assert "sector" in dict(p["overlap_conflict"])["SSGC"]
    assert p["sector_unmapped"] == {"Gas, Water and Multiutilities": ["SSGC"], "Real Estate Investment Trust": ["TPLP"]}
    assert any("invalid_isin" in str(r) for r in p["rejected"])  # ISIN flagged, companies kept


def test_rejects_bad_records_and_dupes():
    recs = [{"symbol": "bad sym!", "company_name": "X", "listing_status": "Active"},
            {"symbol": "AAA", "company_name": "", "listing_status": "Active"},
            {"symbol": "BBB", "company_name": "B", "listing_status": "???"},
            {"symbol": "CCC", "company_name": "C", "listing_status": "Active", "fiscal_year_end": "June 30"},
            {"symbol": "CCC", "company_name": "C2", "listing_status": "Active"}]
    p = m.plan(recs)
    assert [c["ticker"] for c in p["new"]] == ["CCC"] and p["duplicate_in_file"] == ["CCC"] and len(p["rejected"]) == 3


def test_overlaps_never_in_write_estimate():
    est = m.row_estimate(m.plan(SAMPLE, EXISTING))
    assert est["companies"] == 1 and est["company_aliases(ticker+legal_name)"] == 2


import os
import sqlite3
FX = os.path.join(os.path.dirname(__file__), "fixtures")


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    for f in ("market_bars_schema.sql", "source_items_schema.sql", "company_master_schema.sql"):
        c.executescript(open(os.path.join(FX, f)).read())
    c.execute("CREATE TABLE IF NOT EXISTS source_item_versions(x)")
    c.execute("INSERT INTO sectors VALUES('psx-oil-gas-exploration-companies','PSX','OIL & GAS EXPLORATION COMPANIES','t')")
    c.execute("INSERT INTO companies(company_id,legal_name,listing_status,created_at_utc,updated_at_utc) "
              "VALUES('cmp-ogdc','Oil & Gas Development Company Limited','listed','t','t')")
    c.execute("INSERT INTO company_identifiers(company_id,id_type,value,verified_at_utc) VALUES('cmp-ogdc','psx_ticker','OGDC','t')")
    return c


BIG = SAMPLE + [{"symbol": f"T{i:03d}", "company_name": f"Test Co {i}", "sector": "Oil and Gas Exploration Companies",
                 "listing_status": "Active", "isin": "US0378331005" if i == 0 else None, "fiscal_year_end": "December 31"}
                for i in range(5)]


def test_apply_chunked_resumable_idempotent_and_never_touches_existing():
    c = db()
    r1 = m.apply_chunk(c, BIG, "a" * 64, chunk=3)
    assert r1["chunk"] == 3 and r1["remaining_new"] == 4      # 7 new (SSGC, TPLP, T000-T004), OGDC already exists
    assert c.execute("select count(*) from dataset_loads").fetchone()[0] == 0   # incomplete -> not recorded yet
    r2 = m.apply_chunk(c, BIG, "a" * 64, chunk=100)
    assert r2["remaining_new"] == 0 and c.execute("select count(*) from dataset_loads").fetchone()[0] == 1
    before = c.execute("select count(*) from companies").fetchone()[0]
    r3 = m.apply_chunk(c, BIG, "a" * 64)
    assert r3["chunk"] == 0 and c.execute("select count(*) from companies").fetchone()[0] == before
    assert c.execute("select count(*) from companies").fetchone()[0] == 8        # 1 existing + 7 new
    # existing OGDC row untouched, no ISIN added from an invalid value, no new sectors created
    assert c.execute("select legal_name from companies where company_id='cmp-ogdc'").fetchone()[0] == "Oil & Gas Development Company Limited"
    assert c.execute("select count(*) from company_identifiers where id_type='isin'").fetchone()[0] == 1
    assert c.execute("select count(*) from sectors").fetchone()[0] == 1
    assert c.execute("select count(*) from company_identifiers where id_type='psx_ticker'").fetchone()[0] == before


def test_seed_source_disabled_with_owner_origin_note():
    c = db(); m.apply_chunk(c, BIG, "b" * 64)
    s = c.execute("select enabled,lifecycle_status,access_status,notes from sources where source_id='owner_psx_profiles'").fetchone()
    assert s["enabled"] == 0 and s["lifecycle_status"] == "RESTRICTED" and s["access_status"] == "unverified"
    assert "publicly available structural listings" in s["notes"]
    i = c.execute("select retrieval_method,document_type,content_sha256 from source_items where source_id='owner_psx_profiles'").fetchone()
    assert tuple(i) == ("seed", "dataset", "b" * 64)
    assert c.execute("select count(distinct profile_source_item_id) from companies where company_id<>'cmp-ogdc'").fetchone()[0] == 1


# ------------------------------------------------------------------ stub mode
def seed_investify(c, rows):
    c.execute("INSERT INTO sources(source_id,name,source_type,created_at_utc,updated_at_utc) VALUES('investify','Investify','news_media','t','t')")
    for i, (t, nm) in enumerate(rows, 1):
        meta = {"ticker": t, **({"company_name": nm} if nm else {})}
        c.execute("INSERT INTO source_items(source_id,external_id,title,collected_at_utc,content_sha256,source_metadata_json) "
                  "VALUES('investify',?,?,'t',?,?)", (f"psx_filing:{i}", f"{t} filing {i}", f"{i:064d}", json.dumps(meta)))


import json


def test_stub_candidates_exclude_known_tickers_and_never_guess_names():
    c = db()
    seed_investify(c, [("OGDC", None), ("TPLP", "TPL Properties Ltd"), ("CTM", None), ("CTM", None), ("bad sym", None)])
    cands = m.stub_candidates(c)
    assert sorted(cands) == ["CTM", "TPLP"] and cands["CTM"]["items"] == 2
    sp = m.plan_stubs(cands)
    assert [x["ticker"] for x in sp["creatable"]] == ["TPLP"] and [x["ticker"] for x in sp["needs_name"]] == ["CTM"]


def test_names_file_requires_evidence():
    c = db(); seed_investify(c, [("CTM", None)])
    cands = m.stub_candidates(c)
    assert m.plan_stubs(cands, {"CTM": {"company_name": "Colony Textile Mills Ltd"}})["creatable"] == []
    ok = m.plan_stubs(cands, {"CTM": {"company_name": "Colony Textile Mills Ltd", "evidence": "owner-verified PSX listing"}})
    assert ok["creatable"][0]["legal_name"] == "Colony Textile Mills Ltd"


def test_apply_stubs_minimal_idempotent_and_resolves_announcements():
    c = db()
    seed_investify(c, [("OGDC", None), ("TPLP", "TPL Properties Ltd"), ("TPLP", "TPL Properties Ltd"), ("CTM", None)])
    sp = m.plan_stubs(m.stub_candidates(c))
    cov = m.resolution_coverage(c, [x["ticker"] for x in sp["creatable"]])
    assert cov == {"announcements": 4, "linked_now": 1, "linked_after_stubs": 3}
    assert m.apply_stubs(c, sp)["stubs_created"] == 1
    assert m.apply_stubs(c, m.plan_stubs(m.stub_candidates(c)))["stubs_created"] == 0   # re-run: nothing new
    row = c.execute("select listing_status,fiscal_year_end_month,profile_source_item_id from companies where company_id='cmp-tplp'").fetchone()
    assert tuple(row)[:2] == ("unknown", None) and row[2] is not None
    assert c.execute("select count(*) from company_identifiers where id_type='isin'").fetchone()[0] == 0
    assert c.execute("select count(*) from company_classifications").fetchone()[0] == 0
    assert m.resolution_coverage(c)["linked_now"] == 3        # announcements now resolve with NO source_items update
    assert c.execute("select count(*) from companies").fetchone()[0] == 2   # OGDC (existing) + TPLP; CTM still unnamed
