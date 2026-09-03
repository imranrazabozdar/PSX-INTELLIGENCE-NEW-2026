# Fingerprint Out-of-Sample Scan Results

**Prepared:** 2026-09-03. Tests two specific, pre-specified pre-move fingerprints —
extracted from SHFA's and FNEL's sections of `analysis/AICL_SHFA_premove_study.md` —
against the full PSX universe cached in Turso's `daily_ohlc` table, independently of
each other. This is a genuine out-of-sample test: **no threshold in either fingerprint's
definition was adjusted after seeing these results.** Where a result is unfavorable
("neither beats baseline"), it is reported as such.

**Universe:** 213 symbols with >= 120 trading
days of history in `daily_ohlc` (this is the real number of PSX symbols this project's
own cached data has enough history for — not forced to any target count). SHFA's and
FNEL's own documented pre-move report windows are excluded from matching (the source
cases, not out-of-sample evidence).

**Baseline comparison, two figures:**
- **Cited baseline** (this project's previously-established figure, `backend/indicator_backtest_summary.csv`): **44.55%** win rate for any random eligible bar's 10-trading-day-forward return.
- **Freshly-computed baseline**, same methodology, computed from this scan's own universe/timeframe run: **47.81%** (n=202,569 eligible bars, 96,851 positive). The two figures differ — likely reflecting a different/updated `daily_ohlc` snapshot than whenever `indicator_backtest_summary.csv` was last generated — so both are reported and compared against, rather than picking one.

---

## Fingerprint 1 — "SHFA-style MFI-deep-oversold base"

**Definition:** MFI(14) <= 25 on >= 2 days within a 10-trading-day window, RSI(14) >= 40
on those same days, ATR(14) below its own trailing 90-day median, price not already
down more than 10% over the preceding 20 trading days.

**Total matches: 911** (no duplication issue — each match is a distinct
(symbol, trigger date) pair).

### Forward-return distribution

| Horizon | n | Mean | Median | Win rate | 95% CI (10d only) |
|---|---|---|---|---|---|
| +5d  | 905 | +0.49% | +0.00% | 47.6% | — |
| +10d | 897 | +0.93% | -0.38% | 46.4% | [43.1%, 49.6%] |
| +20d | 891 | +1.19% | -0.45% | 45.9% | — |

Breakout (vol>=2.5x avg + up day) within 15 trading days after the match:
**59.4%** of matches.

### Baseline comparison (10-day win rate)

Fingerprint 1's 10-day win rate (46.4%, 95% CI [43.1%, 49.6%], n=897) is
**statistically indistinguishable from the cited 44.55% baseline (95% CI includes it); statistically indistinguishable from the freshly-computed 47.81% baseline**.

**Plain reading:** at n=911, this is a large enough sample for the win-rate estimate to
be meaningful, and the honest result is that Fingerprint 1 does **not** beat baseline —
its 10-day win rate sits at or slightly below both baseline figures, well within
statistical noise. The mean return (+0.93%) is pulled positive by a right-skewed tail
of large winners (see Top 15 below, several 30-100%+ moves), while the median
(-0.38%) is essentially flat-to-negative — i.e. the "typical" outcome after this
fingerprint fires is close to a coin flip with a fat right tail, not a reliable edge.

### Top 15 matches by |10-day forward return|

| Ticker | Trigger date | Trigger values | +5d | +10d | +20d | Breakout w/in 15d |
|---|---|---|---|---|---|---|
| DAAG | 2024-04-29 | MFI=24.8, RSI=48.1, ATR=0.929 (90d median 0.999), price_chg_20d_pre=-6.1% | +43.5% | +106.1% | +272.8% | yes |
| ALAC | 2025-05-15 | MFI=6.5, RSI=44.5, ATR=0.459 (90d median 0.462), price_chg_20d_pre=-9.2% | +4.5% | +79.9% | +38.0% | yes |
| CFL | 2023-10-17 | MFI=8.9, RSI=54.5, ATR=4.064 (90d median 4.237), price_chg_20d_pre=-6.4% | +23.6% | +55.6% | +5.4% | no |
| ARCTM | 2025-05-07 | MFI=21.7, RSI=47.2, ATR=0.889 (90d median 1.280), price_chg_20d_pre=-3.9% | +24.5% | +52.8% | +106.8% | yes |
| WASL | 2023-07-13 | MFI=18.9, RSI=47.2, ATR=0.102 (90d median 0.142), price_chg_20d_pre=-9.3% | +3.9% | +52.8% | +33.9% | yes |
| DWSM | 2022-09-29 | MFI=12.2, RSI=45.7, ATR=0.156 (90d median 0.226), price_chg_20d_pre=-2.8% | +1.9% | +42.6% | +10.0% | yes |
| BPL | 2024-03-12 | MFI=15.3, RSI=41.9, ATR=0.773 (90d median 0.789), price_chg_20d_pre=-2.1% | +32.1% | +41.1% | +84.6% | yes |
| ALNRS | 2022-06-28 | MFI=14.0, RSI=43.2, ATR=3.767 (90d median 3.817), price_chg_20d_pre=-5.7% | +26.0% | +41.1% | +1.5% | yes |
| AATM | 2025-05-22 | MFI=16.6, RSI=42.8, ATR=3.829 (90d median 5.019), price_chg_20d_pre=-9.7% | +8.5% | +41.0% | +79.8% | yes |
| WASL | 2022-03-11 | MFI=8.9, RSI=50.9, ATR=0.147 (90d median 0.152), price_chg_20d_pre=-9.4% | -2.2% | +38.6% | +10.9% | yes |
| BFMOD | 2022-12-29 | MFI=8.8, RSI=42.9, ATR=0.499 (90d median 0.522), price_chg_20d_pre=-9.8% | -1.4% | +35.1% | +35.1% | no |
| AGSML | 2024-04-17 | MFI=12.3, RSI=41.5, ATR=0.210 (90d median 0.406), price_chg_20d_pre=-8.1% | +5.5% | +34.3% | +23.5% | yes |
| CEPB | 2023-11-01 | MFI=20.9, RSI=46.1, ATR=0.839 (90d median 0.990), price_chg_20d_pre=+0.4% | +21.0% | +33.5% | +35.0% | yes |
| BILF | 2025-04-09 | MFI=24.2, RSI=69.0, ATR=1.109 (90d median 1.189), price_chg_20d_pre=+6.7% | +0.4% | +29.6% | +18.6% | yes |
| ARCTM | 2023-05-02 | MFI=22.7, RSI=44.7, ATR=0.553 (90d median 0.881), price_chg_20d_pre=-1.4% | +9.4% | +29.3% | +11.7% | yes |

---

## Fingerprint 2 — "FNEL-style OBV/MFI quiet build after a breakout"

**Definition:** OBV rising over a 3-5 trading day span by more than 1.5x the stock's
own 20-day average daily volume, price flat/up less than 5% over that span, MFI(14)
rising from below 50 to above 70 over that span, occurring after an already-completed
volume-confirmed breakout (vol>=2.5x 20-day avg + up day), searched within a
60-trading-day lookahead from the breakout.

**Duplication note:** the raw scan produced 2762 match records, but 1821 of
these are the SAME underlying (symbol, trigger date) event re-detected relative to
multiple nearby prior breakout days (a stock with several breakout days close together
can have the same later quiet-build window "found" once per nearby breakout). This is a
real property of the fingerprint's definition (a quiet build genuinely can follow more
than one recent breakout), but counting each re-detection as independent evidence would
overstate the sample size. **All statistics below use the DEDUPED set — 941 unique
(symbol, trigger date) pairs, keeping one record per pair** — with the raw, undeduped
total (2762 records) reported alongside for transparency. This is a data-presentation
correction, not a change to the fingerprint's defining thresholds.

