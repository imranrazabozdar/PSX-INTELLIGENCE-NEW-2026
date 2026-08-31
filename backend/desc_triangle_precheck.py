"""desc_triangle_precheck.py — feasibility pre-check for a Descending
Triangle detector: does this geometry (descending resistance + flat
support, simultaneously) actually occur on PSX, and how often?

Reuses the EXACT shared infrastructure every other structural-pattern
module in this codebase uses, rather than reimplementing pivot detection
or symbol screening:
  - AdvancedPatternEngine._preflight() / ._enrich()  (advanced_pattern_engine.py)
  - pivots.find_pivots(df, k=5, min_swing_pct=3.0)    (pivots.py)

Read-only: does not modify any engine, does not write to the database.

ALGORITHM (documented here since this is new, not copied from an
existing detector): for each pre-flight-passing symbol, get the full
chronological alternating pivot list. For every pivot index j where
pivots[j] is a "high", expand a window forward pivot-by-pivot. At each
step, collect the highs and lows seen so far in the window. As soon as
a window satisfies ALL of:
  - >=3 highs, consecutive in the highs-subsequence, each >=1% lower
    than the previous (strictly descending resistance)
  - >=3 lows, all within 3% of each other (flat support)
  - span (last pivot index - first pivot index) in [15, 75] sessions
it counts as ONE qualifying window, and the search for this symbol
resumes from the pivot immediately after this window's start (not its
end) -- a sliding, not exhaustive, count, so heavily overlapping
re-detections of the same visual formation aren't inflated into dozens
of "windows". This is a feasibility estimate, not a certified detector.
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
MIN_SPAN, MAX_SPAN = 15, 75
MIN_HIGHS, MIN_LOWS = 3, 3
HIGH_STEP_PCT = 1.0    # each high must be >=1% below the previous
LOW_BAND_PCT = 3.0     # all lows within 3% of each other


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


def _descending_ok(high_prices: list[float]) -> bool:
    for i in range(1, len(high_prices)):
        if not (high_prices[i] <= high_prices[i - 1] * (1 - HIGH_STEP_PCT / 100.0)):
            return False
    return True


def _flat_ok(low_prices: list[float]) -> bool:
    lo, hi = min(low_prices), max(low_prices)
    if lo <= 0:
        return False
    return (hi - lo) / lo * 100.0 <= LOW_BAND_PCT


def _scan_symbol(sym_df: pd.DataFrame):
    """Returns a list of (start_date, end_date, span_sessions) qualifying
    windows for one symbol's already-enriched, pivot-detected series."""
    pivots = find_pivots(sym_df, k=5, min_swing_pct=3.0)
    windows = []
    j = 0
    n = len(pivots)
    while j < n:
        if pivots[j].kind != "high":
            j += 1
            continue
        highs, lows = [], []
        found = False
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
                if _descending_ok(highs) and _flat_ok(lows):
                    windows.append((pivots[j].date, pivots[end].date, span))
                    found = True
                    break
        j += 1  # slide forward one pivot regardless, per the module docstring
    return windows


def run():
    engine = AdvancedPatternEngine()
    all_df = _load_all_ohlc()

    preflight_pass = []
    results = []  # (symbol, start_date, end_date, span)

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
