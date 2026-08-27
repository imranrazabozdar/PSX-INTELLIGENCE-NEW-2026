# PSX Intelligence V2.5 — Historical Data Automation

V2.5 adds the ingestion/quality-control layer needed to populate the V2.4 true-OHLC engine.

## Why this implementation is conservative
The official PSX Historical Data page supports search by date and symbol and points users to Daily
Downloads. PSX's Terms of Use also restrict automated/systematic retrieval without permission. Therefore
this build does NOT add a hidden scraper that bypasses those restrictions.

## What is automated
1. Download/export historical or daily market-summary files through a method you are authorized to use.
2. Put CSV files on the backend machine.
3. Run:
   `python historical_import.py file1.csv file2.csv --db psx_v2.db`
4. Column aliases are detected automatically.
5. Rows are upserted into `daily_ohlc`.
6. `/ohlc-coverage` reports stored history by symbol.
7. `/data-quality/{symbol}` checks OHLC consistency.
8. `/intelligence/{symbol}` immediately uses the stored rows for ATR, structure, candles and Wyckoff.

This means the analysis pipeline is automatic after authorized files arrive, while the acquisition layer
stays compliant and replaceable if a licensed PSX feed/download API is obtained later.
