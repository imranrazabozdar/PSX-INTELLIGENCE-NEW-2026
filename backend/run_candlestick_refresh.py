#!/usr/bin/env python3
"""
Refresh candlestick patterns for all PSX symbols.
Run once daily after market close to detect patterns on completed candles.

Detects:
  1. Bullish Engulfing (2-candle reversal) — patterns_engine.py
  2. Morning Star (3-candle reversal) — morning_star_detector.py
  3. Three Line Strike — advanced_pattern_engine.py (if available)

Usage:
  python run_candlestick_refresh.py

Output:
  Stores pattern detection results in psx_v2.db candlestick_patterns table
  Logs pattern counts and timestamps
"""

import sqlite3
import logging
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import sys

# Import pattern detectors
try:
    import patterns_engine
    HAS_ENGULFING = True
except ImportError:
    HAS_ENGULFING = False
    print("Warning: patterns_engine not available")

try:
    from morning_star_detector import MorningStarDetector
    HAS_MORNING_STAR = True
except ImportError:
    HAS_MORNING_STAR = False
    print("Warning: morning_star_detector not available")

try:
    import advanced_pattern_engine
    HAS_ADVANCED = True
except ImportError:
    HAS_ADVANCED = False
    print("Warning: advanced_pattern_engine not available")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

PSX_TZ = ZoneInfo('Asia/Karachi')


def load_all_ohlcv_pandas(db_path='psx_v2.db'):
    """Load all OHLCV bars into pandas DataFrame for efficient processing."""
    con = sqlite3.connect(db_path)

    df = pd.read_sql_query("""
        SELECT symbol, trade_date, open, high, low, close, volume
        FROM daily_ohlc
        ORDER BY symbol, trade_date
    """, con)

    con.close()

    # Ensure numeric types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def detect_bullish_engulfing(df):
    """Detect Bullish Engulfing patterns using patterns_engine."""
    if not HAS_ENGULFING:
        return []

    results = []
    try:
        # Process each symbol's data
        for symbol in df['symbol'].unique():
            symbol_data = df[df['symbol'] == symbol].copy()

            if len(symbol_data) < 2:
                continue

            # Convert to list of dicts for patterns_engine
            rows = symbol_data[['trade_date', 'open', 'high', 'low', 'close']].to_dict('records')

            # Normalize and detect
            normalized = patterns_engine.normalize_daily_ohlc(rows, date_key='trade_date')

            if len(normalized) >= 2:
                # Check latest candle
                latest_idx = len(normalized) - 1
                if latest_idx >= 1:
                    c1 = normalized[latest_idx - 1]  # Previous candle
                    c2 = normalized[latest_idx]       # Current candle

                    geometry = patterns_engine._classify_geometry(c1, c2)

                    if geometry is not None:
                        results.append({
                            'symbol': symbol,
                            'pattern': 'BULLISH_ENGULFING',
                            'detected_date': str(c2['date']),
                            'geometry': geometry
                        })
    except Exception as e:
        logger.warning(f"Error detecting Bullish Engulfing: {e}")

    return results


def detect_morning_star(df):
    """Detect Morning Star patterns using morning_star_detector."""
    if not HAS_MORNING_STAR:
        return []

    results = []
    try:
        detector = MorningStarDetector()

        # Process each symbol
        for symbol in df['symbol'].unique():
            symbol_data = df[df['symbol'] == symbol].copy()
            symbol_data = symbol_data.rename(columns={'trade_date': 'trade_date'})

            if len(symbol_data) < 25:  # Morning Star needs minimum history
                continue

            # Detect patterns
            patterns_df = detector.detect_patterns(symbol_data, date_col='trade_date')

            if not patterns_df.empty:
                for _, pattern_row in patterns_df.iterrows():
                    results.append({
                        'symbol': symbol,
                        'pattern': 'MORNING_STAR',
                        'detected_date': str(pattern_row['date'].date() if hasattr(pattern_row['date'], 'date') else pattern_row['date']),
                        'strength': pattern_row['strength_rating']
                    })
    except Exception as e:
        logger.warning(f"Error detecting Morning Star: {e}")

    return results


