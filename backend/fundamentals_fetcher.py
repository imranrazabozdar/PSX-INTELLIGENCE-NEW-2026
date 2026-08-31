"""fundamentals_fetcher.py — Pull public fundamental ratios for the stock
universe from stockanalysis.com and cache them to fundamentals.json (which
fundamentals_analyzer reads).

Public, login-free, server-rendered data only — no scraping behind any gate.
Ratios change quarterly, so this is meant to be re-run occasionally (manually
or via `python main.py fundamentals`), NOT on every engine cycle.

Fields collected per symbol (whatever the page exposes):
    pe, roe (%), de (debt/equity), div_yield (%), eps_growth (%)

    python fundamentals_fetcher.py        # refresh all config.STOCKS
"""

import json
import re
import time
import logging
from datetime import date

import ssl_compat
ssl_compat.enable()          # OS trust store for HTTPS (this laptop intercepts TLS)
import requests

import config

log = logging.getLogger("fundamentals_fetcher")

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/124.0 Safari/537.36")}
BASE = "https://stockanalysis.com/quote/psx/{sym}/"
CACHE_PATH = "fundamentals.json"

# stockanalysis "statistics" page exposes these as
#   {id:"<sid>",title:"...",value:"<v>",hover:"..."}
_STAT_FIELDS = [("pe", "pe"), ("roe", "roe"),
                ("debtEquity", "de"), ("dividendYield", "div_yield")]


def _num(s):
    """Parse a stockanalysis value string to float, or None if not usable."""
    if s is None:
        return None
    s = s.strip().replace(",", "").replace("%", "")
    if s in ("", "-", "N/A", "n/a", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch(symbol, session):
    """Return a dict of available ratios for one symbol (may be partial/empty)."""
    out = {}
    # --- statistics page: pe, roe, debtEquity (de), dividendYield
    try:
        st = session.get(BASE.format(sym=symbol) + "statistics/", timeout=30).text
        for sid, key in _STAT_FIELDS:
            m = re.search(r'id:"%s",[^}]*?value:"([^"]*)"' % re.escape(sid), st)
            if m:
                v = _num(m.group(1))
                if v is not None:
                    out[key] = v
    except Exception as e:                       # network/parse failure is non-fatal
        log.warning("%s: statistics page failed: %s", symbol, e)
    # --- main quote page: epsGrowth (%)
    try:
        mn = session.get(BASE.format(sym=symbol), timeout=30).text
        m = re.search(r"epsGrowth:(-?[\d.]+)", mn)
        if m:
            v = _num(m.group(1))
            if v is not None:
                out["eps_growth"] = round(v, 2)
    except Exception as e:
        log.warning("%s: main page failed: %s", symbol, e)
    return out


def load_cache():
    """Current on-disk cache, or an empty payload if it doesn't exist yet /
    is unreadable. Never raises — a corrupt cache is treated the same as
    no cache, not a crash."""
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            payload = json.load(f)
        payload.setdefault("data", {})
        return payload
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"as_of": None, "source": "stockanalysis.com (PSX)", "data": {}}


def merge_and_save(new_data):
    """Merge `new_data` ({symbol: ratios}) into the EXISTING cache on disk
    and write the result — a caller fetching 3 new symbols must not wipe
    out the other N already cached (the bug fixed here: fetch_all() used
    to overwrite fundamentals.json with ONLY the symbols just fetched).
    New entries win over old ones for the same symbol (freshest wins);
    `as_of` bumps to today whenever anything new was actually written.
    Returns the merged payload."""
    payload = load_cache()
    if new_data:
        payload["data"].update(new_data)
        payload["as_of"] = date.today().isoformat()
    payload["source"] = "stockanalysis.com (PSX)"
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return payload


def fetch_all(symbols=None):
    """Fetch every symbol, MERGE into the existing fundamentals.json
    (not overwrite it), return the merged payload."""
    symbols = symbols or config.STOCKS
    s = requests.Session()
    s.headers.update(UA)
    data = {}
    for sym in symbols:
        d = fetch(sym, s)
        if d:
            data[sym] = d
        log.info("%-7s -> %s", sym, d or "no data")
        time.sleep(0.5)                          # be polite to the source
    return merge_and_save(data)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = fetch_all()
    n = len(p["data"])
    fields = sum(len(v) for v in p["data"].values())
    print(f"\nWrote {CACHE_PATH}: {n}/{len(config.STOCKS)} stocks have data, "
          f"{fields} ratios total, as_of {p['as_of']}")
