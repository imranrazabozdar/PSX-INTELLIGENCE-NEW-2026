#!/usr/bin/env python3
"""check_symbols_live.py — one-off diagnostic: is a given symbol actually
in PSX's live /symbols equity directory right now? Read-only, no Turso
credentials needed. Reuses the exact same endpoint/filter as
backend/run_ohlc_refresh.py's fetch_all_equity_symbols() so "present here"
means "the same live source that daily_ohlc's whole-market refresh reads
from would also see it."

Usage:
    python -m fire_engine.check_symbols_live --symbols 786,SPAC1,SPAC2,...
"""
import argparse

import requests


def fetch_live_equity_symbols() -> set:
    r = requests.get(
        "https://dps.psx.com.pk/symbols",
        headers={"User-Agent": "PSX-Intelligence-V2/2.0 private-research"},
        timeout=15,
    )
    r.raise_for_status()
    rows = r.json()
    symbols = set()
    for x in rows:
        sym = (x.get("symbol") or "").upper()
        if not sym or x.get("isETF") or x.get("isDebt"):
            continue
        symbols.add(sym)
    return symbols


def main():
    parser = argparse.ArgumentParser(description="Check symbols against PSX's live /symbols directory.")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbol list")
    args = parser.parse_args()

    to_check = sorted(set(s.strip().upper() for s in args.symbols.split(",") if s.strip()))
    live = fetch_live_equity_symbols()
    print(f"Live PSX equity directory: {len(live)} symbols (ETFs/debt excluded)\n")

    present = [s for s in to_check if s in live]
    missing = [s for s in to_check if s not in live]

    print(f"Present in live directory ({len(present)}/{len(to_check)}):")
    print(f"  {present}\n")
    print(f"NOT present / not real current PSX tickers ({len(missing)}/{len(to_check)}):")
    print(f"  {missing}")


if __name__ == "__main__":
    main()
