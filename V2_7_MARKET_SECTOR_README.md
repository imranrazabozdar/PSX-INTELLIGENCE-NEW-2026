# PSX Intelligence V2.7 — Market + Sector Intelligence

Adds context so stocks are not ranked in isolation.

## New endpoints
- `/market-regime`
- `/sector-rotation`
- `/relative-strength/{symbol}`

## Inputs available from the official PSX portal
The current PSX portal exposes major indices including KSE100, ALLSHR, KSE30, KMI30 and KMIALLSHR.
Market Watch exposes each security's sector, index memberships, OHLC/current price and volume.
The PSX screener exposes market cap, 1-year change, P/E TTM, dividend yield, free float and 30-day volume average.

## V2.7 outputs
- 50K-liquidity-gated breadth
- risk-on / constructive / mixed / risk-off heuristic
- KSE100/KMI30/ALLSHR/KMIALLSHR constituent breadth
- sector breadth and average change
- sector strength ranking
- top sector leaders
- current-session relative strength vs sector and KSE100 constituents

These are evidence/context scores, not return probabilities.
