"""scan_cache_engine.py — generic named-cache store for every expensive
full-universe analysis (whole-market DSS scan, pattern backtest, walk-forward
validation, regime-split backtest, PSX edge discovery, failure analysis,
volume/accumulation alerts). Each is computed once by a background scheduler
(see app.py's _start_background_refresh_loops) on its own sensible cadence
and served instantly from here — not recomputed on every Streamlit click,
and not gated behind a manual "enter admin token" button for routine use.

Different analyses genuinely need different refresh cadences:
  - dss_scan / alerts: depend partly on TODAY's live volume/price, refreshed
    every SCAN_REFRESH_INTERVAL (default 30 min).
  - backtest_run / walkforward / regime_split / edge_discovery: computed from
    YEARS of daily bars that don't shift within a day — refreshed on
    HEAVY_REFRESH_INTERVAL (default once per day).
  - failure_analysis: reads the audit trail, cheap, refreshed alongside the
    heavy group.
This module doesn't decide cadence — app.py's scheduler does — it just
stores whatever was last computed for each named key, with its age.
"""

import json
import os
import time
from datetime import datetime, timezone

import turso_db

# dss_scan/alerts cadence: partly live-data-dependent.
DEFAULT_MAX_AGE_SECONDS = int(os.getenv("PSX_SCAN_MAX_AGE", "1800"))
# backtest/walkforward/regime-split/edge-discovery/failure-analysis cadence:
# pure daily-bar history, doesn't shift within a day.
HEAVY_MAX_AGE_SECONDS = int(os.getenv("PSX_HEAVY_MAX_AGE", str(24 * 3600)))


def _conn():
    c = turso_db.get_connection()
    return c


_tables_ensured = False

def ensure_tables():
    # Ran this CREATE TABLE IF NOT EXISTS on every save()/latest() call --
    # free with local sqlite3, a real Turso round trip once db access went
    # over the network. Run once per process.
    global _tables_ensured
    if _tables_ensured:
        return
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS analysis_cache(
            cache_key TEXT PRIMARY KEY,
            run_at TEXT, run_at_epoch REAL, result_json TEXT);
        """)
        c.commit()
    _tables_ensured = True


def save(cache_key, result):
    ensure_tables()
    now = time.time()
    with _conn() as c:
        c.execute("""INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
                     VALUES(?,?,?,?)
                     ON CONFLICT(cache_key) DO UPDATE SET
                       run_at=excluded.run_at, run_at_epoch=excluded.run_at_epoch,
                       result_json=excluded.result_json""",
                  (cache_key, datetime.now(timezone.utc).isoformat(), now, json.dumps(result)))
        c.commit()


def latest(cache_key):
    ensure_tables()
    with _conn() as c:
        row = c.execute("SELECT * FROM analysis_cache WHERE cache_key=?", (cache_key,)).fetchone()
    if not row:
        return None
    result = json.loads(row["result_json"])
    result["_cache_run_at"] = row["run_at"]
    result["_cache_age_seconds"] = round(time.time() - row["run_at_epoch"])
    return result


def latest_many(cache_keys):
    """Same result as calling latest() once per key, but as ONE round trip
    when running against Turso -- built for /health, which used to check
    8 cache keys sequentially (8 separate network round trips just to
    report freshness). No-op optimization on the local sqlite3 path, where
    those round trips were already free."""
    ensure_tables()
    if not turso_db.USING_TURSO:
        return {k: latest(k) for k in cache_keys}
    conn = turso_db.get_connection()
    queries = [("SELECT * FROM analysis_cache WHERE cache_key=?", (k,)) for k in cache_keys]
    results = conn.batch_query(queries)
    out = {}
    for k, rows in zip(cache_keys, results):
        if not rows:
            out[k] = None
            continue
        row = rows[0]
        result = json.loads(row["result_json"])
        result["_cache_run_at"] = row["run_at"]
        result["_cache_age_seconds"] = round(time.time() - row["run_at_epoch"])
        out[k] = result
    return out


def status(cache_key):
    cached = latest(cache_key)
    if not cached:
        return {"status": "never_run", "cache_key": cache_key}
    return {"status": "ok", "cache_key": cache_key, "run_at": cached.get("_cache_run_at"),
            "age_seconds": cached.get("_cache_age_seconds")}


def is_fresh(cache_key, max_age_seconds):
    cached = latest(cache_key)
    return cached is not None and cached["_cache_age_seconds"] < max_age_seconds


# ---------------------------------------------------------------------------
# dss_scan-specific helpers (kept as named wrappers — same behavior as before
# this module was generalized, so nothing calling the old names breaks).
def save_scan(result):
    save("dss_scan", result)


def latest_scan():
    return latest("dss_scan")


def refresh_live_overlay(cached_result, quote_lookup):
    """Patches current price/pct from a fresh market_watch() snapshot onto
    every entry in a cached scan's bucket lists — the cheap part that
    genuinely should update every few minutes, without rerunning Wyckoff/
    candlestick/evidence-score analysis for a bar that hasn't changed."""
    bucket_keys = [k for k in cached_result if k.startswith("top_10_")]
    for key in bucket_keys:
        for entry in cached_result.get(key, []):
            q = quote_lookup.get(entry.get("symbol"))
            if q:
                entry["price"] = q.get("price", entry.get("price"))
                entry["pct"] = q.get("pct", entry.get("pct"))
    return cached_result
