#!/usr/bin/env python3
"""run_wyckoff2_backtest.py — RESEARCH / NOT PRODUCTION.

Original Wyckoff (unchanged detector) vs Wyckoff Accumulation 2.0 on the same
dates, configured universe minus exclusions. Turso: none (daily bars from SCS,
KSE-100 from the public index API). Output: report markdown + stats JSON file
(a separate workflow step may store the JSON as analysis_cache
'wyckoff2_research_stats' -- 1 write).

PRE-REGISTERED DEFINITIONS (fixed before any result was seen):
  signal event   first bar of a run of signal bars; 20-bar cooldown per symbol per engine
                 original: signal_type != NO_SIGNAL (daily-only replay -> the 4-hour
                 20-point component is unavailable historically, so the original's
                 replayed scores are a lower bound and EXTREME cannot occur)
                 enhanced: STRONG / ADVANCED / POTENTIAL BREAKOUT
  entry          next session's open + 0.25% slippage; NOT fillable if that session
                 opens at the upper limit and stays locked (low == high)
  breakout       within 20 sessions, a close above the 40-session resistance at the
                 signal date on volume >= 1.5x its prior 20-day average
  failed b/o     after a breakout, a close back below that resistance within 5 sessions
  upper circuit  close >= +9.5% vs previous close and close at the day's high
  trade rule     +10% target / -5% stop, 20-session max; gaps through the stop fill at
                 the open; a lower-circuit-locked session cannot be exited (wait);
                 exit slippage 0.25%; round-trip cost 0.6%
  excluded       events whose forward window has a >11% one-day move that is not an
                 upper/lower circuit lock (corporate-action adjustment)
  splits         by signal date: train first 60%, validation next 20%, test last 20%;
                 classification thresholds = 70th percentile of each component on
                 TRAIN bars only, frozen afterwards
  CIs            95%, clustered by signal date
"""
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import pandas as pd

import scs_daily
import wyckoff2_research as w2

HORIZONS = (1, 3, 5, 10, 20)
SLIP, COST = 0.0025, 0.006
TGT, STP, HOLD = 0.10, 0.05, 20
COOLDOWN = 20
LIQ_MIN_TV = 5e6
OUT_JSON = ROOT / "wyckoff2_research_stats.json"
REPORT = ROOT / "wyckoff2_backtest_report.md"


def universe():
    import volatility_engine as ve
    u, exc = ve.configured_universe()
    return [s for s in u if s not in set(exc)], exc


def load_market():
    try:
        import psx_live
        rows = psx_live.index_history("KSE100", limit=2000)
        if rows:
            s = pd.Series({pd.to_datetime(r["timestamp"], unit="ms").normalize(): float(r["close"]) for r in rows})
            return s.sort_index(), "KSE-100"
    except Exception as e:
        print(f"KSE-100 unavailable ({type(e).__name__}: {e})")
    return None, None


def cluster_ci(flags, dates, z=1.96):
    n = len(flags)
    if not n:
        return (None, None)
    p = sum(flags) / n
    by = defaultdict(lambda: [0, 0])
    for f, d in zip(flags, dates):
        by[d][0] += f
        by[d][1] += 1
    g = len(by)
    if g < 2:
        return (None, None)
    h = z * math.sqrt(sum((k - p * m) ** 2 for k, m in by.values()) / n ** 2 * g / (g - 1))
    return (round(max(0, p - h) * 100, 1), round(min(1, p + h) * 100, 1))


