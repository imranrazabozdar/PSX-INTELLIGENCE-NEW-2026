# Watchlist-Wide Unsupervised Fingerprint Clustering (89 stocks)

**Run date (UTC):** 2026-09-03T17:44:06.729770+00:00

## Step 1 — mechanical move detection

Rule: close return >= +15% over any 10-trading-day window; once flagged, scan skips past that window's end (no overlapping flags per stock). Identical rule applied to all 89 watchlist symbols, no manual selection.

**Total moves found across all watchlist stocks: 1303** (from 86 of 89 symbols with usable cached history).
Of these, 1217 moves had a complete pre-move feature vector (anchor bar with full indicator history available) and were carried into clustering; 86 were detected but skipped from clustering for insufficient pre-move history at the anchor bar.

**7 symbol(s) with insufficient cached history (< 131 bars needed):**
SPSL (68 bars), GDL (130 bars), KOHC (0 bars), WAHDAT (77 bars), ECPL (0 bars), STL (0 bars), STLR (10 bars)

## Step 3 — clustering

Silhouette scores tested (k = number of clusters):

| k | Silhouette score |
|---|---|
| 4 | 0.1597 |
| 5 | 0.1769 |
| 6 | 0.1835 |
| 7 | 0.1571 |
| 8 | 0.1677 |
| 9 | 0.1850 |
| 10 | 0.1713 |
| 11 | 0.1733 |
| 12 | 0.1873 **<- chosen** |

**Chosen k = 12** (highest silhouette score, 0.1873), per the pre-registered selection rule.

| Cluster | Size | Dominant stock? | Description |
|---|---|---|---|
| 0 | 241 | No — spread across 78 distinct stocks, top ticker (TRG) only 3% | low bb_sigma; low rsi14; low macd_dir; Doji common (76% of moves) |
| 1 | 32 | No — spread across 17 distinct stocks, top ticker (BNL) only 16% | high atr_ratio_90; high ema20_50_rel; high rsi14; Doji common (78% of moves) |
| 2 | 149 | No — spread across 59 distinct stocks, top ticker (GAL) only 5% | high bb_sigma; high rsi14; high macd_dir; Doji common (76% of moves) |
| 3 | 188 | No — spread across 71 distinct stocks, top ticker (NRL) only 4% | low macd_dir; high mfi14; high obv_delta10_normvol; Doji common (68% of moves) |
| 4 | 146 | No — spread across 66 distinct stocks, top ticker (NBP) only 5% | Doji common (68% of moves); Bullish Engulfing common (100% of moves) |
| 5 | 3 | YES — MARI is 2/3 (67%) of this cluster's moves; NOT cross-stock | high macd_hist; low ema20_50_rel; high obv_delta10_normvol; Doji common (67% of moves) |
| 6 | 177 | No — spread across 65 distinct stocks, top ticker (KEL) only 3% | high macd_dir; low mfi14; low rsi14; Doji common (72% of moves) |
| 7 | 69 | No — spread across 47 distinct stocks, top ticker (HASCOL) only 7% | Doji common (74% of moves); Morning Star common (100% of moves) |
| 8 | 36 | No — spread across 29 distinct stocks, top ticker (BECO) only 6% | Doji common (75% of moves); Piercing Line common (100% of moves) |
| 9 | 3 | YES — FNEL is 2/3 (67%) of this cluster's moves; NOT cross-stock | low ema20_50_rel; low rsi14; high vol_ratio20 |
| 10 | 50 | No — spread across 30 distinct stocks, top ticker (MDTL) only 8% | high vol_ratio20; high bb_sigma; high obv_delta10_normvol; Doji common (56% of moves) |
| 11 | 123 | No — spread across 54 distinct stocks, top ticker (WASL) only 6% | low rsi14; low mfi14; low obv_delta10_normvol; Hammer common (100% of moves); Doji common (74% of moves) |

### Per-cluster mean feature profile

| Cluster | rsi14 | mfi14 | macd_hist | macd_dir | atr_ratio_90 | obv_delta10_normvol | ema20_50_rel | bb_sigma | vol_ratio20 | pat_bullish_engulfing | pat_morning_star | pat_hammer | pat_doji | pat_piercing_line |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 38.240 | 44.891 | -0.624 | -1.000 | 1.012 | -2.043 | -0.028 | -1.549 | 0.869 | 0.079 | 0.000 | 0.000 | 0.759 | 0.000 |
| 1 | 65.352 | 70.439 | -0.253 | -0.500 | 3.476 | 2.799 | 0.152 | 0.773 | 0.996 | 0.469 | 0.000 | 0.125 | 0.781 | 0.000 |
| 2 | 70.910 | 79.584 | 0.983 | 0.973 | 1.282 | 6.779 | 0.038 | 2.115 | 1.737 | 0.268 | 0.000 | 0.181 | 0.758 | 0.000 |
| 3 | 58.382 | 75.043 | 0.336 | -0.979 | 1.170 | 3.999 | 0.028 | 0.652 | 0.702 | 0.000 | 0.000 | 0.016 | 0.676 | 0.000 |
| 4 | 54.966 | 65.802 | 0.106 | -0.288 | 1.054 | 2.053 | 0.012 | 0.419 | 0.926 | 1.000 | 0.000 | 0.007 | 0.678 | 0.000 |
| 5 | 58.148 | 77.879 | 33.570 | -0.333 | 0.544 | 9.109 | -0.415 | 2.141 | 1.334 | 0.000 | 0.000 | 0.000 | 0.667 | 0.000 |
| 6 | 40.742 | 41.786 | -0.328 | 1.000 | 0.986 | -1.499 | -0.041 | -0.761 | 0.838 | 0.107 | 0.000 | 0.000 | 0.718 | 0.000 |
| 7 | 54.009 | 61.375 | 0.344 | 0.043 | 1.327 | 1.424 | 0.014 | 0.234 | 1.042 | 0.319 | 1.000 | 0.159 | 0.739 | 0.000 |
| 8 | 49.985 | 59.013 | -0.161 | -0.056 | 1.108 | 2.076 | 0.009 | -0.124 | 1.240 | 0.222 | 0.028 | 0.111 | 0.750 | 1.000 |
| 9 | 26.421 | 57.598 | -1.592 | 0.333 | 0.512 | 3.151 | -2.012 | 0.932 | 3.311 | 0.333 | 0.000 | 0.000 | 0.333 | 0.000 |
| 10 | 71.796 | 84.009 | 0.487 | 1.000 | 1.112 | 10.513 | 0.013 | 2.974 | 6.280 | 0.460 | 0.020 | 0.240 | 0.560 | 0.000 |
| 11 | 45.190 | 51.995 | -0.258 | -0.252 | 1.030 | -0.182 | -0.017 | -0.462 | 0.794 | 0.293 | 0.000 | 1.000 | 0.740 | 0.000 |