**Total matches: 941** (deduped) / 2762 (raw, all records the scan produced).

### Forward-return distribution (deduped)

| Horizon | n | Mean | Median | Win rate | 95% CI (10d only) |
|---|---|---|---|---|---|
| +5d  | 938 | +0.01% | -0.66% | 42.5% | — |
| +10d | 936 | +0.72% | -0.73% | 45.8% | [42.7%, 49.0%] |
| +20d | 916 | +1.94% | -0.22% | 48.6% | — |

For comparison, the RAW (undeduped) 10-day win rate is 44.9%
(95% CI [43.0%, 46.8%], n=2749) — materially the same conclusion as the deduped figure.

Breakout (vol>=2.5x avg + up day) within 15 trading days after the match:
**59.9%** of matches (deduped).

### Baseline comparison (10-day win rate, deduped)

Fingerprint 2's 10-day win rate (45.8%, 95% CI [42.7%, 49.0%], n=936) is
**statistically indistinguishable from the cited 44.55% baseline (95% CI includes it); statistically indistinguishable from the freshly-computed 47.81% baseline**.

**Plain reading:** at n=941 (deduped), also a large enough sample to trust the estimate.
Fingerprint 2 does **not** beat baseline either — if anything its win rate sits slightly
below the freshly-computed baseline. As with Fingerprint 1, the mean return is pulled
positive by a right-skewed tail (several 30-59% winners), while the median is negative
— the typical outcome is a small loss, occasionally offset by a large winner.

