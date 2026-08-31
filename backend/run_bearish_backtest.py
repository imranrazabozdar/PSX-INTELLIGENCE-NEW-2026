"""run_bearish_backtest.py — TEMPORARY historical backtest script for the
Evening Star and Bearish Engulfing detectors, across the full PSX
universe. Not wired into app.py/streamlit_app.py; run directly:

    python run_bearish_backtest.py

For Bearish Engulfing (patterns_engine.py), detect_bearish_engulfing()
only ever checks the LATEST completed candle pair (the live-scan
convention every detector in that module follows) -- it is not a
full-history scanner. Rather than re-calling it once per historical date
(O(n^2) per symbol), this script reuses its exact pure helper functions
(_classify_geometry_bearish, _prior_uptrend, _avg_volume_20,
_swing_high_20, _atr14) directly in a single forward pass over every
consecutive candle pair -- same logic, not reimplemented, just applied to
every historical pair instead of only the latest one.

For Evening Star (morning_star_detector.py), detect_evening_star() is
already a full-history vectorized scanner -- called directly, as-is.

Outcome simulation (short-side walk-forward, no lookahead: only bars
strictly after the signal's own close are ever used to decide the
outcome):
  For each signal, walk forward bar-by-bar (close price only) up to
  MAX_HOLD_SESSIONS:
    - close <= target_2         -> TARGET_2_HIT
    - elif close <= target_1    -> TARGET_1_HIT
    - elif close >= stop_loss   -> STOPPED_OUT
  (checked in that order per bar, so a bar clearing multiple thresholds
  records the better outcome -- same priority-ordering convention as
  pattern_backtester.py's long-side walk-forward, direction-inverted.)
  Fewer than MIN_FORWARD_BARS bars available with no decisive exit yet
  -> INSUFFICIENT_DATA. No decisive exit within MAX_HOLD_SESSIONS ->
  TIMEOUT.

  "Win rate for Target 1" = fraction of signals with known outcome whose
  outcome is TARGET_1_HIT or TARGET_2_HIT (price reached at least Target
  1 before the stop). "Win rate for Target 2" = fraction whose outcome is
  specifically TARGET_2_HIT. "Stop hit rate" = fraction STOPPED_OUT.
"""

import os
import sqlite3
from collections import Counter

import numpy as np
import pandas as pd

import patterns_engine as pe
from morning_star_detector import MorningStarDetector

MAX_HOLD_SESSIONS = 60
MIN_FORWARD_BARS = 5

OUTCOME_STOPPED_OUT = "STOPPED_OUT"
OUTCOME_TARGET_1_HIT = "TARGET_1_HIT"
OUTCOME_TARGET_2_HIT = "TARGET_2_HIT"
OUTCOME_TIMEOUT = "TIMEOUT"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_FORWARD_DATA"


def _simulate_short(sub: pd.DataFrame, signal_idx: int, entry_price, stop_loss, target_1, target_2):
    """sub: this symbol's full ascending daily OHLC DataFrame (date/close
    columns). signal_idx: positional index of the signal bar itself
    (entry). Walks forward from signal_idx+1 -- never looks at or before
    the signal bar when deciding the outcome."""
    if stop_loss is None or target_1 is None or target_2 is None:
        return OUTCOME_INSUFFICIENT_DATA, None, None

    forward = sub.iloc[signal_idx + 1: signal_idx + 1 + MAX_HOLD_SESSIONS]
    if len(forward) < MIN_FORWARD_BARS:
        return OUTCOME_INSUFFICIENT_DATA, None, None

    outcome = None
    hold_sessions = None
    for i, (_, bar) in enumerate(forward.iterrows(), start=1):
        close = bar["close"]
        if close <= target_2:
            outcome, hold_sessions = OUTCOME_TARGET_2_HIT, i
        elif close <= target_1:
            outcome, hold_sessions = OUTCOME_TARGET_1_HIT, i
        elif close >= stop_loss:
            outcome, hold_sessions = OUTCOME_STOPPED_OUT, i
        if outcome is not None:
            break

    if outcome is None:
        if len(forward) < MAX_HOLD_SESSIONS:
            return OUTCOME_INSUFFICIENT_DATA, None, None
        return OUTCOME_TIMEOUT, len(forward), entry_price - forward["close"].iat[-1]

    pnl = entry_price - forward["close"].iat[hold_sessions - 1]  # short: profit when close fell
    return outcome, hold_sessions, pnl


