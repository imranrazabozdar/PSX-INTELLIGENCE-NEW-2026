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
USER_AGENT = "Mozilla/5.0 (compatible; PSX-NEWS-INTELLIGENCE research bot, contact owner)"  # amended per owner, see docs/SOURCE_PERMISSION_LOG.md
EXCHANGE_DELAY = timedelta(minutes=15)
PKT = timezone(timedelta(hours=5))

SOURCE_ID = "psx_dps"
TABLE = "market_bars"


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


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_source(conn):
    """Use an existing psx_dps source row if present; otherwise create it DISABLED
    (the scheduled collector must not pick it up; this is a one-off pilot)."""
    if conn.execute("SELECT 1 FROM sources WHERE source_id=?", (SOURCE_ID,)).fetchone():
        return False
    now = _utcnow()
    conn.execute(
        "INSERT INTO sources(source_id,name,source_type,domain,official_url,feed_url,"
        "reliability_tier,access_method,access_status,enabled,content_format,adapter,"
        "category,subcategory,geographic_coverage,terms_status,lifecycle_status,notes,"
        "created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (SOURCE_ID, "PSX Data Portal historical daily OHLCV", "exchange", "dps.psx.com.pk",
         "https://dps.psx.com.pk/", "https://dps.psx.com.pk/historical", "primary_official",
         "html_permitted", "unverified", 0, "html", "dps_historical", "market_data",
         "PSX daily OHLCV (pilot)", "Pakistan", "not_reviewed", "APPROVED",
         f"One-off owner-approved pilot {APPROVAL_ID}; kept disabled. See docs/SOURCE_PERMISSION_LOG.md.",
         now, now))
    return True


def ingest(conn, rows, requests_made=0):
    """INSERT OR IGNORE 1d bars into market_bars under one collector_runs row."""
    ensure_source(conn)
    started = _utcnow()
    cur = conn.execute(
        "INSERT INTO collector_runs(job,source_id,started_at_utc,status,http_requests,log_reference) "
        "VALUES(?,?,?,?,?,?)", (APPROVAL_ID, SOURCE_ID, started, "running", requests_made, APPROVAL_ID))
    run_id = cur.lastrowid
    count = lambda: conn.execute("SELECT COUNT(*) AS n FROM market_bars WHERE source_id=?",
                                 (SOURCE_ID,)).fetchone()
    n0 = count(); n0 = n0["n"] if isinstance(n0, dict) else n0[0]
    good, rejected = [], 0
    for r in rows:
        if not (r["low"] > 0 and r["high"] >= max(r["open"], r["close"], r["low"])
                and r["low"] <= min(r["open"], r["close"]) and r["volume"] >= 0):
            rejected += 1
            continue
        good.append((SOURCE_ID, r["symbol"], "1d", r["date"] + "T00:00:00Z", r["date"],
                     r["open"], r["high"], r["low"], r["close"], r["volume"], started, run_id))
    conn.executemany(
        "INSERT OR IGNORE INTO market_bars(source_id,symbol,timeframe,bar_start_utc,session_date_pkt,"
        "open,high,low,close,volume,retrieved_at_utc,collection_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", good)
    n1 = count(); n1 = n1["n"] if isinstance(n1, dict) else n1[0]
    inserted = n1 - n0
    conn.execute(
        "UPDATE collector_runs SET finished_at_utc=?,status=?,items_fetched=?,items_accepted=?,"
        "items_rejected=?,items_duplicate=? WHERE run_id=?",
        (_utcnow(), "succeeded", len(rows), inserted, rejected, len(good) - inserted, run_id))
    conn.commit()
    return inserted


def run(live, conn=None, sleep=time.sleep, rng=random.uniform):
    plan = [f"{APPROVAL_ID}: {len(SYMBOLS)} requests (cap {REQUEST_CAP}), jitter {JITTER_MIN}-{JITTER_MAX}s, UA={USER_AGENT!r}"]
    if not live:
        plan += [f"  would POST {DPS_HISTORICAL_URL} symbol={s}" for s in SYMBOLS]
        plan.append("  would INSERT OR IGNORE 1d bars into market_bars (dry run: no network, no DB)")
        print("\n".join(plan))
        return {"mode": "dry", "requests": 0, "rows": 0}
    budget, allrows = RequestBudget(), []
    for i, s in enumerate(SYMBOLS):
        if i:
            sleep(rng(JITTER_MIN, JITTER_MAX))
        rows = drop_undelayed(fetch_symbol(s, budget))
        print(f"{s}: {len(rows)} rows")
        allrows += rows
    n = ingest(conn, allrows, budget.used) if allrows else 0
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
