#!/usr/bin/env python3
"""
Signal accuracy backtest — validates whether the intraday module's
bull/bear signals correctly predicted price direction.

Methodology:
  1. Loads all intraday_alert records from the database
  2. For each signal, looks up forward returns at 1-day, 3-day, 5-day horizons
     using daily_ohlc data
  3. A bull signal is "correct" if forward return > 0
  4. A bear signal is "correct" if forward return < 0
  5. Produces a summary table with hit rates per signal type and horizon

Runs in GitHub Actions (same env as the pattern refresh workflow).
"""

import json
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import turso_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

BULL_SIGNALS = {"AD_BULL_DIVERGENCE", "EXTREME_VOLUME", "HIGH_VOLUME", "RANGE_HIGH_VOLUME"}
BEAR_SIGNALS = {"AD_BEAR_DIVERGENCE", "RANGE_LOW_VOLUME"}
HORIZONS = [1, 3, 5]


def load_alerts():
    """Load all intraday alerts from the database."""
    conn = turso_db.get_connection()
    try:
        rows = conn.execute(
            "SELECT symbol, alert_type, triggered_at, price_at_trigger, "
            "volume_ratio, range_position, session_date "
            "FROM intraday_alert ORDER BY session_date, triggered_at"
        ).fetchall()
    except Exception as e:
        logger.warning(f"Could not load intraday_alert: {e}")
        return []

    alerts = []
    for r in rows:
        if isinstance(r, dict):
            alerts.append(r)
        else:
            alerts.append({
                "symbol": r[0], "alert_type": r[1], "triggered_at": r[2],
                "price_at_trigger": r[3], "volume_ratio": r[4],
                "range_position": r[5], "session_date": r[6],
            })
    return alerts


def load_ohlc_for_symbols(symbols: set) -> dict:
    """Load daily OHLC for all symbols that had alerts.
    Returns {symbol: [(trade_date, close), ...]} sorted by date ascending."""
    conn = turso_db.get_connection()
    data = {}
    for sym in symbols:
        rows = conn.execute(
            "SELECT trade_date, open, high, low, close FROM daily_ohlc "
            "WHERE symbol = ? ORDER BY trade_date ASC",
            (sym,)
        ).fetchall()
        if rows:
            parsed = []
            for r in rows:
                if isinstance(r, dict):
                    parsed.append((r["trade_date"], float(r["close"])))
                else:
                    parsed.append((r[0], float(r[4])))
            data[sym] = parsed
    return data


def get_forward_return(ohlc_list, signal_date, horizon):
    """Get the forward return (%) from signal_date over `horizon` trading days.
    Returns None if not enough data."""
    dates = [d for d, _ in ohlc_list]
    try:
        idx = dates.index(signal_date)
    except ValueError:
        # Signal date not in daily OHLC — try finding nearest trading day after
        for i, d in enumerate(dates):
            if d >= signal_date:
                idx = i
                break
        else:
            return None

    if idx + horizon >= len(ohlc_list):
        return None

    entry_close = ohlc_list[idx][1]
    exit_close = ohlc_list[idx + horizon][1]
    if entry_close <= 0:
        return None
    return ((exit_close - entry_close) / entry_close) * 100


