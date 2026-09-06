"""wyckoff_data_fetcher.py — Phase 1: daily + 4-hour OHLCV for the Wyckoff
Institutional Stealth Accumulation Detector.

Timeframe sourcing (deliberately NOT "fetch daily from SCS with
resolution=1" as the prompt's own Phase 1 text literally says --
resolution="1" is 1-MINUTE on SCS's UDF API, per fire_engine/scraper.py's
own verified discovery, not daily; taking that literally would only ever
return one trading day's minute bars, never the 20+ days of daily history
Wyckoff's consolidation/OBV/MACD windows need):

  - Daily bars come from this project's OWN existing `daily_ohlc` table
    (Turso, populated by backend/run_ohlc_refresh.py and already read by
    backend/vcp_detector.py and backend/flat_base_detector.py) -- multi-
    year real PSX daily history already exists there. Fetching it again
    from a different source would duplicate data this project already
    maintains, and risks disagreeing with it.
  - 4-hour bars are genuinely new: SCS's `/history` endpoint with
    resolution="240" (4h = 240 minutes), fetched fresh here, cached in the
    new `ohlcv_4h` table (see database.py's schema) with a 4-hour
    freshness window per the spec.
  - 1-hour data is intentionally never fetched or stored anywhere in this
    module -- entry timing on that timeframe is a manual step for the
    user, not part of this scanner.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd

from fire_engine.scraper import _get_json, _PKT, SCSDataError

RESOLUTION_4H = "240"


def _range_start_end_utc(end_date: str, lookback_days: int) -> tuple:
    """(from_ts, to_ts) as unix seconds: `lookback_days` calendar days of
    PSX session time ending at `end_date`'s 16:30 PKT close."""
    y, m, d = (int(x) for x in end_date.split("-"))
    end_pkt = datetime(y, m, d, 16, 30, 0, tzinfo=_PKT)
    start_pkt = end_pkt - timedelta(days=lookback_days)
    return int(start_pkt.astimezone(timezone.utc).timestamp()), int(end_pkt.astimezone(timezone.utc).timestamp())


def fetch_4h_ohlcv(symbol: str, end_date: str, lookback_days: int = 30,
                    max_retries: int = 3, retry_delay: int = 60, timeout: int = 20) -> list:
    """Fetch 4-hour OHLCV for `symbol` ending `end_date` (YYYY-MM-DD),
    covering `lookback_days` calendar days back. PSX sessions run ~7.5h
    (09:00-16:30 PKT), so a 4-hour bar is roughly half a session -- 30
    calendar days comfortably covers the 20 bars calculate_bollinger_bands()
    needs for BB(20) on this timeframe.

    Returns a list of candle dicts (oldest first), same shape as
    scraper.fetch_daily_ohlcv()'s: {datetime, date, time_of_day, open,
    high, low, close, volume}. Raises SCSDataError on a malformed
    response; a genuinely empty range returns an empty list, never
    fabricated bars. Same retry convention as the 1-minute fetcher (3
    attempts, 60s delay) -- explicitly reused, not reinvented.
    """
    from_ts, to_ts = _range_start_end_utc(end_date, lookback_days)
    data = _get_json(
        "/history", {"symbol": symbol, "resolution": RESOLUTION_4H, "from": from_ts, "to": to_ts},
        timeout, max_retries, retry_delay,
    )

    status = data.get("s")
    if status == "no_data":
        return []
    if status != "ok":
        raise SCSDataError(f"{symbol} 4h[{end_date}-{lookback_days}d]: /history returned status={status!r}: {data}")

    t, o, h, l, c, v = data.get("t"), data.get("o"), data.get("h"), data.get("l"), data.get("c"), data.get("v")
    if not all(isinstance(x, list) for x in (t, o, h, l, c, v)):
        raise SCSDataError(f"{symbol} 4h: /history response missing expected OHLCV arrays: {data.keys()}")
    lengths = {len(t), len(o), len(h), len(l), len(c), len(v)}
    if len(lengths) != 1:
        raise SCSDataError(f"{symbol} 4h: /history OHLCV arrays have mismatched lengths: {lengths}")

    candles = []
    for i in range(len(t)):
        dt = datetime.fromtimestamp(t[i], tz=timezone.utc).astimezone(_PKT)
        candles.append({
            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "date": dt.strftime("%Y-%m-%d"),
            "time_of_day": dt.strftime("%H:%M"),
            "open": float(o[i]), "high": float(h[i]), "low": float(l[i]),
            "close": float(c[i]), "volume": int(v[i]),
        })
    candles.sort(key=lambda c: c["datetime"])
    return candles


