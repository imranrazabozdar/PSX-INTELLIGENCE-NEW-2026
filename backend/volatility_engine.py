"""volatility_engine.py — Volatility Compression & Expansion Intelligence Engine.

Daily (and weekly, resampled from daily) analysis of each PSX stock's
volatility state. It produces THREE separate things, never one blended score:

  * compression score (0-100)     -- how unusually quiet the stock is, no direction
  * bullish evidence score (0-100) -- independently computed upside evidence
  * bearish evidence score (0-100) -- independently computed downside evidence

plus a five-stage label (1 Early Compression, 2 Advanced Squeeze, 3 Expansion
Trigger, 4 Confirmed Expansion, 5 Failed Expansion / Exhaustion; 0 = none),
breakout/breakdown confirmation status, weekly alignment, liquidity class and
corporate-action flags.

Every score is an engineering heuristic with configurable weights, NOT a
probability. Measured historical outcomes live in run_volatility_backtest.py
(stored separately as analysis_cache 'volatility_engine_stats') and are only
displayed next to these scores, never mixed into them.

No look-ahead: every rolling statistic at bar t uses bars <= t only; every
percentile compares bar t with the PRIOR N observations; weekly features at a
daily bar come from the last COMPLETED week before it. The same per-bar code
(compute_frame + classify_series) feeds both the live scanner and the
backtest, so the two cannot drift apart.

Reused from the existing code base (not re-implemented):
  technical_analyzer.bollinger / obv / macd, obv_mfi_scanner.add_indicators
  (MFI(14), Wilder ATR(14), OBV) and _normalise, names (sector).
New here: Keltner channel, ATR(5/20), historical volatility, Donchian,
causal percentiles, ADL and a CMF *series* (technical_analyzer's CMF only
returns the latest value; same formula).

4-hour bars are deliberately NOT used: fire_engine's ohlcv_4h table is a
35-day rolling cache -- too short for 100/200-bar percentiles, and reading it
would add Turso reads.
"""
from __future__ import annotations

import copy
import math

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

import obv_mfi_scanner as _om
import technical_analyzer as _ta

# --------------------------------------------------------------------------
# Configuration -- every threshold and weight is an initial engineering
# hypothesis, not a validated PSX parameter. Override via analyze_universe(cfg=...).
# --------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "bb_period": 20, "bb_mult": 2.0,
    "kc_period": 20, "kc_mult": 1.5,
    "pct_windows": (100, 200),
    "hv_pct_window": 252,
    "min_pct_obs_frac": 0.8,          # percentile needs >= 80% of its window
    "bbw_classes": [                  # (upper percentile bound, label)
        (5, "Extreme Compression"), (10, "Very Strong Compression"),
        (20, "Strong Compression"), (50, "Moderate / Normal"),
        (80, "Elevated Volatility"), (100, "Very High Volatility")],
    # stage rules
    "early_bbw_pct": 20, "early_atr_pct": 20,
    "adv_bbw_pct": 10,
    "compression_memory": 15,         # a break must follow compression within N bars
    "box_period": 20,                 # consolidation box = prior N-bar high/low
    "breakout_rel_vol": 1.5,          # relative volume needed to confirm
    "hold_sessions": 2,               # closes beyond the level needed to confirm
    "fail_window": 10,                # back inside the box within N bars = failed
    "expansion_expiry": 20,           # stop tracking a break after N bars
    "trigger_bbw_rise": 1.25,         # BBW vs its 10-bar low -> volatility turning up
    "trigger_atr_ratio": 1.10,        # ATR5/ATR20 -> volatility turning up
    "exhaustion_atr_ratio": 1.8,
    "potential_dist_pct": 2.0,        # within 2% of the box edge = potential break
    "retest_pct": 1.5,
    "failed_display_bars": 3,
    # PSX safeguards
    "corp_action_move": 0.11,         # |1-day close move| above PSX's ~10% circuit
    "liquidity_classes": [            # (min avg daily traded value PKR, label)
        (100e6, "Highly Liquid"), (20e6, "Liquid"), (3e6, "Moderate Liquidity"), (0, "Illiquid")],
    # score weights (each block sums to 1)
    "w_compression": {"bbw": .25, "squeeze": .20, "atr": .20, "hv": .15, "donchian": .10, "volume": .10},
    "w_bull": {"structure": .20, "rs_market": .20, "volume_flow": .15, "breakout": .20,
               "trend": .15, "rs_sector": .10},
    "w_bear": {"structure": .20, "rs_market": .20, "volume_flow": .15, "breakout": .20,
               "trend": .15, "rs_sector": .10},
    "min_hist_sample": 30,
    "detail_bars": 120,
}

STAGE_LABELS = {0: "No Compression", 1: "Early Compression", 2: "Advanced Squeeze",
                3: "Expansion Trigger", 4: "Confirmed Expansion", 5: "Failed Expansion / Exhaustion"}


def cfg_with(overrides=None):
    c = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in (overrides or {}).items():
        c[k] = v
    return c


# --------------------------------------------------------------------------
# Primitive calculations
# --------------------------------------------------------------------------
def pct_rank_prior(x, window, min_frac=0.8):
    """Percentile (0-100) of x[t] within the PRIOR `window` observations
    x[t-window:t] -- never including x[t] itself or anything after it.
    Ties count half. NaN until enough prior observations exist."""
    x = np.asarray(x, float)
    n = len(x)
    out = np.full(n, np.nan)
    if n <= window:
        return out
    win = sliding_window_view(x[:-1], window)            # win[k] = x[k:k+window], for t = k+window
    cur = x[window:]
    valid = ~np.isnan(win)
    cnt = valid.sum(1)
    with np.errstate(invalid="ignore"):
        less = ((win < cur[:, None]) & valid).sum(1)
        eq = ((win == cur[:, None]) & valid).sum(1)
        pct = (less + 0.5 * eq) / np.where(cnt == 0, 1, cnt) * 100
    ok = (cnt >= window * min_frac) & ~np.isnan(cur)
    out[window:] = np.where(ok, pct, np.nan)
    return out


def wilder_atr(h, l, c, n):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adl(h, l, c, v):
    rng = (h - l).replace(0, np.nan)
    mfm = (((c - l) - (h - c)) / rng).fillna(0.0)
    return (mfm * v).cumsum()


