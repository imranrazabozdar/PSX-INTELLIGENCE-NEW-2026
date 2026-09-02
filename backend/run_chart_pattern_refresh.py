#!/usr/bin/env python3
"""
Daily pattern refresh — runs after market close via GitHub Actions.

Detects three pattern families on the LATEST daily bar and writes results
into BOTH the legacy chart_patterns table AND the analysis_cache table
(the same store the embedded backend's scan endpoints read from), so the
Streamlit frontend can display them even when the embedded backend's own
background loop can't reach dps.psx.com.pk to refresh OHLC data.

Pattern families:
  1. Bullish Engulfing  → analysis_cache key "bullish_engulfing_scan"
  2. Morning Star       → analysis_cache key "morning_star_scan"
  3. Advanced (IHS / Double Bottom) → analysis_cache key "advanced_pattern_scan"
  4. MHarris 5-Bar Reversal (BULL + BEAR) → analysis_cache key "mharris_scan"

Uses turso_db for database access — works against Turso Cloud in CI and
local SQLite in development, controlled by LIBSQL_URL / LIBSQL_AUTH_TOKEN.
"""

import json
import sqlite3
import time
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import logging

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
sys.path.insert(0, str(Path(__file__).parent / 'patterns'))

import turso_db
import patterns_engine as _patterns
from morning_star_detector import MorningStarDetector
from advanced_pattern_adapter import scan_symbol

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

