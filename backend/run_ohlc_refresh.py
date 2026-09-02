#!/usr/bin/env python3
"""
Daily OHLC data refresh — fetches latest daily bars from PSX Data Portal
(dps.psx.com.pk) and stores them in the daily_ohlc table in Turso.

This runs in GitHub Actions (which CAN reach dps.psx.com.pk, unlike
Streamlit Cloud whose datacenter IPs are blocked by PSX).

Covers the WHOLE MARKET: dynamically fetches the full equity list from
PSX's /symbols directory (~550 equities, excluding ETFs and debt).

For initial backfill: fetches full history (up to 5 years) for symbols
that have no data yet. For subsequent runs: fetches only the last 5 days
to pick up new bars efficiently.
"""

import time
import logging
from datetime import datetime, timedelta, timezone

import requests
import sys
from pathlib import Path

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

FALLBACK_SYMBOLS = [
    'CNERGY', 'PRL', 'BOP', 'FNEL', 'KEL', 'SSGC', 'PACE', 'WAVESAPP', 'NBP', 'PIBTL',
    'FCL', 'PPL', 'BLUEX', 'AKBL', 'PREMA', 'BECO', 'BAFL', 'LOTCHEM', 'NRL', 'SYS',
    'HUBC', 'AICL', 'THCCL', 'FCCL', 'HASCOL', 'ABL', 'PSO', 'HBL', 'OGDC', 'AVN',
    'SLGL', 'SPSL', 'POWER', 'UBL', 'TRG', 'TOMCL', 'AIRLINK', 'FFL', 'SEARL', 'CLOV',
    'SNBL', 'SNGP', 'MDTL', 'BML', 'BNL', 'BAHL', 'SYM', 'WASL', 'CPHL', 'FFC',
    'MARI', 'MUGHAL', 'BGL', 'GAL', 'GDL', 'YOUW', 'ZAL', 'AGP', 'LOADS', 'KOHC',
    'SAZEW', 'WAHDAT', 'STCL', 'GLAXO', 'TGL', 'MCB', 'JSBL', 'IMAGE', 'SCBPL', 'BOK',
    'AGTL', 'ECPL', 'BIPL', 'HMB', 'FABL', 'SBL', 'ASTL', 'EFERT', 'DGKC', 'LUCK',
    'TBL', 'STL', 'STLR', 'MLCF', 'CHCC', 'WTL', 'PTC', 'QTECH', 'ITANZ',
]


def fetch_all_equity_symbols() -> list[str]:
    """Fetch the full equity list from PSX's /symbols directory.
    Filters out ETFs and debt instruments. Falls back to the 89-symbol
    watchlist if the PSX endpoint is unreachable."""
    try:
        r = requests.get(
            "https://dps.psx.com.pk/symbols",
            headers={"User-Agent": "PSX-Intelligence-V2/2.0 private-research"},
            timeout=15,
        )
        r.raise_for_status()
        rows = r.json()
        symbols = []
        for x in rows:
            sym = (x.get("symbol") or "").upper()
            if not sym:
                continue
            if x.get("isETF") or x.get("isDebt"):
                continue
            symbols.append(sym)
        logger.info(f"Fetched {len(symbols)} equity symbols from PSX /symbols directory")
        return sorted(set(symbols))
    except Exception as e:
        logger.warning(f"Could not fetch symbol list from PSX: {e}")
        logger.warning(f"Falling back to {len(FALLBACK_SYMBOLS)} watchlist symbols")
        return FALLBACK_SYMBOLS


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


def main():
    try:
        db_status = turso_db.status()
        logger.info(f"Database: {db_status['backend']}")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return 1

    conn = turso_db.get_connection()
    ensure_ohlc_table(conn)

    count_row = conn.execute("SELECT COUNT(DISTINCT symbol) as cnt FROM daily_ohlc").fetchone()
    existing_count = count_row["cnt"] if isinstance(count_row, dict) else count_row[0]
    logger.info(f"Existing symbols in daily_ohlc: {existing_count}")

    symbols = fetch_all_equity_symbols()
    logger.info(f"Will process {len(symbols)} symbols")

    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    refreshed = 0
    new_backfilled = 0
    failed = 0
    skipped = 0

    for i, symbol in enumerate(symbols):
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

    final_count = conn.execute("SELECT COUNT(DISTINCT symbol) as cnt FROM daily_ohlc").fetchone()
    total_symbols = final_count["cnt"] if isinstance(final_count, dict) else final_count[0]

    total_rows = conn.execute("SELECT COUNT(*) as cnt FROM daily_ohlc").fetchone()
    total = total_rows["cnt"] if isinstance(total_rows, dict) else total_rows[0]

    print("")
    logger.info("OHLC refresh complete!")
    logger.info(f"  New backfills: {new_backfilled}")
    logger.info(f"  Refreshed: {refreshed}")
    logger.info(f"  Skipped (up to date): {skipped}")
    logger.info(f"  Failed/no data: {failed}")
    logger.info(f"  Total symbols in DB: {total_symbols}")
    logger.info(f"  Total rows in DB: {total}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
