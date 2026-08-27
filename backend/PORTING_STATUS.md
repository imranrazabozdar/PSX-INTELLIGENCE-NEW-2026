# V1 → V2 Porting Status

## Copied verbatim for parity/audit
technical_analyzer, risk_manager, market_regime, portfolio_risk, portfolio_advisor,
fundamentals_analyzer/fetcher, sentiment/macro-news/news fetcher/feed, backtester,
scoring_engine, signal_generator, shariah_checker, reports, notify.

## Important
These modules originated in the uploaded V1 and depend on V1 `config.py` and
`database.py` contracts. They are deliberately preserved rather than casually
rewritten. `legacy_adapter.py` begins the normalization boundary.

Before live recommendations, complete integration tests must prove that the
same V1 inputs produce the same V1 outputs, then separately validate changes
needed for the full-PSX universe and 50K liquidity gate.
