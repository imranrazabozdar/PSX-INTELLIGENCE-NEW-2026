"""Unit tests for the Wyckoff Institutional Stealth Accumulation Detector
(fire_engine/wyckoff_detector.py). Run with: pytest fire_engine/tests/
No network access needed -- every fixture here is synthetic OHLCV built
in-process, never chart.scstrade.com or the shared Turso DB.

Each fixture is built to isolate ONE condition at a time: a ~45-day flat/
tight daily series (25 lead-in days to let ATR_14/SMA_20 stabilize, then
20 days forming the consolidation window) with a small number of days
deliberately perturbed to flip exactly one of the four scored metrics
(supply exhaustion, absorption, OBV divergence, BB compression) without
disturbing the others -- verified empirically (each helper below prints/
asserts the OTHER three flags stay at their baseline value) rather than
assumed from the formulas alone.
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fire_engine.wyckoff_detector import WyckoffDetector, DEFAULT_CONFIG


# --------------------------------------------------------------- fixtures --
def _build_daily(dry_days=0, absorption=False, price_zigzag=False, n=45):
    """Flat/tight ~45-day daily series. `dry_days` (0-3) marks that many
    low-volume days inside the last-10-day supply-exhaustion window;
    `absorption` adds one high-volume, tight-spread bar; `price_zigzag`
    alternates the close +-a few cents over the final 15 bars (which, as
    a side effect of z-normalized slope comparison, also flips both OBV
    divergence and MACD confirmation on -- used for the signal-tier
    fixtures below, not for isolating OBV divergence alone)."""
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    open_ = np.full(n, 100.0)
    volume = np.full(n, 100000.0)

    for i in range(25, n):  # consolidation window: tight 1.2-wide daily range
        high[i] = 100.6
        low[i] = 99.4

    for idx in [37, 39, 41][:dry_days]:
        volume[idx] = 30000.0  # < 0.5 x SMA_20

    if absorption:
        volume[40] = 260000.0  # >= 2.0 x SMA_20
        high[40] = close[40] + 0.3  # tight spread despite the volume spike
        low[40] = close[40] - 0.3

    if price_zigzag:
        for i in range(30, n):
            close[i] = 100.05 if i % 2 == 0 else 99.98

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _build_obv_divergence_daily(n=45):
    """Isolated OBV-divergence fixture: flat consolidation range (no
    absorption/dry-supply perturbation), but over the final 15 bars, up-
    days get heavier volume and down-days lighter volume with an equal-
    and-opposite price move each way -- net price change ~0 (flat slope)
    while volume-weighted OBV trends up."""
    df = _build_daily()
    for i in range(30, n):
        if i % 2 == 0:
            df.loc[df.index[i], "close"] = 100.05
            df.loc[df.index[i], "volume"] = 150000.0
        else:
            df.loc[df.index[i], "close"] = 99.98
            df.loc[df.index[i], "volume"] = 70000.0
    return df


def _build_4h(daily_index, tight=True):
    """20 trading days x 6 bars/day of 4-hour candles. `tight` gives a
    ~0.0005 BB width (well under the 0.10 threshold); the wide variant
    gives ~0.12 (well over it)."""
    h_dates, h_close = [], []
    for d in daily_index[-20:]:
        for h in (9, 11, 13, 15, 17, 19):
            h_dates.append(d + pd.Timedelta(hours=h))
            h_close.append(100.0)
    h_dates = pd.DatetimeIndex(h_dates)
    amp = 0.02 if tight else 5.0
    h_close = np.array(h_close) + np.tile([0, amp, -amp, amp / 2, -amp / 2, 0], 20)[: len(h_close)]
    wing = 0.05 if tight else 3.0
    return pd.DataFrame(
        {"open": h_close, "high": h_close + wing, "low": h_close - wing, "close": h_close,
         "volume": np.full(len(h_close), 15000.0)},
        index=h_dates,
    )


# ---------------------------------------------------------- rolling_slope --
def test_rolling_slope_calculation():
    """Without z-normalization, the slope at each point must exactly match
    numpy's own polyfit over the same trailing window."""
    values = np.arange(30, dtype=float) * 1.0 + 5.0  # strictly linear, slope 1.0
    series = pd.Series(values)
    window = 15
    slopes = WyckoffDetector.rolling_slope(series, window=window, z_normalize=False)

    expected_last = np.polyfit(np.arange(window), values[-window:], 1)[0]
    assert slopes.iloc[-1] == pytest.approx(expected_last)
    assert slopes.iloc[-1] == pytest.approx(1.0)
    assert pd.isna(slopes.iloc[window - 2])  # not enough history yet


