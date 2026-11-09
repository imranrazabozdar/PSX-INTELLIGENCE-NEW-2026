import json
from pathlib import Path

from core import migrate
from core.db import sqlite_connect

MIG = Path(__file__).resolve().parent.parent / "migrations"


def test_baseline_matches_live_manifest(db):
    manifest = json.loads((MIG / "baseline_manifest.json").read_text())["tables"]
    live_tables = {r["name"] for r in db.execute("select name from sqlite_master where type='table'").rows}
    assert live_tables == set(manifest) and len(manifest) == 56
    for t, cols in manifest.items():
        got = [r["name"] for r in db.execute(f'pragma table_info("{t}")').rows]
        assert got == cols, t


def test_baseline_keeps_provenance_triggers(db):
    n = db.execute("select count(*) n from sqlite_master where type='trigger'").one()["n"]
    assert n == 90
    db.execute("INSERT INTO sources(source_id,name,source_type,created_at_utc,updated_at_utc) VALUES('s','s','other','t','t')")
    db.execute("INSERT INTO source_items(source_id,external_id,collected_at_utc,content_sha256) VALUES('s','e','t',?)", ("a" * 64,))
    for sql in ("DELETE FROM source_items", "UPDATE source_items SET content_sha256='%s'" % ("b" * 64)):
        try:
            db.execute(sql)
            assert False, "trigger should have blocked: " + sql
        except Exception as e:
            assert "append" in str(e) or "immutable" in str(e)


def test_fresh_db_applies_baseline_once():
    d = sqlite_connect()
    assert [v for v, _ in migrate.apply(d, dry_run=True)] == [10]
    migrate.apply(d)
    assert d.execute("select version,name from schema_migrations").one() == {"version": 10, "name": "baseline_snapshot"}
    assert migrate.apply(d, dry_run=True) == []


def test_live_style_db_never_reapplies_baseline(db):
    db.execute("INSERT INTO schema_migrations(version,name,checksum,applied_at_utc,result) VALUES(10,'market_ohlcv','" + "e" * 64 + "','t','applied')")
    assert migrate.apply(db, dry_run=True) == []
