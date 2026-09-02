#!/usr/bin/env python3
"""
Level Break Out backtest — walk-forward backtest of
backend/level_breakout_detector.py's signal against every symbol already
loaded in Turso's daily_ohlc table, using the notebook's own trade rule
(SL = 3% fixed, TP = 2x that risk, both at the class's stated defaults,
unoptimized) PLUS its RSI(14) 80/20 early-exit for open positions.

Entry: the NEXT bar's open (the notebook's Backtest() call has no
trade_on_close=True, so backtesting.py's default next-bar-open execution
applies). SL/TP are anchored to the signal bar's own close.
Exit: first-touch of SL or TP on subsequent days (SL checked first on a
day that could hit either), OR an RSI-based early exit at that day's
close (RSI>80 closes a long, RSI<20 closes a short) -- whichever comes
first. A trade unresolved by the end of available history is marked
"open" and excluded from win/loss stats.

Runs in GitHub Actions (same Turso-secrets pattern as the other
run_*_backtest.py scripts in this repo).
"""

import json
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pandas as pd
import turso_db
import level_breakout_detector as lbd
from pivots import find_pivots

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

MAX_HOLD_BARS = 120  # the notebook's own base-version backtest showed a 76-day max trade
                      # duration on EURUSD; generous cap for PSX daily bars


def simulate_trades_for_symbol(d: pd.DataFrame) -> list:
    """d: DataFrame with date/open/high/low/close/atr14 columns, ascending.
    Walks every bar, evaluates the level-break condition (reusing
    level_breakout_detector._evaluate_at so the backtest and the live
    scanner share the exact same signal logic), and simulates each trade
    through to SL/TP/RSI-exit/timeout."""
    pivots = find_pivots(d, k=lbd.PIVOT_K)
    rsi = lbd._rsi14(d["close"])
    n = len(d)
    high = d["high"].to_numpy()
    low = d["low"].to_numpy()
    close = d["close"].to_numpy()
    open_ = d["open"].to_numpy()
    rsi_arr = rsi.to_numpy()
    dates = d["date"].to_numpy()

    trades = []
    for i in range(lbd.MIN_BARS_REQUIRED, n - 1):
        extra = lbd._evaluate_at(d, pivots, i)
        if extra is None:
            continue

        entry_i = i + 1
        entry_price = float(open_[entry_i])
        signal_close = float(close[i])
        levelbreak = extra["levelbreak"]

        if levelbreak == 2:  # LONG
            sl = signal_close * (1 - lbd.SL_PCT)
            risk = signal_close - sl
            tp = signal_close + risk * lbd.TP_RR
        else:  # SHORT
            sl = signal_close * (1 + lbd.SL_PCT)
            risk = sl - signal_close
            tp = signal_close - risk * lbd.TP_RR
        if risk <= 0:
            continue

        end = min(n, entry_i + MAX_HOLD_BARS)
        outcome, exit_price, exit_j = "open", None, end - 1
        for j in range(entry_i, end):
            if levelbreak == 2:
                hit_sl = low[j] <= sl
                hit_tp = high[j] >= tp
                rsi_exit = rsi_arr[j] > lbd.RSI_EXIT_LONG
            else:
                hit_sl = high[j] >= sl
                hit_tp = low[j] <= tp
                rsi_exit = rsi_arr[j] < lbd.RSI_EXIT_SHORT

            if hit_sl:
                outcome, exit_price, exit_j = "resolved", sl, j
                break
            if hit_tp:
                outcome, exit_price, exit_j = "resolved", tp, j
                break
            if rsi_exit:
                outcome, exit_price, exit_j = "resolved", float(close[j]), j
                break

        if outcome == "open":
            pct = None
        else:
            pct = ((exit_price - entry_price) / entry_price * 100) if levelbreak == 2 \
                else ((entry_price - exit_price) / entry_price * 100)

        trades.append({
            "direction": "BULL" if levelbreak == 2 else "BEAR",
            "signal_date": str(dates[i])[:10],
            "outcome": ("win" if (pct is not None and pct > 0) else ("loss" if pct is not None else "open")),
            "pct": pct, "bars_held": exit_j - entry_i,
        })
    return trades


def load_universe(min_bars=lbd.MIN_BARS_REQUIRED + 10):
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
        rows_ = []
        for r in recs:
            if isinstance(r, dict):
                rows_.append({"date": r["trade_date"], "open": float(r["open"]), "high": float(r["high"]),
                              "low": float(r["low"]), "close": float(r["close"])})
            else:
                rows_.append({"date": r[0], "open": float(r[1]), "high": float(r[2]),
                              "low": float(r[3]), "close": float(r[4])})
        df = pd.DataFrame(rows_)
        df["date"] = pd.to_datetime(df["date"])
        df["atr14"] = lbd._atr14(df)
        universe[sym] = df
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

    logger.info(f"Loading universe (needs >= {lbd.MIN_BARS_REQUIRED + 10} bars per symbol)...")
    universe = load_universe()
    logger.info(f"Universe: {len(universe)} symbols qualify")

    if not universe:
        print("No symbols have enough history yet.")
        return 0

    all_trades = []
    total_bars = 0
    for sym, df in universe.items():
        total_bars += len(df)
        try:
            trades = simulate_trades_for_symbol(df)
            for t in trades:
                t["symbol"] = sym
            all_trades.extend(trades)
        except Exception as e:
            logger.warning(f"  {sym}: failed — {type(e).__name__}: {e}")
            continue

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
        avg_hold = sum(t["bars_held"] for t in trades) / n
        return {"n": n, "win_rate": round(win_rate, 2), "avg_return_pct": round(avg_ret, 3),
                "profit_factor": round(profit_factor, 2) if profit_factor else None,
                "avg_win_pct": round(avg_win, 3), "avg_loss_pct": round(avg_loss, 3),
                "avg_hold_bars": round(avg_hold, 1)}

    overall = _stats(resolved)
    bull = _stats([t for t in resolved if t["direction"] == "BULL"])
    bear = _stats([t for t in resolved if t["direction"] == "BEAR"])

    print("\n" + "=" * 90)
    print("LEVEL BREAK OUT — PSX BACKTEST (SL 3% / TP 2:1 + RSI(14) 80/20 early exit, default/unoptimized)")
    print("=" * 90)
    print(f"Universe: {len(universe)} symbols, {total_bars:,} total daily bars")
    print(f"Total signals detected: {len(all_trades)}  "
          f"(resolved: {len(resolved)}, still open at end of data: {len(still_open)})")
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
    _print_block("BULLISH (resistance breakout)", bull)
    _print_block("BEARISH (support breakdown)", bear)

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
        "params": {"sl_pct": lbd.SL_PCT, "tp_rr": lbd.TP_RR, "rsi_exit_long": lbd.RSI_EXIT_LONG,
                   "rsi_exit_short": lbd.RSI_EXIT_SHORT, "max_hold_bars": MAX_HOLD_BARS},
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
        """, ("level_breakout_backtest", result["run_at"], time.time(), json.dumps(result)))
        conn.commit()
        logger.info("Saved to analysis_cache[level_breakout_backtest]")
    except Exception as e:
        logger.warning(f"Could not save to analysis_cache: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
