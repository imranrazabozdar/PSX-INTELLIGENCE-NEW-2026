#!/usr/bin/env python3
"""ignition_patterns_audit.py -- READ-ONLY 2026 ignition-pattern study.

Finds distinct +10% rallies (ignition day T0 in 2026) and classifies the pre-ignition
archetype, then compares T-1 fingerprints of >=+15% winners with non-igniting 2026 days.

Reuses, does not reimplement:
  analysis/watchlist_breakout_audit.py  open_db, load_bars, upper_lock, TICK
  analysis/phase_d_ytd_audit.py         GuardDB (SELECT/PRAGMA only), load_universe, print_table
  fire_engine/phase_d_detector.py       RULES, _ema, evaluate (SHELF_BREAKOUT check for PHASE_D_SHELF)
  fire_engine/phase_d_badges.py         compute_badges (PRICE_TIER)

Universe : fire_engine/config/fire_config.yaml stocks.universe
Window   : daily_ohlc from 2025-01-01 (warm-up); T0 candidates 2026-01-01 .. 2026-11-24.
Outputs  : <out-dir>/ignition_patterns.csv (one row per distinct rally)
           <out-dir>/ignition_patterns_report.txt (Sections 1-4, assumptions, skipped symbols)

  python analysis/ignition_patterns_audit.py [--local-db PATH] [--out-dir DIR]
"""
import argparse
import bisect
import csv
import os
import statistics
import sys
from datetime import date as _date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend"), str(ROOT / "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)
import watchlist_breakout_audit as A  # noqa: E402
import phase_d_ytd_audit as Y  # noqa: E402
from fire_engine import phase_d_detector as D  # noqa: E402
from fire_engine import phase_d_badges as BD  # noqa: E402

R = D.RULES
SRC_START, YEAR_START, END = "2025-01-01", "2026-01-01", "2026-11-24"
TABLE = "daily_ohlc"
TARGET, WINDOW, COOLDOWN = 0.10, 15, 10
LIQ_PKR = 5_000_000
PATTERNS = ["PHASE_D_SHELF", "COLD_CATALYST_SPIKE", "QUIET_SQUEEZE", "PULLBACK_RECLAIM",
            "STEADY_TREND_GRINDER", "UNCLASSIFIED"]
TIER_SHORT = {BD.TIER_SWEET: "SWEET", BD.TIER_MID: "MID", BD.TIER_HEAVY: "HEAVY"}
CSV_COLS = ["symbol", "ignition_date", "entry_basis", "entry_price", "locked_unfillable", "fillable",
            "bucket", "peak_gain_pct", "peak_date", "days_to_peak", "ge15", "window_status", "price_tier",
            "liquidity", "med20_value_pkr_T1", "pattern", "rvol_T1", "rvol_T0", "atr_ratio_T1", "bb_pctile_T1",
            "rsi14_T1", "mfi14_T1", "obv_slope10_T1", "above_sma200_T1", "above_sma50_T1", "rs1w_pos_T1"]


# ---------------------------------------------------------------- indicator series (pure python)
def ewm(vals, alpha):
    out, e = [], None
    for v in vals:
        e = v if e is None else alpha * v + (1 - alpha) * e
        out.append(e)
    return out