def _report(name, rows_out):
    df = pd.DataFrame(rows_out)
    print(f"\n{'=' * 80}\n{name}\n{'=' * 80}")
    print(f"Total signals generated: {len(df)}")
    if df.empty:
        print("No signals -- nothing further to report.")
        return

    known = df[df["outcome"] != OUTCOME_INSUFFICIENT_DATA]
    n_known = len(known)
    print(f"Signals with a resolvable outcome (>= {MIN_FORWARD_BARS} forward bars): {n_known} "
          f"({len(df) - n_known} excluded as insufficient forward data)")
    if n_known == 0:
        return

    win_t1 = known["outcome"].isin([OUTCOME_TARGET_1_HIT, OUTCOME_TARGET_2_HIT]).sum()
    win_t2 = (known["outcome"] == OUTCOME_TARGET_2_HIT).sum()
    stopped = known[known["outcome"] == OUTCOME_STOPPED_OUT]
    timeouts = (known["outcome"] == OUTCOME_TIMEOUT).sum()

    print(f"Win rate, Target 1 (reached Target 1 or better before Stop): {win_t1 / n_known:.4f} ({win_t1}/{n_known})")
    print(f"Win rate, Target 2 (reached Target 2 before Stop):           {win_t2 / n_known:.4f} ({win_t2}/{n_known})")
    print(f"Stop-loss hit rate:                                          {len(stopped) / n_known:.4f} ({len(stopped)}/{n_known})")
    print(f"Timeout rate (held full {MAX_HOLD_SESSIONS} sessions, no decisive exit): {timeouts / n_known:.4f} ({timeouts}/{n_known})")

    winners = known[known["outcome"].isin([OUTCOME_TARGET_1_HIT, OUTCOME_TARGET_2_HIT])]
    losers = known[known["outcome"] == OUTCOME_STOPPED_OUT]
    med_hold_win = winners["hold_sessions"].median() if len(winners) else None
    med_hold_loss = losers["hold_sessions"].median() if len(losers) else None
    print(f"Median hold time, WINNING trades (sessions): {med_hold_win}")
    print(f"Median hold time, LOSING (stopped-out) trades (sessions): {med_hold_loss}")

    print(f"\nFull outcome distribution: {dict(Counter(known['outcome']))}")


def main():
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    conn = sqlite3.connect(os.path.join(backend_dir, "psx_v2.db"))
    symbols = [r[0] for r in conn.execute("select distinct symbol from daily_ohlc").fetchall()]

    detector = MorningStarDetector()

    evening_star_rows = []
    bearish_engulfing_rows = []

    for sym in symbols:
        raw_rows = conn.execute(
            "select trade_date,open,high,low,close,volume from daily_ohlc "
            "where symbol=? order by trade_date asc", (sym,)).fetchall()
        if len(raw_rows) < 40:
            continue
        rows = [{"trade_date": r[0], "open": r[1], "high": r[2], "low": r[3],
                 "close": r[4], "volume": r[5]} for r in raw_rows]

        # --- Evening Star: full-history vectorized scan, called as-is. ---
        df = pd.DataFrame(rows)
        try:
            es_hits = detector.detect_evening_star(df, date_col="trade_date")
        except Exception:
            es_hits = pd.DataFrame()

        if not es_hits.empty:
            sub = df.rename(columns={"trade_date": "date"}).copy()
            sub["date"] = pd.to_datetime(sub["date"])
            sub = sub.sort_values("date").reset_index(drop=True)
            for _, sig in es_hits.iterrows():
                match = sub.index[sub["date"] == sig["date"]]
                if len(match) == 0:
                    continue
                signal_idx = match[0]
                outcome, hold, pnl = _simulate_short(sub, signal_idx, sig["entry_price"],
                                                      sig["stop_loss"], sig["target_1"], sig["target_2"])
                evening_star_rows.append({"symbol": sym, "date": sig["date"], "outcome": outcome,
                                           "hold_sessions": hold, "pnl": pnl})

        # --- Bearish Engulfing: reuse the exact pure helper functions over
        # every consecutive candle pair (full-history scan), since
        # detect_bearish_engulfing() itself only checks the latest pair. ---
        candles = pe.normalize_daily_ohlc(rows, date_key="trade_date", as_of=None)
        if len(candles) < 40:
            continue
        raw_by_date = pe._raw_dedup_by_date(rows, "trade_date")
        df_long_sym = pd.DataFrame([{"date": c["date"], "close": c["close"]} for c in candles])

        for idx1 in range(len(candles) - 1):
            idx2 = idx1 + 1
            c1, c2 = candles[idx1], candles[idx2]
            geometry = pe._classify_geometry_bearish(c1, c2)
            if geometry is None:
                continue
            uptrend = bool(pe._prior_uptrend(candles, idx1))
            avg_vol20 = pe._avg_volume_20(candles, raw_by_date, idx2)
            day2_volume = raw_by_date.get(c2["date"], {}).get("volume")
            volume_confirmed = False
            if avg_vol20 is not None and day2_volume is not None:
                try:
                    volume_confirmed = float(day2_volume) >= pe.VOLUME_MIN_RATIO_DAY2 * avg_vol20
                except (TypeError, ValueError):
                    volume_confirmed = False
            swing_high = pe._swing_high_20(candles, idx1)
            near_resistance = bool(swing_high and c1["high"] >= swing_high * (1 - pe.NEAR_RESISTANCE_MAX_PCT / 100.0))
            if not (uptrend and volume_confirmed and near_resistance):
                continue  # only backtest VALID (fully-confirmed) signals, not geometry-only

            atr14 = pe._atr14(candles, idx2)
            if atr14 is None:
                continue
            entry_price = c2["close"]
            atr_buffer = max(pe.STOP_LOSS_ATR_MULTIPLIER * atr14, pe.STOP_LOSS_MIN_BUFFER_PCT * entry_price)
            stop_loss = c2["high"] + atr_buffer
            pattern_height = c2["high"] - c2["low"]
            target_1 = entry_price - (0.5 * pattern_height)
            target_2 = entry_price - (1.0 * pattern_height)

            outcome, hold, pnl = _simulate_short(df_long_sym, idx2, entry_price, stop_loss, target_1, target_2)
            bearish_engulfing_rows.append({"symbol": sym, "date": c2["date"], "outcome": outcome,
                                            "hold_sessions": hold, "pnl": pnl})

    _report("EVENING STAR -- full PSX universe backtest", evening_star_rows)
    _report("BEARISH ENGULFING -- full PSX universe backtest", bearish_engulfing_rows)


if __name__ == "__main__":
    main()
