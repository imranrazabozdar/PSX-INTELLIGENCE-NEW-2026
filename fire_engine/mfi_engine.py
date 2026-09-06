"""mfi_engine.py — Phase 4: Money Flow Index(14) and its derivatives,
calculated from raw OHLCV (never trusted from imported data, per the
project's own "calculate MFI from raw OHLCV, don't trust imported MFI"
rule -- compare_mfi() below is how a caller checks an imported value
against this one, not a substitute for computing it).

Standard MFI: typical price = (H+L+C)/3; money flow = typical price *
volume; positive/negative money flow sums over a rolling `length`-period
window based on whether typical price rose or fell vs the prior bar;
MFI = 100 - 100/(1 + positive_sum/negative_sum).

IMPORTANT (per the project's own explicit instruction): MFI rising while
volume is thin is a real PRE-FIRE signal, not noise -- nothing in this
module discounts or filters out low-volume MFI moves.
"""


def calculate_mfi(candles: list, length: int = 14) -> list:
    """candles: list of dicts with high/low/close/volume, oldest first.
    Returns a list the same length as `candles`, with None for the first
    `length` bars (insufficient history)."""
    n = len(candles)
    if n == 0:
        return []

    typical_price = [(c["high"] + c["low"] + c["close"]) / 3 for c in candles]
    money_flow = [typical_price[i] * candles[i]["volume"] for i in range(n)]

    pos_mf = [0.0] * n
    neg_mf = [0.0] * n
    for i in range(1, n):
        if typical_price[i] > typical_price[i - 1]:
            pos_mf[i] = money_flow[i]
        elif typical_price[i] < typical_price[i - 1]:
            neg_mf[i] = money_flow[i]
        # unchanged typical price contributes to neither sum

    mfi = [None] * n
    for i in range(length, n):
        pos_sum = sum(pos_mf[i - length + 1: i + 1])
        neg_sum = sum(neg_mf[i - length + 1: i + 1])
        if neg_sum == 0:
            mfi[i] = 100.0 if pos_sum > 0 else 50.0
        else:
            ratio = pos_sum / neg_sum
            mfi[i] = 100 - (100 / (1 + ratio))
    return mfi


def _slope(values: list) -> float:
    """Simple linear-regression slope (rate of change per step) over
    `values` (index = x, value = y). Returns 0.0 if fewer than 2 usable
    points."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    n = len(pts)
    if n < 2:
        return 0.0
    sum_x = sum(p[0] for p in pts)
    sum_y = sum(p[1] for p in pts)
    sum_xy = sum(p[0] * p[1] for p in pts)
    sum_xx = sum(p[0] * p[0] for p in pts)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def calculate_mfi_derivatives(mfi_series: list) -> dict:
    """Derivatives as of the LAST bar in mfi_series (the "current" bar a
    live/daily scan is evaluating). Returns:
    {delta_5, delta_15, delta_30, delta_60, slope, acceleration, direction,
     persistence}
    Any delta/slope needing more history than is available returns None
    for that key rather than a misleading partial number."""
    n = len(mfi_series)
    if n == 0 or mfi_series[-1] is None:
        return {
            "delta_5": None, "delta_15": None, "delta_30": None, "delta_60": None,
            "slope": None, "acceleration": None, "direction": 0, "persistence": 0,
        }

    current = mfi_series[-1]

    def delta(window):
        if n <= window or mfi_series[-1 - window] is None:
            return None
        return current - mfi_series[-1 - window]

    delta_5 = delta(5)
    delta_15 = delta(15)
    delta_30 = delta(30)
    delta_60 = delta(60)

    recent_window = [v for v in mfi_series[-15:] if v is not None]
    slope = _slope(recent_window) if len(recent_window) >= 2 else None

    # acceleration: second derivative -- slope of the second half of the
    # window vs. the first half, over the same 15-bar recent window.
    acceleration = None
    if len(recent_window) >= 6:
        mid = len(recent_window) // 2
        slope_first = _slope(recent_window[:mid])
        slope_second = _slope(recent_window[mid:])
        acceleration = slope_second - slope_first

    direction = 0
    if delta_5 is not None:
        direction = 1 if delta_5 > 0 else (-1 if delta_5 < 0 else 0)

    persistence = 0
    for i in range(n - 1, 0, -1):
        a, b = mfi_series[i], mfi_series[i - 1]
        if a is None or b is None:
            break
        d = a - b
        if direction == 1 and d > 0:
            persistence += 1
        elif direction == -1 and d < 0:
            persistence += 1
        else:
            break

    return {
        "delta_5": delta_5, "delta_15": delta_15, "delta_30": delta_30, "delta_60": delta_60,
        "slope": slope, "acceleration": acceleration, "direction": direction,
        "persistence": persistence,
    }


def compare_mfi(calculated: list, imported: list, tolerance: float = 1.0) -> dict:
    """Compare this module's calculated MFI against an imported MFI series
    of the same length (e.g. from a vendor feed). Returns a discrepancy
    report -- does NOT decide which one to use; that's a config choice
    made by the caller (see mfi_engine's module docstring)."""
    if len(calculated) != len(imported):
        return {"comparable": False, "reason": f"length mismatch: {len(calculated)} vs {len(imported)}"}
    diffs = []
    for i, (c, imp) in enumerate(zip(calculated, imported)):
        if c is None or imp is None:
            continue
        d = abs(c - imp)
        if d > tolerance:
            diffs.append({"index": i, "calculated": c, "imported": imp, "diff": d})
    return {
        "comparable": True, "num_compared": sum(1 for c, i in zip(calculated, imported) if c is not None and i is not None),
        "num_discrepancies": len(diffs), "discrepancies": diffs[:50],  # cap for sanity
        "max_discrepancy": max((d["diff"] for d in diffs), default=0.0),
    }
