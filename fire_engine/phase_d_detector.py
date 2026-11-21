"""phase_d_detector.py — Phase D Breakout & Shelf Tracker (frozen rules).

A completed-bar technical STATE tracker, standalone from the Wyckoff 1.0
engine (no shared code path, no shared table). Pure functions: a list of
daily bars in, at most one signal for the LAST bar out. No database access.

All rules are evaluated on completed daily bars only and look backwards only
(no bar after the evaluated bar is ever read). Definitions, frozen:

  Common
    sma20_vol[t]   mean volume of the 20 bars BEFORE t (t excluded, so the
                   day's own spike never inflates its own baseline)
    rvol[t]        volume[t] / sma20_vol[t]
    strong close   (close - low) / (high - low) >= 0.70, or a PSX upper
                   lock: high == low and close > previous close
    turnover[t]    close[t] * volume[t] (PKR); breakout-type days
                   (SOS_IGNITION, SHELF_BREAKOUT) need >= 5,000,000
    EMA20          EMA of close, span 20 (adjust=False) over the bars given

  SOS_IGNITION at bar i
    close[i] > max(high[i-20 .. i-1])
    volume[i] >= 4.0 * sma20_vol[i]
    prior 20-bar range (max_high - min_low) / min_low <= 0.30
    strong close, turnover >= 5M

  ACTIVE_SHELF at bar t
    the most recent SOS_IGNITION bar i with 3 <= t - i <= 12 (trading days)
    every bar j in (i, t] closes above the ignition floor
      low[i] + 0.25 * (close[i] - low[i]) AND above EMA20[j]
      (lets a normal LPS throwback into the ignition bar's lower half stand;
      a close in its bottom quarter ends the shelf)
    shelf = bars (i, t]: (shelf_high - shelf_low) / shelf_low <= 0.28
    avg up-day volume >= 1.8 x avg down-day volume (only if there are down
      days; up/down = close vs previous close)

  SHELF_BREAKOUT at bar t
    ACTIVE_SHELF held at t-1 (evaluated on bars up to t-1)
    close[t] > that shelf's shelf_high
    volume[t] >= 2.5 * sma20_vol[t], strong close, turnover >= 5M

  Priority: SHELF_BREAKOUT > SOS_IGNITION > ACTIVE_SHELF, one signal per
  symbol per date.
"""
from datetime import date as _date

RULES = {
    "sos_lookback": 20,
    "sos_vol_mult": 4.0,
    "sos_max_base_range": 0.30,
    "strong_close": 0.70,
    "min_turnover_pkr": 5_000_000,
    "shelf_min_age": 3,
    "shelf_max_age": 12,
    "shelf_max_range": 0.28,
    "shelf_updown_vol": 1.8,
    "ema_span": 20,
    "breakout_vol_mult": 2.5,
    "bars": 90,
    "min_bars": 30,
}
PRIORITY = {"SHELF_BREAKOUT": 0, "SOS_IGNITION": 1, "ACTIVE_SHELF": 2}


def _ema(values, span):
    a = 2.0 / (span + 1.0)
    out, e = [], None
    for v in values:
        e = v if e is None else a * v + (1 - a) * e
        out.append(e)
    return out


def _sma_vol(vol, i, n=20):
    if i < n:
        return None
    w = vol[i - n:i]
    return sum(w) / n


def _strong_close(b, prev_close, thr):
    h, l, c = b["high"], b["low"], b["close"]
    if h == l:
        return prev_close is not None and c > prev_close
    return (c - l) / (h - l) >= thr


def _sos_at(bars, i, r=RULES):
    """SOS_IGNITION test for bar i. Returns a detail dict or None."""
    n = r["sos_lookback"]
    if i < n:
        return None
    b = bars[i]
    vol = [x["volume"] for x in bars]
    sma = _sma_vol(vol, i, n)
    if not sma:
        return None
    prior = bars[i - n:i]
    max_h = max(x["high"] for x in prior)
    min_l = min(x["low"] for x in prior)
    if min_l <= 0:
        return None
    if not (b["close"] > max_h):
        return None
    if not (b["volume"] >= r["sos_vol_mult"] * sma):
        return None
    if not ((max_h - min_l) / min_l <= r["sos_max_base_range"]):
        return None
    if not _strong_close(b, bars[i - 1]["close"], r["strong_close"]):
        return None
    if not (b["close"] * b["volume"] >= r["min_turnover_pkr"]):
        return None
    return {"base_high": max_h, "rvol": b["volume"] / sma}


