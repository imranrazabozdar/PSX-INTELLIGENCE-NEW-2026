# Liquidity-Stratified Re-Test — Top-8 Indicators + 9 New Fingerprints

**Run date (UTC):** 2026-09-03T17:29:44.095376+00:00
**Holdout window:** 2025-09-03 to 2026-09-03 (mechanical, execution-date-derived, identical to the prior sweep)

## Liquidity tiers

Trailing 20-day average traded value = avg(volume) x avg(close) over each ticker's own last 20 available bars, computed once per ticker. Universe: 225 tickers with >=20 bars (of 229 total tickers loaded).

- **Tier A (least liquid third):** 75 tickers, traded value <= 2,769,537
- **Tier B (middle third):** 75 tickers, traded value in (2,769,537, 37,432,939]
- **Tier C (most liquid third):** 75 tickers, traded value > 37,432,939

## Task 1 — Top 8 indicators x 3 liquidity tiers

Method identical to analysis/phase1_all26_sweep.py: upper barrier = entry close + 2.0xATR(14); lower barrier = entry close - 1.5xATR(14); vertical barrier = 15 trading days; same-day double-touch resolves to the lower barrier; n>=150 required or INCONCLUSIVE; PASS only if Wilson 95% CI lower bound on +1-class precision > 50.0%.

