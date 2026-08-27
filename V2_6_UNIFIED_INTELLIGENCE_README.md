# PSX Intelligence V2.6 — Unified Intelligence Engine

V2.6 combines independent evidence into an explainable ranking.

Current components:
- Liquidity
- Daily momentum
- Historical trend / RSI context
- True-OHLC market structure when stored
- True-OHLC Wyckoff evidence when stored

Default opportunity eligibility remains >= 50,000 current-session shares.

The PSX screener also exposes useful real fields such as market cap, P/E (TTM), dividend yield,
free float and 30-day average volume. Those are intentionally NOT mixed into the score until a robust
parser/cache normalizes them across the universe.

## Important
The V2 Conviction score is a heuristic evidence score, NOT a probability of profit.
Missing OHLC/fundamental/news evidence does not get invented.

Endpoints:
- `/conviction/{symbol}`
- `/ranked-opportunities?min_volume=50000&shariah=false&limit=30`
