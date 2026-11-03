#!/usr/bin/env python3
"""research_failed_accumulation.py — READ-ONLY validation study of the
Wyckoff 2.0 FAILED ACCUMULATION classification (RESEARCH / NOT PRODUCTION).

No database access: daily bars from SCS, KSE-100 from the public index API,
everything in memory, one markdown report. Nothing is redefined:
  * FAILED ACCUMULATION, components and classes: wyckoff2_research (unchanged)
  * thresholds: FROZEN values of run 41678682179 (train 70th percentiles)
  * splits: train <= 2024-12-05, validation <= 2025-11-19, test after (same run)
  * entry/exit, slippage, costs, circuit handling: run_wyckoff2_backtest.forward
  * original signals: unchanged production WyckoffDetector, daily-only replay
    (4-hour component unavailable historically -> READY only, no EXTREME)
"""
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

TH = {"abs": 52.2, "obv": 18.0, "struct": 59.3, "rs": 44.1}          # frozen, run 41678682179
TRAIN_TO, VAL_TO = pd.Timestamp("2024-12-05"), pd.Timestamp("2025-11-19")
FAILED = "FAILED ACCUMULATION"
REPORT = ROOT / "failed_accumulation_validation.md"
RNG = np.random.default_rng(20261103)


def split(dt):
    return "train" if dt <= TRAIN_TO else "validation" if dt <= VAL_TO else "test"


def summ(evs, key="r20"):
    if not evs:
        return {"n": 0}
    o = {"n": len(evs), "stocks": len({e["symbol"] for e in evs}), "dates": len({e["date"] for e in evs})}
    for h in (5, 10, 20):
        v = np.array([e[f"r{h}"] for e in evs if f"r{h}" in e])
        if len(v):
            o[f"mean{h}"], o[f"med{h}"] = round(float(v.mean()), 2), round(float(np.median(v)), 2)
    v20 = [e for e in evs if "r20" in e]
    if v20:
        f = [int(e["r20"] > 0) for e in v20]
        o["win20"], o["win20_ci"] = round(100 * np.mean(f), 1), bt.cluster_ci(f, [e["date"] for e in v20])
        o["worst20"] = round(min(e["r20"] for e in v20), 1)
    mae = [e["mae"] for e in evs if "mae" in e]
    if mae:
        for x in (3, 5, 10, 15):
            o[f"dd{x}"] = round(100 * np.mean([m <= -x for m in mae]), 1)
        o["mae"], o["mfe"] = round(float(np.mean(mae)), 2), round(float(np.mean([e["mfe"] for e in evs if "mfe" in e])), 2)
    tr = np.array([e["trade_ret"] for e in evs if "trade_ret" in e])
    if len(tr):
        w, ls = tr[tr > 0], tr[tr <= 0]
        o["pf"] = round(float(w.sum() / -ls.sum()), 2) if ls.sum() < 0 else None
        o["exp"] = round(float(tr.mean()), 2)
    return o


def boot_diff(a, b, key="r20", iters=2000):
    """Mean(a) - mean(b) with a date-cluster bootstrap (dates resampled within
    each group). Returns (diff, 95% CI, share of resamples with diff >= 0)."""
    ga, gb = defaultdict(list), defaultdict(list)
    for e in a:
        if key in e:
            ga[e["date"]].append(e[key])
    for e in b:
        if key in e:
            gb[e["date"]].append(e[key])
    if len(ga) < 5 or len(gb) < 5:
        return None
    la, lb = list(ga.values()), list(gb.values())
    obs = np.mean([x for g in la for x in g]) - np.mean([x for g in lb for x in g])
    ds = []
    for _ in range(iters):
        sa = [la[i] for i in RNG.integers(0, len(la), len(la))]
        sb = [lb[i] for i in RNG.integers(0, len(lb), len(lb))]
        ds.append(np.mean([x for g in sa for x in g]) - np.mean([x for g in sb for x in g]))
    ds = np.array(ds)
    return round(float(obs), 2), (round(float(np.percentile(ds, 2.5)), 2), round(float(np.percentile(ds, 97.5)), 2)), \
        round(float((ds >= 0).mean()), 3)