def cmf_series(h, l, c, v, n=20):
    """Same formula as technical_analyzer.chaikin_money_flow, as a series."""
    rng = (h - l).replace(0, np.nan)
    mfm = (((c - l) - (h - c)) / rng).fillna(0.0)
    vs = v.rolling(n).sum()
    return (mfm * v).rolling(n).sum() / vs.replace(0, np.nan)


def _run_length(mask):
    out = np.zeros(len(mask), int)
    r = 0
    for i, m in enumerate(mask):
        r = r + 1 if m else 0
        out[i] = r
    return out


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h) * 100, 1), round(min(1, c + h) * 100, 1))


# --------------------------------------------------------------------------
# Per-symbol feature frame (all causal)
# --------------------------------------------------------------------------
def weekly_features(d: pd.DataFrame) -> pd.DataFrame:
    """Weekly bars from daily, then shifted so each daily row only sees the
    last COMPLETED week strictly before its own week."""
    w = d.set_index("Date").resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    if len(w) < 15:
        return pd.DataFrame(index=d.index, columns=["wk_bbw_pct", "wk_squeeze", "wk_trend", "wk_break"])
    up, mid, lo = _ta.bollinger(w["Close"], 20, 2)
    bbw = (up - lo) / mid
    atr = wilder_atr(w["High"], w["Low"], w["Close"], 10)
    ema = w["Close"].ewm(span=20, adjust=False).mean()
    sq = (up < ema + 1.5 * atr) & (lo > ema - 1.5 * atr)
    sma10 = w["Close"].rolling(10).mean()
    trend = np.where((w["Close"] > sma10) & (sma10 > sma10.shift(2)), 1,
                     np.where((w["Close"] < sma10) & (sma10 < sma10.shift(2)), -1, 0))
    hi10, lo10 = w["High"].shift(1).rolling(10).max(), w["Low"].shift(1).rolling(10).min()
    brk = np.where(w["Close"] > hi10, 1, np.where(w["Close"] < lo10, -1, 0))
    wf = pd.DataFrame({"wk_bbw_pct": pct_rank_prior(bbw.to_numpy(), 52), "wk_squeeze": sq.astype(float),
                       "wk_trend": trend.astype(float), "wk_break": brk.astype(float)}, index=w.index)
    wf = wf.where(sma10.notna())
    # week ending Friday F applies to days AFTER F (the next week onward)
    wf.index = wf.index + pd.Timedelta(days=1)
    wf.index.name = "wk"
    out = pd.merge_asof(d[["Date"]], wf.reset_index().sort_values("wk"),
                        left_on="Date", right_on="wk", direction="backward")
    return out.drop(columns=["Date", "wk"]).set_index(d.index)


def compute_frame(df: pd.DataFrame, cfg=None, market: pd.Series | None = None,
                  sector: pd.Series | None = None) -> pd.DataFrame:
    """All per-bar features for one symbol. `market` / `sector` are close-like
    index level series indexed by date (optional)."""
    cfg = cfg or DEFAULT_CONFIG
    d = _om.add_indicators(_om._normalise(df))              # reuse: MFI, ATR(14), OBV, SMA20
    h, l, c, v = d["High"], d["Low"], d["Close"], d["Volume"]
    mf = cfg["min_pct_obs_frac"]
    w1, w2 = cfg["pct_windows"]

    up, mid, lo = _ta.bollinger(c, cfg["bb_period"], cfg["bb_mult"])   # reuse
    d["BB_up"], d["BB_mid"], d["BB_lo"] = up, mid, lo
    d["BBW"] = (up - lo) / mid
    d["BBW_p100"] = pct_rank_prior(d["BBW"].to_numpy(), w1, mf)
    d["BBW_p200"] = pct_rank_prior(d["BBW"].to_numpy(), w2, mf)

    d["ATR5"] = wilder_atr(h, l, c, 5)
    d["ATR20"] = wilder_atr(h, l, c, 20)
    ema = c.ewm(span=cfg["kc_period"], adjust=False).mean()
    d["KC_up"] = ema + cfg["kc_mult"] * d["ATR20"]
    d["KC_lo"] = ema - cfg["kc_mult"] * d["ATR20"]
    d["SQZ"] = ((up < d["KC_up"]) & (lo > d["KC_lo"])).astype(bool)
    d["SQZ_run"] = _run_length(d["SQZ"].to_numpy())
    # squeeze tightness: BB width relative to KC width (lower = tighter)
    d["SQZ_tight"] = (up - lo) / (d["KC_up"] - d["KC_lo"])

    d["ATRP"] = d["ATR20"] / c * 100                         # price-normalised
    d["ATRP_p100"] = pct_rank_prior(d["ATRP"].to_numpy(), w1, mf)
    d["ATRP_p200"] = pct_rank_prior(d["ATRP"].to_numpy(), w2, mf)
    d["ATR_ratio"] = d["ATR5"] / d["ATR20"]
    d["ATR_chg5"] = (d["ATR20"] / d["ATR20"].shift(5) - 1) * 100
    d["ATR_chg10"] = (d["ATR20"] / d["ATR20"].shift(10) - 1) * 100

    lr = np.log(c / c.shift())
    for n in (10, 20, 60):
        d[f"HV{n}"] = lr.rolling(n).std() * math.sqrt(252) * 100
    d["HV20_p252"] = pct_rank_prior(d["HV20"].to_numpy(), cfg["hv_pct_window"], mf)
    d["HV_ratio"] = d["HV20"] / d["HV60"]

    for n in (20, 55):
        d[f"DC{n}_hi"] = h.rolling(n).max()
        d[f"DC{n}_lo"] = l.rolling(n).min()
    d["DCW"] = (d["DC20_hi"] - d["DC20_lo"]) / c * 100
    d["DCW_p200"] = pct_rank_prior(d["DCW"].to_numpy(), w2, mf)
    for n in (5, 10, 20):
        d[f"RNG{n}"] = (h.rolling(n).max() - l.rolling(n).min()) / c * 100
    d["RNG_contract"] = d["RNG5"] / d["RNG20"]
    bp = cfg["box_period"]
    d["BOX_hi"] = h.shift(1).rolling(bp).max()
    d["BOX_lo"] = l.shift(1).rolling(bp).min()
    d["dist_hi20"] = (c / d["DC20_hi"] - 1) * 100
    d["dist_lo20"] = (c / d["DC20_lo"] - 1) * 100

    vma20 = v.shift(1).rolling(20).mean()
    vma50 = v.shift(1).rolling(50).mean()
    d["RV20"] = v / vma20
    d["RV50"] = v / vma50
    d["VOL_p100"] = pct_rank_prior(v.rolling(5).mean().to_numpy(), w1, mf)
    d["VOL_tr5"] = v.rolling(5).mean() / v.shift(5).rolling(5).mean()
    d["VOL_tr10"] = v.rolling(10).mean() / v.shift(10).rolling(10).mean()
    upv = v.where(c > c.shift(), 0.0).rolling(20).sum()
    dnv = v.where(c < c.shift(), 0.0).rolling(20).sum()
    d["UPDN_vol"] = upv / dnv.replace(0, np.nan)
    d["OBV_slope20"] = (d["OBV"] - d["OBV"].shift(20)) / (v.rolling(20).mean() * 20)
    d["ADL"] = adl(h, l, c, v)
    d["ADL_slope20"] = (d["ADL"] - d["ADL"].shift(20)) / (v.rolling(20).mean() * 20)
    d["CMF20"] = cmf_series(h, l, c, v, 20)
    d["MFI_chg5"] = d["MFI"] - d["MFI"].shift(5)
    _, _, hist = _ta.macd(c)                                 # reuse
    d["MACD_hist"] = hist
    d["SMA50"] = c.rolling(50).mean()
    d["TV20"] = (c * v).rolling(20).mean()                   # traded value PKR
    d["ZERO_vol60"] = (v <= 0).astype(int).rolling(60, min_periods=1).sum()
    d["RET1"] = c / c.shift() - 1
    d["CA_flag"] = d["RET1"].abs() > cfg["corp_action_move"]
    d["CA_recent20"] = d["CA_flag"].astype(int).rolling(20, min_periods=1).sum() > 0
    d["ret20"] = (c / c.shift(20) - 1) * 100
    d["ret60"] = (c / c.shift(60) - 1) * 100

    def _rel(ix, name):
        if ix is None or len(ix) == 0:
            d[name + "20"] = np.nan
            d[name + "60"] = np.nan
            return
        s = pd.Series(ix).sort_index()
        s = s[~s.index.duplicated()]
        al = s.reindex(pd.DatetimeIndex(d["Date"]), method="ffill").to_numpy(float)
        al = pd.Series(al, index=d.index)
        d[name + "20"] = d["ret20"] - (al / al.shift(20) - 1) * 100
        d[name + "60"] = d["ret60"] - (al / al.shift(60) - 1) * 100

    _rel(market, "RSM")
    _rel(sector, "RSS")
    if market is not None and len(market):
        s = pd.Series(market).sort_index()
        s = s[~s.index.duplicated()]
        al = s.reindex(pd.DatetimeIndex(d["Date"]), method="ffill")
        d["MKT_ret1"] = (al / al.shift() - 1).to_numpy()
    else:
        d["MKT_ret1"] = np.nan

    wk = weekly_features(d)
    for col in wk.columns:
        d[col] = pd.to_numeric(wk[col], errors="coerce")
    return d


