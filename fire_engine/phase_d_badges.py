"""phase_d_badges.py -- pre-ignition badges and a setup grade for Phase D signals.

Pure functions, no database access, and no effect on the detector: given the
daily bars that end at a signal date (oldest first, up to 400 bars), compute
the context flags the tracker stores next to each signal. Display only -- a
Phase D signal is never gated or re-labelled by these badges.

  compute_badges(bars, ignition_date, signal_date) -> dict

Indicators (exact definitions):
  EMA        s.ewm(span=n, adjust=False).mean()
  RSI14      Wilder: up / down of close.diff(), each ewm(alpha=1/14, adjust=False)
  MFI14      tp=(H+L+C)/3, mf=tp*V; positive/negative flow over rolling(14)
  OBV        (sign(close.diff()).fillna(0) * V).cumsum()
  ATR14      TR = max(H-L, |H-Cprev|, |L-Cprev|), ewm(alpha=1/14, adjust=False)
  vol20[j]   mean V[j-20..j-1]

With i = index of the ignition bar and t = the last bar (the signal date):
  COIL_DRYUP         i>=21, ATR[i-1]/ATR[i-15] <= 0.95,
                     min(V[i-3],V[i-2],V[i-1]) / vol20[i-1] <= 0.35
  EXHAUSTED_PRE_IGN  i>=21, MFI14[i-1] > 80 or C[i-1]/C[i-11]-1 > 0.12
  1W_LEADER          weekly (W-FRI) bars: close > EMA10w > EMA30w, RSI14w > 55,
                     OBVw >= rolling(12).max(OBVw); the latest week ending on or
                     before the signal date; False with fewer than 30 weeks
  PRICE_TIER         close[t] <= 25 SWEET_SPOT, <= 100 MID_CAP, else HEAVY_CAP_CAUTION
  SETUP_GRADE        A+ PRIME  if close<=100 and not EXHAUSTED and (COIL or 1W_LEADER)
                     STANDARD  elif close<=100 and 1W_LEADER
                     WATCH_ONLY otherwise
"""
import math

import numpy as np
import pandas as pd

BARS = 400
GRADE_PRIME, GRADE_STANDARD, GRADE_WATCH = "A+ PRIME", "STANDARD", "WATCH_ONLY"
TIER_SWEET, TIER_MID, TIER_HEAVY = "SWEET_SPOT", "MID_CAP", "HEAVY_CAP_CAUTION"
_NAN = float("nan")


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _wilder(s, n=14):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def _rsi(close, n=14):
    d = close.diff()
    up = _wilder(d.clip(lower=0), n)
    dn = _wilder((-d).clip(lower=0), n)
    return 100 - 100 / (1 + up / dn)


def _mfi(h, l, c, v, n=14):
    tp = (h + l + c) / 3
    mf = tp * v
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(n).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg)


def _obv(c, v):
    return (np.sign(c.diff()).fillna(0) * v).cumsum()


def _atr(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return _wilder(tr, n)


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _safe_div(a, b):
    if _isnan(a) or _isnan(b) or b == 0:
        return _NAN
    return a / b


def _le(x, thr):
    return not _isnan(x) and x <= thr


def _gt(x, thr):
    return not _isnan(x) and x > thr


def _tier(close):
    if close <= 25:
        return TIER_SWEET
    if close <= 100:
        return TIER_MID
    return TIER_HEAVY


def _grade(close, exhausted, coil, leader):
    if close <= 100 and not exhausted and (coil or leader):
        return GRADE_PRIME
    if close <= 100 and leader:
        return GRADE_STANDARD
    return GRADE_WATCH


def _weekly_leader(df, signal_date):
    """1W_LEADER: the weekly cond of the latest week whose last trading date is on or before signal_date."""
    w = df.set_index(pd.to_datetime(df["date"])).resample("W-FRI").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), last_date=("date", "last"))
    w = w.dropna(subset=["close"])
    w = w[w["last_date"] <= signal_date]
    if len(w) < 30:
        return False
    c = w["close"].astype(float)
    e10, e30 = _ema(c, 10), _ema(c, 30)
    obv = _obv(c, w["volume"].astype(float))
    cond = (c > e10) & (e10 > e30) & (_rsi(c, 14) > 55) & (obv >= obv.rolling(12).max())
    return bool(cond.iloc[-1])


def _compute(bars, ignition_date, signal_date):
    df = pd.DataFrame([{k: b[k] for k in ("date", "open", "high", "low", "close", "volume")} for b in bars])
    df["date"] = df["date"].map(lambda x: str(x)[:10])
    for k in ("open", "high", "low", "close", "volume"):
        df[k] = df[k].astype(float)
    signal_date = str(signal_date)[:10]
    close_t = float(df["close"].iloc[-1])
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]
    atr, mfi, vol20 = _atr(h, l, c), _mfi(h, l, c, v), v.shift(1).rolling(20).mean()

    dates = list(df["date"])
    ign = str(ignition_date)[:10] if ignition_date else None
    i = dates.index(ign) if ign in dates else None

    def at(s, k):
        return float(s.iloc[k]) if k is not None and 0 <= k < len(s) else _NAN

    if i is None:
        atr_r = dry = mfi_p = ret10 = _NAN
    else:
        atr_r = _safe_div(at(atr, i - 1), at(atr, i - 15))
        vmin = min(at(v, i - 3), at(v, i - 2), at(v, i - 1)) if not any(
            _isnan(at(v, k)) for k in (i - 3, i - 2, i - 1)) else _NAN
        dry = _safe_div(vmin, at(vol20, i - 1))
        mfi_p = at(mfi, i - 1)
        r10 = _safe_div(at(c, i - 1), at(c, i - 11))
        ret10 = _NAN if _isnan(r10) else r10 - 1

    coil = i is not None and i >= 21 and _le(atr_r, 0.95) and _le(dry, 0.35)
    exh = i is not None and i >= 21 and (_gt(mfi_p, 80) or _gt(ret10, 0.12))
    leader = _weekly_leader(df, signal_date)
    grade = _grade(close_t, exh, coil, leader)
    return {
        "coil_dryup": bool(coil), "w1_leader": bool(leader), "exhausted_pre_ign": bool(exh),
        "price_tier": _tier(close_t), "setup_grade": grade,
        "atr_ratio_pre_ign": None if _isnan(atr_r) else float(atr_r),
        "dryup_pre_ign": None if _isnan(dry) else float(dry),
        "mfi_pre_ign": None if _isnan(mfi_p) else float(mfi_p),
        "ret10_pre_ign": None if _isnan(ret10) else float(ret10),
    }


def compute_badges(bars, ignition_date, signal_date):
    """Badges and grade for one signal. Never raises: on any error, badges are False, the grade is
    WATCH_ONLY and the numeric context is None (the price tier is still given when the close is readable)."""
    try:
        return _compute(bars, ignition_date, signal_date)
    except Exception:
        try:
            tier = _tier(float(bars[-1]["close"]))
        except Exception:
            tier = None
        return {"coil_dryup": False, "w1_leader": False, "exhausted_pre_ign": False,
                "price_tier": tier, "setup_grade": GRADE_WATCH,
                "atr_ratio_pre_ign": None, "dryup_pre_ign": None, "mfi_pre_ign": None, "ret10_pre_ign": None}
