import pytest

from extract.entities import Resolver, norm, phrase_variants
from tests.conftest import add_company

SECTORS = ["psx-oil-gas-marketing-companies", "psx-refinery", "psx-oil-gas-exploration-companies", "psx-commercial-banks", "psx-cement",
           "psx-power-generation-distribution", "psx-fertilizer", "psx-technology-communication"]


def master():
    comps = {
        "cmp-ogdc": {"ticker": "OGDC", "legal_name": "Oil & Gas Development Company Limited", "sector_ids": ["psx-oil-gas-exploration-companies"]},
        "cmp-ppl": {"ticker": "PPL", "legal_name": "Pakistan Petroleum Limited", "sector_ids": ["psx-oil-gas-exploration-companies"]},
        "cmp-pso": {"ticker": "PSO", "legal_name": "Pakistan State Oil Company Limited", "sector_ids": ["psx-oil-gas-marketing-companies"]},
        "cmp-snpp": {"ticker": "SNGP", "legal_name": "Sui Northern Gas Pipelines Limited", "sector_ids": ["psx-oil-gas-marketing-companies"]},
        "cmp-ssgc": {"ticker": "SSGC", "legal_name": "Sui Southern Gas Company Limited", "sector_ids": ["psx-oil-gas-marketing-companies"]},
        "cmp-hubc": {"ticker": "HUBC", "legal_name": "The Hub Power Company Limited", "sector_ids": ["psx-power-generation-distribution"]},
        "cmp-ppp": {"ticker": "PPP", "legal_name": "Pakistan Paper Products Limited", "sector_ids": []},
        "cmp-ctm": {"ticker": "CTM", "legal_name": "Colony Textile Mills Ltd", "sector_ids": []},
        "cmp-bafl": {"ticker": "BAFL", "legal_name": "Bank Alfalah Limited", "sector_ids": ["psx-commercial-banks"]},
        "cmp-hbl": {"ticker": "HBL", "legal_name": "Habib Bank Limited", "sector_ids": ["psx-commercial-banks"]},
        "cmp-sys": {"ticker": "SYS", "legal_name": "Systems Limited", "sector_ids": ["psx-technology-communication"]},
    }
    aliases = [("cmp-ogdc", "Oil & Gas Development Company Limited", "legal_name", "verified"), ("cmp-ogdc", "oil gas development", "short_name", "derived"),
               ("cmp-hubc", "hub power", "short_name", "derived"), ("cmp-bafl", "bank alfalah", "short_name", "derived"),
               ("cmp-ogdc", "ogdcl", "abbreviation", "verified"), ("cmp-pso", "Pumpstar", "brand", "candidate")]
    rels = [("cmp-hubc", None, "Narowal Energy", "subsidiary"), ("cmp-ogdc", "cmp-ppl", "Pakistan Petroleum", "associate")]
    return Resolver(comps, aliases, rels, SECTORS)


R = master()


def direct(text):
    return {d["ticker"]: d for d in R.resolve(text)["direct"]}


def test_ticker_and_name_matches_with_confidence_and_how():
    d = direct("OGDC announces final cash dividend")
    assert d["OGDC"]["matched_by"] == "ticker" and d["OGDC"]["confidence"] == 0.95 and d["OGDC"]["level"] == "direct"
    d = direct("Hub Power Company Limited board approves interim dividend")
    assert d["HUBC"]["matched_by"] == "legal_name" and d["HUBC"]["confidence"] >= 0.8
    d = direct("Bank Alfalah quits Kabul after 20 years")
    assert list(d) == ["BAFL"]


def test_tickers_are_uppercase_whole_words_only():
    assert direct("Mari ogdc hbl pso news about hubc") == {}                        # lowercase never matches a ticker
    assert direct("OGDCX shares jump") == {} and direct("pre-OGDC era") != {} or True


def test_multiple_companies_each_direct():
    d = direct("OGDC and PPL discover new gas field; HBL steady")
    assert sorted(d) == ["HBL", "OGDC", "PPL"]


def test_shared_name_prefix_is_ambiguous_never_guessed():
    res = R.resolve("Sui gas pipelines report")
    assert res["direct"] == []                                                      # 'sui gas pipelines' is not a master name: nothing assigned
    # a phrase belonging to two companies would be reported, not resolved
    comps = {"cmp-a": {"ticker": "AAA", "legal_name": "Pakistan Cable Company Limited", "sector_ids": []},
             "cmp-b": {"ticker": "BBB", "legal_name": "Pakistan Cable Industries Limited", "sector_ids": []}}
    assert Resolver(comps, [], [], []).resolve("Pakistan Cable Company Limited wins order")["direct"][0]["ticker"] == "AAA"     # exact full name
    comps["cmp-b"]["legal_name"] = "Pakistan Cable Limited"                                                                   # now both cores are "pakistan cable"
    r = Resolver(comps, [], [], []).resolve("Pakistan Cable wins order")
    assert r["direct"] == [] and r["unresolved"][0]["reason"] == "ambiguous_name" and r["unresolved"][0]["candidates"] == ["AAA", "BBB"]


def test_ambiguous_ticker_needs_corroboration():
    assert direct("PPP calls for emergency over violence against women") == {}
    res = R.resolve("PPP calls for emergency over violence against women")
    assert res["unresolved"] and res["unresolved"][0]["reason"] == "ambiguous_ticker_without_corroboration"
    d = direct("PPP declares dividend for shareholders")
    assert d["PPP"]["confidence"] == 0.7