PSX_TZ = ZoneInfo('Asia/Karachi')


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_ohlcv(lookback_days: int = 200) -> dict:
    """Load latest lookback_days bars for ALL symbols in ONE query.
    Returns dict: {symbol: [list of ohlcv dicts in ascending order]}
    """
    conn = turso_db.get_connection()
    rows = conn.execute(f"""
        WITH ranked AS (
            SELECT symbol, trade_date, open, high, low, close, volume,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) as rn
            FROM daily_ohlc
        )
        SELECT symbol, trade_date, open, high, low, close, volume
        FROM ranked
        WHERE rn <= {lookback_days}
        ORDER BY symbol, trade_date ASC
    """).fetchall()

    data_by_symbol = {}
    for row in rows:
        if isinstance(row, dict):
            symbol = row['symbol']
            data_by_symbol.setdefault(symbol, []).append({
                'trade_date': row['trade_date'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
            })
        else:
            symbol = row[0]
            data_by_symbol.setdefault(symbol, []).append({
                'trade_date': row[1],
                'open': float(row[2]),
                'high': float(row[3]),
                'low': float(row[4]),
                'close': float(row[5]),
                'volume': float(row[6]),
            })
    return data_by_symbol


# ---------------------------------------------------------------------------
# analysis_cache writer (mirrors scan_cache_engine.save)
# ---------------------------------------------------------------------------

def _save_to_analysis_cache(cache_key: str, result: dict):
    """Write a scan result into the analysis_cache table so the backend's
    scan endpoints can serve it via _scan_cache.latest(cache_key)."""
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
    """, (cache_key, datetime.now(timezone.utc).isoformat(), now, json.dumps(result)))
    conn.commit()
    logger.info(f"  Saved to analysis_cache[{cache_key}]")


# ---------------------------------------------------------------------------
# 1. Bullish Engulfing scan
# ---------------------------------------------------------------------------

def run_bullish_engulfing_scan(all_data: dict) -> dict:
    hits = []
    scanned = 0
    for symbol, ohlcv in all_data.items():
        if len(ohlcv) < 10:
            continue
        scanned += 1
        try:
            result = _patterns.detect_bullish_engulfing(ohlcv, date_key="trade_date")
        except Exception:
            continue
        if result["classification"] == _patterns.NO_BULLISH_ENGULFING:
            continue
        result["symbol"] = symbol
        hits.append(result)

    hits.sort(key=lambda r: (r["classification"] != _patterns.VALID_BULLISH_ENGULFING, r["symbol"]))
    return {"status": "ok", "scanned": scanned, "hits": hits}


# ---------------------------------------------------------------------------
# 1b. MHarris 5-Bar Reversal scan (BULL + BEAR in one list, split by
#     the "direction" field -- see patterns_engine.detect_mharris_reversal)
# ---------------------------------------------------------------------------

def run_mharris_scan(all_data: dict) -> dict:
    hits = []
    scanned = 0
    for symbol, ohlcv in all_data.items():
        if len(ohlcv) < 10:
            continue
        scanned += 1
        try:
            result = _patterns.detect_mharris_reversal(ohlcv, date_key="trade_date")
        except Exception:
            continue
        if result["classification"] == _patterns.NO_MHARRIS_SIGNAL:
            continue
        result["symbol"] = symbol
        hits.append(result)

    hits.sort(key=lambda r: (r["direction"] != "BULL", r["symbol"]))
    return {"status": "ok", "scanned": scanned, "hits": hits}


# ---------------------------------------------------------------------------
# 2. Morning Star scan
# ---------------------------------------------------------------------------

def run_morning_star_scan(all_data: dict) -> dict:
    detector = MorningStarDetector()
    hits = []
    scanned = 0
    for symbol, ohlcv in all_data.items():
        if len(ohlcv) < detector.config.min_history_days + 3:
            continue
        scanned += 1
        try:
            df = pd.DataFrame(ohlcv)
            result = detector.detect_patterns(df, date_col="trade_date")
        except Exception:
            continue
        if result.empty:
            continue
        latest_stored_date = pd.to_datetime(df["trade_date"]).max()
        result = result[result["date"] == latest_stored_date]
        if result.empty:
            continue
        row = result.iloc[0]
        hits.append({
            "symbol": symbol, "pattern": row["pattern_type"],
            "date": row["date"].strftime("%Y-%m-%d"),
            "strength_rating": row["strength_rating"],
            "day3_penetration_pct": float(row["day3_penetration_pct"]),
            "volume_ratio_day3": float(row["volume_ratio_day3"]),
            "entry_price": float(row["entry_price"]),
            "stop_loss": float(row["stop_loss"]),
            "target_1": float(row["target_1"]),
            "target_2": float(row["target_2"]),
        })

    hits.sort(key=lambda r: (r["strength_rating"] != "STRONG", r["symbol"]))
    return {"status": "ok", "scanned": scanned, "hits": hits}


# ---------------------------------------------------------------------------
# 3. Advanced pattern scan (IHS / Double Bottom) — latest bar only
# ---------------------------------------------------------------------------

def run_advanced_pattern_scan(all_data: dict) -> dict:
    hits = []
    scanned = 0
    for symbol, ohlcv in all_data.items():
        if len(ohlcv) < 100:
            continue
        scanned += 1
        try:
            signals = scan_symbol(symbol, ohlcv)
            for sig in signals:
                sig["symbol"] = symbol
                hits.append(sig)
        except Exception:
            continue

    hits.sort(key=lambda h: (h.get("confidence_score") is None,
                              -(h.get("confidence_score") or 0)))
    return {"status": "ok", "scanned": scanned, "hits": hits}


# ---------------------------------------------------------------------------
# Legacy chart_patterns table (kept for backward compat)
# ---------------------------------------------------------------------------

def save_to_chart_patterns_table(all_patterns: list):
    conn = turso_db.get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chart_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            pattern_type TEXT,
            signal_date TEXT,
            confidence_score REAL,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, pattern_type, signal_date)
        )
    """)

    today = datetime.now(PSX_TZ).strftime('%Y-%m-%d')
    conn.execute("DELETE FROM chart_patterns WHERE DATE(signal_date) < ?", (today,))

    stored = 0
    for pattern in all_patterns:
        try:
            conn.execute("""
                INSERT INTO chart_patterns
                (symbol, pattern_type, signal_date, confidence_score, detected_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                pattern.get('symbol'),
                pattern.get('pattern_type'),
                pattern.get('signal_date'),
                pattern.get('confidence_score'),
                datetime.now(PSX_TZ).isoformat(),
            ))
            stored += 1
        except (sqlite3.IntegrityError, Exception) as e:
            if "UNIQUE" in str(e).upper() or "integrity" in str(e).lower():
                pass
            else:
                logger.debug(f"Insert failed for {pattern.get('symbol')}: {e}")

    conn.commit()
    return stored


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        db_status = turso_db.status()
        logger.info(f"Database: {db_status['backend']}")
        logger.info("Starting pattern detection (all three families)...")
        print("")

        logger.info("Loading OHLCV data for all symbols...")
        all_data = load_all_ohlcv(lookback_days=200)
        logger.info(f"  Loaded {len(all_data)} symbols with historical data")
        print("")

        # --- 1. Bullish Engulfing ---
        logger.info("Running Bullish Engulfing scan...")
        be_result = run_bullish_engulfing_scan(all_data)
        logger.info(f"  Scanned {be_result['scanned']} symbols, {len(be_result['hits'])} hits")
        _save_to_analysis_cache("bullish_engulfing_scan", be_result)

        # --- 1b. MHarris 5-Bar Reversal ---
        logger.info("Running MHarris 5-Bar Reversal scan...")
        mh_result = run_mharris_scan(all_data)
        logger.info(f"  Scanned {mh_result['scanned']} symbols, {len(mh_result['hits'])} hits")
        _save_to_analysis_cache("mharris_scan", mh_result)

        # --- 2. Morning Star ---
        logger.info("Running Morning Star scan...")
        ms_result = run_morning_star_scan(all_data)
        logger.info(f"  Scanned {ms_result['scanned']} symbols, {len(ms_result['hits'])} hits")
        _save_to_analysis_cache("morning_star_scan", ms_result)

        # --- 3. Advanced Patterns (IHS / Double Bottom) ---
        logger.info("Running Advanced Pattern scan (IHS / Double Bottom)...")
        adv_result = run_advanced_pattern_scan(all_data)
        logger.info(f"  Scanned {adv_result['scanned']} symbols, {len(adv_result['hits'])} hits")
        _save_to_analysis_cache("advanced_pattern_scan", adv_result)

        # --- Legacy chart_patterns table (advanced patterns only) ---
        adv_patterns = adv_result.get("hits", [])
        stored = save_to_chart_patterns_table(adv_patterns)
        logger.info(f"  chart_patterns table: {stored} rows stored")

        print("")
        logger.info("Pattern refresh complete!")
        logger.info("Summary:")
        logger.info(f"  Symbols loaded: {len(all_data)}")
        logger.info(f"  Bullish Engulfing: {len(be_result['hits'])} signals")
        logger.info(f"  MHarris 5-Bar Reversal: {len(mh_result['hits'])} signals")
        logger.info(f"  Morning Star: {len(ms_result['hits'])} signals")
        logger.info(f"  Advanced (IHS/DB): {len(adv_result['hits'])} signals")

        return 0

    except Exception as e:
        logger.error(f"Error during pattern refresh: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
