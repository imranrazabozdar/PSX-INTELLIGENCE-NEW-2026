import os
import sqlite3
import pytest
import investify_parser as ip

FX = os.path.join(os.path.dirname(__file__), "fixtures")
HTML = open(os.path.join(FX, "investify_announcements_sample.html")).read()


def test_extracts_only_public_facts_and_skips_malformed():
    items = ip.parse_announcements(HTML)
    assert [i["psx_id"] for i in items] == ["288842-1", "288838"]
    a = items[0]
    assert (a["ticker"], a["timestamp_utc"], a["category"], a["title"]) == (
        "SSGC", "2026-11-06T12:45:00Z", "Report Transmission", "SSGC publishes Annual Report 2026")
    assert items[1]["category"] == "AGM / EGM" and items[1]["timestamp_utc"] == "2026-11-06T11:29:00Z"


def test_ignores_proprietary_text_sentiment_and_pdf_links():
    blob = repr(ip.parse_announcements(HTML)).lower()
    for bad in ("proprietary", "neutral", "highlights", "dps.psx.com.pk", ".pdf"):
        assert bad not in blob
    assert "investify.pk/announcements/ssgc/dps-pdf-288842-1" in blob


def test_empty_or_garbage_html():
    assert ip.parse_announcements("") == [] and ip.parse_announcements("<html>nothing</html>") == []


def test_ticker_mismatch_skipped():
    bad = HTML.replace("/announcements/TPLP/dps-pdf-288838", "/announcements/XXXX/dps-pdf-288838")
    assert [i["psx_id"] for i in ip.parse_announcements(bad)] == ["288842-1"]


def test_parser_has_no_network_or_db_code():
    src = open(ip.__file__).read().lower()
    for bad in ("import requests", "urllib.request", "turso", "sqlite3", "socket"):
        assert bad not in src


def db():
    c = sqlite3.connect(":memory:")
    for f in ("market_bars_schema.sql", "source_items_schema.sql"):
        c.executescript(open(os.path.join(FX, f)).read())
    c.execute("INSERT INTO sources(source_id,name,source_type,access_status,created_at_utc,updated_at_utc) "
              "VALUES('investify','Investify','news_media','restricted','t','t')")
    return c


def test_mapping_satisfies_real_schema_constraints_in_memory_copy():
    """Validates the design against an in-memory copy of the production DDL only (no Turso)."""
    c = db()
    for it in ip.parse_announcements(HTML):
        row = ip.to_source_item(it, "2026-11-09T12:00:00Z")
        cols = ",".join(row)
        c.execute(f"INSERT INTO source_items({cols}) VALUES({','.join('?' * len(row))})", list(row.values()))
    r = c.execute("select external_id,retrieval_method,document_type,access_status,content_location,permitted_excerpt,"
                  "json_extract(source_metadata_json,'$.ticker') from source_items order by 1").fetchall()
    assert r[0] == ("psx_filing:288838", "html", "announcement", "restricted", None, None, "TPLP")
    with pytest.raises(sqlite3.IntegrityError):  # same (source, external_id) twice is rejected -> dedupe key works
        row = ip.to_source_item(ip.parse_announcements(HTML)[0], "2026-11-09T13:00:00Z")
        c.execute(f"INSERT INTO source_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
