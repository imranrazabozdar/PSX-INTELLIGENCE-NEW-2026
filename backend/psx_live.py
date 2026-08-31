#!/usr/bin/env python3
"""
psx_live.py — adapter for the psxterminal.com public API.

STATUS AS OF 2026-08-26 (verified by direct probing — network tab + curl, not
assumed): the site was rebuilt on SvelteKit and its public REST surface
narrowed since this module was first written. Confirmed by hitting the live
API directly:

  WORKS (public, no auth)            /api/status, /api/init, /api/symbols,
                                      /api/klines/{KSE100,KMI30,KSE30,ALLSHR}/1d
  GATED — 403 "Access denied"        /api/klines/{any individual stock}/1d
                                      (route exists, deliberately restricted —
                                      not attempted to bypass)
  GONE — 404 / no route              /api/market-data, /api/stats (breadth,
                                      sectors), /api/yields/{symbol},
                                      /api/company/{symbol}

So the original four promises this module made — whole-market snapshot,
breadth, sector groupings, per-symbol fundamentals — are no longer available
through this API for individual stocks. What's real and still here: live
daily OHLCV for the four major indices (KSE100/KMI30/KSE30/ALLSHR) in one
request each, and the full symbol list. index_snapshot() is that real
capability; market_snapshot()/breadth()/sectors()/yields()/company() are kept
as functions (nothing that imports them breaks) but now return None with a
distinguishable reason via last_error(), since the endpoints they called are
gone or blocked, not just flaky.

Every call fails soft: if the service is down or an endpoint no longer
exists, callers get None and the dashboard carries on without it.
"""

import json
import time
import urllib.error
import urllib.request

BASE = "https://psxterminal.com"
TIMEOUT = 15
_CACHE = {}          # {key: (expires_at, payload)}
_LAST_ERROR = {}     # {key: reason string} — diagnosable, not just None

HEADERS = {
    "User-Agent": "psx-terminal-dashboard/1.0",
    "Accept": "application/json",
}

# Confirmed-public index symbols (see module docstring). Anything else under
# /api/klines/{symbol}/... currently 403s.
PUBLIC_INDICES = ["KSE100", "KMI30", "KSE30", "ALLSHR"]


def last_error(path=None):
    """Reason the most recent call for `path` returned None, if any.
    Pass no argument to get the whole {path: reason} map."""
    return _LAST_ERROR.get(path) if path else dict(_LAST_ERROR)


