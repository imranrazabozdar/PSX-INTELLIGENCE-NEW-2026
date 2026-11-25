"""Bulkowski-style chart-pattern detector (pure functions, no DB access).

Input per symbol: a pandas DataFrame with columns date, open, high, low, close, volume,
oldest first. Every value used to decide a signal at bar t reads bars <= t only.

Signal semantics:
  CONFIRMED  emitted once per pattern instance, on the first bar where the breakout holds.
  FORMING    emitted only on the latest bar of the series (a live setup snapshot).

Patterns: CUP_WITH_HANDLE, HIGH_TIGHT_FLAG_PSX, PIPE_BOTTOM_1D, BROADENING_BOTTOM.
"""
from __future__ import annotations

import numpy as np

LIQ_MIN_PKR = 5_000_000.0
PIVOT_N = 3
FORMING, CONFIRMED = "FORMING", "CONFIRMED"
CUP, FLAG, PIPE, BROAD = "CUP_WITH_HANDLE", "HIGH_TIGHT_FLAG_PSX", "PIPE_BOTTOM_1D", "BROADENING_BOTTOM"


# ---------------------------------------------------------------- causal indicators
def _prepare(df):
    d = df.sort_values("date", kind="stable").reset_index(drop=True)
    dates = [str(x)[:10] for x in d["date"]]
    A = {k: d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume")}
    return dates, A


def _sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def _ema(x, span):
    a = 2.0 / (span + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _wilder_atr(h, l, c, n=14):
    N = len(c)
    out = np.full(N, np.nan)
    if N <= n:
        return out
    prev_c = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    out[n] = np.mean(tr[1:n + 1])
    for i in range(n + 1, N):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def _pivots(x, kind):
    """Bar p is a swing pivot when it is the extreme of p-N..p+N. Usable only at p+N."""
    N = len(x)
    out = np.zeros(N, dtype=bool)
    for p in range(PIVOT_N, N - PIVOT_N):
        w = x[p - PIVOT_N:p + PIVOT_N + 1]
        out[p] = x[p] == (w.max() if kind == "high" else w.min())
    return out


def _indicators(A):
    h, l, c, v = A["high"], A["low"], A["close"], A["volume"]
    N = len(c)
    I = {"atr": _wilder_atr(h, l, c)}
    for n in (20, 50, 100, 200):
        I[f"sma{n}"] = _sma(c, n)
    I["ema20"] = _ema(c, 20)
    vs = _sma(v, 20)
    I["vol_prior"] = np.concatenate(([np.nan], vs[:-1]))          # mean(Volume[t-20..t-1])
    I["rvol"] = v / I["vol_prior"]
    cv = c * v
    med = np.full(N, np.nan)
    for t in range(20, N):
        med[t] = np.median(cv[t - 20:t])                           # median(Close*Volume[t-20..t-1])
    I["med20"] = med
    step = np.sign(np.diff(c, prepend=c[0]))
    I["obv"] = np.cumsum(step * v)
    I["ph"] = _pivots(h, "high")
    I["pl"] = _pivots(l, "low")
    I["pch"] = _pivots(c, "high")
    return {**A, **I}


# ---------------------------------------------------------------- pattern candidates at bar t
def _cup_cands(t, A):
    c, h, l, v = A["close"], A["high"], A["low"], A["volume"]
    out = []
    for L in range(5, 16):                       # handle 5..15 bars after the right lip
        r = t - 1 - L
        if r < 34 or not A["pch"][r]:
            continue
        lo, hi = max(0, r - 129), r - 34         # base 35..130 bars, left lip in first part
        lb = lo + int(np.argmax(c[lo:hi + 1]))
        Lp, Rp = c[lb], c[r]
        if abs(Rp - Lp) / Lp > 0.05:
            continue
        cl = lb + int(np.argmin(l[lb:r + 1]))
        cup_low = l[cl]
        ref = min(Lp, Rp)
        span = ref - cup_low
        if span <= 0 or not (0.15 <= span / ref <= 0.45):
            continue
        band = cup_low + span / 3.0
        if np.count_nonzero(c[lb:r + 1] <= band) < 15:
            continue
        if not A["obv"][r] > A["obv"][cl]:
            continue
        hs = slice(r + 1, t)
        if l[hs].min() < cup_low + 0.65 * span:  # handle lows stay in upper 35% of depth
            continue
        if not v[hs].mean() < 0.8 * A["vol_prior"][t]:
            continue
        out.append((CUP, (lb, r), cup_low, h[hs].max()))
    return out


def _flag_cands(t, A):
    h, l, v = A["high"], A["low"], A["volume"]
    out = []
    for L in range(5, 16):                       # flag 5..15 bars after the pole top
        b = t - 1 - L
        if b < 1 or not A["ph"][b]:
            continue
        lo = max(0, b - 42)
        a = lo + int(np.argmin(l[lo:b]))         # pole base: lowest low, must be a pivot low
        if not A["pl"][a]:
            continue
        base, top = l[a], h[b]
        height = top - base
        if base <= 0 or height <= 0 or not (0.5 <= top / base - 1.0 <= 0.9999):
            continue
        fs = slice(b + 1, t)
        if (top - l[fs].min()) / height > 0.25:
            continue
        if not v[fs].mean() < 0.8 * v[a:b + 1].mean():
            continue
        out.append((FLAG, (a, b), base, h[fs].max()))
    return out


def _broad_cands(t, A):
    h, l, c = A["high"], A["low"], A["close"]
    lo = max(0, t - 60)
    hp = [int(p) for p in np.flatnonzero(A["ph"][lo:t - 3]) + lo]   # confirmed by t-1
    lp = [int(p) for p in np.flatnonzero(A["pl"][lo:t - 3]) + lo]
    if len(hp) < 2 or len(lp) < 2:
        return []
    hb, ha, lb_, la = hp[-1], hp[-2], lp[-1], lp[-2]
    if not (h[hb] > h[ha] and l[lb_] < l[la]):   # rising highs, falling lows
        return []
    if not 15 <= max(hb, lb_) - min(ha, la) <= 60:
        return []
    floor = l[lb_]
    if (max(h[ha], h[hb]) - floor) / c[t] < 0.15:
        return []
    return [(BROAD, hb, floor, h[hb])]


def _pipe_events(A, last):
    h, l, c = A["high"], A["low"], A["close"]
    atr, med = A["atr"], A["med20"]
    out = []
    for p2 in range(21, last + 1):
        p1 = p2 - 1
        r1, r2 = h[p1] - l[p1], h[p2] - l[p2]
        if not (r1 >= 1.5 * atr[p1] and r2 >= 1.5 * atr[p2]):
            continue
        if l[p2] > l[p2 - 19:p2 + 1].min():      # bar 2 holds the 20-bar low
            continue
        if abs(l[p1] - l[p2]) > 0.01 * l[p2]:
            continue
        if r2 <= 0 or (c[p2] - l[p2]) < 0.6 * r2:   # close in top 40% of range
            continue
        top, floor = max(h[p1], h[p2]), min(l[p1], l[p2])
        if p2 + 1 <= last:
            t = p2 + 1
            if c[t] > top and med[t] >= LIQ_MIN_PKR:
                out.append((PIPE, CONFIRMED, t, floor, top))
                continue
        if p2 >= last - 1 and c[last] <= top and med[last] >= LIQ_MIN_PKR:
            out.append((PIPE, FORMING, last, floor, top))
    return out


# ---------------------------------------------------------------- output
def _signal(symbol, pat, state, t, dates, A, floor, fh):
    c = float(A["close"][t])
    over = [float(A[k][t]) for k in ("sma100", "sma200") if np.isfinite(A[k][t]) and A[k][t] > c]
    if over:
        runway = (min(over) / c - 1.0) * 100.0
        flag = "CLEAR" if runway >= 5.0 else "BLOCKED"
    else:
        runway, flag = None, "CLEAR"
    if state == CONFIRMED:
        stop, basis = max(floor, float(A["ema20"][t])), "max(pattern_floor, EMA20)"
    else:
        stop, basis = floor, "pattern_floor"
    return {
        "symbol": symbol, "pattern": pat, "state": state, "signal_date": dates[t],
        "formation_high": round(float(fh), 4), "rvol": round(float(A["rvol"][t]), 3),
        "median20_pkr": round(float(A["med20"][t]), 0), "pattern_floor": round(float(floor), 4),
        "close": round(c, 4),
        "clear_runway_pct": None if runway is None else round(runway, 2), "runway_flag": flag,
        "suggested_stop": round(float(stop), 4), "stop_basis": basis,
        "universe_breadth_pct": None,
    }


def scan_symbol(symbol, df):
    """All CONFIRMED events plus the latest-bar FORMING setups for one symbol."""
    dates, A = _prepare(df)
    if len(dates) < 25:          # ATR14 and 20-bar liquidity warm-up
        return []
    A = _indicators(A)
    last = len(dates) - 1
    c, med, rvol = A["close"], A["med20"], A["rvol"]
    events, seen = [], set()
    for t in range(21, last + 1):
        if not med[t] >= LIQ_MIN_PKR:
            continue
        for pat, key, floor, fh in _cup_cands(t, A) + _flag_cands(t, A) + _broad_cands(t, A):
            if c[t] > fh:
                if pat == CUP and not rvol[t] >= 1.5:
                    continue
                if (pat, key) not in seen:
                    seen.add((pat, key))
                    events.append((pat, CONFIRMED, t, floor, fh))
            elif t == last and c[t] >= 0.97 * fh:
                events.append((pat, FORMING, last, floor, fh))
    events += _pipe_events(A, last)
    return [_signal(str(symbol).upper(), pat, st, t, dates, A, floor, fh)
            for pat, st, t, floor, fh in events]


def universe_breadth_pct(frames):
    """% of symbols with Close > SMA50 on the latest date present across all loaded symbols."""
    rows = []
    for df in frames.values():
        dates, A = _prepare(df)
        if len(dates) >= 50:
            rows.append((dates[-1], A["close"][-1], _sma(A["close"], 50)[-1]))
    if not rows:
        return None
    latest = max(r[0] for r in rows)
    sel = [r for r in rows if r[0] == latest and np.isfinite(r[2])]
    if not sel:
        return None
    return round(100.0 * sum(1 for r in sel if r[1] > r[2]) / len(sel), 2)


def scan_universe(frames):
    """frames: {symbol: DataFrame}. Returns (signals, universe_breadth_pct)."""
    signals = []
    for sym, df in frames.items():
        signals.extend(scan_symbol(sym, df))
    breadth = universe_breadth_pct(frames)
    for s in signals:
        s["universe_breadth_pct"] = breadth
    return signals, breadth
