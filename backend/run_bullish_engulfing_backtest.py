"""run_bullish_engulfing_backtest.py — TEMPORARY historical backtest
script for the Bullish Engulfing detector (patterns_engine.py), across
the full PSX universe. Not wired into app.py/streamlit_app.py.

detect_bullish_engulfing() only checks the LATEST completed candle pair
(the live-scan convention every detector in that module follows) -- it
is not a full-history scanner. Same approach as run_bearish_backtest.py:
reuse the exact pure helper functions (_classify_geometry,
_prior_downtrend, _atr14) directly over every historical consecutive
pair, rather than reimplementing the logic or re-calling the latest-pair
function once per historical date.

RISK PARAMETERS -- FLAGGED, NOT PART OF THE ORIGINAL MODULE: this
module's docstring states it "intentionally does NOT add trading
strategy, targets, stop losses". Bullish Engulfing has never had a
stop/target formula of its own. To answer "Target 1/2 win rate" and
"stop-loss hit rate" at all, this script applies the SAME measured-move
convention already established for this module's own bearish mirror
(detect_bearish_engulfing, patched this session) and for every other
active pattern engine:
    entry_price = Day 2 close
    stop_loss   = Day2_Low - max(0.5*ATR14, 0.005*entry_price)
    height      = Day2_High - Day2_Low
    target_1    = entry_price + 0.5*height
    target_2    = entry_price + 1.0*height
This is NOT a change to detect_bullish_engulfing() itself -- the
function is untouched, still geometry-only. These levels exist only
inside this backtest script, for measurement purposes.

Outcome simulation (long-side walk-forward, no lookahead: only bars
strictly after the signal's own close are ever used to decide the
outcome) -- identical structure to run_bearish_backtest.py's
_simulate_short, direction-inverted:
    close >= target_2        -> TARGET_2_HIT
    elif close >= target_1   -> TARGET_1_HIT
    elif close <= stop_loss  -> STOPPED_OUT
Fewer than MIN_FORWARD_BARS with no decisive exit -> INSUFFICIENT_DATA.
No decisive exit within MAX_HOLD_SESSIONS -> TIMEOUT.
"""

import os
import sqlite3
from collections import Counter

import pandas as pd

import patterns_engine as pe

MAX_HOLD_SESSIONS = 60
MIN_FORWARD_BARS = 5

OUTCOME_STOPPED_OUT = "STOPPED_OUT"
OUTCOME_TARGET_1_HIT = "TARGET_1_HIT"
OUTCOME_TARGET_2_HIT = "TARGET_2_HIT"
OUTCOME_TIMEOUT = "TIMEOUT"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_FORWARD_DATA"


def _simulate_long(sub: pd.DataFrame, signal_idx: int, entry_price, stop_loss, target_1, target_2):
    """sub: this symbol's full ascending daily OHLC DataFrame (date/close
    columns). signal_idx: positional index of the signal bar itself
    (entry). Walks forward from signal_idx+1 -- never looks at or before
    the signal bar when deciding the outcome."""
    if stop_loss is None or target_1 is None or target_2 is None:
        return OUTCOME_INSUFFICIENT_DATA, None

    forward = sub.iloc[signal_idx + 1: signal_idx + 1 + MAX_HOLD_SESSIONS]
    if len(forward) < MIN_FORWARD_BARS:
        return OUTCOME_INSUFFICIENT_DATA, None

    outcome = None
    hold_sessions = None
    for i, (_, bar) in enumerate(forward.iterrows(), start=1):
        close = bar["close"]
        if close >= target_2:
            outcome, hold_sessions = OUTCOME_TARGET_2_HIT, i
        elif close >= target_1:
            outcome, hold_sessions = OUTCOME_TARGET_1_HIT, i
        elif close <= stop_loss:
            outcome, hold_sessions = OUTCOME_STOPPED_OUT, i
        if outcome is not None:
            break

    if outcome is None:
        if len(forward) < MAX_HOLD_SESSIONS:
            return OUTCOME_INSUFFICIENT_DATA, None
        return OUTCOME_TIMEOUT, len(forward)

    return outcome, hold_sessions


def main():
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    conn = sqlite3.connect(os.path.join(backend_dir, "psx_v2.db"))
    symbols = [r[0] for r in conn.execute("select distinct symbol from daily_ohlc").fetchall()]

    rows_out = []

    for sym in symbols:
        raw_rows = conn.execute(
            "select trade_date,open,high,low,close,volume from daily_ohlc "
            "where symbol=? order by trade_date asc", (sym,)).fetchall()
        if len(raw_rows) < 30:
            continue
        rows = [{"trade_date": r[0], "open": r[1], "high": r[2], "low": r[3],
                 "close": r[4], "volume": r[5]} for r in raw_rows]

        candles = pe.normalize_daily_ohlc(rows, date_key="trade_date", as_of=None)
        if len(candles) < 30:
            continue
        df_long_sym = pd.DataFrame([{"date": c["date"], "close": c["close"]} for c in candles])

        for idx1 in range(len(candles) - 1):
            idx2 = idx1 + 1
            c1, c2 = candles[idx1], candles[idx2]
            geometry = pe._classify_geometry(c1, c2)
            if geometry is None:
                continue
            downtrend = pe._prior_downtrend(candles, idx1)
            if not downtrend:
                continue  # only backtest VALID (fully-confirmed) signals, not geometry-only

            atr14 = pe._atr14(candles, idx2)
            if atr14 is None:
                continue
            entry_price = c2["close"]
            atr_buffer = max(pe.STOP_LOSS_ATR_MULTIPLIER * atr14, pe.STOP_LOSS_MIN_BUFFER_PCT * entry_price)
            stop_loss = c2["low"] - atr_buffer
            pattern_height = c2["high"] - c2["low"]
            target_1 = entry_price + (0.5 * pattern_height)
            target_2 = entry_price + (1.0 * pattern_height)

            outcome, hold = _simulate_long(df_long_sym, idx2, entry_price, stop_loss, target_1, target_2)
            rows_out.append({"symbol": sym, "date": c2["date"], "outcome": outcome, "hold_sessions": hold})

    df = pd.DataFrame(rows_out)
    print(f"{'=' * 80}\nBULLISH ENGULFING -- full PSX universe backtest\n{'=' * 80}")
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


if __name__ == "__main__":
    main()
