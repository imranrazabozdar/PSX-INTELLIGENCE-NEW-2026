"""scoring.py — Phase 12: 0-100 FIRE strength score, combining every
detector's output into one composite. This is a STRENGTH score, not a
probability -- nothing here or downstream claims odds of profit, per the
project's own explicit rule.

Component scores are each normalized to [0, 1] before being multiplied by
their configured weight (fire_scoring.weights in fire_config.yaml, which
must sum to 100 -- enforced by config.load_config()).
"""


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def calculate_fire_score(mfi_acceleration: float, mfi_persistence: int,
                          price_compression_active: bool, absorption_score: float,
                          support_strength: float, volume_expansion: float,
                          breakout_confirmed: bool, cfg: dict) -> dict:
    """cfg: whole loaded fire_config dict (needs fire_scoring, mfi).

    Normalization choices (each mapped to [0,1] before weighting):
      mfi_acceleration:      accel / mfi.acceleration_threshold_15m, capped at 1
      mfi_persistence:       persistence / 10 candles, capped at 1
      price_compression:     1.0 if compression currently active, else 0.0
      volume_absorption:     absorption_score (already 0-100) / 100
      support_structure:     support_strength (already 0-1 from
                              support_resistance.level_strength)
      volume_expansion:      expansion_ratio / fire.min_relative_volume_expansion,
                              capped at 1 (reads fire_config's fire section
                              via the caller passing volume_expansion already
                              normalized against that threshold upstream is
                              NOT required -- this function does the ratio
                              itself using volume.abnormal_rv as the "full
                              marks" anchor, documented below)
      breakout_confirmation:  1.0 if confirmed, else 0.0
    """
    weights = cfg["fire_scoring"]["weights"]
    thresholds = cfg["fire_scoring"]["thresholds"]

    mfi_accel_norm = _clamp01(mfi_acceleration / cfg["mfi"]["acceleration_threshold_15m"]) if cfg["mfi"]["acceleration_threshold_15m"] else 0.0
    mfi_persist_norm = _clamp01(mfi_persistence / 10)
    compression_norm = 1.0 if price_compression_active else 0.0
    absorption_norm = _clamp01(absorption_score / 100)
    support_norm = _clamp01(support_strength)
    # volume_expansion (an RV ratio) earns full marks once it reaches
    # volume.abnormal_rv (2.0x by default) -- consistent with that being
    # the "ABNORMAL" classification boundary elsewhere in the system.
    expansion_norm = _clamp01(volume_expansion / cfg["volume"]["abnormal_rv"]) if cfg["volume"]["abnormal_rv"] else 0.0
    breakout_norm = 1.0 if breakout_confirmed else 0.0

    component_scores = {
        "mfi_acceleration": round(mfi_accel_norm * weights["mfi_acceleration"], 2),
        "mfi_persistence": round(mfi_persist_norm * weights["mfi_persistence"], 2),
        "price_compression": round(compression_norm * weights["price_compression"], 2),
        "volume_absorption": round(absorption_norm * weights["volume_absorption"], 2),
        "support_structure": round(support_norm * weights["support_structure"], 2),
        "volume_expansion": round(expansion_norm * weights["volume_expansion"], 2),
        "breakout_confirmation": round(breakout_norm * weights["breakout_confirmation"], 2),
    }
    total_score = round(sum(component_scores.values()))

    if total_score >= thresholds["extreme_fire"]:
        rating = "EXTREME_FIRE"
    elif total_score >= thresholds["strong_fire"]:
        rating = "STRONG_FIRE"
    elif total_score >= thresholds["prefire"]:
        rating = "PRE_FIRE"
    elif total_score >= thresholds["watch"]:
        rating = "WATCH"
    else:
        rating = "NO_SETUP"

    # confidence: how many of the 7 components contributed non-trivially
    # (>10% of their own max) -- a score built from many partial signals
    # is read as less certain than one where most components fired fully.
    contributing = sum(
        1 for k, v in component_scores.items() if v > 0.1 * weights[k]
    )
    confidence = round(contributing / len(component_scores), 2)

    return {
        "total_score": total_score, "component_breakdown": component_scores,
        "rating": rating, "confidence": confidence,
    }
