"""run_hstop_backtest.py — TEMPORARY historical backtest script for the
Head & Shoulders Top detector (advanced_pattern_engine.py), across the
full PSX universe. Not wired into app.py/streamlit_app.py.

detect_head_shoulders_top() is already a full-history vectorized scanner
(same per-symbol groupby/preflight/enrich/pivot pipeline as scan()), so
it is called directly, as-is -- no reimplementation needed, unlike the
latest-pair-only detectors backtested earlier this session.

Outcome simulation (short-side walk-forward, no lookahead: only bars
strictly after the signal's own close are ever used to decide the
outcome) -- identical structure to run_bearish_backtest.py's
_simulate_short:
    close <= target_2        -> TARGET_2_HIT
    elif close <= target_1   -> TARGET_1_HIT
    elif close >= stop_loss  -> STOPPED_OUT
Fewer than MIN_FORWARD_BARS with no decisive exit -> INSUFFICIENT_DATA.
No decisive exit within MAX_HOLD_SESSIONS -> TIMEOUT.
"""

import os
import sqlite3
from collections import Counter

import pandas as pd

from advanced_pattern_engine import AdvancedPatternEngine

MAX_HOLD_SESSIONS = 60
MIN_FORWARD_BARS = 5

OUTCOME_STOPPED_OUT = "STOPPED_OUT"
OUTCOME_TARGET_1_HIT = "TARGET_1_HIT"
OUTCOME_TARGET_2_HIT = "TARGET_2_HIT"
OUTCOME_TIMEOUT = "TIMEOUT"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_FORWARD_DATA"


def _simulate_short(sub: pd.DataFrame, signal_idx: int, entry_price, stop_loss, target_1, target_2):
    if stop_loss is None or target_1 is None or target_2 is None:
        return OUTCOME_INSUFFICIENT_DATA, None

    forward = sub.iloc[signal_idx + 1: signal_idx + 1 + MAX_HOLD_SESSIONS]
    if len(forward) < MIN_FORWARD_BARS:
        return OUTCOME_INSUFFICIENT_DATA, None

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
            return OUTCOME_INSUFFICIENT_DATA, None
        return OUTCOME_TIMEOUT, len(forward)

    return outcome, hold_sessions


def _report(rows_out):
    df = pd.DataFrame(rows_out)
    print(f"{'=' * 80}\nHEAD & SHOULDERS TOP -- full PSX universe backtest\n{'=' * 80}")
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

    if len(known):
        print(f"\nBy strength/confidence -- median confidence_score of signals: {df['confidence_score'].median():.4f}")


def main():
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    conn = sqlite3.connect(os.path.join(backend_dir, "psx_v2.db"))
    symbols = [r[0] for r in conn.execute("select distinct symbol from daily_ohlc").fetchall()]

    frames = []
    for sym in symbols:
        rows = conn.execute(
            "select symbol,trade_date as date,open,high,low,close,volume from daily_ohlc "
            "where symbol=? order by trade_date asc", (sym,)).fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"]))
    df_long = pd.concat(frames, ignore_index=True)
    print(f"Loaded {len(df_long)} rows across {df_long['symbol'].nunique()} symbols.")

    engine = AdvancedPatternEngine()
    result = engine.detect_head_shoulders_top(df_long)
    print(f"Engine produced {len(result.signals)} signals.")

    by_symbol = {s: g.sort_values("date").reset_index(drop=True) for s, g in df_long.groupby("symbol", sort=False)}

    rows_out = []
    for sig in result.signals:
        sub = by_symbol.get(sig["symbol"])
        match = sub.index[sub["date"] == sig["signal_date"]]
        if len(match) == 0:
            continue
        signal_idx = match[0]
        outcome, hold = _simulate_short(sub, signal_idx, sig["entry_price"], sig["stop_loss"],
                                         sig["target_partial"], sig["target_measured"])
        rows_out.append({"symbol": sig["symbol"], "date": sig["signal_date"], "outcome": outcome,
                          "hold_sessions": hold, "confidence_score": sig["confidence_score"]})

    _report(rows_out)


if __name__ == "__main__":
    main()
