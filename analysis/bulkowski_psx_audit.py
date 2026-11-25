#!/usr/bin/env python3
"""bulkowski_psx_audit.py -- READ-ONLY Bulkowski chart-pattern audit on PSX daily_ohlc.

Patterns: HIGH_TIGHT_FLAG (PSX_50_99 / BULK_100), PIPE_BOTTOM (1D and 1W), BARR_BOTTOM,
DOUBLE_BOTTOM_EVE, CUP_WITH_HANDLE, BROADENING_BOTTOM, DESC_WEDGE_DIVERGING.
Every signal is a Close[t] crossing of the pattern level from below. Execution uses
the Rule 2 engine (A.simulate) entered at the next session's open.

Reuses, does not reimplement:
  analysis/watchlist_breakout_audit.py  open_db, table_names, simulate, TICK
  analysis/phase_d_ytd_audit.py         GuardDB (SELECT/PRAGMA only), load_universe
  fire_engine/phase_d_detector.py       _ema, as_bars
  fire_engine/phase_d_badges.py         price-tier constants (SWEET_SPOT / MID_CAP / HEAVY_CAP)

Universe : fire_engine/config/fire_config.yaml stocks.universe (no exclusions)
Window   : daily_ohlc 2021-09-01 .. 2026-11-24
Outputs  : <out-dir>/bulkowski_psx_trades.csv, <out-dir>/bulkowski_psx_report.txt

  python analysis/bulkowski_psx_audit.py [--local-db PATH] [--out-dir DIR]
"""
import argparse
import csv
import math
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

TABLE = "daily_ohlc"
SRC_START, END = "2021-09-01", "2026-11-24"
MIN_BARS = 120
PIV_N = 3                  # swing pivot half-window
COOLDOWN = 20              # bars, per symbol per pattern name
LIQ_PKR = 5_000_000        # median Close*Volume over 20 sessions ending t-1
TALL_THR = 1.0             # height / median height of the pattern's signals
FWD = 30                   # forward window for break-even failure and throwback
RECENT_FROM = "2025-01-01"
PATTERNS = ["HIGH_TIGHT_FLAG_PSX_50_99", "HIGH_TIGHT_FLAG_BULK_100", "PIPE_BOTTOM_1D", "PIPE_BOTTOM_1W",
            "BARR_BOTTOM", "DOUBLE_BOTTOM_EVE", "CUP_WITH_HANDLE", "BROADENING_BOTTOM", "DESC_WEDGE_DIVERGING"]
TIER_NAMES = {BD.TIER_SWEET: "SWEET_SPOT", BD.TIER_MID: "MID_CAP", BD.TIER_HEAVY: "HEAVY_CAP_CAUTION"}
CSV_COLS = ["symbol", "pattern", "tf", "breakout_date", "close_t", "height_pct", "tall_short", "partial_decline",
            "liquidity", "med20_value_pkr", "entry_date", "entry_price", "fillable", "sim_flags", "be_fail",
            "ultimate_high_pct", "throwback", "regime", "rule2_return_pct", "rule2_exit_reason", "risk_pct",
            "r_multiple", "price_tier"]


# ---------------------------------------------------------------- indicators (causal)
def atr14(B):
    """Wilder ATR14; value at index i uses bars <= i only."""
    n = len(B)
    out = [None] * n
    if n <= 14:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        h, lo, pc = B[i]["high"], B[i]["low"], B[i - 1]["close"]
        tr[i] = max(h - lo, abs(h - pc), abs(lo - pc))
    a = sum(tr[1:15]) / 14.0
    out[14] = a
    for i in range(15, n):
        a = (a * 13 + tr[i]) / 14.0
        out[i] = a
    return out


def pivots(B):
    """Swing pivots: bar p is a swing high (low) when its High (Low) is the strict extreme of p-N..p+N.
    Each pivot becomes usable only at its confirmation bar conf = p + N (no lookahead)."""
    out = []
    for p in range(PIV_N, len(B) - PIV_N):
        win = range(p - PIV_N, p + PIV_N + 1)
        hs = [B[q]["high"] for q in win]
        ls = [B[q]["low"] for q in win]
        if B[p]["high"] == max(hs) and hs.count(B[p]["high"]) == 1:
            out.append({"conf": p + PIV_N, "idx": p, "kind": "H", "price": B[p]["high"]})
        if B[p]["low"] == min(ls) and ls.count(B[p]["low"]) == 1:
            out.append({"conf": p + PIV_N, "idx": p, "kind": "L", "price": B[p]["low"]})
    return out


