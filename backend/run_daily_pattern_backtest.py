#!/usr/bin/env python3
"""
Daily pattern backtest — runs the full walk-forward backtest over all
OHLC data in Turso and produces a success-rate summary for every
detected pattern type.

Uses backtest_engine.py which detects candlestick patterns (Bullish
Engulfing, Hammer, Morning Star, etc.), structural patterns (Spring,
Upthrust, Breakout), and combo patterns walk-forward (no look-ahead
bias), then measures forward returns at 1, 3, 5, 10, 20, 40, 60-day
horizons.

Compares pattern signals against naive baselines (random entry,
trend-following, RSI oversold, MA crossover) to show whether each
pattern adds value beyond what a simple rule would achieve.

Saves results to analysis_cache for the Streamlit frontend.
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
import backtest_engine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def load_universe(min_bars: int = 60) -> dict:
    """Load all symbols' OHLC data as the backtest universe.
    Returns {symbol: [list of {trade_date, open, high, low, close, volume} dicts]}"""
    conn = turso_db.get_connection()

    symbols_row = conn.execute("SELECT DISTINCT symbol FROM daily_ohlc").fetchall()
    symbols = [r["symbol"] if isinstance(r, dict) else r[0] for r in symbols_row]
    logger.info(f"Found {len(symbols)} symbols in daily_ohlc")

    universe = {}
    for sym in symbols:
        rows = conn.execute(
            "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
            "WHERE symbol = ? ORDER BY trade_date ASC",
            (sym,)
        ).fetchall()
        if len(rows) < min_bars:
            continue
        parsed = []
        for r in rows:
            if isinstance(r, dict):
                parsed.append({
                    "trade_date": r["trade_date"],
                    "open": float(r["open"]), "high": float(r["high"]),
                    "low": float(r["low"]), "close": float(r["close"]),
                    "volume": float(r["volume"]),
                })
            else:
                parsed.append({
                    "trade_date": r[0],
                    "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]),
                    "volume": float(r[5]),
                })
        universe[sym] = parsed

    logger.info(f"Universe: {len(universe)} symbols with >= {min_bars} bars")
    return universe


def main():
    try:
        db_status = turso_db.status()
        logger.info(f"Database: {db_status['backend']}")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return 1

    logger.info("Loading universe from daily_ohlc...")
    universe = load_universe(min_bars=60)

    if not universe:
        logger.warning("No symbols with enough OHLC data for backtesting")
        return 0

    logger.info(f"Running walk-forward backtest on {len(universe)} symbols...")
    result = backtest_engine.run_backtest(universe)
    run_id = result["run_id"]
    logger.info(f"Backtest complete! Run ID: {run_id}")
    logger.info(f"  Universe: {result['universe_symbols']} symbols, {result['universe_bars']} bars")
    logger.info(f"  Patterns found: {len(result['patterns_found'])}")

    # Print detailed results
    print("\n" + "=" * 90)
    print("DAILY PATTERN BACKTEST — SUCCESS RATE SUMMARY")
    print("=" * 90)
    print(f"Run ID: {run_id}")
    print(f"Universe: {result['universe_symbols']} symbols, {result['universe_bars']:,} total bars")
    print(f"Patterns detected: {', '.join(result['patterns_found'])}")

    # Classify patterns as bullish or bearish
    BULLISH_PATTERNS = {
        "Bullish Engulfing", "Hammer", "Morning Star", "Piercing Line",
        "Three White Soldiers", "Spring", "Resistance Breakout",
    }
    BEARISH_PATTERNS = {
        "Bearish Engulfing", "Shooting Star", "Evening Star", "Dark Cloud Cover",
        "Three Black Crows", "Upthrust", "Support Breakdown",
    }

    key_horizons = [1, 3, 5, 10, 20]
    summary_data = {}

    for h in key_horizons:
        pat_stats = backtest_engine.all_pattern_stats(horizon=h, run_id=run_id)
        base_stats = backtest_engine.all_baseline_stats(horizon=h, run_id=run_id)

        print(f"\n{'─' * 90}")
        print(f"📊 {h}-DAY FORWARD RETURNS")
        print(f"{'─' * 90}")
        print(f"{'Pattern':<30} {'Side':<6} {'N':<8} {'Win%':<8} {'AvgRet':<10} "
              f"{'AvgWin':<10} {'AvgLoss':<10} {'Expect':<10} {'Verdict'}")
        print(f"{'─' * 30} {'─' * 6} {'─' * 8} {'─' * 8} {'─' * 10} {'─' * 10} {'─' * 10} {'─' * 10} {'─' * 10}")

        for ps in pat_stats:
            pat = ps["pattern"]
            if pat in BULLISH_PATTERNS or any(bp in pat for bp in ["Spring +", "Bullish", "Hammer", "Morning"]):
                side = "BULL"
            elif pat in BEARISH_PATTERNS or any(bp in pat for bp in ["Bearish", "Shooting", "Evening", "Dark"]):
                side = "BEAR"
            else:
                side = "—"

            n = ps["n"]
            wr = ps.get("win_rate") or 0
            avg_ret = ps.get("avg_return") or 0
            avg_win = ps.get("avg_win") or 0
            avg_loss = ps.get("avg_loss") or 0
            expect = ps.get("expectancy") or 0

            if n < 20:
                verdict = "⚠ Low N"
            elif wr >= 60:
                verdict = "✅ GOOD"
            elif wr >= 52:
                verdict = "➡ FAIR"
            else:
                verdict = "❌ POOR"

            print(f"{pat:<30} {side:<6} {n:<8} {wr:>5.1f}%  {avg_ret:>+7.2f}%  "
                  f"{avg_win:>+7.2f}%  {avg_loss:>+7.2f}%  {expect:>+7.2f}%  {verdict}")

            summary_data.setdefault(pat, {})[h] = {
                "n": n, "win_rate": wr, "avg_return": avg_ret,
                "expectancy": expect, "side": side,
            }

        # Baselines
        print(f"\n  {'Baselines:'}")
        for bs in base_stats:
            bl = bs["baseline"]
            n = bs["n"]
            wr = bs.get("win_rate") or 0
            avg_ret = bs.get("avg_return") or 0
            expect = bs.get("expectancy") or 0
            print(f"  {bl:<28} {'BASE':<6} {n:<8} {wr:>5.1f}%  {avg_ret:>+7.2f}%  "
                  f"{'':>10} {'':>10} {expect:>+7.2f}%")

    # Overall summary
    print(f"\n{'=' * 90}")
    print("OVERALL PATTERN SUCCESS RATES (5-day horizon)")
    print(f"{'=' * 90}")

    pat_stats_5d = backtest_engine.all_pattern_stats(horizon=5, run_id=run_id)
    if pat_stats_5d:
        total_signals = sum(ps["n"] for ps in pat_stats_5d)
        total_wins = sum(int(ps["n"] * (ps.get("win_rate") or 0) / 100) for ps in pat_stats_5d)
        overall_wr = total_wins / total_signals * 100 if total_signals > 0 else 0

        bull_stats = [ps for ps in pat_stats_5d
                      if ps["pattern"] in BULLISH_PATTERNS or
                      any(bp in ps["pattern"] for bp in ["Spring +", "Bullish", "Hammer", "Morning"])]
        bear_stats = [ps for ps in pat_stats_5d
                      if ps["pattern"] in BEARISH_PATTERNS or
                      any(bp in ps["pattern"] for bp in ["Bearish", "Shooting", "Evening", "Dark"])]

        if bull_stats:
            bull_n = sum(ps["n"] for ps in bull_stats)
            bull_wins = sum(int(ps["n"] * (ps.get("win_rate") or 0) / 100) for ps in bull_stats)
            bull_wr = bull_wins / bull_n * 100 if bull_n > 0 else 0
            bull_avg_ret = sum(ps["n"] * (ps.get("avg_return") or 0) for ps in bull_stats) / bull_n if bull_n > 0 else 0
            print(f"  📈 Bullish patterns: {bull_wins}/{bull_n} = {bull_wr:.1f}% win rate, avg return {bull_avg_ret:+.2f}%")

        if bear_stats:
            bear_n = sum(ps["n"] for ps in bear_stats)
            bear_wins = sum(int(ps["n"] * (ps.get("win_rate") or 0) / 100) for ps in bear_stats)
            bear_wr = bear_wins / bear_n * 100 if bear_n > 0 else 0
            bear_avg_ret = sum(ps["n"] * (ps.get("avg_return") or 0) for ps in bear_stats) / bear_n if bear_n > 0 else 0
            print(f"  📉 Bearish patterns: {bear_wins}/{bear_n} = {bear_wr:.1f}% win rate, avg return {bear_avg_ret:+.2f}%")

        print(f"  📊 All patterns combined: {total_wins}/{total_signals} = {overall_wr:.1f}% win rate")
        print()

        # Top 5 best and worst patterns
        ranked = sorted(pat_stats_5d, key=lambda x: x.get("expectancy") or 0, reverse=True)
        good = [p for p in ranked if p["n"] >= 20]
        print("  🏆 Top 5 most profitable patterns (5-day, N >= 20):")
        for ps in good[:5]:
            print(f"     {ps['pattern']:<30} win {ps.get('win_rate', 0):.1f}%  "
                  f"expect {ps.get('expectancy', 0):+.2f}%  (N={ps['n']})")
        print()
        print("  ⚠️  Bottom 5 patterns (5-day, N >= 20):")
        for ps in good[-5:]:
            print(f"     {ps['pattern']:<30} win {ps.get('win_rate', 0):.1f}%  "
                  f"expect {ps.get('expectancy', 0):+.2f}%  (N={ps['n']})")

    # Save summary to analysis_cache
    cache_result = {
        "status": "ok",
        "run_id": run_id,
        "universe_symbols": result["universe_symbols"],
        "universe_bars": result["universe_bars"],
        "patterns_found": result["patterns_found"],
        "summary": summary_data,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        conn = turso_db.get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_cache(
                cache_key TEXT PRIMARY KEY,
                run_at TEXT, run_at_epoch REAL, result_json TEXT)
        """)
        now = time.time()
        conn.execute("""
            INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
            VALUES(?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
              run_at=excluded.run_at, run_at_epoch=excluded.run_at_epoch,
              result_json=excluded.result_json
        """, ("daily_pattern_backtest", datetime.now(timezone.utc).isoformat(), now, json.dumps(cache_result)))
        conn.commit()
        logger.info("Backtest results saved to analysis_cache[daily_pattern_backtest]")
    except Exception as e:
        logger.warning(f"Could not save to analysis_cache: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
