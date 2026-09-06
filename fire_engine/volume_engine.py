"""volume_engine.py — Phase 5: time-of-day relative volume. Global volume
comparison is meaningless (9:30 AM is always busier than 3:30 PM), so
every volume figure is compared against the MEDIAN volume this stock has
historically traded at this exact minute-of-day, not a daily average.

Requires a DatabaseManager (fire_engine.database) to read historical
candles and read/write volume_baseline.
"""
import statistics


def calculate_time_of_day_baseline(db, symbol: str, lookback_sessions: int = 30) -> dict:
    """Rebuild volume_baseline rows for `symbol` from its stored history:
    for each time_of_day seen in the last `lookback_sessions` distinct
    trading dates, store the median and mean volume traded at that minute.
    Returns {time_of_day: {median_volume, mean_volume, session_count}}."""
    cur = db.conn.execute(
        "SELECT DISTINCT date FROM market_candles WHERE symbol = ? ORDER BY date DESC LIMIT ?",
        (symbol, lookback_sessions),
    )
    dates = [r["date"] for r in cur.fetchall()]
    if not dates:
        return {}

    placeholders = ",".join("?" for _ in dates)
    cur = db.conn.execute(
        f"SELECT time_of_day, volume FROM market_candles "
        f"WHERE symbol = ? AND date IN ({placeholders})",
        (symbol, *dates),
    )
    by_time = {}
    for row in cur.fetchall():
        by_time.setdefault(row["time_of_day"], []).append(row["volume"])

    result = {}
    for time_of_day, volumes in by_time.items():
        median_volume = int(statistics.median(volumes))
        mean_volume = int(statistics.mean(volumes))
        result[time_of_day] = {
            "median_volume": median_volume, "mean_volume": mean_volume,
            "session_count": len(volumes),
        }
        db.conn.execute(
            """INSERT INTO volume_baseline
               (symbol, time_of_day, median_volume, mean_volume, lookback_sessions)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(symbol, time_of_day) DO UPDATE SET
                 median_volume=excluded.median_volume, mean_volume=excluded.mean_volume,
                 lookback_sessions=excluded.lookback_sessions,
                 last_updated=CURRENT_TIMESTAMP""",
            (symbol, time_of_day, median_volume, mean_volume, len(volumes)),
        )
    db.conn.commit()
    return result


def classify_volume(relative_volume: float, cfg: dict) -> str:
    """cfg is the `volume` section of fire_config.yaml
    (elevated_rv/abnormal_rv/extreme_rv)."""
    if relative_volume >= cfg["extreme_rv"]:
        return "EXTREME"
    if relative_volume >= cfg["abnormal_rv"]:
        return "ABNORMAL"
    if relative_volume >= cfg["elevated_rv"]:
        return "ELEVATED"
    if relative_volume >= 1.0:
        return "NORMAL"
    return "BELOW_AVERAGE"


def calculate_relative_volume(db, symbol: str, time_of_day: str, current_volume: int,
                              cfg: dict) -> dict:
    """cfg is the `volume` section of fire_config.yaml. Uses MEDIAN volume
    at this time_of_day (robust to one outlier session), with a
    progressive-average fallback when fewer than
    cfg['min_lookback_required'] sessions of history exist yet."""
    row = db.conn.execute(
        "SELECT median_volume, mean_volume, lookback_sessions FROM volume_baseline "
        "WHERE symbol = ? AND time_of_day = ?",
        (symbol, time_of_day),
    ).fetchone()

    if row is None or row["median_volume"] in (None, 0):
        return {
            "relative_volume": None, "volume_classification": "UNKNOWN",
            "median_volume": None, "current_volume": current_volume,
            "lookback_count": 0, "confidence": 0.0,
        }

    median_volume = row["median_volume"]
    lookback_count = row["lookback_sessions"] or 0
    relative_volume = current_volume / median_volume if median_volume else None
    confidence = min(1.0, lookback_count / cfg["lookback_sessions"]) if lookback_count else 0.0

    classification = (
        classify_volume(relative_volume, cfg) if relative_volume is not None else "UNKNOWN"
    )
    if lookback_count < cfg["min_lookback_required"]:
        classification = "UNKNOWN"  # too little history to classify with confidence

    return {
        "relative_volume": relative_volume, "volume_classification": classification,
        "median_volume": median_volume, "current_volume": current_volume,
        "lookback_count": lookback_count, "confidence": round(confidence, 3),
    }