# --------------------------------------------------------------------------
# Five-stage state machine (shared by live scan and backtest)
# --------------------------------------------------------------------------
def classify_series(d: pd.DataFrame, cfg=None) -> pd.DataFrame:
    cfg = cfg or DEFAULT_CONFIG
    n = len(d)
    C, H, L = d["Close"].to_numpy(), d["High"].to_numpy(), d["Low"].to_numpy()
    bbw_p, atr_p = d["BBW_p100"].to_numpy(), d["ATRP_p100"].to_numpy()
    sqz = d["SQZ"].to_numpy()
    dcw = d["DCW"].to_numpy()
    rngc = d["RNG_contract"].to_numpy()
    atr_ratio = d["ATR_ratio"].to_numpy()
    vtr = d["VOL_tr10"].to_numpy()
    bbw = d["BBW"].to_numpy()
    rv = d["RV20"].to_numpy()
    box_hi, box_lo = d["BOX_hi"].to_numpy(), d["BOX_lo"].to_numpy()
    hist = d["MACD_hist"].to_numpy()
    ca20 = d["CA_recent20"].to_numpy()

    with np.errstate(invalid="ignore"):
        dcw_decl = dcw < np.roll(dcw, 5)
        dcw_decl[:5] = False
        comp1 = (bbw_p < cfg["early_bbw_pct"]) & ((atr_p < cfg["early_atr_pct"]) | dcw_decl | (rngc < 0.5))
        extra = ((atr_ratio < 1).astype(int) + (rngc < 0.5).astype(int) + (vtr < 1).astype(int))
        comp2 = (bbw_p < cfg["adv_bbw_pct"]) & sqz & (extra >= 2)
    comp_any = comp1 | comp2
    mem = cfg["compression_memory"]
    recent = np.zeros(n, bool)
    last_comp = -10 ** 9
    for t in range(n):
        recent[t] = (t - last_comp) <= mem      # compression in PRIOR bars only
        if comp_any[t]:
            last_comp = t

    bbw_min10 = pd.Series(bbw).rolling(10, min_periods=1).min().to_numpy()
    stage = np.zeros(n, int)
    detail = np.array([""] * n, dtype=object)
    direction = np.zeros(n, int)
    up_status = np.array(["none"] * n, dtype=object)
    dn_status = np.array(["none"] * n, dtype=object)
    level = np.full(n, np.nan)
    break_rv = np.full(n, np.nan)
    since = np.full(n, -1)

    active = None
    fail_left, fail_label, fail_dir = 0, "", 0
    hold, fw, exp = cfg["hold_sessions"], cfg["fail_window"], cfg["expansion_expiry"]
    thr = cfg["breakout_rel_vol"]
    for t in range(n):
        if np.isnan(box_hi[t]) or np.isnan(bbw_p[t]) and np.isnan(atr_p[t]):
            continue
        s, lab, dr = 0, "", 0
        if active is not None:
            k = t - active["t0"]
            dirn, lvl, opp = active["dir"], active["level"], active["opp"]
            inside = C[t] < lvl if dirn > 0 else C[t] > lvl
            if inside and k <= fw:
                trap = C[t] < opp if dirn > 0 else C[t] > opp
                if dirn > 0:
                    lab = "Bull trap" if trap else "Failed bullish breakout"
                else:
                    lab = "Bear trap" if trap else "Failed bearish breakdown"
                s, dr = 5, dirn
                fail_left, fail_label, fail_dir = cfg["failed_display_bars"], lab, dirn
                active = None
            elif k > exp or (inside and k > fw):
                active = None
            else:
                dr = dirn
                if k >= hold and active["rv"] >= thr:
                    if (atr_ratio[t] > cfg["exhaustion_atr_ratio"] and t >= 2
                            and ((dirn > 0 and hist[t] < hist[t - 1] < hist[t - 2])
                                 or (dirn < 0 and hist[t] > hist[t - 1] > hist[t - 2]))):
                        s, lab = 5, "Expansion exhaustion"
                        fail_left, fail_label, fail_dir = cfg["failed_display_bars"], lab, dirn
                        active = None
                    else:
                        s = 4
                        lab = "Confirmed breakout" if dirn > 0 else "Confirmed breakdown"
                        active["confirmed"] = True
                else:
                    s = 3
                    lab = (("Breakout attempt" if dirn > 0 else "Breakdown attempt")
                           + (" (low volume)" if active["rv"] < thr else ""))
                if active is not None:
                    level[t], break_rv[t], since[t] = lvl, active["rv"], k
                    st_name = ("confirmed" if s == 4 else "attempt")
                    if s == 4:
                        # retest = price first moved clearly away (> 2x retest_pct),
                        # then a later bar's low (high, for breakdowns) came back
                        # within retest_pct of the level while closes held.
                        t0, rp = active["t0"], cfg["retest_pct"]
                        cl_ = C[t0 + 1:t + 1]
                        ext = (L if dirn > 0 else H)[t0 + 1:t + 1]
                        away = (cl_ / lvl - 1) * 100 * dirn > 2 * rp
                        if away.any():
                            j = int(np.argmax(away))
                            near = np.abs(ext[j + 1:] / lvl - 1) * 100 <= rp
                            if near.any():
                                st_name = "retested"
                    if dirn > 0:
                        up_status[t] = st_name
                    else:
                        dn_status[t] = st_name
        if active is None and s == 0:
            if recent[t] and not ca20[t] and C[t] > box_hi[t]:
                active = {"dir": 1, "level": box_hi[t], "opp": box_lo[t], "t0": t,
                          "rv": rv[t] if not np.isnan(rv[t]) else 0.0}
            elif recent[t] and not ca20[t] and C[t] < box_lo[t]:
                active = {"dir": -1, "level": box_lo[t], "opp": box_hi[t], "t0": t,
                          "rv": rv[t] if not np.isnan(rv[t]) else 0.0}
            if active is not None:
                s, dr = 3, active["dir"]
                lab = (("Breakout attempt" if dr > 0 else "Breakdown attempt")
                       + (" (low volume)" if active["rv"] < thr else ""))
                level[t], break_rv[t], since[t] = active["level"], active["rv"], 0
                (up_status if dr > 0 else dn_status)[t] = "attempt"
                fail_left = 0
            elif fail_left > 0:
                s, lab, dr = 5, fail_label, fail_dir
                fail_left -= 1
                (up_status if fail_dir > 0 else dn_status)[t] = "failed"
            elif comp2[t]:
                s, lab = 2, "Advanced squeeze"
            elif comp1[t]:
                s, lab = 1, "Early compression"
            elif recent[t] and not ca20[t] and bbw[t] > cfg["trigger_bbw_rise"] * bbw_min10[t] and atr_ratio[t] > cfg["trigger_atr_ratio"]:
                s, lab = 3, "Expansion trigger (volatility rising inside range)"
        elif s == 5 and fail_dir:
            (up_status if fail_dir > 0 else dn_status)[t] = "failed"
        # potential break / intraday-only penetration when nothing stronger
        if s in (1, 2) or (s == 0 and recent[t]):
            if H[t] > box_hi[t] >= C[t]:
                up_status[t] = "attempt (intraday only)"
            elif (box_hi[t] - C[t]) / C[t] * 100 <= cfg["potential_dist_pct"]:
                up_status[t] = "potential"
            if L[t] < box_lo[t] <= C[t]:
                dn_status[t] = "attempt (intraday only)"
            elif (C[t] - box_lo[t]) / C[t] * 100 <= cfg["potential_dist_pct"]:
                dn_status[t] = "potential"
        stage[t], detail[t], direction[t] = s, lab or STAGE_LABELS[s], dr
    return pd.DataFrame({"stage": stage, "stage_detail": detail, "stage_dir": direction,
                         "up_status": up_status, "dn_status": dn_status, "break_level": level,
                         "break_rv": break_rv, "bars_since_break": since,
                         "comp1": comp1, "comp2": comp2}, index=d.index)


