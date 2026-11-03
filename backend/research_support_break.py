#!/usr/bin/env python3
"""research_support_break.py — RESEARCH ONLY. 20-session support breakdown and
multi-indicator confirmation study for PSX (configured universe minus exclusions).

No database: daily bars from SCS, KSE-100 from the public index API, in-memory
only; outputs = support_break_report.md + support_break_leaderboard.csv.

FIXED BEFORE ANY RESULT (do not tune):
  prior20_low[t] = min(low[t-20..t-1])  (current bar excluded; bars = the stock's own
                   trading sessions; suspension gaps are not filled)
  events         variation-specific, first bar of a run, 10-session cooldown per stock
  primary        V_close: close[t] < prior20_low[t]
  forward        descriptive: from the signal CLOSE (further decline, MAE/MFE, recovery);
                 trading: from the NEXT OPEN (+/-0.25% slippage, 0.6% round trip)
  locks          long exit impossible on a lower-locked session (waits for the next
                 unlocked open); short entry impossible into a lower-locked open
  corp. action   events with an unlocked >11% one-day move in [t-1, t+20] are excluded
  splits         train <= 2024-12-05, validation <= 2025-11-19, test after (run 41678682179)
  selection      ON TRAIN ONLY: effect = mean 20d forward return (from next open) of
                 events WITH the condition minus events WITHOUT it, OLS with
                 date-clustered SE; Benjamini-Hochberg FDR q=0.10 per stage;
                 min 100 train events and 30 stocks
  search budget  30 singles + all pairs + triples of the 12 best train singles +
                 quadruples of the 8 best (+ a documented parameter grid on the
                 final shortlist); total counted and reported
  shortlist      top 10 by train effect among FDR-significant rules with a consistent
                 sign in validation -> FROZEN -> evaluated once on test
"""
import itertools
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import pandas as pd

import run_wyckoff2_backtest as bt
import wyckoff2_research as w2

TRAIN_TO, VAL_TO = pd.Timestamp("2024-12-05"), pd.Timestamp("2025-11-19")
SLIP, COST = 0.0025, 0.006
COOLDOWN = 10
MIN_EV, MIN_STOCKS = 100, 30
REPORT = ROOT / "support_break_report.md"
BOARD = ROOT / "support_break_leaderboard.csv"


# ------------------------------------------------------------------ indicators (all causal)
def wilder(x, n):
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(c, n):
    d = c.diff()
    g, l_ = wilder(d.clip(lower=0), n), wilder((-d).clip(lower=0), n)
    return 100 - 100 / (1 + g / l_.replace(0, np.nan))


