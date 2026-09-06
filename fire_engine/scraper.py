"""scraper.py — Phase 1: real 1-minute PSX OHLCV from SCS (Standard
Capital Securities, scstrade.com).

DISCOVERY, verified directly against the live endpoint (not assumed --
see the probe history in this branch's commits for the raw evidence):
`TA_RealTimeCharting.aspx`'s advanced chart widget is built on the
TradingView Charting Library, but its datafeed is entirely self-hosted
on SCS's own `chart.scstrade.com` subdomain -- NOT a proxy to
tradingview.com. `GET https://chart.scstrade.com/config` declares
`supported_resolutions` including `"1"` (1-minute); `GET .../symbols?
symbol=AICL` returns real per-symbol metadata (session hours matching
this project's own PSX session-hours table, `has_intraday: true`);
`GET .../history?symbol=AICL&resolution=1&from=<unix>&to=<unix>`
returned genuine per-minute timestamps for a real trading session. This
is the standard TradingView UDF (Universal Data Feed) protocol, just
served by SCS's own backend, not TradingView's -- confirmed acceptable
per this project's own instruction (using an embedded TradingView
Charting Library that SCS itself serves its own data through is fine;
scraping the public tradingview.com website is what was to be avoided).

No login/auth is required for any of the endpoints below -- they're the
same public calls the chart widget itself makes for any visitor.
"""
import time
from datetime import datetime, timedelta, timezone

import requests

CHART_BASE = "https://chart.scstrade.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.scstrade.com/TechnicalAnalysis/TA_RealTimeCharting.aspx",
    "Accept": "application/json",
}
RESOLUTION_1MIN = "1"

# PKT is UTC+5, no DST.
_PKT = timezone(timedelta(hours=5))


class SCSDataError(Exception):
    """Raised on a malformed/unexpected response -- never silently
    returns fabricated candles (project rule: no fake/interpolated data
    on failure)."""


def _get_json(path: str, params: dict, timeout: int, max_retries: int, retry_delay: int) -> dict:
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(f"{CHART_BASE}{path}", params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(retry_delay)
    raise SCSDataError(f"GET {path} failed after {max_retries} attempts: {last_exc!r}")


def get_symbol_info(symbol: str, timeout: int = 20, max_retries: int = 3, retry_delay: int = 60) -> dict:
    """Raw /symbols response -- session hours, has_intraday, etc."""
    return _get_json("/symbols", {"symbol": symbol}, timeout, max_retries, retry_delay)


def _session_start_end_utc(session_date: str) -> tuple:
    """PSX regular session is 09:00-16:30 PKT (this project's own
    WATCHLIST_HOURS_PKT / session.market_open/market_close in
    fire_config.yaml); returns (from_ts, to_ts) as unix seconds spanning
    that window in UTC for `session_date` (YYYY-MM-DD)."""
    y, m, d = (int(x) for x in session_date.split("-"))
    start_pkt = datetime(y, m, d, 9, 0, 0, tzinfo=_PKT)
    end_pkt = datetime(y, m, d, 16, 30, 0, tzinfo=_PKT)
    return int(start_pkt.astimezone(timezone.utc).timestamp()), int(end_pkt.astimezone(timezone.utc).timestamp())


def fetch_daily_ohlcv(symbol: str, date: str, max_retries: int = 3, retry_delay: int = 60,
                       timeout: int = 20) -> list:
    """Fetch 1-minute OHLCV for `symbol` on `date` (YYYY-MM-DD).

    Returns a list of candle dicts (oldest first): {datetime, date,
    time_of_day, open, high, low, close, volume} -- ready for
    validators.validate_trading_session() and database.DatabaseManager.
    insert_candles(). Raises SCSDataError on a malformed/error response
    rather than ever returning a partial or fabricated candle list; a
    genuinely empty/no-trade session returns an empty list (not an
    error), same as this project's dps_scraper.py already does for
    daily data.
    """
    from_ts, to_ts = _session_start_end_utc(date)
    data = _get_json(
        "/history", {"symbol": symbol, "resolution": RESOLUTION_1MIN, "from": from_ts, "to": to_ts},
        timeout, max_retries, retry_delay,
    )

    status = data.get("s")
    if status == "no_data":
        return []
    if status != "ok":
        raise SCSDataError(f"{symbol} {date}: /history returned status={status!r}: {data}")

    t, o, h, l, c, v = data.get("t"), data.get("o"), data.get("h"), data.get("l"), data.get("c"), data.get("v")
    if not all(isinstance(x, list) for x in (t, o, h, l, c, v)):
        raise SCSDataError(f"{symbol} {date}: /history response missing expected OHLCV arrays: {data.keys()}")
    lengths = {len(t), len(o), len(h), len(l), len(c), len(v)}
    if len(lengths) != 1:
        raise SCSDataError(f"{symbol} {date}: /history OHLCV arrays have mismatched lengths: {lengths}")

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
