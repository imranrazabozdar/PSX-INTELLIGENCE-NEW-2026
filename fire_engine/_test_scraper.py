#!/usr/bin/env python3
"""One-off verification: fire_engine.scraper.fetch_daily_ohlcv() against a
real recent trading day, run through validators.validate_trading_session()
and mfi_engine.calculate_mfi(). Not a permanent test file -- confirms the
production module (not the probe script) actually works end to end."""
from datetime import datetime, timedelta, timezone

from fire_engine.scraper import fetch_daily_ohlcv, get_symbol_info
from fire_engine.validators import validate_trading_session
from fire_engine.mfi_engine import calculate_mfi, calculate_mfi_derivatives

SYMBOL = "AICL"

info = get_symbol_info(SYMBOL)
print(f"Symbol info: session={info.get('session')!r} has_intraday={info.get('has_intraday')} "
      f"description={info.get('description')!r}")

# Most recent weekday (PKT), stepping back until we get candles or hit 10 tries
day = datetime.now(timezone.utc)
for attempt in range(10):
    day -= timedelta(days=1)
    if day.weekday() >= 5:
        continue
    date_str = day.strftime("%Y-%m-%d")
    candles = fetch_daily_ohlcv(SYMBOL, date_str)
    print(f"{date_str}: {len(candles)} candles")
    if candles:
        break

if not candles:
    print("No candles found in the lookback window -- stopping here.")
else:
    print(f"First candle: {candles[0]}")
    print(f"Last candle: {candles[-1]}")

    report = validate_trading_session(SYMBOL, candles, expected_candles=480)
    print(f"Validation: quality_status={report['quality_status']} total={report['total_candles']} "
          f"expected={report['expected_candles']} duplicates={report['duplicate_count']} "
          f"missing={report['missing_candle_count']} issues_sample={report['issues'][:5]}")

    mfi = calculate_mfi(candles, length=14)
    non_null = [v for v in mfi if v is not None]
    print(f"MFI(14): {len(non_null)} non-null values, last={mfi[-1]}")
    deriv = calculate_mfi_derivatives(mfi)
    print(f"MFI derivatives: {deriv}")
