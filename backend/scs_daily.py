"""scs_daily.py — daily OHLCV from SCS (Standard Capital Securities,
chart.scstrade.com), the replacement source for daily_ohlc.

WHY: PSX's own Data Portal (dps_scraper.py, POST dps.psx.com.pk/historical)
started returning 403 Forbidden to every request from GitHub Actions on
2026-09-27 -- confirmed even from a real Chromium session firing fetch()
inside the loaded page, so it's not something request headers can fix.
SCS's TradingView-UDF feed is the same one fire_engine/scraper.py already
uses for 1-minute and 4-hour bars; its /config lists resolution "D" and
/history returns ~5 years of daily bars per symbol in one call (verified:
OGDC 1,243 bars, 2021-09-23..2026-09-25, zero OHLC-inconsistent rows).

Same return contract as dps_scraper.fetch_psx_dps_ohlc so callers are a
drop-in swap: a DataFrame [date, symbol, open, high, low, close, volume],
oldest first; never raises -- any failure or "no_data" comes back as an
empty DataFrame so a batch backfill skips the symbol instead of crashing.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

SOURCE_LABEL = "SCS (chart.scstrade.com) daily"

_BASE = "https://chart.scstrade.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.scstrade.com/TechnicalAnalysis/TA_RealTimeCharting.aspx",
    "Accept": "application/json",
}
_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume"]


def _empty_df():
    return pd.DataFrame(columns=_COLUMNS)


def _parse_history(data, symbol):
    """UDF /history JSON -> list of row dicts. Daily bars are stamped at
    00:00 UTC of the session date, so the UTC date IS the PSX trade date."""
    if data.get("s") != "ok":
        return []
    t, o, h, l, c, v = (data.get(k) for k in ("t", "o", "h", "l", "c", "v"))
    if not all(isinstance(x, list) for x in (t, o, h, l, c, v)):
        return []
    if len({len(t), len(o), len(h), len(l), len(c), len(v)}) != 1:
        return []
    rows = []
    for i in range(len(t)):
        try:
            rows.append({
                "date": datetime.fromtimestamp(t[i], tz=timezone.utc).strftime("%Y-%m-%d"),
                "symbol": symbol,
                "open": float(o[i]), "high": float(h[i]), "low": float(l[i]),
                "close": float(c[i]), "volume": float(v[i] or 0),
            })
        except (TypeError, ValueError):
            continue
    return rows


def fetch_scs_daily_ohlc(symbol, start_date=None, end_date=None, timeout=30):
    """Daily OHLCV for `symbol` from SCS. start_date / end_date are
    "YYYY-MM-DD", inclusive; start defaults to 5 years back, end to today."""
    symbol = symbol.upper().strip()
    if not symbol:
        return _empty_df()
    now = datetime.now(timezone.utc)
    start = (datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
             if start_date else now - timedelta(days=1827))
    end = (datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
           if end_date else now)
    try:
        resp = requests.get(f"{_BASE}/history",
                            params={"symbol": symbol, "resolution": "D",
                                    "from": int(start.timestamp()), "to": int(end.timestamp())},
                            headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[scs_daily] {symbol}: request failed: {type(e).__name__}: {e}")
        return _empty_df()

    rows = _parse_history(data, symbol)
    if not rows:
        return _empty_df()
    df = pd.DataFrame(rows, columns=_COLUMNS)
    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]
    return df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
