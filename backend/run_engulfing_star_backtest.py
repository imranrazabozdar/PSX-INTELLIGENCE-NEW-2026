#!/usr/bin/env python3
"""run_engulfing_star_backtest.py — walk-forward backtest of
engulfing_star_detector.py's Engulfing+Star combined reversal against
every symbol already loaded in Turso's daily_ohlc table.

Outcome simulation (both directions, no lookahead: only bars strictly
after the signal's own close are ever used to decide the outcome) --
same CLOSE-based touch convention as run_bullish_engulfing_backtest.py/
run_hstop_backtest.py (this project's other "trade rule built from the
pattern's own geometry, not the source notebook" backtests):
  BULL: close >= target_2 -> TARGET_2_HIT; elif close >= target_1 -> TARGET_1_HIT;
        elif close <= stop_loss -> STOPPED_OUT
  BEAR: mirror (close <=/<=/>=)
Fewer than MIN_FORWARD_BARS with no decisive exit -> INSUFFICIENT_DATA.
No decisive exit within MAX_HOLD_SESSIONS -> TIMEOUT.
"""

import json
import sys
import time
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pandas as pd
import turso_db
import engulfing_star_detector as esd

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

MAX_HOLD_SESSIONS = 60
MIN_FORWARD_BARS = 5

OUTCOME_STOPPED_OUT = "STOPPED_OUT"
OUTCOME_TARGET_1_HIT = "TARGET_1_HIT"
OUTCOME_TARGET_2_HIT = "TARGET_2_HIT"
OUTCOME_TIMEOUT = "TIMEOUT"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_FORWARD_DATA"


def _simulate(candles, signal_i, direction, entry_price, stop_loss, target_1, target_2):
    if stop_loss is None:
        return OUTCOME_INSUFFICIENT_DATA, None, None

    forward = candles[signal_i + 1: signal_i + 1 + MAX_HOLD_SESSIONS]
    if len(forward) < MIN_FORWARD_BARS:
        return OUTCOME_INSUFFICIENT_DATA, None, None

    for j, bar in enumerate(forward, start=1):
        close = bar["close"]
        if direction == "BULL":
            if close >= target_2:
                return OUTCOME_TARGET_2_HIT, j, (target_2 - entry_price) / entry_price * 100
            if close >= target_1:
                return OUTCOME_TARGET_1_HIT, j, (target_1 - entry_price) / entry_price * 100
            if close <= stop_loss:
                return OUTCOME_STOPPED_OUT, j, (stop_loss - entry_price) / entry_price * 100
        else:
            if close <= target_2:
                return OUTCOME_TARGET_2_HIT, j, (entry_price - target_2) / entry_price * 100
            if close <= target_1:
                return OUTCOME_TARGET_1_HIT, j, (entry_price - target_1) / entry_price * 100
            if close >= stop_loss:
                return OUTCOME_STOPPED_OUT, j, (entry_price - stop_loss) / entry_price * 100

    if len(forward) < MAX_HOLD_SESSIONS:
        return OUTCOME_INSUFFICIENT_DATA, None, None
    return OUTCOME_TIMEOUT, len(forward), None


