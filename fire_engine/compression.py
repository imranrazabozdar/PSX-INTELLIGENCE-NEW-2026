"""compression.py — Phase 7: price compression (stasis) detection.

Two methods, both configurable via the `compression` section of
fire_config.yaml:
  Method 1 (simple):   |close - open| / open * 100 <= price_change_pct
  Method 2 (adaptive):  current ATR <= adaptive_atr_ratio * 30-day ATR

CRITICAL (per project rule): compression alongside a RISING MFI is a
PRE-FIRE indicator, not filtered out here -- this module only detects
compression; pre_fire.py is what combines it with MFI acceleration.
"""


def _true_range(candles: list, i: int) -> float:
    if i == 0:
        return candles[i]["high"] - candles[i]["low"]
    prev_close = candles[i - 1]["close"]
    return max(
        candles[i]["high"] - candles[i]["low"],
        abs(candles[i]["high"] - prev_close),
        abs(candles[i]["low"] - prev_close),
    )


def calculate_atr(candles: list, period: int) -> list:
    """Wilder-smoothed ATR. Returns a list same length as candles, None
    for the first `period` bars."""
    n = len(candles)
    trs = [_true_range(candles, i) for i in range(n)]
    atr = [None] * n
    if n <= period:
        return atr
    atr[period] = sum(trs[1:period + 1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + trs[i]) / period
    return atr


def _severity(range_pct: float, cfg: dict) -> str:
    st = cfg["severity_thresholds"]
    if range_pct <= st["severe"]:
        return "SEVERE"
    if range_pct <= st["moderate"]:
        return "MODERATE"
    if range_pct <= st["mild"]:
        return "MILD"
    return "NONE"


def detect_price_compression(candles: list, cfg: dict, atr_30d: list = None) -> list:
    """candles: full session's (or multi-day) candles, oldest first.
    cfg is the `compression` section of fire_config.yaml.
    atr_30d: optional precomputed 30-calendar-day ATR series aligned to
    `candles` (for Method 2); if omitted, only Method 1 is evaluated.

    Returns a list of compression period dicts, one per qualifying
    lookback_minutes-wide window ending at each candle (Method 1),
    merged with Method 2's flag where atr_30d is supplied:
    {start_time, end_time, duration_minutes, price_open, price_close,
     price_high, price_low, price_range_pct, compression_severity, method}
    """
    lookback = cfg["lookback_minutes"]
    threshold_pct = cfg["price_change_pct"]
    n = len(candles)
    results = []

    for i in range(lookback - 1, n):
        window = candles[i - lookback + 1: i + 1]
        o = window[0]["open"]
        cl = window[-1]["close"]
        h = max(c["high"] for c in window)
        l = min(c["low"] for c in window)
        if o == 0:
            continue
        range_pct = abs(cl - o) / o * 100
        method1_flag = range_pct <= threshold_pct

        method2_flag = False
        if atr_30d is not None and atr_30d[i] is not None:
            current_atr = calculate_atr(window, min(14, lookback - 1))
            cur = next((v for v in reversed(current_atr) if v is not None), None)
            if cur is not None and atr_30d[i] > 0:
                method2_flag = cur <= cfg["adaptive_atr_ratio"] * atr_30d[i]

        if method1_flag or method2_flag:
            results.append({
                "start_time": window[0]["datetime"], "end_time": window[-1]["datetime"],
                "duration_minutes": lookback,
                "price_open": o, "price_close": cl, "price_high": h, "price_low": l,
                "price_range_pct": round(range_pct, 4),
                "compression_severity": _severity(range_pct, cfg),
                "method": "simple" if method1_flag and not method2_flag else
                          ("adaptive" if method2_flag and not method1_flag else "both"),
            })

    return results


def is_compression_active(candles: list, cfg: dict, atr_30d: list = None) -> bool:
    """Whether the LAST `lookback_minutes` candles currently qualify as
    compressed -- the check pre_fire.py needs (a single yes/no as of the
    latest bar, not the full historical list)."""
    lookback = cfg["lookback_minutes"]
    if len(candles) < lookback:
        return False
    periods = detect_price_compression(candles[-lookback:], cfg, atr_30d[-lookback:] if atr_30d else None)
    return bool(periods) and periods[-1]["end_time"] == candles[-1]["datetime"]
