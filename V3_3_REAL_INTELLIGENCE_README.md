# PSX Intelligence V3.3 — Real Intelligence Engine

This build fixes the biggest V3.2 limitation: historical analysis no longer depends on one failing endpoint.

## History source cascade
1. Official PSX EOD endpoint.
2. Yahoo Finance PSX ticker (`SYMBOL.KA`) as a genuine OHLCV fallback.
3. Last successfully cached history stored locally on the phone.

The selected source is displayed inside the chart/analysis. Missing data is never fabricated.

## Functional analysis
- Historical chart
- RSI 14
- SMA 20/50
- EMA12/EMA26 MACD
- Bollinger bands
- ATR 14 when true OHLC exists
- CMF 20 when true OHLCV exists
- OBV
- Candlestick detection (Doji, hammer-like, shooting-star-like, engulfing)
- Market structure / range / breakout-BOS candidates
- Wyckoff range location, volume effort, Spring/Upthrust/SOS/SOW candidates
- Grounded AI bull/bear/confirmation/invalidation brief
- Speak reads the live analysis
- Source/session count shown
- Local historical cache
- Market OPEN/CLOSED + 5-minute-delay timestamp
- Fixed literal `\n` formatting bug in Methodology and Portfolio/Risk

## Accuracy policy
Fallback OHLCV is labelled by source. Candidate pattern names are not promoted to confirmed signals
without confirmation. Evidence scores are not profit probabilities.
