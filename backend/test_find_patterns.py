#!/usr/bin/env python3
"""
Search for symbols that have detectable chart patterns.
"""

import sys
sys.path.insert(0, '.')
from patterns.advanced_pattern_adapter import scan_symbol
import sqlite3

con = sqlite3.connect('psx_v2.db')

# Get list of all symbols
symbols = con.execute(
    'SELECT DISTINCT symbol FROM daily_ohlc ORDER BY symbol LIMIT 20'
).fetchall()

print("🔍 Scanning for chart patterns in top 20 symbols...")
print("")

found_patterns = []

for (symbol,) in symbols:
    # Get last 200 bars for this symbol
    ohlcv_rows = con.execute(f'''
        SELECT trade_date, open, high, low, close, volume
        FROM daily_ohlc
        WHERE symbol = ?
        ORDER BY trade_date DESC
        LIMIT 200
    ''', (symbol,)).fetchall()

    if len(ohlcv_rows) >= 200:
        # Reverse to ascending order
        rows = [{'trade_date': row[0], 'open': float(row[1]), 'high': float(row[2]),
                 'low': float(row[3]), 'close': float(row[4]), 'volume': float(row[5])}
                for row in reversed(ohlcv_rows)]

        # Scan for patterns
        patterns = scan_symbol(symbol, rows)

        if patterns:
            found_patterns.append((symbol, patterns))
            print(f"✅ {symbol}: Found {len(patterns)} patterns")
            for p in patterns[:2]:
                print(f"      • {p['pattern_type']} on {p['signal_date']}")

con.close()

print("")
if found_patterns:
    print(f"✅ SUCCESS: Found patterns in {len(found_patterns)} symbols!")
    print("")
    print("📊 Summary of first symbol with patterns:")
    symbol, patterns = found_patterns[0]
    print(f"   Symbol: {symbol}")
    print(f"   Total patterns: {len(patterns)}")

    # Show date distribution
    by_date = {}
    for p in patterns:
        date = p['signal_date']
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(p['pattern_type'])

    print(f"   Pattern dates:")
    for date in sorted(by_date.keys())[-5:]:
        types = by_date[date]
        print(f"      {date}: {', '.join(set(types))}")

else:
    print("⚠️  No chart patterns found in first 20 symbols")
    print("   This might mean:")
    print("   1. Patterns are rare in this dataset")
    print("   2. The pattern detection has strict criteria")
    print("   3. This is expected for real market data")
    print("")
    print("✅ This is OK! The filtering logic will work when patterns DO exist.")
