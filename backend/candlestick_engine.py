"""candlestick_engine.py — the full Steve Nison candlestick set (STEP 16),
detected walk-forward at any bar index so the same detector serves both live
reads (app.py, at the last bar) and historical backtesting (backtest_engine.py,
at every past bar) with identical logic — no drift between what's detected
live and what's backtested.

Single-candle shapes (Hammer/Hanging Man, Inverted Hammer/Shooting Star) are
directional only in context: the same geometry is bullish after a decline and
bearish after an advance, per Nison. `_trend_context()` is a simple trailing
% move, not a Wyckoff-grade trend read — good enough to disambiguate the
shape's name, not meant to replace market_structure.py's HH/HL structure.

Multiple patterns can legitimately fire on the same bar (e.g. a Marubozu that
is also part of a Three White Soldiers run) — `detect_at` returns a list, not
a single label, matching how real chart reading works.
"""


def _trend_context(a, i, lookback=10):
    if i < lookback:
        return "unknown"
    start, end = a[i - lookback]["close"], a[i - 1]["close"]
    if not start:
        return "unknown"
    chg = (end - start) / start
    if chg > 0.02:
        return "up"
    if chg < -0.02:
        return "down"
    return "flat"


def _body(x):
    return abs(x["close"] - x["open"])


def _rng(x):
    return max(0.0001, x["high"] - x["low"])


def detect_at(a, i):
    """All Nison patterns matching bar `i`, using only a[0..i] (no look-ahead)."""
    out = []
    if i < 0 or i >= len(a):
        return out
    x = a[i]
    body, rng = _body(x), _rng(x)
    upper = x["high"] - max(x["open"], x["close"])
    lower = min(x["open"], x["close"]) - x["low"]
    bull = x["close"] > x["open"]
    trend = _trend_context(a, i)

    # ---- single-candle ----
    if body / rng < 0.05:
        if upper > rng * 0.6 and lower < rng * 0.1:
            out.append("Gravestone Doji")
        elif lower > rng * 0.6 and upper < rng * 0.1:
            out.append("Dragonfly Doji")
        elif upper > rng * 0.35 and lower > rng * 0.35:
            out.append("Long-Legged Doji")
        else:
            out.append("Doji")
    elif body / rng > 0.9:
        out.append("Marubozu")
    elif lower > 2 * max(body, .0001) and upper < body * 0.5:
        if trend == "down":
            out.append("Hammer")
        elif trend == "up":
            out.append("Hanging Man")
    elif upper > 2 * max(body, .0001) and lower < body * 0.5:
        if trend == "down":
            out.append("Inverted Hammer")
        elif trend == "up":
            out.append("Shooting Star")
    elif body / rng < 0.35 and upper > body * 0.4 and lower > body * 0.4:
        out.append("Spinning Top")

    # ---- two-candle ----
    if i >= 1:
        p = a[i - 1]
        p_bull = p["close"] > p["open"]
        p_body = _body(p)
        if bull and not p_bull and x["open"] <= p["close"] and x["close"] >= p["open"]:
            out.append("Bullish engulfing")  # exact app.py naming for backward compatibility
        if not bull and p_bull and x["open"] >= p["close"] and x["close"] <= p["open"]:
            out.append("Bearish engulfing")
        pmid = (p["open"] + p["close"]) / 2
        if not p_bull and bull and x["open"] < p["low"] and pmid < x["close"] < p["open"]:
            out.append("Piercing Pattern")
        if p_bull and not bull and x["open"] > p["close"] and p["open"] < x["close"] < pmid:
            out.append("Dark Cloud Cover")
        if p_body > 0 and body < p_body and max(x["open"], x["close"]) < max(p["open"], p["close"]) \
                and min(x["open"], x["close"]) > min(p["open"], p["close"]):
            out.append("Harami Cross" if body / rng < 0.05 else "Harami")
        if p["high"] and abs(x["high"] - p["high"]) / p["high"] < 0.003:
            out.append("Tweezer Top")
        if p["low"] and abs(x["low"] - p["low"]) / p["low"] < 0.003:
            out.append("Tweezer Bottom")

    # ---- three-candle ----
    if i >= 2:
        p1, p2 = a[i - 1], a[i - 2]
        p1_body, p2_body = _body(p1), _body(p2)
        p2_bull = p2["close"] > p2["open"]
        p1_rng = _rng(p1)
        if not p2_bull and p1_body < p2_body * 0.4 and bull and p2_body and x["close"] > (p2["open"] + p2["close"]) / 2:
            out.append("Morning Doji Star" if p1_body / p1_rng < 0.1 else "Morning Star")
        if p2_bull and p1_body < p2_body * 0.4 and not bull and p2_body and x["close"] < (p2["open"] + p2["close"]) / 2:
            out.append("Evening Doji Star" if p1_body / p1_rng < 0.1 else "Evening Star")
        if (p2["close"] > p2["open"] and p1["close"] > p1["open"] and bull
                and p1["close"] > p2["close"] and x["close"] > p1["close"]
                and p1["open"] > p2["open"] and x["open"] > p1["open"]):
            out.append("Three White Soldiers")
        if (p2["close"] < p2["open"] and p1["close"] < p1["open"] and not bull
                and p1["close"] < p2["close"] and x["close"] < p1["close"]
                and p1["open"] < p2["open"] and x["open"] < p1["open"]):
            out.append("Three Black Crows")
        if p2_body and p1_body < p2_body * 0.6 and max(p1["open"], p1["close"]) < max(p2["open"], p2["close"]) \
                and min(p1["open"], p1["close"]) > min(p2["open"], p2["close"]):
            if not p2_bull and x["close"] > p2["open"]:
                out.append("Three Inside Up")
            if p2_bull and x["close"] < p2["open"]:
                out.append("Three Inside Down")

    # ---- five-candle ----
    if i >= 4:
        c0, c1, c2, c3, c4 = a[i - 4], a[i - 3], a[i - 2], a[i - 1], a[i]
        c0_bull, c4_bull = c0["close"] > c0["open"], c4["close"] > c4["open"]
        c0_body = _body(c0)
        if c0_body:
            mids_small = all(_body(c) < c0_body * 0.6 for c in (c1, c2, c3))
            mids_inside = all(min(c0["open"], c0["close"]) <= min(c["open"], c["close"])
                               and max(c["open"], c["close"]) <= max(c0["open"], c0["close"])
                               for c in (c1, c2, c3))
            if c0_bull and c4_bull and mids_small and mids_inside and c4["close"] > c0["close"]:
                out.append("Rising Three Methods")
            if not c0_bull and not c4_bull and mids_small and mids_inside and c4["close"] < c0["close"]:
                out.append("Falling Three Methods")

    return out


