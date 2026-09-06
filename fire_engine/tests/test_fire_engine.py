"""Unit tests for the PSX FIRE Engine. Run with: pytest fire_engine/tests/
No network access needed -- everything here exercises pure computation
or a throwaway local sqlite file, never chart.scstrade.com."""
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fire_engine.mfi_engine import calculate_mfi, calculate_mfi_derivatives, compare_mfi
from fire_engine.volume_engine import classify_volume
from fire_engine.validators import validate_trading_session
from fire_engine.scoring import calculate_fire_score
from fire_engine.database import DatabaseManager
from fire_engine.exclusions import is_stock_excluded, filter_excluded_stocks
from fire_engine.config import load_config
from fire_engine.pre_fire import detect_pre_fire


def _mk_candle(dt, o, h, l, c, v):
    return {"datetime": dt, "date": dt[:10], "time_of_day": dt[11:16],
            "open": o, "high": h, "low": l, "close": c, "volume": v}


def _rising_candles(n=20, start=100.0, step=0.5, vol=1000):
    out, price = [], start
    for i in range(n):
        price += step
        out.append(_mk_candle(f"2026-01-01 09:{i:02d}:00", price - 0.1, price + 0.2, price - 0.2, price, vol))
    return out


# --------------------------------------------------------------------- MFI --
def test_mfi_all_rising_approaches_100():
    mfi = calculate_mfi(_rising_candles(step=0.5), length=14)
    assert mfi[-1] == 100.0


def test_mfi_all_falling_approaches_0():
    mfi = calculate_mfi(_rising_candles(step=-0.5), length=14)
    assert mfi[-1] == 0.0


def test_mfi_insufficient_history_is_none():
    mfi = calculate_mfi(_rising_candles(n=5), length=14)
    assert all(v is None for v in mfi)


def test_mfi_derivatives_direction_and_persistence():
    mfi = calculate_mfi(_rising_candles(n=30, step=0.5), length=14)
    d = calculate_mfi_derivatives(mfi)
    assert d["direction"] in (0, 1)
    assert d["persistence"] >= 0


def test_compare_mfi_flags_real_discrepancy():
    calculated = [50.0, 60.0, 70.0]
    imported = [50.0, 60.0, 90.0]  # last value is way off
    report = compare_mfi(calculated, imported, tolerance=1.0)
    assert report["comparable"]
    assert report["num_discrepancies"] == 1


# ---------------------------------------------------------- Relative volume --
def test_classify_volume_thresholds():
    cfg = {"elevated_rv": 1.5, "abnormal_rv": 2.0, "extreme_rv": 3.0}
    assert classify_volume(0.8, cfg) == "BELOW_AVERAGE"
    assert classify_volume(1.2, cfg) == "NORMAL"
    assert classify_volume(1.7, cfg) == "ELEVATED"
    assert classify_volume(2.5, cfg) == "ABNORMAL"
    assert classify_volume(3.5, cfg) == "EXTREME"


# -------------------------------------------------------------- Validation --
def test_validation_flags_ohlc_violation():
    bad = [_mk_candle("2026-01-01 09:00:00", 100, 99, 98, 100, 1000)]  # high < open
    report = validate_trading_session("TEST", bad, expected_candles=1)
    assert report["quality_status"] == "ANOMALY"
    assert not report["is_valid"]


def test_validation_flags_duplicate_timestamp():
    candles = [
        _mk_candle("2026-01-01 09:00:00", 100, 101, 99, 100, 1000),
        _mk_candle("2026-01-01 09:00:00", 100, 101, 99, 100, 1000),
    ]
    report = validate_trading_session("TEST", candles, expected_candles=2)
    assert report["duplicate_count"] == 1


def test_validation_detects_time_gap():
    candles = [
        _mk_candle("2026-01-01 09:00:00", 100, 101, 99, 100, 1000),
        _mk_candle("2026-01-01 09:05:00", 100, 101, 99, 100, 1000),
    ]
    report = validate_trading_session("TEST", candles, expected_candles=2)
    assert any("Time gap" in i for i in report["issues"])


def test_validation_clean_session_is_complete():
    candles = _rising_candles(n=5)
    report = validate_trading_session("TEST", candles, expected_candles=5)
    assert report["quality_status"] == "COMPLETE"
    assert report["is_valid"]


