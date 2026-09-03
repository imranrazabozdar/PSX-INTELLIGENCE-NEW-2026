# Feature-Family Regrouping + Within-Family Agreement Tests

**Run date (UTC):** 2026-09-03T17:54:49.691247+00:00

## Part 1 — free regrouping of already-completed results (zero new computation)

Both tables below are parsed directly from `analysis/phase1_all26_triple_barrier_results.md` and `analysis/liquidity_stratified_results.md`, already on disk from prior tasks. No backtest was re-run for this part.

### Family assignment (checkable)

| Family | Members |
|---|---|
| VOLUME | VOLUME_SPIKE, OBV_DIVERGE_BULL, CMF_POS, CMF_NEG |
| MOVING-AVERAGE | EMA20_CROSS_UP, EMA20_CROSS_DN, EMA50_CROSS_UP, EMA50_CROSS_DN, GOLDEN_CROSS, DEATH_CROSS |
| MOMENTUM | RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_HEALTHY, MOM_CROSS_POS, MOM_CROSS_NEG, MACD_CROSS_UP, MACD_CROSS_DOWN, MACD_HIST_POS |
| VOLATILITY | BB_OVERBOUGHT, BB_OVERSOLD, BB_SQUEEZE_BREAK, ADX_TRENDING, ADX_WEAK |

**Judgment call(s) noted explicitly:**
- ADX_TRENDING and ADX_WEAK measure trend STRENGTH, not volatility in the strict sense (they derive from directional movement, not price dispersion like Bollinger Bands). They are placed in VOLATILITY per this task's explicit pre-registered assignment, grouped there as a 'regime/dispersion' family alongside the Bollinger signals rather than in MOMENTUM (they don't measure direction) -- noted explicitly rather than silently reassigned.

### Family-level summary — pooled (all 23 indicators' own already-completed pooled result)

| Family | Members (n) | Mean precision | Mean Wilson CI lower bound | Closest member to 50% |
|---|---|---|---|---|
| VOLUME | 4 | 36.98% | 35.27% | CMF_POS (38.90%, gap 11.10pts) |
| MOVING-AVERAGE | 6 | 33.20% | 30.62% | EMA20_CROSS_UP (36.58%, gap 13.42pts) |
| MOMENTUM | 8 | 36.80% | 34.62% | RSI_OVERBOUGHT (42.15%, gap 7.85pts) |
| VOLATILITY | 5 | 37.00% | 34.29% | BB_OVERBOUGHT (46.68%, gap 3.32pts) |

### Family-level summary — by liquidity tier (only using the top-8 indicators already tiered)