# --------------------------------------------------------------------------
# Scores (at one bar)
# --------------------------------------------------------------------------
def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _clip01(x):
    return None if x is None else max(0.0, min(1.0, x))


def _weighted(parts, weights):
    """Sum of weight*subscore over AVAILABLE parts only; missing parts score 0
    (no points for unavailable data). Returns (score, coverage%)."""
    tot, cov = 0.0, 0.0
    for k, w in weights.items():
        v = parts.get(k)
        if v is not None:
            tot += w * v
            cov += w
    return round(tot * 100, 1), round(cov * 100)


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


_BRK = {"confirmed": 1.0, "retested": 1.0, "attempt": 0.5, "attempt (intraday only)": 0.25,
        "potential": 0.25, "none": 0.0, "failed": 0.0}


def scores_at(d: pd.DataFrame, cl: pd.DataFrame, t: int, cfg=None) -> dict:
    cfg = cfg or DEFAULT_CONFIG
    r = d.iloc[t]
    g = lambda k: _num(r.get(k))
    # ---- compression ----
    bbw = _mean([g("BBW_p100"), g("BBW_p200")])
    atrp = _mean([g("ATRP_p100"), g("ATRP_p200")])
    vol5 = _num(d["RV20"].iloc[max(0, t - 4):t + 1].mean())
    comp_parts = {
        "bbw": None if bbw is None else 1 - bbw / 100,
        "squeeze": (0.6 + 0.4 * min(int(r["SQZ_run"]), 20) / 20) if bool(r["SQZ"]) else (0.0 if g("KC_up") is not None else None),
        "atr": None if atrp is None else 1 - atrp / 100,
        "hv": None if g("HV20_p252") is None else 1 - g("HV20_p252") / 100,
        "donchian": None if g("DCW_p200") is None else 1 - g("DCW_p200") / 100,
        "volume": None if vol5 is None else _clip01((1.2 - vol5) / 0.8),
    }
    comp, comp_cov = _weighted(comp_parts, cfg["w_compression"])

    # ---- directional evidence (bull and bear computed independently) ----
    lo = d["Low"].to_numpy()
    hi = d["High"].to_numpy()
    c = g("Close")
    box_hi, box_lo = g("BOX_hi"), g("BOX_lo")
    pos = None
    if box_hi and box_lo and box_hi > box_lo:
        pos = _clip01((c - box_lo) / (box_hi - box_lo))
    hl = ll = None
    if t >= 20:
        a, b = lo[t - 9:t + 1].min(), lo[t - 19:t - 9].min()
        hl = 1.0 if a > b else 0.0
        a2, b2 = hi[t - 9:t + 1].max(), hi[t - 19:t - 9].max()
        ll = 1.0 if a2 < b2 else 0.0
    rsm20, rsm60, rss20 = g("RSM20"), g("RSM60"), g("RSS20")
    obv_s, cmf, mfi_c = g("OBV_slope20"), g("CMF20"), g("MFI_chg5")
    sma20, sma50, wk = g("SMA20"), g("SMA50"), g("wk_trend")
    up_st, dn_st = cl["up_status"].iloc[t], cl["dn_status"].iloc[t]

    def _rs(x, sign):
        return None if x is None else _clip01(sign * x / 10)

    bull = {
        "structure": _mean([hl, pos]),
        "rs_market": _mean([_rs(rsm20, 1), _rs(rsm60, 1)]),
        "volume_flow": _mean([None if obv_s is None else float(obv_s > 0),
                              None if cmf is None else float(cmf > 0),
                              None if mfi_c is None else float(mfi_c > 0)]),
        "breakout": _BRK.get(up_st, 0.0),
        "trend": _mean([None if None in (c, sma20, sma50) else float(c > sma50 and sma20 > sma50),
                        None if wk is None else float(wk > 0)]),
        "rs_sector": _rs(rss20, 1),
    }
    bear = {
        "structure": _mean([ll, None if pos is None else 1 - pos]),
        "rs_market": _mean([_rs(rsm20, -1), _rs(rsm60, -1)]),
        "volume_flow": _mean([None if obv_s is None else float(obv_s < 0),
                              None if cmf is None else float(cmf < 0),
                              None if mfi_c is None else float(mfi_c < 0)]),
        "breakout": _BRK.get(dn_st, 0.0),
        "trend": _mean([None if None in (c, sma20, sma50) else float(c < sma50 and sma20 < sma50),
                        None if wk is None else float(wk < 0)]),
        "rs_sector": _rs(rss20, -1),
    }
    bull_s, bull_cov = _weighted(bull, cfg["w_bull"])
    bear_s, bear_cov = _weighted(bear, cfg["w_bear"])

    # ---- expansion confirmation (per direction) ----
    def _exp(status, dirn):
        brk = {"confirmed": 1, "retested": 1, "attempt": .5}.get(status, 0)
        rvb = _num(cl["break_rv"].iloc[t])
        bbw_up = g("BBW") is not None and t >= 5 and g("BBW") > _num(d["BBW"].iloc[t - 5]) if g("BBW") else False
        parts = {"b": brk, "rv": 0 if not brk or rvb is None else _clip01(rvb / cfg["breakout_rel_vol"]),
                 "bbw": float(bool(bbw_up)), "atr": float((g("ATR_ratio") or 0) > 1),
                 "hold": float(status in ("confirmed", "retested"))}
        return round(100 * (.40 * parts["b"] + .20 * parts["rv"] + .15 * parts["bbw"]
                            + .15 * parts["atr"] + .10 * parts["hold"]), 1)

    return {"compression_score": comp, "compression_coverage": comp_cov,
            "bull_score": bull_s, "bull_coverage": bull_cov,
            "bear_score": bear_s, "bear_coverage": bear_cov,
            "bull_expansion_score": _exp(up_st, 1), "bear_expansion_score": _exp(dn_st, -1),
            "_bull_parts": bull, "_bear_parts": bear, "_comp_parts": comp_parts}