| Indicator | Tier | n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |
|---|---|---|---|---|---|---|---|---|
| BB_OVERBOUGHT | A | 375 | 160 | 165 | 50 | 42.67% | [37.76%, 47.72%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| BB_OVERBOUGHT | B | 483 | 217 | 224 | 42 | 44.93% | [40.55%, 49.39%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| BB_OVERBOUGHT | C | 573 | 291 | 230 | 52 | 50.79% | [46.70%, 54.86%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| BB_SQUEEZE_BREAK | A | 888 | 286 | 340 | 262 | 32.21% | [29.22%, 35.35%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| BB_SQUEEZE_BREAK | B | 1121 | 474 | 394 | 253 | 42.28% | [39.42%, 45.20%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| BB_SQUEEZE_BREAK | C | 1119 | 546 | 390 | 183 | 48.79% | [45.87%, 51.72%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_OVERBOUGHT | A | 309 | 128 | 130 | 51 | 41.42% | [36.07%, 46.99%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_OVERBOUGHT | B | 442 | 168 | 224 | 50 | 38.01% | [33.61%, 42.62%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_OVERBOUGHT | C | 535 | 246 | 252 | 37 | 45.98% | [41.80%, 50.22%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| MOM_CROSS_POS | A | 765 | 264 | 304 | 197 | 34.51% | [31.23%, 37.95%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| MOM_CROSS_POS | B | 821 | 317 | 296 | 208 | 38.61% | [35.34%, 41.99%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| MOM_CROSS_POS | C | 765 | 361 | 256 | 148 | 47.19% | [43.67%, 50.73%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| VOLUME_SPIKE | A | 1981 | 723 | 809 | 449 | 36.50% | [34.40%, 38.64%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| VOLUME_SPIKE | B | 2270 | 843 | 1046 | 381 | 37.14% | [35.17%, 39.14%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| VOLUME_SPIKE | C | 2224 | 948 | 1023 | 253 | 42.63% | [40.59%, 44.69%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| CMF_POS | A | 450 | 166 | 181 | 103 | 36.89% | [32.56%, 41.44%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| CMF_POS | B | 498 | 176 | 216 | 106 | 35.34% | [31.27%, 39.64%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| CMF_POS | C | 602 | 261 | 249 | 92 | 43.36% | [39.45%, 47.34%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_HEALTHY | A | 920 | 287 | 381 | 252 | 31.20% | [28.29%, 34.26%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_HEALTHY | B | 964 | 349 | 366 | 249 | 36.20% | [33.23%, 39.29%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_HEALTHY | C | 969 | 424 | 357 | 188 | 43.76% | [40.66%, 46.90%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| OBV_DIVERGE_BULL | A | 2728 | 859 | 1075 | 794 | 31.49% | [29.77%, 33.26%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| OBV_DIVERGE_BULL | B | 3726 | 1201 | 1488 | 1037 | 32.23% | [30.75%, 33.75%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| OBV_DIVERGE_BULL | C | 3615 | 1551 | 1348 | 716 | 42.90% | [41.30%, 44.52%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |

## Task 2 — 9 new fingerprints x 3 liquidity tiers

Each fingerprint's exact trigger definition (derived from that stock's own documented pre-move numbers in analysis/AICL_SHFA_premove_study.md, reused as the scan template from backend/run_fingerprint_scan.py's SHFA/FNEL approach):

- **FP_AICL** (source: AICL): BB sigma <= -2.0 at bar t0 (sigma = (close-bb_mid)/bb_std, bollinger period=20,mult=2); within the next 5 bars, a bar k where volume_ratio(20d) >= 5.0 AND MFI(14) crosses above 70 (mfi[k]>=70, mfi[k-1]<70). Trigger date = k. Derived from AICL's documented Day-1 BB -2.4 sigma / Day+3 volume 8.7x / MFI 38.4->78.9 sequence.
- **FP_THCCL** (source: THCCL): At bar t0, MFI(14) <= 55 AND max(MFI over the prior 9 bars, inclusive of t0) >= 80 (a cool-off from an overbought MFI reading); within the next 5 bars, a bar k where volume_ratio(20d) >= 3.0 AND BB sigma >= 1.5. Trigger date = k. Derived from THCCL's documented MFI drift from the 80s down to 51.1 on Day 0, followed by the Day+5 volume 3.8x / BB +3.1 sigma breakout.
- **FP_MDTL** (source: MDTL): BB sigma <= -1.5 at bar t0; within the next 3 bars, a bar k where volume_ratio(20d) >= 5.0 AND MFI(14) crosses above 75 (mfi[k]>=75, mfi[k-1]<75). Trigger date = k. Derived from MDTL's documented Day-7 BB -2.3 sigma followed by the Day+1 same-bar 6.5x volume / MFI 82.3 breakout.
- **FP_FPJM** (source: FPJM): MFI(14) stays within [25,35] for 5 consecutive prior bars (t0-5..t0-1); at t0 itself, volume_ratio(20d) >= 2.5 AND BB sigma crosses up through 1.0 (sigma[t0]>=1.0, sigma[t0-1]<1.0). Trigger date = t0. Derived from FPJM's documented multi-week base with MFI in the low-mid 30s, then the Day+2 2.76x-volume breakout day that doubled as the BB-band expansion.
- **FP_DSIL** (source: DSIL): Within any 10-bar window [t0..t0+9], at least 3 of these 4 conditions each fire on some bar in the window: volume_ratio(20d) >= 2.0; MACD histogram crosses positive; EMA20 crosses above EMA50 (golden cross); close > open (bullish bar). Then, within the following 10 bars after the window, a bar k where volume_ratio(20d) >= 4.0. Trigger date = k. Derived from DSIL's documented cluster of early signals (>2x volume day, MACD sign flip, Piercing Line, golden cross, all pre-dating the reference move) followed by the real 4.35x-volume breakout day.
- **FP_SYM** (source: SYM): A bar t0 where volume_ratio(20d) >= 6.0; within the next 10 bars, the bar L with the lowest close in that window (a local low); within the 10 bars after L, a bar k where the MACD histogram crosses positive. Trigger date = k. Derived from SYM's documented pre-dip volume spike (6.43x) followed by the dip low and the later (day +8) MACD sign flip into bullish territory.
- **FP_PREMA** (source: PREMA): BB sigma <= -2.0 at bar t0; within the next 20 bars, a bar V where volume_ratio(20d) >= 3.0; within the same 20-bar window, at or after V, a bar k where EMA20 crosses above EMA50 (golden cross). Trigger date = k. Derived from PREMA's documented BB -2.2 sigma on the reference date, the 3.24x-volume breakout roughly 3 weeks later, and the golden cross near the window's end.
- **FP_JSBL** (source: JSBL): MFI(14) crosses below 10 at bar t0 (mfi[t0]<10, mfi[t0-1]>=10); within the next 10 bars, a bar k where volume_ratio(20d) >= 2.5 AND the MACD histogram crosses positive on the same bar. Trigger date = k. Derived from JSBL's documented extreme MFI readings (3.2-4.5) around the reference date and the later 2.6x-volume breakout with a MACD sign flip.
- **FP_ILP** (source: ILP): BB sigma <= -1.5 at bar t0; within the next 3 bars, a bar V where volume_ratio(20d) >= 8.0; within the 20 bars after V, a bar k where RSI(14) crosses above 75 (rsi[k]>=75, rsi[k-1]<75). Trigger date = k. Derived from ILP's documented BB -1.8 sigma base, the 9.5x single-day volume spike, and the later RSI climb into the high 70s/low 80s.

n>=20 required per cell or reported as "TOO FEW MATCHES"; each stock's own documented report window is excluded when scanning that stock itself. Same Wilson 95% CI / >50.0% lower-bound PASS rule.

| Fingerprint | Source stock | Tier | n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| FP_AICL | AICL | A | 21 | 7 | 13 | 1 | 33.33% | [17.19%, 54.63%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_AICL | AICL | B | 12 | 5 | 5 | 2 | — | — | TOO FEW MATCHES (n=12, floor=20) |
| FP_AICL | AICL | C | 4 | 1 | 2 | 1 | — | — | TOO FEW MATCHES (n=4, floor=20) |
| FP_THCCL | THCCL | A | 56 | 28 | 19 | 9 | 50.00% | [37.33%, 62.67%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_THCCL | THCCL | B | 37 | 17 | 19 | 1 | 45.95% | [31.04%, 61.62%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_THCCL | THCCL | C | 15 | 8 | 7 | 0 | — | — | TOO FEW MATCHES (n=15, floor=20) |
| FP_MDTL | MDTL | A | 25 | 7 | 13 | 5 | 28.00% | [14.28%, 47.58%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_MDTL | MDTL | B | 19 | 9 | 5 | 5 | — | — | TOO FEW MATCHES (n=19, floor=20) |
| FP_MDTL | MDTL | C | 6 | 5 | 1 | 0 | — | — | TOO FEW MATCHES (n=6, floor=20) |
| FP_FPJM | FPJM | A | 1 | 0 | 1 | 0 | — | — | TOO FEW MATCHES (n=1, floor=20) |
| FP_FPJM | FPJM | B | 2 | 1 | 1 | 0 | — | — | TOO FEW MATCHES (n=2, floor=20) |
| FP_FPJM | FPJM | C | 2 | 0 | 2 | 0 | — | — | TOO FEW MATCHES (n=2, floor=20) |
| FP_DSIL | DSIL | A | 692 | 251 | 314 | 127 | 36.27% | [32.77%, 39.92%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_DSIL | DSIL | B | 634 | 217 | 316 | 101 | 34.23% | [30.64%, 38.01%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_DSIL | DSIL | C | 393 | 177 | 169 | 47 | 45.04% | [40.19%, 49.98%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_SYM | SYM | A | 102 | 28 | 37 | 37 | 27.45% | [19.73%, 36.81%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_SYM | SYM | B | 85 | 26 | 35 | 24 | 30.59% | [21.81%, 41.05%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_SYM | SYM | C | 39 | 17 | 14 | 8 | 43.59% | [29.30%, 59.02%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_PREMA | PREMA | A | 27 | 10 | 13 | 4 | 37.04% | [21.53%, 55.77%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_PREMA | PREMA | B | 30 | 10 | 12 | 8 | 33.33% | [19.23%, 51.22%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_PREMA | PREMA | C | 21 | 5 | 13 | 3 | 23.81% | [10.63%, 45.09%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| FP_JSBL | JSBL | A | 14 | 4 | 7 | 3 | — | — | TOO FEW MATCHES (n=14, floor=20) |
| FP_JSBL | JSBL | B | 5 | 2 | 2 | 1 | — | — | TOO FEW MATCHES (n=5, floor=20) |
| FP_JSBL | JSBL | C | 0 | 0 | 0 | 0 | — | — | TOO FEW MATCHES (n=0, floor=20) |
| FP_ILP | ILP | A | 3 | 0 | 3 | 0 | — | — | TOO FEW MATCHES (n=3, floor=20) |
| FP_ILP | ILP | B | 5 | 4 | 1 | 0 | — | — | TOO FEW MATCHES (n=5, floor=20) |
| FP_ILP | ILP | C | 1 | 1 | 0 | 0 | — | — | TOO FEW MATCHES (n=1, floor=20) |

## Summary

Task 1: 24 cells (8 indicators x 3 tiers), 0 PASS. Task 2: 27 cells (9 fingerprints x 3 tiers), 0 PASS. Combined: 0 PASS out of 51 cells.

**Multiple-testing note:** 51 total cells were tested in this single pass. A lone PASS among 51 tests at the 95% confidence level is not, on its own, a discovery -- roughly 1 in 20 tests is expected to cross the 50% CI-lower-bound threshold by chance alone even with zero true edge. Only a CLUSTER of related PASSes (e.g. the same indicator or fingerprint passing across multiple tiers, or several fingerprints from economically related tiers passing together) would be worth a second, independent look -- not a single isolated cell.

Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run for any cell in this task, regardless of verdict.
