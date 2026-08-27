# PSX Intelligence V2.1 Functional Build

This build removes misleading `backend-ready` labels from the Android app and makes the features that can
work safely without a separately deployed server actually usable.

## Working in the APK
- Direct PSX market-watch collection
- 5-minute refresh cadence and explicit PSX 5M DELAY status
- Full PSX scanner
- Default 50,000-share liquidity gate plus 100K/250K/500K/1M filters
- Shariah filter
- Market breadth / sector Pulse
- Watchlist
- Interactive historical chart when the PSX EOD endpoint responds
- Structure / Wyckoff / AI-evidence contextual views
- Official PSX company Fundamentals link from each stock
- Official PSX Announcements link
- News/disclosure screen that never invents headlines
- Risk, track-record and methodology screens

## Included backend source
FastAPI backend remains included for persistent history, Excel, server-side news, predictions and later
LLM integration. WebSocket refresh cadence is 300 seconds.

## Accuracy policy
No fake bid/ask, no fake news, no fake fundamentals, no fake historical win rate, and no LLM-generated
indicator values. PSX portal data is treated as 5-minute delayed unless the source says otherwise.