def lsq(xs, ys):
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    den = n * sxx - sx * sx
    if den == 0:
        return 0.0, sy / n
    k = (n * sxy - sx * sy) / den
    return k, (sy - k * sx) / n


def weekly(B):
    """W-FRI bars. Returns (weekly bars, daily index of each week's last session)."""
    W, last, cur, key, prev = [], [], None, None, -1
    for idx, b in enumerate(B):
        d = _date.fromisoformat(b["date"])
        k = d + timedelta(days=(4 - d.weekday()) % 7)
        if k != key:
            if cur is not None:
                W.append(cur)
                last.append(prev)
            cur = {"date": b["date"], "open": b["open"], "high": b["high"], "low": b["low"],
                   "close": b["close"], "volume": b["volume"]}
            key = k
        else:
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["volume"] += b["volume"]
            cur["date"] = b["date"]
        prev = idx
    if cur is not None:
        W.append(cur)
        last.append(prev)
    return W, last


# ---------------------------------------------------------------- pattern detectors
# Each returns a list of (pattern_name, height_in_price, partial_decline_flag) for breakouts at bar t.
def det_htf(B, ph, pl, t):
    """HIGH_TIGHT_FLAG: pole low->high gain >=50% within 42 bars; 5-15 bar flag with retracement <25%
    of the pole, closes in the pole's upper half; Close[t] crosses above the flag high."""
    best = None
    for jr in reversed(ph):
        j = jr["idx"]
        if j > t - 6:
            continue
        if j < t - 16:
            break
        hj = jr["price"]
        flag = range(j + 1, t)
        fh = max(B[q]["high"] for q in flag)
        if not (B[t]["close"] > fh and B[t - 1]["close"] <= fh):
            continue
        fl = min(B[q]["low"] for q in flag)
        for lr in reversed(pl):
            i = lr["idx"]
            if i >= j:
                continue
            if j - i > 42:
                break
            L = lr["price"]
            if L <= 0:
                continue
            gain = hj / L - 1.0
            if gain < 0.5:
                continue
            pole = hj - L
            if (hj - fl) >= 0.25 * pole:
                continue
            if min(B[q]["close"] for q in flag) < L + 0.5 * pole:
                continue
            name = "HIGH_TIGHT_FLAG_PSX_50_99" if gain < 1.0 else "HIGH_TIGHT_FLAG_BULK_100"
            if best is None or gain > best[2]:
                best = (name, pole, gain)
    return [(best[0], best[1], None)] if best else []


def det_pipe(B, ATRs, t):
    """PIPE_BOTTOM: adjacent bars (a, b=a+1) each with range >= 1.5 ATR14, b is a 20-bar low,
    lows within 1%. Breakout when Close[t] crosses max High of the pair. Returns height or None."""
    if t < 22:
        return None
    for b in range(max(t - 8, 20), t):
        a = b - 1
        if ATRs[a] is None or ATRs[b] is None:
            continue
        if (B[a]["high"] - B[a]["low"]) < 1.5 * ATRs[a] or (B[b]["high"] - B[b]["low"]) < 1.5 * ATRs[b]:
            continue
        if not all(B[b]["low"] <= B[q]["low"] for q in range(b - 19, b + 1)):
            continue
        la, lb = B[a]["low"], B[b]["low"]
        if lb <= 0 or abs(la - lb) / lb > 0.01:
            continue
        lvl = max(B[a]["high"], B[b]["high"])
        if B[t]["close"] > lvl and B[t - 1]["close"] <= lvl:
            return lvl - min(la, lb)
    return None


