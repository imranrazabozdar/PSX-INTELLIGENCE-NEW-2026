#!/usr/bin/env python3
"""run_wyckoff_preview.py — one-off preview scan for a symbol list supplied
on the command line, WITHOUT touching the production stocks.universe config
or writing into the shared wyckoff_accumulation table (so preview results
never show up on the live Streamlit dashboard as if they were an official
scheduled scan).

Symbols already covered by the real universe get no special-cased "skip":
fetch_daily_and_4h() already avoids redundant work on its own for every
symbol alike -- daily bars always come from the existing daily_ohlc table
(never re-fetched per-scan regardless of symbol) and 4-hour bars are only
re-fetched from SCS when the cached ohlcv_4h rows are more than 4 hours
old. Passing an already-covered symbol here just reuses whatever's fresh;
it doesn't cost an extra SCS call unless the cache genuinely is stale.

Usage:
    python -m fire_engine.run_wyckoff_preview --symbols STL,GLAXO,... --end-date 2026-09-06
"""
import argparse
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fire_engine.config import load_config
from fire_engine.database import DatabaseManager
from fire_engine.wyckoff_data_fetcher import fetch_daily_and_4h
from fire_engine.wyckoff_detector import WyckoffDetector
from fire_engine.wyckoff_scheduler import MIN_DAILY_BARS


def main():
    parser = argparse.ArgumentParser(description="Preview-scan a symbol list without touching production state.")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbol list")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--local-db", default=None,
                         help="Path to a standalone sqlite file instead of the shared Turso DB "
                              "(development/testing only)")
    parser.add_argument("--config", default=None, help="Path to fire_config.yaml (default: bundled)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    symbols = sorted(set(s.strip().upper() for s in args.symbols.split(",") if s.strip()))

    if args.local_db:
        db = DatabaseManager(db_path=args.local_db)
    else:
        import turso_db
        db = DatabaseManager(conn=turso_db.get_connection())

    detector = WyckoffDetector(cfg)
    results = []
    print(f"PREVIEW SCAN -- {len(symbols)} symbols, not written to wyckoff_accumulation, "
          f"not added to stocks.universe\n", flush=True)

    try:
        for i, symbol in enumerate(symbols, 1):
            try:
                df_daily, df_4h = fetch_daily_and_4h(db, symbol, end_date=args.end_date)
                if len(df_daily) < MIN_DAILY_BARS:
                    print(f"[{i}/{len(symbols)}] {symbol}: insufficient daily history "
                          f"({len(df_daily)} bars, need {MIN_DAILY_BARS}), skipped", flush=True)
                    continue
                result = detector.detect_stealth_accumulation(df_daily, df_4h)
                prepared = detector.prepare_for_db_and_ui(result, symbol, args.end_date or "today")
                results.append(prepared)
                print(f"[{i}/{len(symbols)}] {symbol}: score={prepared['accumulation_score']} "
                      f"signal={prepared['signal_type']}", flush=True)
            except Exception as exc:
                print(f"[{i}/{len(symbols)}] {symbol}: ERROR={exc!r}", flush=True)
    finally:
        db.close()

    signals = [r for r in results if r["signal_type"] != "NO_SIGNAL"]
    print(f"\nPreview complete: {len(results)}/{len(symbols)} symbols scanned, "
          f"{len(signals)} with a WATCH/READY/EXTREME signal.")
    if signals:
        print("\nTop signals by score:")
        for r in sorted(signals, key=lambda x: -x["accumulation_score"]):
            print(f"  {r['symbol']:10s} | {r['signal_type']:8s} | Score: {r['accumulation_score']:3d}")


if __name__ == "__main__":
    main()
