# Pre-Move Study: AICL, SHFA, THCCL, FNEL, MDTL, FPJM, BNL, DSIL, SYM, PREMA, JSBL, ILP

**Prepared:** 2026-09-03 (indicator-expansion + 8-new-stock round, extending the prior
AICL/SHFA/THCCL/FNEL day-by-day-forensics round).
**Method note (read first):** All price/volume data below is real, pulled directly from PSX's own
Data Portal (`dps.psx.com.pk/historical`) via `backend/dps_scraper.py`. Because this session's
sandbox cannot reach `dps.psx.com.pk` directly, fetches run in a GitHub Actions job
(`.github/workflows/premove_data_fetch.yml`) and results are pulled back via job logs. This
round's 12-symbol combined fetch produced a single JSON-blob log line large enough that GitHub
Actions truncated the head of the log (silently dropping the parsing marker this pipeline depends
on) -- the workflow now accepts an optional `symbols` input (`PREMOVE_SYMBOLS` env var) so a run
can be split into smaller batches; this round's data was fetched across three such batched runs.

**This round's scope, explicitly:** announcement/catalyst-checking remains out of scope for every
stock except the two carried-forward AICL/SHFA findings from the very first pass (not re-checked).
This round's real additions are (1) a significantly expanded indicator layer (below), (2) the
existing AICL/SHFA/THCCL/FNEL sections re-run through it end to end, with an explicit check for
whether the richer indicator set changes any of their stories, and (3) eight new stocks --
MDTL, FPJM, DSIL, SYM, PREMA, JSBL, ILP (all ticker-identity-confirmed) and BNL (ticker-identity
**mismatch**, disclosed rather than force-fit into a forensic narrative -- see its section).

**Expanded indicator layer (added this round), and why:**

