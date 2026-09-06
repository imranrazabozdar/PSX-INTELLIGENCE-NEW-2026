#!/usr/bin/env python3
"""backfill_4h.py — one-off pre-warm of the ohlcv_4h cache for every
symbol in the universe, covering a date range in ONE fetch per symbol
(SCS's /history endpoint already takes a from/to range, so this isn't a
day-by-day loop -- just wyckoff_data_fetcher.fetch_4h_ohlcv() called with
a large enough lookback_days).

Not a scheduled job, and NOT wired into wyckoff_scheduler.py's own daily
run: run this manually (or via the wyckoff_4h_backfill GitHub Actions
job) when you want the cache refreshed ahead of time, independent of
load_4h_df()'s own 4-hour cache-staleness check -- daily_ohlc (used for
every other Wyckoff metric) already holds years of history maintained by
backend/run_ohlc_refresh.py, so only the 4-hour side needs this.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fire_engine.config import load_config
from fire_engine.database import DatabaseManager
from fire_engine.exclusions import filter_excluded_stocks, load_exclusions_from_config
from fire_engine.wyckoff_data_fetcher import fetch_4h_ohlcv, store_4h_data


def main():
    parser = argparse.ArgumentParser(description="Pre-warm the ohlcv_4h cache for the whole universe.")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD, most recent date to cover")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD, oldest date to cover")
    parser.add_argument("--local-db", default=None,
                         help="Path to a standalone sqlite file instead of the shared Turso DB "
                              "(development/testing only)")
    parser.add_argument("--config", default=None, help="Path to fire_config.yaml (default: bundled)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    lookback_days = (
        datetime.strptime(args.end_date, "%Y-%m-%d") - datetime.strptime(args.start_date, "%Y-%m-%d")
    ).days
    if lookback_days < 0:
        raise SystemExit(f"--start-date {args.start_date} is after --end-date {args.end_date}")

    if args.local_db:
        db = DatabaseManager(db_path=args.local_db)
    else:
        import turso_db
        db = DatabaseManager(conn=turso_db.get_connection())

    universe = cfg["stocks"]["universe"]
    if cfg["exclusion"]["enabled"]:
        universe = filter_excluded_stocks(universe, load_exclusions_from_config())

    total_rows = 0
    errors = []
    try:
        for i, symbol in enumerate(universe, 1):
            try:
                candles = fetch_4h_ohlcv(
                    symbol, args.end_date, lookback_days=lookback_days,
                    max_retries=cfg["data_source"]["retry_attempts"],
                    retry_delay=cfg["data_source"]["retry_delay_seconds"],
                )
                n = store_4h_data(db, symbol, candles)
                total_rows += n
                print(f"[{i}/{len(universe)}] {symbol}: {n} 4h candles stored", flush=True)
            except Exception as exc:
                errors.append(symbol)
                print(f"[{i}/{len(universe)}] {symbol}: ERROR={exc!r}", flush=True)
    finally:
        db.close()

    print(f"\n4h backfill {args.start_date}..{args.end_date}: {len(universe) - len(errors)}/{len(universe)} "
          f"symbols OK, {total_rows} candles stored.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
