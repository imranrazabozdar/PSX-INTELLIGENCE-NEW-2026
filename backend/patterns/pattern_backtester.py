"""pattern_backtester.py — walk-forward backtest of AdvancedPatternEngine
signals, NOT hindsight curve-fitting.

The engine's own no-lookahead guarantee (advanced_pattern_engine.py §0)
already ensures `signal_date` is a real entry point using only data up to
and including that date. This module's only job is to walk FORWARD from
each signal's entry bar through the same historical DataFrame and record
what actually happened -- it never re-runs or re-evaluates the engine,
and never reads a bar before signal_date when deciding anything about
that signal (see _simulate_one's forward-only slicing, and the
`exit_date < signal_date` assertion in validation).

Outcome priority per bar, exactly as specified (checked in this order --
target_2 is checked before target_1 so a bar that clears BOTH records the
better outcome, not the first one matched):
  1. close <= stop_loss        -> STOPPED_OUT   (exit at that close)
  2. close >= target_2         -> TARGET_2_HIT  (exit at that close)
  3. close >= target_1         -> TARGET_1_HIT  (exit AT target_1, not the
                                                  triggering close -- per spec)
  4. max_hold_sessions reached -> TIMEOUT        (exit at that bar's close)

A signal with fewer than 5 forward bars at all is ALWAYS
INSUFFICIENT_FORWARD_DATA (rule 3), regardless of anything else. Otherwise,
if a decisive exit (stop/target1/target2) happens within however many
forward bars exist, that real outcome is recorded no matter how few bars
were available -- a decisive hit doesn't need the full window to be
conclusive. Only when NO decisive exit occurs AND fewer than
max_hold_sessions bars were available to look forward through is the
signal marked INSUFFICIENT_FORWARD_DATA instead of TIMEOUT -- a "timeout"
with fewer bars than the intended hold period wouldn't mean anything.
"""

import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import numpy as np
import pandas as pd

from advanced_pattern_engine import AdvancedPatternEngine
from patterns.advanced_pattern_adapter import STRENGTH_STRONG_THRESHOLD, STRENGTH_MODERATE_THRESHOLD

OUTCOME_STOPPED_OUT = "STOPPED_OUT"
OUTCOME_TARGET_1_HIT = "TARGET_1_HIT"
OUTCOME_TARGET_2_HIT = "TARGET_2_HIT"
OUTCOME_TIMEOUT = "TIMEOUT"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_FORWARD_DATA"

_DECISIVE_OUTCOMES = {OUTCOME_STOPPED_OUT, OUTCOME_TARGET_1_HIT, OUTCOME_TARGET_2_HIT}

MIN_FORWARD_BARS = 5  # rule 3 -- an absolute floor, checked before anything else

SIGNAL_COLUMNS = [
    "symbol", "pattern_type", "pattern_subtype", "signal_date", "entry_price",
    "stop_loss", "target_1", "target_2", "confidence_score", "strength_rating",
    "outcome", "exit_price", "exit_date", "hold_sessions", "pnl_pct",
    "risk_reward_actual", "prior_decline_pct_actual", "stop_loss_pct_from_entry",
]


def _strength_rating(confidence_score: float) -> str:
    """Same three-tier mapping as advanced_pattern_adapter._strength_rating,
    reusing its exact named thresholds -- one source of truth for the
    confidence_score -> label mapping, not a second copy that could drift."""
    if confidence_score >= STRENGTH_STRONG_THRESHOLD:
        return "STRONG"
    if confidence_score >= STRENGTH_MODERATE_THRESHOLD:
        return "MODERATE"
    return "WEAK"