def sma(vals, n):
    out, s = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def series(bars):
    n = len(bars)
    d = [b["date"] for b in bars]
    O, H, L, C, V = ([b[k] for b in bars] for k in ("open", "high", "low", "close", "volume"))
    tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
    up = ewm([0.0] + [max(C[i] - C[i - 1], 0.0) for i in range(1, n)], 1 / 14)
    dn = ewm([0.0] + [max(C[i - 1] - C[i], 0.0) for i in range(1, n)], 1 / 14)
    rsi = [None if i < 14 else (100.0 if dn[i] == 0 else 100 - 100 / (1 + up[i] / dn[i])) for i in range(n)]
    tp = [(H[i] + L[i] + C[i]) / 3 for i in range(n)]
    mf = [tp[i] * V[i] for i in range(n)]
    pf = [mf[i] if i and tp[i] > tp[i - 1] else 0.0 for i in range(n)]
    nf = [mf[i] if i and tp[i] < tp[i - 1] else 0.0 for i in range(n)]
    mfi = [None] * n
    for i in range(14, n):
        p, q = sum(pf[i - 13:i + 1]), sum(nf[i - 13:i + 1])
        mfi[i] = 100 * p / (p + q) if p + q > 0 else None
    obv = [0.0] * n
    for i in range(1, n):
        sg = (C[i] > C[i - 1]) - (C[i] < C[i - 1])
        obv[i] = obv[i - 1] + sg * V[i]
    bbw = [None] * n
    for i in range(19, n):
        w = C[i - 19:i + 1]
        m = sum(w) / 20
        sd = (sum((x - m) ** 2 for x in w) / 20) ** 0.5
        bbw[i] = 4 * sd / m if m else None
    bbpct = [None] * n
    for i in range(138, n):
        w = bbw[i - 119:i + 1]
        if bbw[i] is not None and all(x is not None for x in w):
            bbpct[i] = 100 * sum(1 for x in w if x <= bbw[i]) / 120
    rvol = [None] * n
    for i in range(20, n):
        m = sum(V[i - 20:i]) / 20
        rvol[i] = V[i] / m if m else None
    cv = [C[i] * V[i] for i in range(n)]
    med20 = [None] * n
    for i in range(19, n):
        med20[i] = statistics.median(cv[i - 19:i + 1])
    ret13 = [None] * n
    for i in range(n):
        k = bisect.bisect_right(d, (_date.fromisoformat(d[i]) - timedelta(days=91)).isoformat()) - 1
        if 0 <= k < i:
            ret13[i] = C[i] / C[k] - 1
    return {"d": d, "O": O, "H": H, "L": L, "C": C, "V": V,
            "ema10": D._ema(C, 10), "ema20": D._ema(C, 20),
            "sma50": sma(C, 50), "sma200": sma(C, 200),
            "atr14": ewm(tr, 1 / 14), "atr50": ewm(tr, 1 / 50),
            "rsi": rsi, "mfi": mfi, "obv": obv, "bbpct": bbpct, "rvol": rvol, "med20": med20,
            "ret13": ret13, "rs1w": None}


def state(s, i):
    """Indicator state at bar i (used with i = T-1 for a T0 at T)."""
    C, V = s["C"], s["V"]
    obv_slope = None
    if i >= 10:
        vs = sum(V[i - 9:i + 1])
        obv_slope = (s["obv"][i] - s["obv"][i - 10]) / vs if vs else None
    a14, a50 = s["atr14"][i], s["atr50"][i]
    return {"rvol": s["rvol"][i], "atr_ratio": a14 / a50 if a50 else None, "bbpct": s["bbpct"][i],
            "rsi": s["rsi"][i], "mfi": s["mfi"][i], "obv_slope": obv_slope,
            "above200": None if s["sma200"][i] is None else C[i] > s["sma200"][i],
            "above50": None if s["sma50"][i] is None else C[i] > s["sma50"][i],
            "rs_pos": None if s["rs1w"][i] is None else s["rs1w"][i] > 0}