def forward(raw, t, R):
    O, H, L, C, V = (raw[k] for k in ("open", "high", "low", "close", "volume"))
    vs = raw["vsma_prior"]
    n = len(C)
    if t + 1 >= n:
        return None
    end = min(n, t + 1 + HOLD)
    r1 = C[t + 1:end] / C[t:end - 1] - 1
    locked = (H[t + 1:end] <= L[t + 1:end] * 1.001)
    if ((np.abs(r1) > 0.11) & ~locked).any():
        return {"excluded": True}
    if O[t + 1] >= C[t] * 1.095 and L[t + 1] >= H[t + 1] * 0.999:
        return {"unfilled": True}
    E = O[t + 1] * (1 + SLIP)
    rec = {}
    for hz in HORIZONS:
        if t + hz < n:
            rec[f"r{hz}"] = (C[t + hz] / E - 1) * 100
    if end - (t + 1) >= 5:
        rec["mfe"] = (H[t + 1:end].max() / E - 1) * 100
        rec["mae"] = (L[t + 1:end].min() / E - 1) * 100
    bo = None
    for j in range(t + 1, end):
        if C[j] > R and vs[j] > 0 and V[j] >= 1.5 * vs[j]:
            bo = j
            break
    rec["breakout"] = bo is not None
    rec["t_breakout"] = (bo - t) if bo is not None else None
    rec["failed_breakout"] = bool(bo is not None and (C[bo + 1:min(n, bo + 6)] < R).any())
    rec["uc20"] = bool(((C[t + 1:end] / C[t:end - 1] - 1 >= 0.095) & (C[t + 1:end] >= H[t + 1:end] * 0.999)).any())
    tgt, stp = E * (1 + TGT), E * (1 - STP)
    outcome, xp, held = None, None, None
    pending_stop = False
    for j in range(t + 1, min(n, t + 1 + HOLD + 10)):
        lock_dn = H[j] <= L[j] * 1.001 and C[j] <= C[j - 1] * 0.905
        if pending_stop or O[j] <= stp or L[j] <= stp:
            if lock_dn:
                pending_stop = True
                continue
            outcome, xp, held = "stop", min(O[j], stp) if not pending_stop else O[j], j - t
            break
        if H[j] >= tgt:
            outcome, xp, held = "target", tgt, j - t
            break
        if j - t >= HOLD:
            outcome, xp, held = "timeout", C[j], j - t
            break
    if outcome:
        rec["trade"] = outcome
        rec["trade_ret"] = (xp * (1 - SLIP) / E - 1 - COST) * 100
        rec["held"] = held
    return rec


def stats(evs):
    if not evs:
        return {"n": 0}
    out = {"n": len(evs), "n_dates": len({e["date"] for e in evs})}
    for hz in HORIZONS:
        v = [e[f"r{hz}"] for e in evs if f"r{hz}" in e]
        if v:
            out[f"mean_{hz}d"] = round(float(np.mean(v)), 2)
            out[f"median_{hz}d"] = round(float(np.median(v)), 2)
            f = [int(x > 0) for x in v]
            out[f"win_{hz}d"] = round(100 * float(np.mean(f)), 1)
            out[f"win_{hz}d_ci"] = cluster_ci(f, [e["date"] for e in evs if f"r{hz}" in e])
    for k in ("mfe", "mae"):
        v = [e[k] for e in evs if k in e]
        out[f"avg_{k}"] = round(float(np.mean(v)), 2) if v else None
        out[f"max_{'up' if k == 'mfe' else 'down'}"] = round(float(max(v) if k == "mfe" else min(v)), 1) if v else None
    bo = [e for e in evs if "breakout" in e]
    out["breakout_pct"] = round(100 * np.mean([e["breakout"] for e in bo]), 1) if bo else None
    out["breakout_ci"] = cluster_ci([int(e["breakout"]) for e in bo], [e["date"] for e in bo])
    b2 = [e for e in bo if e["breakout"]]
    out["failed_breakout_pct"] = round(100 * np.mean([e["failed_breakout"] for e in b2]), 1) if b2 else None
    out["median_t_breakout"] = float(np.median([e["t_breakout"] for e in b2])) if b2 else None
    out["uc20_pct"] = round(100 * np.mean([e["uc20"] for e in bo]), 1) if bo else None
    tr = [e for e in evs if "trade" in e]
    if tr:
        r = np.array([e["trade_ret"] for e in tr])
        w, ls = r[r > 0], r[r <= 0]
        out["trades"] = len(tr)
        out["target_first_pct"] = round(100 * np.mean([e["trade"] == "target" for e in tr]), 1)
        out["trade_win_pct"] = round(100 * len(w) / len(r), 1)
        out["expectancy_pct"] = round(float(r.mean()), 2)
        out["profit_factor"] = round(float(w.sum() / -ls.sum()), 2) if len(ls) and ls.sum() < 0 else None
    out["sufficient"] = out["n"] >= 30
    return out


