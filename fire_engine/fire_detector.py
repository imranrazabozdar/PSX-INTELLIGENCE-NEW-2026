"""fire_detector.py — Phase 11: FIRE confirmation.

FIRE (ALL must hold):
  1. PRE-FIRE existed earlier this session (or as a carried-over
     near-close setup -- session_transition.py handles that link)
  2. Volume EXPANDS (RV >= min_relative_volume_expansion)
  3. Price BREAKS OUT (closes above the compression high established
     before PRE-FIRE)
  4. MFI remains SUPPORTIVE (>= min_mfi_for_confirmation, or still rising)
  5. The breakout hasn't been rejected within rejection_check_minutes
     (price hasn't fallen back below the breakout level since)
"""


def detect_fire(candles: list, mfi_series: list, relative_volume: float,
                 prefire_history: list, cfg: dict) -> dict:
    """candles/mfi_series: full history up to "now", oldest first.
    relative_volume: current bar's RV.
    prefire_history: list of prior detect_pre_fire() results for this
    session (or including a carried-over near-close one), each with
    'prefire_detected' and 'timestamp' plus the compression window it was
    computed from -- this function looks for the most recent one with
    prefire_detected=True to establish the breakout reference level.
    cfg: whole loaded fire_config dict.

    Returns:
    {fire_detected, fire_score (0 if not detected, else provisional),
     breakout_confirmed, volume_expansion, mfi_status, rejection_risk,
     timestamp, pre_fire_time}
    """
    fire_cfg = cfg["fire"]
    if not candles:
        return _empty_result()

    timestamp = candles[-1]["datetime"]
    prior_prefire = next((p for p in reversed(prefire_history) if p.get("prefire_detected")), None)
    if prior_prefire is None:
        return _empty_result(timestamp)

    pre_fire_time = prior_prefire["timestamp"]

    # Compression high: the highest high among candles up to and including
    # the PRE-FIRE bar -- the breakout reference level.
    pre_fire_idx = next(
        (i for i, c in enumerate(candles) if c["datetime"] == pre_fire_time), None
    )
    if pre_fire_idx is None:
        return _empty_result(timestamp, pre_fire_time)
    compression_high = max(c["high"] for c in candles[:pre_fire_idx + 1])

    current_close = candles[-1]["close"]
    breakout_confirmed = current_close > compression_high

    volume_expansion = relative_volume if relative_volume is not None else 0.0
    volume_ok = volume_expansion >= fire_cfg["min_relative_volume_expansion"]

    current_mfi = mfi_series[-1] if mfi_series else None
    prior_mfi = mfi_series[pre_fire_idx] if pre_fire_idx < len(mfi_series) else None
    mfi_supportive = current_mfi is not None and (
        current_mfi >= fire_cfg["min_mfi_for_confirmation"]
        or (prior_mfi is not None and current_mfi > prior_mfi)
    )
    mfi_status = "SUPPORTIVE" if mfi_supportive else "NOT_SUPPORTIVE"

    # Rejection check: has price closed back below compression_high at any
    # point in the rejection_check_minutes bars AFTER the breakout was
    # first confirmed? Only meaningful once we know when breakout first
    # occurred; approximate using the bars since pre_fire_idx.
    rejection_risk = False
    check_window = candles[pre_fire_idx + 1:]
    breakout_idx_in_window = next(
        (i for i, c in enumerate(check_window) if c["close"] > compression_high), None
    )
    if breakout_idx_in_window is not None:
        horizon = check_window[breakout_idx_in_window + 1: breakout_idx_in_window + 1 + fire_cfg["rejection_check_minutes"]]
        rejection_risk = any(c["close"] <= compression_high for c in horizon)

    detected = breakout_confirmed and volume_ok and mfi_supportive and not rejection_risk

    return {
        "fire_detected": detected,
        "breakout_confirmed": breakout_confirmed,
        "volume_expansion": round(volume_expansion, 3),
        "mfi_status": mfi_status,
        "rejection_risk": rejection_risk,
        "timestamp": timestamp,
        "pre_fire_time": pre_fire_time,
        "compression_high": compression_high,
    }


def _empty_result(timestamp=None, pre_fire_time=None):
    return {
        "fire_detected": False, "breakout_confirmed": False, "volume_expansion": 0.0,
        "mfi_status": "UNKNOWN", "rejection_risk": False, "timestamp": timestamp,
        "pre_fire_time": pre_fire_time, "compression_high": None,
    }