# ----------------------------------------------------------------- OBV ----
def test_obv_calculation():
    """OBV[0] = 0 by convention (first bar has no prior close to compare
    against); a strictly rising close series accumulates full volume each
    day after that; a strictly falling series accumulates negative volume."""
    n = 6
    vol = 1000
    dates = pd.date_range("2026-01-01", periods=n, freq="D")

    rising = pd.DataFrame({"close": np.arange(100.0, 100.0 + n), "volume": [vol] * n}, index=dates)
    obv_up = WyckoffDetector.calculate_obv(rising)
    assert obv_up.iloc[0] == 0
    assert list(obv_up) == [0, vol, 2 * vol, 3 * vol, 4 * vol, 5 * vol]

    falling = pd.DataFrame({"close": np.arange(100.0, 100.0 - n, -1), "volume": [vol] * n}, index=dates)
    obv_dn = WyckoffDetector.calculate_obv(falling)
    assert obv_dn.iloc[0] == 0
    assert list(obv_dn) == [0, -vol, -2 * vol, -3 * vol, -4 * vol, -5 * vol]


# ------------------------------------------------------- consolidation ----
def test_consolidation_bounds_pct():
    """Method A: (High_20d - Low_20d) / Low_20d <= 0.08 is enough on its
    own to mark the session as consolidating."""
    det = WyckoffDetector()
    df = _build_daily()
    row = det.detect_stealth_accumulation(df).iloc[-1]
    assert row["consolidation_pct"] <= DEFAULT_CONFIG["consolidation_pct_threshold"]
    assert row["is_consolidating"] == True  # noqa: E712 (numpy bool)


def test_consolidation_bounds_atr():
    """Method B: (High_20d - Low_20d) / ATR_14 <= 4.5 must be able to mark
    consolidation on its OWN even when Method A's pct check fails --
    a wide-percentage but proportionally-normal-for-its-own-volatility
    swing (large ATR) is what Method B is for."""
    n = 40
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    base = 140 + 30 * np.sin(np.linspace(0, 4 * np.pi, n))
    df = pd.DataFrame(
        {"open": base, "high": base + 12, "low": base - 12, "close": base,
         "volume": np.full(n, 100000.0)},
        index=dates,
    )
    det = WyckoffDetector()
    row = det.detect_stealth_accumulation(df).iloc[-1]
    assert row["consolidation_pct"] > DEFAULT_CONFIG["consolidation_pct_threshold"]  # Method A fails
    assert row["consolidation_atr"] <= DEFAULT_CONFIG["consolidation_atr_multiplier"]  # Method B passes
    assert row["is_consolidating"] == True  # noqa: E712


def test_consolidation_bounds_fail_both_methods():
    n = 40
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    close = np.linspace(100, 150, n)  # steady staircase: small daily TR, large 20d swing
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close,
         "volume": np.full(n, 100000.0)},
        index=dates,
    )
    det = WyckoffDetector()
    row = det.detect_stealth_accumulation(df).iloc[-1]
    assert row["is_consolidating"] == False  # noqa: E712


# ---------------------------------------------------------- supply exh. ---
def test_supply_exhaustion_count():
    """1 dry day in the 10-day window must NOT trip the flag; 2 must."""
    det = WyckoffDetector()
    row_1 = det.detect_stealth_accumulation(_build_daily(dry_days=1)).iloc[-1]
    row_2 = det.detect_stealth_accumulation(_build_daily(dry_days=2)).iloc[-1]
    assert row_1["dry_supply_flag"] == False  # noqa: E712
    assert row_2["dry_supply_flag"] == True  # noqa: E712


# ----------------------------------------------------------- absorption --
def test_absorption_volume_and_spread():
    """Volume >= 2x SMA_20 AND (tight spread/ATR OR small body/ATR) must
    trip absorption_active; the same volume spike with BOTH a wide
    spread AND a large body must NOT."""
    det = WyckoffDetector()
    row_pos = det.detect_stealth_accumulation(_build_daily(absorption=True)).iloc[-1]
    assert row_pos["absorption_active"] == True  # noqa: E712

    n = 45
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    open_ = np.full(n, 100.0)
    volume = np.full(n, 100000.0)
    for i in range(25, n):
        high[i] = 100.6
        low[i] = 99.4
    volume[40] = 260000.0
    open_[40], close[40], high[40], low[40] = 100.0, 118.0, 120.0, 96.0  # wide spread AND big body
    df_neg = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=dates)
    result_neg = det.detect_stealth_accumulation(df_neg)
    spike_row = result_neg.iloc[40]  # the bar the spike itself is on
    assert spike_row["spread_atr_ratio"] > DEFAULT_CONFIG["absorption_spread_atr_threshold"]
    assert spike_row["co_atr_ratio"] > DEFAULT_CONFIG["absorption_co_atr_threshold"]
    assert result_neg.iloc[-1]["absorption_active"] == False  # noqa: E712


