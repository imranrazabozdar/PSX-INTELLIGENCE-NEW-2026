# Phase 1 Triple-Barrier Sweep — All Indicators

**Run date (UTC):** 2026-09-03T17:08:57.964059+00:00
**Holdout window:** 2025-09-03 to 2026-09-03 (mechanical, execution-date-derived; identical for every indicator below)

**Count note:** the source task referred to "26 indicators." The authoritative source file for this sweep, `backend/indicator_backtester.py`'s `_compute_signals()` -- the exact same file used to verify BB_OVERSOLD's original definition -- defines exactly **23** signal types, not 26. A separate script (`backend/indicator_backtester_volume_extended.py`) defines additional signals under a different methodology that was never used to validate BB_OVERSOLD; borrowing from it would violate the reuse-the-same-source rule, so this sweep covers all 23 signals found in the authoritative source and reports this discrepancy plainly rather than padding the count. Zero indicators were SKIPPED for a missing definition -- all 23 were located directly in the source.

**Method (identical for every indicator, unchanged from the BB_OVERSOLD run):** upper barrier = entry close + 2.0×ATR(14); lower barrier = entry close − 1.5×ATR(14); vertical barrier = 15 trading days; same-day double-touch resolves to the lower barrier; pass/fail rule = Wilson 95% CI lower bound on +1-class precision > 50.0%, with n≥150 required or INCONCLUSIVE. No threshold was adjusted per-indicator.

## Summary table (sorted by Wilson CI lower bound, descending — display order only)

| Indicator | Trigger definition | n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |
|---|---|---|---|---|---|---|---|---|
| BB_OVERBOUGHT | close crosses above upper Bollinger Band(20,2) this bar | 1431 | 668 | 619 | 144 | 46.68% | [44.11%, 49.27%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| BB_SQUEEZE_BREAK | Bollinger bandwidth was at/below its own 60-bar 10th percentile the prior bar and widens this bar | 3128 | 1306 | 1124 | 698 | 41.75% | [40.03%, 43.49%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_OVERBOUGHT | RSI(14) crosses above 70 this bar | 1286 | 542 | 606 | 138 | 42.15% | [39.47%, 44.86%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| MOM_CROSS_POS | 20-bar momentum (pct_change*100) crosses above 0 this bar | 2351 | 942 | 856 | 553 | 40.07% | [38.10%, 42.06%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| VOLUME_SPIKE | volume >= 1.8x its own 20-day rolling average | 6475 | 2514 | 2878 | 1083 | 38.83% | [37.65%, 40.02%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| CMF_POS | Chaikin Money Flow(20) crosses above 0 this bar | 1550 | 603 | 646 | 301 | 38.90% | [36.51%, 41.35%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_HEALTHY | RSI(14) in [45,65] this bar AND RSI(14) was <45 the prior bar | 2853 | 1060 | 1104 | 689 | 37.15% | [35.40%, 38.94%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| OBV_DIVERGE_BULL | OBV higher than 30 bars ago AND close <=1% higher than 30 bars ago | 10069 | 3611 | 3911 | 2547 | 35.86% | [34.93%, 36.80%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| EMA20_CROSS_UP | close crosses above EMA(20) this bar | 3037 | 1111 | 1218 | 708 | 36.58% | [34.89%, 38.31%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| MACD_CROSS_UP | MACD line crosses above its signal line this bar | 1658 | 604 | 711 | 343 | 36.43% | [34.15%, 38.77%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| MACD_HIST_POS | MACD histogram turns positive this bar (>0 now, <=0 prior bar) | 1658 | 604 | 711 | 343 | 36.43% | [34.15%, 38.77%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| EMA20_CROSS_DN | close crosses below EMA(20) this bar | 3069 | 1074 | 1145 | 850 | 35.00% | [33.33%, 36.70%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| MOM_CROSS_NEG | 20-bar momentum (pct_change*100) crosses below 0 this bar | 2379 | 833 | 874 | 672 | 35.01% | [33.12%, 36.95%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| EMA50_CROSS_UP | close crosses above EMA(50) this bar | 1998 | 694 | 884 | 420 | 34.73% | [32.68%, 36.85%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| MACD_CROSS_DOWN | MACD line crosses below its signal line this bar | 1611 | 556 | 628 | 427 | 34.51% | [32.23%, 36.87%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| CMF_NEG | Chaikin Money Flow(20) crosses below 0 this bar | 1574 | 540 | 642 | 392 | 34.31% | [32.00%, 36.69%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| EMA50_CROSS_DN | close crosses below EMA(50) this bar | 2036 | 688 | 789 | 559 | 33.79% | [31.77%, 35.88%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| ADX_TRENDING | ADX crosses above 25 this bar | 704 | 247 | 341 | 116 | 35.09% | [31.65%, 38.68%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| RSI_OVERSOLD | RSI(14) crosses below 30 this bar | 1499 | 490 | 608 | 401 | 32.69% | [30.36%, 35.10%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| GOLDEN_CROSS | EMA(20) crosses above EMA(50) this bar | 425 | 147 | 205 | 73 | 34.59% | [30.22%, 39.23%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| ADX_WEAK | ADX crosses below 20 this bar | 768 | 251 | 291 | 226 | 32.68% | [29.46%, 36.08%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| BB_OVERSOLD *(carried over, not re-run)* | close crosses below lower Bollinger Band(20,2) this bar (close[t]<bb_lo[t] AND close[t-1]>=bb_lo[t-1]) | 1115 | 321 | 541 | 253 | 28.79% | [26.21%, 31.52%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |
| DEATH_CROSS | EMA(20) crosses below EMA(50) this bar | 469 | 115 | 217 | 137 | 24.52% | [20.84%, 28.61%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |

## Summary

Of the 23 indicators evaluated (including BB_OVERSOLD, carried over from its prior run): **0 PASS**, **23 FAIL**, **0 INCONCLUSIVE**, **0 SKIPPED** (no missing definitions this run).

No indicator PASSed in this sweep, so the multiple-testing caveat about trusting a PASS does not apply here -- there is no PASS to caveat. The general point still holds for any future rerun of this sweep that does produce one or more PASSes.

Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run for any indicator in this task, regardless of verdict.
