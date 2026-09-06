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

from fire_engine.compression import detect_price_compression, is_compression_active
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

    # Score within the 0-70 WATCH..PRE-FIRE band: each of the 4 substantive
    # conditions (acceleration/compression/volume/support) is worth up to
    # 17.5 points, scaled by HOW STRONGLY it passed -- not a flat 17.5 for
    # merely clearing its gate. That flat-credit version was a real bug:
    # prefire_detected requires ALL FOUR gates to hold at once, so every
    # single event actually logged (scheduler.py only calls log_fire_event
    # when prefire_detected is True) necessarily had all four gates passing
    # -- meaning every stored PRE_FIRE row scored exactly 17.5*4 = 70.0,
    # with zero possible variance, regardless of how different the
    # underlying MFI/volume/compression numbers actually were (reported as
    # "all PRE-FIRE signals showing FIRE Score = 70" against real 2026-09-04
    # production data). The 0-70 range was only ever reachable by
    # non-detected cases, which are never stored at all.
    #
    # acceleration: passing at exactly the threshold earns half credit;
    # 2x the threshold (a clearly documented, tunable calibration choice,
    # not a fixed law) earns full credit.
    accel_score = 17.5 * min(1.0, mfi_acceleration / (2 * pf_cfg["mfi_acceleration_threshold"])) if acceleration_ok else 0.0

    # compression: tighter than the threshold earns more credit than a
    # compression that barely qualifies (e.g. via the adaptive-ATR method
    # without also being tight in simple percentage terms).
    compression_score = 0.0
    if compression_active:
        lookback = cfg["compression"]["lookback_minutes"]
        periods = detect_price_compression(candles[-lookback:], cfg["compression"])
        range_pct = periods[-1]["price_range_pct"] if periods else cfg["compression"]["price_change_pct"]
        compression_score = 17.5 * max(0.0, min(1.0, 1 - range_pct / cfg["compression"]["price_change_pct"]))

    # volume: thinner volume earns more credit than volume that's merely
    # under the elevated-RV cutoff -- "MFI rising on thin volume" (this
    # module's own PRE-FIRE rule 3) is the stronger version of this signal.
    volume_score = 17.5 * max(0.0, min(1.0, (pf_cfg["max_relative_volume"] - relative_volume) / pf_cfg["max_relative_volume"])) \
        if volume_ok else 0.0

    # support: calculate_support_resistance()'s own level_strength (0-1,
    # more historical touches at the level = more meaningfully defended).
    support_score = 17.5 * calculate_support_resistance(candles, cfg["support_resistance"])["level_strength"] \
        if support_holding else 0.0

    score = accel_score + compression_score + volume_score + support_score
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
