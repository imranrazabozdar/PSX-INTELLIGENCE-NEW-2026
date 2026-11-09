import os
import sqlite3
import investify_ingester as ing
import investify_parser as parser

FX = os.path.join(os.path.dirname(__file__), "fixtures")
HTML = open(os.path.join(FX, "investify_announcements_sample.html")).read()


def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    for f in ("market_bars_schema.sql", "source_items_schema.sql"):
        c.executescript(open(os.path.join(FX, f)).read())
    c.execute("CREATE TABLE source_item_versions(source_item_id INTEGER NOT NULL, version_no INTEGER NOT NULL, "
              "content_sha256 TEXT NOT NULL, collected_at_utc TEXT NOT NULL, permitted_excerpt TEXT, "
              "collection_run_id INTEGER, title TEXT, PRIMARY KEY(source_item_id,version_no), UNIQUE(source_item_id,content_sha256))")
    c.execute("INSERT INTO sources(source_id,name,source_type,access_status,created_at_utc,updated_at_utc) "
              "VALUES('investify','Investify','news_media','restricted','t','t')")
    return c


def test_first_run_inserts_second_run_rejects_duplicates():
    c, items = db(), parser.parse_announcements(HTML)
    r1 = ing.ingest(c, items, 2)
    assert (r1["inserted"], r1["duplicates"]) == (2, 0)
    r2 = ing.ingest(c, items, 2)
    assert (r2["inserted"], r2["duplicates"]) == (0, 2)
    assert c.execute("select count(*) from source_items").fetchone()[0] == 2
    assert c.execute("select count(*) from source_item_versions").fetchone()[0] == 2
    assert c.execute("select count(*) from collector_runs where job='investify_announcements'").fetchone()[0] == 2


def test_stored_row_shape_and_unlinked_tickers():
    c = db(); ing.ingest(c, parser.parse_announcements(HTML))
    r = c.execute("select * from source_items where external_id='psx_filing:288838'").fetchone()
    assert (r["source_id"], r["retrieval_method"], r["access_status"], r["document_type"]) == ("investify", "html", "restricted", "html" and "announcement")
    assert r["permitted_excerpt"] is None and r["content_location"] is None
    assert "PROPRIETARY" not in str(dict(r)).upper()


def test_changed_title_appends_version_not_row():
    c, items = db(), parser.parse_announcements(HTML)
    ing.ingest(c, items)
    items[0]["title"] = "SSGC publishes Annual Report 2026 (corrected)"
    r = ing.ingest(c, items)
    assert r["new_versions"] == 1 and r["inserted"] == 0
    assert c.execute("select count(*) from source_items").fetchone()[0] == 2
    assert c.execute("select max(version_no) from source_item_versions").fetchone()[0] == 2


def test_dry_plan_is_read_only():
    c, items = db(), parser.parse_announcements(HTML)
    p = ing.plan(c, items)
    assert len(p["new"]) == 2 and c.execute("select count(*) from source_items").fetchone()[0] == 0
    assert c.execute("select count(*) from collector_runs").fetchone()[0] == 0


def test_guards():
    import pytest
    with pytest.raises(ing.IngestError): ing.ingest(db(), [{}] * 61)
    c = db(); c.execute("delete from sources")
    with pytest.raises(ing.IngestError): ing.ingest(c, [])


def test_backfill_names_updates_only_metadata_and_logs_exception():
    c = db(); items = parser.parse_announcements(HTML)
    nameless = [dict(i, company_name=None) for i in items]
    ing.ingest(c, nameless)                                  # simulate the original 21 name-less rows
    before = {r[0]: r[1:] for r in c.execute("select source_item_id,content_sha256,title,external_id,collected_at_utc from source_items")}
    d = ing.backfill_names(c, items, dry_run=True)
    assert len(d["updated"]) == 2 and c.execute("select count(*) from collector_runs where job='investify_name_backfill'").fetchone()[0] == 0
    r = ing.backfill_names(c, items)
    assert len(r["updated"]) == 2
    assert {x[0]: x[1:] for x in c.execute("select source_item_id,content_sha256,title,external_id,collected_at_utc from source_items")} == before
    assert c.execute("select json_extract(source_metadata_json,'$.company_name') from source_items where external_id='psx_filing:288838'").fetchone()[0] == "TPL Properties Ltd"
    run = c.execute("select status,items_accepted,errors from collector_runs where job='investify_name_backfill'").fetchone()
    assert run[0] == "succeeded" and run[1] == 2 and "append-only exception" in run[2]
    again = ing.backfill_names(c, items)
    assert len(again["updated"]) == 0 and again["already_set"] == 2
    assert c.execute("select count(*) from source_items").fetchone()[0] == 2          # never inserts


def test_backfill_skips_conflicts_and_unmatched():
    c = db(); items = parser.parse_announcements(HTML)
    ing.ingest(c, items)                                     # rows already carry the names
    items[0]["company_name"] = "Different Name Ltd"
    r = ing.backfill_names(c, items)
    assert len(r["conflict"]) == 1 and len(r["updated"]) == 0
    items[1]["psx_id"] = "999"
    assert len(ing.backfill_names(c, items)["unmatched"]) == 1
