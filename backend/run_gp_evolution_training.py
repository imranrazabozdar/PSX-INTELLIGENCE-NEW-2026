#!/usr/bin/env python3
"""run_gp_evolution_training.py — offline GP-evolved-formula training for
backend/gp_evolved_detector.py, one model per WATCHLIST_SYMBOLS symbol
(kept in sync with app.py's own WATCHLIST_SYMBOLS by explicit copy below,
not import — importing app.py here would pull in FastAPI/background
threads this standalone script has no use for, same reason every other
run_*_backtest.py script in this repo avoids importing app.py).

Per symbol: stock's own daily OHLC (Turso) + KSE-100 index OHLC
(psx_live.index_history(), live, not stored) -> build_training_frame() ->
60/20/20 train/val/test split -> run_evolution() -> pick the Hall-of-Fame
member with the best VALIDATION fitness -> report out-of-sample TEST
stats -> save the trained individual (dill, base64) + those stats to
Turso's analysis_cache under gp_evolved_model_<SYMBOL>.

RESUMABLE: an existing gp_evolved_model_<SYMBOL> entry is skipped unless
GP_FORCE_RETRAIN=1 is set — GP training across ~89 symbols does not fit
one workflow run's time budget, so multiple workflow_dispatch runs are
expected to fill in the rest. MAX_RUNTIME_SECONDS (default ~5.5h, under
GitHub's 6h job cap) makes the script stop cleanly and print exactly
which symbols remain, rather than getting hard-killed mid-write.

After each symbol (whether trained this run or already cached), the
ranking summary (analysis_cache[gp_evolved_ranking]) is rebuilt from
EVERY currently-cached model, so a partial run still produces a useful,
complete-so-far ranking.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pandas as pd
import turso_db
import psx_live
import gp_evolved_detector as gped

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Kept in sync with app.py's WATCHLIST_SYMBOLS by explicit copy (see module docstring).
WATCHLIST_SYMBOLS = [
    'CNERGY', 'PRL', 'BOP', 'FNEL', 'KEL', 'SSGC', 'PACE', 'WAVESAPP', 'NBP', 'PIBTL',
    'FCL', 'PPL', 'BLUEX', 'AKBL', 'PREMA', 'BECO', 'BAFL', 'LOTCHEM', 'NRL', 'SYS',
    'HUBC', 'AICL', 'THCCL', 'FCCL', 'HASCOL', 'ABL', 'PSO', 'HBL', 'OGDC', 'AVN',
    'SLGL', 'SPSL', 'POWER', 'UBL', 'TRG', 'TOMCL', 'AIRLINK', 'FFL', 'SEARL', 'CLOV',
    'SNBL', 'SNGP', 'MDTL', 'BML', 'BNL', 'BAHL', 'SYM', 'WASL', 'CPHL', 'FFC',
    'MARI', 'MUGHAL', 'BGL', 'GAL', 'GDL', 'YOUW', 'ZAL', 'AGP', 'LOADS', 'KOHC',
    'SAZEW', 'WAHDAT', 'STCL', 'GLAXO', 'TGL', 'MCB', 'JSBL', 'IMAGE', 'SCBPL', 'BOK',
    'AGTL', 'ECPL', 'BIPL', 'HMB', 'FABL', 'SBL', 'ASTL', 'EFERT', 'DGKC', 'LUCK',
    'TBL', 'STL', 'STLR', 'MLCF', 'CHCC', 'WTL', 'PTC', 'QTECH', 'ITANZ',
]

MAX_RUNTIME_SECONDS = int(os.getenv("GP_MAX_RUNTIME_SECONDS", str(5 * 3600 + 30 * 60)))
POP_SIZE = int(os.getenv("GP_POP_SIZE", str(gped.POP_SIZE_DEFAULT)))
N_GEN = int(os.getenv("GP_N_GEN", str(gped.N_GEN_DEFAULT)))
FORCE_RETRAIN = os.getenv("GP_FORCE_RETRAIN", "0") == "1"


def _ensure_cache_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS analysis_cache(
        cache_key TEXT PRIMARY KEY, run_at TEXT, run_at_epoch REAL, result_json TEXT)""")


