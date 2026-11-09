"""Initial watchlist = the latest recorded KSE-30 membership (index_memberships, observed from the PSX data portal
page on 2026-11-07), restricted to companies present in the master. Derived from recorded data, not typed from memory.
Idempotent: UNIQUE(item_type, value) + INSERT OR IGNORE."""
from datetime import datetime, timezone


def kse30_tickers(db, index_code="KSE30"):
    rows = db.execute(
        "SELECT ci.value AS ticker FROM index_memberships m "
        "JOIN company_identifiers ci ON ci.company_id=m.company_id AND ci.id_type='psx_ticker' AND ci.valid_to IS NULL "
        "WHERE m.index_code=? AND m.observed_at_utc=(SELECT MAX(observed_at_utc) FROM index_memberships WHERE index_code=?) "
        "ORDER BY ci.value", (index_code, index_code)).rows
    return [r["ticker"] for r in rows]


def init_watchlist(db, index_code="KSE30", dry_run=False, now=None):
    tickers = kse30_tickers(db, index_code)
    existing = {r["value"] for r in db.execute("SELECT value FROM user_watchlist WHERE item_type='ticker'").rows}
    new = [t for t in tickers if t not in existing]
    if not dry_run and new:
        stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.batch([("INSERT OR IGNORE INTO user_watchlist(item_type,value,alert_preferences_json,enabled,created_at_utc) "
                   "VALUES('ticker',?,NULL,1,?)", (t, stamp)) for t in new])
    return {"index": index_code, "members": len(tickers), "already_present": len(tickers) - len(new), "added": 0 if dry_run else len(new),
            "would_add": len(new) if dry_run else 0}