def classify(bars, s, t, sig):
    d, O, L, C = s["d"], s["O"], s["L"], s["C"]
    e10, e20 = s["ema10"], s["ema20"]
    if t < 30:                             # too little history for the 20-session swing-low window
        return "UNCLASSIFIED"
    if sig and sig.get("signal_type") == "SHELF_BREAKOUT":
        ign = bisect.bisect_left(d, sig["ignition_date"])
        if 3 <= t - ign <= 12:
            return "PHASE_D_SHELF"
    f1 = state(s, t - 1)
    rv0 = s["rvol"][t]
    prev10 = range(t - 10, t)
    above20 = sum(1 for k in prev10 if C[k] > e20[k])
    rv_prev = [s["rvol"][k] for k in prev10 if s["rvol"][k] is not None]
    mean_rv = sum(rv_prev) / len(rv_prev) if rv_prev else None
    if rv0 is not None and rv0 >= 2.5 and above20 <= 3 and f1["bbpct"] is not None and f1["bbpct"] > 30:
        return "COLD_CATALYST_SPIKE"
    squeeze = (f1["bbpct"] is not None and f1["bbpct"] <= 25) or (f1["atr_ratio"] is not None and f1["atr_ratio"] <= 0.9)
    flow = (f1["obv_slope"] is not None and f1["obv_slope"] >= 0) or (f1["mfi"] is not None and f1["mfi"] >= 50)
    if squeeze and mean_rv is not None and mean_rv < 0.8 and flow:
        return "QUIET_SQUEEZE"
    near = abs(C[t - 1] / e10[t - 1] - 1) <= 0.02 or abs(C[t - 1] / e20[t - 1] - 1) <= 0.02
    min5 = min(L[t - 5:t])
    swing = min(L[t - 24:t - 4])          # prior 20-session swing low, before the 5-session window
    undercut = min5 < e20[t - 1] or min5 < swing
    reclaim = C[t] > e10[t] and C[t] > O[t]
    if near and undercut and reclaim:
        return "PULLBACK_RECLAIM"
    if rv0 is not None and rv0 < 2.0 and above20 >= 5:
        return "STEADY_TREND_GRINDER"
    return "UNCLASSIFIED"


# ---------------------------------------------------------------- stats helpers
def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def share(flags):
    known = [f for f in flags if f is not None]
    return 100.0 * sum(1 for f in known if f) / len(known) if known else None


