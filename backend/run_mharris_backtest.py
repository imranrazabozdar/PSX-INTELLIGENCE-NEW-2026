#!/usr/bin/env python3
"""
MHarris 5-bar reversal backtest — implements the exact candlestick signal
logic from the "01_MHarris_Systematic.ipynb" reference notebook and
backtests it against every symbol already loaded in Turso's daily_ohlc
table.

THE SIGNAL (translated 1:1 from the notebook's total_signal(), indices
-4..0 relative to the signal candle):

  BULLISH (2) — a contained downtrend snap-back:
    c1: low[-4]  > high[0]     signal candle's whole range still below
                                where price was 4 bars ago
    c2: high[0]  > low[-3]     ...but not below the -3 bar's low either
    c3: low[-3]  > low[-2]     lows declining for 3 straight bars
    c4: low[-2]  > low[-1]     (the downtrend leg the reversal interrupts)
    c5: close[0] > high[-1]    signal candle closes above the PRIOR
                                candle's high — the reversal thrust

  BEARISH (1) — the exact mirror (highs rising for 3 bars, then a
  reversal candle closing below the prior candle's low).

THE TRADE RULE (notebook's MyStrat defaults, NOT the grid-search-optimized
version — this backtest deliberately uses the strategy's stated defaults
so the result reflects the rule itself, not a fit tuned to 7 FX pairs):
  - Bullish: buy at the NEXT bar's open. SL = signal candle's close -4%,
    TP = signal candle's close +2%.
  - Bearish: sell at the NEXT bar's open. SL = signal candle's close +4%,
    TP = signal candle's close -2%.
  - Held until SL or TP is touched (first-touch, SL checked first on a
    day that could hit either — the conservative assumption backtesting.py
    itself uses) or the available price history runs out (marked "open",
    excluded from win/loss stats).

Runs in GitHub Actions (same Turso-secrets pattern as every other
run_*_backtest.py in this repo) since it needs the full daily_ohlc table.
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

import turso_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SL_PCT = 0.04
TP_PCT = 0.02
MAX_HOLD_BARS = 500  # notebook trades held up to 934 CALENDAR days on FX;
                      # cap TRADING-day holds so one stuck symbol doesn't
                      # dominate runtime on a 750-symbol universe


def detect_signal(bars, i):
    """bars: list of dicts with open/high/low/close, oldest-first.
    i: index of the candidate SIGNAL candle (needs i-4 >= 0)."""
    if i < 4:
        return 0
    b = bars
    lo = lambda k: b[i + k]["low"]
    hi = lambda k: b[i + k]["high"]

    c1 = lo(-4) > hi(0)
    c2 = hi(0) > lo(-3)
    c3 = lo(-3) > lo(-2)
    c4 = lo(-2) > lo(-1)
    c5 = b[i]["close"] > hi(-1)
    if c1 and c2 and c3 and c4 and c5:
        return 2

    c1 = hi(-4) < lo(0)
    c2 = lo(0) < hi(-3)
    c3 = hi(-3) < hi(-2)
    c4 = hi(-2) < hi(-1)
    c5 = b[i]["close"] < lo(-1)
    if c1 and c2 and c3 and c4 and c5:
        return 1

    return 0


def simulate_trade(bars, signal_i, direction):
    """direction: 2=long, 1=short. Entry at bars[signal_i+1]'s open (the
    next bar) — SL/TP are set off the SIGNAL candle's close, matching the
    notebook's MyStrat.next() exactly (current_close = signal bar's close,
    order fills at the following bar's open under backtesting.py's default
    execution model). Returns dict with outcome, or None if there's no next
    bar to enter on."""
    if signal_i + 1 >= len(bars):
        return None
    entry_bar = bars[signal_i + 1]
    entry_price = entry_bar["open"]
    signal_close = bars[signal_i]["close"]

    if direction == 2:
        sl = signal_close * (1 - SL_PCT)
        tp = signal_close * (1 + TP_PCT)
    else:
        sl = signal_close * (1 + SL_PCT)
        tp = signal_close * (1 - TP_PCT)

    end = min(len(bars), signal_i + 1 + MAX_HOLD_BARS)
    for j in range(signal_i + 1, end):
        day = bars[j]
        if direction == 2:
            hit_sl = day["low"] <= sl
            hit_tp = day["high"] >= tp
        else:
            hit_sl = day["high"] >= sl
            hit_tp = day["low"] <= tp
        if hit_sl and hit_tp:
            # Both touched same day -- conservative assumption: SL first.
            exit_price = sl
            outcome = "loss"
        elif hit_sl:
            exit_price = sl
            outcome = "loss"
        elif hit_tp:
            exit_price = tp
            outcome = "win"
        else:
            continue

        pct = ((exit_price - entry_price) / entry_price * 100) if direction == 2 \
            else ((entry_price - exit_price) / entry_price * 100)
        return {"outcome": outcome, "pct": pct, "bars_held": j - signal_i,
                "entry_date": entry_bar["trade_date"], "exit_date": day["trade_date"]}

    return {"outcome": "open", "pct": None, "bars_held": end - 1 - signal_i,
            "entry_date": entry_bar["trade_date"], "exit_date": None}


def load_universe(min_bars=60):
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
        bars = []
        for r in recs:
            if isinstance(r, dict):
                bars.append({"trade_date": r["trade_date"], "open": float(r["open"]),
                             "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])})
            else:
                bars.append({"trade_date": r[0], "open": float(r[1]), "high": float(r[2]),
                             "low": float(r[3]), "close": float(r[4])})
        universe[sym] = bars
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

    logger.info("Loading universe from daily_ohlc...")
    universe = load_universe(min_bars=60)
    logger.info(f"Universe: {len(universe)} symbols with >= 60 bars")

    if not universe:
        print("No symbols with enough OHLC data to backtest.")
        return 0

    all_trades = []  # each: {symbol, direction, outcome, pct, bars_held, entry_date}
    total_bars = 0
    for sym, bars in universe.items():
        total_bars += len(bars)
        # signal candle must have i-4 in range and a next bar to enter on
        for i in range(4, len(bars) - 1):
            sig = detect_signal(bars, i)
            if sig == 0:
                continue
            trade = simulate_trade(bars, i, sig)
            if trade is None:
                continue
            trade["symbol"] = sym
            trade["direction"] = "BULL" if sig == 2 else "BEAR"
            trade["signal_date"] = bars[i]["trade_date"]
            all_trades.append(trade)

    logger.info(f"Universe bars: {total_bars:,} · Total signals found: {len(all_trades)}")

    resolved = [t for t in all_trades if t["outcome"] in ("win", "loss")]
    still_open = [t for t in all_trades if t["outcome"] == "open"]
    wins = [t for t in resolved if t["outcome"] == "win"]
    losses = [t for t in resolved if t["outcome"] == "loss"]

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
    print("MHARRIS 5-BAR REVERSAL — PSX BACKTEST (notebook default params: SL 4% / TP 2%)")
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
    _print_block("BULLISH signals", bull)
    _print_block("BEARISH signals", bear)

    # Per-symbol breakdown for symbols with a meaningful sample
    by_symbol = {}
    for t in resolved:
        by_symbol.setdefault(t["symbol"], []).append(t)
    ranked = []
    for sym, trades in by_symbol.items():
        s = _stats(trades)
        if s and s["n"] >= 3:
            s["symbol"] = sym
            ranked.append(s)
    ranked.sort(key=lambda x: x["avg_return_pct"], reverse=True)

    if ranked:
        print("-" * 90)
        print(f"Top 10 symbols by avg return (n >= 3 resolved trades, {len(ranked)} symbols qualify):")
        for s in ranked[:10]:
            print(f"  {s['symbol']:<10} n={s['n']:<4} win_rate={s['win_rate']:>5.1f}%  "
                  f"avg_ret={s['avg_return_pct']:+.3f}%  pf={s['profit_factor']}")
        print("\nBottom 10 symbols by avg return:")
        for s in ranked[-10:]:
            print(f"  {s['symbol']:<10} n={s['n']:<4} win_rate={s['win_rate']:>5.1f}%  "
                  f"avg_ret={s['avg_return_pct']:+.3f}%  pf={s['profit_factor']}")

    # Save to analysis_cache
    result = {
        "status": "ok",
        "universe_symbols": len(universe),
        "universe_bars": total_bars,
        "total_signals": len(all_trades),
        "resolved": len(resolved),
        "still_open": len(still_open),
        "overall": overall,
        "bull": bull,
        "bear": bear,
        "params": {"sl_pct": SL_PCT, "tp_pct": TP_PCT, "max_hold_bars": MAX_HOLD_BARS},
        "top_symbols": ranked[:10],
        "bottom_symbols": ranked[-10:] if len(ranked) > 10 else [],
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
        """, ("mharris_backtest", result["run_at"], time.time(), json.dumps(result)))
        conn.commit()
        logger.info("Saved to analysis_cache[mharris_backtest]")
    except Exception as e:
        logger.warning(f"Could not save to analysis_cache: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
