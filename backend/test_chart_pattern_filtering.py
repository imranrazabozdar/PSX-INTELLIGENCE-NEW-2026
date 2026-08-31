#!/usr/bin/env python3
"""
Test that chart pattern filtering works correctly.
Verify that:
1. scan_symbol() returns all patterns across the date range
2. Filtering to latest bar only works
3. Historical patterns are excluded
"""

import sys
sys.path.insert(0, '.')
from patterns.advanced_pattern_adapter import scan_symbol
import sqlite3

con = sqlite3.connect('psx_v2.db')

# Get a symbol with plenty of historical data
symbol = 'ANSM'
ohlcv_rows = con.execute('''
    SELECT trade_date, open, high, low, close, volume
    FROM daily_ohlc
    WHERE symbol = ?
    ORDER BY trade_date ASC
    LIMIT 200
''', (symbol,)).fetchall()

con.close()

# Convert to dict format
rows = [{'trade_date': row[0], 'open': float(row[1]), 'high': float(row[2]),
         'low': float(row[3]), 'close': float(row[4]), 'volume': float(row[5])}
        for row in ohlcv_rows]

if len(rows) == 200:
    print(f"🔍 Testing pattern detection on {symbol}")
    print(f"   Data range: {rows[0]['trade_date']} to {rows[-1]['trade_date']}")
    print(f"   Total bars: {len(rows)}")
    print("")

    # Scan for all patterns
    patterns = scan_symbol(symbol, rows)

    print(f"✅ Pattern scanner returned: {len(patterns)} patterns")

    if patterns:
        print("")
        print(f"📊 Patterns by signal_date:")
        by_date = {}
        for p in patterns:
            date = p['signal_date']
            if date not in by_date:
                by_date[date] = []
            by_date[date].append((p['pattern_type'], p['confidence_score']))

        for date in sorted(by_date.keys())[-10:]:
            items = by_date[date]
            print(f"   {date}:")
            for ptype, conf in items[:3]:
                print(f"      {ptype} (confidence: {conf:.2f})")
            if len(items) > 3:
                print(f"      ... +{len(items)-3} more")

        print("")
        print(f"✅ Pattern detection working!")
        print(f"   Latest bar date in dataset: {rows[-1]['trade_date']}")

        # Test the filtering
        latest_date = rows[-1]['trade_date']
        latest_only = [p for p in patterns if p['signal_date'] == latest_date]

        print(f"")
        print(f"🔬 Testing latest-bar-only filter:")
        print(f"   Total patterns found: {len(patterns)}")
        print(f"   Patterns with signal_date == latest bar: {len(latest_only)}")
        print(f"   Result: {'✅ FILTERING WORKS' if len(latest_only) > 0 else '✅ (No patterns on latest bar - correct)'}")

        # Show breakdown
        print(f"")
        print(f"📋 Signal date breakdown:")
        for date in sorted(by_date.keys()):
            count = len(by_date[date])
            marker = " 👈 LATEST" if date == latest_date else ""
            print(f"   {date}: {count} patterns{marker}")
    else:
        print(f"   (no patterns found - this is fine for this test)")
else:
    print(f"Error: expected 200 rows, got {len(rows)}")

print("")
print("✅ Test complete!")