# ------------------------------------------------------------ FIRE scoring --
def test_fire_score_all_max_is_100():
    cfg = load_config()
    result = calculate_fire_score(
        mfi_acceleration=cfg["mfi"]["acceleration_threshold_15m"] * 2,
        mfi_persistence=20, price_compression_active=True, absorption_score=100,
        support_strength=1.0, volume_expansion=cfg["volume"]["abnormal_rv"] * 2,
        breakout_confirmed=True, cfg=cfg,
    )
    assert result["total_score"] == 100
    assert result["rating"] == "EXTREME_FIRE"


def test_fire_score_all_zero_is_no_setup():
    cfg = load_config()
    result = calculate_fire_score(
        mfi_acceleration=0, mfi_persistence=0, price_compression_active=False,
        absorption_score=0, support_strength=0.0, volume_expansion=0,
        breakout_confirmed=False, cfg=cfg,
    )
    assert result["total_score"] == 0
    assert result["rating"] == "NO_SETUP"


# --------------------------------------------------------------- Exclusions --
def test_exclusion_filter():
    excluded = ["AABS", "BATA"]
    assert is_stock_excluded("aabs", excluded)  # case-insensitive
    assert not is_stock_excluded("AICL", excluded)
    kept = filter_excluded_stocks(["AICL", "AABS", "SHFA", "BATA"], excluded)
    assert kept == ["AICL", "SHFA"]


# ------------------------------------------------------- Idempotent storage --
def test_insert_candles_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test_fire.db")
        db = DatabaseManager(db_path=db_path)
        candles = _rising_candles(n=3)
        db.insert_candles("AICL", candles)
        db.insert_candles("AICL", candles)  # run twice
        count = db.conn.execute("SELECT COUNT(*) AS n FROM market_candles").fetchone()["n"]
        db.close()
        assert count == 3  # not 6


def test_query_candles_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test_fire.db")
        db = DatabaseManager(db_path=db_path)
        candles = _rising_candles(n=3)
        db.insert_candles("AICL", candles)
        rows = db.query_candles("AICL", "2026-01-01", "2026-01-01")
        db.close()
        assert len(rows) == 3
        assert rows[0]["symbol"] == "AICL"


# ------------------------------------------------------------ pre_fire ----
def test_prefire_score_varies_with_signal_strength_not_flat_70():
    """Regression test for the "every logged PRE-FIRE score is exactly 70"
    bug found against real 2026-09-04 production data: prefire_detected
    requires ALL FOUR gates (acceleration/compression/volume/support) to
    hold at once, so if the score were a flat 17.5 credit per passing gate
    (the original, buggy version), every detected case -- the only ones
    scheduler.py ever logs -- would score exactly 70 with zero variance,
    regardless of how different the underlying numbers actually were. The
    score must scale with how strongly each gate passed, not just whether
    it did."""
    cfg = load_config()
    accel_threshold = cfg["pre_fire"]["mfi_acceleration_threshold"]
    max_rv = cfg["pre_fire"]["max_relative_volume"]
    candle = {"datetime": "2026-09-04 10:00:00", "date": "2026-09-04", "time_of_day": "10:00",
              "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000}
    candles = [candle]

    with patch("fire_engine.pre_fire.is_compression_active", return_value=True), \
         patch("fire_engine.pre_fire.is_support_holding", return_value=True), \
         patch("fire_engine.pre_fire.detect_price_compression") as mock_compress, \
         patch("fire_engine.pre_fire.calculate_support_resistance") as mock_support:

        # Barely passing: right at each threshold, no bonus strength anywhere.
        mock_compress.return_value = [{"price_range_pct": cfg["compression"]["price_change_pct"]}]
        mock_support.return_value = {"level_strength": 0.0}
        barely = detect_pre_fire(
            candles, mfi_series=[50.0], mfi_derivatives={"delta_5": accel_threshold, "delta_15": 0},
            relative_volume=max_rv - 1e-6, cfg=cfg,
        )

        # Strongly passing: well past every threshold.
        mock_compress.return_value = [{"price_range_pct": 0.0}]
        mock_support.return_value = {"level_strength": 1.0}
        strong = detect_pre_fire(
            candles, mfi_series=[50.0], mfi_derivatives={"delta_5": 2 * accel_threshold, "delta_15": 0},
            relative_volume=0.0, cfg=cfg,
        )

    assert barely["prefire_detected"] is True
    assert strong["prefire_detected"] is True
    assert strong["prefire_score"] == 70
    assert barely["prefire_score"] < strong["prefire_score"]
