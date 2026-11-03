#!/usr/bin/env python3
"""run_volatility_backtest.py — Stage B: historical probability & validation
engine for volatility_engine.py.

Reads daily_ohlc from the local snapshot (PSX_DAILY_OHLC_SNAPSHOT) -> 0 Turso
reads for prices; writes ONE analysis_cache row ('volatility_engine_stats')
that the daily scan attaches to its rows, plus a markdown report artifact.

Method
  * Every event is found with the SAME per-bar code the live scanner uses
    (volatility_engine.compute_frame + classify_series + scores_at), so all
    information is causal: features at bar t use bars <= t only.
  * Entry = NEXT session's open. Outcomes use later bars only.
  * Overlap control: per symbol, the same event type cannot fire again within
    COOLDOWN sessions.
  * Events whose forward window contains a >11% one-day move (beyond PSX's
    circuit limit -> likely a corporate-action adjustment) are excluded.
  * Chronological split by signal date: train (first 60% of the date span),
    validation (next 20%), out-of-sample (last 20%, never used to choose
    anything). Plus a calendar-year walk-forward table.
  * Probabilities carry 95% Wilson intervals; n < MIN_N -> "INSUFFICIENT".
  * Calibration: bucket hit-rates measured on TRAIN are used as forecasts for
    OOS events; Brier score vs a no-skill (train base rate) forecast, and a
    reliability table.
  * Costs: COST_RT round-trip (commission + CVT + slippage, configurable)
    subtracted from every simulated trade.
Known limits: universe = symbols currently in daily_ohlc (survivorship bias);
no bid/ask or order-book data; bearish trades assume shorting, which is
restricted on PSX -- treat them as "avoid / exit" evidence.
"""
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

import turso_db
import volatility_engine as ve
import obv_mfi_scanner as om
import run_obv_mfi_backtest as omb
import triangle_regression_detector as trd
from pivots import find_pivots

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("volbt")

HORIZONS = (5, 10, 20)
COOLDOWN = 20
MIN_N = 30
COST_RT = float(os.getenv("PSX_COST_RT_PCT", "0.6")) / 100
FIX_TGT, FIX_STP = 0.08, 0.04          # fixed target / stop
ATR_TGT, ATR_STP = 3.0, 1.5            # ATR-multiple target / stop
MAX_HOLD = 20
PSX_LIMIT = 0.10                       # daily price limit (empirical cap in daily_ohlc is 10%)
BASELINE_EVERY = 5
REPORT = Path(__file__).parent.parent / "volatility_backtest_report.md"


def load_universe():
    conn = turso_db.get_connection()
    # Same universe as the live engine: configured FIRE/Wyckoff symbols minus exclusions.
    universe, excluded = ve.configured_universe()
    syms = [s for s in universe if s not in set(excluded)]
    out = {}
    for s in syms:
        rows = conn.execute("SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
                            "WHERE symbol=? ORDER BY trade_date", (s,)).fetchall()
        if len(rows) >= 260:
            out[s] = om._normalise(pd.DataFrame([dict(r) for r in rows]))
    return out


def load_sectors():
    try:
        import names
        m = names.load()
        return {k: (v or {}).get("sector") for k, v in m.items()}
    except Exception:
        return {}


def load_market():
    try:
        import psx_live
        rows = psx_live.index_history("KSE100", limit=2000)
        if rows:
            s = pd.Series({pd.to_datetime(r["timestamp"], unit="ms").normalize(): float(r["close"]) for r in rows})
            return s.sort_index()
    except Exception as e:
        log.info(f"KSE-100 history unavailable ({type(e).__name__}); using equal-weight proxy")
    return None


