"""PILOT-2026-11-09-02: capped, polite OHLCV fetch from dps.psx.com.pk into daily_ohlc.

Usage: python -m backend.ohlcv_pilot --dry-run | --live
Dry run touches neither network nor database.
"""
import argparse
import sqlite3
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    from backend.dps_scraper import DPS_HISTORICAL_URL, _parse_historical_table
except ImportError:  # run from backend/
    from dps_scraper import DPS_HISTORICAL_URL, _parse_historical_table

APPROVAL_ID = "PILOT-2026-11-09-02"
SYMBOLS = ["APL", "BAHL", "PACE", "DFML"]
REQUEST_CAP = 10
JITTER_MIN, JITTER_MAX = 3.5, 8.5
USER_AGENT = "PSX-NEWS-INTELLIGENCE research bot, contact owner"
EXCHANGE_DELAY = timedelta(minutes=15)
PKT = timezone(timedelta(hours=5))

TABLE = "daily_ohlc"  # existing table: symbol, trade_date, o, h, l, c, volume, source
SOURCE = "psx_dps"


class RequestBudget:
    def __init__(self, cap=REQUEST_CAP):
        self.cap, self.used = cap, 0

    def take(self):
        if self.used >= self.cap:
            raise RuntimeError(f"request cap {self.cap} reached")
        self.used += 1


def drop_undelayed(rows, now=None):
    """Exclude the current PKT session's bar: it is live, not yet 15-min-delayed final."""
    now = (now or datetime.now(timezone.utc)).astimezone(PKT)
    today = now.strftime("%Y-%m-%d")
    return [r for r in rows if r["date"] < today]


def fetch_symbol(symbol, budget, session=None, timeout=20):
    budget.take()
    post = (session or requests).post
    resp = post(DPS_HISTORICAL_URL,
                data={"symbol": symbol, "date": datetime.now(PKT).strftime("%Y-%m-%d")},
                headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return _parse_historical_table(resp.text, symbol)


def ingest(conn, rows):
    """INSERT OR IGNORE into daily_ohlc: fills gaps, never overwrites existing rows."""
    before = conn.execute("SELECT COUNT(*) FROM daily_ohlc").fetchone()[0]
    conn.executemany(
        "INSERT OR IGNORE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)",
        [(r["symbol"], r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"], SOURCE)
         for r in rows])
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM daily_ohlc").fetchone()[0] - before


def run(live, conn=None, sleep=time.sleep, rng=random.uniform):
    plan = [f"{APPROVAL_ID}: {len(SYMBOLS)} requests (cap {REQUEST_CAP}), jitter {JITTER_MIN}-{JITTER_MAX}s, UA={USER_AGENT!r}"]
    if not live:
        plan += [f"  would POST {DPS_HISTORICAL_URL} symbol={s}" for s in SYMBOLS]
        plan.append("  would upsert into daily_ohlc (dry run: no network, no DB)")
        print("\n".join(plan))
        return {"mode": "dry", "requests": 0, "rows": 0}
    budget, allrows = RequestBudget(), []
    for i, s in enumerate(SYMBOLS):
        if i:
            sleep(rng(JITTER_MIN, JITTER_MAX))
        rows = drop_undelayed(fetch_symbol(s, budget))
        print(f"{s}: {len(rows)} rows")
        allrows += rows
    n = ingest(conn, allrows) if allrows else 0
    return {"mode": "live", "requests": budget.used, "rows": n}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--live", action="store_true")
    a = ap.parse_args()
    c = None
    if a.live:
        try:
            from backend import turso_db
        except ImportError:
            import turso_db
        if not turso_db.USING_TURSO:
            sys.exit('refusing live run: Turso not configured (would write local SQLite)')
        c = turso_db.get_connection()
        if isinstance(c, sqlite3.Connection):
            sys.exit('refusing live run: Turso connection failed (local SQLite fallback)')
    print(run(a.live, c))
