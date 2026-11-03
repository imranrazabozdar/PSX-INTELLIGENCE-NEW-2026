"""wyckoff2_research.py — Wyckoff Accumulation 2.0 (RESEARCH / NOT PRODUCTION).

Independent research layer. It never modifies the production engine
(fire_engine/wyckoff_detector.py): the ORIGINAL score/class is obtained by
calling the unchanged WyckoffDetector, and four NEW quality components are
computed alongside it. Nothing here is a probability.

All calculations are point-in-time: every value at bar t uses bars <= t only.
Swing pivots are "confirmed" pivots -- a pivot low at bar i becomes known only
at bar i + PIVOT_K, never earlier (no repainting).

Components (each 0-100, None when there is no evidence to score):

A. Absorption quality -- of the high-volume sessions (volume >= 1.5x the
   prior 20-day average) in the last 20 bars: where they closed in their
   range, whether lower prices were rejected (lower wick), whether the low of
   the session held afterwards, and whether price was higher 3 sessions later
   (only for sessions at least 3 bars old). Heavy two-sided sessions (mid-range
   close on an unusually wide range) are penalised: high volume alone is not
   counted as accumulation.
B. OBV divergence quality -- last two confirmed price swing lows within 60
   bars: price equal/lower while OBV higher, scaled by OBV improvement per bar
   relative to average volume, OBV persistence (share of the last 20 sessions
   with a rising 5-day OBV), and whether the second low is near the 60-day
   support.
C. Accumulation structure -- 40-bar base: range width in ATRs, volatility
   contraction (ATR10/ATR40), rising confirmed swing lows, a recent failed
   breakdown ("spring"), defended support touches; halved when price is
   already > 30% above its 60-day low (extended, not early).
D. Relative strength vs KSE-100 (aligned by date) -- 20- and 60-session excess
   return, average out-performance on market down days (last 60 sessions), and
   an RS line at a 60-session high while price is not (RS leading price).

Classifications (research): thresholds are percentiles of each component on
the TRAIN period only (see run_wyckoff2_backtest.py) and are frozen for the
validation/test periods and live scan. Rules, in order:
  FAILED ACCUMULATION    STRONG+ within the last 20 bars and close now below that base's low
  POTENTIAL BREAKOUT     ADVANCED and within 3% of the 40-bar resistance
  ADVANCED ACCUMULATION  STRONG, RS >= threshold, ATR contracting, price in upper half of base
  STRONG ACCUMULATION    structure >= threshold and >= 2 of the other three >= threshold
  DEVELOPING ACCUMULATION structure >= threshold and >= 1 other >= threshold
  NO CLEAR ACCUMULATION  otherwise
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

PIVOT_K = 3
HV_MULT = 1.5
BASE = 40
LOOKBACK_DIV = 60
EXTENDED = 0.30
RES_NEAR_PCT = 3.0
DEFAULT_THRESHOLDS = {"abs": 60.0, "obv": 60.0, "struct": 60.0, "rs": 60.0}   # provisional until a train run
CLASSES = ["NO CLEAR ACCUMULATION", "DEVELOPING ACCUMULATION", "STRONG ACCUMULATION",
           "ADVANCED ACCUMULATION", "POTENTIAL BREAKOUT", "FAILED ACCUMULATION"]
SIGNAL_CLASSES = ("STRONG ACCUMULATION", "ADVANCED ACCUMULATION", "POTENTIAL BREAKOUT")


def _clip01(x):
    return float(min(1.0, max(0.0, x)))


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Accepts trade_date/date + open/high/low/close/volume; returns ascending
    frame indexed by Timestamp with lowercase columns (WyckoffDetector input)."""
    d = df.rename(columns={"trade_date": "date"}).copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.drop_duplicates("date").sort_values("date").set_index("date")
    return d[["open", "high", "low", "close", "volume"]].astype(float)