# --------------------------------------------------------------------------
def forward(d, t, atrp):
    """Outcome record for a signal at bar t (entry next open)."""
    O, H, L, C = (d[c].to_numpy(float) for c in ("Open", "High", "Low", "Close"))
    n = len(d)
    if t + 1 >= n:
        return None
    E = O[t + 1]
    if not E or E <= 0:
        return None
    end = min(n, t + 1 + MAX_HOLD)
    r1 = np.abs(C[t + 1:end] / C[t:end - 1] - 1)
    if (r1 > ve.DEFAULT_CONFIG["corp_action_move"]).any():
        return {"excluded": True}
    rec = {}
    for h in HORIZONS:
        if t + h < n:
            rec[f"r{h}"] = (C[t + h] / E - 1) * 100
            rec[f"mfe{h}"] = (H[t + 1:t + h + 1].max() / E - 1) * 100
            rec[f"mae{h}"] = (L[t + 1:t + h + 1].min() / E - 1) * 100
    a = (atrp or 0) / 100
    # Execution realism: a stock that opens at its upper limit and stays
    # locked (low == high) cannot be bought at that open; likewise a short
    # cannot be opened into a lower-circuit lock. Such trades are recorded as
    # "unfilled" and kept out of the trade statistics.
    locked_up = O[t + 1] >= C[t] * (1 + PSX_LIMIT - 0.005) and L[t + 1] >= H[t + 1] * 0.999
    locked_dn = O[t + 1] <= C[t] * (1 - PSX_LIMIT + 0.005) and H[t + 1] <= L[t + 1] * 1.001

    def tbs(tgt, stp, side):
        if (side > 0 and locked_up) or (side < 0 and locked_dn):
            return "unfilled", None, None
        for j in range(t + 1, end):
            # Gap through the stop at the open -> filled at the OPEN, not at the
            # stop price. A gap beyond the target is only credited the target.
            if side > 0:
                if O[j] <= E * (1 - stp):
                    return "stop", j - t, O[j] / E - 1
                if O[j] >= E * (1 + tgt):
                    return "target", j - t, tgt
                if L[j] <= E * (1 - stp):
                    return "stop", j - t, -stp
                if H[j] >= E * (1 + tgt):
                    return "target", j - t, tgt
            else:
                if O[j] >= E * (1 + stp):
                    return "stop", j - t, -(O[j] / E - 1)
                if O[j] <= E * (1 - tgt):
                    return "target", j - t, tgt
                if H[j] >= E * (1 + stp):
                    return "stop", j - t, -stp
                if L[j] <= E * (1 - tgt):
                    return "target", j - t, tgt
        if end - 1 >= t + MAX_HOLD:
            return "timeout", MAX_HOLD, side * (C[end - 1] / E - 1)
        return "open", None, None

    rec["long_fix"] = tbs(FIX_TGT, FIX_STP, 1)
    rec["short_fix"] = tbs(FIX_TGT, FIX_STP, -1)
    if a > 0:
        rec["long_atr"] = tbs(ATR_TGT * a, ATR_STP * a, 1)
        rec["short_atr"] = tbs(ATR_TGT * a, ATR_STP * a, -1)
        rec["atrp"] = atrp
    return rec


def symbol_events(sym, d, cl, liq_by_t, reg_by_date):
    """All event types for one symbol -> list of dicts."""
    ev = []
    last = {}
    st, dirn, det = cl["stage"].to_numpy(), cl["stage_dir"].to_numpy(), cl["stage_detail"].to_numpy()
    bbw_p = d["BBW_p100"].to_numpy()
    atrp = d["ATRP"].to_numpy()
    dates = d["Date"]
    n = len(d)
    score_cache = {}

    def sc(t):
        if t not in score_cache:
            score_cache[t] = ve.scores_at(d, cl, t)
        return score_cache[t]

    def add(kind, t, extra=None):
        if t - last.get(kind, -10 ** 9) < COOLDOWN:
            return
        f = forward(d, t, atrp[t])
        if not f or f.get("excluded"):
            return
        last[kind] = t
        dt = dates.iloc[t]
        ev.append({"kind": kind, "symbol": sym, "date": dt, "liq": liq_by_t[t],
                   "regime": reg_by_date.get(dt.normalize(), None), **(extra or {}), **f})

    prev_bucket = None
    for t in range(1, n - 1):
        s, ps = st[t], st[t - 1]
        if s == 1 and ps not in (1, 2):
            add("Stage 1 entry (early compression)", t)
        if s == 2 and ps != 2:
            add("Stage 2 entry (advanced squeeze)", t)
        if s == 4 and ps != 4:
            add("Confirmed bullish expansion" if dirn[t] > 0 else "Confirmed bearish expansion", t)
        if s == 5 and ps != 5 and "Failed" in det[t] or (s == 5 and ps != 5 and "trap" in det[t]):
            add("Failed bullish breakout" if dirn[t] > 0 else "Failed bearish breakdown", t)
        if not np.isnan(bbw_p[t]) and bbw_p[t] < 10 and (np.isnan(bbw_p[t - 1]) or bbw_p[t - 1] >= 10):
            add("Simple BBW percentile < 10", t)
        if s > 0:
            x = sc(t)
            b = ve.setup_bucket(s, dirn[t], x["bull_score"], x["bear_score"])
            if b != prev_bucket:
                add("bucket:" + b, t, {"bucket": b})
                if s in (1, 2):
                    if x["bull_score"] - x["bear_score"] >= 15:
                        add("Compression + bullish evidence", t)
                    elif x["bear_score"] - x["bull_score"] >= 15:
                        add("Compression + bearish evidence", t)
                    else:
                        add("Compression, no directional lean", t)
            prev_bucket = b
        else:
            prev_bucket = None
        if t % BASELINE_EVERY == 0 and not np.isnan(bbw_p[t]):
            add("Baseline (every 5th session)", t)
    return ev


