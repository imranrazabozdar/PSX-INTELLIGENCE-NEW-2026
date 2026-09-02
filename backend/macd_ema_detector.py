"""macd_ema_detector.py — EMA200-trend + MACD zero-line-cross-resumption
signal, translated from a reference systematic-trading notebook's
build_features()/ema_trend_signal() logic.

THE NOTEBOOK ran on 1-hour FX bars (EURUSD=X); every rule parameter below
is kept LITERALLY identical to the notebook (EMA_LEN=200, BACKCANDLES_PREV=5,
HIST_WINDOW=7, ATR_LEN=14) — the only adaptation for PSX is scaling the
MACD-histogram noise threshold relative to PRICE instead of a fixed
FX-scale absolute number (the notebook's raw `4e-6` was calibrated for
EURUSD trading near 1.1; PSX stock prices range from single digits to
thousands of rupees, so an absolute threshold would be meaningless).

SIGNAL (exact translation of ema_trend_signal() + build_features()):
  ema_signal:  +1 if EVERY bar in [i-BACKCANDLES_PREV..i] has
                  Open > EMA200 AND Close > EMA200        (confirmed uptrend)
               -1 if EVERY bar in that window has
                  Open < EMA200 AND Close < EMA200        (confirmed downtrend)
                0 otherwise
  MACD_signal: +1 if the MACD line crosses ABOVE the signal line, BOTH
                  currently below zero, AND the MACD histogram dipped
                  below -threshold at some point in the trailing
                  HIST_WINDOW bars (a real pullback preceded the cross,
                  not noise)
               -1 the exact mirror (crosses below, both above zero,
                  histogram spiked above +threshold in the trailing window)
                0 otherwise
  pre_signal = +1 only when ema_signal == +1 AND MACD_signal == +1
               -1 only when ema_signal == -1 AND MACD_signal == -1
                0 otherwise
  Then: the FIRST pre_signal immediately after a regime flip (opposite in
  sign to the last nonzero pre_signal) is zeroed out — the notebook's own
  whipsaw filter, applied verbatim.

TRADE MANAGEMENT: this module implements ONE of the notebook's five exit
variants — MACDEMA_ATRTrail (pure ATR-based trailing stop, no fixed
take-profit) — because it was the clear standout in the notebook's own
comparison (34.4% return / 1.82 profit factor / 1.23 Sharpe at an
OPTIMIZED atr_mult=3.75, vs. -5.5% to +2.1% for the other four variants
at their own optimized parameters). This module uses the strategy
class's own STATED DEFAULT (atr_mult=2.0), UNOPTIMIZED — consistent with
every other pattern detector in this codebase reporting honest, un-tuned
parameters rather than a fitted result. See backend/run_macdema_backtest.py
for the walk-forward PSX backtest of this exact rule.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EMA_LEN = 200
BACKCANDLES_PREV = 5          # "previous 5 + current" => window of 6
HIST_WINDOW = 7                # current bar + last 6
HIST_THRESH_FRACTION = 3.6e-6  # scaled from the notebook's FX-absolute 4e-6
                                # (4e-6 / ~1.1, EURUSD's approximate level)
ATR_LEN = 14
ATR_MULT_DEFAULT = 2.0         # the strategy class's own stated default

PATTERN_NAME_MACDEMA = "MACD+EMA200 Trend Resumption"
TIMEFRAME_MACDEMA = "1D"
BULLISH_MACDEMA = "BULLISH_MACDEMA_RESUMPTION"
BEARISH_MACDEMA = "BEARISH_MACDEMA_RESUMPTION"
NO_MACDEMA_SIGNAL = "NO_MACDEMA_SIGNAL"

MIN_BARS_REQUIRED = EMA_LEN + BACKCANDLES_PREV + HIST_WINDOW + 5


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _macd(close: pd.Series, fast=12, slow=26, signal=9):
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _ema_trend_signal(df: pd.DataFrame, backcandles_prev: int = BACKCANDLES_PREV) -> list:
    """Exact translation of the notebook's ema_trend_signal(): uses only
    the current and past candles (no lookahead)."""
    n = len(df)
    out = [0] * n
    ema = df["EMA200"].to_numpy()
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    for i in range(n):
        if i < backcandles_prev or np.isnan(ema[i]):
            continue
        start = i - backcandles_prev
        seg_o = o[start:i + 1]
        seg_c = c[start:i + 1]
        seg_ema = ema[start:i + 1]
        up = bool(np.all(seg_o > seg_ema) and np.all(seg_c > seg_ema))
        down = bool(np.all(seg_o < seg_ema) and np.all(seg_c < seg_ema))
        out[i] = 1 if up else (-1 if down else 0)
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """df: DataFrame with lowercase open/high/low/close columns, ascending
    by date (any other columns, e.g. a date column, pass through
    untouched). Returns a copy with EMA200/MACD/MACD_signal_line/
    MACD_hist/ema_signal/MACD_signal/pre_signal/ATR columns added, with
    leading rows that lack enough history for EMA200/MACD dropped
    (matches the notebook's own `out.dropna()`)."""
    out = df.copy()
    out["EMA200"] = _ema(out["close"], EMA_LEN)
    macd_line, signal_line, hist = _macd(out["close"])
    out["MACD"] = macd_line
    out["MACD_signal_line"] = signal_line
    out["MACD_hist"] = hist

    out["ema_signal"] = _ema_trend_signal(out)

    hist_thresh = out["close"] * HIST_THRESH_FRACTION
    macd_line_prev = macd_line.shift(1)
    macd_sig_prev = signal_line.shift(1)

    hist_below_win = hist.rolling(HIST_WINDOW, min_periods=HIST_WINDOW).min() < -hist_thresh
    hist_above_win = hist.rolling(HIST_WINDOW, min_periods=HIST_WINDOW).max() > hist_thresh

    bull_cross = (hist_below_win & (macd_line_prev <= macd_sig_prev) &
                  (macd_line > signal_line) & (macd_line < 0) & (signal_line < 0))
    bear_cross = (hist_above_win & (macd_line_prev >= macd_sig_prev) &
                  (macd_line < signal_line) & (macd_line > 0) & (signal_line > 0))

    out["MACD_signal"] = 0
    out.loc[bull_cross.fillna(False), "MACD_signal"] = 1
    out.loc[bear_cross.fillna(False), "MACD_signal"] = -1

    out["pre_signal"] = 0
    out.loc[(out["ema_signal"] == 1) & (out["MACD_signal"] == 1), "pre_signal"] = 1
    out.loc[(out["ema_signal"] == -1) & (out["MACD_signal"] == -1), "pre_signal"] = -1

    # Whipsaw filter, applied verbatim from the notebook: zero out the
    # FIRST signal immediately after a regime flip.
    s = out["pre_signal"].astype(int)
    prev_nz = s.replace(0, np.nan).ffill().shift(1)
    flip_first = (s != 0) & prev_nz.notna() & (s != prev_nz)
    out.loc[flip_first, "pre_signal"] = 0

    out["ATR"] = _atr(out, ATR_LEN)

    return out.dropna(subset=["EMA200", "MACD", "MACD_signal_line"]).reset_index(drop=True)


def _empty_result_macdema():
    return {"pattern": PATTERN_NAME_MACDEMA, "timeframe": TIMEFRAME_MACDEMA,
            "detected": False, "classification": NO_MACDEMA_SIGNAL}


class MACDEMADetector:
    """Live/latest-bar scanner — mirrors MorningStarDetector's shape
    (detect_patterns(df, date_col)) for consistency with the rest of this
    codebase's pattern modules."""

    def detect_patterns(self, df: pd.DataFrame, date_col: str = "trade_date") -> dict:
        """Never raises. Returns the empty/no-detection result if there's
        not enough history (needs MIN_BARS_REQUIRED bars — EMA200 alone
        needs ~200) or the latest completed bar carries no signal."""
        try:
            d = df.rename(columns={date_col: "date"}).copy()
            d["date"] = pd.to_datetime(d["date"])
            d = d.sort_values("date").reset_index(drop=True)
            if len(d) < MIN_BARS_REQUIRED:
                return _empty_result_macdema()
            feat = build_features(d)
            if feat.empty:
                return _empty_result_macdema()
            last = feat.iloc[-1]
            sig = int(last["pre_signal"])
            if sig == 0:
                return _empty_result_macdema()

            direction = "BULL" if sig == 1 else "BEAR"
            classification = BULLISH_MACDEMA if sig == 1 else BEARISH_MACDEMA
            close = float(last["close"])
            atr = float(last["ATR"]) if pd.notna(last["ATR"]) else None
            stop_loss = None
            if atr is not None and atr > 0:
                trail = ATR_MULT_DEFAULT * atr
                stop_loss = round(close - trail, 2) if sig == 1 else round(close + trail, 2)

            return {
                "pattern": PATTERN_NAME_MACDEMA,
                "timeframe": TIMEFRAME_MACDEMA,
                "detected": True,
                "classification": classification,
                "direction": direction,
                "pattern_date": last["date"].strftime("%Y-%m-%d"),
                "entry_price": round(close, 2),
                "stop_loss": stop_loss,
                # No fixed target -- this is a pure ATR-trailing-stop
                # strategy by design (see module docstring). Never
                # fabricate a target level for a rule that doesn't have one.
                "target_1": None,
            }
        except Exception:
            return _empty_result_macdema()