def _cache_get(conn, key):
    rows = conn.execute("SELECT result_json FROM analysis_cache WHERE cache_key=?", (key,)).fetchall()
    if not rows:
        return None
    r = rows[0]
    raw = r["result_json"] if isinstance(r, dict) else r[0]
    try:
        return json.loads(raw)
    except Exception:
        return None


def _cache_set(conn, key, payload):
    conn.execute("""
        INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
        VALUES(?,?,?,?)
        ON CONFLICT(cache_key) DO UPDATE SET
          run_at=excluded.run_at, run_at_epoch=excluded.run_at_epoch, result_json=excluded.result_json
    """, (key, datetime.now(timezone.utc).isoformat(), time.time(), json.dumps(payload)))
    conn.commit()


def load_symbol_rows(conn, symbol, limit=5000):
    recs = conn.execute(
        "SELECT trade_date, open, high, low, close FROM daily_ohlc "
        "WHERE symbol=? ORDER BY trade_date ASC LIMIT ?", (symbol, limit)
    ).fetchall()
    rows = []
    for r in recs:
        if isinstance(r, dict):
            rows.append({"date": r["trade_date"], "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"])})
        else:
            rows.append({"date": r[0], "open": float(r[1]), "high": float(r[2]),
                         "low": float(r[3]), "close": float(r[4])})
    return rows