def detect_three_line_strike(df):
    """Detect Three Line Strike patterns (bullish)."""
    if not HAS_ADVANCED:
        return []

    results = []
    try:
        # Process each symbol
        for symbol in df['symbol'].unique():
            symbol_data = df[df['symbol'] == symbol].copy()

            if len(symbol_data) < 4:  # Three Line Strike needs 3-4 candles
                continue

            # Convert to list of dicts
            candles = symbol_data[['trade_date', 'open', 'high', 'low', 'close']].to_dict('records')

            # Check latest 4 candles for Three Line Strike
            if len(candles) >= 4:
                latest_idx = len(candles) - 1

                # Try to detect Three Line Strike (simplified check)
                # A proper detection would use advanced_pattern_engine functions
                # For now, log that detection was attempted
                if hasattr(advanced_pattern_engine, 'detect_three_line_strike'):
                    pattern_result = advanced_pattern_engine.detect_three_line_strike(candles)
                    if pattern_result:
                        results.append({
                            'symbol': symbol,
                            'pattern': 'THREE_LINE_STRIKE',
                            'detected_date': str(candles[latest_idx]['trade_date'])
                        })
    except Exception as e:
        logger.warning(f"Error detecting Three Line Strike: {e}")

    return results


def store_results(all_patterns, db_path='psx_v2.db'):
    """Store all pattern detection results in database."""
    con = sqlite3.connect(db_path)

    # Create table if not exists
    con.execute("""
        CREATE TABLE IF NOT EXISTS candlestick_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            pattern_name TEXT,
            detected_date TEXT,
            confidence TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, pattern_name, detected_date)
        )
    """)

    # Clear old patterns for today (to avoid duplicates on re-run)
    today = datetime.now(PSX_TZ).strftime('%Y-%m-%d')
    con.execute("DELETE FROM candlestick_patterns WHERE date(detected_at) = ?", (today,))

    # Insert all patterns
    count = 0
    for pattern in all_patterns:
        try:
            con.execute("""
                INSERT INTO candlestick_patterns
                (symbol, pattern_name, detected_date, confidence)
                VALUES (?, ?, ?, ?)
            """, (
                pattern['symbol'],
                pattern['pattern'],
                pattern['detected_date'],
                pattern.get('strength', pattern.get('geometry', 'DETECTED'))
            ))
            count += 1
        except sqlite3.IntegrityError:
            pass  # Pattern already exists for this date

    con.commit()
    con.close()

    return count


def main():
    """Run candlestick pattern refresh for all pattern types."""
    try:
        logger.info("🔍 Starting comprehensive candlestick pattern detection...")

        # Load all OHLCV data
        logger.info("📊 Loading OHLCV data...")
        df = load_all_ohlcv_pandas()
        logger.info(f"   Loaded {len(df):,} bars from {df['symbol'].nunique()} symbols")

        all_patterns = []

        # Detect each pattern type
        logger.info("🕯️  Detecting patterns...")

        if HAS_ENGULFING:
            logger.info("   • Bullish Engulfing...")
            engulfing = detect_bullish_engulfing(df)
            all_patterns.extend(engulfing)
            logger.info(f"     Found {len(engulfing)} Bullish Engulfing patterns")

        if HAS_MORNING_STAR:
            logger.info("   • Morning Star...")
            morning_star = detect_morning_star(df)
            all_patterns.extend(morning_star)
            logger.info(f"     Found {len(morning_star)} Morning Star patterns")

        if HAS_ADVANCED:
            logger.info("   • Three Line Strike...")
            three_line = detect_three_line_strike(df)
            all_patterns.extend(three_line)
            logger.info(f"     Found {len(three_line)} Three Line Strike patterns")

        # Store results
        logger.info("💾 Storing pattern detection results...")
        stored = store_results(all_patterns)
        logger.info(f"   Stored {stored} pattern detections")

        logger.info("✅ Candlestick pattern refresh complete!")

        # Summary
        if all_patterns:
            logger.info("\n📋 Pattern Summary (Latest Date):")
            by_pattern = {}
            for p in all_patterns:
                key = p['pattern']
                if key not in by_pattern:
                    by_pattern[key] = []
                by_pattern[key].append(f"{p['symbol']}({p['detected_date']})")

            for pattern_type in sorted(by_pattern.keys()):
                symbols = by_pattern[pattern_type]
                logger.info(f"   {pattern_type}: {', '.join(symbols[:5])}" +
                           (f" + {len(symbols)-5} more" if len(symbols) > 5 else ""))
        else:
            logger.info("   No patterns detected in latest bars")

        return 0

    except Exception as e:
        logger.error(f"❌ Error during candlestick refresh: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
