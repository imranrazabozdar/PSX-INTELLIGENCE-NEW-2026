# PSX Intelligence V2.4 — True OHLC Intelligence

PSX currently exposes an official Historical Data search/download area. This build adds the missing
persistent OHLCV layer so genuine historical rows can feed the intelligence engine.

## New backend capabilities
- `daily_ohlc` SQLite store
- POST `/ohlc/{symbol}` genuine OHLCV ingestion
- GET `/ohlc/{symbol}`
- GET `/intelligence/{symbol}`
- ATR(14)
- swing-high / swing-low pivots
- HH/HL vs LH/LL market structure
- BOS detection
- true body/wick candle recognition: doji, hammer-like, shooting-star-like, engulfing
- conservative Wyckoff range/SOS/spring hypotheses
- volume-expansion context

## Accuracy rule
The app never synthesizes high/low from close-only series. Until genuine rows from PSX Historical Data
are ingested, OHLC-dependent outputs explicitly remain unavailable.

## Next integration
Automate the Historical Data downloader/parser for private research, then connect the Android tabs to
`/intelligence/{symbol}` when the backend is deployed.
