"""price_action_engine.py — Al Brooks bar-by-bar classification, breakout
quality, and pullback quality (STEPS 19-22 of the source framework).

Every bar is classified using only itself and its immediate neighbors — no
look-ahead. Breakout/pullback quality are scored 0-100 from concrete, cited
inputs (bar size, volume, close position, follow-through), the same
"analytical scoring convention, not a guaranteed probability" the source
framework insists on for candle-context scoring.
"""


def _avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def classify_bar(a, i):
    """One bar's Al Brooks classification, using a[i-1] and a[i+1] only when
    they exist (i.e. `i+1` is available for backtesting on closed history,
    never for the live/last bar — callers pass i=len(a)-1 and just get no
    'reversal' label for the still-open-ended last bar, which is correct)."""
    if i < 0 or i >= len(a):
        return None
    x = a[i]
    body = abs(x["close"] - x["open"])
    rng = max(0.0001, x["high"] - x["low"])
    bull = x["close"] > x["open"]

    labels = []
    if body / rng < 0.1:
        labels.append("doji")
    elif body / rng > 0.6:
        labels.append("bull trend bar" if bull else "bear trend bar")

    if i >= 1:
        p = a[i - 1]
        if x["high"] <= p["high"] and x["low"] >= p["low"]:
            labels.append("inside bar")
        elif x["high"] >= p["high"] and x["low"] <= p["low"]:
            labels.append("outside bar")

    return {"date": x["trade_date"], "labels": labels or ["neutral bar"],
            "close_position_in_range": round((x["close"] - x["low"]) / rng, 2),
            "body_pct_of_range": round(body / rng, 2)}


def classify_recent_bars(a, n=10):
    start = max(0, len(a) - n)
    return [classify_bar(a, i) for i in range(start, len(a))]


def trend_strength(a, n=10, bullish=True):
    """STEP 19: are the last n bars in the claimed direction closing near
    their highs (bull) / lows (bear), with follow-through, i.e. genuinely
    strong, or just choppy overlap?"""
    if len(a) < n:
        return {"status": "insufficient_history"}
    recent = a[-n:]
    closes_near_extreme = 0
    for x in recent:
        rng = max(0.0001, x["high"] - x["low"])
        pos = (x["close"] - x["low"]) / rng
        if bullish and pos >= 0.65:
            closes_near_extreme += 1
        elif not bullish and pos <= 0.35:
            closes_near_extreme += 1
    overlap = _avg([max(0, min(recent[i]["high"], recent[i - 1]["high"]) - max(recent[i]["low"], recent[i - 1]["low"]))
                     / max(0.0001, recent[i]["high"] - recent[i]["low"]) for i in range(1, len(recent))])
    follow_through = (recent[-1]["close"] > recent[0]["close"]) if bullish else (recent[-1]["close"] < recent[0]["close"])
    score = round(100 * (0.5 * closes_near_extreme / n + 0.3 * (1 - min(1, overlap)) + 0.2 * follow_through), 1)
    return {"status": "ok", "score": score, "closes_near_extreme": f"{closes_near_extreme}/{n}",
            "avg_bar_overlap": round(overlap, 2), "follow_through": follow_through}


def breakout_quality(a, level, direction="up", lookback=5):
    """STEP 20: score a breakout of `level` using bar size, volume, close
    position, distance through the level, and short follow-through."""
    if len(a) < lookback + 5:
        return {"status": "insufficient_history"}
    idx = None
    for i in range(len(a) - lookback, len(a)):
        x = a[i]
        if direction == "up" and x["close"] > level:
            idx = i
            break
        if direction == "down" and x["close"] < level:
            idx = i
            break
    if idx is None:
        return {"status": "no_breakout_in_window"}
    x = a[idx]
    avgv = _avg([b["volume"] for b in a[max(0, idx - 20):idx]])
    rng = max(0.0001, x["high"] - x["low"])
    close_pos = (x["close"] - x["low"]) / rng if direction == "up" else (x["high"] - x["close"]) / rng
    dist_pct = abs(x["close"] - level) / max(0.0001, level) * 100
    vol_score = min(30, 15 * (x["volume"] / max(1, avgv)))
    bar_score = min(25, close_pos * 25)
    dist_score = min(20, dist_pct * 10)
    follow = a[idx + 1:idx + 4]
    ft_ok = follow and (all(b["close"] > level for b in follow) if direction == "up"
                         else all(b["close"] < level for b in follow))
    ft_score = 25 if ft_ok else (10 if follow else 0)
    total = round(vol_score + bar_score + dist_score + ft_score, 1)
    grade = ("Strong Breakout" if total >= 75 else "Moderate Breakout" if total >= 50
             else "Weak Breakout" if total >= 25 else "False Breakout")
    return {"status": "ok", "date": x["trade_date"], "score": total, "grade": grade,
            "volume_ratio": round(x["volume"] / max(1, avgv), 2), "close_position": round(close_pos, 2),
            "distance_pct": round(dist_pct, 2), "follow_through_confirmed": bool(ft_ok)}


def pullback_quality(a, breakout_idx, level, direction="up", window=10):
    """STEP 22: after a breakout, is the pullback shallow/low-volume/holding
    (healthy continuation) or deep/high-volume/breaking back through (failure risk)?"""
    if breakout_idx is None or breakout_idx + 1 >= len(a):
        return {"status": "no_breakout_reference"}
    seg = a[breakout_idx + 1: min(len(a), breakout_idx + 1 + window)]
    if not seg:
        return {"status": "insufficient_data"}
    entry = a[breakout_idx]["close"]
    if direction == "up":
        worst = min(seg, key=lambda b: b["low"])
        depth_pct = (entry - worst["low"]) / max(0.0001, entry) * 100
        holds = worst["low"] > level
    else:
        worst = max(seg, key=lambda b: b["high"])
        depth_pct = (worst["high"] - entry) / max(0.0001, entry) * 100
        holds = worst["high"] < level
    avgv_before = _avg([b["volume"] for b in a[max(0, breakout_idx - 20):breakout_idx]])
    avgv_pullback = _avg([b["volume"] for b in seg])
    vol_ratio = avgv_pullback / max(1, avgv_before)
    score = round(max(0, 100 - depth_pct * 8 - (max(0, vol_ratio - 1) * 30) - (0 if holds else 30)), 1)
    return {"status": "ok", "depth_pct": round(depth_pct, 2), "volume_ratio_vs_pre_breakout": round(vol_ratio, 2),
            "level_held": bool(holds), "score": score,
            "grade": "Healthy" if score >= 70 else "Acceptable" if score >= 45 else "Weak — failure risk"}
