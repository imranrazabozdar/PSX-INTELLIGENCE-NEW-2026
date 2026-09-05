# Flat Base Detector — Phase 1b Results

Flat/Tight Base detector, tested against the same 11 known-move stocks and the same 50-stock random false-positive baseline (identical seed=42 sample) as Phase 1a's VCP detector, for direct comparison. Single detector, single test cycle, no tuning iteration.

## Section 1: 11-Stock Test Results

detect_flat_base() run with its exact defaults: `min_days=12, max_days=35, max_range_pct=12.0, volume_contraction=0.75, volume_threshold=1.5, lookback_days=60`. "hit" = breakout_date falls within 5 trading days of the user-given MOVE_START date.

### AICL (move-start: 2026-07-23)

| start_date | end_date | num_days | range_pct | volume_contraction_ratio | breakout_date | breakout_volume_ratio | overall_flat_base_quality_score | is_textbook_flat_base | hit_or_miss |
|---|---|---|---|---|---|---|---|---|---|
| 2026-05-25 | 2026-06-12 | 12 | 7.77 | 0.720 | 2026-06-15 | 2.968 | 40.31 | False | miss |

### SHFA (move-start: 2026-06-12)

| start_date | end_date | num_days | range_pct | volume_contraction_ratio | breakout_date | breakout_volume_ratio | overall_flat_base_quality_score | is_textbook_flat_base | hit_or_miss |
|---|---|---|---|---|---|---|---|---|---|
| 2026-04-15 | 2026-04-30 | 12 | 11.12 | 0.715 | 2026-05-19 | 2.399 | 25.88 | False | miss |
| 2026-04-20 | 2026-05-20 | 22 | 11.26 | 0.186 | 2026-05-25 | 1.632 | 36.65 | False | miss |
| 2026-04-22 | 2026-05-29 | 24 | 11.00 | 0.165 | 2026-06-02 | 4.502 | 55.40 | False | miss |
| 2026-04-22 | 2026-06-03 | 27 | 11.03 | 0.225 | 2026-06-11 | 1.732 | 36.88 | False | hit |
| 2026-04-22 | 2026-06-12 | 34 | 11.07 | 0.210 | 2026-06-15 | 2.382 | 41.09 | False | hit |
| 2026-04-23 | 2026-06-16 | 35 | 10.24 | 0.275 | 2026-06-17 | 3.798 | 50.39 | False | hit |

### THCCL (move-start: 2026-06-30)

| start_date | end_date | num_days | range_pct | volume_contraction_ratio | breakout_date | breakout_volume_ratio | overall_flat_base_quality_score | is_textbook_flat_base | hit_or_miss |
|---|---|---|---|---|---|---|---|---|---|
| 2026-04-14 | 2026-04-29 | 12 | 11.23 | 0.546 | 2026-05-07 | 3.662 | 38.14 | False | miss |
| 2026-05-08 | 2026-05-25 | 12 | 11.29 | 0.434 | 2026-06-01 | 6.895 | 49.37 | False | miss |
| 2026-06-09 | 2026-06-24 | 12 | 11.01 | 0.627 | 2026-07-07 | 3.786 | 37.20 | False | hit |

### FNEL (move-start: 2026-04-06)

No flat base detected in the 60-day lookback window.

### MDTL (move-start: 2026-07-23)

| start_date | end_date | num_days | range_pct | volume_contraction_ratio | breakout_date | breakout_volume_ratio | overall_flat_base_quality_score | is_textbook_flat_base | hit_or_miss |
|---|---|---|---|---|---|---|---|---|---|
| 2026-05-14 | 2026-06-03 | 12 | 10.24 | 0.236 | 2026-06-05 | 4.757 | 57.30 | False | miss |
| 2026-05-14 | 2026-06-08 | 15 | 11.40 | 0.416 | 2026-06-09 | 1.519 | 28.61 | False | miss |
| 2026-05-14 | 2026-06-10 | 17 | 11.34 | 0.428 | 2026-06-11 | 2.767 | 35.93 | False | miss |
| 2026-06-22 | 2026-07-09 | 12 | 9.90 | 0.342 | 2026-07-24 | 6.520 | 56.74 | False | hit |

### FPJM (move-start: 2026-08-13)

No flat base detected in the 60-day lookback window.

### DSIL (move-start: 2026-07-31)

No flat base detected in the 60-day lookback window.

### SYM (move-start: 2026-04-30)

| start_date | end_date | num_days | range_pct | volume_contraction_ratio | breakout_date | breakout_volume_ratio | overall_flat_base_quality_score | is_textbook_flat_base | hit_or_miss |
|---|---|---|---|---|---|---|---|---|---|
| 2026-05-04 | 2026-05-19 | 12 | 11.24 | 0.330 | 2026-06-04 | 2.365 | 36.84 | False | miss |
| 2026-05-04 | 2026-06-05 | 22 | 11.30 | 0.280 | 2026-06-12 | 2.044 | 36.18 | False | miss |
| 2026-05-04 | 2026-06-15 | 28 | 11.31 | 0.272 | 2026-06-16 | 1.619 | 33.87 | False | miss |
| 2026-05-04 | 2026-06-17 | 30 | 11.28 | 0.273 | 2026-06-23 | 3.988 | 48.11 | False | miss |