def existing_module_events(sym, d, liq_by_t, reg_by_date):
    ev = []
    atrp = d["ATRP"].to_numpy()
    idx = {dt: i for i, dt in enumerate(d["Date"])}
    # OBV+MFI (+ATR contraction) -- same fast path as run_obv_mfi_backtest
    seen = set()
    for t, i0 in omb.signals_for(d):
        if i0 in seen:
            continue
        seen.add(i0)
        f = forward(d, t, atrp[t])
        if f and not f.get("excluded"):
            dt = d["Date"].iloc[t]
            ev.append({"kind": "Existing: OBV+MFI+ATR contraction", "symbol": sym, "date": dt,
                       "liq": liq_by_t[t], "regime": reg_by_date.get(dt.normalize()), **f})
    # Regression-channel triangle squeeze (short-side module)
    try:
        td = pd.DataFrame({"date": d["Date"], "open": d["Open"], "high": d["High"], "low": d["Low"],
                           "close": d["Close"]}).reset_index(drop=True)
        td["atr14"] = trd._atr14(td)
        piv = find_pivots(td, k=trd.PIVOT_K)
        lastt = -10 ** 9
        for i in range(trd.MIN_BARS_REQUIRED, len(td)):
            if trd._evaluate_at(td, piv, i) is None or i - lastt < COOLDOWN:
                continue
            f = forward(d, i, atrp[i])
            if f and not f.get("excluded"):
                lastt = i
                dt = d["Date"].iloc[i]
                ev.append({"kind": "Existing: Regression triangle squeeze", "symbol": sym, "date": dt,
                           "liq": liq_by_t[i], "regime": reg_by_date.get(dt.normalize()), **f})
    except Exception as e:
        log.info(f"triangle module skipped for {sym}: {type(e).__name__}")
    return ev


# --------------------------------------------------------------------------
def cluster_ci(flags, dates, z=1.96):
    """95% CI for a proportion with events clustered by signal DATE (many
    stocks signal on the same market day, so they are not independent).
    Cluster-robust (sandwich) variance; falls back to Wilson when there are
    fewer than 2 dates."""
    n = len(flags)
    if not n:
        return (None, None)
    p = sum(flags) / n
    by = {}
    for f, d in zip(flags, dates):
        a = by.setdefault(d, [0, 0])
        a[0] += f
        a[1] += 1
    g = len(by)
    if g < 2:
        return ve.wilson(sum(flags), n)
    var = sum((k - p * m) ** 2 for k, m in by.values()) / n ** 2 * g / (g - 1)
    h = z * math.sqrt(var)
    return (round(max(0.0, p - h) * 100, 1), round(min(1.0, p + h) * 100, 1))


def _p(pairs, cond):
    """pairs: [(value, date)]. Returns (pct, date-clustered CI, n)."""
    v = [(x, d) for x, d in pairs if x is not None]
    if not v:
        return None, (None, None), 0
    flags = [1 if cond(x) else 0 for x, _ in v]
    return round(100 * sum(flags) / len(v), 1), cluster_ci(flags, [d for _, d in v]), len(v)


