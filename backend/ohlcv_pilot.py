"""PILOT-2026-11-09-03: micro-batch daily OHLCV from the SCS chart feed (TradingView UDF)
into market_bars. Last 30 trading days per symbol, <=500 rows, honest User-Agent.

Usage: python backend/ohlcv_pilot.py --dry-run | --live
(PILOT-2026-11-09-02, the dps.psx.com.pk route, was abandoned: see docs/SOURCE_PERMISSION_LOG.md)
"""
import argparse
import random
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

APPROVAL_ID = "PILOT-2026-11-09-03"
SOURCE_ID = "scs_chart"  # existing, owner-approved source row
HISTORY_URL = "https://chart.scstrade.com/history"
SYMBOLS = ["APL", "BAHL", "PACE", "DFML"]
TRADING_DAYS = 30
LOOKBACK_DAYS = 70  # calendar window wide enough to contain 30 trading days
ROW_CAP = 500
REQUEST_CAP = 10
JITTER_MIN, JITTER_MAX = 3.5, 8.5
USER_AGENT = "Mozilla/5.0 (compatible; PSX-NEWS-INTELLIGENCE research bot, contact owner)"
EXCHANGE_DELAY = timedelta(minutes=15)
PKT = timezone(timedelta(hours=5))


class RequestBudget:
    def __init__(self, cap=REQUEST_CAP):
        self.cap, self.used = cap, 0

    def take(self):
        if self.used >= self.cap:
            raise RuntimeError(f"request cap {self.cap} reached")
        self.used += 1


def parse_udf(payload, symbol):
    """UDF {s,t,o,h,l,c,v} -> list of row dicts; invalid rows skipped."""
    if payload.get("s", "ok") != "ok" or not payload.get("t"):
        return []
    rows = []
    for t, o, h, l, c, v in zip(payload["t"], payload["o"], payload["h"],
                                payload["l"], payload["c"], payload["v"]):
        d = datetime.fromtimestamp(t, timezone.utc).astimezone(PKT).strftime("%Y-%m-%d")
        rows.append({"symbol": symbol, "date": d, "ts": t, "open": float(o), "high": float(h),
                     "low": float(l), "close": float(c), "volume": float(v or 0)})
    return rows


def drop_undelayed(rows, now=None):
    """Exclude the current PKT session and anything younger than the 15-min delay."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(PKT).strftime("%Y-%m-%d")
    return [r for r in rows if r["date"] < today
            and datetime.fromtimestamp(r["ts"], timezone.utc) + timedelta(days=1) <= now - EXCHANGE_DELAY]


def last_n(rows, n=TRADING_DAYS):
    return sorted(rows, key=lambda r: r["date"])[-n:]


def fetch_symbol(symbol, budget, session=None, timeout=25, now=None):
    budget.take()
    now = now or datetime.now(timezone.utc)
    get = (session or requests).get
    resp = get(HISTORY_URL, params={"symbol": symbol, "resolution": "D",
                                    "from": int((now - timedelta(days=LOOKBACK_DAYS)).timestamp()),
                                    "to": int(now.timestamp())},
               headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return parse_udf(resp.json(), symbol)


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _n(row):
    return row["n"] if isinstance(row, dict) else row[0]


def ingest(conn, rows, requests_made=0):
    """INSERT OR IGNORE 1d bars into market_bars under one collector_runs row.
    Requires the source row to exist; never creates sources or overwrites bars."""
    if len(rows) > ROW_CAP:
        raise RuntimeError(f"{len(rows)} rows exceeds approved write cap {ROW_CAP}")
    if not conn.execute("SELECT 1 FROM sources WHERE source_id=?", (SOURCE_ID,)).fetchone():
        raise RuntimeError(f"source {SOURCE_ID} missing")
    started = _utcnow()
    run_id = conn.execute(
        "INSERT INTO collector_runs(job,source_id,started_at_utc,status,http_requests,log_reference) "
        "VALUES(?,?,?,?,?,?)", (APPROVAL_ID, SOURCE_ID, started, "running", requests_made, APPROVAL_ID)).lastrowid
    cnt = lambda: _n(conn.execute("SELECT COUNT(*) AS n FROM market_bars WHERE source_id=? AND symbol IN (?,?,?,?)",
                                  (SOURCE_ID, *SYMBOLS)).fetchone())
    n0, good, rejected = cnt(), [], 0
    for r in rows:
        if not (r["low"] > 0 and r["high"] >= max(r["open"], r["close"], r["low"])
                and r["low"] <= min(r["open"], r["close"]) and r["volume"] >= 0):
            rejected += 1
            continue
        good.append((SOURCE_ID, r["symbol"], "1d", r["date"] + "T00:00:00Z", r["date"], r["open"],
                     r["high"], r["low"], r["close"], r["volume"], started, run_id))
    conn.executemany(
        "INSERT OR IGNORE INTO market_bars(source_id,symbol,timeframe,bar_start_utc,session_date_pkt,"
        "open,high,low,close,volume,retrieved_at_utc,collection_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", good)
    inserted = cnt() - n0
    conn.execute(
        "UPDATE collector_runs SET finished_at_utc=?,status=?,items_fetched=?,items_accepted=?,"
        "items_rejected=?,items_duplicate=? WHERE run_id=?",
        (_utcnow(), "succeeded", len(rows), inserted, rejected, len(good) - inserted, run_id))
    conn.commit()
    return inserted


def run(live, conn=None, sleep=time.sleep, rng=random.uniform, session=None):
    if not live:
        print(f"{APPROVAL_ID} DRY RUN: {len(SYMBOLS)} GETs to {HISTORY_URL} (cap {REQUEST_CAP}), "
              f"last {TRADING_DAYS} bars each, <= {ROW_CAP} rows, jitter {JITTER_MIN}-{JITTER_MAX}s, UA={USER_AGENT!r}")
        print("  no network, no DB; would INSERT OR IGNORE into market_bars (source scs_chart)")
        return {"mode": "dry", "requests": 0, "rows": 0}
    budget, allrows = RequestBudget(), []
    for i, s in enumerate(SYMBOLS):
        if i:
            sleep(rng(JITTER_MIN, JITTER_MAX))
        rows = last_n(drop_undelayed(fetch_symbol(s, budget, session)))
        print(f"{s}: {len(rows)} bars {rows[0]['date'] if rows else '-'}..{rows[-1]['date'] if rows else '-'}")
        allrows += rows
    n = ingest(conn, allrows, budget.used) if allrows else 0
    return {"mode": "live", "requests": budget.used, "fetched": len(allrows), "inserted": n}


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
            sys.exit("refusing live run: Turso not configured (would write local SQLite)")
        c = turso_db.get_connection()
        if isinstance(c, sqlite3.Connection):
            sys.exit("refusing live run: Turso connection failed (local SQLite fallback)")
    print(run(a.live, c))