def load_universe(min_bars=40):
    conn = turso_db.get_connection()
    rows = conn.execute("SELECT DISTINCT symbol FROM daily_ohlc").fetchall()
    symbols = [r["symbol"] if isinstance(r, dict) else r[0] for r in rows]
    universe = {}
    for sym in symbols:
        recs = conn.execute(
            "SELECT trade_date, open, high, low, close FROM daily_ohlc "
            "WHERE symbol = ? ORDER BY trade_date ASC", (sym,)
        ).fetchall()
        if len(recs) < min_bars:
            continue
        candles = []
        for r in recs:
            if isinstance(r, dict):
                candles.append({"date": pd.Timestamp(r["trade_date"]), "open": float(r["open"]),
                                 "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])})
            else:
                candles.append({"date": pd.Timestamp(r[0]), "open": float(r[1]), "high": float(r[2]),
                                 "low": float(r[3]), "close": float(r[4])})
        universe[sym] = candles
    return universe


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

    logger.info(f"Loading universe (needs >= 40 bars per symbol)...")
    universe = load_universe()
    logger.info(f"Universe: {len(universe)} symbols qualify")

    if not universe:
        print("No symbols have enough history yet.")
        return 0

    all_trades = []
    total_bars = 0
    for sym, candles in universe.items():
        total_bars += len(candles)
        for i in range(esd.MIN_BARS_REQUIRED - 1, len(candles) - 1):
            direction = esd._evaluate_at(candles, i)
            if direction is None:
                continue
            entry_price, stop_loss, target_1, target_2 = esd.compute_trade_levels(candles, i, direction)
            outcome, bars_held, pct = _simulate(candles, i, direction, entry_price, stop_loss, target_1, target_2)
            all_trades.append({
                "symbol": sym, "direction": direction,
                "signal_date": candles[i]["date"].strftime("%Y-%m-%d"),
                "outcome": ("win" if outcome in (OUTCOME_TARGET_1_HIT, OUTCOME_TARGET_2_HIT)
                            else "loss" if outcome == OUTCOME_STOPPED_OUT
                            else "open"),
                "pct": pct, "bars_held": bars_held,
            })

    logger.info(f"Universe bars: {total_bars:,} · Total signals found: {len(all_trades)}")

    resolved = [t for t in all_trades if t["outcome"] in ("win", "loss")]
    still_open = [t for t in all_trades if t["outcome"] == "open"]

    def _stats(trades):
        n = len(trades)
        if n == 0:
            return None
        w = [t for t in trades if t["outcome"] == "win"]
        l = [t for t in trades if t["outcome"] == "loss"]
        win_rate = len(w) / n * 100
        avg_ret = sum(t["pct"] for t in trades) / n
        gross_win = sum(t["pct"] for t in w) if w else 0
        gross_loss = abs(sum(t["pct"] for t in l)) if l else 0
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
        avg_win = (gross_win / len(w)) if w else 0
        avg_loss = (-gross_loss / len(l)) if l else 0
        avg_hold = sum(t["bars_held"] for t in trades if t["bars_held"] is not None) / n
        return {"n": n, "win_rate": round(win_rate, 2), "avg_return_pct": round(avg_ret, 3),
                "profit_factor": round(profit_factor, 2) if profit_factor else None,
                "avg_win_pct": round(avg_win, 3), "avg_loss_pct": round(avg_loss, 3),
                "avg_hold_bars": round(avg_hold, 1)}

    overall = _stats(resolved)
    bull = _stats([t for t in resolved if t["direction"] == "BULL"])
    bear = _stats([t for t in resolved if t["direction"] == "BEAR"])

    print("\n" + "=" * 90)
    print("ENGULFING + STAR COMBINED REVERSAL — PSX BACKTEST (geometry-based stop/target, unoptimized)")
    print("=" * 90)
    print(f"Universe: {len(universe)} symbols, {total_bars:,} total daily bars")
    print(f"Total signals detected: {len(all_trades)}  "
          f"(resolved: {len(resolved)}, still open/insufficient data: {len(still_open)})")
    print()

    def _print_block(name, s):
        if not s:
            print(f"{name}: no resolved trades")
            return
        print(f"{name}:")
        print(f"  Trades:        {s['n']}")
        print(f"  Win rate:      {s['win_rate']}%")
        print(f"  Avg return:    {s['avg_return_pct']:+.3f}% per trade")
        print(f"  Avg win:       {s['avg_win_pct']:+.3f}%")
        print(f"  Avg loss:      {s['avg_loss_pct']:+.3f}%")
        print(f"  Profit factor: {s['profit_factor']}")
        print(f"  Avg hold:      {s['avg_hold_bars']} trading days")
        print()

    _print_block("OVERALL", overall)
    _print_block("BULLISH signals", bull)
    _print_block("BEARISH signals", bear)

    by_symbol = {}
    for t in resolved:
        by_symbol.setdefault(t["symbol"], []).append(t)
    ranked = []
    for sym, trades in by_symbol.items():
        s = _stats(trades)
        if s and s["n"] >= 2:
            s["symbol"] = sym
            ranked.append(s)
    ranked.sort(key=lambda x: x["avg_return_pct"], reverse=True)

    if ranked:
        print("-" * 90)
        print(f"Top 10 symbols by avg return (n >= 2 resolved trades, {len(ranked)} symbols qualify):")
        for s in ranked[:10]:
            print(f"  {s['symbol']:<10} n={s['n']:<4} win_rate={s['win_rate']:>5.1f}%  "
                  f"avg_ret={s['avg_return_pct']:+.3f}%  pf={s['profit_factor']}")
        print("\nBottom 10 symbols by avg return:")
        for s in ranked[-10:]:
            print(f"  {s['symbol']:<10} n={s['n']:<4} win_rate={s['win_rate']:>5.1f}%  "
                  f"avg_ret={s['avg_return_pct']:+.3f}%  pf={s['profit_factor']}")

    result = {
        "status": "ok", "universe_symbols": len(universe), "universe_bars": total_bars,
        "total_signals": len(all_trades), "resolved": len(resolved), "still_open": len(still_open),
        "overall": overall, "bull": bull, "bear": bear,
        "top_symbols": ranked[:10], "bottom_symbols": ranked[-10:] if len(ranked) > 10 else [],
        "run_at": datetime.now(timezone.utc).isoformat(),
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
        """, ("engulfing_star_backtest", result["run_at"], time.time(), json.dumps(result)))
        conn.commit()
        logger.info("Saved to analysis_cache[engulfing_star_backtest]")
    except Exception as e:
        logger.warning(f"Could not save to analysis_cache: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
