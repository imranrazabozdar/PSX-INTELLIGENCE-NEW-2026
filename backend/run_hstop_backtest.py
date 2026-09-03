#!/usr/bin/env python3
"""run_hstop_backtest.py — walk-forward backtest of the Head & Shoulders
Top detector (advanced_pattern_engine.py's detect_head_shoulders_top(),
already a full-history vectorized scanner, exact bearish mirror of the
IHS scan -- see that method's own docstring: "kept separate ... because
Head & Shoulders Top has not been backtested yet and must not be wired
into any live caller of scan() by accident"). This script is that missing
backtest, against the real Turso-stored PSX universe.

PRIOR VERSION of this file connected to a local psx_v2.db file directly
and never saved its results anywhere -- workable for local dev, but never
actually run against real production data and invisible to the rest of
the app either way. Rewritten to the same turso_db.py + analysis_cache
convention every other run_*_backtest.py script in this project uses.

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

import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pandas as pd
import turso_db
from advanced_pattern_engine import AdvancedPatternEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

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


def load_universe():
    conn = turso_db.get_connection()
    rows = conn.execute("SELECT DISTINCT symbol FROM daily_ohlc").fetchall()
    symbols = [r["symbol"] if isinstance(r, dict) else r[0] for r in rows]
    frames = []
    for sym in symbols:
        recs = conn.execute(
            "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
            "WHERE symbol = ? ORDER BY trade_date ASC", (sym,)
        ).fetchall()
        if not recs:
            continue
        rows_ = []
        for r in recs:
            if isinstance(r, dict):
                rows_.append({"symbol": sym, "date": r["trade_date"], "open": float(r["open"]),
                              "high": float(r["high"]), "low": float(r["low"]),
                              "close": float(r["close"]), "volume": float(r["volume"] or 0)})
            else:
                rows_.append({"symbol": sym, "date": r[0], "open": float(r[1]), "high": float(r[2]),
                              "low": float(r[3]), "close": float(r[4]), "volume": float(r[5] or 0)})
        frames.append(pd.DataFrame(rows_))
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    df_long = pd.concat(frames, ignore_index=True)
    df_long["date"] = pd.to_datetime(df_long["date"])
    return df_long


def main():
    try:
        db_status = turso_db.status()
        logger.info(f"Database: {db_status['backend']}")
        if db_status.get("on_local_fallback"):
            logger.error("On local Turso fallback — daily_ohlc would be empty. Aborting.")
            return 1
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return 1

    logger.info("Loading full PSX universe from Turso...")
    df_long = load_universe()
    n_symbols = df_long["symbol"].nunique() if len(df_long) else 0
    logger.info(f"Loaded {len(df_long):,} rows across {n_symbols} symbols.")
    if df_long.empty:
        print("No data available.")
        return 0

    engine = AdvancedPatternEngine()
    result = engine.detect_head_shoulders_top(df_long)
    logger.info(f"Engine produced {len(result.signals)} signals.")

    by_symbol = {s: g.sort_values("date").reset_index(drop=True) for s, g in df_long.groupby("symbol", sort=False)}

    rows_out = []
    for sig in result.signals:
        sub = by_symbol.get(sig["symbol"])
        if sub is None:
            continue
        match = sub.index[sub["date"] == sig["signal_date"]]
        if len(match) == 0:
            continue
        signal_idx = match[0]
        outcome, hold = _simulate_short(sub, signal_idx, sig["entry_price"], sig["stop_loss"],
                                         sig["target_partial"], sig["target_measured"])
        rows_out.append({"symbol": sig["symbol"], "date": str(sig["signal_date"])[:10], "outcome": outcome,
                          "hold_sessions": hold, "confidence_score": sig["confidence_score"],
                          "risk_reward_measured": sig["risk_reward_measured"]})

    df_out = pd.DataFrame(rows_out)
    print("\n" + "=" * 80)
    print("HEAD & SHOULDERS TOP — full PSX universe backtest")
    print("=" * 80)
    print(f"Universe: {n_symbols} symbols, {len(df_long):,} total daily bars")
    print(f"Total signals generated: {len(df_out)}")

    result_payload = {
        "status": "ok", "universe_symbols": n_symbols, "universe_bars": int(len(df_long)),
        "total_signals": len(df_out), "run_at": datetime.now(timezone.utc).isoformat(),
    }

    if df_out.empty:
        print("No signals — nothing further to report.")
        result_payload["overall"] = None
    else:
        known = df_out[df_out["outcome"] != OUTCOME_INSUFFICIENT_DATA]
        n_known = len(known)
        print(f"Signals with a resolvable outcome (>= {MIN_FORWARD_BARS} forward bars): {n_known} "
              f"({len(df_out) - n_known} excluded as insufficient forward data)")

        if n_known == 0:
            result_payload["overall"] = None
        else:
            win_t1 = int(known["outcome"].isin([OUTCOME_TARGET_1_HIT, OUTCOME_TARGET_2_HIT]).sum())
            win_t2 = int((known["outcome"] == OUTCOME_TARGET_2_HIT).sum())
            n_stopped = int((known["outcome"] == OUTCOME_STOPPED_OUT).sum())
            n_timeout = int((known["outcome"] == OUTCOME_TIMEOUT).sum())

            # Realised P&L per trade (short): win at target_1 assumed closed at target_1,
            # stopped assumed closed at stop -- reported as % move from entry, matching
            # this project's other backtests' avg-return convention.
            rets = []
            for _, r in known.iterrows():
                sig_match = next((s for s in result.signals
                                   if s["symbol"] == r["symbol"] and str(s["signal_date"])[:10] == r["date"]), None)
                if sig_match is None:
                    continue
                entry = sig_match["entry_price"]
                if r["outcome"] == OUTCOME_TARGET_2_HIT:
                    exit_p = sig_match["target_measured"]
                elif r["outcome"] == OUTCOME_TARGET_1_HIT:
                    exit_p = sig_match["target_partial"]
                elif r["outcome"] == OUTCOME_STOPPED_OUT:
                    exit_p = sig_match["stop_loss"]
                else:
                    continue  # TIMEOUT: no clean exit price to score
                pct = (entry - exit_p) / entry * 100.0  # short: profit when exit < entry
                rets.append(pct)

            avg_ret = sum(rets) / len(rets) if rets else None
            gross_win = sum(r for r in rets if r > 0)
            gross_loss = abs(sum(r for r in rets if r < 0))
            profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
            win_rate_t1 = win_t1 / n_known
            win_rate_t2 = win_t2 / n_known
            stop_rate = n_stopped / n_known
            timeout_rate = n_timeout / n_known

            winners = known[known["outcome"].isin([OUTCOME_TARGET_1_HIT, OUTCOME_TARGET_2_HIT])]
            losers = known[known["outcome"] == OUTCOME_STOPPED_OUT]
            med_hold_win = float(winners["hold_sessions"].median()) if len(winners) else None
            med_hold_loss = float(losers["hold_sessions"].median()) if len(losers) else None

            print(f"Win rate, Target 1 (reached Target 1 or better before Stop): {win_rate_t1:.4f} ({win_t1}/{n_known})")
            print(f"Win rate, Target 2 (reached Target 2 before Stop):           {win_rate_t2:.4f} ({win_t2}/{n_known})")
            print(f"Stop-loss hit rate:                                          {stop_rate:.4f} ({n_stopped}/{n_known})")
            print(f"Timeout rate (held full {MAX_HOLD_SESSIONS} sessions, no decisive exit): {timeout_rate:.4f} ({n_timeout}/{n_known})")
            print(f"Avg return per resolved trade (short, target/stop exit only): "
                  f"{avg_ret:+.3f}%" if avg_ret is not None else "Avg return: n/a")
            print(f"Profit factor: {profit_factor}" if profit_factor is not None else "Profit factor: n/a (no losers)")
            print(f"Median hold time, WINNING trades (sessions): {med_hold_win}")
            print(f"Median hold time, LOSING (stopped-out) trades (sessions): {med_hold_loss}")
            print(f"\nFull outcome distribution: {dict(Counter(known['outcome']))}")
            print(f"\nMedian confidence_score of all signals: {df_out['confidence_score'].median():.4f}")

            result_payload["overall"] = {
                "n": n_known, "win_rate_t1_pct": round(win_rate_t1 * 100, 2),
                "win_rate_t2_pct": round(win_rate_t2 * 100, 2),
                "stop_rate_pct": round(stop_rate * 100, 2), "timeout_rate_pct": round(timeout_rate * 100, 2),
                "avg_return_pct": round(avg_ret, 3) if avg_ret is not None else None,
                "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
                "median_hold_win_sessions": med_hold_win, "median_hold_loss_sessions": med_hold_loss,
                "outcome_distribution": dict(Counter(known["outcome"])),
                "median_confidence_score": round(float(df_out["confidence_score"].median()), 3),
            }

    try:
        conn = turso_db.get_connection()
        conn.execute("""CREATE TABLE IF NOT EXISTS analysis_cache(
            cache_key TEXT PRIMARY KEY, run_at TEXT, run_at_epoch REAL, result_json TEXT)""")
        conn.execute("""
            INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
            VALUES(?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
              run_at=excluded.run_at, run_at_epoch=excluded.run_at_epoch, result_json=excluded.result_json
        """, ("hstop_backtest", result_payload["run_at"], time.time(), json.dumps(result_payload)))
        conn.commit()
        logger.info("Saved to analysis_cache[hstop_backtest]")
    except Exception as e:
        logger.warning(f"Could not save to analysis_cache: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
