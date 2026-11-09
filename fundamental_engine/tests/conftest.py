import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.db import sqlite_connect


@pytest.fixture
def db():
    """In-memory DB with the production baseline schema (tables, indexes, views, triggers) and foreign keys ON."""
    d = sqlite_connect()
    d.script((ROOT / "migrations" / "0010_baseline_snapshot.sql").read_text())
    d.execute("PRAGMA foreign_keys=ON")
    return d


def add_source(db, source_id="src1", access="verified_permitted", stype="exchange"):
    db.execute("INSERT INTO sources(source_id,name,source_type,access_status,created_at_utc,updated_at_utc) "
               "VALUES(?,?,?,?,'t','t')", (source_id, source_id, stype, access))


def add_item(db, source_id="src1", ext="x1", title="t"):
    return db.execute("INSERT INTO source_items(source_id,external_id,title,collected_at_utc,content_sha256) "
                      "VALUES(?,?,?,'t',?)", (source_id, ext, title, "a" * 64)).lastrowid


def add_company(db, ticker="OGDC"):
    cid = f"cmp-{ticker.lower()}"
    db.execute("INSERT INTO companies(company_id,legal_name,listing_status,created_at_utc,updated_at_utc) "
               "VALUES(?,?,'listed','t','t')", (cid, ticker + " Ltd"))
    db.execute("INSERT INTO company_identifiers(company_id,id_type,value,verified_at_utc) VALUES(?,'psx_ticker',?,'t')",
               (cid, ticker))
    return cid
