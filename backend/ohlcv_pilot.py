"""PILOT-2026-11-09-02: capped, polite OHLCV fetch from dps.psx.com.pk into market_bars.

Usage: python -m backend.ohlcv_pilot --dry-run | --live
Dry run touches neither network nor database.
"""
import argparse
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

SCHEMA = """CREATE TABLE IF NOT EXISTS market_bars(
    symbol TEXT NOT NULL, date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    source TEXT, approval_id TEXT, fetched_at TEXT,
    PRIMARY KEY(symbol, date))"""


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


def ingest(conn, rows, fetched_at=None):
    conn.execute(SCHEMA)
    ts = fetched_at or datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO market_bars(symbol,date,open,high,low,close,volume,"
        "source,approval_id,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        [(r["symbol"], r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"],
          "dps.psx.com.pk", APPROVAL_ID, ts) for r in rows])
    conn.commit()
    return len(rows)


def run(live, conn=None, sleep=time.sleep, rng=random.uniform):
    plan = [f"{APPROVAL_ID}: {len(SYMBOLS)} requests (cap {REQUEST_CAP}), jitter {JITTER_MIN}-{JITTER_MAX}s, UA={USER_AGENT!r}"]
    if not live:
        plan += [f"  would POST {DPS_HISTORICAL_URL} symbol={s}" for s in SYMBOLS]
        plan.append("  would upsert into market_bars (dry run: no network, no DB)")
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
        c = turso_db.get_connection()
    print(run(a.live, c))