# --------------------------------------------------------------------------
# Classifications
# --------------------------------------------------------------------------
def bbw_class(p, cfg=None):
    cfg = cfg or DEFAULT_CONFIG
    if p is None:
        return "Insufficient history"
    for ub, lab in cfg["bbw_classes"]:
        if p <= ub:
            return lab
    return cfg["bbw_classes"][-1][1]


def liquidity_class(tv, cfg=None):
    cfg = cfg or DEFAULT_CONFIG
    if tv is None:
        return "Unknown"
    for mn, lab in cfg["liquidity_classes"]:
        if tv >= mn:
            return lab
    return "Illiquid"


def mtf_alignment(bull, bear, wk_trend, wk_break):
    """Daily evidence balance vs weekly structure -> five-level label."""
    dd = (bull or 0) - (bear or 0)
    daily = 1 if dd >= 15 else -1 if dd <= -15 else 0
    wkv = None if wk_trend is None else (wk_trend + (wk_break or 0))
    weekly = None if wkv is None else (1 if wkv > 0 else -1 if wkv < 0 else 0)
    if weekly is None:
        return {1: "Moderate Bullish Alignment", -1: "Moderate Bearish Alignment"}.get(daily, "Conflicting Alignment") + " (daily only)"
    if daily == 1 and weekly == 1:
        return "Strong Bullish Alignment"
    if daily == -1 and weekly == -1:
        return "Strong Bearish Alignment"
    if daily * weekly == -1:
        return "Conflicting Alignment"
    if 1 in (daily, weekly):
        return "Moderate Bullish Alignment"
    if -1 in (daily, weekly):
        return "Moderate Bearish Alignment"
    return "Conflicting Alignment"


def _r(x, nd=2):
    x = _num(x)
    return None if x is None else round(x, nd)


