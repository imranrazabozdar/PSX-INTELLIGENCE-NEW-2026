"""level_breakout_detector.py — horizontal support/resistance "Level
Break Out" detector, translated from a reference systematic-trading
notebook (EURUSD daily, 2003-2023). NOTE: two notebook uploads with this
name were provided this session and are byte-for-byte identical (same
code, same data, same backtest output) -- there is exactly one strategy
here, not two.

RULE (translated 1:1 from detect_structure()): over a trailing BACKCANDLES
(40) window, offset back by PIVOT_K bars to guarantee every pivot in it is
already fully confirmed (the notebook's own comment: "window must be
greater than pivot window to avoid look ahead bias") -- take the last 3
pivot lows and the last 3 pivot highs found in that window:
  - SUPPORT BREAKDOWN (levelbreak=1, SHORT): all 3 lows sit within
    ZONE_WIDTH_PCT of their mean (a flat horizontal level) AND the
    current close sits more than 2x that tolerance BELOW the mean.
  - RESISTANCE BREAKOUT (levelbreak=2, LONG): all 3 highs sit within
    ZONE_WIDTH_PCT of their mean AND the current close sits more than 2x
    that tolerance ABOVE the mean.
  - If (rare) both fire on the same bar, resistance wins -- the notebook
    checks lows first then highs, and the second assignment overwrites
    the first; kept exactly as written, not "fixed" into an either/or.

Classical breakout logic (buy strength, sell weakness) -- the OPPOSITE of
backend/triangle_regression_detector.py's contrarian short-the-squeeze
rule from a different reference notebook. Do not confuse the two.

PIVOTS: reuses this codebase's own pivots.find_pivots() (fractal,
no-lookahead-safe via confirmed_at_index) rather than reimplementing the
notebook's isPivot() from scratch -- same reuse discipline every other
detector added this session follows.

THRESHOLD ADAPTATION (stated plainly): the notebook's zone_width=0.01 is
an ABSOLUTE EUR/USD price band (~0.9% of a ~1.10 price) -- meaningless
reused literally on PSX stocks ranging from single digits to thousands
of rupees. Re-expressed as ZONE_WIDTH_PCT = 1.0% of the level's own
price (mean of the 3 touches), with the breakout confirmation distance
kept as the notebook's own literal "zone_width*2" (2.0% of the level).
perc=0.03 (fixed 3% stop) and TPSLRatio=2 (2:1 reward:risk) are already
dimensionless percentages and are reused literally, unchanged.

TRADE RULE: entry at the NEXT bar's open (the notebook's Backtest() call
has no trade_on_close=True, so backtesting.py's default next-bar-open
execution applies -- unlike triangle_regression_detector.py, which is a
different notebook that DID set trade_on_close=True). SL/TP are anchored
to the signal bar's own close, at the class's stated defaults (perc=0.03,
TPSLRatio=2), unoptimized. The notebook ALSO closes any open position
early if RSI(14) > 80 (long) or < 20 (short) -- a position-MANAGEMENT
rule, not an entry filter (it plays no role in whether a signal fires);
implemented in the walk-forward backtest, not in this live single-bar
detector (a live scanner has no open position to manage).
"""

import numpy as np
import pandas as pd

from pivots import find_pivots

BACKCANDLES = 40
PIVOT_K = 6                 # the notebook's window=6, reused literally as pivots.find_pivots' k
ZONE_WIDTH_PCT = 1.0        # tolerance band for "3 touches at the same level" (see module docstring)

SL_PCT = 0.03                # the notebook's perc=0.03
TP_RR = 2.0                  # the notebook's TPSLRatio=2
RSI_LEN = 14
RSI_EXIT_LONG = 80
RSI_EXIT_SHORT = 20

PATTERN_NAME_LEVEL_BREAKOUT = "Level Break Out"
TIMEFRAME_LB = "1D"
BULLISH_LEVEL_BREAKOUT = "BULLISH_LEVEL_BREAKOUT"
BEARISH_LEVEL_BREAKDOWN = "BEARISH_LEVEL_BREAKDOWN"
NO_LEVEL_BREAKOUT_SIGNAL = "NO_LEVEL_BREAKOUT_SIGNAL"

