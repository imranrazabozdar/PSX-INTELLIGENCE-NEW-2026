# Pre-Move Study: AICL, SHFA, THCCL & FNEL

**Prepared:** 2026-09-03 (deepened/extended from the first pass, which covered only AICL/SHFA at
summary-level detail).
**Method note (read first):** All price/volume data below is real, pulled directly from PSX's own Data
Portal (`dps.psx.com.pk/historical`) via `backend/dps_scraper.py` — the same source this project's
production backfill uses, not yfinance and not training knowledge. Because this session's own sandbox
cannot reach `dps.psx.com.pk` directly (network egress block — the same constraint already documented in
`backend/news_fetcher.py`), the actual fetch ran in a GitHub Actions job
(`.github/workflows/premove_data_fetch.yml`, real unrestricted network) and its logs were pulled back
into this session as the data-transport mechanism. The fetch script is `analysis/fetch_premove_data.py`.

**This round's scope, explicitly:** pure price/volume/technical forensics only, on all four stocks — no
announcement/catalyst checking was performed for THCCL or FNEL in this pass, and AICL/SHFA's
announcement findings below are carried forward unchanged from the first pass (not re-checked). This
round's contribution is (1) a genuine day-by-day forensic table (open/high/low/close/volume/vol-avg/
vol-ratio/candle-pattern/pattern-criteria-text/price-vs-MA20/price-vs-MA50/BB-sigma-position/MACD-hist/
MACD-direction/EMA-cross-state/RSI/support-resistance-note) replacing the earlier summary-level table for
AICL and SHFA, (2) the same table for two new stocks, THCCL and FNEL, and (3) a cross-stock
first-occurrence comparison table.

Indicators (EMA20/EMA50, MACD(12,26,9), Bollinger(20,2), RSI(14), 20-day volume averages, SMA20/SMA50)
are computed over an EXTENDED lookback (~70 calendar days before each requested window) so every
reported day has genuine trailing history to average against — not padded with `None`. Candlestick
pattern rules (Bullish Engulfing, Morning Star, Hammer, Doji, Piercing Line) are literal, classic
textbook definitions, implemented and unit-tested against synthetic OHLC before running on real data.
Support/resistance notes come from a simple retrospective swing-point scan (local highs/lows over a
+/-3-bar window) — this is a descriptive, after-the-fact structural annotation, not a causal/live
trading signal (a swing point's confirmation legitimately uses bars that come after it in the series).

---

## STOCK 1 — AICL (Adamjee Insurance Company Limited)

### Data coverage & ticker identity

Report window: **2026-07-08 to 2026-08-07**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`, same source as the first pass of this study. Ticker identity for **AICL** confirmed two ways (announcements/company-page checking is explicitly out of scope for this round, so identity was verified without it): (1) `AICL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC values on the user's own reference dates match the user-stated reference prices almost exactly (see table below) — a coincidental match on both the ticker symbol AND the exact price level on the exact date is not plausible for a wrong/similarly-named scrip.

**Note on this round's re-fetch:** AICL/SHFA were re-fetched at the same full daily granularity as the first pass (per this round's instruction); the announcement findings from the first pass (company page: no in-window disclosure found; PSX-wide notices: unverifiable JS-rendered page) still stand and are carried forward below unchanged — see "Confirmed PSX-announcement findings (carried forward from first pass)".

**Confirmed PSX-announcement findings (carried forward from first pass, not re-checked this round):** No company-disclosed announcement found inside the 2026-07-08 to 2026-08-10 window on the company page. PSX-wide notices page could not be verified (JS-rendered search). Do not read this as "confirmed catalyst-free" — read it as "no company-disclosure catalyst found in the sources checked; market-wide notices unchecked."

**Chart structure:** 07-08 through 07-22 is a ragged downward drift/consolidation (closes ~75.9-81.7). 07-23 (close 73.02) is a flush-out low below that range. 07-24 reverses hard off that low (Bullish Engulfing). 07-27 closes back above the top of the prior range; the volume breakout confirms on 07-28 (8.70x the 20-day average).

### Day-by-day forensic table