# --------------------------------------------------------------------------
# Live analysis of one symbol (latest bar) + narrative from real numbers
# --------------------------------------------------------------------------
def analyze_symbol(sym, df, cfg=None, market=None, sector=None, sector_name=None, stats=None):
    cfg = cfg or DEFAULT_CONFIG
    d = compute_frame(df, cfg, market, sector)
    if len(d) < 60:
        return None, None
    cl = classify_series(d, cfg)
    t = len(d) - 1
    r = d.iloc[t]
    sc = scores_at(d, cl, t, cfg)
    g = lambda k, nd=2: _r(r.get(k), nd)
    stage = int(cl["stage"].iloc[t])
    ca_dates = d.loc[d["CA_flag"] & (d.index > t - 60), "Date"].dt.strftime("%Y-%m-%d").tolist()
    tv = g("TV20", 0)
    row = {
        "symbol": sym, "date": r["Date"].strftime("%Y-%m-%d"), "close": g("Close"),
        "sector": sector_name,
        "compression_score": sc["compression_score"], "compression_coverage": sc["compression_coverage"],
        "bull_score": sc["bull_score"], "bear_score": sc["bear_score"],
        "bull_expansion_score": sc["bull_expansion_score"], "bear_expansion_score": sc["bear_expansion_score"],
        "evidence_coverage": min(sc["bull_coverage"], sc["bear_coverage"]),
        "stage": stage, "stage_label": STAGE_LABELS[stage], "stage_detail": cl["stage_detail"].iloc[t],
        "stage_dir": int(cl["stage_dir"].iloc[t]),
        "up_status": cl["up_status"].iloc[t], "dn_status": cl["dn_status"].iloc[t],
        "break_level": _r(cl["break_level"].iloc[t]),
        "bars_since_break": int(cl["bars_since_break"].iloc[t]),
        "bbw": g("BBW", 4), "bbw_pct100": g("BBW_p100", 1), "bbw_pct200": g("BBW_p200", 1),
        "bbw_class": bbw_class(g("BBW_p100", 1), cfg),
        "squeeze_on": bool(r["SQZ"]), "squeeze_run": int(r["SQZ_run"]),
        "squeeze_tightening": bool(_num(r["SQZ_tight"]) is not None and t >= 3
                                   and r["SQZ_tight"] < d["SQZ_tight"].iloc[t - 3]),
        "squeeze_released": bool(not r["SQZ"] and t >= 1 and d["SQZ"].iloc[max(0, t - 5):t].any()),
        "atr5": g("ATR5"), "atr14": g("ATR"), "atr20": g("ATR20"), "atr_pct_price": g("ATRP"),
        "atr_pct100": g("ATRP_p100", 1), "atr_pct200": g("ATRP_p200", 1),
        "atr_ratio": g("ATR_ratio"), "atr_chg5": g("ATR_chg5", 1), "atr_chg10": g("ATR_chg10", 1),
        "hv10": g("HV10", 1), "hv20": g("HV20", 1), "hv60": g("HV60", 1),
        "hv20_pct252": g("HV20_p252", 1), "hv_ratio": g("HV_ratio"),
        "dc20_hi": g("DC20_hi"), "dc20_lo": g("DC20_lo"), "dc55_hi": g("DC55_hi"), "dc55_lo": g("DC55_lo"),
        "dc_width": g("DCW"), "dc_width_pct200": g("DCW_p200", 1),
        "range5": g("RNG5"), "range10": g("RNG10"), "range20": g("RNG20"), "range_contract": g("RNG_contract"),
        "dist_hi20": g("dist_hi20"), "dist_lo20": g("dist_lo20"),
        "box_hi": g("BOX_hi"), "box_lo": g("BOX_lo"),
        "support": g("DC55_lo"), "resistance": g("DC55_hi"),
        "rv20": g("RV20"), "rv50": g("RV50"), "vol_pct100": g("VOL_p100", 1),
        "vol_trend5": g("VOL_tr5"), "vol_trend10": g("VOL_tr10"), "updown_vol": g("UPDN_vol"),
        "obv_slope20": g("OBV_slope20", 3), "adl_slope20": g("ADL_slope20", 3),
        "cmf20": g("CMF20", 3), "mfi": g("MFI", 1), "mfi_chg5": g("MFI_chg5", 1),
        "rs_market20": g("RSM20", 1), "rs_market60": g("RSM60", 1), "rs_sector20": g("RSS20", 1),
        "wk_bbw_pct": g("wk_bbw_pct", 1), "wk_squeeze": None if _num(r.get("wk_squeeze")) is None else bool(r["wk_squeeze"]),
        "wk_trend": g("wk_trend", 0), "wk_break": g("wk_break", 0),
        "avg_traded_value": tv, "avg_volume20": _r(d["Volume"].iloc[-20:].mean(), 0),
        "zero_vol_sessions60": int(r["ZERO_vol60"]),
        "liquidity": liquidity_class(tv, cfg),
        "corporate_action_dates": ca_dates,
    }
    row["volume_state"] = _volume_state(row)
    row["mtf_alignment"] = mtf_alignment(row["bull_score"], row["bear_score"], row["wk_trend"], row["wk_break"])
    row["weekly_compressed_daily_expanding"] = bool(
        (row["wk_bbw_pct"] is not None and row["wk_bbw_pct"] < 20 or row["wk_squeeze"])
        and stage in (3, 4))
    mret = _num(r.get("MKT_ret1"))
    row["market_wide_move"] = bool(stage in (3, 4) and mret is not None and abs(mret) >= 0.015
                                   and np.sign(mret) == row["stage_dir"])
    row["hist"] = attach_stats(row, stats, cfg)
    row["narrative"] = narrative(row)

    n = cfg["detail_bars"]
    tail = d.iloc[-n:]
    detail = {
        "date": tail["Date"].dt.strftime("%Y-%m-%d").tolist(),
        "close": [_r(x) for x in tail["Close"]], "high": [_r(x) for x in tail["High"]],
        "low": [_r(x) for x in tail["Low"]],
        "bbw_pct": [_r(x, 1) for x in tail["BBW_p100"]], "atr_pct": [_r(x, 1) for x in tail["ATRP_p100"]],
        "squeeze": [int(x) for x in tail["SQZ"]], "box_hi": [_r(x) for x in tail["BOX_hi"]],
        "box_lo": [_r(x) for x in tail["BOX_lo"]], "stage": [int(x) for x in cl["stage"].iloc[-n:]],
        "cmf": [_r(x, 3) for x in tail["CMF20"]], "mfi": [_r(x, 1) for x in tail["MFI"]],
        "obv": [_r(x, 0) for x in tail["OBV"]],
    }
    return row, detail