class PatternBacktester:
    """Walk-forward backtester for AdvancedPatternEngine signals.

    Usage:
        bt = PatternBacktester(max_hold_sessions=60)
        signal_df, summary = bt.run(df_long)           # scans AND backtests
        # -- or, if you already have a ScanResult --
        signal_df, summary = bt.backtest_signals(df_long, result.signals)
    """

    def __init__(self, max_hold_sessions: int = 60):
        self.max_hold_sessions = max_hold_sessions

    # ------------------------------------------------------------ public --
    def run(self, df_long: pd.DataFrame, engine: AdvancedPatternEngine = None):
        engine = engine or AdvancedPatternEngine()
        result = engine.scan(df_long)
        return self.backtest_signals(df_long, result.signals)

    def backtest_signals(self, df_long: pd.DataFrame, signals: list):
        by_symbol = {sym: g.sort_values("date").reset_index(drop=True)
                     for sym, g in df_long.groupby("symbol", sort=False)}

        rows = [self._simulate_one(by_symbol.get(sig["symbol"]), sig) for sig in signals]
        signal_df = pd.DataFrame(rows, columns=SIGNAL_COLUMNS) if rows else pd.DataFrame(columns=SIGNAL_COLUMNS)
        summary = self._summarize(signal_df)
        return signal_df, summary

    # --------------------------------------------------------- internals --
    def _simulate_one(self, sub: pd.DataFrame, sig: dict) -> dict:
        base = {
            "symbol": sig["symbol"], "pattern_type": sig["pattern_type"],
            "pattern_subtype": sig["pattern_subtype"], "signal_date": sig["signal_date"],
            "entry_price": sig["entry_price"], "stop_loss": sig["stop_loss"],
            "target_1": sig["target_partial"], "target_2": sig["target_measured"],
            "confidence_score": sig["confidence_score"],
            "strength_rating": _strength_rating(sig["confidence_score"]),
            "prior_decline_pct_actual": sig["prior_decline_pct_actual"],
            "stop_loss_pct_from_entry": sig["stop_loss_pct_from_entry"],
        }
        insufficient = dict(base, outcome=OUTCOME_INSUFFICIENT_DATA, exit_price=np.nan,
                             exit_date=None, hold_sessions=np.nan, pnl_pct=np.nan, risk_reward_actual=np.nan)

        if sub is None or sub.empty:
            return insufficient

        matches = sub.index[sub["date"] == sig["signal_date"]]
        if len(matches) == 0:
            return insufficient  # can't locate the entry bar at all -- never fabricate a position
        entry_idx = matches[0]

        forward = sub.iloc[entry_idx + 1: entry_idx + 1 + self.max_hold_sessions]
        if len(forward) < MIN_FORWARD_BARS:
            return insufficient

        entry_price = base["entry_price"]
        stop_loss = base["stop_loss"]
        target_1 = base["target_1"]
        target_2 = base["target_2"]
        risk = entry_price - stop_loss

        outcome = None
        exit_price = None
        exit_date = None
        hold_sessions = None
        for i, (_, bar) in enumerate(forward.iterrows(), start=1):
            close = bar["close"]
            if close <= stop_loss:
                outcome, exit_price = OUTCOME_STOPPED_OUT, close
            elif close >= target_2:
                outcome, exit_price = OUTCOME_TARGET_2_HIT, close
            elif close >= target_1:
                outcome, exit_price = OUTCOME_TARGET_1_HIT, target_1  # exit AT target_1, per spec
            if outcome is not None:
                exit_date, hold_sessions = bar["date"], i
                break

        if outcome is None:
            # No decisive exit found within the bars actually available.
            if len(forward) < self.max_hold_sessions:
                return insufficient  # ran out of data before a real timeout could be called
            last_bar = forward.iloc[-1]
            outcome, exit_price, exit_date, hold_sessions = (
                OUTCOME_TIMEOUT, last_bar["close"], last_bar["date"], len(forward))

        pnl_pct = (exit_price - entry_price) / entry_price * 100.0 if entry_price else np.nan
        risk_reward_actual = (exit_price - entry_price) / risk if risk > 0 else np.nan

        return dict(base, outcome=outcome, exit_price=exit_price, exit_date=exit_date,
                    hold_sessions=hold_sessions, pnl_pct=pnl_pct, risk_reward_actual=risk_reward_actual)

    def _summarize(self, signal_df: pd.DataFrame) -> dict:
        def group_stats(df: pd.DataFrame) -> dict:
            n_signals = len(df)
            excluded = df[df["outcome"] == OUTCOME_INSUFFICIENT_DATA]
            included = df[df["outcome"] != OUTCOME_INSUFFICIENT_DATA]
            n_excluded = len(excluded)
            denom = len(included) or 1  # avoid /0; rates are 0 when denom would be 0 anyway

            def rate(outcome_name):
                return float((included["outcome"] == outcome_name).sum()) / denom if len(included) else 0.0

            win = float(included["outcome"].isin([OUTCOME_TARGET_1_HIT, OUTCOME_TARGET_2_HIT]).sum()) / denom \
                if len(included) else 0.0

            def best_worst(asc: bool):
                if included.empty or included["pnl_pct"].isna().all():
                    return None
                row = included.loc[included["pnl_pct"].idxmin() if asc else included["pnl_pct"].idxmax()]
                return {"symbol": row["symbol"], "signal_date": row["signal_date"], "pnl_pct": round(row["pnl_pct"], 2)}

            stopped = included[included["outcome"] == OUTCOME_STOPPED_OUT]

            return {
                "n_signals": n_signals,
                "n_excluded": n_excluded,
                "win_rate": round(win, 4),
                "target_2_rate": round(rate(OUTCOME_TARGET_2_HIT), 4),
                "pct_hitting_target_2": round(rate(OUTCOME_TARGET_2_HIT), 4),
                "stop_rate": round(rate(OUTCOME_STOPPED_OUT), 4),
                "timeout_rate": round(rate(OUTCOME_TIMEOUT), 4),
                "avg_pnl_pct": round(float(included["pnl_pct"].mean()), 4) if len(included) else None,
                "median_pnl_pct": round(float(included["pnl_pct"].median()), 4) if len(included) else None,
                "avg_loss_when_stopped": round(float(stopped["pnl_pct"].mean()), 4) if len(stopped) else None,
                "avg_hold_sessions": round(float(included["hold_sessions"].mean()), 2) if len(included) else None,
                "avg_confidence_score": round(float(df["confidence_score"].mean()), 4) if n_signals else None,
                "best_signal": best_worst(asc=False),
                "worst_signal": best_worst(asc=True),
            }

        summary = {"overall": group_stats(signal_df)}
        for key, col in (("by_pattern_type", "pattern_type"), ("by_pattern_subtype", "pattern_subtype"),
                          ("by_strength_rating", "strength_rating")):
            summary[key] = {val: group_stats(g) for val, g in signal_df.groupby(col, sort=False)} \
                if not signal_df.empty else {}
        return summary


