import sys
from pathlib import Path

from core.watchlist import init_watchlist, kse30_tickers
from tests.conftest import add_company, add_item, add_source

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import regulator_review_tracking as rt


def seed(db):
    add_source(db); item = add_item(db)
    for t in ("OGDC", "HBL", "LUCK"):
        cid = add_company(db, t)
        db.execute("INSERT INTO index_memberships(index_code,company_id,observed_at_utc,source_item_id) VALUES('KSE30',?,'2026-11-07T00:00:00Z',?)", (cid, item))
    cid = add_company(db, "OLD")   # member only in an older snapshot -> excluded
    db.execute("INSERT INTO index_memberships(index_code,company_id,observed_at_utc,source_item_id) VALUES('KSE30',?,'2026-01-01T00:00:00Z',?)", (cid, item))
    add_company(db, "OTHER")        # not an index member


def test_watchlist_from_latest_membership_idempotent(db):
    seed(db)
    assert kse30_tickers(db) == ["HBL", "LUCK", "OGDC"]
    assert init_watchlist(db, dry_run=True)["would_add"] == 3 and db.execute("select count(*) n from user_watchlist").one()["n"] == 0
    assert init_watchlist(db)["added"] == 3
    again = init_watchlist(db)
    assert again["added"] == 0 and again["already_present"] == 3
    r = db.execute("select item_type,enabled,alert_preferences_json from user_watchlist limit 1").one()
    assert r == {"item_type": "ticker", "enabled": 1, "alert_preferences_json": None}


def test_regulator_tracking_appends_once_and_keeps_status(db):
    for sid in ("sbp", "secp"):
        db.execute("INSERT INTO sources(source_id,name,source_type,access_status,lifecycle_status,review_notes,created_at_utc,updated_at_utc) "
                   "VALUES(?,?,'official_regulator','blocked','BLOCKED','403 to bots','t','t')", (sid, sid))
    assert rt.track(db) == {"sbp": "would update", "secp": "would update"}
    assert rt.track(db, apply=True) == {"sbp": "updated", "secp": "updated"}
    assert rt.track(db, apply=True) == {"sbp": "already tracked", "secp": "already tracked"}
    r = db.execute("select access_status,lifecycle_status,review_notes from sources where source_id='sbp'").one()
    assert r["access_status"] == "blocked" and r["lifecycle_status"] == "BLOCKED" and r["review_notes"].startswith("403 to bots")