def _volume_state(r):
    """Descriptive only -- never labels accumulation from low volume alone."""
    vt, obv, cmf, rv = r["vol_trend10"], r["obv_slope20"], r["cmf20"], r["rv20"]
    if rv is not None and rv >= 2.5:
        return "Unusual participation spike (direction from price/flow, not volume alone)"
    if vt is None:
        return "Insufficient data"
    if vt < 0.8:
        if (obv or 0) > 0 and (cmf or 0) > 0:
            return "Volume contracting with positive money flow (possible supply absorption)"
        if (obv or 0) < 0 and (cmf or 0) < 0:
            return "Volume contracting with negative money flow (possible distribution)"
        return "Volume contracting, flow mixed (weak participation)"
    return "Volume not contracting"


def attach_stats(row, stats, cfg=None):
    """Look up MEASURED historical outcomes for this stock's current setup
    bucket (from the separate backtest). Never derived from the scores."""
    cfg = cfg or DEFAULT_CONFIG
    out = {"available": False, "label": "INSUFFICIENT HISTORICAL EVIDENCE", "n": 0}
    if not stats or not stats.get("buckets"):
        out["note"] = "Historical probability engine has not been run yet."
        return out
    key = setup_bucket(row["stage"], row["stage_dir"], row["bull_score"], row["bear_score"])
    b = stats["buckets"].get(key)
    out["bucket"] = key
    if not b:
        return out
    out.update({k: b.get(k) for k in ("n", "period", "p_up_10d", "p_up_10d_ci", "p_down_10d", "p_down_10d_ci",
                                      "mean_10d", "median_10d", "p_abs5_10d", "mfe_20d", "mae_20d",
                                      "long_target_first", "short_target_first", "oos_n", "oos_p_up_10d")})
    if (b.get("n") or 0) >= cfg["min_hist_sample"]:
        out["available"] = True
        out["label"] = f"n={b['n']} ({b.get('period', '')})"
    return out


def setup_bucket(stage, stage_dir, bull, bear):
    """Bucket used both when recording historical events and at lookup time."""
    lean = "bull" if (bull or 0) - (bear or 0) >= 15 else "bear" if (bear or 0) - (bull or 0) >= 15 else "neutral"
    if stage in (3, 4, 5) and stage_dir:
        return f"s{stage}_{'up' if stage_dir > 0 else 'down'}"
    return f"s{stage}_{lean}"


def narrative(r):
    """Bull case / bear case / confirmation / invalidation from the actual
    measured values -- no generic text."""
    bull, bear = [], []
    f = lambda x, nd=1: "n/a" if x is None else f"{x:.{nd}f}"
    if (r["rs_market20"] or 0) > 0:
        bull.append(f"Outperforming the market by {f(r['rs_market20'])} pts over 20 sessions")
    elif r["rs_market20"] is not None:
        bear.append(f"Underperforming the market by {f(-r['rs_market20'])} pts over 20 sessions")
    if r["rs_sector20"] is not None:
        (bull if r["rs_sector20"] > 0 else bear).append(
            f"{'Ahead of' if r['rs_sector20'] > 0 else 'Behind'} its sector by {f(abs(r['rs_sector20']))} pts (20d)")
    if r["obv_slope20"] is not None:
        (bull if r["obv_slope20"] > 0 else bear).append(f"OBV 20-session slope {f(r['obv_slope20'], 2)}")
    if r["cmf20"] is not None:
        (bull if r["cmf20"] > 0 else bear).append(f"CMF(20) {f(r['cmf20'], 2)}")
    if r["mfi_chg5"] is not None:
        (bull if r["mfi_chg5"] > 0 else bear).append(f"MFI {f(r['mfi'])} ({'+' if r['mfi_chg5'] > 0 else ''}{f(r['mfi_chg5'])} in 5 sessions)")
    if r["wk_trend"] == 1:
        bull.append("Weekly trend up (close above rising 10-week average)")
    elif r["wk_trend"] == -1:
        bear.append("Weekly trend down (close below falling 10-week average)")
    if r["up_status"] not in ("none",):
        bull.append(f"Upside break status: {r['up_status']}")
    if r["dn_status"] not in ("none",):
        bear.append(f"Downside break status: {r['dn_status']}")
    bh, bl, rvt = r["box_hi"], r["box_lo"], 1.5
    confirm_up = (f"Two or more closes above {f(bh, 2)} (20-session range high) with the breakout "
                  f"session's volume ≥ {rvt}× its 20-day average" if bh else "n/a")
    confirm_dn = (f"Two or more closes below {f(bl, 2)} (20-session range low) with breakdown "
                  f"volume ≥ {rvt}× its 20-day average" if bl else "n/a")
    if r["stage"] in (3, 4) and r["break_level"]:
        inval = (f"A close back {'below' if r['stage_dir'] > 0 else 'above'} {f(r['break_level'], 2)} "
                 f"(the broken level) within 10 sessions marks a failed "
                 f"{'breakout' if r['stage_dir'] > 0 else 'breakdown'}")
    elif r["stage"] in (1, 2):
        inval = (f"Compression ends without direction if BBW percentile rises above 50 "
                 f"(now {f(r['bbw_pct100'])}) while price stays inside {f(bl, 2)}–{f(bh, 2)}")
    else:
        inval = "No active compression setup to invalidate"
    warn = []
    if r["corporate_action_dates"]:
        warn.append("Possible corporate action / price adjustment on " + ", ".join(r["corporate_action_dates"])
                    + " — volatility readings around it are unreliable")
    if r["liquidity"] == "Illiquid":
        warn.append("Illiquid: signals can be moved by a few trades")
    if r["market_wide_move"]:
        warn.append("Today's move matches a broad market move — may not be stock-specific")
    if "Conflicting" in r.get("mtf_alignment", ""):
        warn.append("Daily and weekly pictures conflict")
    return {"bull_case": bull, "bear_case": bear, "confirm_up": confirm_up,
            "confirm_down": confirm_dn, "invalidation": inval, "warnings": warn}


