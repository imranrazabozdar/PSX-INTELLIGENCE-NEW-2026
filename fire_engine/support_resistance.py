"""support.py — Phase 8 (support/resistance detection). Descriptive
levels from recent candle history, not a causal/live trading signal.
"""


def calculate_support_resistance(candles: list, cfg: dict) -> dict:
    """candles: full history available, oldest first.
    cfg is the `support_resistance` section of fire_config.yaml
    (lookback_candles).

    Returns:
    {support_primary, support_secondary, resistance_primary,
     resistance_secondary, breakout_above, breakdown_below, level_strength}
    """
    lookback = cfg["lookback_candles"]
    window = candles[-lookback:] if len(candles) >= lookback else candles
    if len(window) < 2:
        return {
            "support_primary": None, "support_secondary": None,
            "resistance_primary": None, "resistance_secondary": None,
            "breakout_above": False, "breakdown_below": False, "level_strength": 0.0,
        }

    lows = sorted(c["low"] for c in window)
    highs = sorted((c["high"] for c in window), reverse=True)

    support_primary = lows[0]
    support_secondary = lows[1] if len(lows) > 1 else lows[0]
    resistance_primary = highs[0]
    resistance_secondary = highs[1] if len(highs) > 1 else highs[0]

    last_close = window[-1]["close"]
    breakout_above = last_close > resistance_primary
    breakdown_below = last_close < support_primary

    # level_strength: how many bars in the window actually touched (within
    # 0.5%) the primary level -- more touches = a more meaningfully
    # defended level, confidence capped at 1.0.
    def touch_count(level):
        if level == 0:
            return 0
        return sum(
            1 for c in window
            if abs(c["low"] - level) / level <= 0.005 or abs(c["high"] - level) / level <= 0.005
        )

    touches = touch_count(support_primary) + touch_count(resistance_primary)
    level_strength = min(1.0, touches / 6)  # 6+ touches across both levels = full confidence

    return {
        "support_primary": support_primary, "support_secondary": support_secondary,
        "resistance_primary": resistance_primary, "resistance_secondary": resistance_secondary,
        "breakout_above": breakout_above, "breakdown_below": breakdown_below,
        "level_strength": round(level_strength, 3),
    }


def is_support_holding(candles: list, cfg: dict) -> bool:
    """Whether the most recent candle's low stayed at/above the support
    level computed from the candles BEFORE it (no new low made)."""
    if len(candles) < 2:
        return True
    levels = calculate_support_resistance(candles[:-1], cfg)
    support = levels["support_primary"]
    if support is None:
        return True
    return candles[-1]["low"] >= support