def main():
    t0 = time.time()
    syms, exc = universe()
    market, msrc = load_market()
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=1830)).strftime("%Y-%m-%d")
    frames, raws, missing = {}, {}, []
    data = {}
    for s in syms:
        try:
            df = scs_daily.fetch_scs_daily_ohlc(s, start_date=start, end_date=end)
        except Exception:
            df = pd.DataFrame()
        df = df[(df["low"] <= df[["open", "close"]].min(axis=1)) & (df[["open", "close"]].max(axis=1) <= df["high"])
                & (df["close"] > 0)] if len(df) else df
        if len(df) < 120:
            missing.append(s)
            continue
        data[s] = w2.normalise(df)
        time.sleep(0.2)
    if market is None:
        rets = pd.DataFrame({s: d["close"].pct_change().where(lambda x: x.abs() <= 0.11) for s, d in data.items()})
        market, msrc = (1 + rets.mean(axis=1).fillna(0)).cumprod(), "equal-weight universe proxy (KSE-100 unavailable)"
    print(f"{len(data)} symbols with data, missing {missing}; benchmark {msrc}; fetched in {time.time() - t0:.0f}s")
    for s, d in data.items():
        frames[s] = w2.compute(d, market)
        raws[s] = {k: d[k].to_numpy() for k in ("open", "high", "low", "close", "volume")}
        raws[s]["vsma_prior"] = d["volume"].shift(1).rolling(20).mean().to_numpy()
        raws[s]["tv20"] = (d["close"] * d["volume"]).rolling(20).mean().to_numpy()
        raws[s]["dates"] = d.index
    print(f"components computed in {time.time() - t0:.0f}s")

    all_dates = sorted({x for f in frames.values() for x in f.index[60:]})
    d0, d1 = all_dates[0], all_dates[-1]
    c_tr, c_va = d0 + (d1 - d0) * 0.6, d0 + (d1 - d0) * 0.8
    pool = pd.concat([f.loc[f.index <= c_tr, ["abs_q", "obv_q", "struct_q", "rs_q"]] for f in frames.values()])
    th = {k: round(float(pool[c].dropna().quantile(0.70)), 1)
          for k, c in (("abs", "abs_q"), ("obv", "obv_q"), ("struct", "struct_q"), ("rs", "rs_q"))}
    for f in frames.values():
        w2.classify(f, th)

    # regimes from the benchmark
    m = market.sort_index()
    s50, s200 = m.rolling(50).mean(), m.rolling(200).mean()
    trend = pd.Series(np.where((m > s50) & (s50 > s200), "Bull", np.where((m < s50) & (s50 < s200), "Bear", "Sideways")),
                      index=m.index).where(s200.notna())
    hv = np.log(m / m.shift()).rolling(20).std() * math.sqrt(252)
    hvp = hv.rolling(252, min_periods=150).apply(lambda x: (x[:-1] < x[-1]).mean() * 100, raw=True)
    volreg = pd.Series(np.where(hvp >= 70, "High vol", np.where(hvp <= 30, "Low vol", "Mid vol")), index=m.index).where(hvp.notna())

    def reg(dt, s):
        try:
            x = s.dropna().asof(dt)
        except Exception:
            return None
        return x if isinstance(x, str) else None

    events = {"original": [], "enhanced": []}
    per_class = defaultdict(list)
    unfilled = Counter()
    excluded = Counter()
    for s, f in frames.items():
        raw = raws[s]
        sig_o = (f["orig_signal"] != "NO_SIGNAL").to_numpy()
        cls = f["enh_class"].to_numpy()
        sig_e = np.isin(cls, w2.SIGNAL_CLASSES)
        rhi = f["range_hi"].to_numpy()
        for eng, sig in (("original", sig_o), ("enhanced", sig_e)):
            last = -10 ** 9
            for t in range(61, len(f) - 1):
                if sig[t] and not sig[t - 1] and t - last >= COOLDOWN:
                    rec = forward(raw, t, rhi[t])
                    if not rec:
                        continue
                    if rec.get("unfilled"):
                        unfilled[eng] += 1
                        continue
                    if rec.get("excluded"):
                        excluded[eng] += 1
                        continue
                    last = t
                    dt = f.index[t]
                    e = {"symbol": s, "date": dt, "t": t, "engine": eng, "orig": f["orig_signal"].iloc[t],
                         "enh": cls[t], "split": "train" if dt <= c_tr else "validation" if dt <= c_va else "test",
                         "trend": reg(dt, trend), "vol": reg(dt, volreg), "liquid": bool(raw["tv20"][t] >= LIQ_MIN_TV),
                         "abs_q": f["abs_q"].iloc[t], "obv_q": f["obv_q"].iloc[t], "struct_q": f["struct_q"].iloc[t],
                         "rs_q": f["rs_q"].iloc[t], **rec}
                    events[eng].append(e)
        last_c = {}
        for t in range(61, len(f) - 1):
            k = cls[t]
            if k != cls[t - 1] and k != "NO CLEAR ACCUMULATION" and t - last_c.get(k, -10 ** 9) >= COOLDOWN:
                rec = forward(raw, t, rhi[t])
                if rec and not rec.get("unfilled") and not rec.get("excluded"):
                    last_c[k] = t
                    per_class[k].append({"date": f.index[t], "split": "train" if f.index[t] <= c_tr else
                                         "validation" if f.index[t] <= c_va else "test", **rec})
    print(f"events: { {k: len(v) for k, v in events.items()} } in {time.time() - t0:.0f}s")

    # baseline: every 5th bar
    base = []
    for s, f in frames.items():
        rhi = f["range_hi"].to_numpy()
        for t in range(61, len(f) - 1, 5):
            rec = forward(raws[s], t, rhi[t])
            if rec and not rec.get("unfilled") and not rec.get("excluded"):
                base.append({"date": f.index[t], "split": "train" if f.index[t] <= c_tr else
                             "validation" if f.index[t] <= c_va else "test", **rec})

    # overlap / eliminated / earlier
    o_days = {(e["symbol"], e["date"]) for e in events["original"]}
    by_sym_e = defaultdict(list)
    for e in events["enhanced"]:
        by_sym_e[e["symbol"]].append(e["t"])
    both, only_o = [], []
    for e in events["original"]:
        near = any(abs(te - e["t"]) <= 10 for te in by_sym_e[e["symbol"]])
        (both if near else only_o).append(e)
    by_sym_o = defaultdict(list)
    for e in events["original"]:
        by_sym_o[e["symbol"]].append(e["t"])
    only_e = [e for e in events["enhanced"] if not any(abs(to - e["t"]) <= 10 for to in by_sym_o[e["symbol"]])]
    elim = [e for e in events["original"] if e["enh"] in ("NO CLEAR ACCUMULATION", "FAILED ACCUMULATION")]
    kept = [e for e in events["original"] if e["enh"] not in ("NO CLEAR ACCUMULATION", "FAILED ACCUMULATION")]

    # upper-circuit capture and lead time
    uc = {"events": 0, "orig_caught": 0, "enh_caught": 0, "orig_lead": [], "enh_lead": []}
    for s, f in frames.items():
        C, H = raws[s]["close"], raws[s]["high"]
        ucd = np.zeros(len(C), bool)
        ucd[1:] = (C[1:] / C[:-1] - 1 >= 0.095) & (C[1:] >= H[1:] * 0.999)
        start_runs = ucd & ~np.concatenate([[False], ucd[:-1]])
        so = (f["orig_signal"] != "NO_SIGNAL").to_numpy()
        se = np.isin(f["enh_class"].to_numpy(), w2.SIGNAL_CLASSES + ("DEVELOPING ACCUMULATION",))
        for t in np.flatnonzero(start_runs):
            if t < 81:
                continue
            uc["events"] += 1
            for key, sg in (("orig", so), ("enh", se)):
                w = np.flatnonzero(sg[t - 40:t])
                if len(w):
                    uc[f"{key}_lead"].append(40 - int(w[0]))
                if sg[t - 20:t].any():
                    uc[f"{key}_caught"] += 1

    def S(evs):
        return stats(evs)

    res = {"status": "ok", "label": "RESEARCH / NOT PRODUCTION", "run_at": datetime.now(timezone.utc).isoformat(),
           "benchmark": msrc, "universe": len(syms), "excluded": exc, "missing": missing,
           "data_from": str(d0.date()), "data_to": str(d1.date()),
           "splits": {"train_to": str(c_tr.date()), "validation_to": str(c_va.date())},
           "thresholds_train_p70": th, "unfilled": dict(unfilled), "excluded_corp_action": dict(excluded),
           "original_note": "daily-only replay: 4-hour BB (20 pts) unavailable historically; EXTREME cannot occur",
           "engines": {k: {"all": S(v), **{sp: S([e for e in v if e["split"] == sp]) for sp in ("train", "validation", "test")},
                           "liquid": S([e for e in v if e["liquid"]])} for k, v in events.items()},
           "baseline": {"all": S(base), "test": S([b for b in base if b["split"] == "test"])},
           "by_class": {k: {"all": S(v), "test": S([e for e in v if e["split"] == "test"])} for k, v in per_class.items()},
           "regimes": {eng: {g: {r: S([e for e in v if e[g] == r]) for r in sorted({e[g] for e in v if e[g]})}
                             for g in ("trend", "vol")} for eng, v in events.items()},
           "by_year": {eng: {str(y): S([e for e in v if e["date"].year == y]) for y in sorted({e["date"].year for e in v})}
                       for eng, v in events.items()},
           "overlap": {"both": S(both), "original_only": S(only_o), "enhanced_only": S(only_e),
                       "original_eliminated_by_2.0": S(elim), "original_kept_by_2.0": S(kept)},
           "upper_circuit": {"events": uc["events"], "orig_caught_pct": round(100 * uc["orig_caught"] / max(1, uc["events"]), 1),
                             "enh_caught_pct": round(100 * uc["enh_caught"] / max(1, uc["events"]), 1),
                             "orig_median_lead": float(np.median(uc["orig_lead"])) if uc["orig_lead"] else None,
                             "enh_median_lead": float(np.median(uc["enh_lead"])) if uc["enh_lead"] else None}}
    # false positives: enhanced test events with 20d return < -5% vs successes (>= +5%)
    te = [e for e in events["enhanced"] if "r20" in e]
    fp = [e for e in te if e["r20"] < -5]
    tp = [e for e in te if e["r20"] >= 5]
    res["false_positive_profile"] = {grp: {k: round(float(np.nanmean([e[k] for e in g])), 1) if g else None
                                           for k in ("abs_q", "obv_q", "struct_q", "rs_q")} | {"n": len(g)}
                                     for grp, g in (("losers_r20_lt_-5", fp), ("winners_r20_ge_5", tp))}
    # live candidates: latest bar per symbol
    live = []
    for s, f in frames.items():
        r = f.iloc[-1]
        live.append({"symbol": s, "date": str(f.index[-1].date()), "enh_class": r["enh_class"],
                     "confirming": int(r["confirming"]), **{k: (None if pd.isna(r[k]) else round(float(r[k]), 1))
                                                           for k in ("abs_q", "obv_q", "struct_q", "rs_q", "dist_res_pct")}})
    res["latest_candidates"] = sorted([x for x in live if x["enh_class"] in w2.SIGNAL_CLASSES + ("DEVELOPING ACCUMULATION",)],
                                      key=lambda x: (-x["confirming"], -(x["struct_q"] or 0)))
    res["elapsed_s"] = round(time.time() - t0)
    OUT_JSON.write_text(json.dumps(res, default=str))
    write_report(res)
    return 0