- **MFI (Money Flow Index, 14-period)** -- volume-weighted RSI; tests whether volume was actually
  flowing IN during the pre-move window, not just present. Standard convention: simple rolling
  sums of positive/negative typical-price*volume over 14 bars (a different smoothing convention
  from this module's Wilder-smoothed RSI, by design -- MFI and RSI are meant to read differently).
- **OBV (On-Balance Volume)** -- cumulative, close-to-close direction-weighted volume; the
  standard tool for spotting quiet accumulation that doesn't yet show up as a price breakout.
- **A/D Line (Accumulation/Distribution Line)** -- cumulative money-flow-volume, but weighted by
  where each bar's close sits within its own high-low range rather than just up/down close-to-
  close. Reported alongside OBV specifically because the two can diverge from each other, and a
  divergence is itself informative (see each stock's "Flow divergence check").
- **ATR (Average True Range, 14-period)**, Wilder-smoothed -- gives this study's prior qualitative
  "low-volatility base" language an actual measured number.
- **VWAP, window-anchored approximation** -- only daily OHLCV is available, so this is NOT a real
  intraday VWAP; it's a cumulative volume-weighted typical price `(H+L+C)/3`, restarting at each
  report window's own first day. Labeled as such in every table it appears in.
- **Ichimoku Cloud** (standard 9/26/52 periods, cloud displaced 26 periods forward) -- reports
  cloud position (above/below/inside), Tenkan/Kijun cross state and date if one occurred
  in-window, and cloud color (bullish green if Senkou A>B, bearish red otherwise) and thickness.
  Because Senkou Span A/B are plotted 26 periods FORWARD, the cloud reading for the last ~26 days
  of any window is provisional -- it's drawn from Tenkan/Kijun computed inside the window itself,
  not from data further back, the same caveat real charting platforms show for an unclosed
  forward cloud.
- **Morning Star and Piercing Line candlestick patterns** -- both were already implemented and
  unit-tested in the prior round's `scan_patterns()` (verified again this round, not
  re-implemented); Piercing Line fired for the first time in this dataset on DSIL (2026-07-23).

Chart-pattern (geometric) detection -- Head & Shoulders, Double Bottom, Triangle, Cup & Handle --
is explicitly OUT of scope for this round, per instruction: it's a separate, larger task
(geometric pattern recognition across a whole price series, not a single-column indicator) to be
scoped once this indicator layer is confirmed working.

**Did the richer indicator set change the story for AICL/SHFA/THCCL/FNEL?** Checked explicitly,
stock by stock:

- **AICL: confirmed, not changed.** OBV/A-D Line track the existing price narrative closely (both
  negative through the 07-08 to 07-23 drift, both flip sharply positive on the 07-28 breakout).
  One minor nuance: MFI's low (38.3-38.4, around 07-23/07-24) is noticeably less extreme than
  RSI's low (34.4 on 07-23) -- volume-weighted momentum wasn't quite as oversold as price-only
  RSI suggested, but this doesn't change the overall signature.
- **SHFA: genuinely changed.** MFI reads deeply oversold (9.6 on 05-29, 16.8-23.9 through
  06-01/06-02) right at the start of the base -- a much more extreme volume-weighted oversold
  reading, and much earlier, than RSI ever showed in the original pass (RSI only reached the
  low-to-mid 40s). This is new information: volume-weighted selling pressure peaked earlier and
  harder than the price-only view suggested.
- **THCCL: confirmed, not changed.** OBV and MFI both stay elevated throughout (MFI 46-86),
  consistent with the already-elevated momentum the original RSI-based read already showed.
- **FNEL: confirmed for the main 04-08 breakout** (OBV/MFI both flip sharply positive same-day,
  matching the existing narrative), **but with one genuinely new secondary finding**: OBV and MFI
  both show a real accumulation build from 04-14 through 04-17 (OBV climbing from -32M to +55M,
  MFI from 71.9 to 84.6) in the days immediately BEFORE the second volume spike on 04-23 -- a
  quieter, volume-led build-up ahead of that second leg that the original RSI/MACD/BB-only set
  didn't surface as a distinct phase.

No systematic OBV/A-D-Line divergence-from-price cluster was found concentrated specifically in
the days immediately before any of the four stocks' breakout days -- divergence flags occur on
scattered ordinary days across all four (see each section's "Flow divergence check"), not as a
concentrated pre-breakout "quiet accumulation" pattern this richer indicator set would have
otherwise missed with the original set.

Indicators (EMA20/EMA50, MACD(12,26,9), Bollinger(20,2), RSI(14), MFI(14), 20-day volume
averages, SMA20/SMA50, OBV, A/D Line, ATR(14), Ichimoku) are computed over an EXTENDED lookback
(~70 calendar days before each requested window, more for BNL/SYM given their wider windows) so
every reported day has genuine trailing history to average against. Candlestick pattern rules
(Bullish Engulfing, Morning Star, Hammer, Doji, Piercing Line) are literal, classic textbook
definitions, unit-tested against synthetic OHLC before running on real data. Support/resistance
notes come from a retrospective swing-point scan (local highs/lows over a +/-3-bar window) --
descriptive, not a causal/live trading signal.

**General price-cliff detector (generalized this round from a FNEL-specific hardcode):** every
stock's raw series is scanned for a day whose close DROPS more than 30% from the prior close AND
whose volume exceeds 3x the trailing 10-day average -- deliberately one-sided (drops only), since
a bonus/rights share issue mechanically dilutes price DOWN, never explains a price rising sharply
(an upward spike on high volume, like FNEL's real 04-08 breakout, is exactly the kind of genuine
signal this whole study exists to find, and must never be trimmed away as a data artifact). The
detector was verified (via an assertion in `analyze_premove.py`'s `main()`) to still find exactly
FNEL's known 2026-02-02 cliff and nothing else for that symbol. It found zero qualifying cliffs
for BNL -- BNL's mismatch with the user's reference prices is NOT explained by an unadjusted
corporate action; see its section.

---
---

## STOCK 1 — AICL (Adamjee Insurance Company Limited)

### Data coverage & ticker identity

Report window: **2026-07-08 to 2026-08-07**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **AICL** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `AICL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Confirmed PSX-announcement findings (carried forward from the first pass, not re-checked this or last round):** No company-disclosed announcement found inside the 2026-07-08 to 2026-08-10 window on the company page. PSX-wide notices page could not be verified (JS-rendered search). Do not read this as "confirmed catalyst-free."

**Chart structure:** 07-08 through 07-22 is a ragged downward drift/consolidation (closes ~75.9-81.7). 07-23 (close 73.02) is a flush-out low below that range. 07-24 reverses hard off that low (Bullish Engulfing). 07-27 closes back above the top of the prior range; the volume breakout confirms on 07-28 (8.70x the 20-day average).

### Core day-by-day table (OHLC, candles, trend)

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

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-08 | 47.30 | 1,649,364 | 611,133 | 3.48 | 81.89 | below | 82.12 | 78.62 | cloud not yet formed (insufficient history) | — |
| 2026-07-09 | 40.90 | 946,304 | 560,914 | 3.43 | 81.42 | below | 82.12 | 78.62 | cloud not yet formed (insufficient history) | — |
| 2026-07-10 | 45.80 | 610,438 | 335,884 | 3.33 | 81.33 | below | 82.25 | 78.62 | cloud not yet formed (insufficient history) | — |
| 2026-07-13 | 46.20 | 344,819 | 442,989 | 3.27 | 81.18 | below | 82.25 | 78.94 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-07-14 | 44.40 | -309,729 | 434,941 | 3.40 | 80.44 | below | 80.55 | 78.94 | cloud not yet formed (insufficient history) | — |
| 2026-07-15 | 44.60 | -107,292 | 487,751 | 3.33 | 80.28 | below | 80.55 | 78.94 | cloud not yet formed (insufficient history) | — |
| 2026-07-16 | 49.80 | 189,412 | 666,203 | 3.29 | 80.20 | below | 80.55 | 79.14 | cloud not yet formed (insufficient history) | — |
| 2026-07-17 | 44.70 | -324,033 | 396,896 | 3.34 | 79.87 | below | 80.11 | 79.14 | cloud not yet formed (insufficient history) | — |
| 2026-07-20 | 49.00 | -50,848 | 647,780 | 3.31 | 79.67 | below | 79.78 | 79.14 | cloud not yet formed (insufficient history) | — |
| 2026-07-21 | 45.30 | -362,230 | 503,958 | 3.24 | 79.54 | below | 78.28 | 80.00 | cloud not yet formed (insufficient history) | — |
| 2026-07-22 | 40.10 | -460,922 | 418,114 | 3.13 | 79.48 | below | 78.28 | 80.28 | cloud not yet formed (insufficient history) | — |
| 2026-07-23 | 38.40 | -933,719 | 56,279 | 3.18 | 79.00 | below | 76.78 | 79.28 | cloud not yet formed (insufficient history) | — |
| 2026-07-24 | 38.30 | -357,047 | 346,774 | 3.62 | 78.72 | below | 75.47 | 78.32 | cloud not yet formed (insufficient history) | — |
| 2026-07-27 | 38.40 | 557,374 | 593,828 | 3.97 | 79.10 | above | 78.05 | 78.32 | cloud not yet formed (insufficient history) | — |
| 2026-07-28 | 78.90 | 8,062,766 | 8,099,220 | 4.30 | 83.59 | above | 80.61 | 80.61 | cloud not yet formed (insufficient history) | — |
| 2026-07-29 | 89.30 | 1,447,977 | 5,501,705 | 4.58 | 85.72 | above | 82.83 | 82.83 | cloud not yet formed (insufficient history) | — |
| 2026-07-30 | 85.90 | 763,299 | 5,832,287 | 4.61 | 85.79 | above | 82.83 | 82.83 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-07-31 | 89.10 | 4,216,794 | 6,090,011 | 4.80 | 86.68 | above | 83.26 | 83.26 | cloud not yet formed (insufficient history) | — |
| 2026-08-03 | 92.10 | 5,802,914 | 4,680,126 | 4.92 | 87.20 | above | 84.78 | 84.78 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-08-04 | 88.20 | 4,847,366 | 3,932,791 | 4.94 | 87.41 | above | 84.78 | 84.78 | cloud not yet formed (insufficient history) | — |
| 2026-08-05 | 87.70 | 4,960,163 | 3,860,801 | 4.79 | 87.43 | above | 84.78 | 84.78 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-08-06 | 90.30 | 7,086,408 | 4,772,986 | 4.91 | 87.98 | above | 87.90 | 84.78 | cloud not yet formed (insufficient history) | — |
| 2026-08-07 | 91.50 | 8,295,137 | 4,779,610 | 5.08 | 88.30 | above | 91.00 | 85.33 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-07-23 = Day 0).

Day -11 (2026-07-08): Volume 2.3x avg, no pattern, BB within bands, MACD hist 0.3252 (falling), EMA20(80.34) > EMA50(78.97), MFI 47.3, price below VWAP, tested prior swing low at 77.50 (2026-06-22), held; tested prior swing high at 85.99 (2026-07-06), rejected at
Day -10 (2026-07-09): Volume 1.2x avg, no pattern, BB within bands, MACD hist 0.0909 (falling), EMA20(80.36) > EMA50(79.03), MFI 40.9, price below VWAP, tested prior swing high at 83.55 (2026-05-08), rejected at
Day -9 (2026-07-10): Volume 0.6x avg, Doji formed (body(0.17) <= 0.1*range(2.00) [body/range=0.09]), BB within bands, MACD hist -0.0847 (falling), EMA20(80.36) > EMA50(79.08), MFI 45.8, price below VWAP, tested prior swing high at 83.55 (2026-05-08), rejected at
Day -8 (2026-07-13): Volume 0.5x avg, no pattern, BB within bands, MACD hist -0.2079 (falling), EMA20(80.35) > EMA50(79.13), MFI 46.2, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing low at 77.50 (2026-06-22), held
Day -7 (2026-07-14): Volume 1.1x avg, no pattern, BB -2.0 sigma, MACD hist -0.4616 (falling), EMA20(80.08) > EMA50(79.07), MFI 44.4, price below VWAP, tested prior swing low at 76.00 (2026-04-24), held
Day -6 (2026-07-15): Volume 0.4x avg, no pattern, BB -1.7 sigma, MACD hist -0.5805 (falling), EMA20(79.88) > EMA50(79.02), MFI 44.6, price below VWAP, tested prior swing low at 76.00 (2026-04-24), held
Day -5 (2026-07-16): Volume 0.6x avg, no pattern, BB within bands, MACD hist -0.5200 (rising), EMA20(79.86) > EMA50(79.05), MFI 49.8, price below VWAP, tested prior swing low at 77.50 (2026-06-22), held
Day -4 (2026-07-17): Volume 1.0x avg, no pattern, BB -2.0 sigma, MACD hist -0.6526 (falling), EMA20(79.57) > EMA50(78.96), MFI 44.7, price below VWAP, tested prior swing low at 76.00 (2026-04-24), held
Day -3 (2026-07-20): Volume 0.5x avg, Hammer formed (lower_wick(1.94) >= 2*body(0.88) AND upper_wick(0.12) <= 0.3*body(0.88) AND high(77.50)-max(open,close)(77.38)=0.12 <= 0.15*range(2.94)), BB -1.5 sigma, MACD hist -0.6714 (falling), EMA20(79.36) > EMA50(78.90), MFI 49.0, price below VWAP, tested prior swing low at 74.01 (2026-04-30), held; tested prior swing high at 77.00 (2026-05-25), broke above
Day -2 (2026-07-21): Volume 0.6x avg, no pattern, BB -1.4 sigma, MACD hist -0.6547 (rising), EMA20(79.17) > EMA50(78.84), MFI 45.3, price below VWAP, tested prior swing low at 77.50 (2026-06-22), broke below
Day -1 (2026-07-22): Volume 0.2x avg, no pattern, BB -1.8 sigma, MACD hist -0.7069 (falling), EMA20(78.86) > EMA50(78.73), MFI 40.1, price below VWAP, tested prior swing low at 76.00 (2026-04-24), broke below; tested prior swing high at 77.00 (2026-05-25), rejected at
Day 0 (2026-07-23): Volume 0.9x avg, no pattern, BB -2.4 sigma, MACD hist -0.8905 (falling), EMA20(78.31) < EMA50(78.50), MFI 38.4, price below VWAP, tested prior swing low at 71.26 (2026-06-03), held; tested prior swing high at 77.00 (2026-05-25), rejected at
Day +1 (2026-07-24): Volume 1.1x avg, Bullish Engulfing formed (prior_close(73.02)<prior_open(75.10, bearish) AND close(77.68)>open(72.00, bullish) AND open(72.00) <= prior_close(73.02) AND close(77.68) >= prior_open(75.10) [today body 72.00→77.68 engulfs prior 75.10→73.02]), BB within bands, MACD hist -0.6624 (rising), EMA20(78.25) < EMA50(78.47), MFI 38.3, price below VWAP, tested prior swing low at 71.03 (2026-05-22), held
Day +2 (2026-07-27): Volume 1.7x avg, no pattern, BB within bands, MACD hist -0.1872 (rising), EMA20(78.64) > EMA50(78.62), MFI 38.4, price above VWAP, tested prior swing low at 77.50 (2026-06-22), held; tested prior swing high at 85.99 (2026-07-06), rejected at
Day +3 (2026-07-28): Volume 8.7x avg, no pattern, BB +2.8 sigma, MACD hist 0.6467 (rising), EMA20(79.77) > EMA50(79.09), MFI 78.9, price above VWAP
Day +4 (2026-07-29): Volume 5.7x avg, Doji formed (body(0.68) <= 0.1*range(8.20) [body/range=0.08]), BB +2.1 sigma, MACD hist 1.0540 (rising), EMA20(80.68) > EMA50(79.49), MFI 89.3, price above VWAP
Day +5 (2026-07-30): Volume 0.6x avg, no pattern, BB +1.7 sigma, MACD hist 1.2149 (rising), EMA20(81.44) > EMA50(79.85), MFI 85.9, price above VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
Day +6 (2026-07-31): Volume 2.6x avg, no pattern, BB +2.1 sigma, MACD hist 1.4852 (rising), EMA20(82.49) > EMA50(80.35), MFI 89.1, price above VWAP
Day +7 (2026-08-03): Volume 1.1x avg, no pattern, BB +2.0 sigma, MACD hist 1.6533 (rising), EMA20(83.57) > EMA50(80.87), MFI 92.1, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day +8 (2026-08-04): Volume 0.7x avg, no pattern, BB +1.6 sigma, MACD hist 1.5393 (falling), EMA20(84.36) > EMA50(81.31), MFI 88.2, price above VWAP
Day +9 (2026-08-05): Volume 0.1x avg, no pattern, BB +1.4 sigma, MACD hist 1.3786 (falling), EMA20(85.10) > EMA50(81.73), MFI 87.7, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day +10 (2026-08-06): Volume 1.5x avg, no pattern, BB +1.7 sigma, MACD hist 1.4408 (rising), EMA20(86.14) > EMA50(82.29), MFI 90.3, price above VWAP, tested prior swing high at 98.90 (2026-08-03), rejected at
Day +11 (2026-08-07): Volume 0.8x avg, Doji formed (body(0.34) <= 0.1*range(7.30) [body/range=0.05]), BB +1.6 sigma, MACD hist 1.4034 (falling), EMA20(87.11) > EMA50(82.84), MFI 91.5, price above VWAP, tested prior swing high at 98.90 (2026-08-03), rejected at

### Flow divergence check

4 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-07-13: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-07-30: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-08-03: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-08-05: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
---

## STOCK 2 — SHFA (Shifa International Hospitals Limited)

### Data coverage & ticker identity

Report window: **2026-05-28 to 2026-06-18**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **SHFA** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `SHFA` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Confirmed PSX-announcement findings (carried forward, not re-checked):** A **Board Meeting (Other Than Financial Results)** was disclosed for **June 19, 2026** -- one day after the move's reference end-date. Treat as a possible catalyst; not catalyst-free.

**Chart structure:** 05-29 through 06-12 is a tight consolidation/base (closes 470.36-482.32, ~2.5% band). 06-15/06-16 are the first closes clearly above the base. 06-17 is the violent breakout/gap day (+8.65% on 3.80x volume). 06-18 opens even higher, hits an intraday high of 554.0, then pulls back to close at 525.59 -- a blow-off/exhaustion shape on the second breakout day.

### Core day-by-day table (OHLC, candles, trend)

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

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-28 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-29 | 9.60 | 213,039 | 110,079 | 17.71 | 474.66 | above | 478.32 | 488.30 | cloud not yet formed (insufficient history) | — |
| 2026-06-01 | 23.90 | 200,191 | 101,475 | 17.65 | 477.32 | below | 478.32 | 488.30 | cloud not yet formed (insufficient history) | — |
| 2026-06-02 | 16.80 | 153,766 | 101,685 | 17.97 | 474.78 | below | 476.32 | 483.32 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-06-03 | 44.50 | 81,143 | 61,740 | 18.04 | 474.28 | below | 476.32 | 481.32 | cloud not yet formed (insufficient history) | — |
| 2026-06-04 | 47.30 | 89,058 | 58,718 | 18.25 | 474.38 | below | 474.31 | 480.32 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-05 | 45.90 | 84,872 | 58,277 | 17.43 | 474.35 | below | 474.31 | 480.32 | cloud not yet formed (insufficient history) | — |
| 2026-06-08 | 45.10 | 78,309 | 61,184 | 17.17 | 474.20 | below | 474.31 | 478.32 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-06-09 | 48.20 | 84,763 | 63,721 | 17.03 | 474.30 | above | 474.31 | 478.32 | cloud not yet formed (insufficient history) | — |
| 2026-06-10 | 47.70 | 79,243 | 61,762 | 16.63 | 474.21 | below | 472.80 | 478.32 | cloud not yet formed (insufficient history) | — |
| 2026-06-11 | 59.00 | 102,033 | 59,367 | 16.36 | 474.45 | above | 475.81 | 478.32 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-12 | 62.50 | 115,109 | 56,202 | 16.06 | 474.94 | above | 475.33 | 478.32 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-15 | 67.30 | 151,723 | 61,974 | 16.19 | 477.37 | above | 481.00 | 478.32 | cloud not yet formed (insufficient history) | — |
| 2026-06-16 | 69.60 | 172,756 | 77,282 | 16.10 | 478.73 | above | 481.50 | 478.32 | cloud not yet formed (insufficient history) | — |
| 2026-06-17 | 80.30 | 247,487 | 136,644 | 18.39 | 489.74 | above | 504.50 | 501.32 | cloud not yet formed (insufficient history) | — |
| 2026-06-18 | 73.50 | 213,095 | 134,165 | 20.86 | 493.17 | above | 508.50 | 505.32 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-06-12 = Day 0).

Day -10 (2026-05-29): Volume 0.6x avg, no pattern, BB within bands, MACD hist -1.1299 (rising), EMA20(482.57) > EMA50(480.30), MFI 9.6, price above VWAP, tested prior swing low at 451.10 (2026-03-19), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -9 (2026-06-01): Volume 1.5x avg, no pattern, BB -1.1 sigma, MACD hist -1.2844 (falling), EMA20(481.83) > EMA50(480.08), MFI 23.9, price below VWAP, tested prior swing low at 471.55 (2026-04-24), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -8 (2026-06-02): Volume 4.5x avg, no pattern, BB -1.2 sigma, MACD hist -1.3782 (falling), EMA20(481.06) > EMA50(479.84), MFI 16.8, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -7 (2026-06-03): Volume 5.3x avg, no pattern, BB -1.6 sigma, MACD hist -1.5790 (falling), EMA20(480.05) > EMA50(479.46), MFI 44.5, price below VWAP, tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -6 (2026-06-04): Volume 0.6x avg, no pattern, BB -1.1 sigma, MACD hist -1.4148 (rising), EMA20(479.42) > EMA50(479.23), MFI 47.3, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 465.00 (2026-04-13), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -5 (2026-06-05): Volume 0.3x avg, no pattern, BB -1.1 sigma, MACD hist -1.2569 (rising), EMA20(478.81) < EMA50(478.99), MFI 45.9, price below VWAP, tested prior swing low at 470.00 (2026-04-30), held
Day -4 (2026-06-08): Volume 0.5x avg, Doji formed (body(0.09) <= 0.1*range(13.75) [body/range=0.01]), BB within bands, MACD hist -1.0841 (rising), EMA20(478.25) < EMA50(478.75), MFI 45.1, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing low at 465.00 (2026-04-13), held
Day -3 (2026-06-09): Volume 0.5x avg, Hammer formed (lower_wick(10.65) >= 2*body(4.64) AND upper_wick(0.00) <= 0.3*body(4.64) AND high(483.30)-max(open,close)(483.30)=0.00 <= 0.15*range(15.29)), BB within bands, MACD hist -0.5371 (rising), EMA20(478.29) < EMA50(478.75), MFI 48.2, price above VWAP, tested prior swing low at 470.00 (2026-04-30), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day -2 (2026-06-10): Volume 0.5x avg, no pattern, BB -1.1 sigma, MACD hist -0.6766 (falling), EMA20(477.54) < EMA50(478.42), MFI 47.7, price below VWAP, tested prior swing low at 465.00 (2026-04-13), held
Day -1 (2026-06-11): Volume 1.7x avg, no pattern, BB within bands, MACD hist -0.3650 (rising), EMA20(477.37) < EMA50(478.32), MFI 59.0, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 470.00 (2026-04-30), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day 0 (2026-06-12): Volume 1.0x avg, Doji formed (body(0.10) <= 0.1*range(10.95) [body/range=0.01]), BB within bands, MACD hist 0.2112 (rising), EMA20(477.73) < EMA50(478.43), MFI 62.5, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 471.55 (2026-04-24), held; tested prior swing high at 489.00 (2026-03-17), rejected at
Day +1 (2026-06-15): Volume 2.4x avg, no pattern, BB +2.2 sigma, MACD hist 1.2628 (rising), EMA20(479.07) > EMA50(478.95), MFI 67.3, price above VWAP, tested prior swing high at 499.99 (2026-05-06), rejected at
Day +2 (2026-06-16): Volume 1.3x avg, no pattern, BB +2.7 sigma, MACD hist 2.2626 (rising), EMA20(480.87) > EMA50(479.70), MFI 69.6, price above VWAP, tested prior swing high at 500.01 (2026-04-10), rejected at
Day +3 (2026-06-17): Volume 3.8x avg, no pattern, BB +3.9 sigma, MACD hist 5.5324 (rising), EMA20(486.61) > EMA50(482.10), MFI 80.3, price above VWAP
Day +4 (2026-06-18): Volume 1.6x avg, no pattern, BB +2.3 sigma, MACD hist 6.3032 (rising), EMA20(490.32) > EMA50(483.81), MFI 73.5, price above VWAP

### Flow divergence check

5 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-06-02: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-06-04: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-08: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-06-11: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-12: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
---

## STOCK 3 — THCCL (full company name not independently confirmed, company-page fetch out of scope this round)

### Data coverage & ticker identity

Report window: **2026-06-15 to 2026-07-09**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **THCCL** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `THCCL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Announcements/catalyst-checking remains out of scope.** No claim of "catalyst-free" is made for THCCL.

**Chart structure:** 06-15 through 06-24 opens already elevated (RSI 60-77) then bleeds down through 06-29/06-30. 07-01 is the first clear reversal up, then a base 07-02 to 07-06. 07-07 is the volume breakout (3.79x the 20-day average, +7.3% on the day), continued elevated volume into 07-08/07-09, closing the window at 73.21 with a confirmed Bullish Engulfing on 07-09.

### Core day-by-day table (OHLC, candles, trend)

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

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-15 | 86.30 | 94,625,532 | 6,690,625 | 3.08 | 71.08 | below | 64.92 | 61.82 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-16 | 83.50 | 91,463,345 | 4,775,243 | 3.11 | 70.42 | below | 65.08 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-06-17 | 81.10 | 88,843,060 | 2,864,618 | 3.03 | 69.95 | below | 66.87 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-06-18 | 81.70 | 92,660,629 | 2,203,475 | 2.97 | 69.79 | below | 68.88 | 61.82 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-19 | 78.20 | 90,709,957 | 1,075,535 | 2.97 | 69.60 | below | 68.88 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-06-22 | 74.00 | 88,456,842 | -757,882 | 2.90 | 69.30 | below | 68.88 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-06-23 | 73.50 | 91,068,289 | -476,649 | 2.79 | 68.98 | below | 68.88 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-06-24 | 73.10 | 89,428,909 | -1,359,392 | 2.65 | 68.82 | below | 69.32 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-06-25 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-26 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-29 | 67.10 | 87,848,430 | -2,544,751 | 2.65 | 68.62 | below | 68.65 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-06-30 | 51.10 | 88,832,614 | -2,408,480 | 2.60 | 68.50 | below | 68.03 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-07-01 | 46.80 | 95,069,714 | 1,624,845 | 2.65 | 68.37 | above | 67.42 | 61.82 | cloud not yet formed (insufficient history) | — |
| 2026-07-02 | 55.00 | 92,452,939 | 75,105 | 2.61 | 68.35 | below | 67.42 | 62.22 | cloud not yet formed (insufficient history) | — |
| 2026-07-03 | 59.50 | 94,227,204 | 32,658 | 2.57 | 68.34 | below | 67.25 | 62.22 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-07-06 | 57.60 | 97,538,036 | 1,510,708 | 2.55 | 68.38 | above | 67.15 | 62.58 | cloud not yet formed (insufficient history) | — |
| 2026-07-07 | 70.20 | 117,938,532 | 13,735,433 | 2.81 | 70.00 | above | 69.90 | 64.12 | cloud not yet formed (insufficient history) | — |
| 2026-07-08 | 56.40 | 101,696,873 | 8,850,079 | 3.15 | 70.29 | above | 70.03 | 64.30 | cloud not yet formed (insufficient history) | — |
| 2026-07-09 | 67.40 | 118,780,792 | 9,927,002 | 3.42 | 70.80 | above | 70.52 | 66.84 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-06-30 = Day 0).

Day -9 (2026-06-15): Volume 1.0x avg, no pattern, BB +1.5 sigma, MACD hist 1.3861 (falling), EMA20(62.17) > EMA50(58.28), MFI 86.3, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing high at 72.20 (2026-06-09), rejected at
Day -8 (2026-06-16): Volume 0.6x avg, no pattern, BB +1.2 sigma, MACD hist 1.1121 (falling), EMA20(62.79) > EMA50(58.69), MFI 83.5, price below VWAP, tested prior swing high at 72.20 (2026-06-09), rejected at
Day -7 (2026-06-17): Volume 0.5x avg, no pattern, BB within bands, MACD hist 0.8122 (falling), EMA20(63.29) > EMA50(59.06), MFI 81.1, price below VWAP
Day -6 (2026-06-18): Volume 0.7x avg, no pattern, BB +1.0 sigma, MACD hist 0.6324 (falling), EMA20(63.86) > EMA50(59.46), MFI 81.7, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day -5 (2026-06-19): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.3528 (falling), EMA20(64.21) > EMA50(59.78), MFI 78.2, price below VWAP
Day -4 (2026-06-22): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.0563 (falling), EMA20(64.43) > EMA50(60.04), MFI 74.0, price below VWAP, tested prior swing low at 65.13 (2026-06-11), held
Day -3 (2026-06-23): Volume 0.5x avg, no pattern, BB within bands, MACD hist -0.1485 (falling), EMA20(64.65) > EMA50(60.30), MFI 73.5, price below VWAP, tested prior swing low at 65.13 (2026-06-11), held
Day -2 (2026-06-24): Volume 0.3x avg, no pattern, BB within bands, MACD hist -0.3065 (falling), EMA20(64.84) > EMA50(60.55), MFI 73.1, price below VWAP, tested prior swing low at 65.13 (2026-06-11), held
Day -1 (2026-06-29): Volume 0.3x avg, no pattern, BB within bands, MACD hist -0.5225 (falling), EMA20(64.85) > EMA50(60.72), MFI 67.1, price below VWAP, tested prior swing low at 65.13 (2026-06-11), broke below
Day 0 (2026-06-30): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.6163 (falling), EMA20(64.93) > EMA50(60.92), MFI 51.1, price below VWAP, tested prior swing low at 65.13 (2026-06-11), held
Day +1 (2026-07-01): Volume 1.2x avg, no pattern, BB within bands, MACD hist -0.4905 (rising), EMA20(65.27) > EMA50(61.21), MFI 46.8, price above VWAP, tested prior swing low at 65.13 (2026-06-11), held
Day +2 (2026-07-02): Volume 0.5x avg, no pattern, BB within bands, MACD hist -0.4540 (rising), EMA20(65.51) > EMA50(61.47), MFI 55.0, price below VWAP
Day +3 (2026-07-03): Volume 0.3x avg, Doji formed (body(0.03) <= 0.1*range(2.09) [body/range=0.01]), BB within bands, MACD hist -0.4176 (rising), EMA20(65.75) > EMA50(61.73), MFI 59.5, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day +4 (2026-07-06): Volume 0.7x avg, no pattern, BB within bands, MACD hist -0.3273 (rising), EMA20(66.07) > EMA50(62.02), MFI 57.6, price above VWAP
Day +5 (2026-07-07): Volume 3.8x avg, no pattern, BB +3.1 sigma, MACD hist 0.0468 (rising), EMA20(66.84) > EMA50(62.50), MFI 70.2, price above VWAP
Day +6 (2026-07-08): Volume 3.2x avg, no pattern, BB +1.1 sigma, MACD hist 0.0238 (falling), EMA20(67.20) > EMA50(62.81), MFI 56.4, price above VWAP
Day +7 (2026-07-09): Volume 3.1x avg, Bullish Engulfing formed (prior_close(70.57)<prior_open(72.80, bearish) AND close(73.21)>open(70.49, bullish) AND open(70.49) <= prior_close(70.57) AND close(73.21) >= prior_open(72.80) [today body 70.49→73.21 engulfs prior 72.80→70.57]), BB +2.1 sigma, MACD hist 0.1532 (rising), EMA20(67.77) > EMA50(63.22), MFI 67.4, price above VWAP

### Flow divergence check

3 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-06-15: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-18: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-07-03: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
---

## STOCK 4 — FNEL (full company name not independently confirmed, company-page fetch out of scope this round)

### Data coverage & ticker identity

Report window: **2026-03-22 to 2026-04-24**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **FNEL** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `FNEL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Data-quality note (carried forward from the deepening round):** FNEL's series shows an abrupt ~90.7% single-day price adjustment on 2026-02-02 (17.70->1.65, volume 191M vs a typical 8-20M) -- a bonus/rights-issue signature, not a real return and not a wrong-ticker mixup (post-adjustment trajectory matches the user's reference prices exactly). This round's general `detect_price_cliffs()` was verified to still find exactly this same cliff (asserted in `analyze_premove.py`'s `main()`) and NOT the real 04-08 breakout day (the detector only flags price DROPS, since a bonus/rights issue mechanically dilutes price down, never up -- see the function's docstring). Indicator computation excludes bars before 2026-02-02.
**Announcements/catalyst-checking remains out of scope.**

**Chart structure:** The window opens inside a multi-week grind lower (03-24 to 04-07). 04-08 is the volume breakout day: +31.2% on 8.65x the 20-day average (212M shares) -- the single most extreme single-day reading in the whole dataset. 04-09/04-10 give back some gain before a calmer base 04-13 to 04-22, then a second violent volume spike on 04-23 (+22.3%, high 1.74 matching the user's reference) closing the window at 1.51 on 04-24.

### Core day-by-day table (OHLC, candles, trend)

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

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-03-23 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-03-24 | 48.90 | -61,432,215 | -256,027,972 | 0.1269 | 1.26 | below | 1.23 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-03-25 | 39.90 | -86,248,264 | -264,299,988 | 0.1243 | 1.24 | below | 1.23 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-03-26 | 31.40 | -119,272,988 | -287,889,077 | 0.1204 | 1.22 | below | 1.23 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-03-27 | 22.30 | -146,454,350 | -304,197,894 | 0.1154 | 1.20 | below | 1.23 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-03-30 | 21.50 | -166,257,035 | -317,399,684 | 0.1114 | 1.19 | below | 1.21 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-03-31 | 26.90 | -158,651,920 | -312,836,615 | 0.1071 | 1.19 | below | 1.21 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-04-01 | 24.90 | -148,473,426 | -316,229,447 | 0.1065 | 1.19 | above | 1.21 | 1.37 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-04-02 | 25.40 | -162,230,143 | -320,815,019 | 0.1047 | 1.18 | below | 1.21 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-04-03 | 27.20 | -155,814,417 | -319,531,874 | 0.1007 | 1.18 | below | 1.21 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-04-06 | 31.80 | -148,520,122 | -315,155,297 | 0.0971 | 1.18 | below | 1.20 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-04-07 | 34.90 | -148,520,122 | -314,372,643 | 0.0938 | 1.18 | below | 1.18 | 1.37 | cloud not yet formed (insufficient history) | — |
| 2026-04-08 | 73.80 | 63,792,345 | -124,408,857 | 0.1185 | 1.34 | above | 1.35 | 1.35 | cloud not yet formed (insufficient history) | — |
| 2026-04-09 | 78.30 | -17,817,227 | -157,052,686 | 0.1243 | 1.37 | above | 1.35 | 1.35 | cloud not yet formed (insufficient history) | — |
| 2026-04-10 | 70.20 | -61,007,075 | -171,449,302 | 0.1240 | 1.38 | above | 1.36 | 1.35 | cloud not yet formed (insufficient history) | — |
| 2026-04-13 | 65.40 | -94,611,414 | -197,586,010 | 0.1251 | 1.37 | below | 1.36 | 1.35 | cloud not yet formed (insufficient history) | — |
| 2026-04-14 | 71.90 | -31,981,179 | -250,580,824 | 0.1262 | 1.37 | below | 1.36 | 1.35 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-04-15 | 77.30 | 3,664,299 | -274,344,476 | 0.1250 | 1.37 | above | 1.36 | 1.35 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-04-16 | 81.30 | 24,774,416 | -284,899,534 | 0.1197 | 1.38 | above | 1.37 | 1.35 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-04-17 | 84.60 | 55,287,726 | -266,591,548 | 0.1154 | 1.38 | above | 1.37 | 1.35 | cloud not yet formed (insufficient history) | — |
| 2026-04-20 | 79.10 | 16,337,495 | -261,027,230 | 0.1179 | 1.38 | above | 1.42 | 1.35 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-04-21 | 79.70 | -11,669,498 | -273,030,227 | 0.1145 | 1.38 | below | 1.46 | 1.35 | cloud not yet formed (insufficient history) | — |
| 2026-04-22 | 82.20 | -11,669,498 | -290,176,958 | 0.1149 | 1.38 | below | 1.41 | 1.35 | cloud not yet formed (insufficient history) | — |
| 2026-04-23 | 88.20 | 275,153,850 | -65,369,469 | 0.1331 | 1.44 | above | 1.52 | 1.42 | cloud not yet formed (insufficient history) | — |
| 2026-04-24 | 76.60 | 146,862,302 | -173,134,370 | 0.1414 | 1.46 | above | 1.52 | 1.42 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-04-06 = Day 0).

Day -9 (2026-03-24): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.0068 (rising), EMA20(1.29) < EMA50(1.41), MFI 48.9, price below VWAP
Day -8 (2026-03-25): Volume 1.2x avg, no pattern, BB within bands, MACD hist 0.0091 (rising), EMA20(1.28) < EMA50(1.41), MFI 39.9, price below VWAP
Day -7 (2026-03-26): Volume 1.6x avg, no pattern, BB within bands, MACD hist 0.0077 (falling), EMA20(1.27) < EMA50(1.40), MFI 31.4, price below VWAP, tested prior swing low at 1.16 (2026-02-20), held
Day -6 (2026-03-27): Volume 1.4x avg, no pattern, BB -1.0 sigma, MACD hist 0.0052 (falling), EMA20(1.26) < EMA50(1.39), MFI 22.3, price below VWAP, tested prior swing low at 1.14 (2026-03-09), held
Day -5 (2026-03-30): Volume 1.0x avg, no pattern, BB -1.4 sigma, MACD hist 0.0015 (falling), EMA20(1.25) < EMA50(1.38), MFI 21.5, price below VWAP, tested prior swing low at 1.10 (2026-03-02), held
Day -4 (2026-03-31): Volume 0.4x avg, no pattern, BB -1.1 sigma, MACD hist 0.0023 (rising), EMA20(1.24) < EMA50(1.37), MFI 26.9, price below VWAP, tested prior swing low at 1.10 (2026-03-02), held
Day -3 (2026-04-01): Volume 0.6x avg, no pattern, BB within bands, MACD hist 0.0060 (rising), EMA20(1.23) < EMA50(1.36), MFI 24.9, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 1.16 (2026-02-20), held
Day -2 (2026-04-02): Volume 0.8x avg, no pattern, BB -1.2 sigma, MACD hist 0.0049 (falling), EMA20(1.22) < EMA50(1.35), MFI 25.4, price below VWAP, tested prior swing low at 1.10 (2026-03-02), held
Day -1 (2026-04-03): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.0052 (rising), EMA20(1.22) < EMA50(1.34), MFI 27.2, price below VWAP, tested prior swing low at 1.10 (2026-03-02), held
Day 0 (2026-04-06): Volume 0.5x avg, Bullish Engulfing formed (prior_close(1.14)<prior_open(1.15, bearish) AND close(1.16)>open(1.12, bullish) AND open(1.12) <= prior_close(1.14) AND close(1.16) >= prior_open(1.15) [today body 1.12→1.16 engulfs prior 1.15→1.14]), BB within bands, MACD hist 0.0071 (rising), EMA20(1.21) < EMA50(1.34), MFI 31.8, price below VWAP, tested prior swing low at 1.14 (2026-03-09), held
Day +1 (2026-04-07): Volume 0.2x avg, no pattern, BB within bands, MACD hist 0.0086 (rising), EMA20(1.21) < EMA50(1.33), MFI 34.9, price below VWAP, tested prior swing low at 1.14 (2026-03-09), held
Day +2 (2026-04-08): Volume 8.7x avg, no pattern, BB +3.9 sigma, MACD hist 0.0365 (rising), EMA20(1.24) < EMA50(1.34), MFI 73.8, price above VWAP
Day +3 (2026-04-09): Volume 2.9x avg, no pattern, BB +2.3 sigma, MACD hist 0.0456 (rising), EMA20(1.26) < EMA50(1.35), MFI 78.3, price above VWAP
Day +4 (2026-04-10): Volume 1.5x avg, Doji formed (body(0.01) <= 0.1*range(0.12) [body/range=0.08]), BB +1.8 sigma, MACD hist 0.0474 (rising), EMA20(1.28) < EMA50(1.35), MFI 70.2, price above VWAP
Day +5 (2026-04-13): Volume 1.1x avg, no pattern, BB within bands, MACD hist 0.0381 (falling), EMA20(1.28) < EMA50(1.35), MFI 65.4, price below VWAP
Day +6 (2026-04-14): Volume 1.9x avg, Doji formed (body(0.01) <= 0.1*range(0.13) [body/range=0.08]), BB within bands, MACD hist 0.0318 (falling), EMA20(1.29) < EMA50(1.35), MFI 71.9, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day +7 (2026-04-15): Volume 1.1x avg, no pattern, BB +1.1 sigma, MACD hist 0.0302 (falling), EMA20(1.30) < EMA50(1.35), MFI 77.3, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day +8 (2026-04-16): Volume 0.6x avg, no pattern, BB +1.1 sigma, MACD hist 0.0290 (falling), EMA20(1.31) < EMA50(1.35), MFI 81.3, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day +9 (2026-04-17): Volume 0.9x avg, no pattern, BB +1.4 sigma, MACD hist 0.0300 (rising), EMA20(1.32) < EMA50(1.36), MFI 84.6, price above VWAP
Day +10 (2026-04-20): Volume 1.1x avg, no pattern, BB within bands, MACD hist 0.0245 (falling), EMA20(1.33) < EMA50(1.36), MFI 79.1, price above VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
Day +11 (2026-04-21): Volume 0.8x avg, no pattern, BB within bands, MACD hist 0.0191 (falling), EMA20(1.33) < EMA50(1.36), MFI 79.7, price below VWAP
Day +12 (2026-04-22): Volume 0.9x avg, Doji formed (body(0.00) <= 0.1*range(0.12) [body/range=0.00]), BB within bands, MACD hist 0.0145 (falling), EMA20(1.34) < EMA50(1.36), MFI 82.2, price below VWAP
Day +13 (2026-04-23): Volume 5.7x avg, no pattern, BB +2.3 sigma, MACD hist 0.0312 (rising), EMA20(1.37) > EMA50(1.37), MFI 88.2, price above VWAP
Day +14 (2026-04-24): Volume 2.3x avg, no pattern, BB +1.0 sigma, MACD hist 0.0276 (falling), EMA20(1.39) > EMA50(1.38), MFI 76.6, price above VWAP

### Flow divergence check

5 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-04-01: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-04-14: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-04-15: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-04-16: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-04-20: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
---

## STOCK 5 — MDTL

### Data coverage & ticker identity

Report window: **2026-07-08 to 2026-07-27**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **MDTL** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `MDTL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Chart structure:** 07-08 through 07-13 drifts down into a shallow low, price pushing to a Bollinger extreme (-2.3 sigma on 07-14), a Doji on 07-15 marking the low. The real move happens fast: 07-24 is both the first >2x-volume day (6.52x) AND the MACD histogram's sign flip AND the breakout day simultaneously -- a same-day confirmation rather than a staged sequence like AICL/SHFA showed. Window closes 6.15 on 07-27, near the open (6.85) after an intraday pullback.

### Core day-by-day table (OHLC, candles, trend)

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-08 | 5.83 | 6.25 | 5.83 | 6.00 | 7,217,496 | 4,119,824 | 1.75 | — | — | -0.1% vs SMA20(6.01) | insufficient history | within bands | -0.0173 | rising | EMA20(5.95) > EMA50(5.94) | 51.80 | tested prior swing low at 5.91 (2026-06-17), held; tested prior swing high at 6.24 (2026-05-13), rejected at |
| 2026-07-09 | 6.00 | 6.28 | 5.95 | 6.10 | 7,426,211 | 4,330,817 | 1.71 | — | — | +1.4% vs SMA20(6.02) | insufficient history | within bands | -0.0044 | rising | EMA20(5.96) > EMA50(5.94) | 55.60 | tested prior swing low at 5.91 (2026-06-17), held; tested prior swing high at 6.24 (2026-05-13), rejected at |
| 2026-07-10 | 6.10 | 6.26 | 6.00 | 6.03 | 1,142,161 | 4,325,816 | 0.26 | — | — | +0.2% vs SMA20(6.02) | insufficient history | within bands | -0.0007 | rising | EMA20(5.97) > EMA50(5.95) | 52.50 | tested prior swing low at 5.91 (2026-06-17), held; tested prior swing high at 6.24 (2026-05-13), rejected at |
| 2026-07-13 | 5.93 | 6.00 | 5.83 | 5.84 | 1,170,912 | 4,083,799 | 0.29 | — | — | -2.8% vs SMA20(6.01) | insufficient history | -1.1 sigma | -0.0107 | falling | EMA20(5.96) > EMA50(5.94) | 45.10 | tested prior swing low at 5.91 (2026-06-17), broke below; tested prior swing high at 5.91 (2026-05-25), rejected at |
| 2026-07-14 | 5.81 | 5.84 | 5.50 | 5.56 | 2,141,551 | 3,897,782 | 0.55 | — | — | -7.1% vs SMA20(5.98) | insufficient history | -2.3 sigma | -0.0344 | falling | EMA20(5.92) < EMA50(5.93) | 36.90 | tested prior swing high at 5.91 (2026-05-25), rejected at |
| 2026-07-15 | 5.67 | 5.77 | 5.57 | 5.68 | 851,467 | 3,827,820 | 0.22 | Doji | body(0.01) <= 0.1*range(0.20) [body/range=0.05] | -4.8% vs SMA20(5.97) | -3.4% vs SMA50(5.88) | -1.5 sigma | -0.0399 | falling | EMA20(5.90) < EMA50(5.92) | 41.80 | tested prior swing low at 5.50 (2026-07-14), held |
| 2026-07-16 | 5.68 | 5.88 | 5.68 | 5.79 | 658,748 | 3,778,071 | 0.17 | — | — | -2.8% vs SMA20(5.96) | -1.5% vs SMA50(5.88) | within bands | -0.0343 | rising | EMA20(5.89) < EMA50(5.91) | 46.00 | tested prior swing low at 5.67 (2026-05-05), held; tested prior swing high at 5.91 (2026-05-25), rejected at |
| 2026-07-17 | 5.67 | 5.88 | 5.66 | 5.67 | 223,845 | 3,673,264 | 0.06 | Doji | body(0.00) <= 0.1*range(0.22) [body/range=0.00] | -4.6% vs SMA20(5.94) | -3.4% vs SMA50(5.87) | -1.3 sigma | -0.0365 | falling | EMA20(5.87) < EMA50(5.90) | 42.40 | tested prior swing low at 5.67 (2026-05-05), held; tested prior swing high at 5.91 (2026-05-25), rejected at |
| 2026-07-20 | 5.74 | 5.74 | 5.51 | 5.57 | 427,229 | 1,870,775 | 0.23 | — | — | -5.5% vs SMA20(5.90) | -5.0% vs SMA50(5.86) | -1.8 sigma | -0.0422 | falling | EMA20(5.84) < EMA50(5.89) | 39.70 | tested prior swing low at 5.50 (2026-07-14), held |
| 2026-07-21 | 5.69 | 5.78 | 5.60 | 5.60 | 798,979 | 1,743,693 | 0.46 | — | — | -4.5% vs SMA20(5.86) | -4.4% vs SMA50(5.86) | -1.5 sigma | -0.0413 | rising | EMA20(5.81) < EMA50(5.88) | 40.90 | tested prior swing low at 5.67 (2026-05-05), broke below |
| 2026-07-22 | 5.56 | 5.73 | 5.43 | 5.46 | 1,115,480 | 1,748,600 | 0.64 | — | — | -6.3% vs SMA20(5.83) | -6.7% vs SMA50(5.85) | -2.1 sigma | -0.0472 | falling | EMA20(5.78) < EMA50(5.86) | 37.10 | tested prior swing low at 5.50 (2026-07-14), broke below |
| 2026-07-23 | 5.60 | 5.60 | 5.36 | 5.38 | 423,606 | 1,679,632 | 0.25 | — | — | -7.2% vs SMA20(5.80) | -7.9% vs SMA50(5.84) | -2.1 sigma | -0.0531 | falling | EMA20(5.74) < EMA50(5.84) | 35.10 | — |
| 2026-07-24 | 5.38 | 6.38 | 5.26 | 6.38 | 15,731,176 | 2,412,723 | 6.52 | Bullish Engulfing | prior_close(5.38)<prior_open(5.60, bearish) AND close(6.38)>open(5.38, bullish) AND open(5.38) <= prior_close(5.38) AND close(6.38) >= prior_open(5.60) [today body 5.38→6.38 engulfs prior 5.60→5.38] | +9.8% vs SMA20(5.81) | +9.1% vs SMA50(5.85) | +2.5 sigma | 0.0104 | rising | EMA20(5.80) < EMA50(5.87) | 62.50 | tested prior swing high at 6.40 (2026-06-12), rejected at |
| 2026-07-27 | 6.85 | 6.90 | 6.10 | 6.15 | 28,843,959 | 3,782,169 | 7.63 | — | — | +5.5% vs SMA20(5.83) | +5.0% vs SMA50(5.86) | +1.3 sigma | 0.0356 | rising | EMA20(5.84) < EMA50(5.88) | 56.60 | tested prior swing high at 7.00 (2026-06-18), rejected at |

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-08 | 75.80 | 55,608,097 | -43,255,254 | 0.2670 | 6.03 | below | 6.03 | 6.29 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-07-09 | 80.90 | 63,034,308 | -43,930,364 | 0.2715 | 6.07 | above | 6.04 | 6.29 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-07-10 | 54.70 | 61,892,147 | -44,808,949 | 0.2707 | 6.07 | below | 6.04 | 6.30 | cloud not yet formed (insufficient history) | — |
| 2026-07-13 | 59.00 | 60,721,235 | -45,842,107 | 0.2656 | 6.06 | below | 6.04 | 6.30 | cloud not yet formed (insufficient history) | — |
| 2026-07-14 | 57.20 | 58,579,684 | -47,227,816 | 0.2709 | 6.01 | below | 5.89 | 6.25 | cloud not yet formed (insufficient history) | — |
| 2026-07-15 | 61.80 | 59,431,151 | -47,142,669 | 0.2666 | 6.00 | below | 5.89 | 6.25 | cloud not yet formed (insufficient history) | — |
| 2026-07-16 | 64.90 | 60,089,899 | -47,076,795 | 0.2618 | 5.99 | below | 5.89 | 6.25 | cloud not yet formed (insufficient history) | — |
| 2026-07-17 | 67.70 | 59,866,054 | -47,280,290 | 0.2588 | 5.99 | below | 5.89 | 6.25 | cloud not yet formed (insufficient history) | — |
| 2026-07-20 | 69.70 | 59,438,825 | -47,484,617 | 0.2568 | 5.98 | below | 5.89 | 6.25 | cloud not yet formed (insufficient history) | — |
| 2026-07-21 | 69.00 | 60,237,804 | -48,283,596 | 0.2534 | 5.97 | below | 5.89 | 6.25 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-07-22 | 70.50 | 59,122,324 | -49,175,980 | 0.2568 | 5.95 | below | 5.84 | 6.21 | cloud not yet formed (insufficient history) | — |
| 2026-07-23 | 67.70 | 58,698,718 | -49,528,985 | 0.2556 | 5.94 | below | 5.68 | 6.18 | cloud not yet formed (insufficient history) | — |
| 2026-07-24 | 82.30 | 74,429,894 | -33,797,809 | 0.3173 | 5.97 | above | 5.82 | 6.13 | cloud not yet formed (insufficient history) | — |
| 2026-07-27 | 90.90 | 45,585,935 | -59,036,273 | 0.3518 | 6.14 | above | 6.08 | 6.13 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-07-23 = Day 0).

Day -11 (2026-07-08): Volume 1.8x avg, no pattern, BB within bands, MACD hist -0.0173 (rising), EMA20(5.95) > EMA50(5.94), MFI 75.8, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 5.91 (2026-06-17), held; tested prior swing high at 6.24 (2026-05-13), rejected at
Day -10 (2026-07-09): Volume 1.7x avg, no pattern, BB within bands, MACD hist -0.0044 (rising), EMA20(5.96) > EMA50(5.94), MFI 80.9, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 5.91 (2026-06-17), held; tested prior swing high at 6.24 (2026-05-13), rejected at
Day -9 (2026-07-10): Volume 0.3x avg, no pattern, BB within bands, MACD hist -0.0007 (rising), EMA20(5.97) > EMA50(5.95), MFI 54.7, price below VWAP, tested prior swing low at 5.91 (2026-06-17), held; tested prior swing high at 6.24 (2026-05-13), rejected at
Day -8 (2026-07-13): Volume 0.3x avg, no pattern, BB -1.1 sigma, MACD hist -0.0107 (falling), EMA20(5.96) > EMA50(5.94), MFI 59.0, price below VWAP, tested prior swing low at 5.91 (2026-06-17), broke below; tested prior swing high at 5.91 (2026-05-25), rejected at
Day -7 (2026-07-14): Volume 0.6x avg, no pattern, BB -2.3 sigma, MACD hist -0.0344 (falling), EMA20(5.92) < EMA50(5.93), MFI 57.2, price below VWAP, tested prior swing high at 5.91 (2026-05-25), rejected at
Day -6 (2026-07-15): Volume 0.2x avg, Doji formed (body(0.01) <= 0.1*range(0.20) [body/range=0.05]), BB -1.5 sigma, MACD hist -0.0399 (falling), EMA20(5.90) < EMA50(5.92), MFI 61.8, price below VWAP, tested prior swing low at 5.50 (2026-07-14), held
Day -5 (2026-07-16): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.0343 (rising), EMA20(5.89) < EMA50(5.91), MFI 64.9, price below VWAP, tested prior swing low at 5.67 (2026-05-05), held; tested prior swing high at 5.91 (2026-05-25), rejected at
Day -4 (2026-07-17): Volume 0.1x avg, Doji formed (body(0.00) <= 0.1*range(0.22) [body/range=0.00]), BB -1.3 sigma, MACD hist -0.0365 (falling), EMA20(5.87) < EMA50(5.90), MFI 67.7, price below VWAP, tested prior swing low at 5.67 (2026-05-05), held; tested prior swing high at 5.91 (2026-05-25), rejected at
Day -3 (2026-07-20): Volume 0.2x avg, no pattern, BB -1.8 sigma, MACD hist -0.0422 (falling), EMA20(5.84) < EMA50(5.89), MFI 69.7, price below VWAP, tested prior swing low at 5.50 (2026-07-14), held
Day -2 (2026-07-21): Volume 0.5x avg, no pattern, BB -1.5 sigma, MACD hist -0.0413 (rising), EMA20(5.81) < EMA50(5.88), MFI 69.0, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 5.67 (2026-05-05), broke below
Day -1 (2026-07-22): Volume 0.6x avg, no pattern, BB -2.1 sigma, MACD hist -0.0472 (falling), EMA20(5.78) < EMA50(5.86), MFI 70.5, price below VWAP, tested prior swing low at 5.50 (2026-07-14), broke below
Day 0 (2026-07-23): Volume 0.2x avg, no pattern, BB -2.1 sigma, MACD hist -0.0531 (falling), EMA20(5.74) < EMA50(5.84), MFI 67.7, price below VWAP
Day +1 (2026-07-24): Volume 6.5x avg, Bullish Engulfing formed (prior_close(5.38)<prior_open(5.60, bearish) AND close(6.38)>open(5.38, bullish) AND open(5.38) <= prior_close(5.38) AND close(6.38) >= prior_open(5.60) [today body 5.38→6.38 engulfs prior 5.60→5.38]), BB +2.5 sigma, MACD hist 0.0104 (rising), EMA20(5.80) < EMA50(5.87), MFI 82.3, price above VWAP, tested prior swing high at 6.40 (2026-06-12), rejected at
Day +2 (2026-07-27): Volume 7.6x avg, no pattern, BB +1.3 sigma, MACD hist 0.0356 (rising), EMA20(5.84) < EMA50(5.88), MFI 90.9, price above VWAP, tested prior swing high at 7.00 (2026-06-18), rejected at

### Flow divergence check

3 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-07-08: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-07-09: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-07-21: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
---

## STOCK 6 — FPJM

### Data coverage & ticker identity

Report window: **2026-07-29 to 2026-09-03**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **FPJM** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `FPJM` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Chart structure:** This is the largest percentage move in the whole dataset (10.02 -> 27.80, +177%, over five weeks). 07-29 through 08-17 is a slow grind higher on ordinary volume; 08-18 is the first vol>2x day and the breakout day together (2.76x). From there the climb continues through late August into a final push, closing the window at 23.15 on 09-03 -- below the day's own open (27.99) and well off the window's peak, a pullback from an extended run rather than a single clean breakout day the way MDTL or THCCL showed.

### Core day-by-day table (OHLC, candles, trend)

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-29 | 10.32 | 10.95 | 10.32 | 10.60 | 468,695 | 1,810,196 | 0.26 | — | — | +3.2% vs SMA20(10.27) | insufficient history | within bands | -0.1136 | falling | EMA20(10.18) > EMA50(9.27) | 54.90 | — |
| 2026-07-30 | 10.50 | 11.15 | 10.50 | 10.88 | 388,268 | 1,823,314 | 0.21 | — | — | +4.4% vs SMA20(10.43) | insufficient history | within bands | -0.0997 | rising | EMA20(10.25) > EMA50(9.34) | 56.60 | tested prior swing high at 11.30 (2026-07-27), rejected at |
| 2026-07-31 | 10.88 | 11.58 | 10.45 | 11.05 | 1,572,577 | 1,888,888 | 0.83 | — | — | +4.3% vs SMA20(10.59) | insufficient history | within bands | -0.0808 | rising | EMA20(10.33) > EMA50(9.40) | 57.70 | — |
| 2026-08-03 | 11.08 | 11.30 | 10.61 | 10.67 | 405,926 | 1,845,123 | 0.22 | — | — | -0.4% vs SMA20(10.71) | insufficient history | within bands | -0.0947 | falling | EMA20(10.36) > EMA50(9.45) | 54.50 | tested prior swing high at 11.30 (2026-07-27), rejected at |
| 2026-08-04 | 10.85 | 11.25 | 10.51 | 10.85 | 784,719 | 1,746,015 | 0.45 | Doji | body(0.00) <= 0.1*range(0.74) [body/range=0.00] | +0.6% vs SMA20(10.78) | +19.9% vs SMA50(9.05) | within bands | -0.0925 | rising | EMA20(10.41) > EMA50(9.51) | 55.70 | tested prior swing high at 11.30 (2026-07-27), rejected at |
| 2026-08-05 | 11.07 | 11.20 | 10.80 | 10.82 | 199,084 | 1,654,597 | 0.12 | — | — | -0.6% vs SMA20(10.88) | +18.9% vs SMA50(9.10) | within bands | -0.0935 | falling | EMA20(10.44) > EMA50(9.56) | 55.40 | tested prior swing high at 11.30 (2026-07-27), rejected at |
| 2026-08-06 | 10.99 | 11.00 | 10.68 | 10.75 | 335,712 | 1,607,671 | 0.21 | — | — | -1.9% vs SMA20(10.96) | +17.3% vs SMA50(9.16) | within bands | -0.0987 | falling | EMA20(10.47) > EMA50(9.61) | 54.80 | — |
| 2026-08-07 | 10.76 | 10.90 | 10.50 | 10.63 | 169,732 | 1,488,805 | 0.11 | — | — | -3.2% vs SMA20(10.98) | +15.1% vs SMA50(9.23) | within bands | -0.1094 | falling | EMA20(10.49) > EMA50(9.65) | 53.60 | — |
| 2026-08-10 | 10.52 | 10.87 | 10.39 | 10.42 | 214,113 | 1,369,853 | 0.16 | — | — | -4.7% vs SMA20(10.94) | +12.1% vs SMA50(9.30) | within bands | -0.1283 | falling | EMA20(10.48) > EMA50(9.68) | 51.40 | — |
| 2026-08-11 | 10.50 | 10.54 | 10.25 | 10.30 | 144,143 | 1,308,471 | 0.11 | — | — | -4.9% vs SMA20(10.83) | +10.2% vs SMA50(9.35) | within bands | -0.1454 | falling | EMA20(10.46) > EMA50(9.70) | 50.20 | — |
| 2026-08-12 | 10.48 | 10.48 | 10.30 | 10.33 | 71,327 | 1,278,199 | 0.06 | — | — | -3.2% vs SMA20(10.67) | +9.9% vs SMA50(9.40) | within bands | -0.1506 | falling | EMA20(10.45) > EMA50(9.73) | 50.50 | — |
| 2026-08-13 | 10.48 | 10.48 | 9.99 | 10.02 | 170,629 | 954,337 | 0.18 | — | — | -5.1% vs SMA20(10.56) | +6.0% vs SMA50(9.45) | -1.4 sigma | -0.1694 | falling | EMA20(10.41) > EMA50(9.74) | 47.20 | — |
| 2026-08-14 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-08-17 | 10.02 | 11.02 | 9.90 | 11.02 | 877,698 | 878,179 | 1.00 | Bullish Engulfing | prior_close(10.02)<prior_open(10.48, bearish) AND close(11.02)>open(10.02, bullish) AND open(10.02) <= prior_close(10.02) AND close(11.02) >= prior_open(10.48) [today body 10.02→11.02 engulfs prior 10.48→10.02] | +4.4% vs SMA20(10.56) | +15.8% vs SMA50(9.51) | +1.2 sigma | -0.1117 | rising | EMA20(10.47) > EMA50(9.79) | 57.10 | — |
| 2026-08-18 | 12.10 | 12.12 | 11.60 | 12.12 | 2,158,444 | 782,256 | 2.76 | Doji; Hammer | body(0.02) <= 0.1*range(0.52) [body/range=0.04] | lower_wick(0.50) >= 2*body(0.02) AND upper_wick(0.00) <= 0.3*body(0.02) AND high(12.12)-max(open,close)(12.12)=0.00 <= 0.15*range(0.52) | +14.0% vs SMA20(10.63) | +26.3% vs SMA50(9.59) | +2.9 sigma | -0.0025 | rising | EMA20(10.63) > EMA50(9.88) | 64.90 | — |
| 2026-08-19 | 12.60 | 13.33 | 12.30 | 13.33 | 3,070,702 | 832,744 | 3.69 | — | — | +23.8% vs SMA20(10.76) | +37.4% vs SMA50(9.70) | +3.3 sigma | 0.1403 | rising | EMA20(10.88) > EMA50(10.01) | 71.10 | — |
| 2026-08-20 | 13.99 | 14.66 | 13.56 | 14.66 | 1,534,694 | 865,081 | 1.77 | — | — | +33.4% vs SMA20(10.99) | +49.0% vs SMA50(9.84) | +3.2 sigma | 0.3040 | rising | EMA20(11.24) > EMA50(10.20) | 76.10 | — |
| 2026-08-21 | 15.40 | 16.13 | 15.10 | 16.13 | 5,093,176 | 1,081,128 | 4.71 | — | — | +42.4% vs SMA20(11.33) | +61.3% vs SMA50(10.00) | +3.1 sigma | 0.4805 | rising | EMA20(11.71) > EMA50(10.43) | 80.20 | — |
| 2026-08-24 | 17.70 | 17.74 | 16.51 | 17.74 | 1,138,352 | 1,051,452 | 1.08 | Doji; Hammer | body(0.04) <= 0.1*range(1.23) [body/range=0.03] | lower_wick(1.19) >= 2*body(0.04) AND upper_wick(0.00) <= 0.3*body(0.04) AND high(17.74)-max(open,close)(17.74)=0.00 <= 0.15*range(1.23) | +51.7% vs SMA20(11.69) | +74.0% vs SMA50(10.20) | +2.9 sigma | 0.6636 | rising | EMA20(12.28) > EMA50(10.72) | 83.50 | — |
| 2026-08-25 | 18.99 | 19.51 | 18.60 | 19.51 | 1,005,721 | 1,032,291 | 0.97 | — | — | +61.0% vs SMA20(12.12) | +87.1% vs SMA50(10.43) | +2.8 sigma | 0.8499 | rising | EMA20(12.97) > EMA50(11.06) | 86.20 | — |
| 2026-08-26 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-08-27 | 21.40 | 21.46 | 20.50 | 21.46 | 1,379,223 | 1,059,147 | 1.30 | Doji; Hammer | body(0.06) <= 0.1*range(0.96) [body/range=0.06] | lower_wick(0.90) >= 2*body(0.06) AND upper_wick(0.00) <= 0.3*body(0.06) AND high(21.46)-max(open,close)(21.46)=0.00 <= 0.15*range(0.96) | +69.5% vs SMA20(12.66) | +100.5% vs SMA50(10.70) | +2.6 sigma | 1.04 | rising | EMA20(13.78) > EMA50(11.47) | 88.50 | — |
| 2026-08-28 | 22.99 | 23.61 | 22.55 | 23.61 | 1,469,520 | 1,109,188 | 1.32 | — | — | +77.3% vs SMA20(13.32) | +114.3% vs SMA50(11.02) | +2.5 sigma | 1.23 | rising | EMA20(14.72) > EMA50(11.95) | 90.40 | — |
| 2026-08-31 | 23.90 | 25.97 | 21.25 | 21.25 | 3,432,498 | 1,261,400 | 2.72 | — | — | +53.6% vs SMA20(13.83) | +88.3% vs SMA50(11.28) | +1.7 sigma | 1.12 | falling | EMA20(15.34) > EMA50(12.31) | 75.80 | — |
| 2026-09-01 | 19.31 | 23.38 | 19.13 | 23.38 | 1,615,655 | 1,263,553 | 1.28 | Piercing Line | open(19.31) < prior_low(21.25) AND prior_mid(22.57) < close(23.38) < prior_open(23.90) | +61.8% vs SMA20(14.45) | +101.7% vs SMA50(11.59) | +1.9 sigma | 1.11 | falling | EMA20(16.10) > EMA50(12.74) | 79.10 | — |
| 2026-09-02 | 25.15 | 25.72 | 25.15 | 25.72 | 209,524 | 1,253,733 | 0.17 | — | — | +69.2% vs SMA20(15.20) | +115.4% vs SMA50(11.94) | +2.0 sigma | 1.18 | rising | EMA20(17.02) > EMA50(13.25) | 82.00 | — |
| 2026-09-03 | 27.99 | 28.29 | 23.15 | 23.15 | 18,970,407 | 2,163,018 | 8.77 | — | — | +46.4% vs SMA20(15.82) | +89.1% vs SMA50(12.24) | +1.3 sigma | 0.9729 | falling | EMA20(17.60) > EMA50(13.64) | 70.40 | — |

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-29 | 41.60 | 2,912,921 | -1,535,897 | 1.02 | 10.62 | below | 10.61 | 11.10 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-07-30 | 37.50 | 3,301,189 | -1,470,190 | 0.9910 | 10.72 | above | 10.22 | 11.10 | cloud not yet formed (insufficient history) | — |
| 2026-07-31 | 35.10 | 4,873,766 | -1,372,774 | 1.00 | 10.92 | above | 10.27 | 11.10 | cloud not yet formed (insufficient history) | — |
| 2026-08-03 | 30.70 | 4,467,840 | -1,708,104 | 0.9787 | 10.91 | below | 10.27 | 11.10 | cloud not yet formed (insufficient history) | — |
| 2026-08-04 | 30.50 | 5,252,559 | -1,771,730 | 0.9617 | 10.90 | below | 10.27 | 11.10 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-08-05 | 45.20 | 5,053,475 | -1,950,906 | 0.9215 | 10.90 | below | 10.27 | 11.10 | cloud not yet formed (insufficient history) | — |
| 2026-08-06 | 51.50 | 4,717,763 | -2,139,744 | 0.8786 | 10.90 | below | 10.90 | 11.10 | cloud not yet formed (insufficient history) | — |
| 2026-08-07 | 68.30 | 4,548,031 | -2,199,150 | 0.8444 | 10.89 | below | 10.90 | 11.10 | cloud not yet formed (insufficient history) | — |
| 2026-08-10 | 60.30 | 4,333,918 | -2,386,499 | 0.8184 | 10.87 | below | 10.95 | 11.34 | cloud not yet formed (insufficient history) | — |
| 2026-08-11 | 64.90 | 4,189,775 | -2,480,937 | 0.7806 | 10.86 | below | 10.91 | 11.38 | cloud not yet formed (insufficient history) | — |
| 2026-08-12 | 70.40 | 4,261,102 | -2,528,489 | 0.7377 | 10.85 | below | 10.91 | 11.38 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-08-13 | 62.20 | 4,090,473 | -2,678,224 | 0.7200 | 10.83 | below | 10.64 | 11.38 | cloud not yet formed (insufficient history) | — |
| 2026-08-14 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-08-17 | 59.10 | 4,968,171 | -1,800,526 | 0.7486 | 10.80 | above | 10.57 | 11.97 | cloud not yet formed (insufficient history) | — |
| 2026-08-18 | 77.00 | 7,126,615 | 357,918 | 0.7737 | 11.11 | above | 11.01 | 11.97 | cloud not yet formed (insufficient history) | — |
| 2026-08-19 | 87.60 | 10,197,317 | 3,428,620 | 0.8049 | 11.63 | above | 11.62 | 11.97 | cloud not yet formed (insufficient history) | — |
| 2026-08-20 | 89.10 | 11,732,011 | 4,963,314 | 0.8424 | 11.96 | above | 12.28 | 11.97 | cloud not yet formed (insufficient history) | — |
| 2026-08-21 | 92.50 | 16,825,187 | 10,056,490 | 0.8872 | 13.06 | above | 13.02 | 12.54 | cloud not yet formed (insufficient history) | — |
| 2026-08-24 | 95.00 | 17,963,539 | 11,194,842 | 0.9388 | 13.32 | above | 13.82 | 13.34 | cloud not yet formed (insufficient history) | — |
| 2026-08-25 | 95.30 | 18,969,260 | 12,200,563 | 0.9982 | 13.62 | above | 14.71 | 14.23 | cloud not yet formed (insufficient history) | — |
| 2026-08-26 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-08-27 | 95.80 | 20,348,483 | 13,579,786 | 1.07 | 14.11 | above | 15.68 | 15.21 | cloud not yet formed (insufficient history) | — |
| 2026-08-28 | 97.50 | 21,818,003 | 15,049,306 | 1.14 | 14.70 | above | 16.75 | 16.28 | cloud not yet formed (insufficient history) | — |
| 2026-08-31 | 77.00 | 18,385,505 | 11,616,808 | 1.40 | 15.77 | above | 18.79 | 17.46 | cloud not yet formed (insufficient history) | — |
| 2026-09-01 | 70.60 | 20,001,160 | 13,232,463 | 1.60 | 16.13 | above | 19.13 | 17.46 | cloud not yet formed (insufficient history) | — |
| 2026-09-02 | 71.20 | 20,210,684 | 13,441,987 | 1.66 | 16.20 | above | 19.77 | 17.93 | cloud not yet formed (insufficient history) | — |
| 2026-09-03 | 32.70 | 1,240,277 | -5,528,420 | 1.90 | 19.71 | above | 21.70 | 19.09 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-08-13 = Day 0).

