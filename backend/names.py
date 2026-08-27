"""names.py — ticker -> official company name + sector, from PSX's own portal.

dps.psx.com.pk/symbols is the exchange's own listed-instruments directory
(1,012 rows: equities, ETFs, bonds/TFCs). Free, no auth, no third party.
Cached to disk with a TTL since it changes rarely (new listings, not
intraday) — refetching per request would be pointless load on PSX for data
that's stable for days.
"""

import json
import os
import time

import requests

PSX = "https://dps.psx.com.pk"
HEAD = {"User-Agent": "PSX-Intelligence-V2/2.0 private-research"}
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "symbol_names.json")
TTL_SECONDS = 24 * 3600

_MEM = {"map": None, "ts": 0.0}


def _fetch():
    r = requests.get(f"{PSX}/symbols", headers=HEAD, timeout=15)
    r.raise_for_status()
    rows = r.json()
    out = {}
    for x in rows:
        sym = (x.get("symbol") or "").upper()
        if not sym:
            continue
        out[sym] = {"name": x.get("name"), "sector": x.get("sectorName"),
                    "is_etf": bool(x.get("isETF")), "is_debt": bool(x.get("isDebt"))}
    return out


def load(force=False):
    """Return {SYMBOL: {name, sector, is_etf, is_debt}}. Fails soft to the
    on-disk cache (even if stale) or {} — never blocks a caller on PSX being
    slow, and never fabricates a name for a symbol it doesn't recognise."""
    now = time.time()
    if not force and _MEM["map"] is not None and (now - _MEM["ts"]) < TTL_SECONDS:
        return _MEM["map"]
    try:
        m = _fetch()
        _MEM["map"] = m
        _MEM["ts"] = now
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": now, "map": m}, f)
        except Exception:
            pass
        return m
    except Exception:
        if _MEM["map"] is not None:
            return _MEM["map"]
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                cached = json.load(f)
            _MEM["map"] = cached["map"]
            _MEM["ts"] = cached.get("fetched_at", 0)
            return _MEM["map"]
        except Exception:
            return {}


def name(symbol, default=None):
    """Official company name for one symbol, or `default` (symbol itself if
    not given) when unknown — never invents a name."""
    m = load()
    row = m.get((symbol or "").upper())
    return (row or {}).get("name") or (default if default is not None else symbol)


def label(symbol):
    """'OGDC — Oil & Gas Development Company Limited', or just the symbol if
    the name isn't known."""
    n = name(symbol, default=None)
    return f"{symbol} — {n}" if n else symbol