def trade_stats(evs, key):
    done = [e for e in evs if key in e and e[key][0] in ("target", "stop", "timeout")]
    tr = [e[key] for e in done]
    unfilled = sum(1 for e in evs if key in e and e[key][0] == "unfilled")
    if not tr:
        return {"n": 0, "unfilled": unfilled} if unfilled else None
    rets = np.array([x[2] - COST_RT for x in tr]) * 100
    w, l = rets[rets > 0], rets[rets <= 0]
    hit = [x for x in tr if x[0] == "target"]
    # equity: equal-size trades in signal-date order (non-compounded)
    eq = np.cumsum(rets[np.argsort([e["date"] for e in done], kind="stable")])
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max())
    sd = rets.std(ddof=1) if len(rets) > 1 else 0
    return {"n": len(tr), "target_first_pct": round(100 * len(hit) / len(tr), 1),
            "target_first_ci": cluster_ci([1 if x[0] == "target" else 0 for x in tr],
                                          [e["date"] for e in done]),
            "unfilled": unfilled,
            "win_rate": round(100 * len(w) / len(rets), 1),
            "avg_win": round(float(w.mean()), 2) if len(w) else None,
            "avg_loss": round(float(l.mean()), 2) if len(l) else None,
            "expectancy": round(float(rets.mean()), 2),
            "profit_factor": round(float(w.sum() / -l.sum()), 2) if len(l) and l.sum() < 0 else None,
            "max_drawdown_pts": round(dd, 1),
            "sharpe_per_trade": round(float(rets.mean() / sd), 3) if sd else None,
            "avg_bars_to_target": round(float(np.mean([x[1] for x in hit])), 1) if hit else None}


def group_stats(evs):
    if not evs:
        return None
    out = {"n": len(evs),
           "period": f"{min(e['date'] for e in evs).date()} → {max(e['date'] for e in evs).date()}"}
    for h in HORIZONS:
        r = [(e.get(f"r{h}"), e["date"]) for e in evs]
        rv = np.array([x for x, _ in r if x is not None])
        out[f"p_up_{h}d"], out[f"p_up_{h}d_ci"], out[f"n_{h}d"] = _p(r, lambda x: x > 0)
        out[f"p_down_{h}d"], out[f"p_down_{h}d_ci"], _ = _p(r, lambda x: x < 0)
        out[f"mean_{h}d"] = round(float(rv.mean()), 2) if len(rv) else None
        out[f"median_{h}d"] = round(float(np.median(rv)), 2) if len(rv) else None
        for th in (3, 5, 10):
            out[f"p_abs{th}_{h}d"], _, _ = _p(r, lambda x, th=th: abs(x) > th)
        mfe = [e.get(f"mfe{h}") for e in evs if e.get(f"mfe{h}") is not None]
        mae = [e.get(f"mae{h}") for e in evs if e.get(f"mae{h}") is not None]
        out[f"mfe_{h}d"] = round(float(np.mean(mfe)), 2) if mfe else None
        out[f"mae_{h}d"] = round(float(np.mean(mae)), 2) if mae else None
        out[f"max_up_{h}d"] = round(float(np.max(mfe)), 1) if mfe else None
        out[f"max_down_{h}d"] = round(float(np.min(mae)), 1) if mae else None
        out[f"p_mfe5_{h}d"], _, _ = _p([(e.get(f"mfe{h}"), e["date"]) for e in evs], lambda x: x >= 5)
        out[f"p_mae5_{h}d"], _, _ = _p([(e.get(f"mae{h}"), e["date"]) for e in evs], lambda x: x <= -5)
    up_atr = [e["mfe10"] >= 2 * e["atrp"] for e in evs if "mfe10" in e and e.get("atrp")]
    dn_atr = [e["mae10"] <= -2 * e["atrp"] for e in evs if "mae10" in e and e.get("atrp")]
    out["p_up_2atr_10d"] = round(100 * np.mean(up_atr), 1) if up_atr else None
    out["p_down_2atr_10d"] = round(100 * np.mean(dn_atr), 1) if dn_atr else None
    for k in ("long_fix", "short_fix", "long_atr", "short_atr"):
        out[k] = trade_stats(evs, k)
    out["long_target_first"] = (out["long_atr"] or {}).get("target_first_pct")
    out["short_target_first"] = (out["short_atr"] or {}).get("target_first_pct")
    out["n_dates"] = len({e["date"] for e in evs})
    out["sufficient"] = out["n"] >= MIN_N
    return out