def store_4h_data(db, symbol: str, candles: list) -> int:
    """UPSERT 4-hour candles into ohlcv_4h, keyed on (symbol, datetime).
    Same batch_query-on-Turso / executemany-on-sqlite3 split as
    database.py's insert_candles() -- at most ~180 rows per symbol here
    (30 days x 6 bars/day), so this matters less than the 1-minute path,
    but the pattern is cheap to keep consistent."""
    db.ensure_stock(symbol)
    upsert_sql = (
        """INSERT INTO ohlcv_4h
           (symbol, datetime, date, time_of_day, open, high, low, close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(symbol, datetime) DO UPDATE SET
             open=excluded.open, high=excluded.high, low=excluded.low,
             close=excluded.close, volume=excluded.volume,
             collection_timestamp=CURRENT_TIMESTAMP"""
    )
    rows = [
        (symbol, c["datetime"], c["date"], c["time_of_day"], c["open"], c["high"], c["low"],
         c["close"], c["volume"])
        for c in candles
    ]
    if hasattr(db.conn, "batch_query"):
        if rows:
            db.conn.batch_query([(upsert_sql, r) for r in rows])
    else:
        db.conn.executemany(upsert_sql, rows)
        db.conn.commit()
    return len(rows)


def _daily_rows_to_df(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _candles_to_df(candles: list) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                             index=pd.DatetimeIndex([], name="datetime"))
    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.set_index("datetime").sort_index()[["open", "high", "low", "close", "volume"]]


def load_daily_df(db, symbol: str, end_date: str, lookback_days: int = 90) -> pd.DataFrame:
    """Last `lookback_days` calendar days of daily_ohlc for `symbol` up to
    and including `end_date`, as a DataFrame indexed by date. LIMIT+DESC
    then reverse, rather than a date-range WHERE clause, so this stays
    cheap against years of history without needing an index on the
    computed range."""
    cur = db.conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume FROM daily_ohlc "
        "WHERE symbol = ? AND trade_date <= ? ORDER BY trade_date DESC LIMIT ?",
        (symbol, end_date, lookback_days),
    )
    rows = [dict(r) for r in cur.fetchall()]
    rows.reverse()
    return _daily_rows_to_df(rows)


def load_4h_df(db, symbol: str, end_date: str, lookback_days: int = 30,
               use_cache: bool = True, max_retries: int = 3, retry_delay: int = 60) -> pd.DataFrame:
    """4-hour bars for `symbol` as a DataFrame indexed by datetime. Reuses
    a cached ohlcv_4h row set when its newest collection_timestamp is
    under 4 hours old (per spec: "cache 4-hour data, expires 4 hours");
    otherwise fetches fresh from SCS and re-caches."""
    if use_cache:
        cur = db.conn.execute(
            "SELECT datetime, date, time_of_day, open, high, low, close, volume, "
            "MAX(collection_timestamp) OVER () as latest_fetch "
            "FROM ohlcv_4h WHERE symbol = ? ORDER BY datetime ASC",
            (symbol,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        if rows:
            latest_fetch = rows[0]["latest_fetch"]
            fetched_at = datetime.strptime(latest_fetch, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - fetched_at < timedelta(hours=4):
                for r in rows:
                    r.pop("latest_fetch", None)
                return _candles_to_df(rows)

    candles = fetch_4h_ohlcv(symbol, end_date, lookback_days=lookback_days,
                              max_retries=max_retries, retry_delay=retry_delay)
    if candles:
        store_4h_data(db, symbol, candles)
    return _candles_to_df(candles)


def fetch_daily_and_4h(db, symbol: str, end_date: str = None, lookback_days_daily: int = 90,
                       lookback_days_4h: int = 30, use_cache: bool = True) -> tuple:
    """Return (df_daily, df_4h), both indexed by datetime, for `symbol`.
    NOTE: no 1-hour data anywhere in this pipeline (intentional exclusion,
    see module docstring)."""
    if end_date is None:
        end_date = datetime.now(_PKT).strftime("%Y-%m-%d")
    df_daily = load_daily_df(db, symbol, end_date, lookback_days_daily)
    df_4h = load_4h_df(db, symbol, end_date, lookback_days_4h, use_cache=use_cache)
    return df_daily, df_4h