def indicators(d, mkt):
    o, h, l, c, v = d["open"], d["high"], d["low"], d["close"], d["volume"]
    X = pd.DataFrame(index=d.index)
    X["p20low"] = l.shift(1).rolling(20).min()
    X["p40low"] = l.shift(1).rolling(40).min()
    for n in (7, 14, 21):
        X[f"rsi{n}"] = rsi(c, n)
    ll, hh = l.rolling(14).min(), h.rolling(14).max()
    X["stk"] = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    X["std"] = X["stk"].rolling(3).mean()
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    X["macd"] = e12 - e26
    X["macds"] = X["macd"].ewm(span=9, adjust=False).mean()
    X["macdh"] = X["macd"] - X["macds"]
    for n in (5, 10, 20):
        X[f"roc{n}"] = (c / c.shift(n) - 1) * 100
    tp = (h + l + c) / 3
    X["cci"] = (tp - tp.rolling(20).mean()) / (0.015 * tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True))
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    av = v.rolling(20).mean()
    for n in (5, 10, 20):
        X[f"obvsl{n}"] = (obv - obv.shift(n)) / (av * n)
    raw = tp * v
    pos = raw.where(tp.diff() > 0, 0.0).rolling(14).sum()
    neg = raw.where(tp.diff() < 0, 0.0).rolling(14).sum()
    X["mfi"] = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    rng = (h - l).replace(0, np.nan)
    mfm = (((c - l) - (h - c)) / rng).fillna(0)
    X["cmf"] = (mfm * v).rolling(20).sum() / v.rolling(20).sum()
    adl = (mfm * v).cumsum()
    X["adlsl"] = (adl - adl.shift(10)) / (av * 10)
    X["rv"] = v / v.shift(1).rolling(20).mean()
    upv = v.where(c > c.shift(), 0).rolling(20).sum()
    dnv = v.where(c < c.shift(), 0).rolling(20).sum()
    X["dnup"] = dnv / upv.replace(0, np.nan)
    for n in (9, 20, 50, 100, 200):
        X[f"ema{n}"] = c.ewm(span=n, adjust=False, min_periods=n).mean()
    X["ema50sl"] = X["ema50"] / X["ema50"].shift(5) - 1
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    atr14 = wilder(tr, 14)
    X["pdi"], X["mdi"] = 100 * wilder(pdm, 14) / atr14, 100 * wilder(mdm, 14) / atr14
    X["adx"] = wilder(100 * (X["pdi"] - X["mdi"]).abs() / (X["pdi"] + X["mdi"]).replace(0, np.nan), 14)
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    X["spanA"] = ((tenkan + kijun) / 2).shift(26)            # cloud at t built from data <= t-26
    X["spanB"] = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    X["tenkan"], X["kijun"] = tenkan, kijun
    for n in (5, 14, 20):
        X[f"atr{n}"] = wilder(tr, n)
    X["atrp"] = X["atr14"] / c * 100
    lr = np.log(c / c.shift())
    for n in (10, 20, 60):
        X[f"hv{n}"] = lr.rolling(n).std() * math.sqrt(252)
    mid, sd = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    X["bbw"] = 4 * sd / mid
    X["bbw_pct"] = X["bbw"].rolling(101).apply(lambda x: (x[:-1] < x[-1]).mean() * 100, raw=True)
    ema20 = c.ewm(span=20, adjust=False).mean()
    X["sqz"] = ((mid + 2 * sd) < (ema20 + 1.5 * X["atr20"])) & ((mid - 2 * sd) > (ema20 - 1.5 * X["atr20"]))
    X["dcw"] = (h.rolling(20).max() - l.rolling(20).min()) / c
    if mkt is not None:
        m = mkt.reindex(d.index, method="ffill")
        for n in (5, 10, 20, 60):
            X[f"rs{n}"] = ((c / c.shift(n)) - (m / m.shift(n))) * 100
        rsl = c / m
        X["rsl_dir"] = rsl / rsl.shift(10) - 1
        sr, mr = c.pct_change(), m.pct_change()
        X["dd_weak"] = (sr - mr).where(mr < -0.005).rolling(60, min_periods=5).mean() * 100
    body = (c - o).abs()
    X["lower_highs"] = h.rolling(10).max() < h.shift(10).rolling(10).max()
    X["lower_lows"] = l.rolling(10).min() < l.shift(10).rolling(10).min()
    X["bear_engulf"] = (c < o) & (c.shift() > o.shift()) & (o >= c.shift()) & (c <= o.shift())
    X["shoot_star"] = ((h - np.maximum(o, c)) >= 2 * body) & ((np.minimum(o, c) - l) <= 0.3 * body + 1e-9) & (c.shift() > c.shift(2))
    X["evening_star"] = ((c.shift(2) > o.shift(2)) & ((c.shift(1) - o.shift(1)).abs() <= 0.3 * body.shift(2))
                         & (c < o) & (c < (o.shift(2) + c.shift(2)) / 2))
    X["inside_break"] = (h.shift(1) <= h.shift(2)) & (l.shift(1) >= l.shift(2)) & (c < l.shift(1))
    X["long_bear"] = (c < o) & (body >= 1.5 * body.rolling(20).mean().shift(1))
    X["ema20_reject"] = ((h >= X["ema20"]) & (c < X["ema20"])).rolling(5).max().astype(bool)
    X["mfi_prev"] = X["mfi"].shift(1)
    return X


