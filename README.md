# PSX Intelligence 2.9 — Consolidated Install Candidate

# PSX Intelligence V2 — WorldClass Release Candidate

This is the consolidated GitHub-ready source package. It combines the V1 parity modules with the redesigned mobile shell and explainable intelligence layer.

## Mobile
- Premium dark institutional UI
- Home / Screener / Pulse / Intelligence / More
- 5-minute delayed source label and 5-minute refresh cadence
- Full PSX universe; Shariah filter
- 50,000-share default opportunity floor; 100K/250K/500K/1M filters
- Watchlist, sector drilldown, interactive history chart
- Stock quote snapshot, Structure, Wyckoff and AI evidence tabs
- News, portfolio/risk, past-picks, announcements, fundamentals and export entry points

## Backend
- FastAPI + SQLite + WebSocket architecture
- Original V1 technical/risk/news/backtest/fundamental modules retained for parity work
- Explainable candlestick/structure intelligence primitives
- Excel export and prediction-history schema

## Truth rule
No missing bid/ask, news, fundamental, phase or probability is fabricated. Public PSX portal information must be presented with its actual freshness status.

Push this folder to GitHub. GitHub Actions builds `PSX-Intelligence-V2-WorldClass-RC.apk`.