def _atr(h, l, c, n):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def confirmed_pivot_lows(low: np.ndarray, k=PIVOT_K):
    """List of (pivot_index, confirm_index). A pivot low at i is a bar whose
    low is the minimum of [i-k, i+k]; it is only usable from bar i+k on."""
    out = []
    for i in range(k, len(low) - k):
        w = low[i - k:i + k + 1]
        if low[i] == w.min() and np.argmin(w) == k:
            out.append((i, i + k))
    return out


def compute(df: pd.DataFrame, market: pd.Series | None = None, df_4h=None, thresholds=None) -> pd.DataFrame:
    """Per-bar research frame for one symbol (point-in-time)."""
    from fire_engine.wyckoff_detector import WyckoffDetector   # unchanged production detector
    th = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
    d = normalise(df) if "date" in df.columns or "trade_date" in df.columns else df.copy()
    orig = WyckoffDetector().detect_stealth_accumulation(d, df_4h)
    o, h, l, c, v = (d[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    n = len(d)
    atr14 = _atr(d["high"], d["low"], d["close"], 14).to_numpy()
    atr10 = _atr(d["high"], d["low"], d["close"], 10).to_numpy()
    atr40 = _atr(d["high"], d["low"], d["close"], 40).to_numpy()
    vsma_prior = d["volume"].shift(1).rolling(20).mean().to_numpy()
    obv = np.concatenate([[0.0], np.cumsum(np.sign(np.diff(c)) * v[1:])])
    vol60 = d["volume"].rolling(60, min_periods=20).mean().to_numpy()
    rng = np.where(h - l > 0, h - l, np.nan)
    clv = np.where(np.isnan(rng), 0.5, (c - l) / np.where(np.isnan(rng), 1, rng))
    lwick = np.where(np.isnan(rng), 0.0, (np.minimum(o, c) - l) / np.where(np.isnan(rng), 1, rng))
    piv = confirmed_pivot_lows(l)

    if market is not None and len(market):
        m = pd.Series(market).sort_index()
        m = m[~m.index.duplicated()].reindex(d.index, method="ffill").to_numpy(float)
    else:
        m = None

    cols = {k: np.full(n, np.nan) for k in ("abs_q", "obv_q", "struct_q", "rs_q", "range_hi", "range_lo",
                                             "dist_res_pct", "pos_in_base", "atr_contraction", "excess20",
                                             "excess60", "down_day_resilience", "hv_days", "div_strength")}
    flags = {k: np.zeros(n, bool) for k in ("higher_lows", "spring", "extended", "rs_leading", "obv_div",
                                            "near_support", "two_sided")}
    for t in range(max(60, BASE), n):
        # ---------------- A. absorption quality
        js = [j for j in range(t - 19, t + 1) if vsma_prior[j] > 0 and v[j] >= HV_MULT * vsma_prior[j]]
        cols["hv_days"][t] = len(js)
        if js:
            s1 = np.mean([clv[j] for j in js])
            s2 = np.mean([(lwick[j] >= 0.4 or clv[j] >= 0.6) for j in js])
            held = np.mean([l[j + 1:t + 1].min() >= l[j] if j < t else True for j in js])
            el = [j for j in js if j <= t - 3]
            fol = np.mean([c[j + 3] > c[j] for j in el]) if el else 0.5
            two = np.mean([(0.4 <= clv[j] <= 0.6) and rng[j] >= 1.5 * atr14[j] for j in js
                           if not np.isnan(rng[j]) and not np.isnan(atr14[j])] or [0])
            flags["two_sided"][t] = two >= 0.5
            cols["abs_q"][t] = 100 * (0.30 * s1 + 0.25 * s2 + 0.25 * fol + 0.20 * held) * (1 - 0.5 * two)
        # ---------------- B. OBV divergence quality
        known = [p for p, cf in piv if cf <= t and p >= t - LOOKBACK_DIV]
        lo60 = l[t - 59:t + 1].min()
        persist = np.mean([obv[j] > obv[j - 5] for j in range(t - 19, t + 1)])
        if len(known) >= 2:
            p1, p2 = known[-2], known[-1]
            price_ll = l[p2] <= l[p1] * 1.01
            obv_hl = obv[p2] > obv[p1]
            near = l[p2] <= lo60 * 1.05
            flags["near_support"][t] = near
            if price_ll and obv_hl and p2 - p1 >= 5 and vol60[t] > 0:
                strength = (obv[p2] - obv[p1]) / (vol60[t] * (p2 - p1))
                cols["div_strength"][t] = strength
                flags["obv_div"][t] = True
                cols["obv_q"][t] = 100 * (0.5 + 0.2 * _clip01(strength / 0.5) + 0.15 * persist + 0.15 * near)
            else:
                cols["obv_q"][t] = 100 * 0.3 * persist * (1.0 if c[t] <= c[t - 20] * 1.02 else 0.5)
        else:
            cols["obv_q"][t] = 100 * 0.3 * persist * (1.0 if c[t] <= c[t - 20] * 1.02 else 0.5)
        # ---------------- C. structure
        hi, lo = h[t - BASE + 1:t + 1].max(), l[t - BASE + 1:t + 1].min()
        cols["range_hi"][t], cols["range_lo"][t] = hi, lo
        cols["dist_res_pct"][t] = (hi / c[t] - 1) * 100
        cols["pos_in_base"][t] = (c[t] - lo) / (hi - lo) if hi > lo else 0.5
        width_atr = (hi - lo) / atr14[t] if atr14[t] > 0 else np.nan
        contr = atr10[t] / atr40[t] if atr40[t] > 0 else np.nan
        cols["atr_contraction"][t] = contr
        lows3 = [l[p] for p, cf in piv if cf <= t and p >= t - BASE][-3:]
        hl = len(lows3) >= 3 and lows3[0] < lows3[1] < lows3[2]
        flags["higher_lows"][t] = hl
        spring = False
        for j in range(t - 19, t + 1):
            ref = l[j - BASE:j].min() if j - BASE >= 0 else np.nan
            if not np.isnan(ref) and l[j] < ref and (c[j:min(t, j + 3) + 1] >= ref).any():
                spring = True
                break
        flags["spring"][t] = spring
        touches = sum(1 for j in range(t - BASE + 1, t + 1) if l[j] <= lo * 1.02 and c[j] >= lo * 1.01)
        ext = c[t] > lo60 * (1 + EXTENDED)
        flags["extended"][t] = ext
        sc = (0.25 * (width_atr <= 8 if not np.isnan(width_atr) else 0)
              + 0.20 * (_clip01((1.1 - contr) / 0.4) if not np.isnan(contr) else 0)
              + 0.20 * hl + 0.15 * spring + 0.20 * min(touches / 3, 1))
        cols["struct_q"][t] = 100 * sc * (0.5 if ext else 1.0)
        # ---------------- D. relative strength vs market
        if m is not None and not np.isnan(m[t - 60]):
            ex20 = ((c[t] / c[t - 20] - 1) - (m[t] / m[t - 20] - 1)) * 100
            ex60 = ((c[t] / c[t - 60] - 1) - (m[t] / m[t - 60] - 1)) * 100
            sr = c[t - 59:t + 1] / c[t - 60:t] - 1
            mr = m[t - 59:t + 1] / m[t - 60:t] - 1
            dd = mr < -0.005
            res = float(np.mean(sr[dd] - mr[dd]) * 100) if dd.any() else 0.0
            rsl = c[t - 59:t + 1] / m[t - 59:t + 1]
            lead = bool(rsl[-1] >= rsl.max() * 0.999 and c[t] < c[t - 59:t + 1].max() * 0.98)
            flags["rs_leading"][t] = lead
            cols["excess20"][t], cols["excess60"][t], cols["down_day_resilience"][t] = ex20, ex60, res
            cols["rs_q"][t] = 100 * (0.25 * _clip01(ex20 / 10 + 0.5) + 0.25 * _clip01(ex60 / 20 + 0.5)
                                     + 0.30 * _clip01(res / 1.0 + 0.5) + 0.20 * lead)
    out = pd.DataFrame({**cols, **flags}, index=d.index)
    out["orig_score"] = orig["accumulation_score"].to_numpy()
    out["orig_signal"] = orig["signal_type"].to_numpy()
    out["close"], out["volume"] = c, v
    out["chg_pct"] = (d["close"].pct_change() * 100).to_numpy()
    classify(out, th)
    return out


def classify(out: pd.DataFrame, th: dict):
    n = len(out)
    cls = np.array(["NO CLEAR ACCUMULATION"] * n, dtype=object)
    conf = np.zeros(n, int)
    last_strong, base_lo = -10 ** 9, np.nan
    A, B, S, R = (out[k].to_numpy() for k in ("abs_q", "obv_q", "struct_q", "rs_q"))
    contr, pos, dres = out["atr_contraction"].to_numpy(), out["pos_in_base"].to_numpy(), out["dist_res_pct"].to_numpy()
    c, rlo = out["close"].to_numpy(), out["range_lo"].to_numpy()
    for t in range(n):
        # int(), not numpy bool: numpy bools add as logical OR, not as counts
        ok = {k: int(bool(not np.isnan(x[t]) and x[t] >= th[k])) for k, x in (("abs", A), ("obv", B), ("struct", S), ("rs", R))}
        conf[t] = sum(ok.values())
        others = ok["abs"] + ok["obv"] + ok["rs"]
        k = "NO CLEAR ACCUMULATION"
        if ok["struct"] and others >= 1:
            k = "DEVELOPING ACCUMULATION"
        if ok["struct"] and others >= 2:
            k = "STRONG ACCUMULATION"
            if ok["rs"] and not np.isnan(contr[t]) and contr[t] < 1 and not np.isnan(pos[t]) and pos[t] >= 0.5:
                k = "ADVANCED ACCUMULATION"
                if not np.isnan(dres[t]) and dres[t] <= RES_NEAR_PCT:
                    k = "POTENTIAL BREAKOUT"
        if k in SIGNAL_CLASSES:
            last_strong, base_lo = t, rlo[t]
        elif t - last_strong <= 20 and not np.isnan(base_lo) and c[t] < base_lo:
            k = "FAILED ACCUMULATION"
        cls[t] = k
    out["enh_class"] = cls
    out["confirming"] = conf


def explain(row: dict, th: dict) -> dict:
    """Satisfied / missing conditions and invalidation, from the actual values."""
    sat, miss = [], []

    def chk(name, val, thr, good):
        (sat if val is not None and not (isinstance(val, float) and math.isnan(val)) and val >= thr else miss).append(
            f"{name} {('n/a' if val is None or (isinstance(val, float) and math.isnan(val)) else round(val, 1))} "
            f"(threshold {round(thr, 1)}) — {good}")
    chk("Accumulation structure", row.get("struct_q"), th["struct"], "tight base, contraction, defended support")
    chk("Absorption quality", row.get("abs_q"), th["abs"], "high-volume sessions closing high / rejecting lows")
    chk("OBV divergence quality", row.get("obv_q"), th["obv"], "OBV higher lows while price holds/undercuts")
    chk("Relative strength", row.get("rs_q"), th["rs"], "out-performs KSE-100, especially on down days")
    for f, txt in (("higher_lows", "rising confirmed swing lows"), ("spring", "recent failed breakdown (spring)"),
                   ("rs_leading", "RS line at a 60-day high before price"), ("near_support", "divergence low near support")):
        (sat if row.get(f) else miss).append(txt)
    if row.get("extended"):
        miss.append("price already >30% above its 60-day low (extended, not early)")
    if row.get("two_sided"):
        miss.append("high-volume sessions look two-sided (mid-range closes on wide ranges)")
    lo, hi = row.get("range_lo"), row.get("range_hi")
    return {"satisfied": sat, "missing": miss,
            "location": (f"{row.get('dist_res_pct', float('nan')):.1f}% below 40-day resistance {hi:.2f}; "
                         f"base low {lo:.2f}; position in base {row.get('pos_in_base', float('nan')):.2f}")
            if lo and hi else "n/a",
            "invalidation": f"A daily close below the base low {lo:.2f} turns this into FAILED ACCUMULATION" if lo else "n/a"}
