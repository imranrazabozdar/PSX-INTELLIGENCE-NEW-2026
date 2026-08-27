# PSX Intelligence V2.3 — Technical Intelligence

Adds native technical and candle/market-behaviour tabs.

## Calculated from real PSX EOD observations
- RSI(14)
- SMA20 / SMA50
- EMA12 / EMA26 MACD proxy
- Bollinger bands
- Close-to-close behaviour
- Evidence score with transparent inputs

## Accuracy safeguard
The PSX public `/timeseries/eod/{symbol}` feed provides timestamp, close, volume and open, but not true
historical daily high/low. Therefore this build intentionally does NOT manufacture:
- ATR
- ADX
- wick-dependent candlestick patterns (hammer, shooting star, etc.)
- historical high/low based structure

Those require a true OHLC backfill from PSX's daily Historical Data source. That is the next data-engine step.
