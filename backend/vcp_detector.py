"""vcp_detector.py — Phase 1a: Minervini-style Volatility Contraction Pattern
(VCP) detector.

A VCP is a series of successively tighter daily ranges (each day's high/low
fully inside the prior day's high/low) with volume drying up during that
tightening, climaxing in a high-volume breakout. This module implements
exactly that, as a single frozen definition for Phase 1a testing -- no
tuning loop, no iteration.

DATA SOURCE: detect_vcp() takes a ticker and loads its own OHLCV, in this
priority order:
  1. `bars` kwarg, if the caller already has bars in hand (list of dicts
     with date/open/high/low/close/volume, or a pandas DataFrame) --
     avoids re-fetching for tickers already loaded elsewhere (used by
     analysis/vcp_phase1a_test.py, which reuses the already-fetched
     analysis/premove_data_raw.json bars for the 11 known stocks).
  2. analysis/premove_data_raw.json, if the ticker is one of the symbols
     already fetched there.
  3. The daily_ohlc table via backend/turso_db.py (Turso if LIBSQL_URL /
     LIBSQL_AUTH_TOKEN are set, else a local sqlite file) -- the same
     data source backend/indicator_backtester.py and the analysis/phase1_*
     scripts already use. Requires network/DB access this sandbox does not
     have directly; scripts that need this path run in GitHub Actions with
     the LIBSQL secrets, matching this repo's existing convention.

ALGORITHM (frozen definition, do not change without a new Phase 1a run):

  1. Contraction-event day t: high[t] <= high[t-1] AND low[t] >= low[t-1]
     (today's range fully contained within yesterday's).
  2. A candidate VCP is a maximal run of `min_contractions` or more
     consecutive contraction-event days. `base_start_date` is the day
     BEFORE the run starts (the reference bar whose range is being
     contracted away from); `start_date` is the run's first contraction
     day.
  3. tightness_score = (range_start - range_end) / range_start * 100,
     clamped to [0, 100], where range_start/range_end are the high-low
     range of the base_start bar and the run's last bar respectively.
  4. volume_dry_up_score = (avg_vol_before - avg_vol_during) /
     avg_vol_before * 100, clamped to [0, 100] (a volume INCREASE during
     the base scores 0, never negative), where avg_vol_before is the mean
     volume of the up-to-10 bars immediately preceding base_start_date and
     avg_vol_during is the mean volume of the contraction run itself.
  5. Scanning forward from the run's last day (up to BREAKOUT_SCAN_HORIZON
     trading days, frozen at 20), the first day where
     volume > trailing_20d_avg_volume * volume_threshold is the breakout
     day. trailing_20d_avg_volume is an inclusive rolling mean (today +
     prior 19 days) -- the same convention analyze_premove.py's vol_20d_avg
     already uses in this repo. If no such day exists in the horizon (or
     there isn't enough trailing history yet), breakout_date and the two
     breakout_* fields are None and the breakout component of the quality
     score is 0.
  6. breakout_price_move = close-to-close %% change on the breakout day:
     (close[t] - close[t-1]) / close[t-1] * 100.
  7. overall_vcp_quality_score = 0.4*tightness_score + 0.3*volume_dry_up_score
     + 0.3*breakout_component, where breakout_component =
     min(breakout_volume_ratio / BREAKOUT_NORM_CAP_X, 1.0) * 100 (frozen at
     BREAKOUT_NORM_CAP_X = 5.0 -- i.e. 5x average volume or more earns full
     marks on this component; this project's own 11-stock forensic study
     found real breakouts routinely running 3.8x-10.7x, so 5x is a
     mid-range anchor, not a ceiling nothing could reach).
  8. is_textbook_vcp = overall_vcp_quality_score >= 70.

DEVIATION FROM THE LITERAL TASK SPEC, documented rather than silently
patched: the spec's output template shows `"ticker": "VCP"`, which would
make every row's ticker field the literal string "VCP" instead of the
actual stock symbol -- clearly a placeholder mix-up with a pattern-type
label. This module instead returns `"ticker": <the real symbol>` and adds
`"pattern_type": "VCP"` as its own field, so the per-stock report is
actually usable while still carrying the "VCP" label the spec asked for.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

_ANALYSIS_DIR = str(Path(__file__).parent.parent / "analysis")
_BACKEND_DIR = str(Path(__file__).parent)
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pandas as pd

PREMOVE_RAW_PATH = Path(_ANALYSIS_DIR) / "premove_data_raw.json"

# Frozen constants (part of the locked Phase 1a definition -- see Section 4
# of analysis/vcp_detector_phase1a_results.md).
MIN_VOLUME_BEFORE_BARS = 3     # fewer than this and "avg_vol_before" is unreliable -> skip candidate
VOL_BEFORE_WINDOW = 10         # bars of trailing volume history used for avg_vol_before
BREAKOUT_SCAN_HORIZON = 20     # trading days scanned forward for a breakout after the base
VOL_AVG_PERIOD = 20            # inclusive rolling volume average period (today + prior 19)
BREAKOUT_NORM_CAP_X = 5.0      # breakout_volume_ratio at/above this scores full marks
QUALITY_WEIGHTS = (0.4, 0.3, 0.3)   # (tightness, volume_dry_up, breakout) -- must sum to 1.0
TEXTBOOK_THRESHOLD = 70.0


def _bars_from_premove_json(ticker: str):
    if not PREMOVE_RAW_PATH.exists():
        return None
    with open(PREMOVE_RAW_PATH) as f:
        data = json.load(f)
    entry = data.get("ohlc", {}).get(ticker)
    if not entry:
        return None
    return entry["bars"]


def _bars_from_db(ticker: str):
    import turso_db
    conn = turso_db.get_connection()
    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
        "WHERE symbol = ? ORDER BY trade_date ASC",
        (ticker,),
    ).fetchall()
    bars = []
    for r in rows:
        r = dict(r) if not isinstance(r, dict) else r
        bars.append({
            "date": r["trade_date"],
            "open": r["open"], "high": r["high"], "low": r["low"],
            "close": r["close"], "volume": r["volume"],
        })
    return bars


def _load_bars(ticker: str):
    """Load bars for `ticker`, trying premove_data_raw.json first (no
    network needed, covers the 11 known study stocks + BNL), then the
    daily_ohlc DB via turso_db (requires LIBSQL secrets or a local
    psx_v2.db with data -- typically only available in GitHub Actions)."""
    bars = _bars_from_premove_json(ticker)
    if bars is not None:
        return bars
    try:
        bars = _bars_from_db(ticker)
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            f"No local data for {ticker!r} in premove_data_raw.json, and the "
            f"daily_ohlc DB path failed ({exc!r}). This ticker likely needs "
            f"to run where LIBSQL_URL/LIBSQL_AUTH_TOKEN are set (GitHub "
            f"Actions), same constraint documented in "
            f"analysis/phase1_triple_barrier_test.py."
        ) from exc
    if not bars:
        raise RuntimeError(f"daily_ohlc returned zero rows for {ticker!r}")
    return bars


def _to_frame(bars) -> pd.DataFrame:
    if isinstance(bars, pd.DataFrame):
        df = bars.copy()
    else:
        df = pd.DataFrame(bars)
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["high", "low", "close", "volume"]).reset_index(drop=True)
    return df


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


def _find_vcps_in_frame(df: pd.DataFrame, min_contractions: int, volume_threshold: float):
    """Core scan: every maximal run of >= min_contractions consecutive
    contraction-event days found anywhere in `df`, each turned into a
    fully-scored VCP dict. `df` must already be sorted ascending by date
    with a contiguous 0..n-1 index."""
    n = len(df)
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    volumes = df["volume"].to_numpy()
    dates = df["date"].astype(str).to_numpy()

    vol_avg20 = df["volume"].rolling(VOL_AVG_PERIOD).mean().to_numpy()

    is_contraction = [False] * n
    for t in range(1, n):
        is_contraction[t] = bool(highs[t] <= highs[t - 1] and lows[t] >= lows[t - 1])

    results = []
    t = 1
    while t < n:
        if not is_contraction[t]:
            t += 1
            continue
        run_start = t
        while t < n and is_contraction[t]:
            t += 1
        run_end = t - 1  # inclusive
        num_contractions = run_end - run_start + 1
        if num_contractions < min_contractions:
            continue

        base_start_idx = run_start - 1  # always >= 0 since is_contraction[0] is False
        range_start = highs[base_start_idx] - lows[base_start_idx]
        range_end = highs[run_end] - lows[run_end]
        if range_start <= 0:
            continue
        tightness_score = _clamp((range_start - range_end) / range_start * 100)

        before_lo = max(0, base_start_idx - (VOL_BEFORE_WINDOW - 1))
        vol_before_window = volumes[before_lo:base_start_idx + 1]
        if len(vol_before_window) < MIN_VOLUME_BEFORE_BARS:
            continue
        avg_vol_before = float(vol_before_window.mean())
        avg_vol_during = float(volumes[run_start:run_end + 1].mean())
        if avg_vol_before <= 0:
            continue
        volume_dry_up_score = _clamp((avg_vol_before - avg_vol_during) / avg_vol_before * 100)

        breakout_date = None
        breakout_volume_ratio = None
        breakout_price_move = None
        breakout_component = 0.0
        scan_start = run_end + 1
        scan_end = min(n, scan_start + BREAKOUT_SCAN_HORIZON)
        for idx in range(scan_start, scan_end):
            avg20 = vol_avg20[idx]
            if pd.isna(avg20) or avg20 <= 0:
                continue
            if volumes[idx] > avg20 * volume_threshold:
                breakout_date = dates[idx]
                breakout_volume_ratio = float(volumes[idx] / avg20)
                breakout_price_move = float((closes[idx] - closes[idx - 1]) / closes[idx - 1] * 100)
                breakout_component = min(breakout_volume_ratio / BREAKOUT_NORM_CAP_X, 1.0) * 100
                break

        w_t, w_d, w_b = QUALITY_WEIGHTS
        overall = w_t * tightness_score + w_d * volume_dry_up_score + w_b * breakout_component

        results.append({
            "pattern_type": "VCP",
            "start_date": str(dates[run_start]),
            "base_start_date": str(dates[base_start_idx]),
            "num_contractions": int(num_contractions),
            "tightness_score": round(tightness_score, 2),
            "volume_dry_up_score": round(volume_dry_up_score, 2),
            "breakout_date": breakout_date,
            "breakout_volume_ratio": round(breakout_volume_ratio, 3) if breakout_volume_ratio is not None else None,
            "breakout_price_move": round(breakout_price_move, 3) if breakout_price_move is not None else None,
            "overall_vcp_quality_score": round(overall, 2),
            "is_textbook_vcp": bool(overall >= TEXTBOOK_THRESHOLD),
        })
    return results


def detect_vcp(
    ticker: str,
    lookback_days: int = 60,
    min_contractions: int = 2,
    volume_threshold: float = 1.5,
    bars=None,
):
    """Detect all VCP patterns for `ticker` within its most recent
    `lookback_days` trading days.

    Returns a list of dicts (empty list if none found), each shaped:
      {
        "ticker": <symbol>, "pattern_type": "VCP",
        "start_date", "base_start_date",
        "num_contractions", "tightness_score", "volume_dry_up_score",
        "breakout_date", "breakout_volume_ratio", "breakout_price_move",
        "overall_vcp_quality_score", "is_textbook_vcp",
      }

    `bars` is an additive optional override (list of OHLCV dicts or a
    DataFrame) letting a caller that already has the ticker's bars in hand
    skip the internal load step -- not part of the original task's
    signature, but backward compatible (defaults to None => internal
    load-by-ticker, exactly as specified).
    """
    raw_bars = bars if bars is not None else _load_bars(ticker)
    df = _to_frame(raw_bars)
    window = df.tail(lookback_days).reset_index(drop=True)
    vcps = _find_vcps_in_frame(window, min_contractions, volume_threshold)
    for v in vcps:
        v["ticker"] = ticker
    return vcps


def _watchlist_symbols():
    """Reuses backend/app.py's own WATCHLIST_SYMBOLS list value verbatim,
    without `import app` -- app.py is a full FastAPI app with heavy
    module-level side effects (DB connections, schedulers, etc.) that
    have no business running just to read a list literal. Instead this
    parses the WATCHLIST_SYMBOLS = [...] assignment directly out of the
    source with ast, the same list, zero side effects."""
    import ast
    app_path = Path(_BACKEND_DIR) / "app.py"
    source = app_path.read_text()
    tree = ast.parse(source, filename=str(app_path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "WATCHLIST_SYMBOLS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError("WATCHLIST_SYMBOLS assignment not found in backend/app.py")


def random_watchlist_sample(exclude, n=50, seed=42):
    """Sample `n` symbols from backend/app.py's WATCHLIST_SYMBOLS, excluding
    `exclude`, for Step 3's false-positive baseline. Deterministic (fixed
    seed) so the sample is reproducible."""
    pool = [s for s in _watchlist_symbols() if s not in exclude]
    rng = random.Random(seed)
    return sorted(rng.sample(pool, min(n, len(pool))))