### PREMA (move-start: 2026-03-30)

| start_date | end_date | num_days | range_pct | volume_contraction_ratio | breakout_date | breakout_volume_ratio | overall_flat_base_quality_score | is_textbook_flat_base | hit_or_miss |
|---|---|---|---|---|---|---|---|---|---|
| 2026-03-10 | 2026-03-27 | 12 | 11.43 | 0.490 | 2026-04-08 | 2.294 | 30.94 | False | miss |

### JSBL (move-start: 2026-05-19)

No flat base detected in the 60-day lookback window.

### ILP (move-start: 2026-06-02)

| start_date | end_date | num_days | range_pct | volume_contraction_ratio | breakout_date | breakout_volume_ratio | overall_flat_base_quality_score | is_textbook_flat_base | hit_or_miss |
|---|---|---|---|---|---|---|---|---|---|
| 2026-04-22 | 2026-05-08 | 12 | 8.48 | 0.708 | 2026-06-04 | 9.500 | 50.51 | False | hit |
| 2026-04-22 | 2026-06-05 | 29 | 9.80 | 0.713 | 2026-06-09 | 3.671 | 37.98 | False | hit |

### Summary

- Stocks with >=1 flat base detected: **7/11** -> ['AICL', 'SHFA', 'THCCL', 'MDTL', 'SYM', 'PREMA', 'ILP']
- Total flat base events detected across all 11 stocks: **21**
- Stocks with >=1 'hit': **4/11** -> ['SHFA', 'THCCL', 'MDTL', 'ILP']
- Stocks with >=1 textbook flat base (quality >= 70): **0/11** -> []
- **Hit rate on known moves: 36.4%**

## Section 2: False Positive Baseline (50-Stock Sample)

Sample: same 50 stocks as Phase 1a's VCP baseline (seed=42), scanned with `detect_flat_base(ticker, lookback_days=126)` -- other params at their exact defaults.

*(All 50 sampled stocks failed to load -- e.g. `no such table: daily_ohlc` -- this environment can't reach the daily_ohlc DB. Run in GitHub Actions with LIBSQL secrets to populate this table.)*

### Summary

- No stocks loaded successfully; no baseline statistics available.

## Section 3: Assessment & Decisions for Phase 1c

**Hit rate on the 11 known stocks: 36.4% -> verdict: NEEDS REWORK**

The detector is **NEEDS REWORK**: the detector or definition needs rework before Phase 1c, not just tuning.

### Stocks the detector missed, and likely why

- **AICL**: 1 flat base(s) detected, but the closest breakout still landed 26 trading days from the known move-start (outside the 5-day hit window).
- **FNEL**: No 12-35 day window with range<=12% and volume contracted to <=75% of its prior level was found anywhere in the 60-day lookback -- this stock's pre-move structure isn't a flat/tight base by this definition.
- **FPJM**: No 12-35 day window with range<=12% and volume contracted to <=75% of its prior level was found anywhere in the 60-day lookback -- this stock's pre-move structure isn't a flat/tight base by this definition.
- **DSIL**: No 12-35 day window with range<=12% and volume contracted to <=75% of its prior level was found anywhere in the 60-day lookback -- this stock's pre-move structure isn't a flat/tight base by this definition.
- **SYM**: 4 flat base(s) detected, but the closest breakout still landed 21 trading days from the known move-start (outside the 5-day hit window).
- **PREMA**: 1 flat base(s) detected, but the closest breakout still landed 7 trading days from the known move-start (outside the 5-day hit window).
- **JSBL**: No 12-35 day window with range<=12% and volume contracted to <=75% of its prior level was found anywhere in the 60-day lookback -- this stock's pre-move structure isn't a flat/tight base by this definition.

## Section 4: Code & Definitions Locked

```python
def detect_flat_base(
    ticker: str,
    df: pd.DataFrame = None,
    min_days: int = 12,
    max_days: int = 35,
    max_range_pct: float = 12.0,
    volume_contraction: float = 0.75,
    volume_threshold: float = 1.5,
    lookback_days: int = 60,
) -> list:
```

Reused, unchanged, from `backend/vcp_detector.py` (so Phase 1a/1b scores are on the same scale): `MIN_VOLUME_BEFORE_BARS=3`, `VOL_BEFORE_WINDOW=10`, `BREAKOUT_SCAN_HORIZON=20`, `VOL_AVG_PERIOD=20`, `BREAKOUT_NORM_CAP_X=5.0`, `QUALITY_WEIGHTS=(0.4, 0.3, 0.3)`, `TEXTBOOK_THRESHOLD=70.0`.

Section 2 sample: identical 50 tickers and seed (42) as Phase 1a's VCP baseline; `lookback_days=126` there, other params at defaults.
