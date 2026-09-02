#!/usr/bin/env python3
"""
MACD+EMA200 trend-resumption backtest — walk-forward backtest of
backend/macd_ema_detector.py's signal against every symbol already
loaded in Turso's daily_ohlc table, using the notebook's own
MACDEMA_ATRTrail exit (pure ATR trailing stop, no fixed take-profit,
atr_mult=2.0 -- the strategy's stated default, unoptimized).

Entry: next bar's open, after a signal on the prior (signal) bar's close
(matches backtesting.py's default next-bar-open execution model, which
the notebook itself uses via trade_on_close=False).
Exit: the trailing stop, ratcheted only in the favorable direction each
day using that day's high (long) / low (short) since entry, is checked
against each subsequent day's low (long) / high (short) for a touch.
No fixed target — a trade that never gets stopped out by the end of
available history is marked "open" and excluded from win/loss stats
(consistent with run_mharris_backtest.py's convention).

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
import macd_ema_detector as det

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

MAX_HOLD_BARS = 250  # ~1 trading year cap so one runaway trend doesn't dominate runtime


def simulate_trades_for_symbol(feat: pd.DataFrame) -> list:
    """feat: build_features() output (ascending, with pre_signal/ATR/high/
    low/close/date columns). Returns a list of trade-result dicts for
    every pre_signal!=0 bar that had a following bar to enter on."""
    trades = []
    n = len(feat)
    sig = feat["pre_signal"].to_numpy()
    high = feat["high"].to_numpy()
    low = feat["low"].to_numpy()
    close = feat["close"].to_numpy()
    atr = feat["ATR"].to_numpy()
    dates = feat["date"].to_numpy()

    for i in range(n - 1):
        s = int(sig[i])
        if s == 0:
            continue
        a = atr[i]
        if not (a > 0):
            continue
        entry_i = i + 1
        entry_price = float(feat["open"].iloc[entry_i])
        trail_dist = det.ATR_MULT_DEFAULT * float(a)

        if s == 1:
            peak = high[entry_i]
            stop = peak - trail_dist
        else:
            trough = low[entry_i]
            stop = trough + trail_dist

        end = min(n, entry_i + 1 + MAX_HOLD_BARS)
        outcome, exit_price, exit_j = "open", None, end - 1
        for j in range(entry_i, end):
            if s == 1:
                peak = max(peak, high[j])
                stop = max(stop, peak - trail_dist)
                if low[j] <= stop:
                    outcome, exit_price, exit_j = "loss" if stop < entry_price else "win", stop, j
                    break
            else:
                trough = min(trough, low[j])
                stop = min(stop, trough + trail_dist)
                if high[j] >= stop:
                    outcome, exit_price, exit_j = "loss" if stop > entry_price else "win", stop, j
                    break

        if outcome == "open":
            pct = None
        else:
            pct = ((exit_price - entry_price) / entry_price * 100) if s == 1 \
                else ((entry_price - exit_price) / entry_price * 100)

        trades.append({
            "direction": "BULL" if s == 1 else "BEAR",
            "signal_date": str(dates[i])[:10],
            "entry_date": str(dates[entry_i])[:10],
            "outcome": outcome, "pct": pct, "bars_held": exit_j - entry_i,
        })
    return trades


def load_universe(min_bars=det.MIN_BARS_REQUIRED):
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
        universe[sym] = pd.DataFrame(rows_)
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

    logger.info(f"Loading universe (needs >= {det.MIN_BARS_REQUIRED} bars per symbol for EMA200)...")
    universe = load_universe()
    logger.info(f"Universe: {len(universe)} symbols qualify")

    if not universe:
        print("No symbols have enough history yet (EMA200 needs ~200+ daily bars). "
              "This will populate as the ongoing full-market backfill grows coverage.")
        return 0

    all_trades = []
    total_bars = 0
    for sym, df in universe.items():
        total_bars += len(df)
        try:
            df["date"] = pd.to_datetime(df["date"])
            feat = det.build_features(df)
            if feat.empty:
                continue
            trades = simulate_trades_for_symbol(feat)
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
    print("MACD+EMA200 TREND RESUMPTION — PSX BACKTEST (ATR trailing stop, atr_mult=2.0, default/unoptimized)")
    print("=" * 90)
    print(f"Universe: {len(universe)} symbols (>= {det.MIN_BARS_REQUIRED} bars), {total_bars:,} total daily bars")
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
        "params": {"atr_mult": det.ATR_MULT_DEFAULT, "atr_len": det.ATR_LEN, "max_hold_bars": MAX_HOLD_BARS},
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
        """, ("macdema_backtest", result["run_at"], time.time(), json.dumps(result)))
        conn.commit()
        logger.info("Saved to analysis_cache[macdema_backtest]")
    except Exception as e:
        logger.warning(f"Could not save to analysis_cache: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