def _get(path, ttl=60):
    """GET with a short TTL cache. Returns parsed JSON 'data', or None —
    with the reason recorded in _LAST_ERROR so callers/diagnostics can tell
    a 403 (gated) from a 404 (gone) from a real network failure."""
    key = path
    now = time.time()
    if key in _CACHE and _CACHE[key][0] > now:
        return _CACHE[key][1]
    try:
        req = urllib.request.Request(BASE + path, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8", "ignore"))
        if not payload.get("success", True):
            _LAST_ERROR[key] = payload.get("error", "API returned success=false")
            return None
        data = payload.get("data", payload)
        _CACHE[key] = (now + ttl, data)
        _LAST_ERROR.pop(key, None)
        return data
    except urllib.error.HTTPError as e:
        _LAST_ERROR[key] = f"HTTP {e.code} {'gated' if e.code == 403 else 'gone' if e.code == 404 else ''}".strip()
        return None
    except Exception as e:
        _LAST_ERROR[key] = f"{type(e).__name__}: {e}"
        return None


def status():
    """Is the service alive? (confirmed public, unlike most of the API below)"""
    try:
        req = urllib.request.Request(BASE + "/api/status", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def index_history(index="KSE100", limit=260, ttl=3600):
    """Historical daily OHLCV for one of the 4 public indices — confirmed
    working with limit>1 (not just the single latest bar index_snapshot()
    uses), by direct probing. Powers true multi-period (1W/1M/3M/6M/12M)
    relative-strength math instead of the single-session proxy. Returns a
    list of {timestamp, open, high, low, close, volume} ascending by time,
    or None if the index isn't one of the 4 public ones or the call fails."""
    if index not in PUBLIC_INDICES:
        return None
    d = _get(f"/api/klines/{index}/1d?limit={limit}", ttl)
    return d if isinstance(d, list) else None


def index_snapshot(ttl=60):
    """Live daily OHLCV for the 4 indices still public on this API. Real data,
    confirmed working — the genuine replacement for the old whole-market
    per-stock snapshot, which is now gated (see module docstring)."""
    out = {}
    for idx in PUBLIC_INDICES:
        d = _get(f"/api/klines/{idx}/1d?limit=1", ttl)
        if isinstance(d, list) and d:
            row = d[-1]
            chg = (round((row["close"] / row["open"] - 1) * 100, 2)
                   if row.get("open") else None)
            out[idx] = {"open": row.get("open"), "high": row.get("high"),
                        "low": row.get("low"), "close": row.get("close"),
                        "volume": row.get("volume"), "chg_pct": chg,
                        "timestamp": row.get("timestamp")}
    return out or None


def symbols(ttl=3600):
    """Full ticker list — confirmed public."""
    d = _get("/api/symbols", ttl)
    return d if isinstance(d, list) else None


def market_snapshot(market="REG", ttl=60):
    """Per-symbol live price, whole market, one request. NO LONGER AVAILABLE:
    /api/market-data returns 404 on the current API (confirmed, not assumed —
    see module docstring). Kept so existing callers degrade to None instead
    of crashing; use index_snapshot() for what's actually still public."""
    return _get(f"/api/market-data?market={market}", ttl)


def breadth(ttl=120):
    """Real advance/decline and up/down volume. NO LONGER AVAILABLE:
    /api/stats is gone on the current API (confirmed 404/timeout)."""
    d = _get("/api/stats?type=breadth", ttl)
    return d if isinstance(d, dict) else None


def sectors(ttl=600):
    """Sector groupings. NO LONGER AVAILABLE: /api/stats is gone (confirmed)."""
    d = _get("/api/stats?type=sectors", ttl)
    return d if isinstance(d, dict) else None


def sector_map(ttl=600):
    """Flatten sectors into {SYMBOL: SECTOR}. Unavailable — see sectors()."""
    s = sectors(ttl)
    if not s:
        return None
    out = {}
    for name, info in s.items():
        for sym in (info or {}).get("symbols", []) or []:
            out[str(sym).upper()] = str(name).title()
    return out or None


def yields(symbol, ttl=3600):
    """P/E, dividend yield, market cap, free float. NO LONGER AVAILABLE:
    /api/yields/{symbol} returns 404 on the current API (confirmed)."""
    d = _get(f"/api/yields/{symbol.upper()}", ttl)
    return d if isinstance(d, dict) else None


def company(symbol, ttl=86400):
    """Business description, shares outstanding, key people."""
    d = _get(f"/api/company/{symbol.upper()}", ttl)
    return d if isinstance(d, dict) else None


def liquidity(symbol):
    """
    Real 30-day average volume — makes the THIN flag accurate instead of
    estimated from our own history window.
    Returns average daily traded VALUE in rupees, or None.
    """
    y = yields(symbol)
    if not y:
        return None
    v30 = y.get("volume30Avg")
    px = y.get("price")
    if v30 and px:
        try:
            return float(v30) * float(px)
        except Exception:
            return None
    return None


def index_report(snap=None):
    """Human-readable regime line from the 4 public indices — the working
    replacement for breadth_report(), which needs the now-gone /api/stats."""
    snap = snap or index_snapshot()
    if not snap:
        return None
    lines = ["--- INDEX SNAPSHOT (live, psxterminal.com) ---"]
    up = down = 0
    for name in PUBLIC_INDICES:
        d = snap.get(name)
        if not d:
            continue
        chg = d.get("chg_pct")
        if chg is not None:
            up += chg > 0
            down += chg < 0
        lines.append(f"{name}: {d.get('close')}  ({chg:+.2f}%)" if chg is not None
                     else f"{name}: {d.get('close')}")
    if up and not down:
        lines.append(">> All public indices up — broad risk-on session.")
    elif down and not up:
        lines.append(">> All public indices down — broad risk-off session.")
    elif up or down:
        lines.append(">> Indices split — no single broad-market read today.")
    lines.append("   Note: per-stock breadth/advance-decline is no longer "
                 "public on this API (see psx_live.py docstring) — this is "
                 "index-level only.")
    return "\n".join(lines)


def breadth_report(b=None):
    """Human-readable regime line, using real exchange breadth. UNAVAILABLE:
    depends on breadth(), which needs the now-gone /api/stats. Use
    index_report() instead."""
    b = b or breadth()
    if not b:
        return None
    adv, dec = b.get("advances", 0), b.get("declines", 0)
    ratio = b.get("advanceDeclineRatio")
    udv = b.get("upDownVolumeRatio")
    unch = b.get("unchanged", 0)

    if (ratio or 0) > 1.5 and (udv or 0) > 1.3:
        regime = "RISK-ON — advances and up-volume both dominant"
    elif (ratio or 0) < 0.7 or (udv or 0) < 0.7:
        regime = "RISK-OFF — declines and down-volume dominant, size down"
    else:
        regime = "MIXED — no broad tailwind, stock-picking market"

    return "\n".join([
        "--- MARKET BREADTH (live, from exchange) ---",
        f"Advances {adv}  ·  Declines {dec}  ·  Unchanged {unch}",
        f"A/D ratio {ratio}   spread {b.get('advanceDeclineSpread')}",
        f"Up volume {(b.get('upVolume') or 0)/1e6:.0f}M vs "
        f"down {(b.get('downVolume') or 0)/1e6:.0f}M   "
        f"ratio {udv}",
        f">> REGIME: {regime}",
        "   Breadth sets your position size, not your stock selection.",
    ])


if __name__ == "__main__":
    print("status  :", status())
    snap = market_snapshot()
    print("snapshot:", f"{len(snap)} symbols" if snap else "FAILED")
    if snap:
        for s in list(snap)[:3]:
            print("   ", s, snap[s]["price"], snap[s]["chg"], "%")
    print()
    print(breadth_report() or "breadth FAILED")
    sm = sector_map()
    print("\nsector map:", f"{len(sm)} symbols mapped" if sm else "FAILED")
    print("yields GAL:", yields("GAL"))


# ----------------------------------------------------------------------------
# LIVE TAPE ANALYSIS — who is actually trading, right now
# ----------------------------------------------------------------------------

_BASELINE = {}      # {sym: {"v30": float, "avg_trade": float}}


def build_baseline(symbols, hist_lookup=None):
    """
    Establish 'normal' for each symbol so we can spot abnormal.
    v30       — 30-day average volume (from their yields endpoint)
    avg_trade — typical rupees per trade, from historical value/trades if we
                have it, else inferred later from the live tape itself.
    """
    for s in symbols:
        s = s.upper()
        if s in _BASELINE:
            continue
        y = yields(s)
        if y and y.get("volume30Avg"):
            try:
                _BASELINE[s] = {"v30": float(y["volume30Avg"]),
                                "price": float(y.get("price") or 0),
                                "free_float": y.get("freeFloat")}
            except Exception:
                pass
    return _BASELINE


def session_progress() -> float:
    """
    Fraction of today's PSX trading session elapsed (0.0 to 1.0).
    Used to normalise intraday volume against expected daily volume.

    Mon-Thu: single session 09:30-15:30 PKT (360 minutes total)
    Friday:  two sessions 09:15-12:00 (165 min) + 14:15-16:05 (110 min)
             = 275 minutes total
    Weekend: returns 1.0

    Reconciled (Fix 3) against WATCHLIST_HOURS_PKT in app.py -- the two
    previously used different Mon-Thu open times (09:15 here vs 09:45
    there) and this function had no Friday-awareness at all.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Karachi"))
    wd = now.weekday()  # 0=Mon, 4=Fri, 5=Sat

    if wd >= 5:          # weekend
        return 1.0

    def t(h, m):         # helper: time on today
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    if wd == 4:          # Friday
        total = 275.0
        s1_start = t(9, 15)
        s1_end = t(12, 0)
        s2_start = t(14, 15)
        s2_end = t(16, 5)

        if now < s1_start:
            return 0.01
        elif now <= s1_end:
            elapsed = (now - s1_start).total_seconds() / 60
            return min(elapsed / total, 1.0)
        elif now < s2_start:
            # Jumu'ah break -- freeze at session 1 completion fraction
            return 165.0 / total   # ~= 0.600
        elif now <= s2_end:
            elapsed = 165 + (now - s2_start).total_seconds() / 60
            return min(elapsed / total, 1.0)
        else:
            return 1.0

    else:                # Monday-Thursday
        total = 360.0
        s_start = t(9, 30)
        s_end = t(15, 30)

        if now <= s_start:
            return 0.01
        if now >= s_end:
            return 1.0
        elapsed = (now - s_start).total_seconds() / 60
        return elapsed / total


def tape_signals(symbols=None, min_value=100_000):
    """
    Read the live tape and flag institutional footprints.

    Returns a list of alert dicts, strongest first:
      VOLUME SURGE     — pace of volume far above the 30-day norm
      BLOCK TRADES     — average trade size far above this symbol's norm
                         (fewer, larger orders = a big participant)
      ACCUMULATION     — surge + price up + closing near the day's high
      DISTRIBUTION     — surge + price down + closing near the day's low
      QUIET STRENGTH   — price up on normal volume, closing strong

    Everything is normalised by how much of the session has elapsed, so an
    11am reading isn't compared against a full day's volume.
    """
    snap = market_snapshot(ttl=45)
    if not snap:
        return None

    frac = session_progress()
    watch = [s.upper() for s in (symbols or snap.keys())]
    build_baseline(watch[:60])          # cap API calls on first pass

    alerts = []
    for sym in watch:
        d = snap.get(sym)
        if not d or not d.get("price"):
            continue
        vol, val, trades = d.get("volume") or 0, d.get("value") or 0, d.get("trades") or 0
        if val < min_value or trades < 3:
            continue

        hi, lo, px = d.get("high") or 0, d.get("low") or 0, d.get("price")
        chg = d.get("chg") or 0
        rng = (hi - lo) if hi and lo and hi > lo else None
        close_pos = ((px - lo) / rng) if rng else 0.5      # 1.0 = closing on high

        avg_trade = val / trades if trades else 0
        base = _BASELINE.get(sym, {})
        v30 = base.get("v30") or 0

        # pace: today's volume so far, extrapolated to a full session
        pace = (vol / frac) if frac > 0.03 else vol
        vol_x = (pace / v30) if v30 else None

        # 'intensity' measures how UNUSUAL the activity is, regardless of
        # direction. Direction is then read separately from price + close_pos.
        tags, intensity = [], 0.0

        if vol_x and vol_x >= 3:
            tags.append(f"volume pace {vol_x:.1f}x the 30-day norm")
            intensity += 3
        elif vol_x and vol_x >= 1.8:
            tags.append(f"volume pace {vol_x:.1f}x normal")
            intensity += 1.5

        # block-trade detection: unusually large rupees per trade
        if avg_trade > 500_000:
            tags.append(f"avg trade Rs {avg_trade/1000:.0f}k — block-sized orders")
            intensity += 3
        elif avg_trade > 200_000:
            tags.append(f"avg trade Rs {avg_trade/1000:.0f}k — larger than retail")
            intensity += 1.5

        bullish = bearish = 0.0
        if close_pos > 0.7 and chg > 0:
            tags.append(f"holding near the day's high ({close_pos*100:.0f}% of range)")
            bullish += 1.5
        elif close_pos < 0.3 and chg < 0:
            tags.append(f"pinned near the day's low ({close_pos*100:.0f}% of range)")
            bearish += 1.5
        if chg > 2:
            bullish += 1
        elif chg < -2:
            bearish += 1

        if not tags:
            continue

        strong = intensity >= 4.5
        if strong and bullish > bearish:
            kind, cls = "ACCUMULATION", "accum"
        elif strong and bearish > bullish:
            kind, cls = "DISTRIBUTION", "distrib"
        elif intensity >= 3 and bearish > bullish:
            kind, cls = "SELLING PRESSURE", "distrib"
        elif avg_trade > 500_000:
            kind, cls = "BLOCK TRADES", "block"
        elif vol_x and vol_x >= 3:
            kind, cls = "VOLUME SURGE", "surge"
        elif bullish and chg > 0:
            kind, cls = "QUIET STRENGTH", "quiet"
        else:
            kind, cls = "UNUSUAL ACTIVITY", "note"

        # signed score: + = buyers in control, - = sellers
        score = intensity + bullish - bearish
        if cls in ("distrib",):
            score = -(intensity + bearish - bullish)

        alerts.append({
            "symbol": sym, "kind": kind, "class": cls,
            "price": px, "chg": chg,
            "score": round(score, 1),
            "vol_x": round(vol_x, 1) if vol_x else None,
            "avg_trade": round(avg_trade),
            "value_m": round(val / 1e6, 1),
            "trades": trades,
            "close_pos": round(close_pos * 100),
            "why": tags,
        })

    alerts.sort(key=lambda a: abs(a["score"]), reverse=True)
    return alerts


def tape_summary(alerts):
    """One-paragraph read of what the live tape is doing."""
    if not alerts:
        return "No unusual activity on the tape right now."
    accum = [a for a in alerts if a["class"] == "accum"]
    dist = [a for a in alerts if a["class"] == "distrib"]
    block = [a for a in alerts if a["class"] == "block"]
    L = [f"{len(alerts)} symbols showing unusual activity."]
    if accum:
        L.append("ACCUMULATION (surge + strength + closing high): " +
                 ", ".join(a["symbol"] for a in accum[:8]))
    if block:
        L.append("BLOCK-SIZED ORDERS (large average trade — a big participant "
                 "is working an order): " + ", ".join(a["symbol"] for a in block[:8]))
    if dist:
        L.append("DISTRIBUTION (surge + weakness + closing low): " +
                 ", ".join(a["symbol"] for a in dist[:8]))
    L.append("Live tape only — this is what is happening today, not a verdict. "
             "Cross-check against the daily/weekly ranking before acting.")
    return "\n".join(L)
