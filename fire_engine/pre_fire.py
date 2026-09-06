"""pre_fire.py — Phase 10: PRE-FIRE detection.

PRE-FIRE (ALL must hold, as of the latest candle):
  1. MFI acceleration >= mfi_acceleration_threshold (over 5-15 candles)
  2. Price compression ACTIVE
  3. Volume NORMAL or thin (RV < max_relative_volume) -- MFI rising on
     thin volume is a real signal here, not filtered out (project rule)
  4. Support HOLDING
  5. NOT in the final 5 minutes of the session (near-close setups are
     tracked separately by session_transition.py, not scored as PRE-FIRE
     the same way)
"""
from datetime import datetime, timedelta

from fire_engine.compression import is_compression_active
from fire_engine.support_resistance import is_support_holding, calculate_support_resistance


def _minutes_to_close(candle_dt, market_close: str) -> float:
    dt = candle_dt if isinstance(candle_dt, datetime) else datetime.fromisoformat(str(candle_dt))
    close_h, close_m = (int(x) for x in market_close.split(":"))
    close_dt = dt.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return (close_dt - dt).total_seconds() / 60


def detect_pre_fire(candles: list, mfi_series: list, mfi_derivatives: dict,
                     relative_volume: float, cfg: dict) -> dict:
    """candles/mfi_series: full history up to "now", oldest first.
    mfi_derivatives: output of mfi_engine.calculate_mfi_derivatives(mfi_series).
    relative_volume: current bar's RV.
    cfg: the whole loaded fire_config dict (needs pre_fire, compression,
    support_resistance, session sections).

    Returns:
    {prefire_detected, prefire_score (0-70), mfi_acceleration,
     compression_active, volume_condition, support_holding, timestamp}
    """
    pf_cfg = cfg["pre_fire"]
    if not candles:
        return _empty_result()

    timestamp = candles[-1]["datetime"]
    minutes_left = _minutes_to_close(timestamp, cfg["session"]["market_close"])
    near_close_window = 5
    not_near_close = minutes_left > near_close_window

    delta_5 = mfi_derivatives.get("delta_5") or 0
    delta_15 = mfi_derivatives.get("delta_15") or 0
    mfi_acceleration = max(delta_5, delta_15)
    acceleration_ok = mfi_acceleration >= pf_cfg["mfi_acceleration_threshold"]

    compression_active = (
        is_compression_active(candles, cfg["compression"]) if pf_cfg["compression_required"] else True
    )

    volume_ok = relative_volume is not None and relative_volume < pf_cfg["max_relative_volume"]
    volume_condition = "NORMAL_OR_THIN" if volume_ok else ("UNKNOWN" if relative_volume is None else "ELEVATED_OR_ABOVE")

    support_holding = (
        is_support_holding(candles, cfg["support_resistance"]) if pf_cfg["support_required"] else True
    )

    detected = acceleration_ok and compression_active and volume_ok and support_holding and not_near_close

    # Score within the 0-70 WATCH..PRE-FIRE band: proportional credit for
    # each of the 4 substantive conditions (acceleration/compression/
    # volume/support), each worth up to 17.5 points -- near-close is a
    # gate, not a scored component.
    score = 0.0
    if acceleration_ok:
        score += 17.5
    if compression_active:
        score += 17.5
    if volume_ok:
        score += 17.5
    if support_holding:
        score += 17.5
    if not not_near_close:
        score = 0.0  # near-close disqualifies PRE-FIRE scoring entirely

    return {
        "prefire_detected": detected,
        "prefire_score": round(score),
        "mfi_acceleration": round(mfi_acceleration, 2),
        "compression_active": compression_active,
        "volume_condition": volume_condition,
        "support_holding": support_holding,
        "timestamp": timestamp,
    }


def _empty_result():
    return {
        "prefire_detected": False, "prefire_score": 0, "mfi_acceleration": 0.0,
        "compression_active": False, "volume_condition": "UNKNOWN",
        "support_holding": False, "timestamp": None,
    }