Day -11 (2026-07-29): Volume 0.3x avg, no pattern, BB within bands, MACD hist -0.1136 (falling), EMA20(10.18) > EMA50(9.27), MFI 41.6, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day -10 (2026-07-30): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.0997 (rising), EMA20(10.25) > EMA50(9.34), MFI 37.5, price above VWAP, tested prior swing high at 11.30 (2026-07-27), rejected at
Day -9 (2026-07-31): Volume 0.8x avg, no pattern, BB within bands, MACD hist -0.0808 (rising), EMA20(10.33) > EMA50(9.40), MFI 35.1, price above VWAP
Day -8 (2026-08-03): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.0947 (falling), EMA20(10.36) > EMA50(9.45), MFI 30.7, price below VWAP, tested prior swing high at 11.30 (2026-07-27), rejected at
Day -7 (2026-08-04): Volume 0.5x avg, Doji formed (body(0.00) <= 0.1*range(0.74) [body/range=0.00]), BB within bands, MACD hist -0.0925 (rising), EMA20(10.41) > EMA50(9.51), MFI 30.5, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing high at 11.30 (2026-07-27), rejected at
Day -6 (2026-08-05): Volume 0.1x avg, no pattern, BB within bands, MACD hist -0.0935 (falling), EMA20(10.44) > EMA50(9.56), MFI 45.2, price below VWAP, tested prior swing high at 11.30 (2026-07-27), rejected at
Day -5 (2026-08-06): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.0987 (falling), EMA20(10.47) > EMA50(9.61), MFI 51.5, price below VWAP
Day -4 (2026-08-07): Volume 0.1x avg, no pattern, BB within bands, MACD hist -0.1094 (falling), EMA20(10.49) > EMA50(9.65), MFI 68.3, price below VWAP
Day -3 (2026-08-10): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.1283 (falling), EMA20(10.48) > EMA50(9.68), MFI 60.3, price below VWAP
Day -2 (2026-08-11): Volume 0.1x avg, no pattern, BB within bands, MACD hist -0.1454 (falling), EMA20(10.46) > EMA50(9.70), MFI 64.9, price below VWAP
Day -1 (2026-08-12): Volume 0.1x avg, no pattern, BB within bands, MACD hist -0.1506 (falling), EMA20(10.45) > EMA50(9.73), MFI 70.4, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day 0 (2026-08-13): Volume 0.2x avg, no pattern, BB -1.4 sigma, MACD hist -0.1694 (falling), EMA20(10.41) > EMA50(9.74), MFI 62.2, price below VWAP
Day +1 (2026-08-17): Volume 1.0x avg, Bullish Engulfing formed (prior_close(10.02)<prior_open(10.48, bearish) AND close(11.02)>open(10.02, bullish) AND open(10.02) <= prior_close(10.02) AND close(11.02) >= prior_open(10.48) [today body 10.02→11.02 engulfs prior 10.48→10.02]), BB +1.2 sigma, MACD hist -0.1117 (rising), EMA20(10.47) > EMA50(9.79), MFI 59.1, price above VWAP
Day +2 (2026-08-18): Volume 2.8x avg, Doji; Hammer formed (body(0.02) <= 0.1*range(0.52) [body/range=0.04] | lower_wick(0.50) >= 2*body(0.02) AND upper_wick(0.00) <= 0.3*body(0.02) AND high(12.12)-max(open,close)(12.12)=0.00 <= 0.15*range(0.52)), BB +2.9 sigma, MACD hist -0.0025 (rising), EMA20(10.63) > EMA50(9.88), MFI 77.0, price above VWAP
Day +3 (2026-08-19): Volume 3.7x avg, no pattern, BB +3.3 sigma, MACD hist 0.1403 (rising), EMA20(10.88) > EMA50(10.01), MFI 87.6, price above VWAP
Day +4 (2026-08-20): Volume 1.8x avg, no pattern, BB +3.2 sigma, MACD hist 0.3040 (rising), EMA20(11.24) > EMA50(10.20), MFI 89.1, price above VWAP
Day +5 (2026-08-21): Volume 4.7x avg, no pattern, BB +3.1 sigma, MACD hist 0.4805 (rising), EMA20(11.71) > EMA50(10.43), MFI 92.5, price above VWAP
Day +6 (2026-08-24): Volume 1.1x avg, Doji; Hammer formed (body(0.04) <= 0.1*range(1.23) [body/range=0.03] | lower_wick(1.19) >= 2*body(0.04) AND upper_wick(0.00) <= 0.3*body(0.04) AND high(17.74)-max(open,close)(17.74)=0.00 <= 0.15*range(1.23)), BB +2.9 sigma, MACD hist 0.6636 (rising), EMA20(12.28) > EMA50(10.72), MFI 95.0, price above VWAP
Day +7 (2026-08-25): Volume 1.0x avg, no pattern, BB +2.8 sigma, MACD hist 0.8499 (rising), EMA20(12.97) > EMA50(11.06), MFI 95.3, price above VWAP
Day +8 (2026-08-27): Volume 1.3x avg, Doji; Hammer formed (body(0.06) <= 0.1*range(0.96) [body/range=0.06] | lower_wick(0.90) >= 2*body(0.06) AND upper_wick(0.00) <= 0.3*body(0.06) AND high(21.46)-max(open,close)(21.46)=0.00 <= 0.15*range(0.96)), BB +2.6 sigma, MACD hist 1.0380 (rising), EMA20(13.78) > EMA50(11.47), MFI 95.8, price above VWAP
Day +9 (2026-08-28): Volume 1.3x avg, no pattern, BB +2.5 sigma, MACD hist 1.2278 (rising), EMA20(14.72) > EMA50(11.95), MFI 97.5, price above VWAP
Day +10 (2026-08-31): Volume 2.7x avg, no pattern, BB +1.7 sigma, MACD hist 1.1180 (falling), EMA20(15.34) > EMA50(12.31), MFI 77.0, price above VWAP
Day +11 (2026-09-01): Volume 1.3x avg, Piercing Line formed (open(19.31) < prior_low(21.25) AND prior_mid(22.57) < close(23.38) < prior_open(23.90)), BB +1.9 sigma, MACD hist 1.1103 (falling), EMA20(16.10) > EMA50(12.74), MFI 70.6, price above VWAP
Day +12 (2026-09-02): Volume 0.2x avg, no pattern, BB +2.0 sigma, MACD hist 1.1778 (rising), EMA20(17.02) > EMA50(13.25), MFI 71.2, price above VWAP
Day +13 (2026-09-03): Volume 8.8x avg, no pattern, BB +1.3 sigma, MACD hist 0.9729 (falling), EMA20(17.60) > EMA50(13.64), MFI 32.7, price above VWAP

### Flow divergence check

3 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-07-29: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-08-04: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-08-12: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
---

## STOCK 7 — DSIL

### Data coverage & ticker identity

