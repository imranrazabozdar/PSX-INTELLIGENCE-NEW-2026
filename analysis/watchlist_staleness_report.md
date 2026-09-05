# Watchlist Fundamentals Staleness Report

**Run date (UTC):** 2026-09-04T03:33:43.597069+00:00

## Step 1 finding — does the underlying data even exist?

Before running staleness detection wide, the actual data-source coverage was checked: `backend/fundamentals.json` currently caches ratios for only **35 symbols total** (any ticker, not just this watchlist), all sourced from `stockanalysis.com` via `fundamentals_fetcher.py`, plus whatever's in `config.FUNDAMENTALS` (currently empty for these tickers). **Only 20 of the 89 watchlist symbols (22.5%) have any usable fundamentals data at all** — the remaining **69 (77.5%) have no underlying data source whatsoever**, not stale data, no data. **This confirms the task's own hypothesis: the primary blocker for most of the watchlist is data coverage, not staleness of what exists.** The staleness mechanism itself (Fix 2) generalizes correctly to every symbol it has data for — see below — but it cannot manufacture data for symbols `fundamentals_fetcher.py` was never run against or that never got a `config.FUNDAMENTALS` manual entry.

## Step 2/3 — bucket counts

- **FRESH** (data exists, not stale): **19** / 89
- **STALE** (data exists, >120 days old): **1** / 89
- **NO_DATA** (suppressed, no source at all): **69** / 89

## STALE priority list (sorted by age_days, descending)

This is the practical priority order for a manual sourcing pass like the one already done for PRL and NRL — oldest/most-in-need-of-verification first.

| Ticker | data_as_of | age_days | P/E | EPS growth | ROE | D/E | Div. yield |
|---|---|---|---|---|---|---|---|
| PRL | 2025-06-30 | 431 | 3.79 | — | 45.49 | 0.39 | — |

## Full table — all 89 watchlist symbols

