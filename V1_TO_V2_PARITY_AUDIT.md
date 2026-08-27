# V2 Release Candidate — Original Engine Parity Audit

The uploaded V1 engine was rescanned before this package was prepared.

## V1 capabilities found
- 15-minute scheduler and market-hours logic
- PSX intraday/EOD/company endpoints
- SQLite persistence for runs, prices, daily OHLC, news, sentiment and outcomes
- Technical engine: RSI, MACD, Bollinger, OBV, ATR/ADX, CMF, support/resistance, candle signal
- KMI30 market regime and multi-horizon relative strength
- Evidence gates: score thresholds, hysteresis, RS laggard veto, CMF Buy confirmation
- Early Watch / building-zone logic
- Risk manager: stop/target, R:R, resistance headroom, earnings, concentration, position sizing
- Portfolio heat and portfolio advisor
- Shariah verification/staleness checks
- Fundamentals cache/analyzer/fetcher
- Macro/company news fetch, news feed, GLM ratings, sentiment analysis and raw headline display
- Backtester, forward outcome grading, indicator accuracy and walk-forward evaluation
- Reports, notifications, morning/evening jobs
- Excel export
- Streamlit dashboard and password support
- Accumulation streak/history views

## V2 requirements retained/added
- Full PSX analytical universe; Shariah is now a filter
- 50,000-share minimum default for opportunity shortlists
- Full-market data remains available below the shortlist threshold
- Mobile Home / Scanner / Markets / Watchlist interaction
- Persistent watchlist
- Sector drill-down
- Historical chart hook
- Structure and Wyckoff tabs
- Backend endpoints for market, breadth, sectors, stock history, news, predictions and Excel
- WebSocket endpoint for client updates
- Database tables for snapshots/news/predictions
- No fabricated ML probabilities or Wyckoff phase labels

## Still requires real deployment/data validation before it can be called final intelligence
The original V1 contains more mature RSI/MACD/CMF/risk/backtest logic than the Alpha mobile client.
Those modules should be ported server-side and validated against the expanded full-PSX universe before
their outputs are allowed to drive live recommendations. News collection also requires a deployed
background job and source-policy review. The APK cannot make those server-side jobs run by itself.

This RC is designed so those engines can be added behind stable API endpoints without redesigning the app.
