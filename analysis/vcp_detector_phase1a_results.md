# VCP Detector — Phase 1a Results

Minervini-style Volatility Contraction Pattern detector, tested against the 11 known-move stocks from the pre-move forensic study and a 50-stock random false-positive baseline. Single detector, single test cycle, no tuning iteration -- per the task's own cost-control instruction.

## Section 1: 11-Stock Test Results

detect_vcp() run with its exact defaults: `lookback_days=60, min_contractions=2, volume_threshold=1.5`. "hit" = breakout_date falls within 5 trading days (position in this stock's own trading-day sequence, not calendar days) of the user-given MOVE_START date reused from `analyze_premove.py`.

### AICL (move-start: 2026-07-23)

| start_date | num_contractions | tightness_score | volume_dry_up_score | breakout_date | breakout_volume_ratio | overall_vcp_quality_score | is_textbook_vcp | hit_or_miss |
|---|---|---|---|---|---|---|---|---|
| 2026-06-23 | 2 | 61.33 | 22.49 | 2026-06-30 | 2.534 | 46.48 | False | miss |
| 2026-07-09 | 2 | 66.67 | 16.39 | 2026-07-27 | 1.706 | 41.82 | False | hit |

### SHFA (move-start: 2026-06-12)

| start_date | num_contractions | tightness_score | volume_dry_up_score | breakout_date | breakout_volume_ratio | overall_vcp_quality_score | is_textbook_vcp | hit_or_miss |
|---|---|---|---|---|---|---|---|---|
| 2026-05-04 | 2 | 50.11 | 62.95 | 2026-05-19 | 2.399 | 53.32 | False | miss |

### THCCL (move-start: 2026-06-30)

| start_date | num_contractions | tightness_score | volume_dry_up_score | breakout_date | breakout_volume_ratio | overall_vcp_quality_score | is_textbook_vcp | hit_or_miss |
|---|---|---|---|---|---|---|---|---|
| 2026-04-16 | 2 | 60.16 | 60.31 | 2026-05-07 | 3.662 | 64.13 | False | miss |

### FNEL (move-start: 2026-04-06)

| start_date | num_contractions | tightness_score | volume_dry_up_score | breakout_date | breakout_volume_ratio | overall_vcp_quality_score | is_textbook_vcp | hit_or_miss |
|---|---|---|---|---|---|---|---|---|
| 2026-03-03 | 3 | 80.56 | 38.72 | 2026-03-26 | 1.647 | 53.72 | False | miss |
| 2026-03-16 | 2 | 25.00 | 41.87 | 2026-03-26 | 1.647 | 32.44 | False | miss |
| 2026-04-15 | 2 | 69.23 | 40.25 | 2026-04-23 | 5.709 | 69.77 | False | miss |

### MDTL (move-start: 2026-07-23)

| start_date | num_contractions | tightness_score | volume_dry_up_score | breakout_date | breakout_volume_ratio | overall_vcp_quality_score | is_textbook_vcp | hit_or_miss |
|---|---|---|---|---|---|---|---|---|
| 2026-06-01 | 3 | 46.15 | 66.64 | 2026-06-05 | 4.757 | 67.00 | False | miss |
| 2026-06-09 | 2 | 76.92 | 0.00 | 2026-06-11 | 2.767 | 47.37 | False | miss |

### FPJM (move-start: 2026-08-13)

No VCP detected in the 60-day lookback window ending at this stock's last available bar.

### DSIL (move-start: 2026-07-31)

No VCP detected in the 60-day lookback window ending at this stock's last available bar.

### SYM (move-start: 2026-04-30)

No VCP detected in the 60-day lookback window ending at this stock's last available bar.

### PREMA (move-start: 2026-03-30)

No VCP detected in the 60-day lookback window ending at this stock's last available bar.

### JSBL (move-start: 2026-05-19)

| start_date | num_contractions | tightness_score | volume_dry_up_score | breakout_date | breakout_volume_ratio | overall_vcp_quality_score | is_textbook_vcp | hit_or_miss |
|---|---|---|---|---|---|---|---|---|
| 2026-03-10 | 2 | 75.38 | 18.51 | 2026-04-01 | 2.143 | 48.56 | False | miss |

### ILP (move-start: 2026-06-02)

No VCP detected in the 60-day lookback window ending at this stock's last available bar.

### Summary

- Stocks with >=1 VCP detected: **6/11** -> ['AICL', 'SHFA', 'THCCL', 'FNEL', 'MDTL', 'JSBL']
- Total VCP events detected across all 11 stocks: **10**
- Stocks with >=1 'hit' (breakout within 5 trading days of the known move-start): **1/11** -> ['AICL']
- Stocks with >=1 textbook VCP (overall_vcp_quality_score >= 70): **0/11** -> []
- **Hit rate on known moves (stocks with a hit / 11): 9.1%**

## Section 2: False Positive Baseline (50-Stock Sample)

*(Not yet available -- vcp_50stock_results.json missing. This half runs in GitHub Actions where the daily_ohlc DB is reachable; see .github/workflows/vcp_phase1a_baseline.yml.)*

## Section 3: Assessment & Decisions for Phase 1b

**Hit rate on the 11 known stocks: 9.1% -> verdict: NEEDS REWORK**

Hit rate is below 50%: the detector, or the VCP definition itself, needs rework before Phase 1b, not just parameter tuning.

### Stocks the detector missed, and likely why

- **SHFA**: 1 VCP(s) detected, but the closest breakout still landed 15 trading days from the known move-start (outside the 5-day hit window) -- a real contraction/volume pattern exists in the window, just not timed to this stock's specific user-given move-start date.
- **THCCL**: 1 VCP(s) detected, but the closest breakout still landed 33 trading days from the known move-start (outside the 5-day hit window) -- a real contraction/volume pattern exists in the window, just not timed to this stock's specific user-given move-start date.
- **FNEL**: 3 VCP(s) detected, but the closest breakout still landed 7 trading days from the known move-start (outside the 5-day hit window) -- a real contraction/volume pattern exists in the window, just not timed to this stock's specific user-given move-start date.
- **MDTL**: 2 VCP(s) detected, but the closest breakout still landed 28 trading days from the known move-start (outside the 5-day hit window) -- a real contraction/volume pattern exists in the window, just not timed to this stock's specific user-given move-start date.
- **FPJM**: No contraction sequence of >=2 consecutive tightening days was found anywhere in this stock's 60-day lookback window at all -- this stock's run-up may be a different archetype entirely (e.g. a grind/flat base rather than a classic VCP), or its true base sits outside the last 60 trading days of the fetched window.
- **DSIL**: No contraction sequence of >=2 consecutive tightening days was found anywhere in this stock's 60-day lookback window at all -- this stock's run-up may be a different archetype entirely (e.g. a grind/flat base rather than a classic VCP), or its true base sits outside the last 60 trading days of the fetched window.
- **SYM**: No contraction sequence of >=2 consecutive tightening days was found anywhere in this stock's 60-day lookback window at all -- this stock's run-up may be a different archetype entirely (e.g. a grind/flat base rather than a classic VCP), or its true base sits outside the last 60 trading days of the fetched window.
- **PREMA**: No contraction sequence of >=2 consecutive tightening days was found anywhere in this stock's 60-day lookback window at all -- this stock's run-up may be a different archetype entirely (e.g. a grind/flat base rather than a classic VCP), or its true base sits outside the last 60 trading days of the fetched window.
- **JSBL**: 1 VCP(s) detected, but the closest breakout still landed 33 trading days from the known move-start (outside the 5-day hit window) -- a real contraction/volume pattern exists in the window, just not timed to this stock's specific user-given move-start date.
- **ILP**: No contraction sequence of >=2 consecutive tightening days was found anywhere in this stock's 60-day lookback window at all -- this stock's run-up may be a different archetype entirely (e.g. a grind/flat base rather than a classic VCP), or its true base sits outside the last 60 trading days of the fetched window.

## Section 4: Code & Definitions Locked

Exact frozen signature (see `backend/vcp_detector.py` for the full algorithm docstring):

```python
def detect_vcp(
    ticker: str,
    lookback_days: int = 60,
    min_contractions: int = 2,
    volume_threshold: float = 1.5,
    bars=None,
):
```

Frozen constants used by every call in this report:

| Constant | Value | Meaning |
|---|---|---|
| `MIN_VOLUME_BEFORE_BARS` | 3 | Minimum bars of trailing volume history required to score a candidate |
| `VOL_BEFORE_WINDOW` | 10 | Bars of trailing volume used for `avg_vol_before` |
| `BREAKOUT_SCAN_HORIZON` | 20 | Trading days scanned forward from base-end for a breakout |
| `VOL_AVG_PERIOD` | 20 | Rolling volume-average period (inclusive of the day itself) |
| `BREAKOUT_NORM_CAP_X` | 5.0 | breakout_volume_ratio at/above this earns full marks on that component |
| `QUALITY_WEIGHTS` | (0.4, 0.3, 0.3) | (tightness, volume_dry_up, breakout) weights, sums to 1.0 |
| `TEXTBOOK_THRESHOLD` | 70.0 | `overall_vcp_quality_score` cutoff for `is_textbook_vcp` |

Parameters used in this report's two test runs:

- **Section 1 (11 known stocks):** all defaults, unchanged (`lookback_days=60, min_contractions=2, volume_threshold=1.5`).
- **Section 2 (50-stock baseline):** `lookback_days=126` (the one deliberate deviation, to span ~6 trading months as Step 3 asked for), `min_contractions=2, volume_threshold=1.5` kept at defaults.

This definition is frozen as of this report. Any change to the algorithm, weights, or
thresholds above for Phase 1b must be a new, separately-dated version, not a silent edit
of this one.
