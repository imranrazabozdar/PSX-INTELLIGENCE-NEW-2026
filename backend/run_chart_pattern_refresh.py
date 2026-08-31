#!/usr/bin/env python3
"""
Detect chart patterns (Double Bottom, Inverse H&S, etc.) on LATEST BAR ONLY.

This detects patterns where the BREAKOUT/CONFIRMATION happens TODAY.
- Needs 200+ days historical context to recognize the pattern
- But ONLY reports patterns where breakout is on the latest bar (today)
- Refreshes daily after market close (4:35 PM PKT)

Key difference from historical scan:
- scan_symbol(symbol, all_200_days) → returns patterns from APRIL-JUNE (old)
- scan_symbol_latest_only(symbol, all_200_days) → returns TODAY's breakouts only
"""

import sqlite3
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

# Import pattern scanner
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'patterns'))
from advanced_pattern_adapter import scan_symbol

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

PSX_TZ = ZoneInfo('Asia/Karachi')


def scan_symbol_latest_only(symbol: str, ohlc_rows: list) -> list:
    """
    Scan chart patterns on LATEST BAR ONLY.

    Key: We need 200+ days of context to recognize the pattern shape,
    but we ONLY report patterns where the BREAKOUT/CONFIRMATION
    happens on the latest bar (today).

    Returns: List of patterns with signal_date == latest bar date
    """
    if not ohlc_rows or len(ohlc_rows) == 0:
        return []

    # Get latest bar date for filtering
    latest_row = ohlc_rows[-1] if isinstance(ohlc_rows, list) else None
    if not latest_row:
        return []

    latest_date = None
    if isinstance(latest_row, dict):
        latest_date = latest_row.get('trade_date') or latest_row.get('date')
    else:
        latest_date = latest_row[0] if len(latest_row) > 0 else None

    # Scan with all 200+ days (pattern recognition needs context)
    all_signals = scan_symbol(symbol, ohlc_rows)

    # Filter to ONLY patterns with signal_date == latest bar
    latest_signals = []
    for signal in all_signals:
        signal_date = signal.get('signal_date')

        # Convert both to same format for comparison
        if signal_date and latest_date:
            signal_date_str = signal_date.strftime('%Y-%m-%d') if hasattr(signal_date, 'strftime') else str(signal_date)
            latest_date_str = latest_date.strftime('%Y-%m-%d') if hasattr(latest_date, 'strftime') else str(latest_date)

            if signal_date_str == latest_date_str:
                latest_signals.append(signal)

    return latest_signals


def load_all_ohlcv(db_path='psx_v2.db', lookback_days: int = 200) -> dict:
    """Load latest lookback_days bars for ALL symbols in ONE query.

    Returns dict: {symbol: [list of ohlcv dicts in ascending order]}

    This is MUCH more efficient than loading per-symbol in a loop.
    See run_candlestick_refresh.py for the same pattern.
    """
    con = sqlite3.connect(db_path)

    # Use window function to get latest N bars per symbol
    rows = con.execute(f"""
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

    con.close()

    # Organize by symbol
    data_by_symbol = {}
    for row in rows:
        symbol = row[0]
        if symbol not in data_by_symbol:
            data_by_symbol[symbol] = []

        data_by_symbol[symbol].append({
            'trade_date': row[1],
            'open': float(row[2]),
            'high': float(row[3]),
            'low': float(row[4]),
            'close': float(row[5]),
            'volume': float(row[6])
        })

    return data_by_symbol


def main():
    """Run chart pattern refresh for TODAY'S BREAKOUTS ONLY."""
    try:
        logger.info("🔍 Starting chart pattern detection (latest bar only)...")
        logger.info("   Patterns with breakout/confirmation on TODAY only")
        print("")

        # Load ALL data at once (single database query, much more efficient)
        logger.info("📊 Loading OHLCV data for all symbols...")
        all_data = load_all_ohlcv(lookback_days=200)
        symbol_list = list(all_data.keys())

        logger.info(f"   Loaded {len(symbol_list)} symbols with historical data")
        logger.info(f"⏳ Scanning for patterns...")
        print("")

        # Detect patterns
        all_patterns = []
        processed = 0

        for symbol in symbol_list:
            try:
                ohlcv = all_data[symbol]

                if len(ohlcv) < 100:  # Need minimum history
                    continue

                # Scan for patterns with breakout on LATEST BAR ONLY
                patterns = scan_symbol_latest_only(symbol, ohlcv)

                if patterns:
                    for pattern in patterns:
                        pattern['symbol'] = symbol
                        all_patterns.append(pattern)

                processed += 1
                if processed % 50 == 0:
                    logger.info(f"   Processed {processed}/{len(symbol_list)} symbols...")

            except Exception as e:
                logger.debug(f"   {symbol}: {str(e)[:50]}")
                continue

        logger.info(f"✅ Pattern detection complete!")
        logger.info(f"   Patterns with TODAY's breakout: {len(all_patterns)}")

        # Store results
        logger.info("💾 Setting up chart_patterns table...")

        # Connect to database for storage
        con = sqlite3.connect('psx_v2.db')

        # Create table schema if not exists
        con.execute("""
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

        # Clear old patterns (keep only today's)
        today = datetime.now(PSX_TZ).strftime('%Y-%m-%d')
        con.execute(
            "DELETE FROM chart_patterns WHERE DATE(signal_date) < ?",
            (today,)
        )

        # Insert new patterns
        stored = 0
        if all_patterns:
            for pattern in all_patterns:
                try:
                    con.execute("""
                        INSERT INTO chart_patterns
                        (symbol, pattern_type, signal_date, confidence_score, detected_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        pattern.get('symbol'),
                        pattern.get('pattern_type'),
                        pattern.get('signal_date'),
                        pattern.get('confidence_score'),
                        datetime.now(PSX_TZ)
                    ))
                    stored += 1
                except sqlite3.IntegrityError:
                    pass  # Duplicate

        con.commit()
        logger.info(f"   Table ready. Stored {stored} patterns")

        con.close()

        print("")
        logger.info("✅ Chart pattern refresh complete!")
        logger.info("")
        logger.info("📋 Summary:")
        logger.info(f"   Symbols scanned: {len(symbol_list)}")
        logger.info(f"   Patterns detected (TODAY's breakouts): {len(all_patterns)}")
        logger.info("")
        logger.info("Key point: Only patterns with breakout on TODAY'S bar are shown")
        logger.info("           Historical pattern dates are NOT displayed")

        return 0

    except Exception as e:
        logger.error(f"❌ Error during chart pattern refresh: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
