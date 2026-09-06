"""validators.py — Phase 3: validate a trading session's 1-minute candles
before they're stored. Never fabricates or interpolates missing candles
(per the project's own "don't create fake/interpolated candles on
failure" rule) -- it only reports what's wrong.

Each candle is a dict: {datetime, date, time_of_day, open, high, low,
close, volume}, `datetime` as "YYYY-MM-DD HH:MM:SS" (sortable as a plain
string) or a datetime object.
"""
from datetime import datetime

MAX_SINGLE_CANDLE_PRICE_MOVE_PCT = 20.0  # a 1-minute close-to-close jump beyond
                                          # this is flagged as an extreme-gap anomaly


def _dt(c):
    v = c["datetime"]
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def validate_trading_session(symbol: str, candles: list, expected_candles: int = 480) -> dict:
    """Returns:
    {is_valid, total_candles, expected_candles, issues: [str],
     quality_status: 'COMPLETE'|'INCOMPLETE'|'ANOMALY',
     duplicate_count, missing_candle_count}
    """
    issues = []
    duplicate_count = 0
    missing_candle_count = 0

    if not candles:
        return {
            "is_valid": False, "total_candles": 0, "expected_candles": expected_candles,
            "issues": [f"No candles supplied for {symbol}"], "quality_status": "INCOMPLETE",
            "duplicate_count": 0, "missing_candle_count": expected_candles,
        }

    # 1. Timestamp ordering + 2. duplicates
    dts = [_dt(c) for c in candles]
    seen = set()
    for i, dt in enumerate(dts):
        if dt in seen:
            duplicate_count += 1
            issues.append(f"Duplicate timestamp at index {i}: {dt}")
        seen.add(dt)
        if i > 0 and dt <= dts[i - 1]:
            issues.append(f"Timestamp ordering violation at index {i}: {dt} <= {dts[i-1]}")

    # 3. OHLC relationships + 4. price sanity + 5. volume sanity
    prev_close = None
    for i, c in enumerate(candles):
        o, h, l, cl, v = c["open"], c["high"], c["low"], c["close"], c["volume"]
        if h < max(o, cl):
            issues.append(f"index {i} ({c['datetime']}): high {h} < max(open,close) {max(o, cl)}")
        if l > min(o, cl):
            issues.append(f"index {i} ({c['datetime']}): low {l} > min(open,close) {min(o, cl)}")
        if o <= 0 or h <= 0 or l <= 0 or cl <= 0:
            issues.append(f"index {i} ({c['datetime']}): non-positive price (O={o} H={h} L={l} C={cl})")
        if v < 0:
            issues.append(f"index {i} ({c['datetime']}): negative volume {v}")
        if prev_close is not None and prev_close > 0:
            move_pct = abs(cl - prev_close) / prev_close * 100
            if move_pct > MAX_SINGLE_CANDLE_PRICE_MOVE_PCT:
                issues.append(
                    f"index {i} ({c['datetime']}): extreme 1-minute gap "
                    f"{move_pct:.2f}% (prev_close={prev_close}, close={cl})"
                )
        prev_close = cl

    # 6. completeness + 7. time gaps (only meaningful if timestamps are clean)
    total_candles = len(candles)
    if total_candles < expected_candles:
        missing_candle_count = expected_candles - total_candles
        issues.append(f"{missing_candle_count} candle(s) short of expected {expected_candles}")

    sorted_dts = sorted(dts)
    for i in range(1, len(sorted_dts)):
        gap_minutes = (sorted_dts[i] - sorted_dts[i - 1]).total_seconds() / 60
        if gap_minutes > 1:
            issues.append(
                f"Time gap of {gap_minutes:.0f} min between {sorted_dts[i-1]} and {sorted_dts[i]}"
            )

    has_structural_issue = any(
        "high" in msg or "low" in msg or "non-positive" in msg or "negative volume" in msg
        or "ordering violation" in msg
        for msg in issues
    )
    has_extreme_gap = any("extreme" in msg for msg in issues)

    if has_structural_issue or has_extreme_gap:
        quality_status = "ANOMALY"
    elif missing_candle_count > 0:
        quality_status = "INCOMPLETE"
    else:
        quality_status = "COMPLETE"

    is_valid = quality_status != "ANOMALY"

    return {
        "is_valid": is_valid,
        "total_candles": total_candles,
        "expected_candles": expected_candles,
        "issues": issues,
        "quality_status": quality_status,
        "duplicate_count": duplicate_count,
        "missing_candle_count": missing_candle_count,
    }