def conditions(X, c, l):
    """30 confirmation conditions, evaluated at the signal bar (all causal)."""
    return {
        "rv>=1.5": X["rv"] >= 1.5, "rv>=2": X["rv"] >= 2.0,
        "cmf<0": X["cmf"] < 0, "obv10_declining": X["obvsl10"] < 0, "obv20_declining": X["obvsl20"] < 0,
        "adl_declining": X["adlsl"] < 0, "mfi<40": X["mfi"] < 40, "down/up_vol>1.2": X["dnup"] > 1.2,
        "rsi14<40": X["rsi14"] < 40, "rsi7<30": X["rsi7"] < 30, "rsi14_x_below50(5d)": ((X["rsi14"] < 50) & (X["rsi14"].shift(5) >= 50)),
        "stoch_K<D&K<20": (X["stk"] < X["std"]) & (X["stk"] < 20), "macd<signal": X["macd"] < X["macds"],
        "macd_hist_falling": (X["macdh"] < 0) & (X["macdh"] < X["macdh"].shift(1)), "roc10<-5": X["roc10"] < -5,
        "cci<-100": X["cci"] < -100,
        "below_ema20": c < X["ema20"], "below_ema50": c < X["ema50"], "below_ema200": c < X["ema200"],
        "ema50_falling": X["ema50sl"] < 0, "adx>20&-DI>+DI": (X["adx"] > 20) & (X["mdi"] > X["pdi"]),
        "below_ichimoku_cloud": c < np.minimum(X["spanA"], X["spanB"]),
        "atr5/atr20>1.2": X["atr5"] / X["atr20"] > 1.2, "bbw_expanding": X["bbw"] > 1.2 * X["bbw"].shift(5),
        "rs20<0": X.get("rs20", pd.Series(np.nan, index=X.index)) < 0,
        "rs60<0": X.get("rs60", pd.Series(np.nan, index=X.index)) < 0,
        "lower_highs": X["lower_highs"], "bearish_candle": X["bear_engulf"] | X["shoot_star"].shift(1, fill_value=False)
        | X["evening_star"] | X["long_bear"], "ema20_rejection(5d)": X["ema20_reject"],
        "40d_range_break": c < X["p40low"],
    }


SENS = ["rv>=1.25", "rv>=2.5", "rsi14<35", "rsi14<45", "mfi<30", "mfi<50", "cmf<-0.1", "rs20<-5"]


def sensitivity(X):
    """Neighbouring parameter values -- reported for stability only, not searched."""
    return {"rv>=1.25": X["rv"] >= 1.25, "rv>=2.5": X["rv"] >= 2.5, "rsi14<35": X["rsi14"] < 35,
            "rsi14<45": X["rsi14"] < 45, "mfi<30": X["mfi"] < 30, "mfi<50": X["mfi"] < 50,
            "cmf<-0.1": X["cmf"] < -0.1, "rs20<-5": X.get("rs20", pd.Series(np.nan, index=X.index)) < -5}


# ------------------------------------------------------------------ statistics
def ols_effect(y, x, dates):
    """mean(y|x) - mean(y|~x) with date-clustered SE -> (effect, se, t, p)."""
    X = np.column_stack([np.ones(len(y)), x.astype(float)])
    try:
        inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return None
    b = inv @ X.T @ y
    u = y - X @ b
    meat = np.zeros((2, 2))
    g = defaultdict(list)
    for i, dt in enumerate(dates):
        g[dt].append(i)
    for idx in g.values():
        s = X[idx].T @ u[idx]
        meat += np.outer(s, s)
    G = len(g)
    V = inv @ meat @ inv * G / max(1, G - 1)
    se = math.sqrt(max(V[1, 1], 1e-12))
    t = b[1] / se
    p = math.erfc(abs(t) / math.sqrt(2))
    return float(b[1]), se, float(t), p


def bh(pvals, q=0.10):
    p = np.asarray(pvals)
    order = np.argsort(p)
    m = len(p)
    thr = q * (np.arange(1, m + 1)) / m
    passed = np.zeros(m, bool)
    ok = p[order] <= thr
    if ok.any():
        k = np.max(np.flatnonzero(ok))
        passed[order[:k + 1]] = True
    return passed


def cl_ci(vals, dates, z=1.96):
    vals = np.asarray(vals, float)
    if len(vals) < 2:
        return (None, None)
    mu = vals.mean()
    g = defaultdict(list)
    for v, d in zip(vals, dates):
        g[d].append(v - mu)
    G = len(g)
    if G < 2:
        return (None, None)
    se = math.sqrt(sum(sum(x) ** 2 for x in g.values()) / len(vals) ** 2 * G / (G - 1))
    return (round(float(mu - z * se), 2), round(float(mu + z * se), 2))