### Top 15 matches by |10-day forward return| (deduped)

| Ticker | Trigger date | Trigger values | +5d | +10d | +20d | Breakout w/in 15d |
|---|---|---|---|---|---|---|
| AMBL | 2026-01-27 | OBV_delta/vol20davg=3.59x, MFI 47.2->72.0, price_chg_over_span=+3.6%, prior_breakout=2025-12-23 | +61.1% | +59.0% | +78.2% | yes |
| BCL | 2024-11-20 | OBV_delta/vol20davg=7.33x, MFI 37.9->70.4, price_chg_over_span=+3.4%, prior_breakout=2024-08-28 | +2.9% | +57.3% | +34.1% | yes |
| THCCL | 2024-09-13 | OBV_delta/vol20davg=3.05x, MFI 28.7->71.5, price_chg_over_span=+3.5%, prior_breakout=2024-07-15 | +17.4% | +54.4% | +74.2% | yes |
| BILF | 2025-04-15 | OBV_delta/vol20davg=19.37x, MFI 24.2->88.1, price_chg_over_span=+1.7%, prior_breakout=2025-02-13 | +21.2% | +51.2% | -4.3% | yes |
| ZAL | 2025-06-30 | OBV_delta/vol20davg=11.28x, MFI 24.3->76.6, price_chg_over_span=+4.1%, prior_breakout=2025-04-21 | +34.2% | +50.5% | +53.6% | yes |
| CSAP | 2024-02-16 | OBV_delta/vol20davg=58.06x, MFI 37.2->88.4, price_chg_over_span=+2.0%, prior_breakout=2024-01-11 | +8.3% | +49.2% | +72.9% | yes |
| BOK | 2025-08-13 | OBV_delta/vol20davg=8.18x, MFI 49.5->86.3, price_chg_over_span=-0.9%, prior_breakout=2025-06-23 | -1.1% | +44.2% | +44.0% | yes |
| EMCO | 2025-04-04 | OBV_delta/vol20davg=2.93x, MFI 27.1->81.8, price_chg_over_span=+3.5%, prior_breakout=2024-12-05 | +25.1% | +41.1% | +35.6% | yes |
| CLOV | 2026-01-12 | OBV_delta/vol20davg=14.49x, MFI 46.4->81.4, price_chg_over_span=+4.7%, prior_breakout=2025-11-24 | +5.1% | +37.3% | +79.0% | yes |
| ESBL | 2025-11-26 | OBV_delta/vol20davg=5.94x, MFI 40.1->76.3, price_chg_over_span=+3.7%, prior_breakout=2025-09-22 | +29.0% | +37.2% | +19.8% | yes |
| AHL | 2024-10-18 | OBV_delta/vol20davg=5.14x, MFI 48.0->72.0, price_chg_over_span=+3.7%, prior_breakout=2024-08-09 | +35.0% | -37.0% | -22.6% | yes |
| ALTN | 2023-08-16 | OBV_delta/vol20davg=46.96x, MFI 40.7->77.0, price_chg_over_span=+4.9%, prior_breakout=2023-07-03 | -32.7% | -36.7% | -33.4% | no |
| LOTCHEM | 2022-04-13 | OBV_delta/vol20davg=4.50x, MFI 36.4->79.3, price_chg_over_span=+2.1%, prior_breakout=2022-03-10 | +20.1% | +35.7% | +63.5% | yes |
| BWHL | 2024-10-14 | OBV_delta/vol20davg=51.48x, MFI 42.3->80.1, price_chg_over_span=+2.1%, prior_breakout=2024-07-30 | +27.5% | +33.8% | +31.2% | yes |
| ASTM | 2025-01-01 | OBV_delta/vol20davg=10.71x, MFI 22.2->81.0, price_chg_over_span=-1.6%, prior_breakout=2024-10-01 | +21.4% | +31.6% | +36.3% | yes |