def calibration(train, oos, key="long_atr"):
    """Train bucket hit-rate -> forecast for OOS events of that bucket."""
    def hit(e):
        x = e.get(key)
        return None if not x or x[0] not in ("target", "stop", "timeout") else float(x[0] == "target")
    tr = [(e["bucket"], hit(e)) for e in train if hit(e) is not None]
    if not tr:
        return None
    base = np.mean([h for _, h in tr])
    rates = {}
    for b in set(b for b, _ in tr):
        hs = [h for bb, h in tr if bb == b]
        rates[b] = np.mean(hs) if len(hs) >= MIN_N else base
    pairs = [(rates.get(e["bucket"], base), hit(e)) for e in oos if hit(e) is not None]
    if len(pairs) < MIN_N:
        return {"n_oos": len(pairs), "note": "INSUFFICIENT OOS EVENTS"}
    p, y = np.array([a for a, _ in pairs]), np.array([b for _, b in pairs])
    brier = float(np.mean((p - y) ** 2))
    brier0 = float(np.mean((base - y) ** 2))
    bins = []
    for lo, hi in ((0, .2), (.2, .3), (.3, .4), (.4, .5), (.5, 1.01)):
        m = (p >= lo) & (p < hi)
        if m.sum():
            bins.append({"pred_range": f"{lo:.0%}-{min(hi, 1):.0%}", "n": int(m.sum()),
                         "pred_mean": round(float(p[m].mean()) * 100, 1),
                         "observed": round(float(y[m].mean()) * 100, 1),
                         "observed_ci": ve.wilson(int(y[m].sum()), int(m.sum()))})
    return {"target": key, "n_oos": len(pairs), "brier": round(brier, 4),
            "brier_no_skill": round(brier0, 4), "skill_vs_base_pct": round((1 - brier / brier0) * 100, 2) if brier0 else None,
            "reliability": bins}


