"""run_three_line_strike_backtest.py — TEMPORARY historical backtest
script for the Bullish Three-Line Strike detector (patterns_engine.py),
across the full PSX universe. Not wired into app.py/streamlit_app.py.

detect_three_line_strike() only checks the LATEST 4-candle window (the
live-scan convention every detector in patterns_engine.py follows) -- it
is not a full-history scanner. Same approach as the Bullish/Bearish
Engulfing backtest scripts: reuse the exact pure helper functions
(_classify_geometry_tls, _prior_uptrend_tls, _avg_volume_20, _atr14)
directly over every historical consecutive 4-candle window, rather than
reimplementing the logic or re-calling the latest-window function once
per historical date.

Only VALID_THREE_LINE_STRIKE signals (geometry + prior uptrend + volume
confirmed) are backtested for outcomes -- same precedent as every other
dual-tier detector backtested this session (Bearish Engulfing, Cup &
Handle, Ascending Triangle): GEOMETRY_ONLY signals are counted
separately but not simulated, since they lack the volume confirmation
this pattern's own spec treats as a real filter, not decoration.

Outcome simulation (long-side walk-forward, no lookahead: only bars
strictly after the signal's own close are ever used to decide the
outcome) -- identical structure to run_bullish_engulfing_backtest.py's
_simulate_long:
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

    n_valid = 0
    n_geometry_only = 0
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
        raw_by_date = pe._raw_dedup_by_date(rows, "trade_date")
        df_long_sym = pd.DataFrame([{"date": c["date"], "close": c["close"]} for c in candles])

        for idx1 in range(len(candles) - 3):
            idx4 = idx1 + 3
            c1, c2, c3, c4 = candles[idx1], candles[idx1 + 1], candles[idx1 + 2], candles[idx4]

            if not pe._classify_geometry_tls(c1, c2, c3, c4):
                continue
            uptrend = pe._prior_uptrend_tls(candles, idx1)
            if not uptrend:
                continue  # hard gate, same as the live detector

            avg_vol20 = pe._avg_volume_20(candles, raw_by_date, idx4)
            day4_volume = raw_by_date.get(c4["date"], {}).get("volume")
            volume_confirmed = False
            if avg_vol20 is not None and day4_volume is not None:
                try:
                    volume_confirmed = float(day4_volume) >= pe.VOLUME_MIN_RATIO_TLS * avg_vol20
                except (TypeError, ValueError):
                    volume_confirmed = False

            if not volume_confirmed:
                n_geometry_only += 1
                continue  # counted, not simulated -- see module docstring

            n_valid += 1
            pattern_low = min(c1["low"], c2["low"], c3["low"], c4["low"])
            entry_price = c4["close"]
            atr14 = pe._atr14(candles, idx4)
            if atr14 is None:
                continue
            atr_buffer = max(pe.STOP_LOSS_ATR_MULTIPLIER * atr14, pe.STOP_LOSS_MIN_BUFFER_PCT * entry_price)
            stop_loss = pattern_low - atr_buffer
            height = c4["high"] - pattern_low
            target_1 = entry_price + height
            target_2 = entry_price + (height * 2.0)

            outcome, hold = _simulate_long(df_long_sym, idx4, entry_price, stop_loss, target_1, target_2)
            rows_out.append({"symbol": sym, "date": c4["date"], "outcome": outcome, "hold_sessions": hold})

    print(f"{'=' * 80}\nBULLISH THREE-LINE STRIKE -- full PSX universe backtest\n{'=' * 80}")
    print(f"Total signals generated: {n_valid + n_geometry_only}")
    print(f"  VALID_THREE_LINE_STRIKE (geometry + uptrend + volume confirmed): {n_valid}")
    print(f"  THREE_LINE_STRIKE_GEOMETRY_ONLY (volume not confirmed): {n_geometry_only}")
    print("(Only VALID signals are simulated below -- see module docstring.)")

    df = pd.DataFrame(rows_out)
    if df.empty:
        print("\nNo VALID signals -- nothing further to report.")
        return

    known = df[df["outcome"] != OUTCOME_INSUFFICIENT_DATA]
    n_known = len(known)
    print(f"\nVALID signals with a resolvable outcome (>= {MIN_FORWARD_BARS} forward bars): {n_known} "
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