# ---------------------------------------------------------- OBV divergence --
def test_obv_divergence():
    """OBV slope > 0.05 (z-normalized) with price slope <= 0.02 must trip
    obv_divergence; a flat baseline with no volume/price asymmetry must not."""
    det = WyckoffDetector()
    row_flat = det.detect_stealth_accumulation(_build_daily()).iloc[-1]
    assert row_flat["obv_divergence"] == False  # noqa: E712

    row_div = det.detect_stealth_accumulation(_build_obv_divergence_daily()).iloc[-1]
    assert row_div["obv_slope"] > DEFAULT_CONFIG["obv_slope_threshold"]
    assert row_div["price_slope"] <= DEFAULT_CONFIG["price_slope_threshold"]
    assert row_div["obv_divergence"] == True  # noqa: E712


# ------------------------------------------------------- BB compression --
def test_bb_compression_on_4h():
    """BB width computed on 4-hour bars, <= 0.10, must trip bb_compression
    on the daily row it resamples into; a wide 4h range must not."""
    det = WyckoffDetector()
    df_daily = _build_daily()

    tight_row = det.detect_stealth_accumulation(df_daily, _build_4h(df_daily.index, tight=True)).iloc[-1]
    assert tight_row["bb_width"] <= DEFAULT_CONFIG["bb_width_threshold"]
    assert tight_row["bb_compression"] == True  # noqa: E712

    wide_row = det.detect_stealth_accumulation(df_daily, _build_4h(df_daily.index, tight=False)).iloc[-1]
    assert wide_row["bb_width"] > DEFAULT_CONFIG["bb_width_threshold"]
    assert wide_row["bb_compression"] == False  # noqa: E712


# --------------------------------------------------------------- MACD -----
def test_macd_confirmation():
    n = 45
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    det = WyckoffDetector()

    up = np.linspace(100, 130, n)
    df_up = pd.DataFrame({"open": up, "high": up + 1, "low": up - 1, "close": up,
                          "volume": np.full(n, 100000.0)}, index=dates)
    row_up = det.detect_stealth_accumulation(df_up).iloc[-1]
    assert row_up["macd_line"] > row_up["macd_signal"]
    assert row_up["macd_confirmation"] == True  # noqa: E712

    dn = np.linspace(130, 100, n)
    df_dn = pd.DataFrame({"open": dn, "high": dn + 1, "low": dn - 1, "close": dn,
                          "volume": np.full(n, 100000.0)}, index=dates)
    row_dn = det.detect_stealth_accumulation(df_dn).iloc[-1]
    assert row_dn["macd_confirmation"] == False  # noqa: E712


# ------------------------------------------------------------- scoring ----
def test_accumulation_score_calculation():
    """Every component present -> 20+20+30+30 = 100, and each component
    score matches its own configured point value exactly."""
    det = WyckoffDetector()
    df_daily = _build_daily(dry_days=2, absorption=True)
    # Overlay the OBV-divergence perturbation onto the same dry+absorption
    # fixture so all four components are active simultaneously.
    for i in range(30, len(df_daily)):
        if i % 2 == 0:
            df_daily.iloc[i, df_daily.columns.get_loc("close")] = 100.05
            df_daily.iloc[i, df_daily.columns.get_loc("volume")] = max(
                df_daily.iloc[i]["volume"], 150000.0
            )
        else:
            df_daily.iloc[i, df_daily.columns.get_loc("close")] = 99.98
            df_daily.iloc[i, df_daily.columns.get_loc("volume")] = min(
                df_daily.iloc[i]["volume"], 70000.0
            )
    df_4h = _build_4h(df_daily.index, tight=True)

    row = det.detect_stealth_accumulation(df_daily, df_4h).iloc[-1]
    assert row["bb_compression"] == True  # noqa: E712
    assert row["dry_supply_flag"] == True  # noqa: E712
    assert row["absorption_active"] == True  # noqa: E712
    assert row["obv_divergence"] == True  # noqa: E712
    assert row["bb_width_score"] == DEFAULT_CONFIG["bb_width_points"]
    assert row["dry_supply_score"] == DEFAULT_CONFIG["supply_exhaustion_points"]
    assert row["absorption_score"] == DEFAULT_CONFIG["absorption_points"]
    assert row["obv_divergence_score"] == DEFAULT_CONFIG["obv_divergence_points"]
    assert row["accumulation_score"] == 100
    assert row["signal_type"] == "EXTREME"