## Step 4 — out-of-sample validation (clusters with >= 15 members)

Clusters tested: [0, 1, 2, 3, 4, 6, 7, 8, 10, 11]. For each, the cluster centroid (mean +/- 1.0 std per numeric feature; majority-presence required for pattern flags seen in >=50% of members) is scanned as a fingerprint against the full 89-stock history, excluding each cluster's own original member dates. Hit = forward return > 0%. n>=20 required per cell or reported as "TOO FEW MATCHES". PASS only if Wilson 95% CI lower bound on win rate > 50.0%.

| Cluster | Horizon | n | Hits | Win rate | Wilson 95% CI | Verdict |
|---|---|---|---|---|---|---|
| 0 | +5d | 2312 | 1166 | 50.43% | [48.40%, 52.47%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 0 | +10d | 2312 | 1179 | 50.99% | [48.96%, 53.03%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 0 | +20d | 2312 | 1208 | 52.25% | [50.21%, 54.28%] | PASS — statistically significant edge, proceed to Phase 2 eligibility |
| 1 | +5d | 93 | 44 | 47.31% | [37.47%, 57.36%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 1 | +10d | 93 | 39 | 41.94% | [32.42%, 52.09%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 1 | +20d | 93 | 42 | 45.16% | [35.44%, 55.27%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 2 | +5d | 639 | 327 | 51.17% | [47.30%, 55.03%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 2 | +10d | 639 | 351 | 54.93% | [51.05%, 58.75%] | PASS — statistically significant edge, proceed to Phase 2 eligibility |
| 2 | +20d | 639 | 364 | 56.96% | [53.09%, 60.75%] | PASS — statistically significant edge, proceed to Phase 2 eligibility |
| 3 | +5d | 1896 | 927 | 48.89% | [46.65%, 51.14%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 3 | +10d | 1896 | 960 | 50.63% | [48.38%, 52.88%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 3 | +20d | 1896 | 893 | 47.10% | [44.86%, 49.35%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 4 | +5d | 909 | 430 | 47.30% | [44.08%, 50.55%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 4 | +10d | 909 | 430 | 47.30% | [44.08%, 50.55%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 4 | +20d | 909 | 469 | 51.60% | [48.35%, 54.83%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 6 | +5d | 2587 | 1244 | 48.09% | [46.17%, 50.01%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 6 | +10d | 2587 | 1326 | 51.26% | [49.33%, 53.18%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 6 | +20d | 2587 | 1359 | 52.53% | [50.61%, 54.45%] | PASS — statistically significant edge, proceed to Phase 2 eligibility |
| 7 | +5d | 430 | 198 | 46.05% | [41.39%, 50.77%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 7 | +10d | 430 | 182 | 42.33% | [37.74%, 47.04%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 7 | +20d | 430 | 201 | 46.74% | [42.08%, 51.47%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 8 | +5d | 258 | 132 | 51.16% | [45.09%, 57.20%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 8 | +10d | 258 | 125 | 48.45% | [42.42%, 54.53%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 8 | +20d | 258 | 114 | 44.19% | [38.26%, 50.29%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 10 | +5d | 111 | 41 | 36.94% | [28.54%, 46.21%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 10 | +10d | 111 | 46 | 41.44% | [32.71%, 50.74%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 10 | +20d | 111 | 44 | 39.64% | [31.03%, 48.94%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 11 | +5d | 844 | 425 | 50.36% | [46.99%, 53.72%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 11 | +10d | 844 | 417 | 49.41% | [46.04%, 52.78%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| 11 | +20d | 844 | 412 | 48.82% | [45.46%, 52.19%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |

## Summary

Across the 10 cluster(s) validated in Step 4 (30 cluster x horizon cells): 4 PASS, 26 FAIL, 0 TOO FEW MATCHES. 4 cell(s) showed real out-of-sample evidence of predicting a positive forward return beyond chance; the remaining cells are descriptive groupings of the specific moves that happened to form them, with no demonstrated predictive power once scanned out-of-sample.

**Multiple-testing note:** 30 cluster x horizon cells were tested in this single pass (10 clusters x up to 3 horizons each). A lone PASS among this many tests at the 95% confidence level is not, on its own, a discovery -- roughly 1 in 20 tests is expected to cross the 50% CI-lower-bound threshold by chance alone even with zero true edge. What would actually be interesting is consistency: the SAME cluster passing across multiple horizons, or a PASS with a wide CI margin well clear of 50% -- not a single isolated cell.

Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run for any cluster in this task, regardless of verdict.