# --------------------------------------------------------------------------
def main():
    stt = turso_db.status()
    if stt.get("on_local_fallback"):
        log.error("On local fallback -- no data. Aborting.")
        return 1
    t0 = time.time()
    uni = load_universe()
    sectors = load_sectors()
    mkt_raw = None   # benchmark = equal-weight index of the loaded stocks (not KSE-100)
    market, sec_idx, msrc = ve.build_indices(uni, sectors, mkt_raw)
    regs = ve.regime_series(market).dropna()
    reg_by_date = {k.normalize(): v for k, v in regs.items()}
    log.info(f"{len(uni)} symbols; market={msrc}; sectors known for {sum(1 for s in uni if sectors.get(s))}")

    events = []
    for i, (s, raw) in enumerate(uni.items()):
        d = ve.compute_frame(raw, market=market, sector=sec_idx.get(s))
        cl = ve.classify_series(d)
        liq = [ve.liquidity_class(None if np.isnan(x) else x) for x in d["TV20"].to_numpy()]
        events += symbol_events(s, d, cl, liq, reg_by_date)
        events += existing_module_events(s, d, liq, reg_by_date)
        if i % 25 == 0:
            log.info(f"  {i}/{len(uni)} symbols, {len(events)} events, {time.time() - t0:.0f}s")

    dmin = min(e["date"] for e in events)
    dmax = max(e["date"] for e in events)
    span = dmax - dmin
    c_tr, c_va = dmin + span * 0.6, dmin + span * 0.8
    for e in events:
        e["split"] = "train" if e["date"] <= c_tr else "validation" if e["date"] <= c_va else "oos"

    kinds = sorted(set(e["kind"] for e in events if not e["kind"].startswith("bucket:")))
    res = {"status": "ok", "run_at": datetime.now(timezone.utc).isoformat(), "market_source": msrc,
           "universe": len(uni), "data_from": str(dmin.date()), "data_to": str(dmax.date()),
           "splits": {"train_to": str(c_tr.date()), "validation_to": str(c_va.date())},
           "assumptions": {"entry": "next session open", "cost_round_trip_pct": COST_RT * 100,
                           "fixed_target_stop_pct": [FIX_TGT * 100, FIX_STP * 100],
                           "atr_target_stop_mult": [ATR_TGT, ATR_STP], "max_hold": MAX_HOLD,
                           "cooldown": COOLDOWN, "min_n": MIN_N,
                           "fills": "long entries into an upper-circuit lock (and shorts into a lower-circuit lock) "
                                    "are unfilled; gap-through stops fill at the open",
                           "confidence_intervals": "95%, clustered by signal date"},
           "groups": {}, "by_split": {}, "by_regime": {}, "by_liquidity": {}, "by_year": {}, "buckets": {}}
    for k in kinds:
        ev = [e for e in events if e["kind"] == k]
        res["groups"][k] = group_stats(ev)
        res["by_split"][k] = {sp: group_stats([e for e in ev if e["split"] == sp]) for sp in ("train", "validation", "oos")}
        res["by_regime"][k] = {rg: group_stats([e for e in ev if e["regime"] == rg]) for rg in ("Bull", "Bear", "Sideways")}
        res["by_liquidity"][k] = {lq: group_stats([e for e in ev if e["liq"] == lq])
                                  for lq in ("Highly Liquid", "Liquid", "Moderate Liquidity", "Illiquid")}
        res["by_year"][k] = {str(y): group_stats([e for e in ev if e["date"].year == y])
                             for y in sorted(set(e["date"].year for e in ev))}
    bev = [e for e in events if e["kind"].startswith("bucket:")]
    for b in sorted(set(e["bucket"] for e in bev)):
        ev = [e for e in bev if e["bucket"] == b]
        g = group_stats(ev)
        oos = group_stats([e for e in ev if e["split"] == "oos"])
        keep = {k: g[k] for k in ("n", "period", "p_up_10d", "p_up_10d_ci", "p_down_10d", "p_down_10d_ci",
                                  "mean_10d", "median_10d", "p_abs5_10d", "mfe_20d", "mae_20d",
                                  "long_target_first", "short_target_first", "sufficient")}
        keep["oos_n"] = oos["n"] if oos else 0
        keep["oos_p_up_10d"] = oos["p_up_10d"] if oos else None
        res["buckets"][b] = keep
    res["calibration"] = {
        "long_atr": calibration([e for e in bev if e["split"] == "train"], [e for e in bev if e["split"] == "oos"], "long_atr"),
        "short_atr": calibration([e for e in bev if e["split"] == "train"], [e for e in bev if e["split"] == "oos"], "short_atr"),
    }
    res["elapsed_s"] = round(time.time() - t0)
    write_report(res)
    if os.getenv("PSX_BACKTEST_NO_SAVE"):
        log.info("PSX_BACKTEST_NO_SAVE set -- report only, production stats row left untouched")
        turso_db.print_usage_report(label="run_volatility_backtest.py")
        return 0
    try:
        conn = turso_db.get_connection()
        conn.execute("""INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
            VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET run_at=excluded.run_at,
            run_at_epoch=excluded.run_at_epoch, result_json=excluded.result_json""",
                     ("volatility_engine_stats", res["run_at"], time.time(), json.dumps(res, default=str)))
        conn.commit()
        log.info("Saved analysis_cache[volatility_engine_stats]")
    except Exception as e:
        log.warning(f"save failed: {e}")
    turso_db.print_usage_report(label="run_volatility_backtest.py")
    return 0


def _f(x, nd=1, pct=False):
    if x is None:
        return "—"
    return f"{x:+.{nd}f}" if not pct else f"{x:.{nd}f}"