def leadin(B, ph, T, t):
    """Downtrend lead-in ending at trough T: start = highest swing high 20-60 bars before T.
    Angle = atan(normalized fitted drop over the lead-in); must be 30-45 degrees.
    Returns (angle, leadin_height, slope, intercept of lead-in swing-high trendline) or None."""
    s_rec = None
    for h in reversed(ph):
        i = h["idx"]
        if i > T - 20:
            continue
        if i < T - 60:
            break
        if s_rec is None or h["price"] > s_rec["price"]:
            s_rec = h
    if s_rec is None:
        return None
    s = s_rec["idx"]
    L = T - s
    base = B[s]["close"]
    if base <= 0:
        return None
    m, _ = lsq(list(range(L + 1)), [B[q]["close"] / base for q in range(s, T + 1)])
    angle = math.degrees(math.atan(-m * L))
    if not (30.0 <= angle <= 45.0):
        return None
    lh = max(B[q]["high"] for q in range(s, T + 1)) - B[T]["low"]
    if lh <= 0:
        return None
    pts = []
    for h in reversed(ph):
        if h["idx"] < s:
            break
        if h["idx"] <= T:
            pts.append((h["idx"], h["price"]))
    if len(pts) < 2:
        return None
    k, c = lsq([p[0] for p in pts], [p[1] for p in pts])
    return angle, lh, k, c


def det_barr(B, ph, pl, t):
    """BARR_BOTTOM: 20+ bar downtrend lead-in (30-45 deg), then a bump whose height >= 2x the
    lead-in height; breakout when Close[t] crosses the lead-in swing-high trendline projected to t."""
    for lr in reversed(pl):
        T = lr["idx"]
        if T < t - 60:
            break
        if T > t - 3:
            continue
        ls = leadin(B, ph, T, t)
        if ls is None:
            continue
        angle, lh, k, c = ls
        if t - 1 < T + 1:
            continue
        P = max(range(T + 1, t), key=lambda q: B[q]["high"])
        bump_h = B[P]["high"] - B[T]["low"]
        if bump_h < 2.0 * lh:
            continue
        if B[t]["close"] > k * t + c and B[t - 1]["close"] <= k * (t - 1) + c:
            return [("BARR_BOTTOM", bump_h, None)]
    return []


def det_dbe(B, pl, t):
    """DOUBLE_BOTTOM_EVE: two swing lows >=10 bars apart within 3%; middle swing high M between them;
    breakout when Close[t] crosses M."""
    for br in reversed(pl):
        b = br["idx"]
        if b < t - 60:
            break
        if b > t - 2:
            continue
        lb = br["price"]
        best = None
        for ar in reversed(pl):
            a = ar["idx"]
            if a > b - 10:
                continue
            if a < b - 80:
                break
            la = ar["price"]
            m = min(la, lb)
            if m <= 0 or abs(la - lb) / m > 0.03:
                continue
            M = max(B[q]["high"] for q in range(a + 1, b))
            if best is None or abs(la - lb) < best[0]:
                best = (abs(la - lb), M, m)
        if best and B[t]["close"] > best[1] and B[t - 1]["close"] <= best[1]:
            return [("DOUBLE_BOTTOM_EVE", best[1] - best[2], None)]
    return []


def det_cup(B, ph, pl, t):
    """CUP_WITH_HANDLE: left rim i, right rim j (|R2-R1|<=3%, j-i>=35), cup low c with >=15 bars on
    each side; handle of 5-15 bars whose low is in the cup's upper half; breakout above handle high."""
    for jr in reversed(ph):
        j = jr["idx"]
        if j > t - 6:
            continue
        if j < t - 16:
            break
        R2 = jr["price"]
        for ir in reversed(ph):
            i = ir["idx"]
            if i > j - 35:
                continue
            if i < j - 150:
                break
            R1 = ir["price"]
            if R1 <= 0 or abs(R2 - R1) / R1 > 0.03:
                continue
            c = min(range(i + 1, j), key=lambda q: B[q]["low"])
            if c - i < 15 or j - c < 15:
                continue
            C = B[c]["low"]
            R = max(R1, R2)
            depth = R - C
            if depth <= 0:
                continue
            hw = range(j + 1, t)
            hh = max(B[q]["high"] for q in hw)
            hl = min(B[q]["low"] for q in hw)
            if hl < C + 0.5 * depth:
                continue
            if B[t]["close"] > hh and B[t - 1]["close"] <= hh:
                return [("CUP_WITH_HANDLE", depth, None)]
    return []


