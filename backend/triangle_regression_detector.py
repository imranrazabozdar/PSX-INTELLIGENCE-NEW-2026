"""triangle_regression_detector.py — rolling regression-slope converging-
channel detector, translated from a reference systematic-trading
notebook's detect_flag()/precompute_triangle_flags() logic (5-minute gold
futures, GC=F).

HOW THIS DIFFERS FROM backend/ascending_triangle_engine.py (already in
this codebase, currently SUSPENDED for insufficient PSX signal density --
5 signals in a 5-year universe scan, see CALIBRATION_LOG.md): that engine
requires an EXACT discrete 6-pivot sequence (T1/P1/T2/P2/T3/P3) -- 3 highs
within a tight flat-top band and 3 lows each rising by a minimum step.
This module is a CONTINUOUS, rolling formulation instead: over a trailing
LOOKBACK window, fit an OLS regression through EVERY confirmed pivot high
and EVERY confirmed pivot low separately (however many exist, not a fixed
count of 3), and require both lines to be genuinely linear (R² >= MIN_R2)
with a near-flat/declining resistance rail and a meaningfully rising
support rail. Looser geometry, much higher expected signal density --
NOT a replacement for the discrete engine (that one stays as-is, just
disabled), a genuinely different additional method.

DIRECTION -- kept exactly as the notebook backtested it, not the
classical-textbook assumption that an ascending-triangle squeeze resolves
upward: the notebook's own backtest on GC=F 5-min bars SHORTS this
geometry (its ShortSignalStrategy class), betting on a squeeze
failure/breakdown. That is an empirical choice from THEIR backtest on a
different instrument/timeframe, not a claim it transfers to PSX daily
bars -- see run_triangle_regression_backtest.py for the walk-forward PSX
result before trusting the direction here.

PIVOTS: reuses this codebase's OWN pivots.find_pivots() (fractal,
no-lookahead-safe via confirmed_at_index) rather than reverse-engineering
the notebook's undisclosed add_pivots()/utilities.py internals -- the
same reuse discipline ascending_triangle_engine.py already follows
against AdvancedPatternEngine/CupHandleEngine.

THRESHOLD ADAPTATION (stated plainly, not glossed over): the notebook's
MAX_HIGH_SLOPE=0.0002 / MIN_LOW_SLOPE=0.0005 are FRACTIONAL PRICE CHANGE
PER 5-MINUTE BAR, calibrated to gold-futures microstructure -- reused
literally on PSX DAILY bars they would almost never fire (a daily bar
moves far more, per bar, than a 5-minute bar). This module instead
expresses the SAME two thresholds as TOTAL DRIFT ACROSS THE LOOKBACK
WINDOW (slope * lookback bars), which is timeframe-invariant in spirit:
0.0002*40 = 0.8% total resistance-rail drift ceiling, 0.0005*40 = 2.0%
total support-rail rise floor, over LOOKBACK=40 (bars -- now trading
days). MIN_R2 (0.7) is dimensionless and reused literally, unchanged.

TRADE RULE: kept exactly as the notebook's ShortSignalStrategy class
default (SL = signal bar's high * 1.01, i.e. a 1% buffer above the high;
TP = entry - rr*(stop-entry), rr=3 -- the class's own stated default,
NOT the notebook's own later-optimized rr=1.5, consistent with every
other detector in this codebase using unoptimized, stated-default
parameters). Entry is the signal bar's own close (the notebook backtests
with trade_on_close=True, so this needs no next-bar-open approximation
the way the other detectors here do).
"""

import numpy as np
import pandas as pd

from pivots import find_pivots

LOOKBACK = 40
PIVOT_K = 3                    # the notebook's PIVOT_WINDOW=3, reused literally as pivots.find_pivots' k
MAX_HIGH_DRIFT_PCT = 0.8       # total resistance-rail drift across LOOKBACK bars (see module docstring)
MIN_LOW_DRIFT_PCT = 2.0        # total support-rail rise across LOOKBACK bars
MIN_R2 = 0.7
MIN_PIVOTS_PER_SIDE = 2        # need >= 2 points to regress at all

SL_BUFFER_PCT = 0.01           # the notebook's sl_buffer=0.01
RR_DEFAULT = 3.0               # the notebook's class-stated default (rr=3), unoptimized

PATTERN_NAME_TRIANGLE_REG = "Regression-Channel Triangle Squeeze"
TIMEFRAME_TR = "1D"
BEARISH_TRIANGLE_REG = "BEARISH_TRIANGLE_SQUEEZE"
NO_TRIANGLE_REG_SIGNAL = "NO_TRIANGLE_SQUEEZE_SIGNAL"

