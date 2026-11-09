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


def test_overlaps_never_in_write_estimate_and_no_write_path():
    est = m.row_estimate(m.plan(SAMPLE, EXISTING))
    assert est["companies"] == 1 and est["company_aliases(ticker+legal_name)"] == 2
    src = open(m.__file__).read().lower()
    for bad in ("insert into", "executemany", "conn.commit", "update companies", "delete from"):
        assert bad not in src
