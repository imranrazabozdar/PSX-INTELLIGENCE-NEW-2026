#!/usr/bin/env python3
"""run_wyckoff_batch.py — CLI entry point for the Wyckoff Institutional
Stealth Accumulation daily batch (Phase 18-22). Same shape as
run_daily_batch.py -- same GitHub Actions job (fire_engine_daily_batch.yml),
run right after the FIRE Engine batch step, against the same shared Turso
DB so /patterns/wyckoff-scan sees a completed run immediately. Pass
--local-db PATH to use a standalone sqlite file instead (development/
testing only).
"""
import argparse
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fire_engine.config import load_config
from fire_engine.database import DatabaseManager
from fire_engine.market_hours import get_market_status, is_trading_day
from fire_engine.wyckoff_scheduler import run_daily_wyckoff_batch


def main():
    parser = argparse.ArgumentParser(description="Run the Wyckoff Accumulation daily batch.")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today, PKT)")
    parser.add_argument("--local-db", default=None,
                         help="Path to a standalone sqlite file instead of the shared Turso DB "
                              "(development/testing only)")
    parser.add_argument("--config", default=None, help="Path to fire_config.yaml (default: bundled)")
    parser.add_argument("--skip-market-check", action="store_true",
                         help="Run even if today (the invocation day, not --date) is a weekend -- "
                              "for a deliberate manual/backfill run; the scheduled cron never needs this.")
    args = parser.parse_args()

    print(f"Market status: {get_market_status()}")
    if not args.skip_market_check and not is_trading_day():
        print("PSX is closed today (weekend) -- exiting without running the batch.")
        sys.exit(0)

    cfg = load_config(args.config)

    if args.local_db:
        db = DatabaseManager(db_path=args.local_db)
    else:
        import turso_db
        db = DatabaseManager(conn=turso_db.get_connection())

    try:
        result = run_daily_wyckoff_batch(db, cfg, date=args.date)
    finally:
        db.close()

    print(f"\nWyckoff batch for {result['date']}: {len(result['results'])} symbols scanned, "
          f"{result['stocks_with_signal']} with a WATCH/READY/EXTREME signal.")


if __name__ == "__main__":
    main()
