#!/usr/bin/env python3
"""Fetch missing Aug 31, 2026 OHLCV data from PSX DPS and load to database."""

import sqlite3
import pandas as pd
from datetime import datetime
from dps_scraper import fetch_psx_dps_ohlc_bulk

print("🔄 Fetching Aug 31, 2026 data from PSX DPS Portal...")
print("")

con = sqlite3.connect('psx_v2.db')

# Get list of all unique symbols that have data
symbols = con.execute('SELECT DISTINCT symbol FROM daily_ohlc ORDER BY symbol').fetchall()
symbol_list = [s[0] for s in symbols]
print(f"📊 Fetching data for {len(symbol_list)} symbols...")
print(f"⏳ This may take 2-3 minutes due to rate limiting...")
print("")

# Fetch all symbols for Aug 31
results = fetch_psx_dps_ohlc_bulk(symbol_list, start_date='2026-08-31', end_date='2026-08-31', sleep_seconds=0.2)

# Count and load
total_bars = 0
loaded_symbols = 0
failed_symbols = []

for symbol, df in results.items():
    if df is not None and not df.empty:
        try:
            df.to_sql('daily_ohlc', con, if_exists='append', index=False)
            total_bars += len(df)
            loaded_symbols += 1
        except sqlite3.IntegrityError as e:
            # Duplicate, already exists
            failed_symbols.append(f"{symbol} (duplicate)")
        except Exception as e:
            failed_symbols.append(f"{symbol} ({str(e)[:30]})")
    elif symbol in [s[0] for s in symbols]:
        print(f"  ⚠️  {symbol}: No data returned")

con.commit()
con.close()

print("")
print(f"✅ Aug 31 data fetch complete!")
print(f"   Symbols with Aug 31 data loaded: {loaded_symbols}")
print(f"   Total bars loaded: {total_bars}")

if failed_symbols:
    print(f"   ⚠️  Issues: {len(failed_symbols)}")
    for sym in failed_symbols[:5]:
        print(f"      - {sym}")

if total_bars > 0:
    print("")
    print("✓ Aug 31 data successfully loaded!")
    print("✓ Running candlestick pattern detection...")

    # Now run pattern refresh
    import subprocess
    result = subprocess.run(['python', 'run_candlestick_refresh.py'], capture_output=True, text=True)

    # Show last few lines
    lines = result.stdout.strip().split('\n')
    for line in lines[-10:]:
        print(f"  {line}")