def det_broad(B, ph, pl, t):
    """BROADENING_BOTTOM: last 3 swing highs rising and last 3 swing lows falling (range widening).
    DESC_WEDGE_DIVERGING: highs and lows both falling, lows falling faster (range diverging).
    Breakout when Close[t] crosses the last swing high. Partial decline: close fell >=10% from the
    formation peak before t."""
    H = [r for r in reversed(ph) if r["idx"] >= t - 80][:3]
    L = [r for r in reversed(pl) if r["idx"] >= t - 80][:3]
    if len(H) < 3 or len(L) < 3:
        return []
    H, L = list(reversed(H)), list(reversed(L))
    h1, h2, h3 = (r["price"] for r in H)
    l1, l2, l3 = (r["price"] for r in L)
    if not (B[t]["close"] > h3 and B[t - 1]["close"] <= h3):
        return []
    name = None
    if h1 < h2 < h3 and l1 > l2 > l3 and (h3 - l3) > (h1 - l1):
        name = "BROADENING_BOTTOM"
    elif h1 > h2 > h3 and l1 > l2 > l3 and (h3 - l3) > (h1 - l1) and (h3 - h1) > (l3 - l1):
        name = "DESC_WEDGE_DIVERGING"
    if name is None:
        return []
    pk = max(H, key=lambda r: r["price"])
    peak = pk["price"]
    partial = min(B[q]["close"] for q in range(pk["idx"], t)) <= 0.9 * peak
    return [(name, max(h1, h2, h3) - min(l1, l2, l3), partial)]


def daily_candidates(B, ATR, ph, pl, t):
    out = []
    out += det_htf(B, ph, pl, t)
    h = det_pipe(B, ATR, t)
    if h is not None:
        out.append(("PIPE_BOTTOM_1D", h, None))
    out += det_barr(B, ph, pl, t)
    out += det_dbe(B, pl, t)
    out += det_cup(B, ph, pl, t)
    out += det_broad(B, ph, pl, t)
    return out


# ---------------------------------------------------------------- scan + post-processing
def scan(B):
    """All raw breakouts for one symbol (causal). Returns list of dict(t, pattern, tf, height, partial)."""
    n = len(B)
    ATR = atr14(B)
    pivs = pivots(B)
    W, Wlast = weekly(B)
    WATR = atr14(W)
    wk = {}
    for w in range(22, len(W)):
        h = det_pipe(W, WATR, w)
        if h is not None:
            wk.setdefault(Wlast[w], []).append((w, h))
    sigs, cool, ph, pl, p = [], {}, [], [], 0
    for t in range(40, n):
        while p < len(pivs) and pivs[p]["conf"] <= t:
            (ph if pivs[p]["kind"] == "H" else pl).append(pivs[p])
            p += 1
        for name, height, partial in daily_candidates(B, ATR, ph, pl, t):
            last = cool.get(name)
            if last is None or t - last >= COOLDOWN:
                cool[name] = t
                sigs.append({"t": t, "pattern": name, "tf": "D", "height": height, "partial": partial})
        for w, h in wk.get(t, []):
            key = "PIPE_BOTTOM_1W"
            last = cool.get(key)
            if last is None or w - last >= COOLDOWN:
                cool[key] = w
                sigs.append({"t": t, "pattern": key, "tf": "W", "height": h, "partial": None})
    return sigs


def regime_map(series):
    acc = {}
    for B in series.values():
        cl = [b["close"] for b in B]
        s = 0.0
        for i in range(len(B)):
            s += cl[i]
            if i >= 50:
                s -= cl[i - 50]
            if i >= 49:
                sma = s / 50.0
                if sma > 0:
                    acc.setdefault(B[i]["date"], []).append(cl[i] / sma)
    return {d: ("BULL" if statistics.mean(v) > 1.0 else "BEAR") for d, v in acc.items() if v}


def f1(x):
    return "-" if x is None else f"{x:.1f}"


def agg(rows):
    n = len(rows)
    be = [r["be_fail"] for r in rows if r["be_fail"] is not None]
    ug = [r["ug"] for r in rows if r["ug"] is not None]
    tb = [r["throwback"] for r in rows if r["throwback"] is not None]
    rm = [r["r_mult"] for r in rows if r["r_mult"] is not None]
    return {
        "n": n,
        "be_fail": 100.0 * sum(be) / len(be) if be else None,
        "ug_med": statistics.median(ug) if ug else None,
        "win": 100.0 * sum(1 for r in rows if r["ret"] > 0) / n if n else None,
        "exp_r": statistics.mean(rm) if rm else None,
        "tb": 100.0 * sum(tb) / len(tb) if tb else None,
    }


