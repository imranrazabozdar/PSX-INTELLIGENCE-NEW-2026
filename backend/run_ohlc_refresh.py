#!/usr/bin/env python3
"""
Daily OHLC data refresh — fetches latest daily bars from PSX Data Portal
(dps.psx.com.pk) and stores them in the daily_ohlc table in Turso.

This runs in GitHub Actions (which CAN reach dps.psx.com.pk, unlike
Streamlit Cloud whose datacenter IPs are blocked by PSX).

Scoped to the FIRE Engine + Wyckoff universe (fire_engine/config/
fire_config.yaml's stocks.universe, ~150 symbols) -- NOT the whole PSX
market. This used to dynamically fetch PSX's full ~750-symbol equity
list to also feed the separate whole-market pattern-scan/backtest
features (bullish engulfing, MHarris, MACD+EMA200, etc.), but that meant
a symbol newly added to the FIRE/Wyckoff universe could sit behind
hundreds of alphabetically-earlier symbols nobody here needed, taking
days to get its initial backfill purely by chance of its ticker's first
letter -- and the other ~600 symbols were never used by anything this
project's user actually wanted, just data overload. Restricted to this
universe by explicit request (2026-09-07): the whole-market pattern-scan
features will stop getting new data for every symbol outside this list;
their results for those symbols will go stale rather than update.

For initial backfill: fetches full history (up to 5 years) for symbols
that have no data yet. For subsequent runs: fetches only the last 5 days
to pick up new bars efficiently.
"""

import os
import time
import logging
from datetime import datetime, timedelta, timezone

import sys
from pathlib import Path

import yaml

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import turso_db
import dps_scraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

_FIRE_CONFIG_PATH = Path(__file__).parent.parent / "fire_engine" / "config" / "fire_config.yaml"


