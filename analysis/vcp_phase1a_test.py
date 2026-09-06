#!/usr/bin/env python3
"""Phase 1a, Step 2: run backend/vcp_detector.py's detect_vcp() -- with its
exact default parameters (lookback_days=60, min_contractions=2,
volume_threshold=1.5) -- against the 11 known stocks from the pre-move
forensic study, using the already-fetched bars in premove_data_raw.json
(no network needed; local run, no GitHub Actions required for this half).

For every VCP detect_vcp() finds, checks whether its breakout_date lands
within 5 TRADING days (position in this stock's own trading-day sequence,
not calendar days) of that stock's user-given MOVE_START date -- reusing
MOVE_START verbatim from analyze_premove.py, not re-typing it. That's the
"hit" signal: the detector caught a pattern whose breakout roughly
coincides with the real, previously-identified move.

Single pass, no iteration/tuning: writes analysis/vcp_11stock_results.json,
consumed by analysis/build_vcp_phase1a_report.py alongside Step 3's
50-stock baseline (produced separately, in GitHub Actions, where the
daily_ohlc DB is reachable).
"""
import json
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from vcp_detector import detect_vcp, _bars_from_premove_json
from analyze_premove import MOVE_START  # reused verbatim, not redefined

TICKERS = ["AICL", "SHFA", "THCCL", "FNEL", "MDTL", "FPJM", "DSIL", "SYM", "PREMA", "JSBL", "ILP"]
HIT_WINDOW_TRADING_DAYS = 5
OUT_PATH = str(Path(__file__).parent / "vcp_11stock_results.json")


def _trading_day_distance(bars, date_a, date_b):
    """Absolute distance, in trading-day POSITIONS (not calendar days),
    between two dates found in this ticker's own sorted bar sequence.
    Returns None if either date isn't an exact bar date (shouldn't happen
    for breakout_date, which is always drawn from the bars themselves;
    MOVE_START dates are user-given and checked for presence)."""
    dates = sorted(b["date"] for b in bars)
    if date_a not in dates or date_b not in dates:
        return None
    return abs(dates.index(date_a) - dates.index(date_b))


def main():
    out = {}
    for ticker in TICKERS:
        bars = _bars_from_premove_json(ticker)
        vcps = detect_vcp(ticker, bars=bars)  # exact defaults: lookback_days=60,
                                               # min_contractions=2, volume_threshold=1.5
        move_start = MOVE_START.get(ticker)
        for v in vcps:
            if v["breakout_date"] is None:
                v["hit_or_miss"] = "no_breakout_in_horizon"
                continue
            dist = _trading_day_distance(bars, v["breakout_date"], move_start)
            if dist is None:
                v["hit_or_miss"] = "move_start_date_not_in_window"
            else:
                v["trading_days_from_move_start"] = dist
                v["hit_or_miss"] = "hit" if dist <= HIT_WINDOW_TRADING_DAYS else "miss"
        out[ticker] = {
            "move_start": move_start,
            "num_bars_in_full_history": len(bars),
            "vcps_found": vcps,
        }

    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    # Console summary (also folded into the final report by build_vcp_phase1a_report.py)
    stocks_with_vcp = [t for t in TICKERS if out[t]["vcps_found"]]
    stocks_with_hit = [
        t for t in TICKERS
        if any(v.get("hit_or_miss") == "hit" for v in out[t]["vcps_found"])
    ]
    stocks_with_textbook = [
        t for t in TICKERS
        if any(v["is_textbook_vcp"] for v in out[t]["vcps_found"])
    ]
    print(f"Wrote {OUT_PATH}")
    print(f"Stocks with >=1 VCP detected: {len(stocks_with_vcp)}/11 -> {stocks_with_vcp}")
    print(f"Stocks with >=1 'hit' (breakout within {HIT_WINDOW_TRADING_DAYS} trading days "
          f"of move-start): {len(stocks_with_hit)}/11 -> {stocks_with_hit}")
    print(f"Stocks with >=1 textbook VCP (quality>=70): {len(stocks_with_textbook)}/11 -> {stocks_with_textbook}")


if __name__ == "__main__":
    main()