Report window: **2026-07-16 to 2026-08-12**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **DSIL** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `DSIL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Chart structure:** 07-16 through 07-22 is a mild base; 07-17 (day -10) already shows a >2x volume day and a positive MACD histogram flip, well ahead of the reference move-start (07-31). A Piercing Line on 07-23 and an EMA20/50 golden cross on 07-24 both land inside this early window too -- meaning by the time the reference move-start date itself arrives, several bullish signals had already fired. The actual highest-conviction breakout day is 08-03 (4.35x volume), well into the second half of the window; the close at window-end (08-12) is 15.07, a pullback from the day's own high of 17.75 (matching the user's reference) after a huge 67.5M-share volume day.

### Core day-by-day table (OHLC, candles, trend)

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-16 | 9.50 | 10.25 | 9.37 | 10.04 | 1,412,565 | 901,695 | 1.57 | — | — | +0.8% vs SMA20(9.96) | insufficient history | within bands | -0.0569 | rising | EMA20(9.91) < EMA50(10.04) | 50.40 | tested prior swing low at 9.21 (2026-06-30), held |
| 2026-07-17 | 10.34 | 10.85 | 9.85 | 10.51 | 2,099,577 | 971,335 | 2.16 | — | — | +5.6% vs SMA20(9.95) | insufficient history | +1.4 sigma | 0.0152 | rising | EMA20(9.97) < EMA50(10.06) | 55.90 | — |
| 2026-07-20 | 10.45 | 10.55 | 10.13 | 10.31 | 926,825 | 957,166 | 0.97 | — | — | +3.7% vs SMA20(9.94) | insufficient history | within bands | 0.0482 | rising | EMA20(10.00) < EMA50(10.07) | 53.20 | tested prior swing high at 10.52 (2026-07-03), rejected at |
| 2026-07-21 | 10.50 | 10.70 | 10.00 | 10.38 | 729,013 | 923,198 | 0.79 | — | — | +4.4% vs SMA20(9.94) | insufficient history | +1.1 sigma | 0.0721 | rising | EMA20(10.03) < EMA50(10.08) | 54.10 | tested prior swing high at 10.85 (2026-07-17), rejected at |
| 2026-07-22 | 10.49 | 10.50 | 10.20 | 10.34 | 399,055 | 908,408 | 0.44 | — | — | +4.1% vs SMA20(9.94) | +2.3% vs SMA50(10.11) | +1.0 sigma | 0.0819 | rising | EMA20(10.06) < EMA50(10.09) | 53.50 | tested prior swing high at 10.52 (2026-07-03), rejected at |
| 2026-07-23 | 10.15 | 10.50 | 10.05 | 10.45 | 724,780 | 907,654 | 0.80 | Piercing Line | open(10.15) < prior_low(10.20) AND prior_mid(10.41) < close(10.45) < prior_open(10.49) | +5.0% vs SMA20(9.96) | +3.3% vs SMA50(10.12) | +1.2 sigma | 0.0917 | rising | EMA20(10.10) < EMA50(10.11) | 54.90 | tested prior swing high at 10.52 (2026-07-03), rejected at |
| 2026-07-24 | 10.45 | 10.75 | 10.18 | 10.51 | 604,820 | 903,271 | 0.67 | — | — | +5.3% vs SMA20(9.98) | +3.8% vs SMA50(10.13) | +1.3 sigma | 0.0976 | rising | EMA20(10.14) > EMA50(10.12) | 55.70 | tested prior swing high at 10.85 (2026-07-17), rejected at |
| 2026-07-27 | 10.89 | 10.89 | 10.52 | 10.58 | 367,226 | 900,116 | 0.41 | — | — | +5.7% vs SMA20(10.01) | +4.4% vs SMA50(10.14) | +1.3 sigma | 0.1011 | rising | EMA20(10.18) > EMA50(10.14) | 56.70 | tested prior swing low at 10.59 (2026-06-11), broke below; tested prior swing high at 10.85 (2026-07-17), rejected at |
| 2026-07-28 | 10.68 | 10.68 | 10.03 | 10.40 | 278,621 | 788,131 | 0.35 | — | — | +3.4% vs SMA20(10.06) | +2.5% vs SMA50(10.15) | within bands | 0.0868 | falling | EMA20(10.20) > EMA50(10.15) | 53.40 | tested prior swing high at 10.52 (2026-07-03), rejected at |
| 2026-07-29 | 10.49 | 10.50 | 10.06 | 10.13 | 295,397 | 647,304 | 0.46 | — | — | +0.8% vs SMA20(10.05) | -0.3% vs SMA50(10.16) | within bands | 0.0562 | falling | EMA20(10.20) > EMA50(10.15) | 48.90 | tested prior swing high at 10.52 (2026-07-03), rejected at |
| 2026-07-30 | 10.22 | 10.30 | 9.99 | 10.06 | 432,480 | 630,687 | 0.69 | — | — | +0.1% vs SMA20(10.05) | -1.2% vs SMA50(10.18) | within bands | 0.0295 | falling | EMA20(10.18) > EMA50(10.15) | 47.70 | — |
| 2026-07-31 | 10.20 | 10.50 | 10.05 | 10.19 | 854,165 | 639,267 | 1.34 | Doji | body(0.01) <= 0.1*range(0.45) [body/range=0.02] | +1.4% vs SMA20(10.05) | -0.0% vs SMA50(10.19) | within bands | 0.0194 | falling | EMA20(10.18) > EMA50(10.15) | 50.10 | tested prior swing low at 9.99 (2026-07-30), held; tested prior swing high at 10.52 (2026-07-03), rejected at |
| 2026-08-03 | 10.45 | 11.15 | 10.15 | 11.01 | 3,454,197 | 794,810 | 4.35 | — | — | +9.1% vs SMA20(10.09) | +7.6% vs SMA50(10.23) | +1.9 sigma | 0.0642 | rising | EMA20(10.26) > EMA50(10.18) | 61.70 | tested prior swing low at 9.99 (2026-07-30), held |
| 2026-08-04 | 11.35 | 12.11 | 10.80 | 12.11 | 13,166,895 | 1,424,526 | 9.24 | — | — | +18.8% vs SMA20(10.19) | +17.7% vs SMA50(10.29) | +3.0 sigma | 0.1588 | rising | EMA20(10.44) > EMA50(10.26) | 71.30 | tested prior swing low at 10.59 (2026-06-11), held |
| 2026-08-05 | 11.50 | 12.00 | 11.30 | 11.90 | 5,698,047 | 1,681,400 | 3.39 | — | — | +15.5% vs SMA20(10.30) | +15.0% vs SMA50(10.34) | +2.2 sigma | 0.1957 | rising | EMA20(10.58) > EMA50(10.32) | 67.80 | — |
| 2026-08-06 | 12.24 | 12.80 | 11.92 | 12.58 | 4,486,648 | 1,865,674 | 2.40 | — | — | +20.4% vs SMA20(10.45) | +20.9% vs SMA50(10.41) | +2.4 sigma | 0.2509 | rising | EMA20(10.77) > EMA50(10.41) | 72.50 | — |
| 2026-08-07 | 12.61 | 13.84 | 12.40 | 13.84 | 12,582,914 | 2,475,330 | 5.08 | — | — | +29.9% vs SMA20(10.66) | +31.9% vs SMA50(10.50) | +2.8 sigma | 0.3510 | rising | EMA20(11.06) > EMA50(10.55) | 78.70 | — |
| 2026-08-10 | 14.00 | 15.22 | 13.70 | 15.22 | 10,527,189 | 2,993,963 | 3.52 | — | — | +39.1% vs SMA20(10.95) | +43.4% vs SMA50(10.61) | +2.9 sigma | 0.4810 | rising | EMA20(11.46) > EMA50(10.73) | 83.20 | — |
| 2026-08-11 | 15.74 | 16.74 | 15.35 | 16.74 | 5,515,264 | 3,242,965 | 1.70 | — | — | +47.8% vs SMA20(11.33) | +55.6% vs SMA50(10.76) | +2.9 sigma | 0.6306 | rising | EMA20(11.96) > EMA50(10.97) | 86.60 | — |
| 2026-08-12 | 16.99 | 17.75 | 15.07 | 15.07 | 67,531,272 | 6,604,348 | 10.23 | — | — | +29.7% vs SMA20(11.62) | +38.7% vs SMA50(10.87) | +1.7 sigma | 0.5797 | falling | EMA20(12.26) > EMA50(11.13) | 70.00 | — |

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-16 | 54.10 | 22,125,836 | 21,305,545 | 0.6215 | 9.89 | above | 9.68 | 11.05 | cloud not yet formed (insufficient history) | — |
| 2026-07-17 | 59.70 | 24,225,413 | 21,977,409 | 0.6485 | 10.20 | above | 9.91 | 10.78 | cloud not yet formed (insufficient history) | — |
| 2026-07-20 | 66.70 | 23,298,588 | 21,845,006 | 0.6322 | 10.22 | above | 9.91 | 10.78 | cloud not yet formed (insufficient history) | — |
| 2026-07-21 | 59.00 | 24,027,601 | 21,907,493 | 0.6370 | 10.24 | above | 9.91 | 10.78 | cloud not yet formed (insufficient history) | — |
| 2026-07-22 | 53.30 | 23,628,546 | 21,880,889 | 0.6130 | 10.25 | above | 9.91 | 10.36 | cloud not yet formed (insufficient history) | — |
| 2026-07-23 | 46.10 | 24,353,326 | 22,444,607 | 0.6013 | 10.26 | above | 9.91 | 10.12 | cloud not yet formed (insufficient history) | — |
| 2026-07-24 | 51.00 | 24,958,146 | 22,540,105 | 0.5991 | 10.28 | above | 9.91 | 9.98 | cloud not yet formed (insufficient history) | — |
| 2026-07-27 | 55.80 | 25,325,372 | 22,291,979 | 0.5834 | 10.30 | above | 9.97 | 9.96 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-07-28 | 57.30 | 25,046,751 | 22,330,557 | 0.5882 | 10.30 | above | 10.13 | 9.96 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-07-29 | 60.20 | 24,751,354 | 22,129,150 | 0.5776 | 10.30 | below | 10.37 | 9.93 | cloud not yet formed (insufficient history) | — |
| 2026-07-30 | 59.80 | 24,318,874 | 21,891,984 | 0.5585 | 10.29 | below | 10.44 | 9.93 | cloud not yet formed (insufficient history) | — |
| 2026-07-31 | 64.20 | 25,173,039 | 21,569,299 | 0.5507 | 10.29 | below | 10.44 | 9.93 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-08-03 | 76.50 | 28,627,236 | 24,056,321 | 0.5828 | 10.42 | above | 10.57 | 10.05 | cloud not yet formed (insufficient history) | — |
| 2026-08-04 | 88.90 | 41,794,131 | 37,223,216 | 0.6348 | 11.06 | above | 11.05 | 10.54 | cloud not yet formed (insufficient history) | — |
| 2026-08-05 | 90.70 | 36,096,084 | 41,293,250 | 0.6473 | 11.18 | above | 11.05 | 10.54 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-08-06 | 91.50 | 40,582,732 | 43,536,574 | 0.6653 | 11.34 | above | 11.39 | 10.88 | cloud not yet formed (insufficient history) | — |
| 2026-08-07 | 95.90 | 53,165,646 | 56,119,488 | 0.7207 | 11.86 | above | 11.91 | 11.40 | cloud not yet formed (insufficient history) | — |
| 2026-08-10 | 96.80 | 63,692,835 | 66,646,677 | 0.7778 | 12.37 | above | 12.61 | 12.09 | cloud not yet formed (insufficient history) | — |
| 2026-08-11 | 97.70 | 69,208,099 | 72,161,941 | 0.8308 | 12.70 | above | 13.36 | 12.85 | cloud not yet formed (insufficient history) | — |
| 2026-08-12 | 40.60 | 1,676,827 | 4,630,669 | 0.9629 | 14.37 | above | 13.90 | 13.36 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-07-31 = Day 0).

Day -11 (2026-07-16): Volume 1.6x avg, no pattern, BB within bands, MACD hist -0.0569 (rising), EMA20(9.91) < EMA50(10.04), MFI 54.1, price above VWAP, tested prior swing low at 9.21 (2026-06-30), held
Day -10 (2026-07-17): Volume 2.2x avg, no pattern, BB +1.4 sigma, MACD hist 0.0152 (rising), EMA20(9.97) < EMA50(10.06), MFI 59.7, price above VWAP
Day -9 (2026-07-20): Volume 1.0x avg, no pattern, BB within bands, MACD hist 0.0482 (rising), EMA20(10.00) < EMA50(10.07), MFI 66.7, price above VWAP, tested prior swing high at 10.52 (2026-07-03), rejected at
Day -8 (2026-07-21): Volume 0.8x avg, no pattern, BB +1.1 sigma, MACD hist 0.0721 (rising), EMA20(10.03) < EMA50(10.08), MFI 59.0, price above VWAP, tested prior swing high at 10.85 (2026-07-17), rejected at
Day -7 (2026-07-22): Volume 0.4x avg, no pattern, BB +1.0 sigma, MACD hist 0.0819 (rising), EMA20(10.06) < EMA50(10.09), MFI 53.3, price above VWAP, tested prior swing high at 10.52 (2026-07-03), rejected at
Day -6 (2026-07-23): Volume 0.8x avg, Piercing Line formed (open(10.15) < prior_low(10.20) AND prior_mid(10.41) < close(10.45) < prior_open(10.49)), BB +1.2 sigma, MACD hist 0.0917 (rising), EMA20(10.10) < EMA50(10.11), MFI 46.1, price above VWAP, tested prior swing high at 10.52 (2026-07-03), rejected at
Day -5 (2026-07-24): Volume 0.7x avg, no pattern, BB +1.3 sigma, MACD hist 0.0976 (rising), EMA20(10.14) > EMA50(10.12), MFI 51.0, price above VWAP, tested prior swing high at 10.85 (2026-07-17), rejected at
Day -4 (2026-07-27): Volume 0.4x avg, no pattern, BB +1.3 sigma, MACD hist 0.1011 (rising), EMA20(10.18) > EMA50(10.14), MFI 55.8, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.59 (2026-06-11), broke below; tested prior swing high at 10.85 (2026-07-17), rejected at
Day -3 (2026-07-28): Volume 0.3x avg, no pattern, BB within bands, MACD hist 0.0868 (falling), EMA20(10.20) > EMA50(10.15), MFI 57.3, price above VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing high at 10.52 (2026-07-03), rejected at
Day -2 (2026-07-29): Volume 0.5x avg, no pattern, BB within bands, MACD hist 0.0562 (falling), EMA20(10.20) > EMA50(10.15), MFI 60.2, price below VWAP, tested prior swing high at 10.52 (2026-07-03), rejected at
Day -1 (2026-07-30): Volume 0.7x avg, no pattern, BB within bands, MACD hist 0.0295 (falling), EMA20(10.18) > EMA50(10.15), MFI 59.8, price below VWAP
Day 0 (2026-07-31): Volume 1.3x avg, Doji formed (body(0.01) <= 0.1*range(0.45) [body/range=0.02]), BB within bands, MACD hist 0.0194 (falling), EMA20(10.18) > EMA50(10.15), MFI 64.2, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 9.99 (2026-07-30), held; tested prior swing high at 10.52 (2026-07-03), rejected at
Day +1 (2026-08-03): Volume 4.3x avg, no pattern, BB +1.9 sigma, MACD hist 0.0642 (rising), EMA20(10.26) > EMA50(10.18), MFI 76.5, price above VWAP, tested prior swing low at 9.99 (2026-07-30), held
Day +2 (2026-08-04): Volume 9.2x avg, no pattern, BB +3.0 sigma, MACD hist 0.1588 (rising), EMA20(10.44) > EMA50(10.26), MFI 88.9, price above VWAP, tested prior swing low at 10.59 (2026-06-11), held
Day +3 (2026-08-05): Volume 3.4x avg, no pattern, BB +2.2 sigma, MACD hist 0.1957 (rising), EMA20(10.58) > EMA50(10.32), MFI 90.7, price above VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
Day +4 (2026-08-06): Volume 2.4x avg, no pattern, BB +2.4 sigma, MACD hist 0.2509 (rising), EMA20(10.77) > EMA50(10.41), MFI 91.5, price above VWAP
Day +5 (2026-08-07): Volume 5.1x avg, no pattern, BB +2.8 sigma, MACD hist 0.3510 (rising), EMA20(11.06) > EMA50(10.55), MFI 95.9, price above VWAP
Day +6 (2026-08-10): Volume 3.5x avg, no pattern, BB +2.9 sigma, MACD hist 0.4810 (rising), EMA20(11.46) > EMA50(10.73), MFI 96.8, price above VWAP
Day +7 (2026-08-11): Volume 1.7x avg, no pattern, BB +2.9 sigma, MACD hist 0.6306 (rising), EMA20(11.96) > EMA50(10.97), MFI 97.7, price above VWAP
Day +8 (2026-08-12): Volume 10.2x avg, no pattern, BB +1.7 sigma, MACD hist 0.5797 (falling), EMA20(12.26) > EMA50(11.13), MFI 40.6, price above VWAP

### Flow divergence check

4 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-07-27: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-07-28: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-07-31: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-08-05: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
---

## STOCK 8 — SYM

### Data coverage & ticker identity

Report window: **2026-04-10 to 2026-07-03**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **SYM** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `SYM` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Chart structure:** This window captures BOTH legs the user asked for: an early dip (low 9.85 on 04-30, the user-given Day 0) inside a broader decline that started well before the window, then a slow multi-month climb through May/June to the final breakout reference (high 12.69 on 07-03). Note the breakout_day computed here (04-27, 6.43x volume) actually falls just BEFORE the 04-30 dip reference -- a large volume day on the way down, not on the way up -- while the real MACD sign flip into bullish territory only comes on 05-13 (day +8), after the dip. This is a materially different, slower shape than the other stocks in this dataset: no single clean breakout day, more of a multi-week grind.

### Core day-by-day table (OHLC, candles, trend)

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-04-10 | 11.00 | 11.45 | 10.95 | 11.23 | 1,602,473 | 901,648 | 1.78 | — | — | +11.3% vs SMA20(10.09) | insufficient history | +2.2 sigma | 0.2687 | rising | EMA20(10.42) < EMA50(11.22) | 56.80 | — |
| 2026-04-13 | 10.90 | 10.90 | 10.45 | 10.51 | 1,052,628 | 927,619 | 1.13 | — | — | +3.9% vs SMA20(10.12) | insufficient history | within bands | 0.2226 | falling | EMA20(10.43) < EMA50(11.19) | 49.50 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-04-14 | 10.61 | 11.00 | 10.61 | 10.88 | 993,361 | 964,569 | 1.03 | — | — | +6.9% vs SMA20(10.18) | -3.9% vs SMA50(11.33) | +1.3 sigma | 0.2082 | falling | EMA20(10.47) < EMA50(11.18) | 52.80 | tested prior swing low at 10.45 (2026-04-13), held |
| 2026-04-15 | 10.98 | 11.45 | 10.98 | 11.00 | 1,579,581 | 1,026,381 | 1.54 | Doji | body(0.02) <= 0.1*range(0.47) [body/range=0.04] | +7.4% vs SMA20(10.25) | -2.3% vs SMA50(11.26) | +1.4 sigma | 0.1981 | falling | EMA20(10.52) < EMA50(11.17) | 53.90 | — |
| 2026-04-16 | 11.19 | 11.46 | 10.91 | 11.30 | 2,534,253 | 1,138,216 | 2.23 | — | — | +9.5% vs SMA20(10.32) | +0.8% vs SMA50(11.21) | +1.7 sigma | 0.2022 | rising | EMA20(10.60) < EMA50(11.18) | 56.60 | — |
| 2026-04-17 | 11.45 | 11.65 | 11.00 | 11.42 | 3,272,712 | 1,279,887 | 2.56 | Doji | body(0.03) <= 0.1*range(0.65) [body/range=0.05] | +9.8% vs SMA20(10.40) | +2.4% vs SMA50(11.15) | +1.6 sigma | 0.2031 | rising | EMA20(10.68) < EMA50(11.19) | 57.60 | — |
| 2026-04-20 | 11.17 | 11.35 | 10.83 | 11.04 | 1,391,319 | 1,334,724 | 1.04 | — | — | +5.5% vs SMA20(10.46) | -0.5% vs SMA50(11.09) | within bands | 0.1695 | falling | EMA20(10.71) < EMA50(11.18) | 53.20 | — |
| 2026-04-21 | 11.10 | 11.45 | 11.04 | 11.30 | 1,350,735 | 1,390,385 | 0.97 | — | — | +7.4% vs SMA20(10.52) | +2.5% vs SMA50(11.03) | +1.2 sigma | 0.1565 | falling | EMA20(10.77) < EMA50(11.19) | 55.70 | tested prior swing high at 11.65 (2026-04-17), rejected at |
| 2026-04-22 | 11.28 | 11.28 | 10.83 | 10.89 | 1,317,585 | 1,411,530 | 0.93 | — | — | +3.2% vs SMA20(10.56) | -0.5% vs SMA50(10.95) | within bands | 0.1141 | falling | EMA20(10.78) < EMA50(11.18) | 51.10 | — |
| 2026-04-23 | 10.84 | 10.85 | 10.60 | 10.67 | 1,156,254 | 1,421,009 | 0.81 | — | — | +0.8% vs SMA20(10.59) | -1.8% vs SMA50(10.87) | within bands | 0.0672 | falling | EMA20(10.77) < EMA50(11.16) | 48.70 | tested prior swing low at 10.45 (2026-04-13), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-04-24 | 10.67 | 10.88 | 10.48 | 10.80 | 775,990 | 1,382,085 | 0.56 | — | — | +1.4% vs SMA20(10.65) | +0.0% vs SMA50(10.80) | within bands | 0.0422 | falling | EMA20(10.77) < EMA50(11.14) | 50.20 | tested prior swing low at 10.45 (2026-04-13), held; tested prior swing high at 10.75 (2026-04-01), broke above |
| 2026-04-27 | 10.75 | 11.88 | 10.70 | 11.27 | 12,741,673 | 1,980,803 | 6.43 | — | — | +4.7% vs SMA20(10.76) | +4.9% vs SMA50(10.74) | +1.1 sigma | 0.0538 | rising | EMA20(10.82) < EMA50(11.15) | 55.10 | tested prior swing high at 11.65 (2026-04-17), rejected at |
| 2026-04-28 | 11.13 | 12.16 | 10.80 | 11.18 | 44,618,680 | 4,137,281 | 10.78 | Doji | body(0.05) <= 0.1*range(1.36) [body/range=0.04] | +3.2% vs SMA20(10.83) | +4.7% vs SMA50(10.68) | within bands | 0.0519 | falling | EMA20(10.85) < EMA50(11.15) | 54.00 | — |
| 2026-04-29 | 11.20 | 11.23 | 10.57 | 10.64 | 4,501,758 | 4,276,919 | 1.05 | — | — | -1.8% vs SMA20(10.84) | +0.1% vs SMA50(10.62) | within bands | 0.0128 | falling | EMA20(10.83) < EMA50(11.13) | 47.80 | tested prior swing low at 10.48 (2026-04-24), held |
| 2026-04-30 | 10.61 | 10.61 | 9.85 | 10.25 | 2,533,287 | 4,354,819 | 0.58 | — | — | -5.5% vs SMA20(10.85) | -2.9% vs SMA50(10.56) | -1.4 sigma | -0.0380 | falling | EMA20(10.78) < EMA50(11.09) | 43.90 | tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-05-01 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-04 | 10.30 | 10.66 | 10.01 | 10.09 | 3,390,441 | 4,490,632 | 0.76 | — | — | -7.0% vs SMA20(10.85) | -3.7% vs SMA50(10.48) | -1.9 sigma | -0.0787 | falling | EMA20(10.71) < EMA50(11.05) | 42.40 | tested prior swing low at 9.85 (2026-04-30), held; tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-05-05 | 10.01 | 10.24 | 9.97 | 10.11 | 1,108,817 | 4,512,952 | 0.25 | — | — | -6.8% vs SMA20(10.84) | -3.0% vs SMA50(10.42) | -1.8 sigma | -0.0994 | falling | EMA20(10.65) < EMA50(11.02) | 42.70 | tested prior swing low at 9.85 (2026-04-30), held; tested prior swing high at 10.10 (2026-03-12), broke above |
| 2026-05-06 | 10.32 | 10.99 | 10.26 | 10.62 | 2,798,384 | 4,622,321 | 0.61 | — | — | -2.3% vs SMA20(10.87) | +2.2% vs SMA50(10.39) | within bands | -0.0748 | rising | EMA20(10.65) < EMA50(11.00) | 49.20 | tested prior swing low at 10.27 (2026-02-24), held |
| 2026-05-07 | 10.62 | 10.89 | 10.55 | 10.64 | 2,081,481 | 4,600,257 | 0.45 | Doji | body(0.02) <= 0.1*range(0.34) [body/range=0.06] | -1.8% vs SMA20(10.84) | +2.5% vs SMA50(10.38) | within bands | -0.0543 | rising | EMA20(10.65) < EMA50(10.99) | 49.40 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-05-08 | 10.64 | 10.90 | 10.52 | 10.65 | 2,564,120 | 4,668,277 | 0.55 | Doji | body(0.01) <= 0.1*range(0.38) [body/range=0.03] | -1.6% vs SMA20(10.82) | +2.6% vs SMA50(10.38) | within bands | -0.0379 | rising | EMA20(10.65) < EMA50(10.97) | 49.60 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-05-11 | 10.65 | 11.10 | 10.55 | 10.80 | 5,125,823 | 4,844,444 | 1.06 | — | — | -0.0% vs SMA20(10.80) | +4.0% vs SMA50(10.38) | within bands | -0.0160 | rising | EMA20(10.66) < EMA50(10.97) | 51.60 | tested prior swing low at 10.48 (2026-04-24), held |
| 2026-05-12 | 10.81 | 11.06 | 10.63 | 10.67 | 1,950,974 | 4,889,361 | 0.40 | — | — | -1.3% vs SMA20(10.81) | +2.9% vs SMA50(10.37) | within bands | -0.0095 | rising | EMA20(10.66) < EMA50(10.96) | 49.70 | tested prior swing low at 10.48 (2026-04-24), held |
| 2026-05-13 | 10.76 | 11.01 | 10.54 | 10.85 | 3,300,899 | 5,004,738 | 0.66 | — | — | +0.4% vs SMA20(10.81) | +4.7% vs SMA50(10.37) | within bands | 0.0067 | rising | EMA20(10.68) < EMA50(10.95) | 52.30 | tested prior swing low at 10.48 (2026-04-24), held |
| 2026-05-14 | 10.96 | 11.15 | 10.64 | 10.68 | 3,967,996 | 5,124,159 | 0.77 | — | — | -1.1% vs SMA20(10.79) | +2.9% vs SMA50(10.38) | within bands | 0.0058 | falling | EMA20(10.68) < EMA50(10.94) | 49.70 | tested prior swing low at 10.48 (2026-04-24), held |
| 2026-05-15 | 10.73 | 10.77 | 10.52 | 10.57 | 1,206,352 | 5,057,764 | 0.24 | — | — | -1.7% vs SMA20(10.76) | +1.7% vs SMA50(10.39) | within bands | -0.0020 | falling | EMA20(10.67) < EMA50(10.93) | 48.10 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-05-18 | 10.62 | 10.62 | 10.01 | 10.18 | 1,131,199 | 4,950,688 | 0.23 | — | — | -4.8% vs SMA20(10.70) | -2.1% vs SMA50(10.40) | -1.5 sigma | -0.0314 | falling | EMA20(10.62) < EMA50(10.90) | 42.70 | tested prior swing low at 9.85 (2026-04-30), held; tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-05-19 | 10.37 | 10.37 | 10.11 | 10.14 | 525,092 | 4,907,377 | 0.11 | — | — | -4.8% vs SMA20(10.65) | -2.4% vs SMA50(10.39) | -1.4 sigma | -0.0506 | falling | EMA20(10.58) < EMA50(10.87) | 42.10 | tested prior swing low at 10.01 (2026-05-18), held; tested prior swing high at 10.44 (2026-03-25), rejected at |
| 2026-05-20 | 10.25 | 10.65 | 10.10 | 10.28 | 1,963,733 | 4,938,027 | 0.40 | Doji | body(0.03) <= 0.1*range(0.55) [body/range=0.05] | -3.0% vs SMA20(10.60) | -1.1% vs SMA50(10.39) | within bands | -0.0507 | falling | EMA20(10.55) < EMA50(10.84) | 44.70 | tested prior swing low at 10.01 (2026-05-18), held; tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-05-21 | 10.35 | 10.83 | 10.35 | 10.58 | 2,067,853 | 4,975,540 | 0.42 | — | — | -0.0% vs SMA20(10.58) | +1.5% vs SMA50(10.43) | within bands | -0.0285 | rising | EMA20(10.55) < EMA50(10.83) | 49.80 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-05-22 | 10.65 | 10.69 | 10.29 | 10.33 | 851,642 | 4,960,310 | 0.17 | — | — | -2.2% vs SMA20(10.57) | -1.0% vs SMA50(10.44) | within bands | -0.0285 | falling | EMA20(10.53) < EMA50(10.81) | 46.00 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-05-25 | 10.38 | 10.54 | 10.33 | 10.42 | 990,969 | 4,971,059 | 0.20 | — | — | -1.2% vs SMA20(10.55) | -0.3% vs SMA50(10.45) | within bands | -0.0207 | rising | EMA20(10.52) < EMA50(10.80) | 47.50 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-05-26 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-27 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-28 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-29 | 10.44 | 10.52 | 10.30 | 10.49 | 950,620 | 4,381,506 | 0.22 | — | — | -0.2% vs SMA20(10.51) | +0.3% vs SMA50(10.46) | within bands | -0.0096 | rising | EMA20(10.52) < EMA50(10.79) | 48.80 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-06-01 | 10.51 | 10.76 | 10.51 | 10.52 | 1,655,974 | 2,233,371 | 0.74 | Doji | body(0.01) <= 0.1*range(0.25) [body/range=0.04] | +0.4% vs SMA20(10.48) | +0.4% vs SMA50(10.48) | within bands | 0.0004 | rising | EMA20(10.52) < EMA50(10.78) | 49.30 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-06-02 | 10.58 | 10.58 | 10.30 | 10.42 | 1,389,087 | 2,077,737 | 0.67 | — | — | -0.4% vs SMA20(10.46) | -0.7% vs SMA50(10.49) | within bands | 0.0009 | rising | EMA20(10.51) < EMA50(10.76) | 47.50 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-06-03 | 10.42 | 10.44 | 10.25 | 10.30 | 553,835 | 1,978,765 | 0.28 | — | — | -1.6% vs SMA20(10.47) | -2.0% vs SMA50(10.50) | within bands | -0.0058 | falling | EMA20(10.49) < EMA50(10.74) | 45.30 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.44 (2026-03-25), rejected at |
| 2026-06-04 | 10.33 | 10.44 | 10.00 | 10.17 | 4,853,204 | 2,051,903 | 2.37 | — | — | -2.9% vs SMA20(10.47) | -3.3% vs SMA50(10.51) | -1.4 sigma | -0.0174 | falling | EMA20(10.46) < EMA50(10.72) | 43.00 | tested prior swing low at 10.01 (2026-05-18), held; tested prior swing high at 10.44 (2026-03-25), rejected at |
| 2026-06-05 | 10.24 | 10.39 | 10.15 | 10.21 | 1,018,072 | 2,047,365 | 0.50 | — | — | -2.5% vs SMA20(10.48) | -2.9% vs SMA50(10.52) | -1.3 sigma | -0.0204 | falling | EMA20(10.43) < EMA50(10.70) | 44.00 | tested prior swing low at 10.27 (2026-02-24), broke below; tested prior swing high at 10.44 (2026-03-25), rejected at |
| 2026-06-08 | 10.12 | 10.18 | 10.02 | 10.14 | 626,803 | 1,938,786 | 0.32 | — | — | -3.0% vs SMA20(10.45) | -3.6% vs SMA50(10.52) | -1.4 sigma | -0.0250 | falling | EMA20(10.41) < EMA50(10.68) | 42.60 | tested prior swing low at 10.01 (2026-05-18), held; tested prior swing high at 10.10 (2026-03-12), broke above |
| 2026-06-09 | 10.19 | 10.64 | 10.19 | 10.40 | 2,968,685 | 1,983,147 | 1.50 | — | — | -0.4% vs SMA20(10.44) | -1.2% vs SMA50(10.52) | within bands | -0.0092 | rising | EMA20(10.41) < EMA50(10.67) | 48.80 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-06-10 | 10.35 | 10.65 | 10.35 | 10.50 | 1,479,678 | 1,928,924 | 0.77 | — | — | +0.6% vs SMA20(10.43) | -0.3% vs SMA50(10.53) | within bands | 0.0085 | rising | EMA20(10.42) < EMA50(10.66) | 51.00 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at |
| 2026-06-11 | 10.45 | 10.47 | 10.31 | 10.37 | 688,718 | 1,707,069 | 0.40 | — | — | -0.4% vs SMA20(10.41) | -1.7% vs SMA50(10.55) | within bands | 0.0116 | rising | EMA20(10.41) < EMA50(10.65) | 48.10 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.44 (2026-03-25), rejected at |
| 2026-06-12 | 10.45 | 10.74 | 10.35 | 10.48 | 3,663,584 | 1,792,700 | 2.04 | Doji | body(0.03) <= 0.1*range(0.39) [body/range=0.08] | +0.8% vs SMA20(10.40) | -0.9% vs SMA50(10.58) | within bands | 0.0207 | rising | EMA20(10.42) < EMA50(10.64) | 50.70 | tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-06-15 | 10.75 | 10.75 | 10.50 | 10.61 | 1,177,346 | 1,686,522 | 0.70 | — | — | +2.1% vs SMA20(10.39) | +0.2% vs SMA50(10.59) | +1.4 sigma | 0.0344 | rising | EMA20(10.44) < EMA50(10.64) | 53.60 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at |
| 2026-06-16 | 10.69 | 10.80 | 10.55 | 10.76 | 2,621,016 | 1,619,173 | 1.62 | — | — | +3.5% vs SMA20(10.39) | +1.5% vs SMA50(10.60) | +2.2 sigma | 0.0514 | rising | EMA20(10.47) < EMA50(10.65) | 56.70 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.83 (2026-05-21), rejected at |
| 2026-06-17 | 10.85 | 10.89 | 10.62 | 10.72 | 1,738,398 | 1,645,775 | 1.06 | — | — | +3.1% vs SMA20(10.40) | +1.0% vs SMA50(10.61) | +1.8 sigma | 0.0573 | rising | EMA20(10.49) < EMA50(10.65) | 55.60 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.83 (2026-05-21), rejected at |
| 2026-06-18 | 10.81 | 10.85 | 10.61 | 10.68 | 1,691,991 | 1,673,815 | 1.01 | — | — | +2.4% vs SMA20(10.43) | +0.5% vs SMA50(10.63) | +1.4 sigma | 0.0559 | falling | EMA20(10.51) < EMA50(10.65) | 54.50 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.83 (2026-05-21), rejected at |
| 2026-06-19 | 10.80 | 10.80 | 10.50 | 10.62 | 2,133,770 | 1,754,249 | 1.22 | — | — | +1.6% vs SMA20(10.45) | -0.1% vs SMA50(10.63) | within bands | 0.0485 | falling | EMA20(10.52) < EMA50(10.65) | 52.80 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.83 (2026-05-21), rejected at |
| 2026-06-22 | 10.88 | 10.88 | 10.47 | 10.57 | 1,028,001 | 1,707,462 | 0.60 | — | — | +1.0% vs SMA20(10.46) | -0.7% vs SMA50(10.64) | within bands | 0.0384 | falling | EMA20(10.52) < EMA50(10.65) | 51.30 | tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.89 (2026-06-17), rejected at |
| 2026-06-23 | 10.70 | 11.06 | 10.40 | 10.90 | 7,989,881 | 2,003,564 | 3.99 | — | — | +4.0% vs SMA20(10.48) | +2.5% vs SMA50(10.63) | +2.1 sigma | 0.0511 | rising | EMA20(10.56) < EMA50(10.66) | 59.30 | tested prior swing low at 10.45 (2026-04-13), held; tested prior swing high at 11.15 (2026-05-14), rejected at |
| 2026-06-24 | 10.94 | 11.47 | 10.93 | 11.30 | 7,163,122 | 2,319,138 | 3.09 | — | — | +7.3% vs SMA20(10.53) | +6.2% vs SMA50(10.64) | +2.9 sigma | 0.0819 | rising | EMA20(10.63) < EMA50(10.68) | 66.50 | tested prior swing high at 11.65 (2026-04-17), rejected at |
| 2026-06-25 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-26 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-29 | 11.30 | 11.50 | 10.80 | 10.94 | 6,088,399 | 2,574,009 | 2.37 | — | — | +3.6% vs SMA20(10.56) | +2.8% vs SMA50(10.64) | +1.4 sigma | 0.0737 | falling | EMA20(10.66) < EMA50(10.69) | 56.80 | tested prior swing high at 11.65 (2026-04-17), rejected at |
| 2026-06-30 | 10.93 | 12.03 | 10.93 | 12.03 | 19,420,901 | 3,497,523 | 5.55 | Bullish Engulfing | prior_close(10.94)<prior_open(11.30, bearish) AND close(12.03)>open(10.93, bullish) AND open(10.93) <= prior_close(10.94) AND close(12.03) >= prior_open(11.30) [today body 10.93→12.03 engulfs prior 11.30→10.94] | +13.1% vs SMA20(10.63) | +12.8% vs SMA50(10.67) | +3.3 sigma | 0.1339 | rising | EMA20(10.79) > EMA50(10.74) | 70.70 | tested prior swing high at 12.16 (2026-04-28), rejected at |
| 2026-07-01 | 12.30 | 12.45 | 11.50 | 11.70 | 8,616,711 | 3,845,560 | 2.24 | — | — | +9.4% vs SMA20(10.69) | +9.5% vs SMA50(10.68) | +2.1 sigma | 0.1428 | rising | EMA20(10.88) > EMA50(10.78) | 64.00 | — |
| 2026-07-02 | 11.80 | 11.94 | 11.65 | 11.76 | 2,856,961 | 3,918,954 | 0.73 | — | — | +9.3% vs SMA20(10.76) | +9.9% vs SMA50(10.70) | +1.9 sigma | 0.1438 | rising | EMA20(10.96) > EMA50(10.82) | 64.60 | tested prior swing high at 12.16 (2026-04-28), rejected at |
| 2026-07-03 | 11.76 | 12.69 | 11.76 | 12.02 | 11,003,300 | 4,441,427 | 2.48 | Bullish Engulfing | prior_close(11.76)<prior_open(11.80, bearish) AND close(12.02)>open(11.76, bullish) AND open(11.76) <= prior_close(11.76) AND close(12.02) >= prior_open(11.80) [today body 11.76→12.02 engulfs prior 11.80→11.76] | +10.8% vs SMA20(10.84) | +12.2% vs SMA50(10.71) | +2.0 sigma | 0.1521 | rising | EMA20(11.06) > EMA50(10.87) | 67.40 | — |

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-04-10 | 58.70 | -1,471,414 | -5,241,736 | 0.6291 | 11.21 | above | 10.31 | 10.23 | cloud not yet formed (insufficient history) | — |
| 2026-04-13 | 54.40 | -2,524,042 | -6,013,664 | 0.6399 | 10.98 | below | 10.57 | 10.23 | cloud not yet formed (insufficient history) | — |
| 2026-04-14 | 54.80 | -1,530,681 | -5,631,602 | 0.6292 | 10.94 | below | 10.57 | 10.23 | cloud not yet formed (insufficient history) | — |
| 2026-04-15 | 62.10 | 48,900 | -7,076,750 | 0.6250 | 11.00 | above | 10.57 | 10.23 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-04-16 | 72.30 | 2,583,153 | -6,016,972 | 0.6196 | 11.07 | above | 10.68 | 10.23 | cloud not yet formed (insufficient history) | — |
| 2026-04-17 | 79.20 | 5,855,865 | -5,060,333 | 0.6218 | 11.16 | above | 10.82 | 10.33 | cloud not yet formed (insufficient history) | — |
| 2026-04-20 | 72.50 | 4,464,546 | -5,327,894 | 0.6195 | 11.15 | below | 11.05 | 10.33 | cloud not yet formed (insufficient history) | — |
| 2026-04-21 | 72.20 | 5,815,281 | -4,965,502 | 0.6045 | 11.16 | above | 11.05 | 10.33 | cloud not yet formed (insufficient history) | — |
| 2026-04-22 | 70.70 | 4,497,696 | -5,931,731 | 0.5949 | 11.14 | below | 11.05 | 10.33 | cloud not yet formed (insufficient history) | — |
| 2026-04-23 | 69.00 | 3,341,442 | -6,440,483 | 0.5732 | 11.11 | below | 11.05 | 10.33 | cloud not yet formed (insufficient history) | — |
| 2026-04-24 | 69.20 | 4,117,432 | -5,974,889 | 0.5608 | 11.10 | below | 11.07 | 10.33 | cloud not yet formed (insufficient history) | — |
| 2026-04-27 | 82.20 | 16,859,105 | -6,406,810 | 0.6050 | 11.18 | above | 11.18 | 10.45 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-04-28 | 92.20 | -27,759,575 | -26,091,522 | 0.6589 | 11.30 | below | 11.32 | 10.59 | cloud not yet formed (insufficient history) | — |
| 2026-04-29 | 88.50 | -32,261,333 | -29,638,361 | 0.6590 | 11.27 | below | 11.32 | 10.59 | cloud not yet formed (insufficient history) | — |
| 2026-04-30 | 85.70 | -34,794,620 | -29,505,030 | 0.6684 | 11.24 | below | 11.00 | 10.59 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-05-01 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-04 | 87.30 | -38,185,061 | -32,060,901 | 0.6671 | 11.20 | below | 11.00 | 10.59 | cloud not yet formed (insufficient history) | — |
| 2026-05-05 | 86.10 | -37,076,244 | -32,019,834 | 0.6387 | 11.19 | below | 11.00 | 10.59 | cloud not yet formed (insufficient history) | — |
| 2026-05-06 | 86.30 | -34,277,860 | -32,058,168 | 0.6559 | 11.17 | below | 11.00 | 10.67 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-07 | 86.20 | -32,196,379 | -33,037,688 | 0.6334 | 11.16 | below | 11.00 | 10.93 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-08 | 83.00 | -29,632,259 | -33,847,411 | 0.6153 | 11.14 | below | 11.00 | 10.93 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-11 | 85.40 | -24,506,436 | -34,313,394 | 0.6106 | 11.13 | below | 11.00 | 10.93 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-12 | 83.30 | -26,457,410 | -35,901,397 | 0.5977 | 11.12 | below | 10.54 | 11.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-13 | 85.10 | -23,156,511 | -34,847,918 | 0.5886 | 11.11 | below | 10.47 | 11.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-14 | 86.80 | -27,124,507 | -38,193,483 | 0.5830 | 11.10 | below | 10.56 | 11.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-15 | 85.60 | -28,330,859 | -38,917,295 | 0.5592 | 11.09 | below | 10.56 | 11.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-18 | 82.10 | -29,462,058 | -39,417,989 | 0.5628 | 11.09 | below | 10.58 | 11.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-19 | 57.40 | -29,987,150 | -39,821,906 | 0.5412 | 11.08 | below | 10.58 | 11.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-20 | 67.60 | -28,023,417 | -40,500,287 | 0.5418 | 11.07 | below | 10.58 | 11.00 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-21 | 74.60 | -25,955,564 | -40,586,447 | 0.5424 | 11.06 | below | 10.58 | 11.00 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-22 | 69.90 | -26,807,206 | -41,267,761 | 0.5322 | 11.06 | below | 10.58 | 11.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-25 | 70.10 | -25,816,237 | -41,409,328 | 0.5092 | 11.05 | below | 10.58 | 11.00 | below cloud, cloud bearish (red), thickness 1.65 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-26 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-27 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-28 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-29 | 68.10 | -24,865,617 | -40,717,968 | 0.4886 | 11.04 | below | 10.58 | 11.00 | below cloud, cloud bearish (red), thickness 1.53 | — |
| 2026-06-01 | 67.60 | -23,209,643 | -42,241,464 | 0.4729 | 11.04 | below | 10.42 | 11.00 | below cloud, cloud bearish (red), thickness 1.41 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-02 | 70.70 | -24,598,730 | -42,439,905 | 0.4592 | 11.03 | below | 10.42 | 11.00 | below cloud, cloud bearish (red), thickness 1.41 | — |
| 2026-06-03 | 62.20 | -25,152,565 | -42,702,248 | 0.4399 | 11.03 | below | 10.46 | 11.00 | below cloud, cloud bearish (red), thickness 1.41 | — |
| 2026-06-04 | 55.50 | -30,005,769 | -43,805,249 | 0.4399 | 11.00 | below | 10.41 | 11.00 | below cloud, cloud bearish (red), thickness 1.41 | — |
| 2026-06-05 | 50.90 | -28,987,697 | -44,314,285 | 0.4257 | 10.99 | below | 10.41 | 11.00 | below cloud, cloud bearish (red), thickness 1.41 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-08 | 39.00 | -29,614,500 | -44,000,883 | 0.4088 | 10.99 | below | 10.38 | 11.00 | below cloud, cloud bearish (red), thickness 1.12 | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-06-09 | 49.70 | -26,645,815 | -44,198,795 | 0.4153 | 10.97 | below | 10.38 | 10.54 | below cloud, cloud bearish (red), thickness 0.85 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-10 | 55.70 | -25,166,137 | -44,198,795 | 0.4071 | 10.97 | below | 10.38 | 10.50 | below cloud, cloud bearish (red), thickness 0.73 | — |
| 2026-06-11 | 55.30 | -25,854,855 | -44,370,975 | 0.3916 | 10.96 | below | 10.38 | 10.56 | below cloud, cloud bearish (red), thickness 0.85 | — |
| 2026-06-12 | 58.60 | -22,191,271 | -45,592,170 | 0.3915 | 10.95 | below | 10.37 | 10.56 | below cloud, cloud bearish (red), thickness 0.71 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-15 | 56.90 | -21,013,925 | -45,733,451 | 0.3828 | 10.95 | below | 10.38 | 10.57 | below cloud, cloud bearish (red), thickness 0.71 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-16 | 63.60 | -18,392,909 | -43,951,160 | 0.3733 | 10.95 | below | 10.40 | 10.57 | below cloud, cloud bearish (red), thickness 0.64 | — |
| 2026-06-17 | 68.60 | -20,131,307 | -44,401,856 | 0.3659 | 10.94 | below | 10.46 | 10.57 | below cloud, cloud bearish (red), thickness 0.18 | — |
| 2026-06-18 | 63.00 | -21,823,298 | -45,106,852 | 0.3569 | 10.94 | below | 10.46 | 10.57 | below cloud, cloud bullish (green), thickness 0.22 | — |
| 2026-06-19 | 55.50 | -23,957,068 | -45,533,606 | 0.3529 | 10.94 | below | 10.54 | 10.57 | inside cloud, cloud bullish (green), thickness 0.38 | — |
| 2026-06-22 | 58.50 | -24,985,069 | -46,060,143 | 0.3570 | 10.93 | below | 10.60 | 10.57 | below cloud, cloud bullish (green), thickness 0.19 | — |
| 2026-06-23 | 69.90 | -16,995,188 | -41,944,144 | 0.3786 | 10.93 | below | 10.69 | 10.57 | above cloud, cloud bullish (green), thickness 0.15 | — |
| 2026-06-24 | 85.50 | -9,832,066 | -39,291,136 | 0.3923 | 10.94 | above | 10.91 | 10.73 | above cloud, cloud bullish (green), thickness 0.20 | — |
| 2026-06-25 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-26 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-29 | 71.90 | -15,920,465 | -42,944,175 | 0.4143 | 10.94 | below | 10.95 | 10.75 | above cloud, cloud bullish (green), thickness 0.20 | — |
| 2026-06-30 | 82.30 | 3,500,436 | -23,523,274 | 0.4632 | 11.02 | above | 11.21 | 11.02 | above cloud, cloud bullish (green), thickness 0.21 | — |
| 2026-07-01 | 84.10 | -5,116,275 | -28,511,897 | 0.4980 | 11.06 | above | 11.43 | 11.22 | above cloud, cloud bullish (green), thickness 0.21 | — |
| 2026-07-02 | 79.90 | -2,259,314 | -29,201,508 | 0.4831 | 11.07 | above | 11.43 | 11.22 | above cloud, cloud bullish (green), thickness 0.21 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-07-03 | 83.70 | 8,743,986 | -34,052,425 | 0.5151 | 11.12 | above | 11.54 | 11.34 | above cloud, cloud bullish (green), thickness 0.21 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-04-30 = Day 0).

Day -14 (2026-04-10): Volume 1.8x avg, no pattern, BB +2.2 sigma, MACD hist 0.2687 (rising), EMA20(10.42) < EMA50(11.22), MFI 58.7, price above VWAP
Day -13 (2026-04-13): Volume 1.1x avg, no pattern, BB within bands, MACD hist 0.2226 (falling), EMA20(10.43) < EMA50(11.19), MFI 54.4, price below VWAP, tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day -12 (2026-04-14): Volume 1.0x avg, no pattern, BB +1.3 sigma, MACD hist 0.2082 (falling), EMA20(10.47) < EMA50(11.18), MFI 54.8, price below VWAP, tested prior swing low at 10.45 (2026-04-13), held
Day -11 (2026-04-15): Volume 1.5x avg, Doji formed (body(0.02) <= 0.1*range(0.47) [body/range=0.04]), BB +1.4 sigma, MACD hist 0.1981 (falling), EMA20(10.52) < EMA50(11.17), MFI 62.1, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day -10 (2026-04-16): Volume 2.2x avg, no pattern, BB +1.7 sigma, MACD hist 0.2022 (rising), EMA20(10.60) < EMA50(11.18), MFI 72.3, price above VWAP
Day -9 (2026-04-17): Volume 2.6x avg, Doji formed (body(0.03) <= 0.1*range(0.65) [body/range=0.05]), BB +1.6 sigma, MACD hist 0.2031 (rising), EMA20(10.68) < EMA50(11.19), MFI 79.2, price above VWAP
Day -8 (2026-04-20): Volume 1.0x avg, no pattern, BB within bands, MACD hist 0.1695 (falling), EMA20(10.71) < EMA50(11.18), MFI 72.5, price below VWAP
Day -7 (2026-04-21): Volume 1.0x avg, no pattern, BB +1.2 sigma, MACD hist 0.1565 (falling), EMA20(10.77) < EMA50(11.19), MFI 72.2, price above VWAP, tested prior swing high at 11.65 (2026-04-17), rejected at
Day -6 (2026-04-22): Volume 0.9x avg, no pattern, BB within bands, MACD hist 0.1141 (falling), EMA20(10.78) < EMA50(11.18), MFI 70.7, price below VWAP
Day -5 (2026-04-23): Volume 0.8x avg, no pattern, BB within bands, MACD hist 0.0672 (falling), EMA20(10.77) < EMA50(11.16), MFI 69.0, price below VWAP, tested prior swing low at 10.45 (2026-04-13), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day -4 (2026-04-24): Volume 0.6x avg, no pattern, BB within bands, MACD hist 0.0422 (falling), EMA20(10.77) < EMA50(11.14), MFI 69.2, price below VWAP, tested prior swing low at 10.45 (2026-04-13), held; tested prior swing high at 10.75 (2026-04-01), broke above
Day -3 (2026-04-27): Volume 6.4x avg, no pattern, BB +1.1 sigma, MACD hist 0.0538 (rising), EMA20(10.82) < EMA50(11.15), MFI 82.2, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing high at 11.65 (2026-04-17), rejected at
Day -2 (2026-04-28): Volume 10.8x avg, Doji formed (body(0.05) <= 0.1*range(1.36) [body/range=0.04]), BB within bands, MACD hist 0.0519 (falling), EMA20(10.85) < EMA50(11.15), MFI 92.2, price below VWAP
Day -1 (2026-04-29): Volume 1.1x avg, no pattern, BB within bands, MACD hist 0.0128 (falling), EMA20(10.83) < EMA50(11.13), MFI 88.5, price below VWAP, tested prior swing low at 10.48 (2026-04-24), held
Day 0 (2026-04-30): Volume 0.6x avg, no pattern, BB -1.4 sigma, MACD hist -0.0380 (falling), EMA20(10.78) < EMA50(11.09), MFI 85.7, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing high at 10.60 (2026-03-05), rejected at
Day +1 (2026-05-04): Volume 0.8x avg, no pattern, BB -1.9 sigma, MACD hist -0.0787 (falling), EMA20(10.71) < EMA50(11.05), MFI 87.3, price below VWAP, tested prior swing low at 9.85 (2026-04-30), held; tested prior swing high at 10.60 (2026-03-05), rejected at
Day +2 (2026-05-05): Volume 0.2x avg, no pattern, BB -1.8 sigma, MACD hist -0.0994 (falling), EMA20(10.65) < EMA50(11.02), MFI 86.1, price below VWAP, tested prior swing low at 9.85 (2026-04-30), held; tested prior swing high at 10.10 (2026-03-12), broke above
Day +3 (2026-05-06): Volume 0.6x avg, no pattern, BB within bands, MACD hist -0.0748 (rising), EMA20(10.65) < EMA50(11.00), MFI 86.3, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.27 (2026-02-24), held
Day +4 (2026-05-07): Volume 0.5x avg, Doji formed (body(0.02) <= 0.1*range(0.34) [body/range=0.06]), BB within bands, MACD hist -0.0543 (rising), EMA20(10.65) < EMA50(10.99), MFI 86.2, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day +5 (2026-05-08): Volume 0.6x avg, Doji formed (body(0.01) <= 0.1*range(0.38) [body/range=0.03]), BB within bands, MACD hist -0.0379 (rising), EMA20(10.65) < EMA50(10.97), MFI 83.0, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day +6 (2026-05-11): Volume 1.1x avg, no pattern, BB within bands, MACD hist -0.0160 (rising), EMA20(10.66) < EMA50(10.97), MFI 85.4, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.48 (2026-04-24), held
Day +7 (2026-05-12): Volume 0.4x avg, no pattern, BB within bands, MACD hist -0.0095 (rising), EMA20(10.66) < EMA50(10.96), MFI 83.3, price below VWAP, tested prior swing low at 10.48 (2026-04-24), held
Day +8 (2026-05-13): Volume 0.7x avg, no pattern, BB within bands, MACD hist 0.0067 (rising), EMA20(10.68) < EMA50(10.95), MFI 85.1, price below VWAP, tested prior swing low at 10.48 (2026-04-24), held
Day +9 (2026-05-14): Volume 0.8x avg, no pattern, BB within bands, MACD hist 0.0058 (falling), EMA20(10.68) < EMA50(10.94), MFI 86.8, price below VWAP, tested prior swing low at 10.48 (2026-04-24), held
Day +10 (2026-05-15): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.0020 (falling), EMA20(10.67) < EMA50(10.93), MFI 85.6, price below VWAP, tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day +11 (2026-05-18): Volume 0.2x avg, no pattern, BB -1.5 sigma, MACD hist -0.0314 (falling), EMA20(10.62) < EMA50(10.90), MFI 82.1, price below VWAP, tested prior swing low at 9.85 (2026-04-30), held; tested prior swing high at 10.60 (2026-03-05), rejected at
Day +12 (2026-05-19): Volume 0.1x avg, no pattern, BB -1.4 sigma, MACD hist -0.0506 (falling), EMA20(10.58) < EMA50(10.87), MFI 57.4, price below VWAP, tested prior swing low at 10.01 (2026-05-18), held; tested prior swing high at 10.44 (2026-03-25), rejected at
Day +13 (2026-05-20): Volume 0.4x avg, Doji formed (body(0.03) <= 0.1*range(0.55) [body/range=0.05]), BB within bands, MACD hist -0.0507 (falling), EMA20(10.55) < EMA50(10.84), MFI 67.6, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.01 (2026-05-18), held; tested prior swing high at 10.60 (2026-03-05), rejected at
Day +14 (2026-05-21): Volume 0.4x avg, no pattern, BB within bands, MACD hist -0.0285 (rising), EMA20(10.55) < EMA50(10.83), MFI 74.6, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day +15 (2026-05-22): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.0285 (falling), EMA20(10.53) < EMA50(10.81), MFI 69.9, price below VWAP, tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day +16 (2026-05-25): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.0207 (rising), EMA20(10.52) < EMA50(10.80), MFI 70.1, price below VWAP, below cloud, cloud bearish (red), thickness 1.65, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at
Day +17 (2026-05-29): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.0096 (rising), EMA20(10.52) < EMA50(10.79), MFI 68.1, price below VWAP, below cloud, cloud bearish (red), thickness 1.53, tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at
Day +18 (2026-06-01): Volume 0.7x avg, Doji formed (body(0.01) <= 0.1*range(0.25) [body/range=0.04]), BB within bands, MACD hist 0.0004 (rising), EMA20(10.52) < EMA50(10.78), MFI 67.6, price below VWAP, below cloud, cloud bearish (red), thickness 1.41, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day +19 (2026-06-02): Volume 0.7x avg, no pattern, BB within bands, MACD hist 0.0009 (rising), EMA20(10.51) < EMA50(10.76), MFI 70.7, price below VWAP, below cloud, cloud bearish (red), thickness 1.41, tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at
Day +20 (2026-06-03): Volume 0.3x avg, no pattern, BB within bands, MACD hist -0.0058 (falling), EMA20(10.49) < EMA50(10.74), MFI 62.2, price below VWAP, below cloud, cloud bearish (red), thickness 1.41, tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.44 (2026-03-25), rejected at
Day +21 (2026-06-04): Volume 2.4x avg, no pattern, BB -1.4 sigma, MACD hist -0.0174 (falling), EMA20(10.46) < EMA50(10.72), MFI 55.5, price below VWAP, below cloud, cloud bearish (red), thickness 1.41, tested prior swing low at 10.01 (2026-05-18), held; tested prior swing high at 10.44 (2026-03-25), rejected at
Day +22 (2026-06-05): Volume 0.5x avg, no pattern, BB -1.3 sigma, MACD hist -0.0204 (falling), EMA20(10.43) < EMA50(10.70), MFI 50.9, price below VWAP, below cloud, cloud bearish (red), thickness 1.41, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.27 (2026-02-24), broke below; tested prior swing high at 10.44 (2026-03-25), rejected at
Day +23 (2026-06-08): Volume 0.3x avg, no pattern, BB -1.4 sigma, MACD hist -0.0250 (falling), EMA20(10.41) < EMA50(10.68), MFI 39.0, price below VWAP, below cloud, cloud bearish (red), thickness 1.12, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing low at 10.01 (2026-05-18), held; tested prior swing high at 10.10 (2026-03-12), broke above
Day +24 (2026-06-09): Volume 1.5x avg, no pattern, BB within bands, MACD hist -0.0092 (rising), EMA20(10.41) < EMA50(10.67), MFI 49.7, price below VWAP, below cloud, cloud bearish (red), thickness 0.85, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at
Day +25 (2026-06-10): Volume 0.8x avg, no pattern, BB within bands, MACD hist 0.0085 (rising), EMA20(10.42) < EMA50(10.66), MFI 55.7, price below VWAP, below cloud, cloud bearish (red), thickness 0.73, tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.60 (2026-03-05), rejected at
Day +26 (2026-06-11): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.0116 (rising), EMA20(10.41) < EMA50(10.65), MFI 55.3, price below VWAP, below cloud, cloud bearish (red), thickness 0.85, tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.44 (2026-03-25), rejected at
Day +27 (2026-06-12): Volume 2.0x avg, Doji formed (body(0.03) <= 0.1*range(0.39) [body/range=0.08]), BB within bands, MACD hist 0.0207 (rising), EMA20(10.42) < EMA50(10.64), MFI 58.6, price below VWAP, below cloud, cloud bearish (red), thickness 0.71, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.27 (2026-02-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day +28 (2026-06-15): Volume 0.7x avg, no pattern, BB +1.4 sigma, MACD hist 0.0344 (rising), EMA20(10.44) < EMA50(10.64), MFI 56.9, price below VWAP, below cloud, cloud bearish (red), thickness 0.71, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.75 (2026-04-01), rejected at
Day +29 (2026-06-16): Volume 1.6x avg, no pattern, BB +2.2 sigma, MACD hist 0.0514 (rising), EMA20(10.47) < EMA50(10.65), MFI 63.6, price below VWAP, below cloud, cloud bearish (red), thickness 0.64, tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.83 (2026-05-21), rejected at
Day +30 (2026-06-17): Volume 1.1x avg, no pattern, BB +1.8 sigma, MACD hist 0.0573 (rising), EMA20(10.49) < EMA50(10.65), MFI 68.6, price below VWAP, below cloud, cloud bearish (red), thickness 0.18, tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.83 (2026-05-21), rejected at
Day +31 (2026-06-18): Volume 1.0x avg, no pattern, BB +1.4 sigma, MACD hist 0.0559 (falling), EMA20(10.51) < EMA50(10.65), MFI 63.0, price below VWAP, below cloud, cloud bullish (green), thickness 0.22, tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.83 (2026-05-21), rejected at
Day +32 (2026-06-19): Volume 1.2x avg, no pattern, BB within bands, MACD hist 0.0485 (falling), EMA20(10.52) < EMA50(10.65), MFI 55.5, price below VWAP, inside cloud, cloud bullish (green), thickness 0.38, tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.83 (2026-05-21), rejected at
Day +33 (2026-06-22): Volume 0.6x avg, no pattern, BB within bands, MACD hist 0.0384 (falling), EMA20(10.52) < EMA50(10.65), MFI 58.5, price below VWAP, below cloud, cloud bullish (green), thickness 0.19, tested prior swing low at 10.48 (2026-04-24), held; tested prior swing high at 10.89 (2026-06-17), rejected at
Day +34 (2026-06-23): Volume 4.0x avg, no pattern, BB +2.1 sigma, MACD hist 0.0511 (rising), EMA20(10.56) < EMA50(10.66), MFI 69.9, price below VWAP, above cloud, cloud bullish (green), thickness 0.15, tested prior swing low at 10.45 (2026-04-13), held; tested prior swing high at 11.15 (2026-05-14), rejected at
Day +35 (2026-06-24): Volume 3.1x avg, no pattern, BB +2.9 sigma, MACD hist 0.0819 (rising), EMA20(10.63) < EMA50(10.68), MFI 85.5, price above VWAP, above cloud, cloud bullish (green), thickness 0.20, tested prior swing high at 11.65 (2026-04-17), rejected at
Day +36 (2026-06-29): Volume 2.4x avg, no pattern, BB +1.4 sigma, MACD hist 0.0737 (falling), EMA20(10.66) < EMA50(10.69), MFI 71.9, price below VWAP, above cloud, cloud bullish (green), thickness 0.20, tested prior swing high at 11.65 (2026-04-17), rejected at
Day +37 (2026-06-30): Volume 5.5x avg, Bullish Engulfing formed (prior_close(10.94)<prior_open(11.30, bearish) AND close(12.03)>open(10.93, bullish) AND open(10.93) <= prior_close(10.94) AND close(12.03) >= prior_open(11.30) [today body 10.93→12.03 engulfs prior 11.30→10.94]), BB +3.3 sigma, MACD hist 0.1339 (rising), EMA20(10.79) > EMA50(10.74), MFI 82.3, price above VWAP, above cloud, cloud bullish (green), thickness 0.21, tested prior swing high at 12.16 (2026-04-28), rejected at
Day +38 (2026-07-01): Volume 2.2x avg, no pattern, BB +2.1 sigma, MACD hist 0.1428 (rising), EMA20(10.88) > EMA50(10.78), MFI 84.1, price above VWAP, above cloud, cloud bullish (green), thickness 0.21
Day +39 (2026-07-02): Volume 0.7x avg, no pattern, BB +1.9 sigma, MACD hist 0.1438 (rising), EMA20(10.96) > EMA50(10.82), MFI 79.9, price above VWAP, above cloud, cloud bullish (green), thickness 0.21, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing high at 12.16 (2026-04-28), rejected at
Day +40 (2026-07-03): Volume 2.5x avg, Bullish Engulfing formed (prior_close(11.76)<prior_open(11.80, bearish) AND close(12.02)>open(11.76, bullish) AND open(11.76) <= prior_close(11.76) AND close(12.02) >= prior_open(11.80) [today body 11.76→12.02 engulfs prior 11.80→11.76]), BB +2.0 sigma, MACD hist 0.1521 (rising), EMA20(11.06) > EMA50(10.87), MFI 83.7, price above VWAP, above cloud, cloud bullish (green), thickness 0.21, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)

### Flow divergence check

18 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-04-15: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-04-27: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-04-30: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-05-06: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-07: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-08: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-11: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-20: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-21: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-25: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-01: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-05: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-08: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-06-09: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-12: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-15: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-07-02: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-07-03: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
---

## STOCK 9 — PREMA

### Data coverage & ticker identity

Report window: **2026-03-15 to 2026-04-27**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **PREMA** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `PREMA` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Chart structure:** 03-16 through 03-29 drifts down into a Doji-marked low on 03-18, reaching a genuine Bollinger extreme (-2.2 sigma) exactly on the reference move-start date, 03-30. Volume and price both build over the following two weeks; the highest-conviction breakout day is 04-14 (3.24x volume), roughly three weeks into the window, with an EMA20/50 golden cross following on 04-24, close to the window's end. No MACD histogram sign flip was detected in-window (it may have flipped before 03-16, outside this report's start).

### Core day-by-day table (OHLC, candles, trend)

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-03-16 | 26.79 | 26.92 | 25.90 | 25.94 | 281,622 | 953,468 | 0.30 | — | — | -11.1% vs SMA20(29.17) | -26.3% vs SMA50(35.20) | within bands | 0.0551 | rising | EMA20(29.22) < EMA50(33.35) | 34.50 | — |
| 2026-03-17 | 26.49 | 26.49 | 25.20 | 25.72 | 205,786 | 915,426 | 0.22 | — | — | -10.1% vs SMA20(28.60) | -26.3% vs SMA50(34.92) | within bands | 0.0985 | rising | EMA20(28.89) < EMA50(33.05) | 34.00 | — |
| 2026-03-18 | 25.85 | 26.47 | 25.61 | 25.91 | 409,095 | 892,293 | 0.46 | Doji | body(0.06) <= 0.1*range(0.86) [body/range=0.07] | -7.5% vs SMA20(28.00) | -25.2% vs SMA50(34.63) | within bands | 0.1589 | rising | EMA20(28.60) < EMA50(32.77) | 34.90 | tested prior swing low at 25.20 (2026-03-17), held |
| 2026-03-19 | 25.80 | 26.10 | 25.22 | 26.04 | 275,365 | 842,517 | 0.33 | Hammer | lower_wick(0.58) >= 2*body(0.24) AND upper_wick(0.06) <= 0.3*body(0.24) AND high(26.10)-max(open,close)(26.04)=0.06 <= 0.15*range(0.88) | -5.6% vs SMA20(27.58) | -24.2% vs SMA50(34.34) | within bands | 0.2225 | rising | EMA20(28.36) < EMA50(32.50) | 35.50 | tested prior swing low at 25.20 (2026-03-17), held |
| 2026-03-20 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-03-23 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-03-24 | 26.50 | 27.34 | 26.40 | 26.45 | 312,670 | 731,350 | 0.43 | Doji | body(0.05) <= 0.1*range(0.94) [body/range=0.05] | -3.0% vs SMA20(27.27) | -22.3% vs SMA50(34.05) | within bands | 0.3022 | rising | EMA20(28.18) < EMA50(32.27) | 37.60 | — |
| 2026-03-25 | 26.50 | 27.27 | 26.00 | 27.10 | 790,824 | 710,896 | 1.11 | — | — | -0.1% vs SMA20(27.12) | -19.8% vs SMA50(33.77) | within bands | 0.4025 | rising | EMA20(28.07) < EMA50(32.06) | 40.80 | tested prior swing high at 27.34 (2026-03-24), rejected at |
| 2026-03-26 | 27.09 | 27.09 | 26.00 | 26.06 | 699,008 | 672,146 | 1.04 | — | — | -3.4% vs SMA20(26.97) | -22.2% vs SMA50(33.48) | within bands | 0.4016 | falling | EMA20(27.88) < EMA50(31.83) | 37.50 | tested prior swing high at 27.34 (2026-03-24), rejected at |
| 2026-03-27 | 26.48 | 26.48 | 25.00 | 25.07 | 550,528 | 676,319 | 0.81 | — | — | -6.3% vs SMA20(26.77) | -24.4% vs SMA50(33.18) | -1.1 sigma | 0.3397 | falling | EMA20(27.61) < EMA50(31.56) | 34.60 | tested prior swing low at 25.20 (2026-03-17), broke below |
| 2026-03-30 | 25.02 | 25.02 | 23.00 | 23.54 | 499,515 | 623,495 | 0.80 | — | — | -10.8% vs SMA20(26.38) | -28.4% vs SMA50(32.87) | -2.2 sigma | 0.2074 | falling | EMA20(27.23) < EMA50(31.25) | 30.60 | — |
| 2026-03-31 | 23.97 | 24.11 | 23.20 | 23.64 | 249,006 | 588,509 | 0.42 | — | — | -9.3% vs SMA20(26.06) | -27.4% vs SMA50(32.57) | -2.1 sigma | 0.1416 | falling | EMA20(26.89) < EMA50(30.95) | 31.20 | tested prior swing low at 23.00 (2026-03-30), held |
| 2026-04-01 | 24.00 | 25.25 | 24.00 | 24.68 | 680,690 | 577,713 | 1.18 | — | — | -4.9% vs SMA20(25.95) | -23.5% vs SMA50(32.28) | -1.1 sigma | 0.1806 | rising | EMA20(26.68) < EMA50(30.70) | 36.80 | tested prior swing low at 24.21 (2026-03-03), held |
| 2026-04-02 | 24.34 | 24.35 | 23.52 | 24.22 | 233,030 | 526,579 | 0.44 | Hammer | lower_wick(0.70) >= 2*body(0.12) AND upper_wick(0.01) <= 0.3*body(0.12) AND high(24.35)-max(open,close)(24.34)=0.01 <= 0.15*range(0.83) | -6.5% vs SMA20(25.91) | -24.3% vs SMA50(31.99) | -1.4 sigma | 0.1870 | rising | EMA20(26.44) < EMA50(30.45) | 35.40 | — |
| 2026-04-03 | 23.50 | 24.00 | 23.13 | 23.96 | 258,699 | 492,394 | 0.53 | — | — | -7.0% vs SMA20(25.77) | -24.4% vs SMA50(31.69) | -1.4 sigma | 0.1851 | falling | EMA20(26.21) < EMA50(30.20) | 34.60 | tested prior swing low at 23.00 (2026-03-30), held |
| 2026-04-06 | 24.05 | 24.40 | 23.60 | 24.22 | 290,664 | 459,900 | 0.63 | — | — | -5.3% vs SMA20(25.58) | -22.9% vs SMA50(31.39) | -1.1 sigma | 0.2107 | rising | EMA20(26.02) < EMA50(29.96) | 36.20 | — |
| 2026-04-07 | 24.01 | 24.88 | 24.00 | 24.63 | 188,013 | 442,500 | 0.42 | — | — | -3.1% vs SMA20(25.43) | -20.8% vs SMA50(31.11) | within bands | 0.2615 | rising | EMA20(25.88) < EMA50(29.75) | 38.60 | tested prior swing low at 24.21 (2026-03-03), held |
| 2026-04-08 | 26.50 | 27.09 | 26.50 | 27.09 | 1,053,576 | 459,185 | 2.29 | — | — | +6.1% vs SMA20(25.54) | -12.3% vs SMA50(30.87) | +1.3 sigma | 0.4554 | rising | EMA20(26.00) < EMA50(29.65) | 50.90 | tested prior swing high at 27.34 (2026-03-24), rejected at |
| 2026-04-09 | 27.01 | 27.21 | 26.21 | 26.54 | 618,068 | 432,431 | 1.43 | — | — | +3.9% vs SMA20(25.53) | -13.4% vs SMA50(30.64) | within bands | 0.5359 | rising | EMA20(26.05) < EMA50(29.53) | 48.50 | tested prior swing high at 27.34 (2026-03-24), rejected at |
| 2026-04-10 | 26.67 | 27.50 | 26.67 | 27.16 | 910,305 | 452,388 | 2.01 | — | — | +6.3% vs SMA20(25.56) | -10.7% vs SMA50(30.42) | +1.4 sigma | 0.6145 | rising | EMA20(26.16) < EMA50(29.43) | 51.30 | tested prior swing high at 27.34 (2026-03-24), rejected at |
| 2026-04-13 | 25.50 | 26.74 | 25.50 | 26.11 | 890,937 | 482,514 | 1.85 | — | — | +2.3% vs SMA20(25.53) | -13.5% vs SMA50(30.18) | within bands | 0.5798 | falling | EMA20(26.15) < EMA50(29.30) | 46.80 | tested prior swing low at 25.20 (2026-03-17), held |
| 2026-04-14 | 26.50 | 28.72 | 26.50 | 28.72 | 1,819,791 | 560,860 | 3.24 | — | — | +12.0% vs SMA20(25.64) | -4.3% vs SMA50(30.00) | +2.3 sigma | 0.7082 | rising | EMA20(26.40) < EMA50(29.28) | 56.90 | tested prior swing high at 28.49 (2026-03-05), broke above |
| 2026-04-15 | 31.00 | 31.59 | 30.50 | 31.59 | 1,766,630 | 635,110 | 2.78 | — | — | +21.9% vs SMA20(25.92) | +5.7% vs SMA50(29.88) | +3.0 sigma | 0.9470 | rising | EMA20(26.89) < EMA50(29.37) | 64.80 | tested prior swing high at 32.00 (2026-02-27), rejected at |
| 2026-04-16 | 32.88 | 34.75 | 32.50 | 34.75 | 5,340,438 | 891,843 | 5.99 | — | — | +31.8% vs SMA20(26.37) | +16.5% vs SMA50(29.82) | +3.1 sigma | 1.26 | rising | EMA20(27.64) < EMA50(29.58) | 71.10 | — |
| 2026-04-17 | 35.04 | 38.00 | 35.04 | 37.78 | 7,328,999 | 1,237,838 | 5.92 | — | — | +40.1% vs SMA20(26.97) | +26.7% vs SMA50(29.81) | +3.0 sigma | 1.59 | rising | EMA20(28.61) < EMA50(29.90) | 75.60 | — |
| 2026-04-20 | 35.99 | 37.90 | 34.00 | 35.68 | 3,812,786 | 1,414,709 | 2.70 | Doji | body(0.31) <= 0.1*range(3.90) [body/range=0.08] | +30.0% vs SMA20(27.45) | +20.2% vs SMA50(29.68) | +2.0 sigma | 1.58 | falling | EMA20(29.28) < EMA50(30.13) | 67.70 | tested prior swing high at 38.00 (2026-04-17), rejected at |
| 2026-04-21 | 36.02 | 37.74 | 34.81 | 35.11 | 4,992,112 | 1,648,681 | 3.03 | — | — | +25.9% vs SMA20(27.88) | +18.7% vs SMA50(29.58) | +1.6 sigma | 1.46 | falling | EMA20(29.83) < EMA50(30.32) | 65.70 | tested prior swing high at 38.00 (2026-04-17), rejected at |
| 2026-04-22 | 34.70 | 35.25 | 34.00 | 34.12 | 787,474 | 1,648,513 | 0.48 | — | — | +20.8% vs SMA20(28.23) | +15.7% vs SMA50(29.48) | +1.3 sigma | 1.24 | falling | EMA20(30.24) < EMA50(30.47) | 62.30 | — |
| 2026-04-23 | 34.30 | 34.30 | 32.16 | 32.66 | 1,520,889 | 1,689,608 | 0.90 | — | — | +14.3% vs SMA20(28.56) | +11.3% vs SMA50(29.36) | within bands | 0.9362 | falling | EMA20(30.47) < EMA50(30.56) | 57.50 | — |
| 2026-04-24 | 31.82 | 35.93 | 30.75 | 35.93 | 2,558,983 | 1,790,030 | 1.43 | Bullish Engulfing | prior_close(32.66)<prior_open(34.30, bearish) AND close(35.93)>open(31.82, bullish) AND open(31.82) <= prior_close(32.66) AND close(35.93) >= prior_open(34.30) [today body 31.82→35.93 engulfs prior 34.30→32.66] | +23.4% vs SMA20(29.11) | +22.8% vs SMA50(29.26) | +1.4 sigma | 0.8982 | falling | EMA20(30.99) > EMA50(30.77) | 64.10 | — |
| 2026-04-27 | 37.01 | 39.25 | 36.55 | 37.62 | 10,808,531 | 2,305,481 | 4.69 | — | — | +26.2% vs SMA20(29.81) | +28.7% vs SMA50(29.23) | +1.6 sigma | 0.9248 | rising | EMA20(31.62) > EMA50(31.04) | 67.00 | tested prior swing low at 37.00 (2026-01-30), held |

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-03-16 | 52.80 | -9,669,608 | -25,050,679 | 1.89 | 26.25 | below | 26.49 | 33.30 | cloud not yet formed (insufficient history) | — |
| 2026-03-17 | 49.60 | -9,875,394 | -25,090,560 | 1.85 | 26.06 | below | 26.66 | 33.30 | cloud not yet formed (insufficient history) | — |
| 2026-03-18 | 42.20 | -9,466,299 | -25,214,240 | 1.78 | 26.03 | below | 26.61 | 33.30 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-03-19 | 46.20 | -9,190,934 | -24,976,425 | 1.71 | 25.98 | above | 26.41 | 32.50 | cloud not yet formed (insufficient history) | — |
| 2026-03-20 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-03-23 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-03-24 | 53.60 | -8,878,264 | -25,255,832 | 1.68 | 26.13 | above | 26.60 | 31.90 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-03-25 | 66.70 | -8,087,440 | -24,676,725 | 1.65 | 26.36 | above | 26.60 | 31.53 | cloud not yet formed (insufficient history) | — |
| 2026-03-26 | 56.30 | -8,786,448 | -25,298,778 | 1.61 | 26.37 | below | 26.27 | 31.45 | cloud not yet formed (insufficient history) | — |
| 2026-03-27 | 45.80 | -9,336,976 | -25,797,229 | 1.60 | 26.23 | below | 26.17 | 31.45 | cloud not yet formed (insufficient history) | — |
| 2026-03-30 | 46.60 | -9,836,491 | -26,029,676 | 1.64 | 25.94 | below | 25.17 | 30.62 | cloud not yet formed (insufficient history) | — |
| 2026-03-31 | 50.00 | -9,587,485 | -26,037,885 | 1.59 | 25.81 | below | 25.17 | 28.77 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-04-01 | 45.60 | -8,906,795 | -25,977,985 | 1.59 | 25.65 | below | 25.17 | 28.00 | cloud not yet formed (insufficient history) | — |
| 2026-04-02 | 38.70 | -9,139,825 | -25,817,952 | 1.56 | 25.57 | below | 25.17 | 27.50 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-04-03 | 39.10 | -9,398,524 | -25,583,041 | 1.52 | 25.48 | below | 25.17 | 27.50 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-04-06 | 43.90 | -9,107,860 | -25,423,176 | 1.47 | 25.41 | below | 25.13 | 27.50 | cloud not yet formed (insufficient history) | — |
| 2026-04-07 | 47.90 | -8,919,847 | -25,341,989 | 1.43 | 25.38 | below | 25.05 | 27.50 | cloud not yet formed (insufficient history) | — |
| 2026-04-08 | 58.40 | -7,866,271 | -24,288,413 | 1.50 | 25.61 | above | 25.05 | 25.74 | cloud not yet formed (insufficient history) | — |
| 2026-04-09 | 50.20 | -8,484,339 | -24,498,556 | 1.47 | 25.70 | above | 25.11 | 25.74 | cloud not yet formed (insufficient history) | — |
| 2026-04-10 | 58.60 | -7,574,034 | -24,334,043 | 1.43 | 25.85 | above | 25.31 | 25.74 | cloud not yet formed (insufficient history) | — |
| 2026-04-13 | 50.20 | -8,464,971 | -24,348,413 | 1.45 | 25.87 | above | 25.31 | 25.74 | cloud not yet formed (insufficient history) | — |
| 2026-04-14 | 56.50 | -6,645,180 | -22,528,622 | 1.53 | 26.21 | above | 25.92 | 25.86 | cloud not yet formed (insufficient history) | — |
| 2026-04-15 | 69.20 | -4,878,550 | -20,761,992 | 1.63 | 26.90 | above | 27.36 | 27.30 | cloud not yet formed (insufficient history) | — |
| 2026-04-16 | 84.20 | 461,888 | -15,421,554 | 1.74 | 28.97 | above | 29.18 | 28.88 | cloud not yet formed (insufficient history) | — |
| 2026-04-17 | 91.80 | 7,790,887 | -9,182,001 | 1.84 | 31.24 | above | 31.00 | 30.50 | cloud not yet formed (insufficient history) | — |
| 2026-04-20 | 77.30 | 3,978,101 | -9,709,925 | 1.99 | 31.84 | above | 31.75 | 30.50 | cloud not yet formed (insufficient history) | — |
| 2026-04-21 | 81.00 | -1,014,011 | -13,679,761 | 2.06 | 32.43 | above | 31.75 | 30.50 | cloud not yet formed (insufficient history) | — |
| 2026-04-22 | 79.30 | -1,801,485 | -14,316,040 | 2.00 | 32.47 | above | 31.75 | 30.50 | cloud not yet formed (insufficient history) | — |
| 2026-04-23 | 76.00 | -3,322,374 | -15,126,234 | 2.01 | 32.50 | above | 31.75 | 30.50 | cloud not yet formed (insufficient history) | — |
| 2026-04-24 | 77.70 | -763,391 | -12,567,251 | 2.24 | 32.61 | above | 32.25 | 30.50 | cloud not yet formed (insufficient history) | — |
| 2026-04-27 | 83.50 | 10,045,140 | -14,809,020 | 2.31 | 33.73 | above | 34.88 | 31.12 | above cloud, cloud bearish (red), thickness 4.15 | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-03-30 = Day 0).

Day -8 (2026-03-16): Volume 0.3x avg, no pattern, BB within bands, MACD hist 0.0551 (rising), EMA20(29.22) < EMA50(33.35), MFI 52.8, price below VWAP
Day -7 (2026-03-17): Volume 0.2x avg, no pattern, BB within bands, MACD hist 0.0985 (rising), EMA20(28.89) < EMA50(33.05), MFI 49.6, price below VWAP
Day -6 (2026-03-18): Volume 0.5x avg, Doji formed (body(0.06) <= 0.1*range(0.86) [body/range=0.07]), BB within bands, MACD hist 0.1589 (rising), EMA20(28.60) < EMA50(32.77), MFI 42.2, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 25.20 (2026-03-17), held
Day -5 (2026-03-19): Volume 0.3x avg, Hammer formed (lower_wick(0.58) >= 2*body(0.24) AND upper_wick(0.06) <= 0.3*body(0.24) AND high(26.10)-max(open,close)(26.04)=0.06 <= 0.15*range(0.88)), BB within bands, MACD hist 0.2225 (rising), EMA20(28.36) < EMA50(32.50), MFI 46.2, price above VWAP, tested prior swing low at 25.20 (2026-03-17), held
Day -4 (2026-03-24): Volume 0.4x avg, Doji formed (body(0.05) <= 0.1*range(0.94) [body/range=0.05]), BB within bands, MACD hist 0.3022 (rising), EMA20(28.18) < EMA50(32.27), MFI 53.6, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day -3 (2026-03-25): Volume 1.1x avg, no pattern, BB within bands, MACD hist 0.4025 (rising), EMA20(28.07) < EMA50(32.06), MFI 66.7, price above VWAP, tested prior swing high at 27.34 (2026-03-24), rejected at
Day -2 (2026-03-26): Volume 1.0x avg, no pattern, BB within bands, MACD hist 0.4016 (falling), EMA20(27.88) < EMA50(31.83), MFI 56.3, price below VWAP, tested prior swing high at 27.34 (2026-03-24), rejected at
Day -1 (2026-03-27): Volume 0.8x avg, no pattern, BB -1.1 sigma, MACD hist 0.3397 (falling), EMA20(27.61) < EMA50(31.56), MFI 45.8, price below VWAP, tested prior swing low at 25.20 (2026-03-17), broke below
Day 0 (2026-03-30): Volume 0.8x avg, no pattern, BB -2.2 sigma, MACD hist 0.2074 (falling), EMA20(27.23) < EMA50(31.25), MFI 46.6, price below VWAP
Day +1 (2026-03-31): Volume 0.4x avg, no pattern, BB -2.1 sigma, MACD hist 0.1416 (falling), EMA20(26.89) < EMA50(30.95), MFI 50.0, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 23.00 (2026-03-30), held
Day +2 (2026-04-01): Volume 1.2x avg, no pattern, BB -1.1 sigma, MACD hist 0.1806 (rising), EMA20(26.68) < EMA50(30.70), MFI 45.6, price below VWAP, tested prior swing low at 24.21 (2026-03-03), held
Day +3 (2026-04-02): Volume 0.4x avg, Hammer formed (lower_wick(0.70) >= 2*body(0.12) AND upper_wick(0.01) <= 0.3*body(0.12) AND high(24.35)-max(open,close)(24.34)=0.01 <= 0.15*range(0.83)), BB -1.4 sigma, MACD hist 0.1870 (rising), EMA20(26.44) < EMA50(30.45), MFI 38.7, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
Day +4 (2026-04-03): Volume 0.5x avg, no pattern, BB -1.4 sigma, MACD hist 0.1851 (falling), EMA20(26.21) < EMA50(30.20), MFI 39.1, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing low at 23.00 (2026-03-30), held
Day +5 (2026-04-06): Volume 0.6x avg, no pattern, BB -1.1 sigma, MACD hist 0.2107 (rising), EMA20(26.02) < EMA50(29.96), MFI 43.9, price below VWAP
Day +6 (2026-04-07): Volume 0.4x avg, no pattern, BB within bands, MACD hist 0.2615 (rising), EMA20(25.88) < EMA50(29.75), MFI 47.9, price below VWAP, tested prior swing low at 24.21 (2026-03-03), held
Day +7 (2026-04-08): Volume 2.3x avg, no pattern, BB +1.3 sigma, MACD hist 0.4554 (rising), EMA20(26.00) < EMA50(29.65), MFI 58.4, price above VWAP, tested prior swing high at 27.34 (2026-03-24), rejected at
Day +8 (2026-04-09): Volume 1.4x avg, no pattern, BB within bands, MACD hist 0.5359 (rising), EMA20(26.05) < EMA50(29.53), MFI 50.2, price above VWAP, tested prior swing high at 27.34 (2026-03-24), rejected at
Day +9 (2026-04-10): Volume 2.0x avg, no pattern, BB +1.4 sigma, MACD hist 0.6145 (rising), EMA20(26.16) < EMA50(29.43), MFI 58.6, price above VWAP, tested prior swing high at 27.34 (2026-03-24), rejected at
Day +10 (2026-04-13): Volume 1.9x avg, no pattern, BB within bands, MACD hist 0.5798 (falling), EMA20(26.15) < EMA50(29.30), MFI 50.2, price above VWAP, tested prior swing low at 25.20 (2026-03-17), held
Day +11 (2026-04-14): Volume 3.2x avg, no pattern, BB +2.3 sigma, MACD hist 0.7082 (rising), EMA20(26.40) < EMA50(29.28), MFI 56.5, price above VWAP, tested prior swing high at 28.49 (2026-03-05), broke above
Day +12 (2026-04-15): Volume 2.8x avg, no pattern, BB +3.0 sigma, MACD hist 0.9470 (rising), EMA20(26.89) < EMA50(29.37), MFI 69.2, price above VWAP, tested prior swing high at 32.00 (2026-02-27), rejected at
Day +13 (2026-04-16): Volume 6.0x avg, no pattern, BB +3.1 sigma, MACD hist 1.2588 (rising), EMA20(27.64) < EMA50(29.58), MFI 84.2, price above VWAP
Day +14 (2026-04-17): Volume 5.9x avg, no pattern, BB +3.0 sigma, MACD hist 1.5890 (rising), EMA20(28.61) < EMA50(29.90), MFI 91.8, price above VWAP
Day +15 (2026-04-20): Volume 2.7x avg, Doji formed (body(0.31) <= 0.1*range(3.90) [body/range=0.08]), BB +2.0 sigma, MACD hist 1.5822 (falling), EMA20(29.28) < EMA50(30.13), MFI 77.3, price above VWAP, tested prior swing high at 38.00 (2026-04-17), rejected at
Day +16 (2026-04-21): Volume 3.0x avg, no pattern, BB +1.6 sigma, MACD hist 1.4588 (falling), EMA20(29.83) < EMA50(30.32), MFI 81.0, price above VWAP, tested prior swing high at 38.00 (2026-04-17), rejected at
Day +17 (2026-04-22): Volume 0.5x avg, no pattern, BB +1.3 sigma, MACD hist 1.2385 (falling), EMA20(30.24) < EMA50(30.47), MFI 79.3, price above VWAP
Day +18 (2026-04-23): Volume 0.9x avg, no pattern, BB within bands, MACD hist 0.9362 (falling), EMA20(30.47) < EMA50(30.56), MFI 76.0, price above VWAP
Day +19 (2026-04-24): Volume 1.4x avg, Bullish Engulfing formed (prior_close(32.66)<prior_open(34.30, bearish) AND close(35.93)>open(31.82, bullish) AND open(31.82) <= prior_close(32.66) AND close(35.93) >= prior_open(34.30) [today body 31.82→35.93 engulfs prior 34.30→32.66]), BB +1.4 sigma, MACD hist 0.8982 (falling), EMA20(30.99) > EMA50(30.77), MFI 77.7, price above VWAP
Day +20 (2026-04-27): Volume 4.7x avg, no pattern, BB +1.6 sigma, MACD hist 0.9248 (rising), EMA20(31.62) > EMA50(31.04), MFI 83.5, price above VWAP, above cloud, cloud bearish (red), thickness 4.15, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 37.00 (2026-01-30), held

### Flow divergence check

6 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-03-18: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-03-24: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-03-31: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-04-02: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-04-03: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-04-27: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
---

## STOCK 10 — JSBL

### Data coverage & ticker identity

Report window: **2026-05-04 to 2026-06-02**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **JSBL** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `JSBL` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Chart structure:** 05-04 opens the window already at 13.66; 05-06 (day -9) is an extreme single-day volume spike (10.7x the 20-day average) alongside a Bollinger extreme, both well before the reference move-start (05-19). A Bullish Engulfing on 05-25 and the MACD sign flip/breakout day on 05-29 (2.6x volume) follow. Window closes 13.78 on 06-02, close to its open (14.50) that day after an intraday pullback from a high of 15.20 (matching the user's reference).

### Core day-by-day table (OHLC, candles, trend)

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-04 | 14.47 | 14.50 | 12.35 | 13.66 | 98,832 | 467,928 | 0.21 | — | — | -6.6% vs SMA20(14.63) | insufficient history | -1.0 sigma | -0.2391 | falling | EMA20(14.31) > EMA50(14.05) | 45.20 | tested prior swing high at 14.27 (2026-03-09), rejected at |
| 2026-05-05 | 13.01 | 13.80 | 13.00 | 13.65 | 46,882 | 407,423 | 0.12 | — | — | -6.7% vs SMA20(14.63) | insufficient history | -1.0 sigma | -0.2486 | falling | EMA20(14.25) > EMA50(14.04) | 45.20 | tested prior swing high at 13.85 (2026-03-13), rejected at |
| 2026-05-06 | 13.75 | 14.00 | 12.29 | 12.29 | 9,298,677 | 868,701 | 10.70 | — | — | -15.6% vs SMA20(14.56) | -8.5% vs SMA50(13.43) | -2.2 sigma | -0.3316 | falling | EMA20(14.06) > EMA50(13.97) | 37.30 | tested prior swing high at 13.85 (2026-03-13), rejected at |
| 2026-05-07 | 12.44 | 12.58 | 12.11 | 12.22 | 1,506,130 | 883,755 | 1.70 | — | — | -15.5% vs SMA20(14.47) | -8.6% vs SMA50(13.37) | -1.9 sigma | -0.3731 | falling | EMA20(13.89) < EMA50(13.90) | 36.90 | — |
| 2026-05-08 | 12.25 | 12.36 | 11.98 | 12.00 | 1,078,193 | 890,048 | 1.21 | — | — | -16.8% vs SMA20(14.42) | -9.8% vs SMA50(13.31) | -1.9 sigma | -0.3952 | falling | EMA20(13.71) < EMA50(13.83) | 35.80 | — |
| 2026-05-11 | 12.10 | 12.23 | 11.94 | 11.96 | 887,067 | 891,923 | 0.99 | — | — | -16.4% vs SMA20(14.30) | -9.9% vs SMA50(13.28) | -1.7 sigma | -0.3916 | rising | EMA20(13.54) < EMA50(13.75) | 35.60 | — |
| 2026-05-12 | 12.00 | 12.19 | 11.49 | 11.57 | 4,180,113 | 1,093,891 | 3.82 | — | — | -18.3% vs SMA20(14.16) | -12.6% vs SMA50(13.23) | -1.8 sigma | -0.3935 | falling | EMA20(13.35) < EMA50(13.67) | 33.40 | — |
| 2026-05-13 | 11.79 | 11.91 | 11.40 | 11.61 | 10,093,867 | 1,586,802 | 6.36 | — | — | -17.0% vs SMA20(13.99) | -12.0% vs SMA50(13.19) | -1.5 sigma | -0.3704 | rising | EMA20(13.19) < EMA50(13.59) | 33.90 | — |
| 2026-05-14 | 11.86 | 11.86 | 11.55 | 11.57 | 926,640 | 1,624,871 | 0.57 | — | — | -16.1% vs SMA20(13.79) | -12.2% vs SMA50(13.18) | -1.4 sigma | -0.3371 | rising | EMA20(13.03) < EMA50(13.51) | 33.60 | tested prior swing low at 11.40 (2026-05-13), held |
| 2026-05-15 | 11.79 | 11.79 | 11.51 | 11.66 | 344,761 | 1,635,434 | 0.21 | — | — | -14.2% vs SMA20(13.59) | -11.6% vs SMA50(13.19) | -1.2 sigma | -0.2901 | rising | EMA20(12.90) < EMA50(13.44) | 34.70 | tested prior swing low at 11.40 (2026-05-13), held |
| 2026-05-18 | 11.80 | 11.80 | 11.45 | 11.48 | 199,991 | 1,637,837 | 0.12 | — | — | -14.0% vs SMA20(13.35) | -13.0% vs SMA50(13.19) | -1.2 sigma | -0.2535 | rising | EMA20(12.77) < EMA50(13.36) | 33.50 | tested prior swing low at 11.40 (2026-05-13), held |
| 2026-05-19 | 11.78 | 11.78 | 11.21 | 11.40 | 228,634 | 1,639,058 | 0.14 | — | — | -13.1% vs SMA20(13.12) | -13.5% vs SMA50(13.18) | -1.2 sigma | -0.2185 | rising | EMA20(12.64) < EMA50(13.28) | 33.00 | tested prior swing low at 11.40 (2026-05-13), held |
| 2026-05-20 | 11.41 | 11.61 | 11.30 | 11.45 | 85,264 | 1,633,765 | 0.05 | — | — | -11.2% vs SMA20(12.90) | -12.9% vs SMA50(13.15) | -1.1 sigma | -0.1774 | rising | EMA20(12.52) < EMA50(13.21) | 33.70 | tested prior swing low at 11.21 (2026-05-19), held |
| 2026-05-21 | 11.46 | 11.75 | 11.35 | 11.54 | 336,994 | 1,625,952 | 0.21 | — | — | -9.3% vs SMA20(12.72) | -12.2% vs SMA50(13.14) | within bands | -0.1318 | rising | EMA20(12.43) < EMA50(13.14) | 35.10 | tested prior swing low at 11.40 (2026-05-13), held |
| 2026-05-22 | 11.55 | 11.55 | 11.30 | 11.43 | 247,282 | 1,631,639 | 0.15 | — | — | -9.1% vs SMA20(12.57) | -12.9% vs SMA50(13.12) | within bands | -0.0982 | rising | EMA20(12.34) < EMA50(13.08) | 34.20 | tested prior swing low at 11.21 (2026-05-19), held |
| 2026-05-25 | 11.43 | 11.75 | 11.43 | 11.64 | 298,249 | 1,611,464 | 0.19 | Bullish Engulfing | prior_close(11.43)<prior_open(11.55, bearish) AND close(11.64)>open(11.43, bullish) AND open(11.43) <= prior_close(11.43) AND close(11.64) >= prior_open(11.55) [today body 11.43→11.64 engulfs prior 11.55→11.43] | -6.1% vs SMA20(12.40) | -11.2% vs SMA50(13.10) | within bands | -0.0531 | rising | EMA20(12.27) < EMA50(13.02) | 37.60 | tested prior swing low at 11.40 (2026-05-13), held |
| 2026-05-26 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-27 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-28 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-29 | 11.64 | 12.80 | 11.50 | 12.80 | 4,801,236 | 1,845,291 | 2.60 | — | — | +4.1% vs SMA20(12.30) | -2.3% vs SMA50(13.11) | within bands | 0.0574 | rising | EMA20(12.32) < EMA50(13.01) | 52.30 | tested prior swing low at 11.40 (2026-05-13), held |
| 2026-06-01 | 13.15 | 14.08 | 12.80 | 14.08 | 7,227,746 | 2,205,277 | 3.28 | — | — | +14.9% vs SMA20(12.26) | +7.2% vs SMA50(13.13) | +2.0 sigma | 0.2107 | rising | EMA20(12.49) < EMA50(13.05) | 62.70 | tested prior swing high at 14.27 (2026-03-09), rejected at |
| 2026-06-02 | 14.50 | 15.20 | 13.66 | 13.78 | 5,115,442 | 2,374,637 | 2.15 | — | — | +12.3% vs SMA20(12.27) | +4.7% vs SMA50(13.16) | +1.6 sigma | 0.2815 | rising | EMA20(12.61) < EMA50(13.08) | 59.50 | — |

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-04 | 38.90 | -916,769 | -3,578,909 | 1.33 | 13.50 | above | 14.32 | 13.48 | cloud not yet formed (insufficient history) | — |
| 2026-05-05 | 35.40 | -963,651 | -3,549,608 | 1.29 | 13.50 | above | 14.32 | 13.48 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-05-06 | 11.70 | -10,262,328 | -12,848,285 | 1.32 | 12.87 | below | 13.81 | 13.48 | cloud not yet formed (insufficient history) | — |
| 2026-05-07 | 9.70 | -11,768,458 | -13,649,418 | 1.26 | 12.79 | below | 13.72 | 14.16 | cloud not yet formed (insufficient history) | — |
| 2026-05-08 | 8.00 | -12,846,651 | -14,614,117 | 1.20 | 12.73 | below | 13.66 | 14.16 | cloud not yet formed (insufficient history) | — |
| 2026-05-11 | 7.80 | -13,733,718 | -15,378,830 | 1.14 | 12.68 | below | 13.64 | 14.37 | cloud not yet formed (insufficient history) | — |
| 2026-05-12 | 5.30 | -17,913,831 | -18,603,488 | 1.10 | 12.46 | below | 13.23 | 14.14 | cloud not yet formed (insufficient history) | — |
| 2026-05-13 | 3.70 | -7,819,964 | -20,384,759 | 1.06 | 12.15 | below | 12.95 | 14.10 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-14 | 6.40 | -8,746,604 | -21,191,833 | 1.01 | 12.14 | below | 12.95 | 14.10 | cloud not yet formed (insufficient history) | — |
| 2026-05-15 | 3.80 | -8,401,843 | -21,167,207 | 0.9560 | 12.13 | below | 12.70 | 14.10 | cloud not yet formed (insufficient history) | — |
| 2026-05-18 | 3.30 | -8,601,834 | -21,332,914 | 0.9127 | 12.13 | below | 12.70 | 14.10 | cloud not yet formed (insufficient history) | — |
| 2026-05-19 | 3.20 | -8,830,468 | -21,409,125 | 0.8883 | 12.12 | below | 11.89 | 14.01 | cloud not yet formed (insufficient history) | — |
| 2026-05-20 | 3.40 | -8,745,204 | -21,411,875 | 0.8470 | 12.12 | below | 11.79 | 14.01 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-21 | 4.50 | -8,408,210 | -21,428,725 | 0.8150 | 12.11 | below | 11.72 | 14.01 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-05-22 | 4.10 | -8,655,492 | -21,418,834 | 0.7747 | 12.11 | below | 11.70 | 14.01 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-05-25 | 5.10 | -8,357,243 | -21,325,631 | 0.7422 | 12.10 | below | 11.56 | 14.01 | cloud not yet formed (insufficient history) | — |
| 2026-05-26 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-27 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-28 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-29 | 25.90 | -3,556,007 | -16,524,395 | 0.7820 | 12.14 | above | 12.01 | 13.80 | cloud not yet formed (insufficient history) | — |
| 2026-06-01 | 46.50 | 3,671,739 | -9,296,649 | 0.8176 | 12.40 | above | 12.64 | 13.76 | cloud not yet formed (insufficient history) | — |
| 2026-06-02 | 56.70 | -1,443,703 | -13,614,879 | 0.8692 | 12.60 | above | 13.21 | 13.76 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-05-19 = Day 0).

Day -11 (2026-05-04): Volume 0.2x avg, no pattern, BB -1.0 sigma, MACD hist -0.2391 (falling), EMA20(14.31) > EMA50(14.05), MFI 38.9, price above VWAP, tested prior swing high at 14.27 (2026-03-09), rejected at
Day -10 (2026-05-05): Volume 0.1x avg, no pattern, BB -1.0 sigma, MACD hist -0.2486 (falling), EMA20(14.25) > EMA50(14.04), MFI 35.4, price above VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing high at 13.85 (2026-03-13), rejected at
Day -9 (2026-05-06): Volume 10.7x avg, no pattern, BB -2.2 sigma, MACD hist -0.3316 (falling), EMA20(14.06) > EMA50(13.97), MFI 11.7, price below VWAP, tested prior swing high at 13.85 (2026-03-13), rejected at
Day -8 (2026-05-07): Volume 1.7x avg, no pattern, BB -1.9 sigma, MACD hist -0.3731 (falling), EMA20(13.89) < EMA50(13.90), MFI 9.7, price below VWAP
Day -7 (2026-05-08): Volume 1.2x avg, no pattern, BB -1.9 sigma, MACD hist -0.3952 (falling), EMA20(13.71) < EMA50(13.83), MFI 8.0, price below VWAP
Day -6 (2026-05-11): Volume 1.0x avg, no pattern, BB -1.7 sigma, MACD hist -0.3916 (rising), EMA20(13.54) < EMA50(13.75), MFI 7.8, price below VWAP
Day -5 (2026-05-12): Volume 3.8x avg, no pattern, BB -1.8 sigma, MACD hist -0.3935 (falling), EMA20(13.35) < EMA50(13.67), MFI 5.3, price below VWAP
Day -4 (2026-05-13): Volume 6.4x avg, no pattern, BB -1.5 sigma, MACD hist -0.3704 (rising), EMA20(13.19) < EMA50(13.59), MFI 3.7, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
Day -3 (2026-05-14): Volume 0.6x avg, no pattern, BB -1.4 sigma, MACD hist -0.3371 (rising), EMA20(13.03) < EMA50(13.51), MFI 6.4, price below VWAP, tested prior swing low at 11.40 (2026-05-13), held
Day -2 (2026-05-15): Volume 0.2x avg, no pattern, BB -1.2 sigma, MACD hist -0.2901 (rising), EMA20(12.90) < EMA50(13.44), MFI 3.8, price below VWAP, tested prior swing low at 11.40 (2026-05-13), held
Day -1 (2026-05-18): Volume 0.1x avg, no pattern, BB -1.2 sigma, MACD hist -0.2535 (rising), EMA20(12.77) < EMA50(13.36), MFI 3.3, price below VWAP, tested prior swing low at 11.40 (2026-05-13), held
Day 0 (2026-05-19): Volume 0.1x avg, no pattern, BB -1.2 sigma, MACD hist -0.2185 (rising), EMA20(12.64) < EMA50(13.28), MFI 3.2, price below VWAP, tested prior swing low at 11.40 (2026-05-13), held
Day +1 (2026-05-20): Volume 0.1x avg, no pattern, BB -1.1 sigma, MACD hist -0.1774 (rising), EMA20(12.52) < EMA50(13.21), MFI 3.4, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 11.21 (2026-05-19), held
Day +2 (2026-05-21): Volume 0.2x avg, no pattern, BB within bands, MACD hist -0.1318 (rising), EMA20(12.43) < EMA50(13.14), MFI 4.5, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 11.40 (2026-05-13), held
Day +3 (2026-05-22): Volume 0.1x avg, no pattern, BB within bands, MACD hist -0.0982 (rising), EMA20(12.34) < EMA50(13.08), MFI 4.1, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing low at 11.21 (2026-05-19), held
Day +4 (2026-05-25): Volume 0.2x avg, Bullish Engulfing formed (prior_close(11.43)<prior_open(11.55, bearish) AND close(11.64)>open(11.43, bullish) AND open(11.43) <= prior_close(11.43) AND close(11.64) >= prior_open(11.55) [today body 11.43→11.64 engulfs prior 11.55→11.43]), BB within bands, MACD hist -0.0531 (rising), EMA20(12.27) < EMA50(13.02), MFI 5.1, price below VWAP, tested prior swing low at 11.40 (2026-05-13), held
Day +5 (2026-05-29): Volume 2.6x avg, no pattern, BB within bands, MACD hist 0.0574 (rising), EMA20(12.32) < EMA50(13.01), MFI 25.9, price above VWAP, tested prior swing low at 11.40 (2026-05-13), held
Day +6 (2026-06-01): Volume 3.3x avg, no pattern, BB +2.0 sigma, MACD hist 0.2107 (rising), EMA20(12.49) < EMA50(13.05), MFI 46.5, price above VWAP, tested prior swing high at 14.27 (2026-03-09), rejected at
Day +7 (2026-06-02): Volume 2.1x avg, no pattern, BB +1.6 sigma, MACD hist 0.2815 (rising), EMA20(12.61) < EMA50(13.08), MFI 56.7, price above VWAP

### Flow divergence check

5 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-05-05: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-05-13: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-20: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-21: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-05-22: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
---

## STOCK 11 — ILP

### Data coverage & ticker identity

Report window: **2026-05-18 to 2026-06-30**. OHLC pulled from `dps.psx.com.pk/historical` via `backend/dps_scraper.py`. Ticker identity for **ILP** confirmed two ways (announcements/company-page checking remains out of scope this round): (1) `ILP` is one of this project's own already-used, real PSX Watchlist symbols (`backend/app.py`'s `WATCHLIST_SYMBOLS`), and (2) the fetched OHLC on the user's exact reference dates matches the user-stated reference prices (see table below).

**Chart structure:** 05-18 through 06-03 is a shallow, choppy base (78-84 range), touching a Bollinger extreme (-1.8 sigma) on 05-18 itself. 06-04 (day +2) is a sharp single-day volume spike (9.5x average) that doubles as the breakout day, though price only firms up gradually after it; the real acceleration comes 06-12 through 06-30, with RSI climbing into the high 70s/low 80s and the window closing at 107.54 on 06-30, essentially matching the user's reference (107.00).

### Core day-by-day table (OHLC, candles, trend)

| Date | Open | High | Low | Close | Volume | Vol 20d avg | Vol ratio | Candle pattern | Pattern criteria met | Price vs MA20 | Price vs MA50 | BB position | MACD hist | MACD dir | EMA20 vs EMA50 | RSI(14) | Support/resistance note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-18 | 81.04 | 81.48 | 78.51 | 79.49 | 87,647 | 487,161 | 0.18 | — | — | -3.2% vs SMA20(82.12) | insufficient history | -1.8 sigma | -0.5932 | falling | EMA20(81.63) > EMA50(79.39) | 46.10 | tested prior swing low at 78.30 (2026-04-13), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-05-19 | 80.94 | 80.94 | 78.00 | 79.19 | 165,695 | 469,286 | 0.35 | — | — | -3.4% vs SMA20(81.98) | insufficient history | -1.7 sigma | -0.6600 | falling | EMA20(81.40) > EMA50(79.38) | 45.30 | tested prior swing low at 78.30 (2026-04-13), held |
| 2026-05-20 | 79.90 | 80.55 | 78.55 | 80.03 | 37,038 | 422,220 | 0.09 | Doji | body(0.13) <= 0.1*range(2.00) [body/range=0.06] | -2.2% vs SMA20(81.86) | +0.1% vs SMA50(79.95) | -1.1 sigma | -0.6214 | rising | EMA20(81.27) > EMA50(79.41) | 48.00 | tested prior swing low at 78.30 (2026-04-13), held |
| 2026-05-21 | 81.00 | 81.64 | 78.99 | 79.48 | 543,326 | 437,059 | 1.24 | — | — | -2.8% vs SMA20(81.78) | -0.8% vs SMA50(80.15) | -1.3 sigma | -0.6061 | rising | EMA20(81.10) > EMA50(79.41) | 46.40 | tested prior swing low at 79.01 (2026-04-24), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-05-22 | 80.00 | 80.99 | 79.50 | 80.32 | 156,547 | 435,957 | 0.36 | — | — | -1.8% vs SMA20(81.78) | +0.1% vs SMA50(80.22) | within bands | -0.5160 | rising | EMA20(81.02) > EMA50(79.45) | 49.20 | tested prior swing low at 79.01 (2026-04-24), held |
| 2026-05-25 | 82.00 | 83.50 | 81.00 | 82.89 | 463,141 | 449,459 | 1.03 | — | — | +1.2% vs SMA20(81.92) | +3.2% vs SMA50(80.30) | within bands | -0.2722 | rising | EMA20(81.20) > EMA50(79.58) | 56.70 | tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-05-26 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-27 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-28 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-29 | 82.27 | 83.00 | 81.46 | 81.98 | 276,098 | 431,011 | 0.64 | — | — | +0.2% vs SMA20(81.82) | +2.0% vs SMA50(80.39) | within bands | -0.1663 | rising | EMA20(81.28) > EMA50(79.67) | 53.70 | tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-06-01 | 82.97 | 82.97 | 81.00 | 81.31 | 127,810 | 387,906 | 0.33 | — | — | -0.5% vs SMA20(81.69) | +1.1% vs SMA50(80.45) | within bands | -0.1367 | rising | EMA20(81.28) > EMA50(79.74) | 51.50 | tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-06-02 | 80.75 | 81.92 | 79.01 | 80.99 | 142,065 | 336,744 | 0.42 | Doji | body(0.24) <= 0.1*range(2.91) [body/range=0.08] | -0.8% vs SMA20(81.62) | +0.6% vs SMA50(80.51) | within bands | -0.1339 | rising | EMA20(81.25) > EMA50(79.79) | 50.50 | tested prior swing low at 79.01 (2026-04-24), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-06-03 | 80.99 | 81.92 | 80.90 | 81.03 | 80,846 | 319,530 | 0.25 | Doji | body(0.04) <= 0.1*range(1.02) [body/range=0.04] | -0.7% vs SMA20(81.59) | +0.5% vs SMA50(80.60) | within bands | -0.1246 | rising | EMA20(81.23) > EMA50(79.84) | 50.60 | tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-06-04 | 80.70 | 84.00 | 80.60 | 81.67 | 5,507,939 | 579,804 | 9.50 | — | — | +0.1% vs SMA20(81.59) | +1.2% vs SMA50(80.69) | within bands | -0.0733 | rising | EMA20(81.27) > EMA50(79.91) | 52.80 | tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.50 (2026-05-25), rejected at |
| 2026-06-05 | 81.99 | 82.80 | 81.25 | 81.51 | 349,690 | 594,966 | 0.59 | — | — | -0.1% vs SMA20(81.59) | +0.9% vs SMA50(80.78) | within bands | -0.0492 | rising | EMA20(81.29) > EMA50(79.97) | 52.20 | tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-06-08 | 81.00 | 82.00 | 80.23 | 81.49 | 193,134 | 519,234 | 0.37 | — | — | +0.1% vs SMA20(81.40) | +0.8% vs SMA50(80.86) | within bands | -0.0343 | rising | EMA20(81.31) > EMA50(80.03) | 52.10 | tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at |
| 2026-06-09 | 81.49 | 83.99 | 81.49 | 82.81 | 2,202,330 | 599,918 | 3.67 | — | — | +1.8% vs SMA20(81.34) | +2.4% vs SMA50(80.88) | +1.2 sigma | 0.0596 | rising | EMA20(81.46) > EMA50(80.14) | 57.10 | tested prior swing low at 80.23 (2026-06-08), held; tested prior swing high at 84.00 (2026-06-04), rejected at |
| 2026-06-10 | 82.99 | 84.57 | 82.51 | 84.49 | 853,636 | 636,682 | 1.34 | — | — | +3.8% vs SMA20(81.39) | +4.3% vs SMA50(81.00) | +2.4 sigma | 0.2209 | rising | EMA20(81.74) > EMA50(80.31) | 62.40 | tested prior swing high at 85.00 (2026-04-27), rejected at |
| 2026-06-11 | 84.49 | 84.49 | 83.53 | 84.01 | 787,888 | 655,317 | 1.20 | — | — | +3.2% vs SMA20(81.43) | +3.6% vs SMA50(81.11) | +1.9 sigma | 0.2776 | rising | EMA20(81.96) > EMA50(80.46) | 60.10 | tested prior swing high at 84.00 (2026-06-04), broke above |
| 2026-06-12 | 84.02 | 88.00 | 84.02 | 87.32 | 2,092,821 | 754,158 | 2.78 | — | — | +6.9% vs SMA20(81.67) | +7.3% vs SMA50(81.36) | +3.0 sigma | 0.5071 | rising | EMA20(82.47) > EMA50(80.72) | 68.70 | tested prior swing high at 86.50 (2026-04-10), broke above |
| 2026-06-15 | 95.50 | 95.96 | 91.00 | 94.43 | 7,502,709 | 1,125,950 | 6.66 | — | — | +14.7% vs SMA20(82.30) | +15.4% vs SMA50(81.81) | +3.6 sigma | 1.07 | rising | EMA20(83.61) > EMA50(81.26) | 79.00 | — |
| 2026-06-16 | 94.50 | 96.25 | 92.56 | 93.23 | 3,926,816 | 1,285,603 | 3.05 | — | — | +12.4% vs SMA20(82.94) | +13.6% vs SMA50(82.10) | +2.5 sigma | 1.29 | rising | EMA20(84.53) > EMA50(81.73) | 74.60 | — |
| 2026-06-17 | 93.30 | 95.50 | 92.00 | 95.07 | 3,516,541 | 1,450,686 | 2.42 | — | — | +13.7% vs SMA20(83.64) | +15.3% vs SMA50(82.48) | +2.4 sigma | 1.47 | rising | EMA20(85.53) > EMA50(82.25) | 76.70 | — |
| 2026-06-18 | 95.00 | 96.49 | 94.50 | 94.72 | 2,306,933 | 1,561,650 | 1.48 | — | — | +12.2% vs SMA20(84.40) | +14.3% vs SMA50(82.87) | +1.9 sigma | 1.46 | falling | EMA20(86.41) > EMA50(82.74) | 75.40 | — |
| 2026-06-19 | 94.75 | 96.59 | 92.50 | 94.25 | 1,931,157 | 1,649,923 | 1.17 | — | — | +10.7% vs SMA20(85.15) | +13.2% vs SMA50(83.27) | +1.6 sigma | 1.34 | falling | EMA20(87.15) > EMA50(83.19) | 73.60 | — |
| 2026-06-22 | 95.25 | 95.90 | 93.50 | 93.95 | 1,128,191 | 1,704,481 | 0.66 | — | — | +9.4% vs SMA20(85.85) | +12.3% vs SMA50(83.64) | +1.4 sigma | 1.16 | falling | EMA20(87.80) > EMA50(83.62) | 72.40 | — |
| 2026-06-23 | 94.70 | 94.70 | 92.60 | 92.81 | 1,589,064 | 1,756,768 | 0.90 | — | — | +7.3% vs SMA20(86.51) | +10.7% vs SMA50(83.85) | +1.1 sigma | 0.8835 | falling | EMA20(88.28) > EMA50(83.98) | 67.80 | — |
| 2026-06-24 | 97.47 | 101.38 | 96.20 | 99.58 | 9,687,570 | 2,233,319 | 4.34 | — | — | +13.8% vs SMA20(87.48) | +18.4% vs SMA50(84.14) | +1.9 sigma | 1.08 | rising | EMA20(89.35) > EMA50(84.59) | 77.10 | — |
| 2026-06-25 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-26 | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-29 | 101.40 | 109.54 | 101.40 | 108.37 | 8,329,966 | 2,626,660 | 3.17 | — | — | +22.1% vs SMA20(88.75) | +28.0% vs SMA50(84.64) | +2.6 sigma | 1.67 | rising | EMA20(91.16) > EMA50(85.52) | 83.60 | — |
| 2026-06-30 | 109.36 | 110.50 | 107.13 | 107.54 | 2,492,615 | 2,737,486 | 0.91 | — | — | +19.5% vs SMA20(90.03) | +26.2% vs SMA50(85.21) | +2.1 sigma | 1.88 | rising | EMA20(92.72) > EMA50(86.38) | 81.30 | — |

### Volume & flow table (same dates as the core table above)

MFI(14) is volume-weighted RSI; OBV and A/D Line are both cumulative volume-direction
indicators (OBV uses simple close-to-close direction, A/D Line weights by where the close
sits within its own high-low range -- the two can diverge, which is itself informative,
see "Flow divergence" below); ATR(14) is Wilder-smoothed true range, in price units; VWAP
here is a **window-anchored approximation** (cumulative volume-weighted typical price
`(H+L+C)/3`, restarting at this window's own first day) since only daily OHLCV is
available -- **not** a real intraday VWAP; Tenkan-sen/Kijun-sen and the Ichimoku cloud use
standard periods (9/26/52, cloud displaced 26 periods forward) -- the cloud reading for the
last ~26 days of any window is provisional, since Senkou Span A/B for those days are drawn
from Tenkan/Kijun computed inside the window itself, the same caveat real charting
platforms show for an unclosed forward cloud.

| Date | MFI(14) | OBV | A/D Line | ATR(14) | VWAP (window-anchored) | Price vs VWAP | Tenkan-sen | Kijun-sen | Ichimoku cloud | Flow divergence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-18 | 45.10 | -766,461 | 1,388,151 | 3.17 | 79.83 | below | 82.25 | 82.40 | cloud not yet formed (insufficient history) | — |
| 2026-05-19 | 35.00 | -932,156 | 1,356,590 | 3.16 | 79.53 | below | 81.75 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-20 | 43.70 | -895,118 | 1,374,368 | 3.07 | 79.56 | above | 81.25 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-21 | 53.00 | -1,438,444 | 1,031,970 | 3.04 | 79.87 | below | 80.97 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-22 | 51.60 | -1,281,897 | 1,047,730 | 2.93 | 79.93 | above | 80.97 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-25 | 56.10 | -818,756 | 1,284,858 | 2.95 | 80.74 | above | 80.92 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-05-26 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-27 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-28 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-05-29 | 32.80 | -1,094,854 | 1,195,216 | 2.85 | 80.96 | above | 80.75 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-06-01 | 37.30 | -1,222,664 | 1,107,630 | 2.79 | 81.02 | above | 80.75 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-06-02 | 37.10 | -1,364,729 | 1,158,891 | 2.80 | 80.99 | below | 80.75 | 82.00 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-06-03 | 43.50 | -1,283,883 | 1,098,653 | 2.67 | 81.00 | above | 80.75 | 82.00 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-04 | 79.10 | 4,224,056 | -942,525 | 2.72 | 81.79 | below | 81.28 | 82.00 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down) |
| 2026-06-05 | 76.50 | 3,874,366 | -1,174,899 | 2.64 | 81.79 | below | 81.50 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-06-08 | 81.50 | 3,681,232 | -1,093,063 | 2.58 | 81.78 | below | 81.50 | 82.00 | cloud not yet formed (insufficient history) | A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up) |
| 2026-06-09 | 87.10 | 5,883,562 | -969,733 | 2.57 | 81.99 | above | 81.50 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-06-10 | 88.80 | 6,737,198 | -182,398 | 2.53 | 82.13 | above | 81.79 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-06-11 | 90.80 | 5,949,310 | -182,398 | 2.42 | 82.26 | above | 81.79 | 82.00 | cloud not yet formed (insufficient history) | — |
| 2026-06-12 | 92.20 | 8,042,131 | 1,195,288 | 2.53 | 82.88 | above | 83.50 | 83.00 | cloud not yet formed (insufficient history) | — |
| 2026-06-15 | 95.10 | 15,544,840 | 4,069,309 | 2.97 | 86.68 | above | 88.09 | 86.98 | cloud not yet formed (insufficient history) | — |
| 2026-06-16 | 95.90 | 11,618,024 | 1,568,492 | 3.02 | 87.81 | above | 88.24 | 87.12 | cloud not yet formed (insufficient history) | — |
| 2026-06-17 | 96.40 | 15,134,565 | 4,220,968 | 3.06 | 88.58 | above | 88.24 | 87.12 | cloud not yet formed (insufficient history) | — |
| 2026-06-18 | 97.50 | 12,827,632 | 2,424,111 | 2.98 | 89.07 | above | 88.36 | 87.25 | cloud not yet formed (insufficient history) | — |
| 2026-06-19 | 91.60 | 10,896,475 | 2,145,533 | 3.06 | 89.38 | above | 89.04 | 87.30 | cloud not yet formed (insufficient history) | — |
| 2026-06-22 | 92.20 | 9,768,284 | 1,440,414 | 3.01 | 89.55 | above | 89.55 | 87.30 | cloud not yet formed (insufficient history) | — |
| 2026-06-23 | 87.70 | 8,179,220 | 169,163 | 2.95 | 89.72 | above | 90.06 | 87.30 | cloud not yet formed (insufficient history) | — |
| 2026-06-24 | 89.50 | 17,866,790 | 3,124,059 | 3.35 | 91.70 | above | 92.70 | 89.69 | cloud not yet formed (insufficient history) | — |
| 2026-06-25 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-26 | — | — | — | — | — | — | — | — | — | No PSX trading data (weekday, no trade recorded / holiday) |
| 2026-06-29 | 92.20 | 26,196,756 | 9,059,415 | 3.82 | 93.97 | above | 100.27 | 93.77 | cloud not yet formed (insufficient history) | — |
| 2026-06-30 | 92.90 | 23,704,141 | 7,173,312 | 3.79 | 94.61 | above | 101.25 | 94.25 | cloud not yet formed (insufficient history) | — |

### What specifically fired, and on which day

Day offsets are relative to the user-given move-start date (2026-06-02 = Day 0).

Day -8 (2026-05-18): Volume 0.2x avg, no pattern, BB -1.8 sigma, MACD hist -0.5932 (falling), EMA20(81.63) > EMA50(79.39), MFI 45.1, price below VWAP, tested prior swing low at 78.30 (2026-04-13), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day -7 (2026-05-19): Volume 0.3x avg, no pattern, BB -1.7 sigma, MACD hist -0.6600 (falling), EMA20(81.40) > EMA50(79.38), MFI 35.0, price below VWAP, tested prior swing low at 78.30 (2026-04-13), held
Day -6 (2026-05-20): Volume 0.1x avg, Doji formed (body(0.13) <= 0.1*range(2.00) [body/range=0.06]), BB -1.1 sigma, MACD hist -0.6214 (rising), EMA20(81.27) > EMA50(79.41), MFI 43.7, price above VWAP, tested prior swing low at 78.30 (2026-04-13), held
Day -5 (2026-05-21): Volume 1.2x avg, no pattern, BB -1.3 sigma, MACD hist -0.6061 (rising), EMA20(81.10) > EMA50(79.41), MFI 53.0, price below VWAP, tested prior swing low at 79.01 (2026-04-24), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day -4 (2026-05-22): Volume 0.4x avg, no pattern, BB within bands, MACD hist -0.5160 (rising), EMA20(81.02) > EMA50(79.45), MFI 51.6, price above VWAP, tested prior swing low at 79.01 (2026-04-24), held
Day -3 (2026-05-25): Volume 1.0x avg, no pattern, BB within bands, MACD hist -0.2722 (rising), EMA20(81.20) > EMA50(79.58), MFI 56.1, price above VWAP, tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day -2 (2026-05-29): Volume 0.6x avg, no pattern, BB within bands, MACD hist -0.1663 (rising), EMA20(81.28) > EMA50(79.67), MFI 32.8, price above VWAP, tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day -1 (2026-06-01): Volume 0.3x avg, no pattern, BB within bands, MACD hist -0.1367 (rising), EMA20(81.28) > EMA50(79.74), MFI 37.3, price above VWAP, tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day 0 (2026-06-02): Volume 0.4x avg, Doji formed (body(0.24) <= 0.1*range(2.91) [body/range=0.08]), BB within bands, MACD hist -0.1339 (rising), EMA20(81.25) > EMA50(79.79), MFI 37.1, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing low at 79.01 (2026-04-24), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day +1 (2026-06-03): Volume 0.2x avg, Doji formed (body(0.04) <= 0.1*range(1.02) [body/range=0.04]), BB within bands, MACD hist -0.1246 (rising), EMA20(81.23) > EMA50(79.84), MFI 43.5, price above VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day +2 (2026-06-04): Volume 9.5x avg, no pattern, BB within bands, MACD hist -0.0733 (rising), EMA20(81.27) > EMA50(79.91), MFI 79.1, price below VWAP, A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down), tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.50 (2026-05-25), rejected at
Day +3 (2026-06-05): Volume 0.6x avg, no pattern, BB within bands, MACD hist -0.0492 (rising), EMA20(81.29) > EMA50(79.97), MFI 76.5, price below VWAP, tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day +4 (2026-06-08): Volume 0.4x avg, no pattern, BB within bands, MACD hist -0.0343 (rising), EMA20(81.31) > EMA50(80.03), MFI 81.5, price below VWAP, A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up), tested prior swing low at 80.01 (2026-04-30), held; tested prior swing high at 83.00 (2026-03-25), rejected at
Day +5 (2026-06-09): Volume 3.7x avg, no pattern, BB +1.2 sigma, MACD hist 0.0596 (rising), EMA20(81.46) > EMA50(80.14), MFI 87.1, price above VWAP, tested prior swing low at 80.23 (2026-06-08), held; tested prior swing high at 84.00 (2026-06-04), rejected at
Day +6 (2026-06-10): Volume 1.3x avg, no pattern, BB +2.4 sigma, MACD hist 0.2209 (rising), EMA20(81.74) > EMA50(80.31), MFI 88.8, price above VWAP, tested prior swing high at 85.00 (2026-04-27), rejected at
Day +7 (2026-06-11): Volume 1.2x avg, no pattern, BB +1.9 sigma, MACD hist 0.2776 (rising), EMA20(81.96) > EMA50(80.46), MFI 90.8, price above VWAP, tested prior swing high at 84.00 (2026-06-04), broke above
Day +8 (2026-06-12): Volume 2.8x avg, no pattern, BB +3.0 sigma, MACD hist 0.5071 (rising), EMA20(82.47) > EMA50(80.72), MFI 92.2, price above VWAP, tested prior swing high at 86.50 (2026-04-10), broke above
Day +9 (2026-06-15): Volume 6.7x avg, no pattern, BB +3.6 sigma, MACD hist 1.0742 (rising), EMA20(83.61) > EMA50(81.26), MFI 95.1, price above VWAP
Day +10 (2026-06-16): Volume 3.0x avg, no pattern, BB +2.5 sigma, MACD hist 1.2904 (rising), EMA20(84.53) > EMA50(81.73), MFI 95.9, price above VWAP
Day +11 (2026-06-17): Volume 2.4x avg, no pattern, BB +2.4 sigma, MACD hist 1.4664 (rising), EMA20(85.53) > EMA50(82.25), MFI 96.4, price above VWAP
Day +12 (2026-06-18): Volume 1.5x avg, no pattern, BB +1.9 sigma, MACD hist 1.4649 (falling), EMA20(86.41) > EMA50(82.74), MFI 97.5, price above VWAP
Day +13 (2026-06-19): Volume 1.2x avg, no pattern, BB +1.6 sigma, MACD hist 1.3411 (falling), EMA20(87.15) > EMA50(83.19), MFI 91.6, price above VWAP
Day +14 (2026-06-22): Volume 0.7x avg, no pattern, BB +1.4 sigma, MACD hist 1.1551 (falling), EMA20(87.80) > EMA50(83.62), MFI 92.2, price above VWAP
Day +15 (2026-06-23): Volume 0.9x avg, no pattern, BB +1.1 sigma, MACD hist 0.8835 (falling), EMA20(88.28) > EMA50(83.98), MFI 87.7, price above VWAP
Day +16 (2026-06-24): Volume 4.3x avg, no pattern, BB +1.9 sigma, MACD hist 1.0753 (rising), EMA20(89.35) > EMA50(84.59), MFI 89.5, price above VWAP
Day +17 (2026-06-29): Volume 3.2x avg, no pattern, BB +2.6 sigma, MACD hist 1.6740 (rising), EMA20(91.16) > EMA50(85.52), MFI 92.2, price above VWAP
Day +18 (2026-06-30): Volume 0.9x avg, no pattern, BB +2.1 sigma, MACD hist 1.8786 (rising), EMA20(92.72) > EMA50(86.38), MFI 92.9, price above VWAP

### Flow divergence check

4 day(s) with an OBV/A-D Line divergence-from-price flag:
  - 2026-06-02: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
  - 2026-06-03: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-04: A/D Line diverges from price (price up, A/D down); OBV and A/D Line disagree with each other (OBV up, A/D down)
  - 2026-06-08: A/D Line diverges from price (price down, A/D up); OBV and A/D Line disagree with each other (OBV down, A/D up)
---

## STOCK 12 — BNL — TICKER/PRICE MISMATCH, NOT A FORENSIC SECTION

**This section is a data-quality disclosure, not a pre-move forensic narrative, per the explicit
instruction to report any mismatch rather than silently proceed.**

The user's reference for BNL was **2.10 on 2025-05-09 -> 17.10 on 2025-09-17** (a >700% move
flagged in advance as needing a price-cliff/corporate-action check, the same way FNEL's real
2026-02-02 bonus-share adjustment was caught).

The real, fetched PSX data for ticker `BNL` over an extended window (2025-02-09 to 2025-09-17,
149 trading days) shows:

- **2025-05-09 close: 23.20** (not 2.10 -- off by roughly 11x)
- **2025-09-17 close: 160.09** (not 17.10 -- off by roughly 9.4x)
- The full 149-bar series is **smooth and continuous** -- `detect_price_cliffs()` (the same
  function that correctly found FNEL's real 2026-02-02 bonus-share cliff) found **zero**
  qualifying discontinuities anywhere in this window. There is no single-day price cliff that
  would reconcile the ~10x gap between the user's reference numbers and the real fetched prices.
- The real move IS large and real -- close 13.99 on 2025-02-10 to close 160.09 on 2025-09-17, a
  genuine +1044% run over the period -- just not at the price levels the user cited.

**What this means:** unlike FNEL (where a real, dated corporate action fully explained an
apparent price-scale mismatch, confirmed by the post-adjustment prices matching the user's
reference exactly), BNL's real PSX price history does not match the user-given reference prices
at either endpoint, by a consistent ~10x factor, with no dated event to explain it. Plausible
explanations that this study cannot resolve without further input: the reference prices may be
quoting a different par-value/share class, a different exchange, an already-split-adjusted
series from another source, or `BNL` on `dps.psx.com.pk` may not be the intended scrip at all
(a similarly-named ticker issue, exactly as the user's own instructions warned against for
THCCL/FNEL in the prior round -- worth the same scrutiny here).

**No day-by-day forensic table, "what fired" narrative, or chart-structure summary is produced
for BNL in this round.** Producing one would imply this data represents the move the user asked
about, which it does not, at least not without further confirmation of the reference prices'
source/scale or of `BNL`'s exact intended identity. The real fetched OHLC (2025-02-09 to
2025-09-17) is nonetheless saved in `analysis/premove_data_raw.json` and its indicators in
`analysis/premove_analysis.json` under the `BNL` key, available once/if the mismatch is resolved.
---

## Cross-stock first-occurrence comparison (all 12 stocks)

For all twelve stocks currently in the dataset, the day (relative to each stock's own move-start
date, Day 0) each of the following first appears in its report window. **BNL is included in this
table only because it produces real numbers from real (if reference-mismatched) PSX data for the
fetched `BNL` ticker -- its row(s) should be read with the identity caveat above in mind, not as
confirmation of the user's originally-described move.**

| Signal | AICL | SHFA | THCCL | FNEL | MDTL | FPJM | BNL | DSIL | SYM | PREMA | JSBL | ILP |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| First volume >2x avg | Day -11 (2026-07-08) | Day -8 (2026-06-02) | Day +5 (2026-07-07) | Day +2 (2026-04-08) | Day +1 (2026-07-24) | Day +2 (2026-08-18) | Day -13 (2025-04-21) | Day -10 (2026-07-17) | Day -10 (2026-04-16) | Day +7 (2026-04-08) | Day -9 (2026-05-06) | Day +2 (2026-06-04) |
| First candlestick pattern | Day -9 (2026-07-10) | Day -4 (2026-06-08) | Day +3 (2026-07-03) | Day 0 (2026-04-06) | Day -6 (2026-07-15) | Day -7 (2026-08-04) | Day -10 (2025-04-24) | Day -6 (2026-07-23) | Day -11 (2026-04-15) | Day -6 (2026-03-18) | Day +4 (2026-05-25) | Day -6 (2026-05-20) |
| First BB oversold (<=-1.5 sigma) | Day -7 (2026-07-14) | Day -7 (2026-06-03) | not observed in window | not observed in window | Day -7 (2026-07-14) | not observed in window | not observed in window | not observed in window | Day +1 (2026-05-04) | Day 0 (2026-03-30) | Day -9 (2026-05-06) | Day -8 (2026-05-18) |
| First MACD hist sign change (neg->pos) | Day +3 (2026-07-28) | Day 0 (2026-06-12) | Day +5 (2026-07-07) | not observed in window | Day +1 (2026-07-24) | Day +3 (2026-08-19) | Day +6 (2025-05-19) | Day -10 (2026-07-17) | Day +8 (2026-05-13) | not observed in window | Day +5 (2026-05-29) | Day +5 (2026-06-09) |
| First EMA20/50 golden cross | Day +2 (2026-07-27) | Day +1 (2026-06-15) | not observed in window | Day +13 (2026-04-23) | not observed in window | not observed in window | not observed in window | Day -5 (2026-07-24) | Day +37 (2026-06-30) | Day +19 (2026-04-24) | not observed in window | not observed in window |
| Breakout day (vol>=2.5x + up day) | Day +3 (2026-07-28) | Day +3 (2026-06-17) | Day +5 (2026-07-07) | Day +2 (2026-04-08) | Day +1 (2026-07-24) | Day +2 (2026-08-18) | Day -13 (2025-04-21) | Day +1 (2026-08-03) | Day -3 (2026-04-27) | Day +11 (2026-04-14) | Day +5 (2026-05-29) | Day +2 (2026-06-04) |

**Reading this table:** across the now-11 reliably-identified stocks (excluding BNL), the breakout
day continues to cluster in a fairly narrow band relative to each stock's own move-start date, but
the spread widened noticeably with this round's additions -- SYM's breakout_day computation (day -3)
actually precedes its own move-start reference, and DSIL's/JSBL's/PREMA's earliest signals (first
volume spike, first MACD flip) also land well before their move-start dates, sometimes 6-10 days
early. This is a genuinely more mixed picture than the tight day+2-to+5 cluster the first four
stocks showed -- at n=11, "first elevated volume" and "breakout day" are clearly NOT a single
universal lag from a stock's own reference move-start; the relationship between a user-cited
reference date and this study's own mechanically-detected signal days varies stock to stock,
and should be read per-stock, not assumed to generalize.
---

## Reproducibility

- Raw fetched data: three batched GitHub Actions runs this round (log-line truncation on the
  combined 12-symbol payload forced the split) --
  [33762455347](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33762455347)
  (AICL,SHFA,THCCL,FNEL,MDTL,FPJM),
  [33762462806](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33762462806)
  (DSIL,SYM,PREMA,JSBL,ILP), and
  [33762471001](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33762471001)
  (BNL alone, given its wide window) -- all triggered from `analysis/fetch_premove_data.py`,
  merged and saved as `analysis/premove_data_raw.json`.
- Indicator computation (including the new MFI/OBV/A-D-Line/ATR/VWAP/Ichimoku layer), pattern
  scan, general price-cliff detection/trim, and first-occurrence tracking:
  `analysis/analyze_premove.py` (unit-tested against synthetic OHLC before running on real data,
  including a dedicated test that an upward volume spike is never flagged as a price cliff), reads
  `premove_data_raw.json` and writes `analysis/premove_analysis.json`.
- Markdown table / "what fired" narrative / flow-divergence / cross-stock table generation:
  `analysis/gen_report_v2.py`, assembled into this file by `analysis/build_full_report.py` --
  every number in the tables above is generated programmatically from `premove_analysis.json`,
  never hand-typed. Verified the full fetch -> analyze -> render pipeline reproduces
  byte-identical `premove_analysis.json` output on re-run (diff on sorted `json.dumps()` output).
- To add a 13th+ entry to this dataset: add an entry to `TARGETS` in `fetch_premove_data.py` and a
  `MOVE_START` entry in `analyze_premove.py`, re-run the `Pre-move study data fetch (manual,
  one-off)` GitHub Actions workflow (use the `symbols` input to batch large additions), save its
  JSON output over `premove_data_raw.json` (merging with existing symbols if fetched in batches),
  then re-run `analyze_premove.py` and `build_full_report.py`.