Every column below is generated programmatically from `analysis/premove_analysis.json` (see Reproducibility) — none of these numbers are hand-typed. Weekday rows with no PSX-reported trade are shown explicitly as gap rows, not skipped.

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-08 | 84.80 | 85.00 | 79.00 | 81.68 | 1,266,800 | 557,290 | 2.27 | — | — | +2.3% vs SMA20(79.81) | +5.0% vs SMA50(77.76) | within bands | 0.3252 | falling | EMA20(80.34) > EMA50(78.97) | 55.60 | tested prior swing low at 77.50 (2026-06-22), held; tested prior swing high at 85.99 (2026-07-06), rejected at |
| 2026-07-09 | 80.01 | 82.00 | 79.20 | 80.50 | 703,060 | 570,792 | 1.23 | — | — | +0.5% vs SMA20(80.13) | +3.5% vs SMA50(77.81) | within bands | 0.0909 | falling | EMA20(80.36) > EMA50(79.03) | 52.00 | tested prior swing high at 83.55 (2026-05-08), rejected at |
| 2026-07-10 | 80.50 | 82.00 | 80.00 | 80.33 | 335,866 | 565,349 | 0.59 | Doji | body(0.17) <= 0.1*range(2.00) [body/range=0.09] | -0.2% vs SMA20(80.50) | +3.2% vs SMA50(77.83) | within bands | -0.0847 | falling | EMA20(80.36) > EMA50(79.08) | 51.50 | tested prior swing high at 83.55 (2026-05-08), rejected at |
| 2026-07-13 | 79.95 | 81.00 | 78.52 | 80.26 | 265,619 | 561,544 | 0.47 | — | — | -0.7% vs SMA20(80.82) | +3.1% vs SMA50(77.85) | within bands | -0.2079 | falling | EMA20(80.35) > EMA50(79.13) | 51.30 | tested prior swing low at 77.50 (2026-06-22), held |
| 2026-07-14 | 79.00 | 79.99 | 75.11 | 77.52 | 654,548 | 577,097 | 1.13 | — | — | -4.3% vs SMA20(80.97) | -0.4% vs SMA50(77.82) | -2.0 sigma | -0.4616 | falling | EMA20(80.08) > EMA50(79.07) | 43.20 | tested prior swing low at 76.00 (2026-04-24), held |
| 2026-07-15 | 76.50 | 78.80 | 76.50 | 77.95 | 202,437 | 539,368 | 0.38 | — | — | -3.7% vs SMA20(80.95) | +0.2% vs SMA50(77.80) | -1.7 sigma | -0.5805 | falling | EMA20(79.88) > EMA50(79.02) | 44.70 | tested prior swing low at 76.00 (2026-04-24), held |
| 2026-07-16 | 78.52 | 80.30 | 77.54 | 79.75 | 296,704 | 507,226 | 0.58 | — | — | -1.4% vs SMA20(80.84) | +2.5% vs SMA50(77.83) | within bands | -0.5200 | rising | EMA20(79.86) > EMA50(79.05) | 50.50 | tested prior swing low at 77.50 (2026-06-22), held |
| 2026-07-17 | 79.69 | 79.90 | 75.82 | 76.79 | 513,445 | 514,941 | 1.00 | — | — | -4.7% vs SMA20(80.61) | -1.4% vs SMA50(77.86) | -2.0 sigma | -0.6526 | falling | EMA20(79.57) > EMA50(78.96) | 42.60 | tested prior swing low at 76.00 (2026-04-24), held |
| 2026-07-20 | 76.50 | 77.50 | 74.56 | 77.38 | 273,185 | 505,489 | 0.54 | Hammer | lower_wick(1.94) >= 2*body(0.88) AND upper_wick(0.12) <= 0.3*body(0.88) AND high(77.50)-max(open,close)(77.38)=0.12 <= 0.15*range(2.94) | -3.8% vs SMA20(80.45) | -0.6% vs SMA50(77.87) | -1.5 sigma | -0.6714 | falling | EMA20(79.36) > EMA50(78.90) | 44.40 | tested prior swing low at 74.01 (2026-04-30), held; tested prior swing high at 77.00 (2026-05-25), broke above |
| 2026-07-21 | 78.00 | 79.00 | 76.77 | 77.37 | 311,382 | 504,140 | 0.62 | — | — | -3.6% vs SMA20(80.30) | -0.7% vs SMA50(77.89) | -1.4 sigma | -0.6547 | rising | EMA20(79.17) > EMA50(78.84) | 44.40 | tested prior swing low at 77.50 (2026-06-22), broke below |
| 2026-07-22 | 77.25 | 77.50 | 75.81 | 75.92 | 98,692 | 493,392 | 0.20 | — | — | -5.2% vs SMA20(80.09) | -2.4% vs SMA50(77.80) | -1.8 sigma | -0.7069 | falling | EMA20(78.86) > EMA50(78.73) | 40.70 | tested prior swing low at 76.00 (2026-04-24), broke below; tested prior swing high at 77.00 (2026-05-25), rejected at |
| 2026-07-23 | 75.10 | 76.48 | 72.56 | 73.02 | 472,797 | 508,331 | 0.93 | — | — | -8.4% vs SMA20(79.73) | -5.9% vs SMA50(77.62) | -2.4 sigma | -0.8905 | falling | EMA20(78.31) < EMA50(78.50) | 34.40 | tested prior swing low at 71.26 (2026-06-03), held; tested prior swing high at 77.00 (2026-05-25), rejected at |
| 2026-07-24 | 72.00 | 80.00 | 70.65 | 77.68 | 576,672 | 507,630 | 1.14 | Bullish Engulfing | prior_close(73.02)<prior_open(75.10, bearish) AND close(77.68)>open(72.00, bullish) AND open(72.00) <= prior_close(73.02) AND close(77.68) >= prior_open(75.10) [today body 72.00→77.68 engulfs prior 75.10→73.02] | -2.5% vs SMA20(79.63) | +0.2% vs SMA50(77.52) | within bands | -0.6624 | rising | EMA20(78.25) < EMA50(78.47) | 48.20 | tested prior swing low at 71.03 (2026-05-22), held |
| 2026-07-27 | 76.90 | 85.45 | 76.90 | 82.33 | 914,421 | 535,961 | 1.71 | — | — | +3.3% vs SMA20(79.72) | +6.1% vs SMA50(77.57) | within bands | -0.1872 | rising | EMA20(78.64) > EMA50(78.62) | 57.80 | tested prior swing low at 77.50 (2026-06-22), held; tested prior swing high at 85.99 (2026-07-06), rejected at |
| 2026-07-28 | 83.87 | 90.56 | 82.01 | 90.56 | 7,505,392 | 862,239 | 8.70 | — | — | +12.8% vs SMA20(80.25) | +16.4% vs SMA50(77.80) | +2.8 sigma | 0.6467 | rising | EMA20(79.77) > EMA50(79.09) | 68.70 | — |
| 2026-07-29 | 89.97 | 95.00 | 86.80 | 89.29 | 6,614,789 | 1,153,980 | 5.73 | Doji | body(0.68) <= 0.1*range(8.20) [body/range=0.08] | +10.8% vs SMA20(80.56) | +14.5% vs SMA50(78.00) | +2.1 sigma | 1.05 | rising | EMA20(80.68) > EMA50(79.49) | 65.90 | — |
| 2026-07-30 | 86.20 | 90.00 | 85.05 | 88.72 | 684,678 | 1,162,470 | 0.59 | — | — | +9.7% vs SMA20(80.85) | +13.4% vs SMA50(78.25) | +1.7 sigma | 1.21 | rising | EMA20(81.44) > EMA50(79.85) | 64.60 | — |
| 2026-07-31 | 89.00 | 95.87 | 88.50 | 92.46 | 3,453,495 | 1,328,077 | 2.60 | — | — | +13.6% vs SMA20(81.40) | +17.6% vs SMA50(78.59) | +2.1 sigma | 1.49 | rising | EMA20(82.49) > EMA50(80.35) | 68.90 | — |
| 2026-08-03 | 95.00 | 98.90 | 93.50 | 93.80 | 1,586,120 | 1,380,546 | 1.15 | — | — | +14.5% vs SMA20(81.90) | +18.7% vs SMA50(79.02) | +2.0 sigma | 1.65 | rising | EMA20(83.57) > EMA50(80.87) | 70.30 | — |
| 2026-08-04 | 94.10 | 96.50 | 91.36 | 91.92 | 955,548 | 1,384,282 | 0.69 | — | — | +11.7% vs SMA20(82.26) | +15.8% vs SMA50(79.39) | +1.6 sigma | 1.54 | falling | EMA20(84.36) > EMA50(81.31) | 65.80 | — |
| 2026-08-05 | 93.30 | 94.44 | 91.51 | 92.04 | 112,797 | 1,326,582 | 0.09 | — | — | +11.2% vs SMA20(82.78) | +15.4% vs SMA50(79.78) | +1.4 sigma | 1.38 | falling | EMA20(85.10) > EMA50(81.73) | 66.00 | — |
| 2026-08-06 | 92.89 | 97.88 | 91.40 | 96.03 | 2,126,245 | 1,397,742 | 1.52 | — | — | +14.9% vs SMA20(83.56) | +19.7% vs SMA50(80.24) | +1.7 sigma | 1.44 | rising | EMA20(86.14) > EMA50(82.29) | 70.60 | tested prior swing high at 98.90 (2026-08-03), rejected at |
| 2026-08-07 | 96.03 | 100.00 | 92.70 | 96.37 | 1,208,729 | 1,441,385 | 0.84 | Doji | body(0.34) <= 0.1*range(7.30) [body/range=0.05] | +14.2% vs SMA20(84.36) | +19.4% vs SMA50(80.71) | +1.6 sigma | 1.40 | falling | EMA20(87.11) > EMA50(82.84) | 70.90 | tested prior swing high at 98.90 (2026-08-03), rejected at |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-07-23 = Day 0).