def _format_summary_table(summary: dict) -> str:
    """Plain-text rendering of the summary dict -- one block per grouping."""
    lines = []
    cols = ["n_signals", "n_excluded", "win_rate", "target_2_rate", "pct_hitting_target_2", "stop_rate",
            "timeout_rate", "avg_pnl_pct", "median_pnl_pct", "avg_loss_when_stopped",
            "avg_hold_sessions", "avg_confidence_score"]

    def render_block(title, stats_by_key):
        lines.append(f"\n=== {title} ===")
        header = f"{'':22s}" + "".join(f"{c:>16s}" for c in cols)
        lines.append(header)
        for key, stats in stats_by_key.items():
            row = f"{str(key):22s}" + "".join(f"{str(stats.get(c)):>16s}" for c in cols)
            lines.append(row)
            bw = f"    best={stats.get('best_signal')}  worst={stats.get('worst_signal')}"
            lines.append(bw)

    render_block("OVERALL", {"overall": summary["overall"]})
    render_block("BY PATTERN TYPE", summary.get("by_pattern_type", {}))
    render_block("BY PATTERN SUBTYPE", summary.get("by_pattern_subtype", {}))
    render_block("BY STRENGTH RATING", summary.get("by_strength_rating", {}))
    return "\n".join(lines)


if __name__ == "__main__":
    import sqlite3

    conn = sqlite3.connect(os.path.join(_BACKEND_DIR, "psx_v2.db"))
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
    result = engine.scan(df_long)
    print(f"Engine produced {len(result.signals)} signals.")

    bt = PatternBacktester(max_hold_sessions=60)
    signal_df, summary = bt.backtest_signals(df_long, result.signals)

    # Validation #3: no exit_date may precede its own signal_date.
    resolved = signal_df.dropna(subset=["exit_date"])
    bad = resolved[pd.to_datetime(resolved["exit_date"]) < pd.to_datetime(resolved["signal_date"])]
    assert bad.empty, f"LOOKAHEAD BUG: {len(bad)} signal(s) have exit_date before signal_date:\n{bad}"
    print("Lookahead assertion passed: no exit_date precedes its signal_date.")

    out_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results.csv")
    signal_df.to_csv(out_csv, index=False)
    print(f"Saved signal-level results to {out_csv}")

    print(_format_summary_table(summary))