| Ticker | Bucket | data_as_of | age_days | P/E | EPS growth | ROE | D/E | Div. yield |
|---|---|---|---|---|---|---|---|---|
| CNERGY | FRESH | 2026-08-30 | 5 | 5.23 | — | 6.99 | 0.08 | — |
| PRL | STALE | 2025-06-30 | 431 | 3.79 | — | 45.49 | 0.39 | — |
| BOP | FRESH | 2026-08-30 | 5 | 6.26 | 23.06 | 18.42 | — | 8.58 |
| FNEL | NO_DATA | — | — | — | — | — | — | — |
| KEL | NO_DATA | — | — | — | — | — | — | — |
| SSGC | NO_DATA | — | — | — | — | — | — | — |
| PACE | NO_DATA | — | — | — | — | — | — | — |
| WAVESAPP | NO_DATA | — | — | — | — | — | — | — |
| NBP | FRESH | 2026-08-30 | 5 | 5.37 | 10.18 | 15.65 | — | 17.14 |
| PIBTL | NO_DATA | — | — | — | — | — | — | — |
| FCL | NO_DATA | — | — | — | — | — | — | — |
| PPL | FRESH | 2026-08-30 | 5 | 8.18 | -12.05 | 10.94 | 0.0 | 3.15 |
| BLUEX | NO_DATA | — | — | — | — | — | — | — |
| AKBL | NO_DATA | — | — | — | — | — | — | — |
| PREMA | NO_DATA | — | — | — | — | — | — | — |
| BECO | NO_DATA | — | — | — | — | — | — | — |
| BAFL | FRESH | 2026-08-30 | 5 | 5.43 | 2.68 | 17.51 | — | 10.29 |
| LOTCHEM | NO_DATA | — | — | — | — | — | — | — |
| NRL | FRESH | 2026-06-30 | 66 | 6.51 | — | 11.55 | 0.85 | — |
| SYS | FRESH | 2026-08-30 | 5 | 16.72 | 23.27 | 22.81 | 0.17 | 1.55 |
| HUBC | FRESH | 2026-08-30 | 5 | 5.51 | 7.58 | 22.42 | 0.28 | 9.49 |
| AICL | FRESH | 2026-08-30 | 5 | 5.68 | 8.83 | 11.79 | 0.01 | 4.26 |
| THCCL | NO_DATA | — | — | — | — | — | — | — |
| FCCL | NO_DATA | — | — | — | — | — | — | — |
| HASCOL | NO_DATA | — | — | — | — | — | — | — |
| ABL | FRESH | 2026-08-30 | 5 | 5.66 | -10.4 | 13.31 | — | 9.44 |
| PSO | FRESH | 2026-08-30 | 5 | 3.89 | 211.15 | 15.62 | 1.07 | 2.66 |
| HBL | FRESH | 2026-08-30 | 5 | 7.15 | 5.64 | 14.28 | — | 7.58 |
| OGDC | FRESH | 2026-08-30 | 5 | 8.99 | -7.12 | 11.35 | 0.0 | 4.71 |
| AVN | NO_DATA | — | — | — | — | — | — | — |
| SLGL | NO_DATA | — | — | — | — | — | — | — |
| SPSL | NO_DATA | — | — | — | — | — | — | — |
| POWER | NO_DATA | — | — | — | — | — | — | — |
| UBL | FRESH | 2026-08-30 | 5 | 7.6 | 36.43 | 31.52 | — | 7.17 |
| TRG | FRESH | 2026-08-30 | 5 | — | — | -13.71 | — | — |
| TOMCL | NO_DATA | — | — | — | — | — | — | — |
| AIRLINK | NO_DATA | — | — | — | — | — | — | — |
| FFL | NO_DATA | — | — | — | — | — | — | — |
| SEARL | NO_DATA | — | — | — | — | — | — | — |
| CLOV | NO_DATA | — | — | — | — | — | — | — |
| SNBL | NO_DATA | — | — | — | — | — | — | — |
| SNGP | NO_DATA | — | — | — | — | — | — | — |
| MDTL | NO_DATA | — | — | — | — | — | — | — |
| BML | NO_DATA | — | — | — | — | — | — | — |
| BNL | NO_DATA | — | — | — | — | — | — | — |
| BAHL | NO_DATA | — | — | — | — | — | — | — |
| SYM | NO_DATA | — | — | — | — | — | — | — |
| WASL | NO_DATA | — | — | — | — | — | — | — |
| CPHL | NO_DATA | — | — | — | — | — | — | — |
| FFC | FRESH | 2026-08-30 | 5 | 8.96 | 8.33 | 34.45 | 0.39 | 6.8 |
| MARI | FRESH | 2026-08-30 | 5 | 9.19 | 32.9 | 28.78 | 0.05 | 5.54 |
| MUGHAL | NO_DATA | — | — | — | — | — | — | — |
| BGL | NO_DATA | — | — | — | — | — | — | — |
| GAL | NO_DATA | — | — | — | — | — | — | — |
| GDL | NO_DATA | — | — | — | — | — | — | — |
| YOUW | NO_DATA | — | — | — | — | — | — | — |
| ZAL | NO_DATA | — | — | — | — | — | — | — |
| AGP | NO_DATA | — | — | — | — | — | — | — |
| LOADS | NO_DATA | — | — | — | — | — | — | — |
| KOHC | NO_DATA | — | — | — | — | — | — | — |
| SAZEW | NO_DATA | — | — | — | — | — | — | — |
| WAHDAT | NO_DATA | — | — | — | — | — | — | — |
| STCL | NO_DATA | — | — | — | — | — | — | — |
| GLAXO | NO_DATA | — | — | — | — | — | — | — |
| TGL | NO_DATA | — | — | — | — | — | — | — |
| MCB | FRESH | 2026-08-30 | 5 | 8.35 | -0.52 | 17.91 | — | 8.94 |
| JSBL | NO_DATA | — | — | — | — | — | — | — |
| IMAGE | NO_DATA | — | — | — | — | — | — | — |
| SCBPL | NO_DATA | — | — | — | — | — | — | — |
| BOK | NO_DATA | — | — | — | — | — | — | — |
| AGTL | NO_DATA | — | — | — | — | — | — | — |
| ECPL | NO_DATA | — | — | — | — | — | — | — |
| BIPL | NO_DATA | — | — | — | — | — | — | — |
| HMB | NO_DATA | — | — | — | — | — | — | — |
| FABL | NO_DATA | — | — | — | — | — | — | — |
| SBL | NO_DATA | — | — | — | — | — | — | — |
| ASTL | NO_DATA | — | — | — | — | — | — | — |
| EFERT | NO_DATA | — | — | — | — | — | — | — |
| DGKC | NO_DATA | — | — | — | — | — | — | — |
| LUCK | FRESH | 2026-08-30 | 5 | 7.27 | 15.71 | 22.38 | 0.39 | 1.14 |
| TBL | NO_DATA | — | — | — | — | — | — | — |
| STL | NO_DATA | — | — | — | — | — | — | — |
| STLR | NO_DATA | — | — | — | — | — | — | — |
| MLCF | NO_DATA | — | — | — | — | — | — | — |
| CHCC | NO_DATA | — | — | — | — | — | — | — |
| WTL | NO_DATA | — | — | — | — | — | — | — |
| PTC | NO_DATA | — | — | — | — | — | — | — |
| QTECH | NO_DATA | — | — | — | — | — | — | — |
| ITANZ | NO_DATA | — | — | — | — | — | — | — |

## Honest current state

Right now, **19 of 89 watchlist symbols (21.3%) are FRESH** — the only slice of the fundamentals layer that can be trusted at face value without a manual check. The other **70 (78.7%) need work**: 1 have real but stale data (>120 days old, 1.1% of the watchlist) and 69 have no data source at all (77.5% of the watchlist, the larger of the two gaps). This is the current, unvarnished state of the fundamentals layer across the full watchlist, not an aspirational one — closing the NO_DATA gap requires running `fundamentals_fetcher.py` (or adding manual `config.FUNDAMENTALS` entries) for the 69 uncovered symbols, and closing the STALE gap requires the same kind of one-company-at-a-time manual filing research already done for PRL and NRL — neither was attempted in this task, per its own scope.