def ols_cluster(X, y, groups, names):
    X = np.column_stack([np.ones(len(y)), X])
    names = ["const"] + names
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    u = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    gs = defaultdict(list)
    for i, g in enumerate(groups):
        gs[g].append(i)
    for idx in gs.values():
        s = X[idx].T @ u[idx]
        meat += np.outer(s, s)
    G = len(gs)
    V = XtX_inv @ meat @ XtX_inv * G / max(1, G - 1)
    se = np.sqrt(np.diag(V))
    return {n: (round(float(b), 3), round(float(s), 3), round(float(b / s), 2) if s else None)
            for n, b, s in zip(names, beta, se)}


def main():
    t0 = time.time()
    syms, exc = bt.universe()
    market, msrc = bt.load_market()
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
        if len(df) < 120:
            missing.append(s)
            continue
        data[s] = w2.normalise(df)
        time.sleep(0.2)
    m = market.sort_index()
    s50, s200 = m.rolling(50).mean(), m.rolling(200).mean()
    trend = pd.Series(np.where((m > s50) & (s50 > s200), "Bull", np.where((m < s50) & (s50 < s200), "Bear", "Sideways")),
                      index=m.index).where(s200.notna()).dropna()

    orig_events, fail_events, panel = [], [], []
    for s, d in data.items():
        f = w2.compute(d, market, thresholds=TH)
        O, H, L, C, V = (d[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
        raw = {"open": O, "high": H, "low": L, "close": C, "volume": V,
               "vsma_prior": d["volume"].shift(1).rolling(20).mean().to_numpy()}
        n = len(C)
        cls, osig, osc = f["enh_class"].to_numpy(), f["orig_signal"].to_numpy(), f["orig_score"].to_numpy()
        rhi, rlo, ex20 = f["range_hi"].to_numpy(), f["range_lo"].to_numpy(), f["excess20"].to_numpy()
        fail = cls == FAILED
        atr = w2._atr(d["high"], d["low"], d["close"], 14).to_numpy()
        sma20, sma50 = d["close"].rolling(20).mean().to_numpy(), d["close"].rolling(50).mean().to_numpy()
        low20p = d["low"].shift(1).rolling(20).min().to_numpy()
        low60 = d["low"].rolling(60).min().to_numpy()
        low20 = d["low"].rolling(20).min().to_numpy()
        tv20 = (d["close"] * d["volume"]).rolling(20).mean().to_numpy()
        mom10 = np.r_[np.full(10, np.nan), C[10:] / C[:-10] - 1]
        atrp = atr / C
        atr_hi = atrp > pd.Series(atrp).rolling(250, min_periods=120).quantile(0.67).to_numpy()
        dates = d.index

        def feat(t):
            return {"prior5": (C[t] / C[t - 5] - 1) * 100, "prior10": (C[t] / C[t - 10] - 1) * 100,
                    "prior20": (C[t] / C[t - 20] - 1) * 100, "dist_low20": (C[t] / low20[t] - 1) * 100,
                    "dist_low60": (C[t] / low60[t] - 1) * 100, "atrp": atrp[t] * 100,
                    "ex20": ex20[t] if not np.isnan(ex20[t]) else 0.0, "orig_score": float(osc[t]),
                    "log_tv": math.log10(max(tv20[t], 1.0)), "regime": trend.asof(dates[t]) if dates[t] >= trend.index[0] else None,
                    "w_sma20": bool(C[t] < sma20[t]), "w_sma50": bool(C[t] < sma50[t]),
                    "w_support": bool(C[t] < low20p[t]), "w_rs": bool(ex20[t] < 0) if not np.isnan(ex20[t]) else False,
                    "w_atr_mom": bool(atr_hi[t] and mom10[t] < 0)}

        # ---- original READY/EXTREME events (first bar of a run, 20-bar cooldown; same as the backtest)
        last = -10 ** 9
        for t in range(61, n - 1):
            rdy = osig[t] in ("READY", "EXTREME")
            if not (rdy and osig[t - 1] not in ("READY", "EXTREME") and t - last >= bt.COOLDOWN):
                continue
            rec = bt.forward(raw, t, rhi[t])
            if not rec or rec.get("unfilled") or rec.get("excluded"):
                continue
            last = t
            w = np.flatnonzero(fail[max(0, t - 20):min(n, t + 11)]) + max(0, t - 20) - t   # offsets of FAILED bars
            first_after = next((int(x) for x in w if x >= 1), None)
            timing = ("before" if any(-20 <= x <= -1 for x in w) else "same day" if 0 in w else
                      "1-5 after" if first_after is not None and first_after <= 5 else
                      "6-10 after" if first_after is not None else "never")
            no_research = all(np.isnan(f[c].iloc[t]) for c in ("abs_q", "obv_q", "struct_q", "rs_q"))
            group = "D" if no_research else ("A" if (fail[max(0, t - 5):t + 1]).any() else "B")
            e = {"symbol": s, "date": dates[t], "split": split(dates[t]), "group": group, "timing": timing,
                 "first_after": first_after, **feat(t), **rec}
            if first_after is not None:          # what happens if the position is exited at the warning
                tw = t + first_after
                if tw + 1 < n:
                    E = O[t + 1] * (1 + bt.SLIP)
                    e["ret_to_warning_exit"] = (O[tw + 1] * (1 - bt.SLIP) / E - 1 - bt.COST) * 100
                    e["ret_hold20"] = (C[min(n - 1, t + 20)] * (1 - bt.SLIP) / E - 1 - bt.COST) * 100
            orig_events.append(e)

        # ---- FAILED events (first bar of a FAILED run, 20-bar cooldown) + timing
        last = -10 ** 9
        for t in range(61, n - 1):
            if not (fail[t] and not fail[t - 1] and t - last >= bt.COOLDOWN):
                continue
            rec = bt.forward(raw, t, rhi[t])
            if not rec or rec.get("unfilled") or rec.get("excluded"):
                continue
            last = t
            br = next((b for b in range(max(21, t - 20), min(n, t + 21)) if C[b] < low20p[b]), None)
            dec = {}
            for x in (3, 5, 10):
                j = next((j for j in range(t + 1, min(n, t + 21)) if C[j] <= C[t] * (1 - x / 100)), None)
                dec[f"t_dec{x}"] = (j - t) if j is not None else None
            peak = C[max(0, t - 20):t + 1].max()
            trough = C[t:min(n, t + 21)].min()
            done = (peak - C[t]) / (peak - trough) if peak > trough else 1.0
            fwd_min = (C[t + 1:min(n, t + 21)].min() / C[t] - 1) * 100 if t + 1 < n else np.nan
            e = {"symbol": s, "date": dates[t], "split": split(dates[t]),
                 "group": "C" if osig[t] in ("WATCH", "NO_SIGNAL") else "A-type",
                 "lead_vs_support20": (br - t) if br is not None else None, "share_of_decline_done": done,
                 "fwd_min20": fwd_min, "recovered20": bool(t + 20 < n and C[t + 20] > C[t]), **dec, **feat(t), **rec}
            fail_events.append(e)

        # ---- panel for controls / simple-warning comparison (every 5th bar)
        for t in range(81, n - 1, 5):
            if np.isnan(f["struct_q"].iloc[t]):
                continue
            rec = bt.forward(raw, t, rhi[t])
            if not rec or rec.get("unfilled") or rec.get("excluded") or "r20" not in rec:
                continue
            panel.append({"symbol": s, "date": dates[t], "split": split(dates[t]), "failed": bool(fail[t]),
                          "orig_ready": osig[t] in ("READY", "EXTREME"), **feat(t), "r20": rec["r20"], "r10": rec.get("r10")})
    print(f"computed in {time.time() - t0:.0f}s: {len(orig_events)} original events, {len(fail_events)} FAILED events, "
          f"{len(panel)} panel rows; missing {missing}")
    write_report(orig_events, fail_events, panel, msrc, missing, exc)
    return 0


def tbl(rows):
    H = ("| Group | Events | Stocks | Mean 5/10/20d % | Median 20d % | Win 20d % [95% CI] | DD≥3/5/10/15 % | "
         "MAE / MFE % | Worst 20d % | Trade PF / expectancy % |\n|---|---|---|---|---|---|---|---|---|---|")
    out = [H]
    for name, s in rows:
        if not s.get("n"):
            out.append(f"| {name} | 0 | | | | | | | | |")
            continue
        ci = s.get("win20_ci", (None, None))
        out.append(f"| {name} | {s['n']} | {s['stocks']} | {s.get('mean5')} / {s.get('mean10')} / {s.get('mean20')} | "
                   f"{s.get('med20')} | {s.get('win20')} [{ci[0]}–{ci[1]}] | {s.get('dd3')} / {s.get('dd5')} / "
                   f"{s.get('dd10')} / {s.get('dd15')} | {s.get('mae')} / {s.get('mfe')} | {s.get('worst20')} | "
                   f"{s.get('pf')} / {s.get('exp')} |")
    return out


def pct(x, q):
    x = [v for v in x if v is not None]
    return round(float(np.percentile(x, q)), 1) if x else None


def write_report(oe, fe, panel, msrc, missing, exc):
    L = ["# FAILED ACCUMULATION — read-only validation (RESEARCH / NOT PRODUCTION)", "",
         f"Benchmark {msrc} · thresholds frozen {TH} · splits train ≤ {TRAIN_TO.date()}, validation ≤ {VAL_TO.date()}, "
         f"test after · excluded {exc} · no SCS data {missing} · 0 database reads/writes.", "",
         "Original signals are the unchanged detector replayed on daily data only (4-hour component unavailable "
         "historically): READY only, EXTREME cannot occur.", ""]
    for sp in ("test", "all", "train", "validation"):
        sel = [e for e in oe if sp == "all" or e["split"] == sp]
        A, B, D = ([e for e in sel if e["group"] == g] for g in "ABD")
        C = [e for e in fe if (sp == "all" or e["split"] == sp) and e["group"] == "C"]
        L += [f"## B. Core table — {sp.upper()}", ""] + tbl([
            ("A: original READY + FAILED (at/≤5 sessions before signal)", summ(A)),
            ("B: original READY, no FAILED", summ(B)), ("C: FAILED while original WATCH/NO SIGNAL", summ(C)),
            ("D: original READY, no research observation", summ(D))])
        for h in ("r5", "r10", "r20"):
            bd = boot_diff(A, B, h)
            L.append(f"- A − B mean {h}: {bd[0] if bd else 'insufficient'}"
                     + (f" pts, 95% CI {bd[1]}, share of resamples ≥ 0: {bd[2]}" if bd else ""))
        L.append("")
    # timing
    L += ["## C. Warning timing (FAILED events, first bar of each FAILED run)", ""]
    for sp in ("test", "all"):
        sel = [e for e in fe if sp == "all" or e["split"] == sp]
        lead = [e["lead_vs_support20"] for e in sel]
        known = [x for x in lead if x is not None]
        L += [f"### {sp.upper()} (n={len(sel)}, stocks {len({e['symbol'] for e in sel})})", "",
              "- By construction FAILED fires on the first close below the 40-session base low, i.e. AT the base breakdown.",
              f"- Versus the first close below the prior 20-session low (shorter support): median lead "
              f"{pct(known, 50)} sessions (25th {pct(known, 25)}, 75th {pct(known, 75)}); warning before that break "
              f"{round(100 * np.mean([x > 0 for x in known]), 1) if known else None}%, same day "
              f"{round(100 * np.mean([x == 0 for x in known]), 1) if known else None}%, after "
              f"{round(100 * np.mean([x < 0 for x in known]), 1) if known else None}%",
              f"- Share of the 20-session peak-to-trough decline already done when the warning appeared: median "
              f"{pct([e['share_of_decline_done'] * 100 for e in sel], 50)}% (25th {pct([e['share_of_decline_done'] * 100 for e in sel], 25)}, "
              f"75th {pct([e['share_of_decline_done'] * 100 for e in sel], 75)}); warnings before most of the decline (<50% done): "
              f"{round(100 * np.mean([e['share_of_decline_done'] < 0.5 for e in sel]), 1) if sel else None}%",
              f"- Sessions from warning until a further 3/5/10% fall: median {pct([e['t_dec3'] for e in sel], 50)} / "
              f"{pct([e['t_dec5'] for e in sel], 50)} / {pct([e['t_dec10'] for e in sel], 50)}; reached: "
              f"{round(100 * np.mean([e['t_dec3'] is not None for e in sel]), 1)}% / "
              f"{round(100 * np.mean([e['t_dec5'] is not None for e in sel]), 1)}% / "
              f"{round(100 * np.mean([e['t_dec10'] is not None for e in sel]), 1)}%",
              f"- No meaningful further downside (20-session low not 5% below warning close): "
              f"{round(100 * np.mean([e['fwd_min20'] > -5 for e in sel]), 1)}% · recovered above warning close after 20: "
              f"{round(100 * np.mean([e['recovered20'] for e in sel]), 1)}%", ""]
    # original-signal timing and filter value
    L += ["## D. Original READY signals: when FAILED appears, and precision / recall", ""]
    for sp in ("test", "all"):
        sel = [e for e in oe if (sp == "all" or e["split"] == sp) and "r20" in e]
        cnt = pd.Series([e["timing"] for e in sel]).value_counts().to_dict()
        L.append(f"### {sp.upper()} (n={len(sel)})")
        L.append(f"- FAILED relative to the original signal: {cnt}")
        for name, rule in (("flag available at entry (A)", lambda e: e["group"] == "A"),
                           ("flag at entry or within 5 sessions", lambda e: e["timing"] in ("before", "same day", "1-5 after")),
                           ("flag at any time ≤10 sessions", lambda e: e["timing"] != "never")):
            y = np.array([e["r20"] < 0 for e in sel], dtype=bool)
            p = np.array([rule(e) for e in sel], dtype=bool)
            tp, fp, fn = int((p & y).sum()), int((p & ~y).sum()), int((~p & y).sum())
            tn = int((~p & ~y).sum())
            L.append(f"- {name}: flagged {int(p.sum())} · precision {round(100 * tp / max(1, tp + fp), 1)}% · recall "
                     f"{round(100 * tp / max(1, tp + fn), 1)}% · false-positive rate {round(100 * fp / max(1, fp + tn), 1)}% · "
                     f"losers caught {tp}/{tp + fn} · winners wrongly flagged {fp}/{fp + tn}")
        ex = [e for e in sel if "ret_to_warning_exit" in e and e["timing"] in ("1-5 after", "6-10 after")]
        if ex:
            dif = [e["ret_to_warning_exit"] - e["ret_hold20"] for e in ex]
            L.append(f"- Exit at the warning (signals warned 1–10 sessions after entry, n={len(ex)}): mean net "
                     f"{round(float(np.mean([e['ret_to_warning_exit'] for e in ex])), 2)}% vs holding 20 sessions "
                     f"{round(float(np.mean([e['ret_hold20'] for e in ex])), 2)}% · improved {sum(x > 0 for x in dif)}, "
                     f"worsened {sum(x <= 0 for x in dif)} · mean change {round(float(np.mean(dif)), 2)} pts")
        avoided = [e["r20"] for e in sel if e["group"] == "A"]
        L.append(f"- Excluding group A at entry: removes {len(avoided)} signals with mean 20d {round(float(np.mean(avoided)), 2) if avoided else None}% "
                 f"(losses avoided {round(float(sum(-x for x in avoided if x < 0)), 1)} pts, gains forgone "
                 f"{round(float(sum(x for x in avoided if x > 0)), 1)} pts)")
        L.append("")
    # controls
    L += ["## E. Independent predictive value (panel, every 5th session; OLS of 20-session return, date-clustered SE)", ""]
    dfp = pd.DataFrame(panel)
    base = ["prior5", "prior10", "prior20", "dist_low20", "dist_low60", "atrp", "ex20", "orig_score", "log_tv"]
    simple = ["w_sma20", "w_sma50", "w_support", "w_rs", "w_atr_mom"]
    for sp in ("test", "all"):
        sub = dfp if sp == "all" else dfp[dfp["split"] == sp]
        sub = sub.dropna(subset=base + ["r20"])
        reg = pd.get_dummies(sub["regime"].fillna("NA"), prefix="reg", drop_first=True).astype(float)
        X1 = np.column_stack([sub["failed"].astype(float)] + [sub[c].to_numpy(float) for c in base] + [reg.to_numpy()])
        n1 = ["FAILED"] + base + list(reg.columns)
        r1 = ols_cluster(X1, sub["r20"].to_numpy(float), sub["date"].astype(str).to_numpy(), n1)
        X2 = np.column_stack([X1] + [sub[c].astype(float).to_numpy() for c in simple])
        r2 = ols_cluster(X2, sub["r20"].to_numpy(float), sub["date"].astype(str).to_numpy(), n1 + simple)
        uncond = sub.groupby("failed")["r20"].mean().round(2).to_dict()
        L += [f"### {sp.upper()} (rows {len(sub)}, FAILED rows {int(sub['failed'].sum())}, stocks {sub['symbol'].nunique()})",
              f"- Unconditional mean 20d: FAILED {uncond.get(True)}% vs not {uncond.get(False)}%",
              f"- FAILED coefficient with price/volatility/RS/score/regime/liquidity controls: {r1['FAILED']} (beta, SE, t)",
              f"- ... plus all five simple warnings: FAILED {r2['FAILED']} · " +
              " · ".join(f"{k} {r2[k]}" for k in simple)]
        # coarsened matching on prior weakness
        q = sub.copy()
        for c in ("prior20", "dist_low20"):
            q[c + "_b"] = pd.qcut(q[c], 5, labels=False, duplicates="drop")
        cells = q.groupby(["prior20_b", "dist_low20_b", "regime"], dropna=False)
        diffs, wts = [], []
        for _, g in cells:
            a, b2 = g[g["failed"]], g[~g["failed"]]
            if len(a) >= 3 and len(b2) >= 3:
                diffs.append(a["r20"].mean() - b2["r20"].mean())
                wts.append(len(a))
        L.append(f"- Matched on prior 20d return, distance from 20d low and regime (quintile cells): weighted mean "
                 f"difference FAILED − similar unflagged = "
                 f"{round(float(np.average(diffs, weights=wts)), 2) if diffs else None} pts over {sum(wts)} FAILED rows in {len(diffs)} cells")
        L.append("")
    # regimes
    L += ["## F. Market regimes (FAILED events and original-signal groups)", ""]
    for sp in ("test", "all"):
        L.append(f"### {sp.upper()}")
        for rg in ("Bull", "Bear", "Sideways"):
            fsel = [e for e in fe if (sp == "all" or e["split"] == sp) and e["regime"] == rg]
            A = [e for e in oe if (sp == "all" or e["split"] == sp) and e["regime"] == rg and e["group"] == "A"]
            B = [e for e in oe if (sp == "all" or e["split"] == sp) and e["regime"] == rg and e["group"] == "B"]
            sf, sa, sb = summ(fsel), summ(A), summ(B)
            lead = [e["lead_vs_support20"] for e in fsel if e["lead_vs_support20"] is not None]
            L.append(f"- {rg}: FAILED n={sf.get('n')} mean 5/10/20d {sf.get('mean5')}/{sf.get('mean10')}/{sf.get('mean20')} · "
                     f"win20 {sf.get('win20')} · DD5/10 {sf.get('dd5')}/{sf.get('dd10')} · lead vs 20d support median "
                     f"{pct(lead, 50)} · A n={sa.get('n')} mean20 {sa.get('mean20')} vs B n={sb.get('n')} mean20 {sb.get('mean20')}")
        L.append("")
    # simple warnings
    L += ["## G. Simple price-based warnings (panel, mean 20d flagged vs unflagged)", "",
          "| Warning | Split | Flagged rows | Mean 20d flagged % | Mean 20d unflagged % | Difference |", "|---|---|---|---|---|---|"]
    for sp in ("test", "all"):
        sub = dfp if sp == "all" else dfp[dfp["split"] == sp]
        for w in ["failed"] + simple:
            a, b2 = sub[sub[w]], sub[~sub[w]]
            L.append(f"| {w} | {sp} | {len(a)} | {round(a['r20'].mean(), 2)} | {round(b2['r20'].mean(), 2)} | "
                     f"{round(a['r20'].mean() - b2['r20'].mean(), 2)} |")
    L += ["", "_RESEARCH / NOT PRODUCTION · read-only · nothing redefined · 0 database reads/writes._"]
    REPORT.write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
