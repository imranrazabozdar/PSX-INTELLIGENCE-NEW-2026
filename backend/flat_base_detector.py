"""flat_base_detector.py — Phase 1b: Flat Base / Tight Base detector.

Reuses vcp_detector.py's already-built plumbing rather than re-implementing
it (same data loaders, same clamp helper, same breakout-scan constants and
quality-score weights/threshold, so Phase 1b results are directly
comparable to Phase 1a's, not scored on a different scale): `_load_bars`,
`_to_frame`, `_clamp`, `random_watchlist_sample`, `MIN_VOLUME_BEFORE_BARS`,
`VOL_BEFORE_WINDOW`, `BREAKOUT_SCAN_HORIZON`, `VOL_AVG_PERIOD`,
`BREAKOUT_NORM_CAP_X`, `QUALITY_WEIGHTS`, `TEXTBOOK_THRESHOLD`.

DEFINITION: a flat/tight base is a `min_days`-to-`max_days` window whose
high-low range stays within `max_range_pct` of the window's own average
close, on volume that contracted to `volume_contraction`x (or less) of what
traded in the `VOL_BEFORE_WINDOW` bars right before the base -- climaxing
in a volume breakout, scored and thresholded exactly like VCP's.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pandas as pd

from vcp_detector import (  # reused, not reimplemented
    _load_bars, _to_frame, _clamp, random_watchlist_sample,
    MIN_VOLUME_BEFORE_BARS, VOL_BEFORE_WINDOW, BREAKOUT_SCAN_HORIZON,
    VOL_AVG_PERIOD, BREAKOUT_NORM_CAP_X, QUALITY_WEIGHTS, TEXTBOOK_THRESHOLD,
)


def detect_flat_base(
    ticker: str,
    df: pd.DataFrame = None,
    min_days: int = 12,
    max_days: int = 35,
    max_range_pct: float = 12.0,
    volume_contraction: float = 0.75,
    volume_threshold: float = 1.5,
    lookback_days: int = 60,
) -> list:
    """Detect flat bases for `ticker` within its most recent `lookback_days`
    trading days. `df` is an additive optional override (bars already in
    hand); omitted, it loads via vcp_detector._load_bars(ticker) exactly
    like detect_vcp() does. Returns a list of dicts (empty if none found)."""
    raw = df if df is not None else _load_bars(ticker)
    full = _to_frame(raw)
    window = full.tail(lookback_days).reset_index(drop=True)
    n = len(window)
    highs = window["high"].to_numpy()
    lows = window["low"].to_numpy()
    closes = window["close"].to_numpy()
    volumes = window["volume"].to_numpy()
    dates = window["date"].astype(str).to_numpy()
    vol_avg20 = window["volume"].rolling(VOL_AVG_PERIOD).mean().to_numpy()

    results = []
    end = min_days - 1
    while end < n:
        chosen = None
        for length in range(max_days, min_days - 1, -1):
            start = end - length + 1
            if start < 0:
                continue
            before_lo = max(0, start - VOL_BEFORE_WINDOW)
            vol_before = volumes[before_lo:start]
            if len(vol_before) < MIN_VOLUME_BEFORE_BARS:
                continue
            seg_high = highs[start:end + 1].max()
            seg_low = lows[start:end + 1].min()
            seg_close_mean = closes[start:end + 1].mean()
            if seg_close_mean <= 0:
                continue
            range_pct = float((seg_high - seg_low) / seg_close_mean * 100)
            avg_vol_before = float(vol_before.mean())
            avg_vol_during = float(volumes[start:end + 1].mean())
            if avg_vol_before <= 0:
                continue
            vol_ratio = avg_vol_during / avg_vol_before
            if range_pct <= max_range_pct and vol_ratio <= volume_contraction:
                chosen = (start, length, range_pct, vol_ratio, avg_vol_before, avg_vol_during)
                break  # longest qualifying length wins (max_days downwards)
        if chosen is None:
            end += 1
            continue

        start, length, range_pct, vol_ratio, avg_vol_before, avg_vol_during = chosen
        tightness_score = _clamp((max_range_pct - range_pct) / max_range_pct * 100)
        volume_dry_up_score = _clamp((1 - vol_ratio) * 100)

        breakout_date = breakout_volume_ratio = breakout_price_move = None
        breakout_component = 0.0
        breakout_idx = None
        scan_start = end + 1
        scan_end = min(n, scan_start + BREAKOUT_SCAN_HORIZON)
        for idx in range(scan_start, scan_end):
            avg20 = vol_avg20[idx]
            if pd.isna(avg20) or avg20 <= 0:
                continue
            if volumes[idx] > avg20 * volume_threshold:
                breakout_idx = idx
                breakout_date = dates[idx]
                breakout_volume_ratio = float(volumes[idx] / avg20)
                breakout_price_move = float((closes[idx] - closes[idx - 1]) / closes[idx - 1] * 100)
                breakout_component = min(breakout_volume_ratio / BREAKOUT_NORM_CAP_X, 1.0) * 100
                break

        w_t, w_d, w_b = QUALITY_WEIGHTS
        overall = w_t * tightness_score + w_d * volume_dry_up_score + w_b * breakout_component

        results.append({
            "ticker": ticker,
            "pattern_type": "FLAT_BASE",
            "start_date": str(dates[start]),
            "end_date": str(dates[end]),
            "num_days": int(length),
            "range_pct": round(range_pct, 2),
            "volume_contraction_ratio": round(vol_ratio, 3),
            "tightness_score": round(tightness_score, 2),
            "volume_dry_up_score": round(volume_dry_up_score, 2),
            "breakout_date": breakout_date,
            "breakout_volume_ratio": round(breakout_volume_ratio, 3) if breakout_volume_ratio is not None else None,
            "breakout_price_move": round(breakout_price_move, 3) if breakout_price_move is not None else None,
            "overall_flat_base_quality_score": round(overall, 2),
            "is_textbook_flat_base": bool(overall >= TEXTBOOK_THRESHOLD),
        })
        # Advance past this base (and its breakout day, if one was found) before
        # looking for the next non-overlapping base -- mirrors detect_vcp()'s
        # maximal-run, non-overlapping scan.
        end = (breakout_idx if breakout_idx is not None else end + length) + 1
    return results