def table(headers, rows, widths):
    line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    out = [line, "-" * len(line)]
    for r in rows:
        out.append(" | ".join(str(c).ljust(w) for c, w in zip(r, widths)))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    a = ap.parse_args(argv)
    if not a.local_db and not (os.getenv("LIBSQL_URL") or os.getenv("TURSO_DATABASE_URL")):
        sys.exit("No data source: pass --local-db PATH or set LIBSQL_URL")
    a.host = None
    raw, _src = A.open_db(a)              # source address deliberately not printed
    db = Y.GuardDB(raw)                   # refuses every statement except SELECT / PRAGMA
    print("[turso usage] read-only audit: SELECT/PRAGMA only, rows written: 0 "
          "(GuardDB refuses all other statements)")
    if TABLE not in A.table_names(db):
        sys.exit(f"{TABLE} not found in data source")
    universe = Y.load_universe()
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    series, skipped = {}, []
    for sym in universe:
        rows = db.query(f"SELECT trade_date, open, high, low, close, volume FROM {TABLE} "
                        "WHERE symbol = ? AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
                        (sym, SRC_START, END))
        B = D.as_bars(rows)
        if len(B) < MIN_BARS:
            skipped.append(f"{sym}({len(B)})")
            continue
        series[sym] = B
    print(f"Universe: {len(universe)} symbols | scanned: {len(series)} | skipped (<{MIN_BARS} bars): {len(skipped)}")

    raw_sigs = []
    for sym, B in series.items():
        for s in scan(B):
            s["sym"] = sym
            raw_sigs.append(s)
    print(f"Raw breakouts (all patterns, pre-liquidity): {len(raw_sigs)}")

    regime = regime_map(series)
    data = {sym: {"bars": B, "e20": D._ema([b["close"] for b in B], 20),
                  "e10": D._ema([b["close"] for b in B], 10)} for sym, B in series.items()}

    heights = {}
    for s in raw_sigs:
        B = data[s["sym"]]["bars"]
        heights.setdefault(s["pattern"], []).append(100.0 * s["height"] / B[s["t"]]["close"])
    med_h = {k: statistics.median(v) for k, v in heights.items()}

    rows = []
    no_entry = 0
    for s in raw_sigs:
        S = data[s["sym"]]
        B, t = S["bars"], s["t"]
        e = t + 1
        if e >= len(B) or B[e]["open"] <= 0:
            no_entry += 1
            continue
        E = B[e]["open"]
        sim = A.simulate(B, t, S["e20"], S["e10"])
        fillable = "UNFILLABLE_UPPER_LOCK" not in sim["flags"]
        if t >= 20:
            med = statistics.median(B[q]["close"] * B[q]["volume"] for q in range(t - 20, t))
        else:
            med = None
        liquid = med is not None and med >= LIQ_PKR
        hp = 100.0 * s["height"] / B[t]["close"]
        tall = hp / med_h[s["pattern"]] >= TALL_THR if med_h.get(s["pattern"]) else False
        fwd = B[e:e + FWD]
        be_fail = (max(b["high"] for b in fwd) < E * 1.05) if len(fwd) == FWD else None
        throwback = (1 if min(b["low"] for b in fwd) <= B[t]["close"] else 0) if len(fwd) == FWD else None
        run, ug_hi = -math.inf, E
        for j in range(e, len(B)):
            b = B[j]
            run = max(run, b["high"])
            if b["close"] <= 0.8 * run:
                break
            ug_hi = max(ug_hi, b["high"])
        ug = (ug_hi / E - 1.0) * 100.0
        risk = (E - S["e20"][t]) / E * 100.0
        r_mult = sim["ret"] / risk if risk > 0 else None
        rows.append({"sym": s["sym"], "pattern": s["pattern"], "tf": s["tf"], "date": B[t]["date"],
                     "close": B[t]["close"], "hp": hp, "tall": tall, "partial": s["partial"],
                     "liquid": liquid, "med": med, "entry_date": B[e]["date"], "E": E,
                     "fillable": fillable, "flags": sim["flags"], "be_fail": be_fail, "ug": ug,
                     "throwback": throwback, "regime": regime.get(B[t]["date"], "NA"),
                     "ret": sim["ret"], "reason": sim["reason"], "risk": risk, "r_mult": r_mult,
                     "tier": TIER_NAMES.get(BD.TIER_SWEET if B[t]["close"] <= 25 else
                                            BD.TIER_MID if B[t]["close"] <= 100 else BD.TIER_HEAVY)})
    print(f"Signals with next-session entry: {len(rows)} (no entry bar: {no_entry})")

    with open(out_dir / "bulkowski_psx_trades.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLS)
        for r in rows:
            w.writerow([r["sym"], r["pattern"], r["tf"], r["date"], f"{r['close']:.2f}", f"{r['hp']:.2f}",
                        "TALL" if r["tall"] else "SHORT", "" if r["partial"] is None else int(r["partial"]),
                        "LIQUID" if r["liquid"] else "ILLIQUID",
                        "" if r["med"] is None else f"{r['med']:.0f}", r["entry_date"], f"{r['E']:.2f}",
                        int(r["fillable"]), r["flags"],
                        "" if r["be_fail"] is None else int(r["be_fail"] is False),
                        f"{r['ug']:.2f}", "" if r["throwback"] is None else r["throwback"], r["regime"],
                        f"{r['ret']:.2f}", r["reason"], f"{r['risk']:.2f}",
                        "" if r["r_mult"] is None else f"{r['r_mult']:.3f}", r["tier"]])

    core = [r for r in rows if r["liquid"] and r["fillable"]]
    L = []
    L.append(f"[turso usage] read-only audit: SELECT/PRAGMA only; reads issued: {db.reads}; "
             f"non-read statements refused: {db.writes_refused}; rows written: 0")
    L.append(f"Universe {len(universe)} | scanned {len(series)} | skipped (<{MIN_BARS} bars): {len(skipped)}")
    L.append("Skipped: " + (", ".join(skipped) if skipped else "none"))
    L.append(f"Breakouts with entry: {len(rows)} | LIQUID: {sum(r['liquid'] for r in rows)} | "
             f"LIQUID & fillable: {len(core)} | market regime proxy: equal-weighted Close/SMA50 average")
    L.append("")
    L.append("Table 1 - PSX Pattern Leaderboard (metrics on LIQUID & fillable)")
    t1 = []
    for pat in PATTERNS:
        allp = [r for r in rows if r["pattern"] == pat]
        liq = [r for r in allp if r["liquid"]]
        g = agg([r for r in core if r["pattern"] == pat])
        t1.append([pat, len(allp), len(liq), g["n"], f1(g["be_fail"]), f1(g["ug_med"]), f1(g["win"]),
                   f"{g['exp_r']:.2f}" if g["exp_r"] is not None else "-", f1(g["tb"])])
    t1.append(["ALL (pre-liquidity filter total)", len(rows), sum(r["liquid"] for r in rows), len(core),
               "", "", "", "", ""])
    L.append(table(["Pattern", "All Signals (pre-liq)", "Total Signals (LIQUID)", "Fillable",
                    "Break-Even Fail % (<5%)", "Median Ultimate Gain %", "Rule-2 Win %",
                    "Rule-2 Expectancy (R)", "Throwback %"], t1, [32, 20, 22, 9, 22, 22, 14, 22, 12]))
    L.append("")
    L.append("Table 2 - Bulkowski rules on PSX (all patterns, LIQUID & fillable)")
    groups = [("Regime BULL", lambda r: r["regime"] == "BULL"), ("Regime BEAR", lambda r: r["regime"] == "BEAR"),
              ("TALL", lambda r: r["tall"]), ("SHORT", lambda r: not r["tall"]),
              ("Throwback", lambda r: r["throwback"] == 1), ("No-Throwback", lambda r: r["throwback"] == 0)]
    t2 = []
    for name, f in groups:
        g = agg([r for r in core if f(r)])
        t2.append([name, g["n"], f1(g["be_fail"]), f1(g["ug_med"]), f1(g["win"])])
    L.append(table(["Group", "Fillable N", "Break-Even Fail %", "Median Ultimate Gain %", "Rule-2 Win %"],
                   t2, [18, 12, 18, 24, 14]))
    L.append("")
    L.append(f"Table 3 - Top 15 recent PSX examples (breakout {RECENT_FROM} .. {END}, LIQUID & fillable, "
             "sorted by Ultimate High % desc)")
    recent = [r for r in core if RECENT_FROM <= r["date"] <= END]
    recent.sort(key=lambda r: -r["ug"])
    t3 = [[r["sym"], r["pattern"], r["date"], f"{r['E']:.2f}", f"{r['ug']:.1f}", f"{r['ret']:.1f}"]
          for r in recent[:15]]
    L.append(table(["Symbol", "Pattern", "Breakout Date", "Entry Price", "Ultimate High %", "Rule-2 Return %"],
                   t3, [10, 30, 14, 12, 16, 16]))
    L.append("")
    L.append("Assumptions")
    L += [
        "- Data: daily_ohlc 2021-09-01..2026-11-24, universe fire_config.yaml stocks.universe (207, no exclusions).",
        f"- Minimum history {MIN_BARS} bars in the loaded window; shorter symbols are listed as skipped.",
        "- Regime: KSE-100 index data is NOT in the database. Proxy = equal-weighted average of Close/SMA50 "
        "across scanned symbols on the breakout date; BULL if > 1.",
        f"- Swing pivots: N={PIV_N} each side, strict extreme, usable only at bar p+N (causal). ATR = Wilder ATR14 at pivot bar.",
        "- Breakouts: Close[t] crosses the level from below (Close[t-1] <= level < Close[t]). Intraday not used.",
        "- HIGH_TIGHT_FLAG: pole = pivot low to pivot high <=42 bars, gain >=50%; height = pole (H-L); "
        "PSX_50_99 for gain 50-99.99%, BULK_100 for >=100%; flag 5-15 bars, retracement <25% of pole, closes in upper half of pole.",
        "- PIPE_BOTTOM 1D on daily bars; 1W on W-FRI bars evaluated on each week's last session (zero lookahead, entry next session). "
        "Pair ranges >=1.5 ATR14, second bar = 20-bar low, lows within 1%; height = pair range.",
        "- BARR_BOTTOM: lead-in >=20 bars (start = highest swing high 20-60 bars before trough); "
        "angle = atan(-slope*L) of closes normalized by lead-in start, must be 30-45 deg; bump height >=2x lead-in height; "
        "breakout vs lead-in swing-high trendline projected to t.",
        "- DOUBLE_BOTTOM_EVE: troughs >=10 bars apart within 3%, middle swing high = max High between; 'rounded' troughs NOT tested beyond pivot definition.",
        "- CUP_WITH_HANDLE: rims within 3%, rim separation >=35 bars, cup low >=15 bars from each rim (U-shape approximation); handle 5-15 bars, handle low in cup upper half.",
        "- BROADENING_BOTTOM (rising highs, falling lows) and DESC_WEDGE_DIVERGING (falling highs and lows, lows faster) use last 3 swing highs/lows within 80 bars; "
        "breakout over last swing high. PARTIAL_DECLINE flag = min Close after formation peak <= 90% of peak.",
        f"- TALL/SHORT: height as % of breakout close / median height % of that pattern's signals (all, pre-liquidity); TALL if >= {TALL_THR}.",
        f"- Liquidity: median(Close*Volume) over the 20 sessions ending t-1 >= PKR {LIQ_PKR:,} = LIQUID.",
        "- Entry: next session open. Execution via watchlist_breakout_audit.simulate (Rule 2: 20-EMA initial stop, 10-EMA trail after +10% close, "
        "crash stop -25%, lower-lock deferral). Fillable = not flagged UNFILLABLE_UPPER_LOCK (O==H==L upper lock).",
        f"- Break-Even Failure: max High over next {FWD} bars (entry bar included) < entry*1.05 = failure. Signals without {FWD} forward bars are excluded from that metric.",
        "- Ultimate High Gain: max High from entry up to (excluding) the first close >=20% below the running high; % of entry. Censored at data end if no reversal.",
        f"- Throwback: Low <= breakout Close within {FWD} bars after breakout.",
        "- Rule-2 Return % from simulate; R risk = (entry - EMA20 at t)/entry*100; expectancy = mean(return%/risk%) over fillable LIQUID trades with risk>0.",
        "- Cooldown: 20 bars per symbol per pattern name (weekly pattern counted in weekly bars).",
        "- Locked-open handling: entries on upper-lock-open sessions flagged UNFILLABLE; exits deferred through lower-lock sessions (simulate).",
        "- Peak/median/mean statistics ignore missing values; 'Fillable' is the denominator for all table metrics.",
        "- Universe: no survivorship adjustment beyond the current universe list.",
    ]
    report = "\n".join(L) + "\n"
    (out_dir / "bulkowski_psx_report.txt").write_text(report)
    print(f"Wrote {out_dir / 'bulkowski_psx_trades.csv'} ({len(rows)} rows) and "
          f"{out_dir / 'bulkowski_psx_report.txt'}")
    print("[turso usage] footer: rows written: 0")


if __name__ == "__main__":
    main()