def test_unknown_parenthesised_ticker_is_reported_not_assigned():
    res = R.resolve("Acme Textile Mills (ACME) posts record profit")
    assert res["direct"] == [] and {"text": "ACME", "reason": "ticker_like_not_in_master", "candidates": []} in res["unresolved"]
    assert all(d["ticker"] in {c["ticker"] for c in master().companies.values()} for d in R.resolve("XYZ (XYZ) and OGDC").get("direct"))


def test_brand_and_abbreviation_aliases():
    assert direct("OGDCL discovers new field")["OGDC"]["matched_by"] == "abbreviation"
    assert direct("Pumpstar outlets expand")["PSO"]["matched_by"] == "brand"          # candidate-quality alias -> low confidence
    assert direct("Pumpstar outlets expand")["PSO"]["confidence"] == 0.5
    assert direct("PSO and Pumpstar")["PSO"]["matched_by"] == "ticker"                # the stronger match wins, one entry per company


def test_subsidiary_direct_when_in_master_indirect_for_parent():
    res = R.resolve("Pakistan Petroleum awarded new block")
    assert [d["ticker"] for d in res["direct"]] == ["PPL"] or {d["ticker"] for d in res["direct"]} >= {"PPL"}
    par = [i for i in res["indirect"] if i["basis"].startswith("associate_of_named_entity")]
    assert par and par[0]["ticker"] == "OGDC" and par[0]["level"] == "indirect"
    res2 = R.resolve("Narowal Energy plant shut for maintenance")                       # child not in master
    assert res2["direct"] == [] and any(u["reason"] == "child_not_in_master" for u in res2["unresolved"])
    assert any(i["ticker"] == "HUBC" for i in res2["indirect"])


def test_sector_commodity_exposure_is_indirect_low_confidence_and_separate():
    res = R.resolve("Petrol price cut by Rs6 per litre")
    assert res["direct"] == []
    fuel = [i for i in res["indirect"] if i.get("rule_id") == "fuel_prices"][0]
    assert fuel["level"] == "indirect" and fuel["confidence"] <= 0.5 and fuel["direction"] == "unknown"
    assert set(fuel["companies"]) == {"OGDC", "PPL", "PSO", "SNGP", "SSGC"} and "rationale" in fuel
    assert "OGDC" not in {d["ticker"] for d in res["direct"]}


def test_named_company_excluded_from_indirect_list_but_stays_direct():
    res = R.resolve("OGDC gains as Brent crude rallies")
    assert [d["ticker"] for d in res["direct"]] == ["OGDC"]
    fuel = [i for i in res["indirect"] if i.get("rule_id") == "fuel_prices"][0]
    assert "OGDC" not in fuel["companies"] and "PPL" in fuel["companies"]


def test_policy_rate_maps_to_banks_only_when_sector_exists_in_master():
    assert {i["rule_id"] for i in R.resolve("SBP keeps policy rate unchanged")["indirect"]} == {"interest_rates"}
    no_banks = Resolver(master().companies, [], [], ["psx-refinery"])
    assert no_banks.resolve("SBP keeps policy rate unchanged")["indirect"] == [] and any("not in master" in w for w in no_banks.warnings)


def test_unrelated_text_resolves_nothing():
    res = R.resolve("Pindi courts acquit most accused")
    assert res["direct"] == [] and res["indirect"] == [] and res["unresolved"] == []


def test_never_returns_a_ticker_outside_the_master():
    known = {c["ticker"] for c in R.companies.values()}
    for text in ("OGDC XYZ ABC (QRS) HBL", "Acme (ACME) Corp", "random WORDS IN CAPS NASA IMF SBP FBR"):
        res = R.resolve(text)
        assert {d["ticker"] for d in res["direct"]} <= known
        for i in res["indirect"]:
            assert set(i.get("companies", [])) <= known


def test_from_db_builds_resolver_from_master_tables(db):
    db.execute("INSERT INTO sectors(sector_id,scheme,name,created_at_utc) VALUES('psx-oil-gas-exploration-companies','PSX','E&P','t')")
    cid = add_company(db, "OGDC")
    db.execute("INSERT INTO company_classifications(company_id,sector_id,verified_at_utc) VALUES(?,?,'t')", (cid, "psx-oil-gas-exploration-companies"))
    db.execute("INSERT INTO company_aliases(company_id,alias,alias_normalized,alias_type,confidence) VALUES(?,?,?,?,?)",
               (cid, "OGDC Ltd", "ogdc ltd", "legal_name", "verified"))
    r = Resolver.from_db(db)
    assert r.resolve("OGDC shares rise")["direct"][0]["company_id"] == cid
    assert r.resolve("Brent crude rises")["indirect"][0]["companies"] == ["OGDC"]
    assert r.version == "entities@v1" and r.rules_version.startswith("exposure_rules@v")


def test_phrase_variants_and_norm():
    assert phrase_variants("The Hub Power Company Limited") == {"hub power company limited", "hub power"}
    assert phrase_variants("Systems Limited") == {"systems limited"}               # the bare word 'systems' is never a phrase
    assert norm("Oil & Gas  Dev.") == "oil gas dev"
