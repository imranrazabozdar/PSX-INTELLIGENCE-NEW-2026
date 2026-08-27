# PSX Intelligence 2.9 — Install Candidate

This package consolidates the Android shell and backend work through V2.8.

## Android works without a separately deployed backend
- PSX market-watch reader
- 5-minute refresh/status
- >=50,000 volume gate and higher filters
- Shariah filter
- stock search and detail
- historical close/open/volume chart where the PSX endpoint responds
- RSI / SMA / EMA-MACD proxy / Bollinger calculations
- watchlist
- market pulse
- official PSX company/fundamental and announcement navigation
- educational Intelligence Lab

## Backend adds deeper research
- persistent true OHLCV
- ATR and pivot structure
- BOS
- candlestick recognition
- conservative Wyckoff hypotheses
- historical import/quality control
- unified conviction endpoints
- market regime / sector rotation / relative strength
- announcement intelligence
- grounded AI research brief

The deeper backend features require a running FastAPI service and genuine OHLC history. They are not
pretended to be active merely because the APK compiled.

## Build APK
Push this package over the existing Git repository and let `.github/workflows/build-apk.yml` build it.

## Accuracy
PSX portal information is treated as 5-minute delayed unless indicated otherwise. Do not redistribute
PSX market data without appropriate rights/license. The application is a private research tool, not
investment advice.
