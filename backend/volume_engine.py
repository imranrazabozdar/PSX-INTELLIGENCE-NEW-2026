"""Volume Intelligence Engine
Detects abnormal volume activity and possible accumulation/distribution behaviour.
No prediction, only evidence-based alerts.
"""

from statistics import mean


def volume_analysis(bars):
    """
    bars = list of Candle objects
    Candle should contain:
    o = open
    h = high
    l = low
    c = close
    v = volume
    """

    if len(bars) < 20:
        return {
            "status": "insufficient_history",
            "message": "Need at least 20 volume observations"
        }

    volumes = [x.v for x in bars]

    avg20 = mean(volumes[-20:])
    current = volumes[-1]

    ratio = current / max(avg20, 1)

    if ratio >= 3:
        signal = "EXTREME_VOLUME"
        alert = "Possible institutional activity - investigate"
    elif ratio >= 1.8:
        signal = "HIGH_VOLUME"
        alert = "Unusual volume expansion detected"
    elif ratio <= 0.5:
        signal = "LOW_ACTIVITY"
        alert = "Below average participation"
    else:
        signal = "NORMAL"
        alert = "Normal volume behaviour"

    price_change = 0

    if len(bars) >= 2:
        previous = bars[-2].c
        if previous:
            price_change = ((bars[-1].c - previous) / previous) * 100

    if ratio >= 1.8 and price_change > 0:
        behaviour = "Accumulation candidate"
    elif ratio >= 1.8 and price_change < 0:
        behaviour = "Distribution candidate"
    else:
        behaviour = "No clear accumulation/distribution evidence"

    return {
        "current_volume": current,
        "average_20_volume": round(avg20, 2),
        "volume_ratio": round(ratio, 2),
        "signal": signal,
        "alert": alert,
        "price_change_percent": round(price_change, 2),
        "behaviour": behaviour,
        "note": "Volume signals require confirmation from price structure and fundamentals."
    }