def train_one(conn, symbol, index_rows, start_time):
    key = f"gp_evolved_model_{symbol}"
    if not FORCE_RETRAIN:
        existing = _cache_get(conn, key)
        if existing and existing.get("status") == "ok":
            logger.info(f"  {symbol}: already trained (cached) — skipping")
            return "cached"

    stock_rows = load_symbol_rows(conn, symbol)
    if len(stock_rows) < gped.MIN_BARS_REQUIRED:
        logger.info(f"  {symbol}: only {len(stock_rows)} bars, need >= {gped.MIN_BARS_REQUIRED} — skipping")
        _cache_set(conn, key, {"status": "insufficient_history", "bars": len(stock_rows),
                                "symbol": symbol})
        return "skipped"

    df = gped.build_training_frame(stock_rows, index_rows)
    if df is None:
        logger.info(f"  {symbol}: not enough KSE-100-overlapping history after z-score warm-up — skipping")
        _cache_set(conn, key, {"status": "insufficient_overlap", "symbol": symbol})
        return "skipped"

    train, val, test = gped.split_frame(df)
    if min(len(train), len(val), len(test)) < 30:
        logger.info(f"  {symbol}: split too thin (train={len(train)} val={len(val)} test={len(test)}) — skipping")
        _cache_set(conn, key, {"status": "split_too_thin", "symbol": symbol})
        return "skipped"

    t0 = time.time()
    result = gped.train_symbol(train, val, test, pop_size=POP_SIZE, n_gen=N_GEN, seed=gped.RNG_SEED)
    elapsed = time.time() - t0

    if result is None:
        logger.info(f"  {symbol}: no individual cleared the MIN_TRADES guard on validation "
                     f"({elapsed:.1f}s) — skipping")
        _cache_set(conn, key, {"status": "no_viable_individual", "symbol": symbol,
                                "train_bars": len(train), "val_bars": len(val), "test_bars": len(test)})
        return "no_viable"

    best, val_fitness, test_stats = result
    payload = {
        "status": "ok",
        "symbol": symbol,
        "model_blob": gped.serialize_individual(best),
        "formula": str(best),
        "tree_size": len(best),
        "val_fitness": round(val_fitness, 6),
        "test_stats": test_stats,
        "train_bars": len(train), "val_bars": len(val), "test_bars": len(test),
        "pop_size": POP_SIZE, "n_gen": N_GEN,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(conn, key, payload)
    logger.info(f"  {symbol}: trained in {elapsed:.1f}s — test return {test_stats['total_return_pct']:+.2f}%, "
                f"PF {test_stats['profit_factor']}, {test_stats['n_trades']} trades")
    return "trained"


def rebuild_ranking(conn):
    """Read back every gp_evolved_model_* entry currently in the cache and
    rebuild the ranking summary — runs after every symbol so a partial
    (time-budget-truncated) run still leaves a complete-so-far ranking."""
    rows = conn.execute(
        "SELECT cache_key, result_json FROM analysis_cache WHERE cache_key LIKE 'gp_evolved_model_%'"
    ).fetchall()
    ranked = []
    n_ok, n_skipped = 0, 0
    for r in rows:
        raw = r["result_json"] if isinstance(r, dict) else r[1]
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if payload.get("status") == "ok":
            n_ok += 1
            ts = payload["test_stats"]
            ranked.append({
                "symbol": payload["symbol"],
                "total_return_pct": ts["total_return_pct"],
                "annualized_return_pct": ts["annualized_return_pct"],
                "sharpe": ts["sharpe"],
                "profit_factor": ts["profit_factor"],
                "win_rate_pct": ts["win_rate_pct"],
                "n_trades": ts["n_trades"],
                "max_drawdown_pct": ts["max_drawdown_pct"],
                "trained_at": payload.get("trained_at"),
            })
        else:
            n_skipped += 1

    ranked.sort(key=lambda r: (r["sharpe"] if r["sharpe"] is not None else -999), reverse=True)
    summary = {
        "status": "ok",
        "symbols_trained": n_ok,
        "symbols_skipped": n_skipped,
        "ranked": ranked,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(conn, "gp_evolved_ranking", summary)
    return summary


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

    logger.info("Fetching KSE-100 index history (live, psx_live.index_history)...")
    index_rows = psx_live.index_history("KSE100", limit=3000)
    if not index_rows:
        logger.error("KSE-100 index history unavailable — cannot build the GP's 2nd input series. Aborting.")
        return 1
    logger.info(f"KSE-100 index history: {len(index_rows)} bars")

    conn = turso_db.get_connection()
    _ensure_cache_table(conn)

    logger.info(f"Training up to {len(WATCHLIST_SYMBOLS)} watchlist symbols "
                f"(pop={POP_SIZE}, gen={N_GEN}, force_retrain={FORCE_RETRAIN}, "
                f"budget={MAX_RUNTIME_SECONDS}s)...")

    start_time = time.time()
    counts = {"trained": 0, "cached": 0, "skipped": 0, "no_viable": 0}
    remaining = []
    for i, symbol in enumerate(WATCHLIST_SYMBOLS, 1):
        if time.time() - start_time > MAX_RUNTIME_SECONDS:
            remaining = WATCHLIST_SYMBOLS[i - 1:]
            logger.warning(f"Time budget reached after {i - 1}/{len(WATCHLIST_SYMBOLS)} symbols — "
                            f"stopping cleanly. {len(remaining)} symbols left for the next run.")
            break
        logger.info(f"[{i}/{len(WATCHLIST_SYMBOLS)}] {symbol}")
        try:
            outcome = train_one(conn, symbol, index_rows, start_time)
            counts[outcome] = counts.get(outcome, 0) + 1
        except Exception as e:
            logger.warning(f"  {symbol}: failed — {type(e).__name__}: {e}")
            counts["skipped"] = counts.get("skipped", 0) + 1

    summary = rebuild_ranking(conn)

    print("\n" + "=" * 90)
    print("GP-EVOLVED FORMULA — PSX TRAINING RUN")
    print("=" * 90)
    print(f"This run: trained={counts.get('trained', 0)} cached={counts.get('cached', 0)} "
          f"skipped={counts.get('skipped', 0)} no_viable={counts.get('no_viable', 0)}")
    if remaining:
        print(f"Not yet attempted this run ({len(remaining)}): {', '.join(remaining)}")
    print(f"\nOverall: {summary['symbols_trained']} symbols have a viable trained model, "
          f"{summary['symbols_skipped']} do not (insufficient history/overlap or no individual "
          f"cleared the MIN_TRADES guard).")

    if summary["ranked"]:
        print("\nTop 10 by out-of-sample Sharpe:")
        for r in summary["ranked"][:10]:
            print(f"  {r['symbol']:<10} sharpe={r['sharpe']:>7} return={r['total_return_pct']:+7.2f}%  "
                  f"pf={r['profit_factor']}  trades={r['n_trades']}  dd={r['max_drawdown_pct']}%")
        print("\nBottom 10 by out-of-sample Sharpe:")
        for r in summary["ranked"][-10:]:
            print(f"  {r['symbol']:<10} sharpe={r['sharpe']:>7} return={r['total_return_pct']:+7.2f}%  "
                  f"pf={r['profit_factor']}  trades={r['n_trades']}  dd={r['max_drawdown_pct']}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