MIN_BARS_REQUIRED = LOOKBACK + 2 * PIVOT_K + 5


def _empty_result():
    return {"pattern": PATTERN_NAME_TRIANGLE_REG, "timeframe": TIMEFRAME_TR,
            "detected": False, "classification": NO_TRIANGLE_REG_SIGNAL}


def _atr14(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean()


def _ols_slope_r2(points):
    """points: list of (index, price), index as an integer bar position.
    Returns (fractional_slope_per_bar, r_squared), or (None, None) if
    fewer than 2 points or a degenerate (zero-variance) fit."""
    if len(points) < 2:
        return None, None
    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    mean_x, mean_y = xs.mean(), ys.mean()
    var_x = ((xs - mean_x) ** 2).sum()
    if var_x == 0 or mean_y == 0:
        return None, None
    cov = ((xs - mean_x) * (ys - mean_y)).sum()
    slope_raw = cov / var_x
    slope_frac = slope_raw / mean_y
    pred = mean_y + slope_raw * (xs - mean_x)
    ss_res = ((ys - pred) ** 2).sum()
    ss_tot = ((ys - mean_y) ** 2).sum()
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0
    return slope_frac, r2


def _evaluate_at(d: pd.DataFrame, pivots: list, i: int):
    """Shared logic between the live single-bar detector and the
    backtest's bar-by-bar walk: evaluates whether bar i's trailing
    LOOKBACK window of CONFIRMED pivots (confirmed_at_index <= i) forms a
    valid squeeze. Returns the signal dict fields (without pattern/
    timeframe/detected/classification wrapper) or None."""
    window_start = max(0, i - LOOKBACK)
    highs = [(p.index, p.price) for p in pivots
             if p.kind == "high" and p.confirmed_at_index <= i and p.index >= window_start]
    lows = [(p.index, p.price) for p in pivots
            if p.kind == "low" and p.confirmed_at_index <= i and p.index >= window_start]
    if len(highs) < MIN_PIVOTS_PER_SIDE or len(lows) < MIN_PIVOTS_PER_SIDE:
        return None

    slope_high, r2_high = _ols_slope_r2(highs)
    slope_low, r2_low = _ols_slope_r2(lows)
    if slope_high is None or slope_low is None:
        return None

    max_high_slope = (MAX_HIGH_DRIFT_PCT / 100.0) / LOOKBACK
    min_low_slope = (MIN_LOW_DRIFT_PCT / 100.0) / LOOKBACK

    if not (slope_high <= max_high_slope and slope_low >= min_low_slope
            and r2_high >= MIN_R2 and r2_low >= MIN_R2):
        return None

    return {
        "slope_high_pct_total": round(slope_high * LOOKBACK * 100, 3),
        "slope_low_pct_total": round(slope_low * LOOKBACK * 100, 3),
        "r2_high": round(r2_high, 3), "r2_low": round(r2_low, 3),
        "highs_used": len(highs), "lows_used": len(lows),
    }


def detect_triangle_squeeze(df: pd.DataFrame, date_col: str = "trade_date") -> dict:
    """df: DataFrame with date_col/open/high/low/close (any order, extra
    columns ignored), ideally ascending by date (re-sorted regardless).
    Evaluates the LATEST completed bar only -- live-scan convention
    matching every other detector in this codebase. Never raises;
    returns the empty/no-detection result on malformed input or
    insufficient history (needs MIN_BARS_REQUIRED rows)."""
    try:
        d = df.rename(columns={date_col: "date"}).copy()
        d["date"] = pd.to_datetime(d["date"])
        d = d.sort_values("date").reset_index(drop=True)
        if len(d) < MIN_BARS_REQUIRED:
            return _empty_result()
        d["atr14"] = _atr14(d)
        pivots = find_pivots(d, k=PIVOT_K)
        i = len(d) - 1

        extra = _evaluate_at(d, pivots, i)
        if extra is None:
            return _empty_result()

        signal_close = float(d["close"].iat[i])
        signal_high = float(d["high"].iat[i])
        stop_loss = round(signal_high * (1 + SL_BUFFER_PCT), 2)
        risk = stop_loss - signal_close
        target_1 = round(signal_close - RR_DEFAULT * risk, 2) if risk > 0 else None

        result = {
            "pattern": PATTERN_NAME_TRIANGLE_REG, "timeframe": TIMEFRAME_TR,
            "detected": True, "classification": BEARISH_TRIANGLE_REG, "direction": "BEAR",
            "pattern_date": d["date"].iat[i].strftime("%Y-%m-%d"),
            "entry_price": round(signal_close, 2),
            "stop_loss": stop_loss, "target_1": target_1,
        }
        result.update(extra)
        return result
    except Exception:
        return _empty_result()