def main():
    try:
        db_status = turso_db.status()
        logger.info(f"Database: {db_status['backend']}")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return 1

    # 1. Load all alerts
    alerts = load_alerts()
    logger.info(f"Loaded {len(alerts)} intraday alerts")

    if not alerts:
        logger.warning("No alerts found — nothing to backtest")
        print("\n=== SIGNAL BACKTEST SUMMARY ===")
        print("No intraday alerts found in database.")
        print("Alerts are generated during market hours by the intraday monitoring module.")
        return 0

    # 2. Get unique symbols and load their OHLC data
    symbols = set(a["symbol"] for a in alerts)
    logger.info(f"Unique symbols with alerts: {len(symbols)}")

    ohlc_data = load_ohlc_for_symbols(symbols)
    logger.info(f"Loaded OHLC data for {len(ohlc_data)} symbols")

    # 3. Compute forward returns for each alert
    results_by_type = defaultdict(lambda: {h: {"correct": 0, "wrong": 0, "neutral": 0, "no_data": 0, "returns": []}
                                           for h in HORIZONS})

    for alert in alerts:
        sym = alert["symbol"]
        alert_type = alert["alert_type"]
        session_date = alert["session_date"]
        is_bull = alert_type in BULL_SIGNALS
        is_bear = alert_type in BEAR_SIGNALS

        if not (is_bull or is_bear):
            continue

        if sym not in ohlc_data:
            for h in HORIZONS:
                results_by_type[alert_type][h]["no_data"] += 1
            continue

        for h in HORIZONS:
            fwd_ret = get_forward_return(ohlc_data[sym], session_date, h)
            if fwd_ret is None:
                results_by_type[alert_type][h]["no_data"] += 1
                continue

            results_by_type[alert_type][h]["returns"].append(fwd_ret)

            if is_bull:
                if fwd_ret > 0:
                    results_by_type[alert_type][h]["correct"] += 1
                elif fwd_ret < 0:
                    results_by_type[alert_type][h]["wrong"] += 1
                else:
                    results_by_type[alert_type][h]["neutral"] += 1
            elif is_bear:
                if fwd_ret < 0:
                    results_by_type[alert_type][h]["correct"] += 1
                elif fwd_ret > 0:
                    results_by_type[alert_type][h]["wrong"] += 1
                else:
                    results_by_type[alert_type][h]["neutral"] += 1

    # 4. Print summary
    print("\n" + "=" * 80)
    print("INTRADAY SIGNAL BACKTEST — ACCURACY SUMMARY")
    print("=" * 80)
    print(f"Total alerts analyzed: {len(alerts)}")
    print(f"Unique symbols: {len(symbols)}")
    print(f"Date range: {alerts[0]['session_date']} to {alerts[-1]['session_date']}")
    print()

    all_type_results = {}

    for alert_type in sorted(results_by_type.keys()):
        side = "BULL" if alert_type in BULL_SIGNALS else "BEAR"
        print(f"{'─' * 80}")
        print(f"📊 {alert_type} ({side})")
        print(f"{'─' * 80}")
        print(f"{'Horizon':<12} {'Signals':<10} {'Correct':<10} {'Wrong':<10} "
              f"{'Hit Rate':<12} {'Avg Fwd Ret':<14} {'Verdict'}")
        print(f"{'─' * 12} {'─' * 10} {'─' * 10} {'─' * 10} {'─' * 12} {'─' * 14} {'─' * 10}")

        type_summary = {}
        for h in HORIZONS:
            r = results_by_type[alert_type][h]
            total = r["correct"] + r["wrong"] + r["neutral"]
            hit_rate = (r["correct"] / total * 100) if total > 0 else 0
            avg_ret = sum(r["returns"]) / len(r["returns"]) if r["returns"] else 0

            if total < 5:
                verdict = "⚠ Low sample"
            elif hit_rate >= 60:
                verdict = "✅ GOOD"
            elif hit_rate >= 50:
                verdict = "➡ FAIR"
            else:
                verdict = "❌ POOR"

            print(f"{h}-day{'':<7} {total:<10} {r['correct']:<10} {r['wrong']:<10} "
                  f"{hit_rate:>5.1f}%{'':<6} {avg_ret:>+7.2f}%{'':<6} {verdict}")

            type_summary[h] = {
                "total": total, "correct": r["correct"], "wrong": r["wrong"],
                "hit_rate": round(hit_rate, 1), "avg_return": round(avg_ret, 2),
                "no_data": r["no_data"],
            }

        all_type_results[alert_type] = type_summary
        print()

    # 5. Overall summary
    print("=" * 80)
    print("OVERALL SUMMARY")
    print("=" * 80)

    for side_name, side_set in [("BULL signals", BULL_SIGNALS), ("BEAR signals", BEAR_SIGNALS)]:
        for h in HORIZONS:
            total_correct = sum(results_by_type[t][h]["correct"] for t in side_set if t in results_by_type)
            total_wrong = sum(results_by_type[t][h]["wrong"] for t in side_set if t in results_by_type)
            total = total_correct + total_wrong
            if total > 0:
                overall_hit = total_correct / total * 100
                all_rets = []
                for t in side_set:
                    if t in results_by_type:
                        all_rets.extend(results_by_type[t][h]["returns"])
                avg_ret = sum(all_rets) / len(all_rets) if all_rets else 0
                print(f"  {side_name} @ {h}-day: {total_correct}/{total} = {overall_hit:.1f}% hit rate, "
                      f"avg fwd return {avg_ret:+.2f}%")

    print()

    # 6. Save results to analysis_cache for frontend display
    result = {
        "status": "ok",
        "total_alerts": len(alerts),
        "unique_symbols": len(symbols),
        "date_range": [alerts[0]["session_date"], alerts[-1]["session_date"]],
        "by_type": all_type_results,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        conn = turso_db.get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_cache(
                cache_key TEXT PRIMARY KEY,
                run_at TEXT, run_at_epoch REAL, result_json TEXT)
        """)
        import time
        now = time.time()
        conn.execute("""
            INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
            VALUES(?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
              run_at=excluded.run_at, run_at_epoch=excluded.run_at_epoch,
              result_json=excluded.result_json
        """, ("signal_backtest", datetime.now(timezone.utc).isoformat(), now, json.dumps(result)))
        conn.commit()
        logger.info("Results saved to analysis_cache[signal_backtest]")
    except Exception as e:
        logger.warning(f"Could not save results to analysis_cache: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
