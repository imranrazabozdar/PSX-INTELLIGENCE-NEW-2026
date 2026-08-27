# PSX Intelligence V3.1 — Consolidated Release Candidate

This is the package to build/install for testing. It consolidates the prior functional, fundamentals,
technical, true-OHLC, historical-ingestion, unified-intelligence, market/sector, news/AI, and Wyckoff Pro work.

## Key research layers
- PSX 5-minute delayed market-watch handling
- default >=50,000 share liquidity gate
- Shariah filter
- technical evidence: RSI, SMA, EMA/MACD proxy, Bollinger
- genuine OHLCV store and validation
- ATR, pivots, HH/HL vs LH/LL, BOS
- candlestick recognition only when true OHLC exists
- Wyckoff Pro: trading range, Effort vs Result, Spring/Test/SOS, UT/SOW, conservative phase hypotheses
- fundamentals and official PSX disclosure access
- market regime, breadth, sector rotation, relative strength
- unified explainable evidence ranking
- grounded AI research brief architecture
- watchlist and research-methodology screens

## Accuracy contract
No fake bid/ask, no fake OHLC, no invented filings/news, no fabricated win rates, and no score presented
as a probability of profit. Missing evidence stays missing.

## Important backend distinction
The APK has direct PSX-facing functions. Persistent OHLCV, deeper Wyckoff/structure/candlestick processing,
historical ingestion and server-side research endpoints require the included FastAPI backend to be running.

## Build
Copy this package over the existing Git-connected project, commit and push. GitHub Actions builds the APK.