def load_universe_symbols() -> list[str]:
    """The FIRE Engine + Wyckoff universe (fire_engine/config/fire_config.yaml's
    stocks.universe) -- the only symbols this script now fetches. Raises if
    the config can't be read: unlike the old whole-market fetch (a network
    call with a legitimate fallback for transient PSX outages), a missing or
    malformed local config file is a real bug, not a transient condition, and
    silently falling back to some other hardcoded list would just reintroduce
    the same "scanning symbols nobody asked for" problem this change removed."""
    with open(_FIRE_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return sorted({str(s).upper() for s in cfg["stocks"]["universe"]})


def ensure_ohlc_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_ohlc(
      symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
      source TEXT, PRIMARY KEY(symbol, trade_date))""")
    conn.commit()


def get_last_stored_date(conn, symbol):
    row = conn.execute(
        "SELECT MAX(trade_date) as mx FROM daily_ohlc WHERE symbol = ?",
        (symbol.upper(),)
    ).fetchone()
    if row:
        mx = row["mx"] if isinstance(row, dict) else row[0]
        return mx
    return None


MAX_RUNTIME_SECONDS = int(os.getenv("PSX_OHLC_REFRESH_BUDGET_SECONDS", str(20 * 60)))


def main():
    try:
        db_status = turso_db.status()
        logger.info(f"Database: {db_status['backend']}")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return 1

    conn = turso_db.get_connection()
    ensure_ohlc_table(conn)

    try:
        symbols = load_universe_symbols()
    except Exception as e:
        logger.error(f"Could not load FIRE/Wyckoff universe from {_FIRE_CONFIG_PATH}: "
                     f"{type(e).__name__}: {e}")
        return 1

    def _count_universe_coverage():
        placeholders = ",".join("?" for _ in symbols)
        row = conn.execute(
            f"SELECT COUNT(DISTINCT symbol) as cnt FROM daily_ohlc WHERE symbol IN ({placeholders})",
            tuple(symbols),
        ).fetchone()
        return row["cnt"] if isinstance(row, dict) else row[0]

    logger.info(f"Existing universe symbols already in daily_ohlc: {_count_universe_coverage()}/{len(symbols)}")
    logger.info(f"Will process {len(symbols)} symbols (FIRE/Wyckoff universe only -- "
                f"daily_ohlc may still hold older, no-longer-refreshed rows for other symbols)")

    # Even scoped to ~150 symbols, an all-new universe's first-ever backfill
    # (5 years of history each, ~20-25s/symbol once the daily_ohlc table is
    # empty for them) can run past a single CI job's turn. Rather than let
    # the job get hard-cancelled mid-symbol (which starves every LATER
    # workflow step -- pattern scans, backtests -- of a turn, every single
    # run, forever), this script self-stops within a time budget and exits
    # cleanly so the rest of the workflow always runs. Each run persists what
    # it fetched (INSERT OR IGNORE) and the next run resumes from
    # get_last_stored_date(), so coverage grows run over run. In steady
    # state (all 150 already backfilled), a run is just ~150 quick
    # last-day refreshes -- well under the budget.
    run_start = time.monotonic()

    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    refreshed = 0
    new_backfilled = 0
    failed = 0
    skipped = 0
    budget_exhausted = False

    for i, symbol in enumerate(symbols):
        if time.monotonic() - run_start > MAX_RUNTIME_SECONDS:
            logger.info(f"Time budget ({MAX_RUNTIME_SECONDS}s) reached after {i}/{len(symbols)} "
                        f"symbols — stopping here so pattern scans/backtests still get a turn "
                        f"this run. Remaining symbols pick up on the next scheduled run.")
            budget_exhausted = True
            break
        try:
            last_date = get_last_stored_date(conn, symbol)

            if last_date and last_date >= end_date:
                skipped += 1
                continue

            is_backfill = not last_date
            if last_date:
                start_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                if (i + 1) % 50 == 0 or i == 0:
                    logger.info(f"  [{i+1}/{len(symbols)}] {symbol}: refreshing from {start_date}")
            else:
                start_date = (datetime.now(timezone.utc) - timedelta(days=1827)).strftime("%Y-%m-%d")
                logger.info(f"  [{i+1}/{len(symbols)}] {symbol}: initial backfill from {start_date}")

            df = dps_scraper.fetch_psx_dps_ohlc(symbol, start_date=start_date, end_date=end_date)

            if df.empty:
                logger.info(f"    {symbol}: no data returned")
                failed += 1
                time.sleep(0.5)
                continue

            good = []
            for _, x in df.iterrows():
                try:
                    o, h, l, c = float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])
                    if not (l <= min(o, c) <= max(o, c) <= h) or c <= 0:
                        continue
                    good.append((symbol.upper(), x["date"], o, h, l, c,
                                 float(x["volume"] or 0), "PSX Data Portal (dps.psx.com.pk)"))
                except Exception:
                    continue

            if good:
                if turso_db.USING_TURSO and hasattr(conn, 'batch_query'):
                    sql = "INSERT OR IGNORE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)"
                    CHUNK = 100
                    for ci in range(0, len(good), CHUNK):
                        conn.batch_query([(sql, p) for p in good[ci:ci + CHUNK]])
                else:
                    conn.executemany("INSERT OR IGNORE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)", good)
                    conn.commit()

                if last_date:
                    refreshed += 1
                else:
                    new_backfilled += 1
                logger.info(f"    {symbol}: stored {len(good)} bars")
            else:
                failed += 1

            time.sleep(1.0 if is_backfill else 0.3)

        except Exception as e:
            logger.warning(f"    {symbol}: failed — {type(e).__name__}: {e}")
            failed += 1
            time.sleep(0.5)

    final_universe_count = _count_universe_coverage()

    print("")
    logger.info(f"OHLC refresh {'stopped at time budget' if budget_exhausted else 'complete'}!")
    logger.info(f"  New backfills: {new_backfilled}")
    logger.info(f"  Refreshed: {refreshed}")
    logger.info(f"  Skipped (up to date): {skipped}")
    logger.info(f"  Failed/no data: {failed}")
    logger.info(f"  Universe symbols with data in DB: {final_universe_count} / {len(symbols)} target")
    if budget_exhausted:
        logger.info(f"  {len(symbols) - final_universe_count} universe symbols still need their "
                    f"initial backfill — will continue on the next scheduled run.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