# --------------------------------------------------------------------------
# Market / sector proxies
# --------------------------------------------------------------------------
def build_indices(frames: dict, sectors: dict, market_series=None):
    """frames: {sym: normalised df}. Returns (market Series, {sym: sector Series},
    market_source). Sector index excludes the stock itself (equal-weight mean
    of peers' daily returns); needs >= 3 peers."""
    rets = {}
    for s, d in frames.items():
        x = d.set_index("Date")["Close"]
        x = x[~x.index.duplicated()]
        r = x.pct_change()
        rets[s] = r.where(r.abs() <= DEFAULT_CONFIG["corp_action_move"])   # drop corp-action jumps
    R = pd.DataFrame(rets).sort_index()
    if market_series is not None and len(market_series) > 100:
        market, src = market_series, "KSE-100"
    else:
        market, src = (1 + R.mean(axis=1, skipna=True).fillna(0)).cumprod(), "equal-weight universe proxy (KSE-100 unavailable)"
    by_sec = {}
    for s, sec in sectors.items():
        if sec and s in R:
            by_sec.setdefault(sec, []).append(s)
    sec_idx = {}
    for sec, members in by_sec.items():
        if len(members) < 4:
            continue
        sub = R[members]
        tot, cnt = sub.sum(axis=1, skipna=True), sub.notna().sum(axis=1)
        for s in members:
            own = sub[s].fillna(0)
            c = cnt - sub[s].notna().astype(int)
            peer = ((tot - own) / c.where(c >= 3)).fillna(0)
            sec_idx[s] = (1 + peer).cumprod()
    return market, sec_idx, src


def market_regime(market: pd.Series, frames: dict):
    m = market.dropna()
    if len(m) < 210:
        return {"trend": "unknown"}
    s50, s200 = m.rolling(50).mean().iloc[-1], m.rolling(200).mean().iloc[-1]
    last = m.iloc[-1]
    trend = ("Bull" if last > s50 > s200 else "Bear" if last < s50 < s200 else "Sideways")
    lr = np.log(m / m.shift()).dropna()
    hv = lr.rolling(20).std() * math.sqrt(252) * 100
    hvp = pct_rank_prior(hv.to_numpy(), 252)[-1]
    above = [bool(d["Close"].iloc[-1] > d["Close"].rolling(50).mean().iloc[-1]) for d in frames.values() if len(d) >= 50]
    return {"trend": trend, "vol20": _r(hv.iloc[-1], 1), "vol20_pct252": _r(hvp, 1),
            "breadth_above_sma50_pct": round(100 * sum(above) / len(above), 1) if above else None,
            "risk_off": bool(trend == "Bear" and (hvp or 0) > 80)}


def regime_series(market: pd.Series) -> pd.Series:
    m = market.dropna()
    s50, s200 = m.rolling(50).mean(), m.rolling(200).mean()
    return pd.Series(np.where((m > s50) & (s50 > s200), "Bull",
                              np.where((m < s50) & (s50 < s200), "Bear", "Sideways")), index=m.index).where(s200.notna())


# --------------------------------------------------------------------------
# Universe scan (called by run_chart_pattern_refresh.py)
# --------------------------------------------------------------------------
def analyze_universe(all_data: dict, sectors: dict, cfg=None, market_series=None, stats=None, prev=None):
    cfg = cfg or DEFAULT_CONFIG
    frames = {}
    for s, rows in all_data.items():
        try:
            frames[s] = _om._normalise(pd.DataFrame(rows))
        except Exception:
            continue
    market, sec_idx, msrc = build_indices(frames, sectors, market_series)
    rows, details = [], {}
    for s, f in frames.items():
        if len(f) < 60:
            continue
        try:
            row, det = analyze_symbol(s, f, cfg, market, sec_idx.get(s), sectors.get(s), stats)
        except Exception:
            continue
        if row:
            rows.append(row)
            details[s] = det
    alerts = build_alerts(rows, prev)
    regime = market_regime(market, frames)
    return {"status": "ok", "scanned": len(rows), "market_source": msrc, "regime": regime,
            "stats_available": bool(stats and stats.get("buckets")),
            "stats_run_at": (stats or {}).get("run_at"),
            "config": {k: v for k, v in cfg.items() if not k.startswith("w_")} | {
                "w_compression": cfg["w_compression"], "w_bull": cfg["w_bull"], "w_bear": cfg["w_bear"]},
            "timeframes": {"daily": True, "weekly": True,
                           "4h": "not used: ohlcv_4h is a 35-day rolling cache, too short for percentiles"},
            "rows": rows, "alerts": alerts}, details


ALERT_RANK = {"Confirmed breakout": 1, "Confirmed breakdown": 1, "Failed bullish breakout": 2,
              "Failed bearish breakdown": 2, "Bull trap": 2, "Bear trap": 2, "Expansion exhaustion": 3,
              "Potential bullish expansion": 4, "Potential bearish expansion": 4, "Advanced squeeze": 5,
              "Extreme compression": 6, "Newly entering early compression": 7}


def _alert_kind(r):
    s, det = r["stage"], r["stage_detail"]
    if s == 4 or s == 5:
        return det
    if s == 3:
        return "Potential bullish expansion" if r["stage_dir"] > 0 else "Potential bearish expansion" if r["stage_dir"] < 0 else None
    if s == 2:
        return "Advanced squeeze"
    if s == 1:
        return "Extreme compression" if (r["bbw_pct100"] or 100) <= 5 else "Newly entering early compression"
    return None


def build_alerts(rows, prev):
    """Only emit an alert when a symbol's alert kind CHANGED since the
    previous stored scan (no repeats for an unchanged condition)."""
    before = {}
    for r in (prev or {}).get("rows", []) or []:
        before[r["symbol"]] = _alert_kind(r)
    out = []
    liq_w = {"Highly Liquid": 1.0, "Liquid": .85, "Moderate Liquidity": .6, "Illiquid": .3, "Unknown": .5}
    for r in rows:
        k = _alert_kind(r)
        if not k or before.get(r["symbol"]) == k:
            continue
        dirn = max(r["bull_score"], r["bear_score"])
        exp = max(r["bull_expansion_score"], r["bear_expansion_score"])
        mtf = 1.0 if "Strong" in r["mtf_alignment"] else .7 if "Moderate" in r["mtf_alignment"] else .4
        hq = 1.0 if r["hist"].get("available") else .6
        pr = (0.30 * r["compression_score"] + 0.25 * dirn + 0.25 * exp) / 80 * liq_w.get(r["liquidity"], .5) * mtf * hq
        out.append({"symbol": r["symbol"], "alert": k, "stage": r["stage"], "priority": round(pr * 100, 1),
                    "compression": r["compression_score"], "bull": r["bull_score"], "bear": r["bear_score"],
                    "liquidity": r["liquidity"], "previous": before.get(r["symbol"])})
    out.sort(key=lambda a: (ALERT_RANK.get(a["alert"], 9), -a["priority"]))
    return out
