"""dps_scraper.py — true daily OHLCV directly from the PSX Data Portal
(dps.psx.com.pk), replacing yfinance as the backfill source for
daily_ohlc.

WHY: yfinance's PSX coverage (via the "<SYMBOL>.KA" Yahoo ticker) is
split/dividend-adjusted and occasionally misaligned with PSX's own
quoted prices — confirmed by a data audit that found the Yahoo-backed
Open/Close disagreeing with PSX's actual end-of-day print for the same
session. dps.psx.com.pk is the exchange's own data portal, so its
numbers are what PSX itself reports for that session, not a
third-party's adjusted re-derivation of it.

ENDPOINT (reverse-engineered from the live site, not documented by PSX):
POST https://dps.psx.com.pk/historical, form fields `symbol` and
`date`. This is the exact request dps.psx.com.pk/historical's own
"Historical Data" page fires to populate its on-page table. Verified
directly against the live endpoint: it returns an HTML fragment
containing <table id="historicalTable"> with one row per trading
session — DATE / OPEN / HIGH / LOW / CLOSE / VOLUME — and in practice
returns the symbol's full available history (years of rows) regardless
of the `date` value, so this module fetches once per symbol and filters
to the requested date range client-side rather than trying to page the
API by date.

No official PSX API/JSON contract exists for this endpoint — it is the
same HTML the public website itself renders, fetched the way a browser
would. If PSX changes the page's markup, `_parse_historical_table`
below is the one place that needs updating.
"""

import time
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

DPS_HISTORICAL_URL = "https://dps.psx.com.pk/historical"

# A real browser UA — dps.psx.com.pk has been observed rejecting requests
# from bare/default User-Agents (e.g. python-requests/x.y.z).
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://dps.psx.com.pk/historical",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "text/html, */*; q=0.01",
}

_OHLC_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume"]


def _empty_df():
    return pd.DataFrame(columns=_OHLC_COLUMNS)


def _parse_historical_table(html, symbol):
    """Parses dps.psx.com.pk/historical's response HTML into a list of
    dicts. Any row that doesn't cleanly parse (malformed cell, a stray
    non-data row) is skipped rather than raising — one bad row must
    never lose an entire symbol's backfill."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="historicalTable") or soup.find("table")
    if table is None:
        return []
    tbody = table.find("tbody")
    if tbody is None:
        return []

    rows = []
    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 6:
            continue
        try:
            date_str = cells[0].get_text(strip=True)
            trade_date = datetime.strptime(date_str, "%b %d, %Y").strftime("%Y-%m-%d")
            o = float(cells[1].get_text(strip=True).replace(",", ""))
            h = float(cells[2].get_text(strip=True).replace(",", ""))
            l = float(cells[3].get_text(strip=True).replace(",", ""))
            c = float(cells[4].get_text(strip=True).replace(",", ""))
            v_raw = cells[5].get_text(strip=True).replace(",", "")
            v = float(v_raw) if v_raw else 0.0
        except (ValueError, IndexError):
            continue
        rows.append({"date": trade_date, "symbol": symbol, "open": o, "high": h,
                     "low": l, "close": c, "volume": v})
    return rows


def fetch_psx_dps_ohlc(symbol, start_date=None, end_date=None, timeout=20):
    """Fetch true daily OHLCV for one PSX-listed `symbol` from the PSX
    Data Portal.

    start_date / end_date: "YYYY-MM-DD" strings, inclusive on both ends.
    Either may be omitted for an open-ended bound.

    Returns a DataFrame with columns [date, symbol, open, high, low,
    close, volume], sorted oldest-first. Never raises — a network
    failure, an unrecognized symbol, or a session with no data (a
    public holiday, a not-yet-listed stock) all just come back as an
    EMPTY DataFrame, exactly like a normal "nothing to report" result,
    so callers can skip gracefully instead of crashing a batch backfill.
    """
    symbol = symbol.upper().strip()
    if not symbol:
        return _empty_df()

    request_date = end_date or datetime.now().strftime("%Y-%m-%d")
    try:
        resp = requests.post(
            DPS_HISTORICAL_URL,
            data={"symbol": symbol, "date": request_date},
            headers=HEADERS, timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[dps_scraper] {symbol}: request failed: {type(e).__name__}: {e}")
        return _empty_df()

    rows = _parse_historical_table(resp.text, symbol)
    if not rows:
        # No table / no rows -- treat as "no data for this symbol right
        # now" (holiday, delisted, bad ticker), never an exception.
        return _empty_df()

    df = pd.DataFrame(rows, columns=_OHLC_COLUMNS)
    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]
    return df.sort_values("date").reset_index(drop=True)


def fetch_psx_dps_ohlc_bulk(symbols, start_date=None, end_date=None, sleep_seconds=1.0):
    """Sequentially fetch multiple symbols, sleeping `sleep_seconds`
    between requests so a bulk backfill doesn't hammer PSX's servers.
    Returns {symbol: DataFrame} — a symbol with no data maps to an
    empty DataFrame, not a missing key, so callers can iterate every
    requested symbol uniformly."""
    out = {}
    last = len(symbols) - 1
    for i, sym in enumerate(symbols):
        out[sym.upper()] = fetch_psx_dps_ohlc(sym, start_date, end_date)
        if i < last:
            time.sleep(sleep_seconds)
    return out


if __name__ == "__main__":
    _df = fetch_psx_dps_ohlc("OGDC", start_date="2026-08-01", end_date="2026-08-27")
    print(_df.to_string(index=False))
