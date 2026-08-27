"""data_quality_engine.py — STEP 2-3: a real data-quality audit and liquidity
classification over stored true-OHLC, run BEFORE any indicator/pattern
calculation trusts the data. Corporate-action jumps are flagged for review,
never silently reclassified as Markdown/Selling-Climax (STEP 2's explicit
warning) — this module has no split/bonus/rights database to check against,
so a >=15% overnight gap is reported as `large_gap`, not diagnosed.
"""

import statistics
from datetime import datetime


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def audit(rows):
    """STEP 2: DATA QUALITY SCORE 0-100. Every check is counted, not just
    flagged, so the score is reproducible, not a vibe."""
    if not rows:
        return {"status": "missing", "score": 0}
    n = len(rows)
    issues = {"missing_trading_days": 0, "duplicate_dates": 0, "zero_volume_sessions": 0,
              "impossible_ohlc": 0, "negative_volume": 0, "stale_price_runs": 0, "large_gaps": []}

    seen_dates = set()
    stale_run = 0
    prev_close = None
    for i, x in enumerate(rows):
        d = x.get("trade_date")
        if d in seen_dates:
            issues["duplicate_dates"] += 1
        seen_dates.add(d)
        if not (x["low"] <= min(x["open"], x["close"]) <= max(x["open"], x["close"]) <= x["high"]):
            issues["impossible_ohlc"] += 1
        if (x.get("volume") or 0) < 0:
            issues["negative_volume"] += 1
        if (x.get("volume") or 0) == 0:
            issues["zero_volume_sessions"] += 1
        if prev_close:
            if x["close"] == prev_close:
                stale_run += 1
                if stale_run >= 5:
                    issues["stale_price_runs"] += 1
                    stale_run = 0
            else:
                stale_run = 0
            gap_pct = abs(x["close"] - prev_close) / prev_close * 100 if prev_close else 0
            if gap_pct >= 15:
                issues["large_gaps"].append({"date": d, "prior_close": prev_close, "close": x["close"],
                                              "gap_pct": round(gap_pct, 1)})
        prev_close = x["close"]

    # Missing trading days: count gaps of >1 calendar weekday-adjusted days
    # between consecutive stored sessions beyond a normal weekend/holiday run.
    for i in range(1, n):
        try:
            d0, d1 = _parse_date(rows[i - 1]["trade_date"]), _parse_date(rows[i]["trade_date"])
            gap_days = (d1 - d0).days
            if gap_days > 4:  # more than a long weekend
                issues["missing_trading_days"] += 1
        except Exception:
            pass

    penalty = (issues["missing_trading_days"] * 1 + issues["duplicate_dates"] * 3 +
               issues["zero_volume_sessions"] * 0.5 + issues["impossible_ohlc"] * 5 +
               issues["negative_volume"] * 5 + issues["stale_price_runs"] * 2 +
               len(issues["large_gaps"]) * 1)  # large gaps flagged, only lightly penalized — may be real, legitimate moves
    score = max(0, round(100 - (penalty / max(1, n) * 100), 1))
    status = "ok" if score >= 90 else "review" if score >= 70 else "poor"

    return {"status": status, "score": score, "sessions": n,
            "first": rows[0]["trade_date"], "last": rows[-1]["trade_date"],
            "issues": issues,
            "note": "Large gaps (>=15% one day) are flagged for review, never auto-classified as "
                    "Markdown/Selling-Climax/corporate-action-adjusted without checking the actual "
                    "announcement — this module has no split/bonus/rights database to cross-check against."}


def classify_liquidity(rows, window=60):
    """STEP 3: classify liquidity from the stock's own trailing volume
    behavior, not fundamentals or price. Thresholds are share-count buckets
    reasonable for PSX, not universal — tune LIQUIDITY_THRESHOLDS if needed."""
    if not rows or len(rows) < 10:
        return {"status": "insufficient_history"}
    recent = rows[-window:] if len(rows) > window else rows
    vols = [x.get("volume") or 0 for x in recent]
    vals = [(x.get("volume") or 0) * (x.get("close") or 0) for x in recent]
    avg_vol = statistics.mean(vols)
    median_vol = statistics.median(vols)
    avg_value = statistics.mean(vals)
    zero_days = sum(1 for v in vols if v == 0)
    zero_freq_pct = round(zero_days / len(vols) * 100, 1)
    low_vol_days = sum(1 for v in vols if v < 50_000)
    low_vol_pct = round(low_vol_days / len(vols) * 100, 1)
    turnover_consistency = round(statistics.pstdev(vols) / avg_vol, 2) if avg_vol else None

    if avg_vol >= 3_000_000:
        tier = "Highly Liquid"
    elif avg_vol >= 750_000:
        tier = "Liquid"
    elif avg_vol >= 200_000:
        tier = "Moderately Liquid"
    elif avg_vol >= 50_000:
        tier = "Illiquid"
    else:
        tier = "Very Illiquid"

    confidence_multiplier = {"Highly Liquid": 1.0, "Liquid": 0.9, "Moderately Liquid": 0.75,
                             "Illiquid": 0.5, "Very Illiquid": 0.25}[tier]

    return {"status": "ok", "tier": tier, "avg_daily_volume": round(avg_vol),
            "median_daily_volume": round(median_vol), "avg_daily_value": round(avg_value),
            "zero_volume_frequency_pct": zero_freq_pct, "low_volume_days_pct": low_vol_pct,
            "turnover_consistency": turnover_consistency, "window_bars": len(recent),
            "confidence_multiplier": confidence_multiplier,
            "note": "A candlestick pattern in an extremely illiquid stock should receive substantially "
                    "less confidence — see confidence_multiplier, applied to the DSS evidence score."}