BULLISH_PATTERNS = {
    "Hammer", "Inverted Hammer", "Dragonfly Doji", "Bullish engulfing", "Piercing Pattern",
    "Morning Star", "Morning Doji Star", "Three White Soldiers", "Three Inside Up",
    "Rising Three Methods", "Tweezer Bottom",
}
BEARISH_PATTERNS = {
    "Hanging Man", "Shooting Star", "Gravestone Doji", "Bearish engulfing", "Dark Cloud Cover",
    "Evening Star", "Evening Doji Star", "Three Black Crows", "Three Inside Down",
    "Falling Three Methods", "Tweezer Top",
}


def bias(pattern):
    if pattern in BULLISH_PATTERNS:
        return "bullish"
    if pattern in BEARISH_PATTERNS:
        return "bearish"
    return "neutral"  # Doji variants, Spinning Top, Marubozu (direction-neutral by itself), Harami (context-dependent)


def context_score(a, i, pattern, support=None, resistance=None, avg_volume=None):
    """STEP 17: never score a candle from geometry alone. Combines pattern
    quality (clean vs marginal geometry), location quality (distance to the
    nearest relevant support/resistance), trend context (was there a real
    prior move to reverse/continue), and volume support — the same four
    inputs the source framework's worked example (25 -> 50 -> 70 -> 90) uses.
    0-100, an analytical scoring convention, never a probability."""
    if i < 0 or i >= len(a):
        return {"score": 0, "breakdown": {}}
    x = a[i]
    b = bias(pattern)

    body = abs(x["close"] - x["open"])
    rng = max(0.0001, x["high"] - x["low"])
    pattern_quality = min(25, 25 * min(1.0, body / rng * 3)) if pattern != "Doji" else 15

    location_quality = 0
    level = support if b == "bullish" else resistance if b == "bearish" else None
    if level and level > 0:
        dist_pct = abs(x["close"] - level) / level * 100
        location_quality = max(0, 25 - dist_pct * 5)  # within ~1% of the level = full marks

    trend = _trend_context(a, i)
    reversal_pattern = b in ("bullish", "bearish")
    trend_context_score = 0
    if reversal_pattern:
        if (b == "bullish" and trend == "down") or (b == "bearish" and trend == "up"):
            trend_context_score = 20  # pattern reverses the prevailing trend — the classic Nison setup
        elif trend == "flat":
            trend_context_score = 8

    volume_support = 0
    if avg_volume:
        vr = x["volume"] / avg_volume if avg_volume else 0
        volume_support = min(15, 15 * min(1.0, vr / 1.5))

    total = round(pattern_quality + location_quality + trend_context_score + volume_support)
    return {"score": min(100, total),
            "breakdown": {"pattern_quality": round(pattern_quality), "location_quality": round(location_quality),
                          "trend_context": trend_context_score, "volume_support": round(volume_support)},
            "note": "Analytical scoring convention (pattern+location+trend+volume), not a guaranteed "
                    "probability — follow-through still required for confirmation."}


def confirmation_status(a, i, pattern):
    """STEP 18: did the bars AFTER the pattern actually confirm it — close
    higher/break the pattern's high (bullish) or the mirror (bearish), hold
    the pattern's low/high? If there are no bars after `i` yet (a pattern on
    the most recent live bar), the honest answer is Unconfirmed, not a guess."""
    b = bias(pattern)
    if b == "neutral":
        return {"status": "N/A", "reason": "Direction-neutral pattern (Doji/Spinning Top/Marubozu by itself)."}
    after = a[i + 1:]
    if not after:
        return {"status": "Unconfirmed", "reason": "No bars yet after this pattern — check again next session."}
    x = a[i]
    checks = []
    if b == "bullish":
        closed_higher = any(nb["close"] > x["close"] for nb in after[:3])
        broke_high = any(nb["close"] > x["high"] for nb in after[:3])
        held_low = all(nb["low"] >= x["low"] * 0.99 for nb in after[:3])
        checks = [closed_higher, broke_high, held_low]
    else:
        closed_higher = any(nb["close"] < x["close"] for nb in after[:3])
        broke_high = any(nb["close"] < x["low"] for nb in after[:3])
        held_low = all(nb["high"] <= x["high"] * 1.01 for nb in after[:3])
        checks = [closed_higher, broke_high, held_low]
    passed = sum(checks)
    if passed == 3:
        status = "Confirmed"
    elif passed >= 1:
        status = "Partially Confirmed"
    else:
        status = "Failed"
    return {"status": status, "checks_passed": f"{passed}/3", "bars_since": len(after[:3])}
