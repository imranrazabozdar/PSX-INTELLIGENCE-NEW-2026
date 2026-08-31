"""rectangle_precheck.py — feasibility pre-check for a Rectangle
(trading range) detector: flat resistance + flat support coexisting,
with a minimum height to exclude dead/flat stocks.

Reuses the same shared infrastructure as desc_triangle_precheck.py:
  - AdvancedPatternEngine._preflight() / ._enrich()
  - pivots.find_pivots(df, k=5, min_swing_pct=3.0)

Read-only: does not modify any engine, does not write to the database.

ALGORITHM: for each pre-flight-passing symbol, get the full chronological
alternating pivot list. For every pivot index j, expand a window forward
pivot-by-pivot. As soon as a window satisfies ALL of:
  - >=3 highs, all within 3% of each other (flat resistance)
  - >=3 lows, all within 3% of each other (flat support)
  - span (last pivot index - first pivot index) in [20, 80] sessions
  - height = (max(highs) - min(lows)) / min(lows) >= 5%
it counts as ONE qualifying window, and the search for this symbol
resumes from the pivot immediately after this window's start -- same
sliding, non-exhaustive counting convention as the Descending Triangle
pre-check, for the same reason (avoid inflating one visual formation
into dozens of overlapping "windows").
"""

import sqlite3
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from advanced_pattern_engine import AdvancedPatternEngine
from pivots import find_pivots

DB_PATH = "psx_v2.db"
MIN_SPAN, MAX_SPAN = 20, 80
MIN_HIGHS, MIN_LOWS = 3, 3
BAND_PCT = 3.0       # highs within 3% of each other; lows within 3% of each other
MIN_HEIGHT_PCT = 5.0  # (max_resistance - min_support) / min_support >= 5%


def _load_all_ohlc(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT symbol, trade_date AS date, open, high, low, close, volume "
            "FROM daily_ohlc ORDER BY symbol, trade_date", conn)
    finally:
        conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _flat_ok(prices: list[float]) -> bool:
    lo, hi = min(prices), max(prices)
    if lo <= 0:
        return False
    return (hi - lo) / lo * 100.0 <= BAND_PCT


def _height_ok(highs: list[float], lows: list[float]) -> bool:
    max_res, min_sup = max(highs), min(lows)
    if min_sup <= 0:
        return False
    return (max_res - min_sup) / min_sup * 100.0 >= MIN_HEIGHT_PCT


def _scan_symbol(sym_df: pd.DataFrame):
    pivots = find_pivots(sym_df, k=5, min_swing_pct=3.0)
    windows = []
    j = 0
    n = len(pivots)
    while j < n:
        highs, lows = [], []
        for end in range(j, n):
            p = pivots[end]
            if p.kind == "high":
                highs.append(p.price)
            else:
                lows.append(p.price)
            span = pivots[end].index - pivots[j].index
            if span > MAX_SPAN:
                break
            if span < MIN_SPAN:
                continue
            if len(highs) >= MIN_HIGHS and len(lows) >= MIN_LOWS:
                if _flat_ok(highs) and _flat_ok(lows) and _height_ok(highs, lows):
                    windows.append((pivots[j].date, pivots[end].date, span))
                    break
        j += 1
    return windows


def run():
    engine = AdvancedPatternEngine()
    all_df = _load_all_ohlc()

    preflight_pass = []
    results = []

    for symbol, g in all_df.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        ok, reason = engine._preflight(g)
        if not ok:
            continue
        preflight_pass.append(symbol)

        enriched = engine._enrich(g)
        windows = _scan_symbol(enriched)
        for start_date, end_date, span in windows:
            results.append((symbol, start_date, end_date, span))

    return preflight_pass, results


if __name__ == "__main__":
    t0 = time.time()
    print("Running pre-flight + pivot scan across the PSX universe ...")
    preflight_pass, results = run()

    n_preflight = len(preflight_pass)
    symbols_with_window = sorted({r[0] for r in results})
    spans = [r[3] for r in results]

    print(f"\nPre-flight-passing symbols: {n_preflight}")
    print(f"Symbols with >=1 qualifying window: {len(symbols_with_window)}")
    print(f"Total qualifying windows: {len(results)}")
    if spans:
        print(f"Median span (sessions): {float(np.median(spans)):.1f}")
        print(f"Min span: {min(spans)}  Max span: {max(spans)}")
    else:
        print("Median/min/max span: n/a (zero windows)")

    decision = "PROCEED" if (len(results) >= 50 and len(symbols_with_window) >= 30) else "SKIP"
    print(f"\nDECISION: {decision}  "
          f"(rule: >=50 windows AND >=30 symbols -> PROCEED; else SKIP)")
    print(f"windows={len(results)}, symbols={len(symbols_with_window)}")

    print(f"\nElapsed: {time.time() - t0:.1f}s")