| Family | Tier | Members used | Mean precision | Mean Wilson CI lower bound |
|---|---|---|---|---|
| VOLUME | A | VOLUME_SPIKE, OBV_DIVERGE_BULL, CMF_POS | 34.96% | 32.24% |
| VOLUME | B | VOLUME_SPIKE, OBV_DIVERGE_BULL, CMF_POS | 34.90% | 32.40% |
| VOLUME | C | VOLUME_SPIKE, OBV_DIVERGE_BULL, CMF_POS | 42.96% | 40.45% |
| MOVING-AVERAGE | A | (none of this family's members are in the top-8 tiered set) | — | — |
| MOVING-AVERAGE | B | (none of this family's members are in the top-8 tiered set) | — | — |
| MOVING-AVERAGE | C | (none of this family's members are in the top-8 tiered set) | — | — |
| MOMENTUM | A | RSI_OVERBOUGHT, RSI_HEALTHY, MOM_CROSS_POS | 35.71% | 31.86% |
| MOMENTUM | B | RSI_OVERBOUGHT, RSI_HEALTHY, MOM_CROSS_POS | 37.61% | 34.06% |
| MOMENTUM | C | RSI_OVERBOUGHT, RSI_HEALTHY, MOM_CROSS_POS | 45.64% | 42.04% |
| VOLATILITY | A | BB_OVERBOUGHT, BB_SQUEEZE_BREAK | 37.44% | 33.49% |
| VOLATILITY | B | BB_OVERBOUGHT, BB_SQUEEZE_BREAK | 43.61% | 39.98% |
| VOLATILITY | C | BB_OVERBOUGHT, BB_SQUEEZE_BREAK | 49.79% | 46.28% |

## Part 2 — two NEW pre-registered within-family agreement tests

Universe: 86 of 89 watchlist symbols with usable history. Holdout window: 2025-09-03 to 2026-09-03 (mechanical, identical derivation to every other test in this project). Same barriers as phase1_all26_sweep.py: upper = entry close + 2.0xATR(14); lower = entry close - 1.5xATR(14); vertical = 15 trading days; same-day double-touch resolves to the lower barrier. n>=150 required or INCONCLUSIVE; PASS only if Wilson 95% CI lower bound on +1-class precision > 50.0%.

### Test A — MA Stack Alignment

**Definition:** trigger fires on any day where close > EMA20 AND EMA20 > EMA50 AND EMA50 > EMA100 simultaneously (full bullish stack), computed on the closing price with standard exponential moving averages (`close.ewm(span=N, adjust=False).mean()`, the same method already used for EMA20/EMA50 in `backend/indicator_backtester.py`'s `_compute_signals()` -- EMA100 is the only new series, computed identically, not reimplemented). A persistent STATE condition (every day the stack holds), not a one-bar crossover event.

| n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |
|---|---|---|---|---|---|---|
| 5255 | 2155 | 2511 | 589 | 41.01% | [39.69%, 42.34%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |

Component indicators for the beats-every-component check: EMA20_CROSS_UP (36.58%), EMA50_CROSS_UP (34.73%), GOLDEN_CROSS (34.59%) -- the three bullish MOVING-AVERAGE-family members Test A's alignment condition is built from (the bearish members EMA20_CROSS_DN/EMA50_CROSS_DN/DEATH_CROSS are not relevant comparators for a bullish-stack test).

### Test B — Volume Confirmation Cluster

**Definition:** trigger fires on any day where at least 2 of these 3 volume-based conditions are true simultaneously: (a) volume >= 1.8x its 20-day average (reused verbatim as `VOLUME_SPIKE` from `_compute_signals()`); (b) OBV has risen while price was flat/down, reused verbatim as the existing `OBV_DIVERGE_BULL` boolean series from `_compute_signals()` -- **note:** the task text describing this condition said 'trailing 10 days', but the actual existing `OBV_DIVERGE_BULL` definition in `backend/indicator_backtester.py` uses a 30-bar lookback (`obv > obv.shift(30)` and `close <= close.shift(30) * 1.01`); per this project's reuse-verbatim-don't-redefine rule and the task's own instruction to reuse 'the existing OBV_DIVERGE_BULL definition', the actual 30-bar definition was reused as-is and this discrepancy is flagged here rather than silently resolved either way; (c) CMF(20) is positive (a persistent state -- `_cmf(...) > 0` -- computed with the existing `_cmf()` function but NOT the same event as `CMF_POS`, which is a one-bar cross-above-zero event; the task's own text specifies 'CMF(20) is positive', so the persistent-state condition is what was implemented, while `CMF_POS`'s pooled result is still used below as the comparison benchmark per the task's explicit instruction).

| n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |
|---|---|---|---|---|---|---|
| 2166 | 906 | 924 | 336 | 41.83% | [39.77%, 43.92%] | FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was |

**Trigger breakdown by which 2 (or 3) conditions were true:** volume+OBV only: 305; volume+CMF only: 1000; OBV+CMF only: 720; all three: 141.

Component indicators (as named explicitly in the task, all FAIL individually, pooled): VOLUME_SPIKE 38.83%, OBV_DIVERGE_BULL 35.86%, CMF_POS 38.90%.

## Summary

**Family profile:** pooled mean precision across the four families ranges from 33.20% (MOVING-AVERAGE) to 37.00% (VOLATILITY) -- a spread of 3.80 points. This is a modest, not dramatic, difference; no family is systematically distinct from the others -- all four sit well below the 50% CI-lower-bound line on both a pooled and a per-tier basis, and the same liquid-tier-does-better pattern documented in the earlier liquidity task shows up inside every family that has top-8 members represented (VOLUME, MOMENTUM, VOLATILITY), not just one.

**Test A (MA Stack Alignment):** precision 41.01% vs. its three bullish MOVING-AVERAGE components (EMA20_CROSS_UP 36.58%, EMA50_CROSS_UP 34.73%, GOLDEN_CROSS 34.59%) -- Test A beats ALL three of its components, a genuine finding by the task's own bar.

**Test B (Volume Confirmation Cluster):** precision 41.83% vs. its three components (VOLUME_SPIKE 38.83%, OBV_DIVERGE_BULL 35.86%, CMF_POS 38.90%) -- Test B beats ALL three of its components, a genuine finding by the task's own bar.

**Cumulative test count:** this task adds **2** new pre-registered tests (Test A, Test B) to the running total from this project: 23 pooled (phase1_all26_sweep) + 24 liquidity-tiered (liquidity_stratified_tests, Task 1) + 27 fingerprint-tiered (liquidity_stratified_tests, Task 2) + 30 cluster-validation (watchlist_cluster_analysis, Step 4) = 104 prior tests, **bringing the running total to 106**. A single PASS among this many cumulative tests across the whole investigation needs the same 1-in-20-by-chance skepticism applied consistently -- it does not reset per-task. Whatever Test A or Test B's individual verdict is here, it is one data point among 106, not evaluated in isolation.

Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run for any test in this task, regardless of verdict.