def _shelf_at(bars, t, ema, r=RULES):
    """ACTIVE_SHELF test for bar t (uses bars[0..t] only). Detail or None."""
    for age in range(r["shelf_min_age"], r["shelf_max_age"] + 1):
        i = t - age
        if i < 0:
            break
        if _sos_at(bars, i, r) is None:
            continue
        # most recent qualifying ignition found -> evaluate this one only
        ign = bars[i]
        floor = ign["low"] + 0.25 * (ign["close"] - ign["low"])
        shelf = bars[i + 1:t + 1]
        for j in range(i + 1, t + 1):
            if not (bars[j]["close"] > floor and bars[j]["close"] > ema[j]):
                return None
        hi = max(x["high"] for x in shelf)
        lo = min(x["low"] for x in shelf)
        if lo <= 0 or (hi - lo) / lo > r["shelf_max_range"]:
            return None
        up, dn = [], []
        for j in range(i + 1, t + 1):
            (up if bars[j]["close"] > bars[j - 1]["close"] else dn if bars[j]["close"] < bars[j - 1]["close"]
             else []).append(bars[j]["volume"])
        ratio = None
        if dn:
            avg_up = sum(up) / len(up) if up else 0.0
            avg_dn = sum(dn) / len(dn)
            ratio = avg_up / avg_dn if avg_dn else None
            if avg_dn and avg_up < r["shelf_updown_vol"] * avg_dn:
                return None
        return {"ignition_index": i, "ignition_date": ign["date"], "shelf_high": hi, "shelf_low": lo,
                "shelf_days": age, "up_down_vol_ratio": ratio}
    return None


def evaluate(bars, r=RULES):
    """Signal for the LAST bar of `bars` (oldest first; each a dict with
    date/open/high/low/close/volume). Returns a dict or None."""
    t = len(bars) - 1
    if t < 1:
        return None
    ema = _ema([b["close"] for b in bars], r["ema_span"])
    vol = [b["volume"] for b in bars]
    b, prev = bars[t], bars[t - 1]
    sma = _sma_vol(vol, t)
    rvol = (b["volume"] / sma) if sma else None
    common = {"date": b["date"], "close": b["close"],
              "pct_change": (b["close"] / prev["close"] - 1) * 100 if prev["close"] else None,
              "rvol": rvol, "turnover_pkr": b["close"] * b["volume"]}

    # 1. SHELF_BREAKOUT
    sh_prev = _shelf_at(bars, t - 1, ema, r)
    if sh_prev and sma and b["close"] > sh_prev["shelf_high"] and b["volume"] >= r["breakout_vol_mult"] * sma \
            and _strong_close(b, prev["close"], r["strong_close"]) and common["turnover_pkr"] >= r["min_turnover_pkr"]:
        return dict(common, signal_type="SHELF_BREAKOUT", base_or_shelf_high=sh_prev["shelf_high"],
                    shelf_days=sh_prev["shelf_days"], up_down_vol_ratio=sh_prev["up_down_vol_ratio"],
                    ignition_date=sh_prev["ignition_date"])
    # 2. SOS_IGNITION
    sos = _sos_at(bars, t, r)
    if sos:
        return dict(common, signal_type="SOS_IGNITION", base_or_shelf_high=sos["base_high"], shelf_days=0,
                    up_down_vol_ratio=None, ignition_date=b["date"])
    # 3. ACTIVE_SHELF
    sh = _shelf_at(bars, t, ema, r)
    if sh:
        return dict(common, signal_type="ACTIVE_SHELF", base_or_shelf_high=sh["shelf_high"],
                    shelf_days=sh["shelf_days"], up_down_vol_ratio=sh["up_down_vol_ratio"],
                    ignition_date=sh["ignition_date"])
    return None


def as_bars(rows):
    """daily_ohlc rows (dicts with trade_date/open/high/low/close/volume) -> bar dicts."""
    out = []
    for x in rows:
        d = x.get("trade_date") or x.get("date")
        out.append({"date": d if isinstance(d, str) else _date.isoformat(d), "open": float(x["open"]),
                    "high": float(x["high"]), "low": float(x["low"]), "close": float(x["close"]),
                    "volume": float(x["volume"] or 0)})
    return out