def fx(x, nd=2):
    if x is None:
        return "-"
    if isinstance(x, bool):
        return str(x)
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    a = ap.parse_args(argv)
    if not a.local_db and not (os.getenv("LIBSQL_URL") or os.getenv("TURSO_DATABASE_URL")):
        sys.exit("No data source: pass --local-db PATH or set LIBSQL_URL")
    a.host = None
    raw, _src = A.open_db(a)          # source address deliberately not printed
    db = Y.GuardDB(raw)
    have = A.table_names(db)
    if TABLE not in have:
        sys.exit(f"{TABLE} not found in data source")
    universe = Y.load_universe()

    print("[turso usage] read-only audit: SELECT/PRAGMA only, rows written: 0 (GuardDB refuses all other statements)")
    print(f"Universe: {len(universe)} symbols (fire_config.yaml stocks.universe)")
    print(f"Window  : warm-up {SRC_START} | T0 candidates {YEAR_START} .. {END}")

    per, skipped = {}, []
    for sym in universe:
        bars = [b for b in A.load_bars(db, TABLE, sym) if SRC_START <= b["date"] <= END]
        if len(bars) < 60:
            skipped.append(f"{sym}({len(bars)})")
            continue
        per[sym] = (bars, series(bars))

    # 1W RS = 13-week return minus equal-weighted universe 13-week return on the same date
    ew = {}
    for _, s in per.values():
        for i, x in enumerate(s["ret13"]):
            if x is not None:
                ew.setdefault(s["d"][i], []).append(x)
    ew_mean = {k: sum(v) / len(v) for k, v in ew.items()}
    for _, s in per.values():
        s["rs1w"] = [None if x is None else x - ew_mean[s["d"][i]] for i, x in enumerate(s["ret13"])]

    rallies, nonign = [], []
    for sym, (bars, s) in per.items():
        d, O, H, L, C, ema10 = s["d"], s["O"], s["H"], s["L"], s["C"], s["ema10"]
        n = len(bars)
        t_start = bisect.bisect_left(d, YEAR_START)
        t0s, last = set(), -10 ** 9
        for t in range(max(1, t_start), n):
            if d[t] > END:
                break
            if t <= last + COOLDOWN:
                continue
            gap_up = O[t] > C[t - 1]
            entry = O[t] if gap_up else C[t]
            target = entry * (1 + TARGET)
            hit, peak, pk, exit_j = False, float("-inf"), None, None
            for j in range(t + 1, min(n, t + 1 + WINDOW)):
                if H[j] > peak:
                    peak, pk = H[j], j
                if H[j] >= target:
                    hit = True
                if C[j] < ema10[j]:
                    exit_j = j
                    break
            if not hit:
                continue
            last = t
            t0s.add(t)
            if exit_j is not None:
                wstat = f"EMA10_BREAK@{d[exit_j]}"
            elif t + WINDOW < n:
                wstat = "WINDOW_END"
            else:
                wstat = "DATA_END_TRUNCATED"
            locked = abs(O[t] - H[t]) < A.TICK and abs(H[t] - L[t]) < A.TICK and H[t] >= A.upper_lock(C[t - 1]) - A.TICK
            peak_gain = (peak / entry - 1) * 100
            sig = D.evaluate(bars[max(0, t - R["bars"] + 1):t + 1])
            pattern = classify(bars, s, t, sig)
            price_tier = BD.compute_badges(bars[max(0, t - 399):t + 1], d[t], d[t])["price_tier"]
            med20 = s["med20"][t - 1]
            st1 = state(s, t - 1)
            rallies.append({
                "symbol": sym, "ignition_date": d[t], "entry_basis": "OPEN_GAP" if gap_up else "CLOSE",
                "entry_price": round(entry, 2), "locked_unfillable": locked, "fillable": not locked,
                "bucket": ">=+15%" if peak_gain >= 15 else "+10-14.9%", "peak_gain_pct": round(peak_gain, 2),
                "peak_date": d[pk], "days_to_peak": pk - t, "ge15": peak_gain >= 15, "window_status": wstat,
                "price_tier": TIER_SHORT.get(price_tier, price_tier),
                "liquidity": "LIQUID" if med20 is not None and med20 >= LIQ_PKR else "ILLIQUID",
                "med20_value_pkr_T1": None if med20 is None else round(med20, 0),
                "pattern": pattern, "rvol_T1": st1["rvol"], "rvol_T0": s["rvol"][t],
                "atr_ratio_T1": st1["atr_ratio"], "bb_pctile_T1": st1["bbpct"], "rsi14_T1": st1["rsi"],
                "mfi14_T1": st1["mfi"], "obv_slope10_T1": st1["obv_slope"], "above_sma200_T1": st1["above200"],
                "above_sma50_T1": st1["above50"], "rs1w_pos_T1": st1["rs_pos"], "_st1": st1,
            })
        for t in range(max(1, t_start), n):
            if d[t] > END:
                break
            if t not in t0s:
                nonign.append(state(s, t - 1))
    db_stats = (db.reads, db.writes_refused)

    # ------------------------------------------------------------ report
    W = [" "]
    def add(*lines):
        W.extend(lines)
    tot = len(rallies)
    fil = sum(1 for r in rallies if r["fillable"])
    lockn = tot - fil
    winners = [r for r in rallies if r["ge15"]]
    liq = lambda rs: [r for r in rs if r["liquidity"] == "LIQUID"]  # noqa: E731

    add("=" * 100, "IGNITION PATTERNS AUDIT (2026)  -- READ-ONLY", "=" * 100,
        f"Symbols analysed: {len(per)} of {len(universe)} | skipped (<60 bars): {len(skipped)}",
        f"Distinct rallies: {tot} | fillable: {fil} | UNFILLABLE_LOCK: {lockn}", "")

    add("SECTION 1 -- Distinct rallies by peak bucket", "-" * 100)
    cols1 = ["Bucket", "Total", "Fillable", "Locked-gap", "SWEET", "MID", "HEAVY", "LIQ>=5M", "ILLIQ"]
    rows1 = []
    for b in ["+10-14.9%", ">=+15%", "ALL"]:
        rs = rallies if b == "ALL" else [r for r in rallies if r["bucket"] == b]
        f = [r for r in rs if r["fillable"]]
        def split(key, val):
            sub = [r for r in rs if r[key] == val]
            return f"{len(sub)}({sum(1 for r in sub if r['fillable'])})"
        rows1.append({"Bucket": b, "Total": len(rs), "Fillable": len(f), "Locked-gap": len(rs) - len(f),
                      "SWEET": split("price_tier", "SWEET"), "MID": split("price_tier", "MID"),
                      "HEAVY": split("price_tier", "HEAVY"), "LIQ>=5M": split("liquidity", "LIQUID"),
                      "ILLIQ": split("liquidity", "ILLIQUID")})
    add(*Y.print_table(rows1, cols1), "  (tier / liquidity cells: total(fillable))", "")

    def pattern_rows(rs):
        out = []
        for p in PATTERNS:
            sub = [r for r in rs if r["pattern"] == p]
            out.append({"Pattern": p, "Count": len(sub),
                        "% Share": f"{100 * len(sub) / len(rs):.1f}" if rs else "-",
                        "Med Peak Gain %": fx(med([r["peak_gain_pct"] for r in sub]), 2),
                        "Med Days to Peak": fx(med([r["days_to_peak"] for r in sub]), 1),
                        "% Above 50-SMA T-1": fx(share([r["_st1"]["above50"] for r in sub]), 1),
                        "% 1W RS>0 T-1": fx(share([r["_st1"]["rs_pos"] for r in sub]), 1)})
        return out
    cols2 = ["Pattern", "Count", "% Share", "Med Peak Gain %", "Med Days to Peak", "% Above 50-SMA T-1", "% 1W RS>0 T-1"]
    add("SECTION 2 -- Pattern stats, ALL distinct rallies", "-" * 100)
    add(*Y.print_table(pattern_rows(rallies), cols2), "")
    add("SECTION 2b -- Pattern stats, >=+15% subset", "-" * 100)
    add(*Y.print_table(pattern_rows(winners), cols2), "")

    add("SECTION 3 -- T-1 fingerprint: >=+15% winners vs non-igniting 2026 symbol-days", "-" * 100)
    metrics = [("RVOL(T-1)", "rvol"), ("ATR_Ratio_14_50", "atr_ratio"), ("BB_Width_Pctile", "bbpct"),
               ("RSI14", "rsi"), ("MFI14", "mfi"), ("OBV_Slope_10D", "obv_slope")]
    rows3 = []
    for label, k in metrics:
        wv, nv = med([r["_st1"][k] for r in winners]), med([x[k] for x in nonign])
        rows3.append({"Metric": label, "Winners median": fx(wv, 3), "Non-igniting median": fx(nv, 3),
                      "Ratio W/N": fx(wv / nv, 2) if wv is not None and nv and wv * nv > 0 else "n/m"})
    wa, na = share([r["_st1"]["above200"] for r in winners]), share([x["above200"] for x in nonign])
    rows3.append({"Metric": "% Above 200-SMA (share)", "Winners median": fx(wa, 1), "Non-igniting median": fx(na, 1),
                  "Ratio W/N": fx(wa / na, 2) if wa is not None and na else "-"})
    add(*Y.print_table(rows3, ["Metric", "Winners median", "Non-igniting median", "Ratio W/N"]),
        f"  winners N={len(winners)} | non-igniting symbol-days N={len(nonign)}", "")

    add("SECTION 4 -- Top 25 liquid >=+15% rallies (LIQ >= PKR 5M at T-1), by peak gain", "-" * 100)
    top = sorted(liq(winners), key=lambda r: r["peak_gain_pct"], reverse=True)[:25]
    rows4 = [{"Symbol": r["symbol"], "Tier": r["price_tier"], "Ignition Date": r["ignition_date"],
              "Pattern": r["pattern"], "T-1 RVOL": fx(r["rvol_T1"]), "T0 RVOL": fx(r["rvol_T0"]),
              "Peak Gain %": fx(r["peak_gain_pct"]), "Days to Peak": r["days_to_peak"]} for r in top]
    add(*Y.print_table(rows4, ["Symbol", "Tier", "Ignition Date", "Pattern", "T-1 RVOL", "T0 RVOL",
                               "Peak Gain %", "Days to Peak"]), "")

    add("ASSUMPTIONS", "-" * 100,
        f"1  Universe = fire_config stocks.universe ({len(universe)} symbols, deduped, no exclusion list applied).",
        "2  Entry = Open(T0) if Open(T0) > Close(T-1) else Close(T0). Target = entry*1.10.",
        f"3  Rally window = next {WINDOW} sessions, stopped at the first close < EMA10 (that session's high is included).",
        "   Qualifies if high >= target before/on the EMA10-break session. Peak = max high over that window.",
        "   Windows that run past data end are kept and tagged DATA_END_TRUNCATED (count of such rallies in CSV).",
        f"4  Cooldown: after a qualifying T0, candidates T0+1..T0+{COOLDOWN} are ignored.",
        "5  UNFILLABLE_LOCK = |O-H|<0.011 and |H-L|<0.011 on T0 and H >= upper_lock(Close(T-1)) - 0.011.",
        "   Kept in all totals; excluded from fillable counts in Section 1.",
        "6  Sections 2 and 2b / 3 use ALL distinct rallies (locked included) as literally specified; Section 1 splits fillable.",
        "7  Peak bucket: >=+15% if peak gain >= 15.0 (max high in window), else +10-14.9%.",
        "8  ATR14 and ATR50 = Wilder EWM (alpha 1/14, 1/50) of True Range. RSI14 and OBV standard; MFI14 = 14-session rolling flow.",
        "9  BB width = 4*sd20 / mean20 (population sd). BB_Width_Pctile = % of trailing 120 widths <= current.",
        "10 Liquidity = median(close*volume) over the 20 sessions ending T-1 >= PKR 5M.",
        "11 1W RS = 13-week return (91 calendar days, last session on/before) minus equal-weighted universe mean 13-week return on that date.",
        "12 PHASE_D_SHELF = evaluate() on 90-bar window ending T0 returns SHELF_BREAKOUT and its ignition is 3-12 sessions earlier.",
        "13 COLD: RVOL(T0)>=2.5, <=3 of T-10..T-1 closes above EMA20, BB pctile(T-1)>30.",
        "14 QUIET: (BB pctile<=25 or ATR ratio<=0.9 at T-1), mean RVOL(T-10..T-1)<0.8, (OBV slope>=0 or MFI>=50 at T-1).",
        "15 PULLBACK: |Close(T-1)/EMA10-1|<=2% or |Close(T-1)/EMA20-1|<=2%; min Low(T-5..T-1) < EMA20(T-1) or < min Low of the 20 sessions before that window; Close(T0)>EMA10(T0) and green bar.",
        "16 STEADY: RVOL(T0)<2.0 and >=5 of T-10..T-1 closes above EMA20 (the 'T0 close' clause read as this count).",
        "17 Non-igniting sample = every 2026 symbol-day that is not a qualifying T0; its fingerprint uses the prior session (same lag as T-1).",
        "18 Section 3 'median' for % Above 200-SMA is reported as a share of days. Ratio = winners / non-igniting.",
        "19 PRICE_TIER from compute_badges on bars through T0 (SWEET <=25, MID <=100, HEAVY >100).",
        "20 T0 with fewer than 30 bars of history in the data (short-listed symbols) is classified UNCLASSIFIED.", "")
    add("SKIPPED SYMBOLS (<60 bars in window): " + (", ".join(skipped) if skipped else "none"),
        f"Turso usage: {db_stats[0]} SELECT/PRAGMA statements, {db_stats[1]} non-read statements refused, rows written: 0")
    report = "\n".join(W) + "\n"

    od = Path(a.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    with open(od / "ignition_patterns.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=CSV_COLS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rallies)
    (od / "ignition_patterns_report.txt").write_text(report)

    print(report)
    print(f"Saved: {od / 'ignition_patterns.csv'} ({len(rallies)} rows)")
    print(f"Saved: {od / 'ignition_patterns_report.txt'}")
    print(f"[turso usage] end of run: {db_stats[0]} SELECT/PRAGMA, refused non-reads: {db_stats[1]}, rows written: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