def write_report(res):
    L = [f"# Volatility Intelligence Engine — historical validation", "",
         f"Run {res['run_at'][:16]} UTC · {res['universe']} symbols · {res['data_from']} → {res['data_to']} · "
         f"market benchmark: {res['market_source']}", "",
         f"Splits by signal date: train ≤ {res['splits']['train_to']} · validation ≤ {res['splits']['validation_to']} · "
         f"out-of-sample after. Entry next open · round-trip cost {res['assumptions']['cost_round_trip_pct']:.2f}% · "
         f"ATR trade = +{ATR_TGT}×ATR target / −{ATR_STP}×ATR stop, {MAX_HOLD}-session max · n < {MIN_N} = insufficient.", "",
         "## All setups vs benchmarks (full period)", "",
         "| Setup | n | P(up 10d) [95% CI] | Mean 10d % | Median 10d % | P(|move|>5% 10d) | MFE20 / MAE20 % | Long ATR: target-first % / expectancy % / PF | Short ATR: target-first % / expectancy % |",
         "|---|---|---|---|---|---|---|---|---|"]

    def row(k, g):
        if not g:
            return f"| {k} | 0 | — | | | | | | |"
        la, sa = g["long_atr"] or {}, g["short_atr"] or {}
        ci = g["p_up_10d_ci"]
        ins = "" if g["sufficient"] else " ⚠ INSUFFICIENT"
        return (f"| {k}{ins} | {g['n']} | {g['p_up_10d']} [{ci[0]}–{ci[1]}] | {_f(g['mean_10d'], 2)} | {_f(g['median_10d'], 2)} | "
                f"{g['p_abs5_10d']} | {_f(g['mfe_20d'])} / {_f(g['mae_20d'])} | "
                f"{la.get('target_first_pct')} / {_f(la.get('expectancy'), 2)} / {la.get('profit_factor')} | "
                f"{sa.get('target_first_pct')} / {_f(sa.get('expectancy'), 2)} |")

    for k, g in res["groups"].items():
        L.append(row(k, g))
    L += ["", "## Out-of-sample only (last 20% of the period, never used for any choice)", "",
          L[8], L[9]]
    for k in res["groups"]:
        L.append(row(k, res["by_split"][k].get("oos")))
    L += ["", "## By market regime — P(up 10d) / mean 10d % / n", "", "| Setup | Bull | Bear | Sideways |", "|---|---|---|---|"]
    for k in res["groups"]:
        cells = []
        for rg in ("Bull", "Bear", "Sideways"):
            g = res["by_regime"][k].get(rg)
            cells.append("—" if not g else f"{g['p_up_10d']} / {_f(g['mean_10d'], 2)} / {g['n']}")
        L.append(f"| {k} | " + " | ".join(cells) + " |")
    L += ["", "## By liquidity — mean 10d % / n", "", "| Setup | Highly Liquid | Liquid | Moderate | Illiquid |", "|---|---|---|---|---|"]
    for k in res["groups"]:
        cells = []
        for lq in ("Highly Liquid", "Liquid", "Moderate Liquidity", "Illiquid"):
            g = res["by_liquidity"][k].get(lq)
            cells.append("—" if not g else f"{_f(g['mean_10d'], 2)} / {g['n']}")
        L.append(f"| {k} | " + " | ".join(cells) + " |")
    L += ["", "## Walk-forward by year — mean 10d % (n)", ""]
    years = sorted({y for k in res["by_year"] for y in res["by_year"][k]})
    L += ["| Setup | " + " | ".join(years) + " |", "|---" * (len(years) + 1) + "|"]
    for k in res["groups"]:
        L.append(f"| {k} | " + " | ".join(
            "—" if not res["by_year"][k].get(y) else f"{_f(res['by_year'][k][y]['mean_10d'], 2)} ({res['by_year'][k][y]['n']})"
            for y in years) + " |")
    L += ["", "## Setup buckets used by the live dashboard", "",
          "| Bucket | n | P(up 10d) [CI] | Mean 10d % | Long target-first % | Short target-first % | OOS n | OOS P(up 10d) |",
          "|---|---|---|---|---|---|---|---|"]
    for b, g in res["buckets"].items():
        L.append(f"| {b}{'' if g['sufficient'] else ' ⚠'} | {g['n']} | {g['p_up_10d']} [{g['p_up_10d_ci'][0]}–{g['p_up_10d_ci'][1]}] | "
                 f"{_f(g['mean_10d'], 2)} | {g['long_target_first']} | {g['short_target_first']} | {g['oos_n']} | {g['oos_p_up_10d']} |")
    L += ["", "## Probability calibration (train bucket rates → OOS outcomes)", ""]
    for k, c in res["calibration"].items():
        if not c or "brier" not in c:
            L.append(f"- {k}: {c}")
            continue
        L.append(f"- **{k}**: OOS n={c['n_oos']}, Brier {c['brier']} vs no-skill {c['brier_no_skill']} "
                 f"(skill {c['skill_vs_base_pct']}%)")
        for b in c["reliability"]:
            L.append(f"  - predicted {b['pred_range']} (mean {b['pred_mean']}%): observed {b['observed']}% "
                     f"[{b['observed_ci'][0]}–{b['observed_ci'][1]}], n={b['n']}")
    REPORT.write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