# ------------------------------------------------------------- signals ----
def test_signal_generation():
    """WATCH (60-69), READY (70-84) and EXTREME (85+) each require both
    gates (is_consolidating AND macd_confirmation) plus the matching
    score band; a baseline with no active components stays NO_SIGNAL
    even though its gates are satisfied."""
    det = WyckoffDetector()

    baseline = det.detect_stealth_accumulation(_build_daily()).iloc[-1]
    assert baseline["accumulation_score"] == 0
    assert baseline["signal_type"] == "NO_SIGNAL"

    watch = det.detect_stealth_accumulation(_build_daily(absorption=True, price_zigzag=True)).iloc[-1]
    assert 60 <= watch["accumulation_score"] < 70
    assert watch["signal_type"] == "WATCH"

    ready = det.detect_stealth_accumulation(
        _build_daily(dry_days=2, absorption=True, price_zigzag=True)
    ).iloc[-1]
    assert 70 <= ready["accumulation_score"] < 85
    assert ready["signal_type"] == "READY"

    df_daily_extreme = _build_daily(dry_days=2, absorption=True)
    for i in range(30, len(df_daily_extreme)):
        vol_col, close_col = df_daily_extreme.columns.get_loc("volume"), df_daily_extreme.columns.get_loc("close")
        current_vol = df_daily_extreme.iloc[i, vol_col]
        if i % 2 == 0:
            df_daily_extreme.iloc[i, close_col] = 100.05
            df_daily_extreme.iloc[i, vol_col] = max(current_vol, 150000.0)
        else:
            df_daily_extreme.iloc[i, close_col] = 99.98
            df_daily_extreme.iloc[i, vol_col] = min(current_vol, 70000.0)
    extreme = det.detect_stealth_accumulation(
        df_daily_extreme, _build_4h(df_daily_extreme.index, tight=True)
    ).iloc[-1]
    assert extreme["accumulation_score"] >= 85
    assert extreme["signal_type"] == "EXTREME"


# --------------------------------------------------------- db/ui prep -----
def test_prepare_for_db_and_ui():
    det = WyckoffDetector()
    df = det.detect_stealth_accumulation(_build_daily(absorption=True))
    out = det.prepare_for_db_and_ui(df, "TESTSYM", "2026-02-14")

    assert out["symbol"] == "TESTSYM"
    assert out["scan_date"] == "2026-02-14"
    assert isinstance(out["accumulation_score"], int)
    assert isinstance(out["is_consolidating"], bool)
    assert isinstance(out["macd_confirmation"], bool)
    assert isinstance(out["bb_width"], float)
    assert out["signal_type"] in ("NO_SIGNAL", "WATCH", "READY", "EXTREME")

    components = json.loads(out["components"])
    assert set(components) == {
        "bb_compression", "supply_exhaustion", "absorption", "obv_divergence",
        "is_consolidating", "macd_confirmation",
    }
    assert components["absorption"] is True

    # NaN handling: a too-short DataFrame (rolling windows never fill in)
    # must come back as 0/False, never NaN or a numpy scalar.
    short_df = det.detect_stealth_accumulation(_build_daily(n=5))
    short_out = det.prepare_for_db_and_ui(short_df, "SHORT", "2026-01-05")
    assert short_out["accumulation_score"] == 0
    assert short_out["bb_width"] == 0.0
    assert short_out["is_consolidating"] is False


# ------------------------------------------------------ alignment integ. --
def test_integration_daily_4h_alignment():
    """Full pipeline, daily + 4-hour together: the resampled 4h BB width
    must land on the LAST calendar day (matching df_4h's own last date),
    not on some other day, and no 1-hour-anything must appear anywhere
    in the output (this pipeline never fetches or computes on 1h data)."""
    det = WyckoffDetector()
    df_daily = _build_daily()
    df_4h = _build_4h(df_daily.index, tight=True)

    result = det.detect_stealth_accumulation(df_daily, df_4h)

    last_day = df_daily.index[-1]
    assert not pd.isna(result.loc[last_day, "bb_width"])
    assert result.loc[last_day, "bb_width"] <= DEFAULT_CONFIG["bb_width_threshold"]

    # A day before df_4h's own range started must have NO 4h-derived value
    # (proves the merge landed on real matching dates, not a blanket fill).
    day_before_4h_range = df_daily.index[-21]
    assert pd.isna(result.loc[day_before_4h_range, "bb_width"])

    assert not any("1h" in c or "hourly" in c for c in result.columns)
    assert result.iloc[-1]["signal_type"] in ("NO_SIGNAL", "WATCH", "READY", "EXTREME")
