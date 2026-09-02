#!/usr/bin/env python3
"""
Regression-channel triangle squeeze backtest — walk-forward backtest of
backend/triangle_regression_detector.py's signal against every symbol
already loaded in Turso's daily_ohlc table, using the notebook's own
ShortSignalStrategy trade rule (SL = signal bar's high + 1% buffer,
TP = entry - rr*(stop-entry), rr=3.0, the class's stated default,
unoptimized).

Entry: the signal bar's own close (matches the notebook's
trade_on_close=True).
Exit: first-touch of SL or TP on subsequent days (SL checked first on a
day that could hit either -- the same conservative assumption used by
every other backtest script in this repo). No resolution by the end of
available history is marked "open" and excluded from win/loss stats.

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
import triangle_regression_detector as trd
from pivots import find_pivots

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

MAX_HOLD_BARS = 60  # notebook's own backtest showed a 6-day max trade duration on GC=F;
                     # 60 trading days is a generous cap for PSX daily bars


def simulate_trades_for_symbol(d: pd.DataFrame) -> list:
    """d: DataFrame with date/open/high/low/close/atr14 columns, ascending.
    Walks every bar, evaluates the squeeze condition (reusing
    triangle_regression_detector._evaluate_at so the backtest and the
    live scanner share the exact same signal logic), and simulates each
    short entry through to SL/TP/timeout."""
    pivots = find_pivots(d, k=trd.PIVOT_K)
    n = len(d)
    high = d["high"].to_numpy()
    low = d["low"].to_numpy()
    close = d["close"].to_numpy()
    dates = d["date"].to_numpy()

    trades = []
    for i in range(trd.MIN_BARS_REQUIRED, n):
        extra = trd._evaluate_at(d, pivots, i)
        if extra is None:
            continue

        entry_price = float(close[i])
        stop = float(high[i]) * (1 + trd.SL_BUFFER_PCT)
        risk = stop - entry_price
        if risk <= 0:
            continue
        target = entry_price - trd.RR_DEFAULT * risk

        end = min(n, i + 1 + MAX_HOLD_BARS)
        outcome, exit_price, exit_j = "open", None, end - 1
        for j in range(i + 1, end):
            hit_sl = high[j] >= stop
            hit_tp = low[j] <= target
            if hit_sl:
                outcome, exit_price, exit_j = "loss", stop, j
                break
            if hit_tp:
                outcome, exit_price, exit_j = "win", target, j
                break

        pct = ((entry_price - exit_price) / entry_price * 100) if outcome != "open" else None
        trades.append({
            "signal_date": str(dates[i])[:10], "outcome": outcome, "pct": pct,
            "bars_held": exit_j - i,
        })
    return trades


def load_universe(min_bars=trd.MIN_BARS_REQUIRED + 10):
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
        df["atr14"] = trd._atr14(df)
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

    logger.info(f"Loading universe (needs >= {trd.MIN_BARS_REQUIRED + 10} bars per symbol)...")
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

    print("\n" + "=" * 90)
    print("REGRESSION-CHANNEL TRIANGLE SQUEEZE — PSX BACKTEST (short-only, RR=3.0, SL buffer=1%, default/unoptimized)")
    print("=" * 90)
    print(f"Universe: {len(universe)} symbols, {total_bars:,} total daily bars")
    print(f"Total signals detected: {len(all_trades)}  "
          f"(resolved: {len(resolved)}, still open at end of data: {len(still_open)})")
    print()

    if overall:
        print("OVERALL:")
        print(f"  Trades:        {overall['n']}")
        print(f"  Win rate:      {overall['win_rate']}%")
        print(f"  Avg return:    {overall['avg_return_pct']:+.3f}% per trade")
        print(f"  Avg win:       {overall['avg_win_pct']:+.3f}%")
        print(f"  Avg loss:      {overall['avg_loss_pct']:+.3f}%")
        print(f"  Profit factor: {overall['profit_factor']}")
        print(f"  Avg hold:      {overall['avg_hold_bars']} trading days")
    else:
        print("No resolved trades — this pattern may be too rare on the current PSX coverage, "
              "or thresholds too strict for daily bars. Coverage/results will grow as the "
              "full-market backfill loads more history.")

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
        "overall": overall,
        "params": {"rr": trd.RR_DEFAULT, "sl_buffer_pct": trd.SL_BUFFER_PCT,
                   "max_hold_bars": MAX_HOLD_BARS, "lookback": trd.LOOKBACK, "min_r2": trd.MIN_R2},
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
        """, ("triangle_regression_backtest", result["run_at"], time.time(), json.dumps(result)))
        conn.commit()
        logger.info("Saved to analysis_cache[triangle_regression_backtest]")
    except Exception as e:
        logger.warning(f"Could not save to analysis_cache: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
