"""absorption.py — Phase 8: bullish/bearish absorption detection.

Bullish absorption: elevated/abnormal volume + small price displacement +
support holding + MFI rising-or-high. Bearish absorption: same volume
condition + price can't advance + resistance holding + MFI falling-or-low.

This is structural evidence of possible accumulation/distribution, NOT a
certainty and NOT a probability claim -- per the project's own explicit
rule, nothing here or downstream should be read as "this WILL move."
"""
from fire_engine.support_resistance import calculate_support_resistance, is_support_holding


def _price_displacement_pct(candles: list, lookback_minutes: int) -> float:
    window = candles[-lookback_minutes:]
    o = window[0]["open"]
    cl = window[-1]["close"]
    return abs(cl - o) / o * 100 if o else 0.0


def detect_bullish_absorption(candles: list, relative_volume: float, mfi_series: list,
                               cfg: dict, sr_cfg: dict) -> dict:
    """candles: full history up to and including "now", oldest first.
    relative_volume: this bar's RV (from volume_engine.calculate_relative_volume).
    mfi_series: full MFI series aligned to candles (from mfi_engine.calculate_mfi).
    cfg: `absorption` section of fire_config.yaml. sr_cfg: `support_resistance` section.

    Returns {absorption_detected, absorption_type, absorption_score (0-100),
    volume_condition, price_compression_pct, mfi_trend}.
    """
    lookback = cfg["lookback_minutes"]
    if len(candles) < lookback or relative_volume is None:
        return _no_absorption()

    displacement_pct = _price_displacement_pct(candles, lookback)
    volume_ok = relative_volume >= cfg["min_relative_volume"]
    displacement_ok = displacement_pct <= cfg["max_price_displacement_pct"]
    support_holding = is_support_holding(candles, sr_cfg)

    current_mfi = mfi_series[-1] if mfi_series else None
    prior_mfi = mfi_series[-lookback] if len(mfi_series) >= lookback else None
    mfi_rising = current_mfi is not None and (
        current_mfi >= 50 or (prior_mfi is not None and current_mfi > prior_mfi)
    )
    mfi_trend = "RISING" if (current_mfi is not None and prior_mfi is not None and current_mfi > prior_mfi) else (
        "HIGH" if (current_mfi is not None and current_mfi >= 50) else "NEUTRAL_OR_LOW"
    )

    detected = volume_ok and displacement_ok and support_holding and mfi_rising
    score = 0.0
    if volume_ok:
        score += 30
    if displacement_ok:
        score += 30
    if support_holding:
        score += 20
    if mfi_rising:
        score += 20

    return {
        "absorption_detected": detected,
        "absorption_type": "BULLISH" if detected else "NONE",
        "absorption_score": round(score, 1),
        "volume_condition": "ELEVATED_OR_ABOVE" if volume_ok else "NORMAL_OR_BELOW",
        "price_compression_pct": round(displacement_pct, 4),
        "mfi_trend": mfi_trend,
    }


def detect_bearish_absorption(candles: list, relative_volume: float, mfi_series: list,
                               cfg: dict, sr_cfg: dict) -> dict:
    lookback = cfg["lookback_minutes"]
    if len(candles) < lookback or relative_volume is None:
        return _no_absorption()

    displacement_pct = _price_displacement_pct(candles, lookback)
    volume_ok = relative_volume >= cfg["min_relative_volume"]
    displacement_ok = displacement_pct <= cfg["max_price_displacement_pct"]

    levels = calculate_support_resistance(candles[:-1], sr_cfg)
    resistance = levels["resistance_primary"]
    resistance_holding = resistance is not None and candles[-1]["high"] <= resistance

    current_mfi = mfi_series[-1] if mfi_series else None
    prior_mfi = mfi_series[-lookback] if len(mfi_series) >= lookback else None
    mfi_falling = current_mfi is not None and (
        current_mfi <= 50 or (prior_mfi is not None and current_mfi < prior_mfi)
    )
    mfi_trend = "FALLING" if (current_mfi is not None and prior_mfi is not None and current_mfi < prior_mfi) else (
        "LOW" if (current_mfi is not None and current_mfi <= 50) else "NEUTRAL_OR_HIGH"
    )

    detected = volume_ok and displacement_ok and resistance_holding and mfi_falling
    score = 0.0
    if volume_ok:
        score += 30
    if displacement_ok:
        score += 30
    if resistance_holding:
        score += 20
    if mfi_falling:
        score += 20

    return {
        "absorption_detected": detected,
        "absorption_type": "BEARISH" if detected else "NONE",
        "absorption_score": round(score, 1),
        "volume_condition": "ELEVATED_OR_ABOVE" if volume_ok else "NORMAL_OR_BELOW",
        "price_compression_pct": round(displacement_pct, 4),
        "mfi_trend": mfi_trend,
    }


def _no_absorption():
    return {
        "absorption_detected": False, "absorption_type": "NONE", "absorption_score": 0.0,
        "volume_condition": "UNKNOWN", "price_compression_pct": None, "mfi_trend": "UNKNOWN",
    }