def _row(name, s):
    if not s or not s.get("n"):
        return f"| {name} | 0 | | | | | | | | | | |"
    ci = s.get("win_10d_ci") or (None, None)
    return (f"| {name} | {s['n']} | {s.get('mean_5d')} | {s.get('mean_10d')} | {s.get('mean_20d')} | "
            f"{s.get('win_10d')} [{ci[0]}–{ci[1]}] | {s.get('breakout_pct')} | {s.get('failed_breakout_pct')} | "
            f"{s.get('avg_mfe')} / {s.get('avg_mae')} | {s.get('uc20_pct')} | {s.get('expectancy_pct')} | {s.get('profit_factor')} |")


H = ("| Group | n | Mean 5d % | Mean 10d % | Mean 20d % | Win 10d % [95% CI] | Breakout % | Failed b/o % | "
     "MFE / MAE % | Upper circuit ≤20d % | Trade expectancy % (net) | PF |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def write_report(r):
    L = ["# Wyckoff Accumulation 2.0 — RESEARCH / NOT PRODUCTION backtest", "",
         f"Run {r['run_at'][:16]} UTC · universe {r['universe']} (excluded {r['excluded']}, no data {r['missing']}) · "
         f"{r['data_from']} → {r['data_to']} · benchmark {r['benchmark']} · train ≤ {r['splits']['train_to']}, "
         f"validation ≤ {r['splits']['validation_to']}, test after.", "",
         f"Thresholds (70th percentile on TRAIN only): {r['thresholds_train_p70']} · unfilled entries (upper-circuit "
         f"locks): {r['unfilled']} · excluded (corporate action): {r['excluded_corp_action']}", "",
         f"Original: {r['original_note']}.", "", "## Original vs Enhanced", "", H]
    for eng in ("original", "enhanced"):
        for sp in ("all", "train", "validation", "test", "liquid"):
            L.append(_row(f"{eng} — {sp}", r["engines"][eng][sp]))
    L += [_row("Baseline (every 5th session) — all", r["baseline"]["all"]),
          _row("Baseline — test", r["baseline"]["test"]), "", "## Enhanced classes (class entry events)", "", H]
    for k in w2.CLASSES:
        if k in r["by_class"]:
            L += [_row(f"{k} — all", r["by_class"][k]["all"]), _row(f"{k} — test", r["by_class"][k]["test"])]
    L += ["", "## Overlap and filtering", "", H]
    for k, v in r["overlap"].items():
        L.append(_row(k, v))
    uc = r["upper_circuit"]
    L += ["", f"## Upper-circuit capture (first day of each lock run)", "",
          f"- Events {uc['events']} · original signal in prior 20 sessions: {uc['orig_caught_pct']}% · "
          f"enhanced (DEVELOPING or stronger) in prior 20: {uc['enh_caught_pct']}%",
          f"- Median lead (sessions from first signal within prior 40 to the lock): original {uc['orig_median_lead']}, "
          f"enhanced {uc['enh_median_lead']}", "", "## Market regimes", ""]
    for eng in ("original", "enhanced"):
        L += [f"### {eng}", "", H]
        for g in ("trend", "vol"):
            for rg, s in r["regimes"][eng][g].items():
                L.append(_row(f"{g}: {rg}", s))
        L.append("")
    L += ["## Walk-forward by year", "", H]
    for eng in ("original", "enhanced"):
        for y, s in r["by_year"][eng].items():
            L.append(_row(f"{eng} {y}", s))
    L += ["", "## False-positive profile (enhanced, 20-day outcome)", "", f"{r['false_positive_profile']}", "",
          "## Latest candidates (RESEARCH)", ""]
    for x in r["latest_candidates"][:30]:
        L.append(f"- {x['symbol']} ({x['date']}): {x['enh_class']} · confirming {x['confirming']} · structure "
                 f"{x['struct_q']} · absorption {x['abs_q']} · OBV {x['obv_q']} · RS {x['rs_q']} · "
                 f"{x['dist_res_pct']}% below resistance")
    L += ["", "_RESEARCH / NOT PRODUCTION. No production threshold, weight or gate was changed._"]
    REPORT.write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