def describe(ev):
    if len(ev) == 0:
        return {"n": 0}
    o = {"n": len(ev), "stocks": ev["symbol"].nunique(), "dates": ev["date"].nunique()}
    for hz in (3, 5, 10, 20):
        x = ev[f"r{hz}"].dropna()
        o[f"mean{hz}"], o[f"med{hz}"] = round(x.mean(), 2), round(x.median(), 2)
        o[f"neg{hz}"] = round(100 * (x < 0).mean(), 1)
    o["ci20"] = cl_ci(ev["r20"].dropna(), ev.loc[ev["r20"].notna(), "date"])
    for th in (3, 5, 10, 15):
        o[f"fall{th}"] = round(100 * (ev["fwd_low20"] <= -th).mean(), 1)
    o["mae"], o["mfe"] = round(ev["fwd_low20"].mean(), 2), round(ev["fwd_high20"].mean(), 2)
    o["t_fall5"] = ev["t_fall5"].median()
    o["t_reclaim"] = ev["t_reclaim"].median()
    rc = ev["t_reclaim"]
    o["reclaim<=3"], o["reclaim<=5"] = round(100 * (rc <= 3).mean(), 1), round(100 * (rc <= 5).mean(), 1)
    o["reclaim<=10"], o["reclaim<=20"] = round(100 * (rc <= 10).mean(), 1), round(100 * (rc <= 20).mean(), 1)
    o["never_reclaim20"] = round(100 * rc.isna().mean(), 1)
    o["exit_vs_hold20"] = round(ev["save20"].mean(), 2) if "save20" in ev else None
    o["top10_stock_share"] = round(100 * ev["symbol"].value_counts().head(10).sum() / len(ev), 1)
    return o


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    syms, exc = bt.universe()
    mkt, msrc = bt.load_market()
    end = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    start = (pd.Timestamp.utcnow() - pd.Timedelta(days=1830)).strftime("%Y-%m-%d")
    data, missing = {}, []
    for s in syms:
        try:
            df = bt.scs_daily.fetch_scs_daily_ohlc(s, start_date=start, end_date=end)
        except Exception:
            df = pd.DataFrame()
        if len(df):
            df = df[(df["low"] <= df[["open", "close"]].min(axis=1)) & (df[["open", "close"]].max(axis=1) <= df["high"]) & (df["close"] > 0)]
        if len(df) < 260:
            missing.append(s)
            continue
        data[s] = w2.normalise(df)
        time.sleep(0.2)
    m = mkt.sort_index()
    s50, s200 = m.rolling(50).mean(), m.rolling(200).mean()
    trend = pd.Series(np.where((m > s50) & (s50 > s200), "Bull", np.where((m < s50) & (s50 < s200), "Bear", "Sideways")),
                      index=m.index).where(s200.notna()).dropna()
    hv = np.log(m / m.shift()).rolling(20).std()
    hvp = hv.rolling(252, min_periods=150).apply(lambda x: (x[:-1] < x[-1]).mean() * 100, raw=True)
    volreg = pd.Series(np.where(hvp >= 70, "High vol", np.where(hvp <= 30, "Low vol", "Mid vol")), index=m.index).where(hvp.notna()).dropna()

    rows = []
    cond_names = None
    for s, d in data.items():
        X = indicators(d, m)
        O, H, L, C = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
        n = len(C)
        cond = conditions(X, d["close"], d["low"])
        cond_names = list(cond)
        cond.update(sensitivity(X))
        all_names = list(cond)
        CM = np.column_stack([cond[k].fillna(False).to_numpy(bool) for k in all_names])
        p20 = X["p20low"].to_numpy()
        ret1 = np.r_[np.nan, C[1:] / C[:-1] - 1]
        locked = H <= L * 1.001
        v_intraday = (L < p20) & (C >= p20)
        v_close = C < p20
        v_close1 = C < p20 * 0.99
        v_two = v_close & np.r_[False, v_close[:-1]]
        # failed retest: a close-break within the prior 10 sessions, then high >= that level and close < level
        v_retest = np.zeros(n, bool)
        lvl_ret = np.full(n, np.nan)
        last_break, last_lvl = -10 ** 9, np.nan
        for t in range(n):
            if v_close[t] and not (t >= 1 and v_close[t - 1]):
                last_break, last_lvl = t, p20[t]
            elif 1 <= t - last_break <= 10 and H[t] >= last_lvl and C[t] < last_lvl and C[t - 1] < last_lvl:
                v_retest[t], lvl_ret[t] = True, last_lvl
        variations = {"V0 intraday below, close above": v_intraday, "V1 close below (primary)": v_close,
                      "V2 close >=1% below": v_close1, "V3 two consecutive closes below": v_two,
                      "V4 failed retest of broken level": v_retest}
        dates = d.index
        reg_t = trend.reindex(dates, method="ffill").to_numpy()
        reg_v = volreg.reindex(dates, method="ffill").to_numpy()
        tv20 = (d["close"] * d["volume"]).rolling(20).mean().to_numpy()
        prior20 = np.r_[np.full(20, np.nan), C[20:] / C[:-20] - 1] * 100
        for vname, sig in variations.items():
            last = -10 ** 9
            for t in range(220, n - 1):
                if not sig[t] or (t >= 1 and sig[t - 1]) or t - last < COOLDOWN:
                    continue
                w_end = min(n, t + 21)
                bad = (np.abs(ret1[max(1, t - 1):w_end]) > 0.11) & ~locked[max(1, t - 1):w_end]
                if bad.any():
                    continue
                last = t
                level = lvl_ret[t] if vname.startswith("V4") else p20[t]
                e = {"symbol": s, "date": dates[t], "variation": vname, "regime": reg_t[t], "volreg": reg_v[t],
                     "tv20": tv20[t], "prior20": prior20[t], "depth": (C[t] / level - 1) * 100}
                for hz in (3, 5, 10, 20):
                    e[f"r{hz}"] = (C[t + hz] / (O[t + 1] * (1 + SLIP)) - 1) * 100 if t + hz < n else np.nan
                fl = L[t + 1:w_end]
                e["fwd_low20"] = (fl.min() / C[t] - 1) * 100 if len(fl) else np.nan
                e["fwd_high20"] = (H[t + 1:w_end].max() / C[t] - 1) * 100 if len(fl) else np.nan
                j = next((k for k in range(t + 1, w_end) if C[k] <= C[t] * 0.95), None)
                e["t_fall5"] = (j - t) if j else np.nan
                j = next((k for k in range(t + 1, w_end) if C[k] > level), None)
                e["t_reclaim"] = (j - t) if j else np.nan
                # long protection: exit at next executable open vs hold 20 sessions
                k = t + 1
                while k < n and locked[k] and C[k] <= C[k - 1] * 0.905:
                    k += 1
                if t + 20 < n and k < n:
                    exit_px = O[k] * (1 - SLIP)
                    hold_px = C[t + 20] * (1 - SLIP)
                    e["save20"] = (exit_px / hold_px - 1) * 100          # >0 = exiting beat holding
                    # research-only short: enter next open unless locked down, exit close t+20
                    if not (locked[t + 1] and O[t + 1] <= C[t] * 0.905):
                        ent = O[t + 1] * (1 - SLIP)
                        e["short20"] = (ent / (C[t + 20] * (1 + SLIP)) - 1 - COST) * 100
                for ci, cn in enumerate(all_names):
                    e[cn] = bool(CM[t, ci])
                rows.append(e)
    ev = pd.DataFrame(rows)
    ev["split"] = np.where(ev["date"] <= TRAIN_TO, "train", np.where(ev["date"] <= VAL_TO, "validation", "test"))
    print(f"{len(data)} stocks, missing {missing}; {len(ev)} events; {time.time() - t0:.0f}s")

    # baseline: all sessions (every 5th), forward 20d from next open -- for context
    base = []
    for s, d in data.items():
        O, C = d["open"].to_numpy(), d["close"].to_numpy()
        for t in range(220, len(C) - 21, 5):
            base.append({"date": d.index[t], "r20": (C[t + 20] / (O[t + 1] * (1 + SLIP)) - 1) * 100})
    base = pd.DataFrame(base)
    base["split"] = np.where(base["date"] <= TRAIN_TO, "train", np.where(base["date"] <= VAL_TO, "validation", "test"))

    prim = ev[ev["variation"] == "V1 close below (primary)"].copy()
    tr, va, te = (prim[prim["split"] == k] for k in ("train", "validation", "test"))

    def eval_rule(df, cols):
        mask = df[list(cols)].all(axis=1).to_numpy()
        y = df["r20"].to_numpy(float)
        ok = ~np.isnan(y)
        if mask[ok].sum() < 5 or (~mask[ok]).sum() < 5:
            return None
        r = ols_effect(y[ok], mask[ok], df["date"].to_numpy()[ok])
        if not r:
            return None
        sub = df[mask]
        return {"effect": r[0], "se": r[1], "t": r[2], "p": r[3], "n": int(mask.sum()),
                "stocks": int(sub["symbol"].nunique()), "mean20_with": float(sub["r20"].mean()),
                "mean20_without": float(df[~mask]["r20"].mean())}

    # ---------------- staged search on TRAIN
    tested = []
    singles = []
    for cn in cond_names:
        r = eval_rule(tr, (cn,))
        if r:
            singles.append(((cn,), r))
    tested += singles
    eligible = [x for x in singles if x[1]["n"] >= MIN_EV and x[1]["stocks"] >= MIN_STOCKS]
    best = [x[0][0] for x in sorted(eligible, key=lambda x: x[1]["effect"])]
    pairs = [(cmb, eval_rule(tr, cmb)) for cmb in itertools.combinations(cond_names, 2)]
    tested += [x for x in pairs if x[1]]
    triples = [(cmb, eval_rule(tr, cmb)) for cmb in itertools.combinations(best[:12], 3)]
    tested += [x for x in triples if x[1]]
    quads = [(cmb, eval_rule(tr, cmb)) for cmb in itertools.combinations(best[:8], 4)]
    tested += [x for x in quads if x[1]]
    budget = len(tested)
    cand = [(c, r) for c, r in tested if r["n"] >= MIN_EV and r["stocks"] >= MIN_STOCKS]
    passed = bh([r["p"] for _, r in cand], 0.10) if cand else []
    sig = [(c, r) for (c, r), ok in zip(cand, passed) if ok and r["effect"] < 0]
    # validation check (sign consistent and n >= 30), then freeze top 10 by train effect
    vrows = []
    for c, r in sig:
        v = eval_rule(va, c)
        if v and v["n"] >= 30 and v["effect"] < 0:
            vrows.append((c, r, v))
    vrows.sort(key=lambda x: x[1]["effect"])
    frozen = vrows[:10]
    # ---------------- test (once) for the frozen shortlist
    final = []
    for c, r, v in frozen:
        t_ = eval_rule(te, c)
        mask = te[list(c)].all(axis=1)
        sub = te[mask]
        final.append({"rule": " + ".join(c), "k": len(c), "train_effect": round(r["effect"], 2), "train_n": r["n"],
                      "train_p": r["p"], "val_effect": round(v["effect"], 2), "val_n": v["n"],
                      "test_effect": round(t_["effect"], 2) if t_ else None, "test_t": round(t_["t"], 2) if t_ else None,
                      "test_n": int(mask.sum()), "test_stocks": int(sub["symbol"].nunique()),
                      "test_mean20": round(sub["r20"].mean(), 2) if len(sub) else None,
                      "test_neg20_pct": round(100 * (sub["r20"] < 0).mean(), 1) if len(sub) else None,
                      "test_fall10_pct": round(100 * (sub["fwd_low20"] <= -10).mean(), 1) if len(sub) else None,
                      "test_exit_vs_hold20": round(sub["save20"].mean(), 2) if len(sub) else None,
                      "test_short20_net": round(sub["short20"].mean(), 2) if len(sub) else None,
                      "test_short_pf": (round(sub.loc[sub["short20"] > 0, "short20"].sum() / -sub.loc[sub["short20"] <= 0, "short20"].sum(), 2)
                                        if len(sub) and (sub["short20"] <= 0).any() else None),
                      "test_top10_stock_share": round(100 * sub["symbol"].value_counts().head(10).sum() / max(1, len(sub)), 1)})
    # ---------------- walk-forward (yearly): pick best FDR-free single+pair on data < year, test on year
    wf = []
    years = sorted(prim["date"].dt.year.unique())
    for y in years[2:]:
        past, cur = prim[prim["date"].dt.year < y], prim[prim["date"].dt.year == y]
        pool = [(c, eval_rule(past, c)) for c in [(x,) for x in cond_names] + list(itertools.combinations(cond_names, 2))]
        pool = [(c, r) for c, r in pool if r and r["n"] >= MIN_EV and r["stocks"] >= MIN_STOCKS]
        if not pool:
            continue
        c, r = min(pool, key=lambda x: x[1]["effect"])
        cr = eval_rule(cur, c)
        wf.append({"year": int(y), "rule": " + ".join(c), "insample_effect": round(r["effect"], 2),
                   "outsample_effect": round(cr["effect"], 2) if cr else None, "outsample_n": cr["n"] if cr else 0})
    # ---------------- false-breakdown discrimination (train vs test)
    fb = []
    for sp, df in (("train", tr), ("test", te)):
        d2 = df.dropna(subset=["r20"])
        quick = d2["t_reclaim"] <= 5
        for cn in cond_names:
            a, b = d2.loc[quick, cn].mean(), d2.loc[~quick, cn].mean()
            fb.append({"split": sp, "condition": cn, "share_in_false_breakdowns": round(100 * a, 1),
                       "share_in_genuine": round(100 * b, 1), "difference": round(100 * (b - a), 1)})
    fb = pd.DataFrame(fb)
    # ---------------- parameter sensitivity (reported only, never used for selection)
    sens = []
    for cn in SENS:
        for sp, df in (("train", tr), ("test", te)):
            r = eval_rule(df, (cn,))
            if r:
                sens.append({"param": cn, "split": sp, "n": r["n"], "effect": round(r["effect"], 2), "t": round(r["t"], 2)})
    lb = pd.DataFrame([{"stage": len(c), "rule": " + ".join(c), **{k: (round(v, 4) if isinstance(v, float) else v)
                                                                    for k, v in r.items()}} for c, r in tested])
    lb = lb.sort_values("effect")
    lb.to_csv(BOARD, index=False)
    write_report(ev, base, prim, tested, cand, sig, vrows, final, wf, fb, budget, missing, exc, msrc, len(data), sens)
    print(f"done in {time.time() - t0:.0f}s")
    return 0