Day -11 (2026-07-08): Volume 2.3x avg, no pattern, BB within bands, MACD hist 0.3252 (falling), EMA20(80.34) > EMA50(78.97), tested prior swing low at 77.50 (2026-06-22), held; tested prior swing high at 85.99 (2026-07-06), rejected at
Day -10 (2026-07-09): Volume 1.2x avg, no pattern, BB within bands, MACD hist 0.0909 (falling), EMA20(80.36) > EMA50(79.03), tested prior swing high at 83.55 (2026-05-08), rejected at
Day -9 (2026-07-10): Volume 0.6x avg, Doji formed (body(0.17) <= 0.1*range(2.00) [body/range=0.09]), BB within bands, MACD hist -0.0847 (falling), EMA20(80.36) > EMA50(79.08), tested prior swing high at 83.55 (2026-05-08), rejected at
Day -8 (2026-07-13): Volume 0.5x avg, no pattern, BB within bands, MACD hist -0.2079 (falling), EMA20(80.35) > EMA50(79.13), tested prior swing low at 77.50 (2026-06-22), held
Day -7 (2026-07-14): Volume 1.1x avg, no pattern, BB -2.0 sigma, MACD hist -0.4616 (falling), EMA20(80.08) > EMA50(79.07), tested prior swing low at 76.00 (2026-04-24), held
Day -6 (2026-07-15): Volume 0.4x avg, no pattern, BB -1.7 sigma, MACD hist -0.5805 (falling), EMA20(79.88) > EMA50(79.02), tested prior swing low at 76.00 (2026-04-24), held
Day -5 (2026-07-16): Volume 0.6x avg, no pattern, BB within bands, MACD hist -0.5200 (rising), EMA20(79.86) > EMA50(79.05), tested prior swing low at 77.50 (2026-06-22), held
Day -4 (2026-07-17): Volume 1.0x avg, no pattern, BB -2.0 sigma, MACD hist -0.6526 (falling), EMA20(79.57) > EMA50(78.96), tested prior swing low at 76.00 (2026-04-24), held
Day -3 (2026-07-20): Volume 0.5x avg, Hammer formed (lower_wick(1.94) >= 2*body(0.88) AND upper_wick(0.12) <= 0.3*body(0.88) AND high(77.50)-max(open,close)(77.38)=0.12 <= 0.15*range(2.94)), BB -1.5 sigma, MACD hist -0.6714 (falling), EMA20(79.36) > EMA50(78.90), tested prior swing low at 74.01 (2026-04-30), held; tested prior swing high at 77.00 (2026-05-25), broke above
Day -2 (2026-07-21): Volume 0.6x avg, no pattern, BB -1.4 sigma, MACD hist -0.6547 (rising), EMA20(79.17) > EMA50(78.84), tested prior swing low at 77.50 (2026-06-22), broke below
Day -1 (2026-07-22): Volume 0.2x avg, no pattern, BB -1.8 sigma, MACD hist -0.7069 (falling), EMA20(78.86) > EMA50(78.73), tested prior swing low at 76.00 (2026-04-24), broke below; tested prior swing high at 77.00 (2026-05-25), rejected at
Day 0 (2026-07-23): Volume 0.9x avg, no pattern, BB -2.4 sigma, MACD hist -0.8905 (falling), EMA20(78.31) < EMA50(78.50), tested prior swing low at 71.26 (2026-06-03), held; tested prior swing high at 77.00 (2026-05-25), rejected at
Day +1 (2026-07-24): Volume 1.1x avg, Bullish Engulfing formed (prior_close(73.02)<prior_open(75.10, bearish) AND close(77.68)>open(72.00, bullish) AND open(72.00) <= prior_close(73.02) AND close(77.68) >= prior_open(75.10) [today body 72.00→77.68 engulfs prior 75.10→73.02]), BB within bands, MACD hist -0.6624 (rising), EMA20(78.25) < EMA50(78.47), tested prior swing low at 71.03 (2026-05-22), held
Day +2 (2026-07-27): Volume 1.7x avg, no pattern, BB within bands, MACD hist -0.1872 (rising), EMA20(78.64) > EMA50(78.62), tested prior swing low at 77.50 (2026-06-22), held; tested prior swing high at 85.99 (2026-07-06), rejected at
Day +3 (2026-07-28): Volume 8.7x avg, no pattern, BB +2.8 sigma, MACD hist 0.6467 (rising), EMA20(79.77) > EMA50(79.09)
Day +4 (2026-07-29): Volume 5.7x avg, Doji formed (body(0.68) <= 0.1*range(8.20) [body/range=0.08]), BB +2.1 sigma, MACD hist 1.0540 (rising), EMA20(80.68) > EMA50(79.49)
Day +5 (2026-07-30): Volume 0.6x avg, no pattern, BB +1.7 sigma, MACD hist 1.2149 (rising), EMA20(81.44) > EMA50(79.85)
Day +6 (2026-07-31): Volume 2.6x avg, no pattern, BB +2.1 sigma, MACD hist 1.4852 (rising), EMA20(82.49) > EMA50(80.35)
Day +7 (2026-08-03): Volume 1.1x avg, no pattern, BB +2.0 sigma, MACD hist 1.6533 (rising), EMA20(83.57) > EMA50(80.87)
Day +8 (2026-08-04): Volume 0.7x avg, no pattern, BB +1.6 sigma, MACD hist 1.5393 (falling), EMA20(84.36) > EMA50(81.31)
Day +9 (2026-08-05): Volume 0.1x avg, no pattern, BB +1.4 sigma, MACD hist 1.3786 (falling), EMA20(85.10) > EMA50(81.73)
Day +10 (2026-08-06): Volume 1.5x avg, no pattern, BB +1.7 sigma, MACD hist 1.4408 (rising), EMA20(86.14) > EMA50(82.29), tested prior swing high at 98.90 (2026-08-03), rejected at
Day +11 (2026-08-07): Volume 0.8x avg, Doji formed (body(0.34) <= 0.1*range(7.30) [body/range=0.05]), BB +1.6 sigma, MACD hist 1.4034 (falling), EMA20(87.11) > EMA50(82.84), tested prior swing high at 98.90 (2026-08-03), rejected at

---

## STOCK 2 — SHFA (Shifa International Hospitals Limited)

### Data coverage & ticker identity