MIN_BARS_REQUIRED = BACKCANDLES + 2 * PIVOT_K + 5


def _empty_result():
    return {"pattern": PATTERN_NAME_LEVEL_BREAKOUT, "timeframe": TIMEFRAME_LB,
            "detected": False, "classification": NO_LEVEL_BREAKOUT_SIGNAL}


def _atr14(df: pd.DataFrame) -> pd.Series:
    """find_pivots() requires an 'atr14' column (its amplitude filter) --
    same EWM(alpha=1/14) convention already used elsewhere in this
    codebase (e.g. macd_ema_detector._atr14)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean()


def _rsi14(close: pd.Series, length: int = RSI_LEN) -> pd.Series:
    """Standard Wilder's-smoothing RSI, same EWM(alpha=1/length) convention
    already used for ATR elsewhere in this codebase (e.g.
    macd_ema_detector._atr14)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _evaluate_at(d: pd.DataFrame, pivots: list, i: int):
    """Shared logic between the live single-bar detector and the
    backtest's bar-by-bar walk. Returns {"levelbreak": 1|2,
    "level_price": float} or None. `i` is the SIGNAL candle (the notebook's
    `candle`)."""
    window_start = i - BACKCANDLES - PIVOT_K
    window_end = i - PIVOT_K  # exclusive, matches df.iloc[candle-backcandles-window:candle-window]
    if window_start < 0:
        return None

    highs = [p.price for p in pivots
             if p.kind == "high" and window_start <= p.index < window_end and p.confirmed_at_index <= i]
    lows = [p.price for p in pivots
            if p.kind == "low" and window_start <= p.index < window_end and p.confirmed_at_index <= i]
    highs = highs[-3:]
    lows = lows[-3:]

    close = float(d["close"].iat[i])
    levelbreak = 0
    level_price = None

    if len(lows) == 3:
        mean_low = sum(lows) / 3.0
        zone_width = mean_low * (ZONE_WIDTH_PCT / 100.0)
        support_condition = all(abs(low - mean_low) <= zone_width for low in lows)
        if support_condition and (mean_low - close) > zone_width * 2:
            levelbreak = 1
            level_price = mean_low

    if len(highs) == 3:
        mean_high = sum(highs) / 3.0
        zone_width = mean_high * (ZONE_WIDTH_PCT / 100.0)
        resistance_condition = all(abs(high - mean_high) <= zone_width for high in highs)
        if resistance_condition and (close - mean_high) > zone_width * 2:
            levelbreak = 2  # overwrites a support-breakdown hit on the same bar, matching the notebook literally
            level_price = mean_high

    if levelbreak == 0:
        return None
    return {"levelbreak": levelbreak, "level_price": round(level_price, 2)}


def detect_level_breakout(df: pd.DataFrame, date_col: str = "trade_date") -> dict:
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
        levelbreak = extra["levelbreak"]
        if levelbreak == 2:
            classification, direction = BULLISH_LEVEL_BREAKOUT, "BULL"
            stop_loss = round(signal_close * (1 - SL_PCT), 2)
            risk = signal_close - stop_loss
            target_1 = round(signal_close + risk * TP_RR, 2)
        else:
            classification, direction = BEARISH_LEVEL_BREAKDOWN, "BEAR"
            stop_loss = round(signal_close * (1 + SL_PCT), 2)
            risk = stop_loss - signal_close
            target_1 = round(signal_close - risk * TP_RR, 2)

        return {
            "pattern": PATTERN_NAME_LEVEL_BREAKOUT, "timeframe": TIMEFRAME_LB,
            "detected": True, "classification": classification, "direction": direction,
            "pattern_date": d["date"].iat[i].strftime("%Y-%m-%d"),
            "entry_price": round(signal_close, 2),
            "stop_loss": stop_loss, "target_1": target_1,
            "level_price": extra["level_price"],
        }
    except Exception:
        return _empty_result()