---

## Overall conclusion

Neither fingerprint beats this project's established PSX baseline win rate at the
10-day horizon, at sample sizes (n=911 and n=941 respectively) large enough to trust
the estimate rather than dismiss it as too-few-matches noise. Both fingerprints' 95%
confidence intervals for the 10-day win rate include or sit very close to both baseline
figures (cited 44.55% and freshly-computed 47.81%). This means: **the specific
technical signatures pulled from SHFA's and FNEL's pre-move windows do not generalize
into a standalone predictive edge across the wider PSX universe** — they described what
happened in those two cases, but were not, on this evidence, a repeatable "tell." This
does not mean SHFA's and FNEL's moves were unexplained or random in isolation — only
that the specific MFI/RSI/ATR and OBV/MFI signatures extracted from them, applied
mechanically and independently of everything else in this study (candlestick patterns,
support/resistance, chart structure, Ichimoku, the announcement findings that did exist
for SHFA), are not shown by this scan to carry a reliable edge on their own.

The right-skewed mean-vs-median gap in both fingerprints (positive mean, flat/negative
median) is itself informative: a small number of large winners are propping up the
average return while the "typical" outcome is closer to flat-to-negative. Anyone using
either fingerprint as a standalone signal should expect a roughly coin-flip-or-worse hit
rate with occasional large winners and occasional large losses (see the worst outcomes
inside `analysis/fingerprint_matches.json` — down to -37% at 10 days for Fingerprint 2
and -26% for Fingerprint 1), not a dependable edge.

## Reproducibility

- Scan script: `backend/run_fingerprint_scan.py`, reusing `analysis/analyze_premove.py`'s
  `analyze()` directly for all indicator computation (MFI, RSI, ATR, OBV, vol_ratio) —
  nothing reimplemented. Unit-tested against synthetic row data (including negative
  controls) before running on real data.
- Runs in GitHub Actions (`.github/workflows/fingerprint_scan.yml`, `workflow_dispatch`,
  Turso secrets) since this session's sandbox cannot reach Turso directly and the repo's
  local `psx_v2.db` is a stub without the real `daily_ohlc` universe. Final run:
  [33778401391](https://github.com/imranrazabozdar/PSX-INTELLIGENCE-NEW-2026/actions/runs/33778401391).
- Full raw match list (every match, every field, both fingerprints, undeduped) saved to
  `analysis/fingerprint_matches.json`. This report's tables and statistics are derived
  from that file (Fingerprint 2's headline numbers use the deduped subset documented
  above; the file itself contains both the raw and deduped lists).