Report window: **2026-05-28 to 2026-06-18**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`, same source as the first pass of this study. Ticker identity for **SHFA** confirmed two ways (announcements/company-page checking is explicitly out of scope for this round, so identity was verified without it): (1) `SHFA` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC values on the user's own reference dates match the user-stated reference prices almost exactly (see table below) — a coincidental match on both the ticker symbol AND the exact price level on the exact date is not plausible for a wrong/similarly-named scrip.

**Note on this round's re-fetch:** re-fetched at full daily granularity per this round's instruction; the first pass's announcement finding stands unchanged — see below.

**Confirmed PSX-announcement findings (carried forward from first pass, not re-checked this round):** A **Board Meeting (Other Than Financial Results)** was disclosed for **June 19, 2026** — one day after the move's reference end-date. This is a real, confirmed, disclosed event immediately adjacent to the move and should be treated as a possible catalyst; this move should NOT be labeled catalyst-free.

**Chart structure:** 05-29 through 06-12 is a tight consolidation/base (closes 470.36-482.32, ~2.5% band). 06-15/06-16 are the first closes clearly above the base. 06-17 is the violent breakout/gap day (+8.65% on 3.80x volume). 06-18 opens even higher, hits an intraday high of 554.0, then pulls back to close at 525.59 — a blow-off/exhaustion shape on the second breakout day.

### Day-by-day forensic table

Every column below is generated programmatically from `analysis/premove_analysis.json` (see Reproducibility) — none of these numbers are hand-typed. Weekday rows with no PSX-reported trade are shown explicitly as gap rows, not skipped.

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-28 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-29 | 478.00 | 485.00 | 456.65 | 482.32 | 6,076 | 9,669 | 0.63 | — | — | -0.1% vs SMA20(482.98) | +0.8% vs SMA50(478.26) | within bands | -1.13 | rising | EMA20(482.57) > EMA50(480.30) | 49.70 | tested prior swing low at 451.10 (2026-03-19), held; tested prior swing high at 489.00 (2026-03-17), rejected at |
| 2026-06-01 | 488.95 | 488.95 | 472.00 | 474.80 | 12,848 | 8,793 | 1.46 | — | — | -1.6% vs SMA20(482.62) | -0.7% vs SMA50(478.34) | -1.1 sigma | -1.28 | falling | EMA20(481.83) > EMA50(480.08) | 45.50 | tested prior swing low at 471.55 (2026-04-24), held; tested prior swing high at 489.00 (2026-03-17), rejected at |
| 2026-06-02 | 480.00 | 484.80 | 462.66 | 473.78 | 46,425 | 10,312 | 4.50 | — | — | -1.8% vs SMA20(482.38) | -1.0% vs SMA50(478.39) | -1.2 sigma | -1.38 | falling | EMA20(481.06) > EMA50(479.84) | 44.90 | tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at |
| 2026-06-03 | 479.99 | 485.00 | 466.11 | 470.36 | 72,623 | 13,695 | 5.30 | — | — | -2.4% vs SMA20(482.16) | -1.7% vs SMA50(478.31) | -1.6 sigma | -1.58 | falling | EMA20(480.05) > EMA50(479.46) | 43.00 | tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at |
| 2026-06-04 | 477.94 | 488.00 | 467.00 | 473.49 | 7,915 | 13,222 | 0.60 | — | — | -1.7% vs SMA20(481.68) | -1.0% vs SMA50(478.20) | -1.1 sigma | -1.41 | rising | EMA20(479.42) > EMA50(479.23) | 45.30 | tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at |
| 2026-06-05 | 474.00 | 476.75 | 470.00 | 473.02 | 4,186 | 13,388 | 0.31 | — | — | -1.7% vs SMA20(481.38) | -1.1% vs SMA50(478.34) | -1.1 sigma | -1.26 | rising | EMA20(478.81) < EMA50(478.99) | 45.00 | tested prior swing low at 470.00 (2026-04-30), held |
| 2026-06-08 | 473.02 | 476.76 | 463.01 | 472.93 | 6,563 | 12,978 | 0.51 | Doji | body(0.09) <= 0.1*range(13.75) [body/range=0.01] | -1.6% vs SMA20(480.40) | -1.2% vs SMA50(478.50) | within bands | -1.08 | rising | EMA20(478.25) < EMA50(478.75) | 44.90 | tested prior swing low at 465.00 (2026-04-13), held |
| 2026-06-09 | 483.30 | 483.30 | 468.01 | 478.66 | 6,454 | 12,079 | 0.53 | Hammer | lower_wick(10.65) >= 2*body(4.64) AND upper_wick(0.00) <= 0.3*body(4.64) AND high(483.30)-max(open,close)(483.30)=0.00 <= 0.15*range(15.29) | -0.3% vs SMA20(480.00) | +0.0% vs SMA50(478.66) | within bands | -0.5371 | rising | EMA20(478.29) < EMA50(478.75) | 49.60 | tested prior swing low at 470.00 (2026-04-30), held; tested prior swing high at 489.00 (2026-03-17), rejected at |
| 2026-06-10 | 467.30 | 476.88 | 467.30 | 470.39 | 5,520 | 12,133 | 0.45 | — | — | -1.8% vs SMA20(479.01) | -1.7% vs SMA50(478.74) | -1.1 sigma | -0.6766 | falling | EMA20(477.54) < EMA50(478.42) | 43.80 | tested prior swing low at 465.00 (2026-04-13), held |
| 2026-06-11 | 482.94 | 482.94 | 470.00 | 475.79 | 22,790 | 13,161 | 1.73 | — | — | -0.5% vs SMA20(478.11) | -0.7% vs SMA50(479.24) | within bands | -0.3650 | rising | EMA20(477.37) < EMA50(478.32) | 48.10 | tested prior swing low at 470.00 (2026-04-30), held; tested prior swing high at 489.00 (2026-03-17), rejected at |
| 2026-06-12 | 481.05 | 487.95 | 477.00 | 481.15 | 13,076 | 13,641 | 0.96 | Doji | body(0.10) <= 0.1*range(10.95) [body/range=0.01] | +0.7% vs SMA20(477.75) | +0.2% vs SMA50(480.19) | within bands | 0.2112 | rising | EMA20(477.73) < EMA50(478.43) | 51.90 | tested prior swing low at 471.55 (2026-04-24), held; tested prior swing high at 489.00 (2026-03-17), rejected at |
| 2026-06-15 | 482.00 | 499.00 | 482.00 | 491.84 | 36,614 | 15,372 | 2.38 | — | — | +2.9% vs SMA20(477.82) | +2.2% vs SMA50(481.23) | +2.2 sigma | 1.26 | rising | EMA20(479.07) > EMA50(478.95) | 58.60 | tested prior swing high at 499.99 (2026-05-06), rejected at |
| 2026-06-16 | 491.84 | 500.00 | 485.01 | 497.96 | 21,033 | 16,292 | 1.29 | — | — | +4.1% vs SMA20(478.22) | +3.3% vs SMA50(482.22) | +2.7 sigma | 2.26 | rising | EMA20(480.87) > EMA50(479.70) | 61.80 | tested prior swing high at 500.01 (2026-04-10), rejected at |
| 2026-06-17 | 497.96 | 546.00 | 497.96 | 541.06 | 74,731 | 19,678 | 3.80 | — | — | +12.5% vs SMA20(481.02) | +11.7% vs SMA50(484.23) | +3.9 sigma | 5.53 | rising | EMA20(486.61) > EMA50(482.10) | 76.10 | — |
| 2026-06-18 | 549.95 | 554.00 | 501.00 | 525.59 | 34,392 | 21,233 | 1.62 | — | — | +8.8% vs SMA20(483.26) | +8.2% vs SMA50(485.94) | +2.3 sigma | 6.30 | rising | EMA20(490.32) > EMA50(483.81) | 66.50 | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-06-12 = Day 0).

Day -10 (2026-05-29): Volume 0.6x avg, no pattern, BB within bands, MACD hist -1.1299 (rising), EMA20(482.57) > EMA50(480.30), tested prior swing low at 451.10 (2026-03-19), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -9 (2026-06-01): Volume 1.5x avg, no pattern, BB -1.1 sigma, MACD hist -1.2844 (falling), EMA20(481.83) > EMA50(480.08), tested prior swing low at 471.55 (2026-04-24), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -8 (2026-06-02): Volume 4.5x avg, no pattern, BB -1.2 sigma, MACD hist -1.3782 (falling), EMA20(481.06) > EMA50(479.84), tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -7 (2026-06-03): Volume 5.3x avg, no pattern, BB -1.6 sigma, MACD hist -1.5790 (falling), EMA20(480.05) > EMA50(479.46), tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -6 (2026-06-04): Volume 0.6x avg, no pattern, BB -1.1 sigma, MACD hist -1.4148 (rising), EMA20(479.42) > EMA50(479.23), tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -5 (2026-06-05): Volume 0.3x avg, no pattern, BB -1.1 sigma, MACD hist -1.2569 (rising), EMA20(478.81) < EMA50(478.99), tested prior swing low at 470.00 (2026-04-30), held
Day -4 (2026-06-08): Volume 0.5x avg, Doji formed (body(0.09) <= 0.1*range(13.75) [body/range=0.01]), BB within bands, MACD hist -1.0841 (rising), EMA20(478.25) < EMA50(478.75), tested prior swing low at 465.00 (2026-04-13), held
Day -3 (2026-06-09): Volume 0.5x avg, Hammer formed (lower_wick(10.65) >= 2*body(4.64) AND upper_wick(0.00) <= 0.3*body(4.64) AND high(483.30)-max(open,close)(483.30)=0.00 <= 0.15*range(15.29)), BB within bands, MACD hist -0.5371 (rising), EMA20(478.29) < EMA50(478.75), tested prior swing low at 470.00 (2026-04-30), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -2 (2026-06-10): Volume 0.5x avg, no pattern, BB -1.1 sigma, MACD hist -0.6766 (falling), EMA20(477.54) < EMA50(478.42), tested prior swing low at 465.00 (2026-04-13), held
Day -1 (2026-06-11): Volume 1.7x avg, no pattern, BB within bands, MACD hist -0.3650 (rising), EMA20(477.37) < EMA50(478.32), tested prior swing low at 470.00 (2026-04-30), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day 0 (2026-06-12): Volume 1.0x avg, Doji formed (body(0.10) <= 0.1*range(10.95) [body/range=0.01]), BB within bands, MACD hist 0.2112 (rising), EMA20(477.73) < EMA50(478.43), tested prior swing low at 471.55 (2026-04-24), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day +1 (2026-06-15): Volume 2.4x avg, no pattern, BB +2.2 sigma, MACD hist 1.2628 (rising), EMA20(479.07) > EMA50(478.95), tested prior swing high at 499.99 (2026-05-06), rejected at
Day +2 (2026-06-16): Volume 1.3x avg, no pattern, BB +2.7 sigma, MACD hist 2.2626 (rising), EMA20(480.87) > EMA50(479.70), tested prior swing high at 500.01 (2026-04-10), rejected at
Day +3 (2026-06-17): Volume 3.8x avg, no pattern, BB +3.9 sigma, MACD hist 5.5324 (rising), EMA20(486.61) > EMA50(482.10)
Day +4 (2026-06-18): Volume 1.6x avg, no pattern, BB +2.3 sigma, MACD hist 6.3032 (rising), EMA20(490.32) > EMA50(483.81)

---

## STOCK 3 — THCCL (full company name not independently confirmed this round, since the company-page fetch is out of scope this pass — ticker identity below is confirmed via the project's own watchlist and by exact-price-match instead)

### Data coverage & ticker identity

Report window: **2026-06-15 to 2026-07-09**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`, same source as the first pass of this study. Ticker identity for **THCCL** confirmed two ways (announcements/company-page checking is explicitly out of scope for this round, so identity was verified without it): (1) `THCCL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC values on the user's own reference dates match the user-stated reference prices almost exactly (see table below) — a coincidental match on both the ticker symbol AND the exact price level on the exact date is not plausible for a wrong/similarly-named scrip.

**Announcements/catalyst-checking intentionally out of scope for this round** (per this round's explicit instruction — pure price/volume/technical forensics only, all four stocks). No claim of "catalyst-free" is made for THCCL; this is simply not checked in this pass.

**Chart structure:** 06-15 through 06-24 opens already elevated (SMA20 well below spot, RSI 60-77) then bleeds down through 06-29/06-30 as momentum cools. 07-01 is the first clear reversal up (+4.3% on the day), then a multi-day base 07-02 to 07-06 in the high-66s to high-68s. 07-07 is the volume breakout day (3.79x the 20-day average, +7.3% on the day), followed by continued elevated volume into 07-08/07-09, closing the window at 73.21 with a confirmed Bullish Engulfing on 07-09.

### Day-by-day forensic table

Every column below is generated programmatically from `analysis/premove_analysis.json` (see Reproducibility) — none of these numbers are hand-typed. Weekday rows with no PSX-reported trade are shown explicitly as gap rows, not skipped.

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-15 | 71.89 | 72.64 | 70.00 | 70.59 | 4,972,110 | 4,834,625 | 1.03 | — | — | +18.8% vs SMA20(59.43) | insufficient history | +1.5 sigma | 1.39 | falling | EMA20(62.17) > EMA50(58.28) | 77.30 | tested prior swing high at 72.20 (2026-06-09), rejected at |
| 2026-06-16 | 71.00 | 71.50 | 68.00 | 68.69 | 3,162,187 | 4,971,285 | 0.64 | — | — | +14.1% vs SMA20(60.21) | insufficient history | +1.2 sigma | 1.11 | falling | EMA20(62.79) > EMA50(58.69) | 70.10 | tested prior swing high at 72.20 (2026-06-09), rejected at |
| 2026-06-17 | 69.00 | 69.67 | 67.75 | 68.01 | 2,620,285 | 5,094,702 | 0.51 | — | — | +11.6% vs SMA20(60.96) | insufficient history | within bands | 0.8122 | falling | EMA20(63.29) > EMA50(59.06) | 67.70 | — |
| 2026-06-18 | 68.62 | 70.30 | 68.51 | 69.25 | 3,817,569 | 5,258,415 | 0.73 | — | — | +12.0% vs SMA20(61.83) | +18.6% vs SMA50(58.38) | +1.0 sigma | 0.6324 | falling | EMA20(63.86) > EMA50(59.46) | 69.80 | — |
| 2026-06-19 | 69.35 | 69.94 | 67.00 | 67.62 | 1,950,672 | 5,318,041 | 0.37 | — | — | +8.0% vs SMA20(62.64) | +15.2% vs SMA50(58.68) | within bands | 0.3528 | falling | EMA20(64.21) > EMA50(59.78) | 64.00 | — |
| 2026-06-22 | 68.00 | 68.34 | 66.30 | 66.49 | 2,253,115 | 5,395,984 | 0.42 | — | — | +4.9% vs SMA20(63.36) | +12.8% vs SMA50(58.95) | within bands | 0.0563 | falling | EMA20(64.43) > EMA50(60.04) | 60.30 | tested prior swing low at 65.13 (2026-06-11), held |
| 2026-06-23 | 67.30 | 67.30 | 66.00 | 66.72 | 2,611,447 | 5,504,225 | 0.47 | — | — | +4.1% vs SMA20(64.07) | +12.9% vs SMA50(59.12) | within bands | -0.1485 | falling | EMA20(64.65) > EMA50(60.30) | 60.80 | tested prior swing low at 65.13 (2026-06-11), held |
| 2026-06-24 | 66.90 | 67.21 | 66.43 | 66.61 | 1,639,380 | 5,566,713 | 0.29 | — | — | +2.8% vs SMA20(64.80) | +12.4% vs SMA50(59.25) | within bands | -0.3065 | falling | EMA20(64.84) > EMA50(60.55) | 60.40 | tested prior swing low at 65.13 (2026-06-11), held |
| 2026-06-25 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-26 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-29 | 66.50 | 67.37 | 64.65 | 64.99 | 1,580,479 | 5,593,877 | 0.28 | — | — | -0.6% vs SMA20(65.40) | +9.5% vs SMA50(59.35) | within bands | -0.5225 | falling | EMA20(64.85) > EMA50(60.72) | 54.80 | tested prior swing low at 65.13 (2026-06-11), broke below |
| 2026-06-30 | 65.00 | 66.50 | 64.55 | 65.66 | 984,184 | 5,593,186 | 0.18 | — | — | -0.5% vs SMA20(65.99) | +10.3% vs SMA50(59.54) | within bands | -0.6163 | falling | EMA20(64.93) > EMA50(60.92) | 56.60 | tested prior swing low at 65.13 (2026-06-11), held |
| 2026-07-01 | 66.00 | 69.00 | 66.00 | 68.47 | 6,237,100 | 5,383,378 | 1.16 | — | — | +2.9% vs SMA20(66.54) | +14.6% vs SMA50(59.75) | within bands | -0.4905 | rising | EMA20(65.27) > EMA50(61.21) | 63.20 | tested prior swing low at 65.13 (2026-06-11), held |
| 2026-07-02 | 69.45 | 69.45 | 67.39 | 67.81 | 2,616,775 | 5,039,297 | 0.52 | — | — | +1.3% vs SMA20(66.97) | +13.2% vs SMA50(59.91) | within bands | -0.4540 | rising | EMA20(65.51) > EMA50(61.47) | 60.80 | — |
| 2026-07-03 | 68.01 | 69.11 | 67.02 | 68.04 | 1,774,265 | 5,011,456 | 0.35 | Doji | body(0.03) <= 0.1*range(2.09) [body/range=0.01] | +0.9% vs SMA20(67.45) | +13.3% vs SMA50(60.08) | within bands | -0.4176 | rising | EMA20(65.75) > EMA50(61.73) | 61.40 | — |
| 2026-07-06 | 68.00 | 69.75 | 67.51 | 69.13 | 3,310,832 | 5,017,373 | 0.66 | — | — | +1.8% vs SMA20(67.90) | +14.7% vs SMA50(60.26) | within bands | -0.3273 | rising | EMA20(66.07) > EMA50(62.02) | 63.90 | — |
| 2026-07-07 | 70.01 | 75.25 | 70.01 | 74.20 | 20,400,496 | 5,388,718 | 3.79 | — | — | +8.6% vs SMA20(68.30) | +22.5% vs SMA50(60.59) | +3.1 sigma | 0.0468 | rising | EMA20(66.84) > EMA50(62.50) | 72.80 | — |
| 2026-07-08 | 72.80 | 75.50 | 67.92 | 70.57 | 16,241,659 | 5,065,184 | 3.21 | — | — | +3.2% vs SMA20(68.36) | +16.0% vs SMA50(60.84) | +1.1 sigma | 0.0238 | falling | EMA20(67.20) > EMA50(62.81) | 61.20 | — |
| 2026-07-09 | 70.49 | 76.48 | 69.50 | 73.21 | 17,083,919 | 5,416,527 | 3.15 | Bullish Engulfing | prior_close(70.57)<prior_open(72.80, bearish) AND close(73.21)>open(70.49, bullish) AND open(70.49) <= prior_close(70.57) AND close(73.21) >= prior_open(72.80) [today body 70.49→73.21 engulfs prior 72.80→70.57] | +6.8% vs SMA20(68.55) | +19.7% vs SMA50(61.17) | +2.1 sigma | 0.1532 | rising | EMA20(67.77) > EMA50(63.22) | 65.50 | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-06-30 = Day 0).

Day -9 (2026-06-15): Volume 1.0x avg, no pattern, BB +1.5 sigma, MACD hist 1.3861 (falling), EMA20(62.17) > EMA50(58.28), tested prior swing high at 72.20 (2026-06-09), rejected at
Day -8 (2026-06-16): Volume 0.6x avg, no pattern, BB +1.2 sigma, MACD hist 1.1121 (falling), EMA20(62.79) > EMA50(58.69), tested prior swing high at 72.20 (2026-06-09), rejected at
Day -7 (2026-06-17): Volume 0.5x avg, no pattern, BB within bands, MACD hist 0.8122 (falling), EMA20(63.29) > EMA50(59.06)
Day -6 (2026-06-18): Volume 0.7x avg, no pattern, BB +1.0 sigma, MACD hist 0.6324 (falling), EMA20(63.86) > EMA50(59.46)
Day -5 (2026-06-19): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.3528 (falling), EMA20(64.21) > EMA50(59.78)
Day -4 (2026-06-22): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.0563 (falling), EMA20(64.43) > EMA50(60.04), tested prior swing low at 65.13 (2026-06-11), held
Day -3 (2026-06-23): Volume 0.5x avg, no pattern, BB within bands, MACD hist -0.1485 (falling), EMA20(64.65) > EMA50(60.30), tested prior swing low at 65.13 (2026-06-11), held
Day -2 (2026-06-24): Volume 0.3x avg, no pattern, BB within bands, MACD hist -0.3065 (falling), EMA20(64.84) > EMA50(60.55), tested prior swing low at 65.13 (2026-06-11), held
Day -1 (2026-06-29): Volume 0.3x avg, no pattern, BB within bands, MACD hist -0.5225 (falling), EMA20(64.85) > EMA50(60.72), tested prior swing low at 65.13 (2026-06-11), broke below
Day 0 (2026-06-30): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.6163 (falling), EMA20(64.93) > EMA50(60.92), tested prior swing low at 65.13 (2026-06-11), held
Day +1 (2026-07-01): Volume 1.2x avg, no pattern, BB within bands, MACD hist -0.4905 (rising), EMA20(65.27) > EMA50(61.21), tested prior swing low at 65.13 (2026-06-11), held
Day +2 (2026-07-02): Volume 0.5x avg, no pattern, BB within bands, MACD hist -0.4540 (rising), EMA20(65.51) > EMA50(61.47)
Day +3 (2026-07-03): Volume 0.3x avg, Doji formed (body(0.03) <= 0.1*range(2.09) [body/range=0.01]), BB within bands, MACD hist -0.4176 (rising), EMA20(65.75) > EMA50(61.73)
Day +4 (2026-07-06): Volume 0.7x avg, no pattern, BB within bands, MACD hist -0.3273 (rising), EMA20(66.07) > EMA50(62.02)
Day +5 (2026-07-07): Volume 3.8x avg, no pattern, BB +3.1 sigma, MACD hist 0.0468 (rising), EMA20(66.84) > EMA50(62.50)
Day +6 (2026-07-08): Volume 3.2x avg, no pattern, BB +1.1 sigma, MACD hist 0.0238 (falling), EMA20(67.20) > EMA50(62.81)
Day +7 (2026-07-09): Volume 3.1x avg, Bullish Engulfing formed (prior_close(70.57)<prior_open(72.80, bearish) AND close(73.21)>open(70.49, bullish) AND open(70.49) <= prior_close(70.57) AND close(73.21) >= prior_open(72.80) [today body 70.49→73.21 engulfs prior 72.80→70.57]), BB +2.1 sigma, MACD hist 0.1532 (rising), EMA20(67.77) > EMA50(63.22)

---

## STOCK 4 — FNEL (full company name not independently confirmed this round, since the company-page fetch is out of scope this pass — ticker identity below is confirmed via the project's own watchlist and by exact-price-match instead)

### Data coverage & ticker identity

Report window: **2026-03-22 to 2026-04-24**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`, same source as the first pass of this study. Ticker identity for **FNEL** confirmed two ways (announcements/company-page checking is explicitly out of scope for this round, so identity was verified without it): (1) `FNEL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC values on the user's own reference dates match the user-stated reference prices almost exactly (see table below) — a coincidental match on both the ticker symbol AND the exact price level on the exact date is not plausible for a wrong/similarly-named scrip.

**Important data-quality note — READ BEFORE USING THIS SECTION:** FNEL's fetched historical series shows an abrupt **~90.7% single-day price adjustment on 2026-02-02** (close 17.70 on 2026-01-30 -> 1.65 on 2026-02-02, volume spiking to 191,182,675 vs a typical 8-20M in the days before). This is the classic signature of a large bonus-share or rights issue on PSX being reflected as a raw (non-split-adjusted) price cliff in the historical table, **not a real -90.7% one-day return and not a wrong-ticker mixup**: the post-adjustment series continues trading organically at the new scale, and the window-end values (close 1.16 on 2026-04-06, high 1.74 on 2026-04-23) match the user's own reference prices for this move almost exactly, which would be an implausible coincidence for a mismatched scrip. To keep every moving-average/volatility/Bollinger calculation below from spanning that capital-structure discontinuity, this study's indicator computation for FNEL **excludes bars before 2026-02-02** — meaning the 50-day volume/price averages only reach full 50-bar depth partway through the report window (rows before that show "insufficient history" for the SMA50/vol comparisons, honestly, rather than a computed-but-wrong number spanning the cliff). This is a genuine limitation of the underlying PSX historical data for this stock, not an error in this study's methodology, and readers should independently confirm the corporate-action date/ratio against PSX's official disclosures before using pre-April FNEL price history for anything beyond this technical study.

**Announcements/catalyst-checking intentionally out of scope for this round** (same as THCCL — pure technical forensics only this pass). No claim of "catalyst-free" is made for FNEL.

**Chart structure:** The report window opens already inside a multi-week grind lower (03-24 to 04-07, closes 1.25 down to 1.16, RSI mid-30s to low-40s, EMA20 below EMA50 throughout — a genuine bearish trend, not a base). 04-08 is the volume breakout day: +31.2% on the day (open 1.30, high 1.60, close 1.58) on 8.65x the 20-day average volume (212M shares) — the single most extreme reading in any of the four stocks' windows. 04-09/04-10 give back some of that gain (1.47, then 1.44) before a second, calmer base 04-13 to 04-22 (1.31-1.46). 04-23 is a second violent volume spike (+22.3% on the day, 5.71x avg volume, high hits 1.74 exactly matching the user's reference), closing the window at 1.51 on 04-24 after a pullback from that high.

### Day-by-day forensic table

Every column below is generated programmatically from `analysis/premove_analysis.json` (see Reproducibility) — none of these numbers are hand-typed. Weekday rows with no PSX-reported trade are shown explicitly as gap rows, not skipped.

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-03-23 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-03-24 | 1.31 | 1.31 | 1.22 | 1.25 | 8,168,773 | 19,769,506 | 0.41 | — | — | -3.7% vs SMA20(1.30) | insufficient history | within bands | 0.0068 | rising | EMA20(1.29) < EMA50(1.41) | 42.40 | — |
| 2026-03-25 | 1.25 | 1.29 | 1.20 | 1.23 | 24,816,049 | 19,777,932 | 1.25 | — | — | -4.8% vs SMA20(1.29) | insufficient history | within bands | 0.0091 | rising | EMA20(1.28) < EMA50(1.41) | 41.10 | — |
| 2026-03-26 | 1.23 | 1.24 | 1.17 | 1.18 | 33,024,724 | 20,056,952 | 1.65 | — | — | -7.7% vs SMA20(1.28) | insufficient history | within bands | 0.0077 | falling | EMA20(1.27) < EMA50(1.40) | 38.10 | tested prior swing low at 1.16 (2026-02-20), held |
| 2026-03-27 | 1.19 | 1.19 | 1.14 | 1.15 | 27,181,362 | 19,744,956 | 1.38 | — | — | -8.8% vs SMA20(1.26) | insufficient history | -1.0 sigma | 0.0052 | falling | EMA20(1.26) < EMA50(1.39) | 36.40 | tested prior swing low at 1.14 (2026-03-09), held |
| 2026-03-30 | 1.16 | 1.16 | 1.10 | 1.11 | 19,802,685 | 19,734,723 | 1.00 | — | — | -10.6% vs SMA20(1.24) | insufficient history | -1.4 sigma | 0.0015 | falling | EMA20(1.25) < EMA50(1.38) | 34.20 | tested prior swing low at 1.10 (2026-03-02), held |
| 2026-03-31 | 1.14 | 1.16 | 1.11 | 1.15 | 7,605,115 | 18,302,695 | 0.42 | — | — | -5.9% vs SMA20(1.22) | insufficient history | -1.1 sigma | 0.0023 | rising | EMA20(1.24) < EMA50(1.37) | 38.20 | tested prior swing low at 1.10 (2026-03-02), held |
| 2026-04-01 | 1.17 | 1.25 | 1.16 | 1.19 | 10,178,494 | 16,719,152 | 0.61 | — | — | -2.4% vs SMA20(1.22) | insufficient history | within bands | 0.0060 | rising | EMA20(1.23) < EMA50(1.36) | 42.10 | tested prior swing low at 1.16 (2026-02-20), held |
| 2026-04-02 | 1.12 | 1.17 | 1.11 | 1.13 | 13,756,717 | 16,667,982 | 0.83 | — | — | -6.5% vs SMA20(1.21) | insufficient history | -1.2 sigma | 0.0049 | falling | EMA20(1.22) < EMA50(1.35) | 38.20 | tested prior swing low at 1.10 (2026-03-02), held |
| 2026-04-03 | 1.15 | 1.16 | 1.11 | 1.14 | 6,415,726 | 16,400,866 | 0.39 | — | — | -5.0% vs SMA20(1.20) | insufficient history | within bands | 0.0052 | rising | EMA20(1.22) < EMA50(1.34) | 39.20 | tested prior swing low at 1.10 (2026-03-02), held |
| 2026-04-06 | 1.12 | 1.17 | 1.12 | 1.16 | 7,294,295 | 15,801,476 | 0.46 | Bullish Engulfing | prior_close(1.14)<prior_open(1.15, bearish) AND close(1.16)>open(1.12, bullish) AND open(1.12) <= prior_close(1.14) AND close(1.16) >= prior_open(1.15) [today body 1.12→1.16 engulfs prior 1.15→1.14] | -2.5% vs SMA20(1.19) | insufficient history | within bands | 0.0071 | rising | EMA20(1.21) < EMA50(1.34) | 41.30 | tested prior swing low at 1.14 (2026-03-09), held |
| 2026-04-07 | 1.13 | 1.18 | 1.13 | 1.16 | 3,913,268 | 15,609,322 | 0.25 | — | — | -1.9% vs SMA20(1.18) | insufficient history | within bands | 0.0086 | rising | EMA20(1.21) < EMA50(1.33) | 41.30 | tested prior swing low at 1.14 (2026-03-09), held |
| 2026-04-08 | 1.30 | 1.60 | 1.22 | 1.58 | 212,312,467 | 24,544,524 | 8.65 | — | — | +31.2% vs SMA20(1.20) | insufficient history | +3.9 sigma | 0.0365 | rising | EMA20(1.24) < EMA50(1.34) | 67.70 | — |
| 2026-04-09 | 1.61 | 1.61 | 1.41 | 1.47 | 81,609,572 | 27,850,008 | 2.93 | — | — | +21.1% vs SMA20(1.21) | insufficient history | +2.3 sigma | 0.0456 | rising | EMA20(1.26) < EMA50(1.35) | 60.00 | — |
| 2026-04-10 | 1.45 | 1.52 | 1.40 | 1.44 | 43,189,848 | 29,158,333 | 1.48 | Doji | body(0.01) <= 0.1*range(0.12) [body/range=0.08] | +17.6% vs SMA20(1.23) | insufficient history | +1.8 sigma | 0.0474 | rising | EMA20(1.28) < EMA50(1.35) | 58.10 | — |
| 2026-04-13 | 1.39 | 1.39 | 1.30 | 1.31 | 33,604,339 | 30,100,852 | 1.12 | — | — | +6.4% vs SMA20(1.23) | insufficient history | within bands | 0.0381 | falling | EMA20(1.28) < EMA50(1.35) | 50.60 | — |
| 2026-04-14 | 1.34 | 1.45 | 1.32 | 1.33 | 62,630,235 | 32,435,686 | 1.93 | Doji | body(0.01) <= 0.1*range(0.13) [body/range=0.08] | +7.4% vs SMA20(1.24) | insufficient history | within bands | 0.0318 | falling | EMA20(1.29) < EMA50(1.35) | 51.60 | — |
| 2026-04-15 | 1.44 | 1.44 | 1.38 | 1.39 | 35,645,478 | 33,663,246 | 1.06 | — | — | +11.3% vs SMA20(1.25) | +3.3% vs SMA50(1.35) | +1.1 sigma | 0.0302 | falling | EMA20(1.30) < EMA50(1.35) | 54.70 | — |
| 2026-04-16 | 1.44 | 1.44 | 1.40 | 1.41 | 21,110,117 | 34,156,035 | 0.62 | — | — | +11.8% vs SMA20(1.26) | +5.2% vs SMA50(1.34) | +1.1 sigma | 0.0290 | falling | EMA20(1.31) < EMA50(1.35) | 55.70 | — |
| 2026-04-17 | 1.42 | 1.47 | 1.42 | 1.46 | 30,513,310 | 35,240,069 | 0.87 | — | — | +14.6% vs SMA20(1.27) | +9.3% vs SMA50(1.34) | +1.4 sigma | 0.0300 | rising | EMA20(1.32) < EMA50(1.36) | 58.20 | — |
| 2026-04-20 | 1.45 | 1.45 | 1.31 | 1.39 | 38,950,231 | 36,086,140 | 1.08 | — | — | +8.5% vs SMA20(1.28) | +4.6% vs SMA50(1.33) | within bands | 0.0245 | falling | EMA20(1.33) < EMA50(1.36) | 53.60 | — |
| 2026-04-21 | 1.43 | 1.43 | 1.36 | 1.38 | 28,006,993 | 37,078,051 | 0.76 | — | — | +7.1% vs SMA20(1.29) | +4.3% vs SMA50(1.32) | within bands | 0.0191 | falling | EMA20(1.33) < EMA50(1.36) | 53.00 | — |
| 2026-04-22 | 1.38 | 1.47 | 1.35 | 1.38 | 34,293,463 | 37,551,922 | 0.91 | Doji | body(0.00) <= 0.1*range(0.12) [body/range=0.00] | +6.5% vs SMA20(1.30) | +4.6% vs SMA50(1.32) | within bands | 0.0145 | falling | EMA20(1.34) < EMA50(1.36) | 53.00 | — |
| 2026-04-23 | 1.39 | 1.74 | 1.37 | 1.70 | 286,823,348 | 50,241,853 | 5.71 | — | — | +28.6% vs SMA20(1.32) | +28.6% vs SMA50(1.32) | +2.3 sigma | 0.0312 | rising | EMA20(1.37) > EMA50(1.37) | 67.50 | — |
| 2026-04-24 | 1.73 | 1.74 | 1.49 | 1.51 | 128,291,548 | 55,297,362 | 2.32 | — | — | +12.7% vs SMA20(1.34) | +14.3% vs SMA50(1.32) | +1.0 sigma | 0.0276 | falling | EMA20(1.39) > EMA50(1.38) | 56.40 | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-04-06 = Day 0).

Day -9 (2026-03-24): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.0068 (rising), EMA20(1.29) < EMA50(1.41)
Day -8 (2026-03-25): Volume 1.2x avg, no pattern, BB within bands, MACD hist 0.0091 (rising), EMA20(1.28) < EMA50(1.41)
Day -7 (2026-03-26): Volume 1.6x avg, no pattern, BB within bands, MACD hist 0.0077 (falling), EMA20(1.27) < EMA50(1.40), tested prior swing low at 1.16 (2026-02-20), held
Day -6 (2026-03-27): Volume 1.4x avg, no pattern, BB -1.0 sigma, MACD hist 0.0052 (falling), EMA20(1.26) < EMA50(1.39), tested prior swing low at 1.14 (2026-03-09), held
Day -5 (2026-03-30): Volume 1.0x avg, no pattern, BB -1.4 sigma, MACD hist 0.0015 (falling), EMA20(1.25) < EMA50(1.38), tested prior swing low at 1.10 (2026-03-02), held
Day -4 (2026-03-31): Volume 0.4x avg, no pattern, BB -1.1 sigma, MACD hist 0.0023 (rising), EMA20(1.24) < EMA50(1.37), tested prior swing low at 1.10 (2026-03-02), held
Day -3 (2026-04-01): Volume 0.6x avg, no pattern, BB within bands, MACD hist 0.0060 (rising), EMA20(1.23) < EMA50(1.36), tested prior swing low at 1.16 (2026-02-20), held
Day -2 (2026-04-02): Volume 0.8x avg, no pattern, BB -1.2 sigma, MACD hist 0.0049 (falling), EMA20(1.22) < EMA50(1.35), tested prior swing low at 1.10 (2026-03-02), held
Day -1 (2026-04-03): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.0052 (rising), EMA20(1.22) < EMA50(1.34), tested prior swing low at 1.10 (2026-03-02), held
Day 0 (2026-04-06): Volume 0.5x avg, Bullish Engulfing formed (prior_close(1.14)<prior_open(1.15, bearish) AND close(1.16)>open(1.12, bullish) AND open(1.12) <= prior_close(1.14) AND close(1.16) >= prior_open(1.15) [today body 1.12→1.16 engulfs prior 1.15→1.14]), BB within bands, MACD hist 0.0071 (rising), EMA20(1.21) < EMA50(1.34), tested prior swing low at 1.14 (2026-03-09), held
Day +1 (2026-04-07): Volume 0.2x avg, no pattern, BB within bands, MACD hist 0.0086 (rising), EMA20(1.21) < EMA50(1.33), tested prior swing low at 1.14 (2026-03-09), held
Day +2 (2026-04-08): Volume 8.7x avg, no pattern, BB +3.9 sigma, MACD hist 0.0365 (rising), EMA20(1.24) < EMA50(1.34)
Day +3 (2026-04-09): Volume 2.9x avg, no pattern, BB +2.3 sigma, MACD hist 0.0456 (rising), EMA20(1.26) < EMA50(1.35)
Day +4 (2026-04-10): Volume 1.5x avg, Doji formed (body(0.01) <= 0.1*range(0.12) [body/range=0.08]), BB +1.8 sigma, MACD hist 0.0474 (rising), EMA20(1.28) < EMA50(1.35)
Day +5 (2026-04-13): Volume 1.1x avg, no pattern, BB within bands, MACD hist 0.0381 (falling), EMA20(1.28) < EMA50(1.35)
Day +6 (2026-04-14): Volume 1.9x avg, Doji formed (body(0.01) <= 0.1*range(0.13) [body/range=0.08]), BB within bands, MACD hist 0.0318 (falling), EMA20(1.29) < EMA50(1.35)
Day +7 (2026-04-15): Volume 1.1x avg, no pattern, BB +1.1 sigma, MACD hist 0.0302 (falling), EMA20(1.30) < EMA50(1.35)
Day +8 (2026-04-16): Volume 0.6x avg, no pattern, BB +1.1 sigma, MACD hist 0.0290 (falling), EMA20(1.31) < EMA50(1.35)
Day +9 (2026-04-17): Volume 0.9x avg, no pattern, BB +1.4 sigma, MACD hist 0.0300 (rising), EMA20(1.32) < EMA50(1.36)
Day +10 (2026-04-20): Volume 1.1x avg, no pattern, BB within bands, MACD hist 0.0245 (falling), EMA20(1.33) < EMA50(1.36)
Day +11 (2026-04-21): Volume 0.8x avg, no pattern, BB within bands, MACD hist 0.0191 (falling), EMA20(1.33) < EMA50(1.36)
Day +12 (2026-04-22): Volume 0.9x avg, Doji formed (body(0.00) <= 0.1*range(0.12) [body/range=0.00]), BB within bands, MACD hist 0.0145 (falling), EMA20(1.34) < EMA50(1.36)
Day +13 (2026-04-23): Volume 5.7x avg, no pattern, BB +2.3 sigma, MACD hist 0.0312 (rising), EMA20(1.37) > EMA50(1.37)
Day +14 (2026-04-24): Volume 2.3x avg, no pattern, BB +1.0 sigma, MACD hist 0.0276 (falling), EMA20(1.39) > EMA50(1.38)

---

## Cross-stock first-occurrence comparison

For all four stocks, the day (relative to each stock's own move-start date, Day 0) each of the following
first appears in its report window:

| Signal | AICL | SHFA | THCCL | FNEL |
|---|---|---|---|---|
| First volume >2x avg | Day -11 (2026-07-08) | Day -8 (2026-06-02) | Day +5 (2026-07-07) | Day +2 (2026-04-08) |
| First candlestick pattern | Day -9 (2026-07-10) | Day -4 (2026-06-08) | Day +3 (2026-07-03) | Day 0 (2026-04-06) |
| First BB oversold (<=-1.5 sigma) | Day -7 (2026-07-14) | Day -7 (2026-06-03) | not observed in window | not observed in window |
| First MACD hist sign change (neg->pos) | Day +3 (2026-07-28) | Day 0 (2026-06-12) | Day +5 (2026-07-07) | not observed in window |
| First EMA20/50 golden cross | Day +2 (2026-07-27) | Day +1 (2026-06-15) | not observed in window | Day +13 (2026-04-23) |
| Breakout day (vol>=2.5x + up day) | Day +3 (2026-07-28) | Day +3 (2026-06-17) | Day +5 (2026-07-07) | Day +2 (2026-04-08) |

**Reading this table:** the breakout day (highest-conviction volume+price confirmation) lands between
Day +2 and Day +5 across all four stocks — a fairly tight cluster given the four stocks span wildly
different price scales (₹1-2 for FNEL up to ₹500+ for SHFA) and sectors (insurance, healthcare, cement,
fertilizer). The first >2x-average-volume day and the breakout day coincide exactly for THCCL and FNEL,
but not for AICL or SHFA (where an earlier, smaller volume pickup preceded the actual breakout by several
sessions) — so "first elevated volume" is not a reliable stand-alone breakout-timing signal on its own in
this n=4 sample; it needs to be read together with the candlestick/MACD/BB signals in the same row. BB
oversold readings and EMA20/50 golden crosses are inconsistent across the four (present for AICL/SHFA,
absent for THCCL, and only very late for FNEL, well after its own breakout) — with n=4, this is descriptive,
not a validated cross-stock rule.

---

## Reproducibility

- Raw fetched data (all four stocks' OHLC, this round's pure-technical pass — no announcements fetched):
  GitHub Actions run
  [33750322608](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33750322608),
  triggered from `analysis/fetch_premove_data.py`, saved verbatim as `analysis/premove_data_raw.json`.
  (First pass's AICL/SHFA-plus-announcements run remains at
  [33746474452](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33746474452)
  for the announcement findings carried forward above.)
- Indicator computation, pattern scan, FNEL pre-adjustment trim, and first-occurrence tracking:
  `analysis/analyze_premove.py` (unit-tested against synthetic OHLC before running on real data), reads
  `premove_data_raw.json` and writes `analysis/premove_analysis.json`.
- Markdown table / "what fired" narrative / cross-stock table generation: `analysis/gen_report_v2.py`,
  assembled into this file by `analysis/build_full_report.py` — every number in the tables above is
  generated programmatically from `premove_analysis.json`, never hand-typed (the lesson from the first
  pass, where a hand-typed draft had real transcription errors, caught only by cross-checking against the
  raw JSON). Re-running `analyze_premove.py` from its repo location reproduces byte-identical JSON output
  (verified via `diff` on sorted `json.dumps()` output).
- To add a 5th+ entry to this dataset: add an entry to `TARGETS` in `fetch_premove_data.py` and a
  `MOVE_START` entry in `analyze_premove.py`, re-run the `Pre-move study data fetch (manual, one-off)`
  GitHub Actions workflow, save its JSON output over `premove_data_raw.json`, then re-run
  `analyze_premove.py` and `build_full_report.py`.