def fmt(o):
    if not o.get("n"):
        return "| 0 |" + " |" * 13
    return (f"| {o['n']} | {o['stocks']} | {o['mean3']} / {o['mean5']} / {o['mean10']} / {o['mean20']} | {o['med20']} | "
            f"{o['neg20']}% | {o['ci20']} | {o['fall3']} / {o['fall5']} / {o['fall10']} / {o['fall15']} | "
            f"{o['mae']} / {o['mfe']} | {o['t_fall5']} | {o['reclaim<=3']} / {o['reclaim<=5']} / {o['reclaim<=10']} / "
            f"{o['reclaim<=20']} | {o['never_reclaim20']} | {o['exit_vs_hold20']} | {o['top10_stock_share']}% |")


def write_report(ev, base, prim, tested, cand, sig, vrows, final, wf, fb, budget, missing, exc, msrc, nstocks, sens):
    H = ("| Variation / split | Events | Stocks | Mean 3/5/10/20d % (from next open) | Median 20d | Neg 20d | 20d mean 95% CI | "
         "Further fall ≥3/5/10/15% (from close) | Avg max fall / rise % | Median sessions to −5% | Reclaimed ≤3/5/10/20 % | "
         "Never reclaimed % | Exit-vs-hold 20d pts | Top-10-stock share |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    L = ["# 20-session support breakdown — RESEARCH ONLY", "",
         f"{nstocks} stocks (configured universe minus exclusions {exc}; no usable SCS data {missing}) · benchmark {msrc} · "
         f"splits train ≤ {TRAIN_TO.date()}, validation ≤ {VAL_TO.date()}, test after · 0 database reads/writes.", "",
         "## B. Baseline — every variation, every split", "", H]
    for vname in ev["variation"].unique():
        for sp in ("train", "validation", "test"):
            L.append(f"| {vname} — {sp} " + fmt(describe(ev[(ev['variation'] == vname) & (ev['split'] == sp)])))
    L.append("")
    for sp in ("train", "validation", "test"):
        b = base[base["split"] == sp]["r20"]
        L.append(f"- Unconditional 20d return (every 5th session) {sp}: mean {round(b.mean(), 2)}%, negative {round(100 * (b < 0).mean(), 1)}%")
    L += ["", "## C. Single confirmations on the primary event (TRAIN, effect = mean 20d with − without, date-clustered)", "",
          "| Condition | n with | stocks | mean20 with | mean20 without | effect | t | p |", "|---|---|---|---|---|---|---|---|"]
    for c, r in sorted([x for x in tested if len(x[0]) == 1], key=lambda x: x[1]["effect"]):
        L.append(f"| {c[0]} | {r['n']} | {r['stocks']} | {round(r['mean20_with'], 2)} | {round(r['mean20_without'], 2)} | "
                 f"{round(r['effect'], 2)} | {round(r['t'], 2)} | {r['p']:.4f} |")
    L += ["", f"## D. Combination search", "",
          f"- Rules evaluated on TRAIN: **{budget}** ({sum(1 for c, _ in tested if len(c) == 1)} singles, {sum(1 for c, _ in tested if len(c) == 2)} pairs, "
          f"{sum(1 for c, _ in tested if len(c) == 3)} triples, {sum(1 for c, _ in tested if len(c) == 4)} quadruples)",
          f"- With ≥{MIN_EV} events and ≥{MIN_STOCKS} stocks: {len(cand)} · pass BH-FDR q=0.10 with a negative effect: {len(sig)} · "
          f"also negative in validation (n≥30): {len(vrows)} · frozen shortlist: {len(final)}", "",
          "### Frozen shortlist — evaluated ONCE on the untouched test period", "",
          "| Rule | k | Train effect (n, p) | Validation effect (n) | TEST effect (t) | Test n / stocks | Test mean 20d | Test neg 20d | "
          "Test fall ≥10% | Exit-vs-hold 20d pts | Short 20d net % (PF) | Top-10-stock share |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in final:
        L.append(f"| {f['rule']} | {f['k']} | {f['train_effect']} ({f['train_n']}, {f['train_p']:.4f}) | {f['val_effect']} ({f['val_n']}) | "
                 f"**{f['test_effect']}** ({f['test_t']}) | {f['test_n']} / {f['test_stocks']} | {f['test_mean20']} | {f['test_neg20_pct']}% | "
                 f"{f['test_fall10_pct']}% | {f['test_exit_vs_hold20']} | {f['test_short20_net']} ({f['test_short_pf']}) | {f['test_top10_stock_share']}% |")
    L += ["", "## E. False breakdowns (reclaimed within 5 sessions) vs genuine — share of events with each condition", "",
          "| Condition | Train: false / genuine % | Test: false / genuine % |", "|---|---|---|"]
    for cn in fb["condition"].unique():
        a = fb[(fb["condition"] == cn) & (fb["split"] == "train")].iloc[0]
        b = fb[(fb["condition"] == cn) & (fb["split"] == "test")].iloc[0]
        L.append(f"| {cn} | {a['share_in_false_breakdowns']} / {a['share_in_genuine']} | {b['share_in_false_breakdowns']} / {b['share_in_genuine']} |")
    L += ["", "## F. Market regimes — primary event, every split", "", H]
    for g in ("regime", "volreg"):
        for rg in sorted(prim[g].dropna().unique()):
            for sp in ("train", "test"):
                L.append(f"| {g}={rg} — {sp} " + fmt(describe(prim[(prim[g] == rg) & (prim["split"] == sp)])))
    L += ["", "### Frozen shortlist by regime (TEST mean 20d, n)", ""]
    for f in final:
        cols = f["rule"].split(" + ")
        te = prim[(prim["split"] == "test") & prim[cols].all(axis=1)]
        L.append(f"- {f['rule']}: " + " · ".join(f"{rg} {round(te[te['regime'] == rg]['r20'].mean(), 2)} ({int((te['regime'] == rg).sum())})"
                                                for rg in ("Bull", "Bear", "Sideways")))
    L += ["", "## G. Trading realism — primary event (next-open execution, locks, slippage, costs)", ""]
    for sp in ("train", "validation", "test"):
        d = prim[prim["split"] == sp]
        s20 = d["short20"].dropna()
        L.append(f"- {sp}: long protection, exit at next executable open vs hold 20 sessions: mean {round(d['save20'].mean(), 2)} pts "
                 f"(beats holding {round(100 * (d['save20'] > 0).mean(), 1)}%) · research short 20d net {round(s20.mean(), 2)}% "
                 f"(win {round(100 * (s20 > 0).mean(), 1)}%, PF {round(s20[s20 > 0].sum() / -s20[s20 <= 0].sum(), 2) if (s20 <= 0).any() else None})")
    liq = prim[prim["tv20"] >= 5e6]
    L.append(f"- Liquid only (20d traded value ≥ PKR 5m), test: n {int((liq['split'] == 'test').sum())}, exit-vs-hold "
             f"{round(liq[liq['split'] == 'test']['save20'].mean(), 2)} pts")
    L += ["", "## H. Walk-forward (yearly; best single/pair chosen on all earlier years, applied to the next year)", "",
          "| Year | Rule chosen | In-sample effect | Out-of-sample effect | Out-of-sample n |", "|---|---|---|---|---|"]
    for w in wf:
        L.append(f"| {w['year']} | {w['rule']} | {w['insample_effect']} | {w['outsample_effect']} | {w['outsample_n']} |")
    L += ["", "## I. Parameter sensitivity (neighbouring thresholds; not used for selection)", "",
          "| Parameter | Split | n | effect | t |", "|---|---|---|---|---|"]
    for x in sens:
        L.append(f"| {x['param']} | {x['split']} | {x['n']} | {x['effect']} | {x['t']} |")
    L += ["", "_RESEARCH ONLY · no production code, data, alerts or workflows changed · 0 database reads/writes._"]
    REPORT.write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
