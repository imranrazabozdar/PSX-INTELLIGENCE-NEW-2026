#!/usr/bin/env python3
"""stop_hunt_entry_audit.py -- READ-ONLY entry-method comparison (Baseline vs Method A vs Method B).

Signal list (T0 = signal session, C0 = Close[T0], day 1 = T0+1), all reused, none reimplemented:
  Bulkowski  analysis/bulkowski_psx_audit.scan(B), kept to HIGH_TIGHT_FLAG_PSX_50_99, PIPE_BOTTOM_1D,
             BROADENING_BOTTOM (scan() itself is unchanged).
  Phase D    analysis/watchlist_breakout_audit.breakouts(B) dated 2026-01-01..2026-11-24, kept when
             fire_engine/phase_d_badges.compute_badges(bars through T0) gives setup_grade in
             {A+ PRIME, STANDARD}. Label PHASE_D_A+_STD.
  Universe   fire_engine/config/fire_config.yaml stocks.universe (no exclusions).
  Data       daily_ohlc, 2021-09-01..2026-11-24, one SELECT per symbol. Symbols with < 120 bars are skipped.
  Liquidity  median(Close*Volume) over the 20 sessions ending T0-1 >= PKR 5,000,000.

Methods (same signal list):
  Baseline   enter Open[T0+1] (skip if T0+1 is upper-locked).
  Method A   limit bid L = 0.965*C0, valid T0+1..T0+5.
  Method B   sweep (Low <= 0.97*C0 with no close below EMA20 up to the sweep) and reclaim
             (first later Close > C0 within T0+15, entry at the following Open).

Exits (all methods): initial stop = first close < EMA20 (Method B: first close < sweep low);
trailing = once a close >= fill*1.10 the stop becomes first close < EMA10; crash = intraday Low <=
fill*0.75 exits at min(level, Open). Exit sells are deferred past lower-circuit locks via A.fill_exit.
Net = gross - 0.45 percentage points. Net R = net return % / risk %, risk % = (fill - EMA20[T0]) / fill * 100.

Usage:
  python analysis/stop_hunt_entry_audit.py [--local-db PATH] [--out-dir DIR] [--symbols A,B]
"""
import argparse
import csv
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend"), str(ROOT / "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)

import watchlist_breakout_audit as A  # noqa: E402
import phase_d_ytd_audit as Y  # noqa: E402
import bulkowski_psx_audit as BK  # noqa: E402
from fire_engine import phase_d_detector as D  # noqa: E402
from fire_engine import phase_d_badges as BD  # noqa: E402

TABLE = "daily_ohlc"
SRC_START, END = "2021-09-01", "2026-11-24"
PD_FROM, PD_TO = "2026-01-01", "2026-11-24"
MIN_BARS = 120
LIQ_PKR = 5_000_000
FRICTION = 0.45
TICK = A.TICK
CRASH = 0.25
TRAIL_ON = 0.10
BK_KEEP = ("HIGH_TIGHT_FLAG_PSX_50_99", "PIPE_BOTTOM_1D", "BROADENING_BOTTOM")
PD_LABEL = "PHASE_D_A+_STD"
PD_GRADES = (BD.GRADE_PRIME, BD.GRADE_STANDARD)
PATTERNS = ["HIGH_TIGHT_FLAG_PSX_50_99", "PIPE_BOTTOM_1D", "BROADENING_BOTTOM", PD_LABEL]
BASE, METH_A, METH_B = "Baseline", "Method A", "Method B"
METHODS = [BASE, METH_A, METH_B]
CSV_COLS = ["method", "pattern", "symbol", "t0_date", "c0", "filled", "note", "fill_date", "entry_price",
            "risk_pct", "exit_date", "exit_price", "exit_reason", "gross_return_pct", "net_return_pct",
            "net_r", "mfe_pct", "hold_sessions", "open_at_end"]


# ---------------------------------------------------------------- circuit helpers
def up_locked(b, prev_close):
    """Upper-circuit lock: O == H == L at the upper lock price. A buy cannot fill."""
    ul = A.upper_lock(prev_close)
    return abs(b["open"] - b["high"]) < TICK and abs(b["high"] - b["low"]) < TICK and b["low"] >= ul - TICK


def dn_locked(b, prev_close):
    """Lower-circuit lock (A.locked_down). A sell cannot fill."""
    return A.locked_down(b, prev_close)


# ---------------------------------------------------------------- exit simulation
def simulate_exit(bars, fi, entry, e20, e10, init_level):
    """Exit rules from fill session fi on. init_level None -> EMA20 stop; float -> close below that level."""
    n = len(bars)
    crash = entry * (1 - CRASH)
    trailing = False
    exit_i = exit_px = reason = None
    for j in range(fi, n):
        b = bars[j]
        prev = bars[j - 1]["close"]
        if b["low"] <= crash:
            if dn_locked(b, prev):
                k = A.fill_exit(bars, j)
                if k < n:
                    exit_i, exit_px, reason = k, bars[k]["open"], "CRASH_STOP_-25%_LLOCK_DEFERRED"
                else:
                    exit_i, exit_px, reason = n - 1, bars[-1]["close"], "OPEN(CRASH)"
            else:
                exit_i, exit_px, reason = j, min(b["open"], crash), "CRASH_STOP_-25%"
            break
        if trailing:
            hit, label = b["close"] < e10[j], "10EMA_TRAIL"
        elif init_level is None:
            hit, label = b["close"] < e20[j], "20EMA_STOP"
        else:
            hit, label = b["close"] < init_level, "SWEEP_LOW_STOP"
        if hit:
            k = A.fill_exit(bars, j + 1)
            if k < n:
                exit_i, exit_px = k, bars[k]["open"]
                reason = label + ("_LLOCK_DEFERRED" if k > j + 1 else "")
            else:
                exit_i, exit_px, reason = n - 1, bars[-1]["close"], f"OPEN({label})"
            break
        if b["close"] >= entry * (1 + TRAIL_ON):
            trailing = True
    if exit_i is None:
        exit_i, exit_px, reason = n - 1, bars[-1]["close"], "OPEN"
    seg = bars[fi:exit_i + 1]
    gross = (exit_px / entry - 1) * 100
    return {"exit_i": exit_i, "exit_date": bars[exit_i]["date"], "exit_px": exit_px, "reason": reason,
            "gross": gross, "net": gross - FRICTION,
            "mfe": (max(x["high"] for x in seg) / entry - 1) * 100,
            "hold": exit_i - fi, "open_at_end": reason.startswith("OPEN")}


def filled_result(bars, t, e20, e10, fi, entry, init_level):
    ex = simulate_exit(bars, fi, entry, e20, e10, init_level)
    risk = (entry - e20[t]) / entry * 100
    ex.update(filled=True, note="", fill_date=bars[fi]["date"], entry=entry, risk=risk,
              net_r=(ex["net"] / risk) if risk > 0 else None)
    return ex


def not_filled(note):
    return {"filled": False, "note": note}


# ---------------------------------------------------------------- entry methods
def run_baseline(bars, t, e20, e10):
    if t + 1 >= len(bars):
        return not_filled("NO_NEXT_SESSION")
    if up_locked(bars[t + 1], bars[t]["close"]):
        return not_filled("UPPER_LOCK_ENTRY_SKIP")
    return filled_result(bars, t, e20, e10, t + 1, bars[t + 1]["open"], None)


def run_method_a(bars, t, e20, e10):
    n = len(bars)
    c0 = bars[t]["close"]
    lim = 0.965 * c0
    if t + 1 >= n:
        return not_filled("NO_NEXT_SESSION")
    b1 = bars[t + 1]
    if b1["open"] < lim:
        # Pre-check: gap below the limit on T0+1 -> only trade if T0+1 closes back above 0.95*C0.
        if b1["close"] > 0.95 * c0 and not up_locked(b1, c0):
            return filled_result(bars, t, e20, e10, t + 1, b1["open"], None)
        return not_filled("PRECHECK_SKIP_GAP_BELOW_LIMIT")
    for j in range(t + 1, min(t + 6, n)):
        b = bars[j]
        if b["low"] <= lim and not up_locked(b, bars[j - 1]["close"]):
            return filled_result(bars, t, e20, e10, j, min(b["open"], lim), None)
    return not_filled("NO_FILL_IN_5_SESSIONS")


def run_method_b(bars, t, e20, e10):
    n = len(bars)
    c0 = bars[t]["close"]
    lvl = 0.97 * c0
    js = None
    for k in range(t + 1, min(t + 6, n)):
        if bars[k]["close"] < e20[k]:          # any close below EMA20 before the sweep disqualifies
            break
        if bars[k]["low"] <= lvl:
            js = k
            break
    if js is None:
        return not_filled("NO_QUALIFYING_SWEEP")
    sweep_low = min(bars[k]["low"] for k in range(t + 1, js + 1))
    m = None
    for k in range(js + 1, min(t + 15, n - 2) + 1):   # reclaim within T0+15; m+1 must exist
        if bars[k]["close"] > c0:
            m = k
            break
    if m is None:
        return not_filled("NO_RECLAIM_WITHIN_15_SESSIONS")
    e = m + 1
    if up_locked(bars[e], bars[m]["close"]):
        return not_filled("UPPER_LOCK_ENTRY_SKIP")
    return filled_result(bars, t, e20, e10, e, bars[e]["open"], sweep_low)


# ---------------------------------------------------------------- dip cohort (Table 3)
def dip_stats(bars, t, e20):
    n = len(bars)
    if t + 20 >= n:
        return None                             # incomplete forward window (needs T0+20)
    c0 = bars[t]["close"]
    lo = min(bars[k]["low"] for k in range(t + 1, t + 6))
    dip = (lo / c0 - 1) * 100
    if not (-4.0 - 1e-9 <= dip <= -3.0 + 1e-9):
        return {"dipper": False}
    d = next(k for k in range(t + 1, t + 6) if bars[k]["low"] == lo)
    recovered = any(bars[k]["close"] >= c0 for k in range(d, t + 11))
    reach10 = any(bars[k]["high"] >= 1.10 * c0 for k in range(t + 1, t + 21))
    k1 = next((k for k in range(t + 1, t + 11) if bars[k]["close"] < e20[k]), None)
    fell = k1 is not None and not any(bars[k]["close"] >= c0 for k in range(t + 1, k1))
    if reach10:
        cls = "REACHED_+10%"
    elif recovered:
        cls = "RECOVERED"
    elif fell:
        cls = "FELL_BELOW_EMA20"
    else:
        cls = "NEITHER"
    return {"dipper": True, "recovered": recovered, "reach10": reach10, "fell": fell, "cls": cls}


# ---------------------------------------------------------------- stats + formatting
def liquid(bars, t):
    if t < 20:
        return False
    med = statistics.median(bars[q]["close"] * bars[q]["volume"] for q in range(t - 20, t))
    return med >= LIQ_PKR


def max_dd(rows):
    eq = peak = 1.0
    mdd = 0.0
    for r in sorted(rows, key=lambda r: (r["fill_date"], r["symbol"], r["t0_date"], r["pattern"])):
        eq *= 1 + r["net"] / 100
        peak = max(peak, eq)
        mdd = min(mdd, (eq / peak - 1) * 100)
    return mdd


def stats(rows):
    """rows: filled results carrying net, net_r."""
    n = len(rows)
    nets = [r["net"] for r in rows]
    rs = [r["net_r"] for r in rows if r["net_r"] is not None]
    return {"n": n,
            "win": 100.0 * sum(x > 0 for x in nets) / n if n else None,
            "exp_r": statistics.mean(rs) if rs else None,
            "med": statistics.median(nets) if nets else None,
            "nonpos_risk": n - len(rs)}


def f(v, nd=2):
    return "-" if v is None else f"{v:.{nd}f}"


def table(headers, rows):
    w = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]
    lines = ["  ".join(str(h).ljust(w[i]) for i, h in enumerate(headers)),
             "  ".join("-" * w[i] for i in range(len(headers)))]
    lines += ["  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)) for r in rows]
    return lines


# ---------------------------------------------------------------- main
ASSUMPTIONS = [
    "Universe: fire_config.yaml stocks.universe, no exclusions; daily_ohlc 2021-09-01..2026-11-24; < 120 bars skipped.",
    "Signals: Bulkowski HIGH_TIGHT_FLAG_PSX_50_99 / PIPE_BOTTOM_1D / BROADENING_BOTTOM (all dates in window);",
    "         Phase D SHELF_BREAKOUT dated 2026-01-01..2026-11-24 with setup_grade A+ PRIME or STANDARD (bars through T0).",
    "         A symbol-date can appear under two patterns; each (pattern, signal) is an independent signal (no portfolio cap).",
    "Liquidity: median(Close*Volume) over 20 sessions ending T0-1 >= PKR 5,000,000; failing signals are removed from every table.",
    "Baseline: entry Open[T0+1]; skipped (not filled) if T0+1 is upper-locked.",
    "Method A pre-check: if Open[T0+1] < 0.965*C0 then fill at Open[T0+1] only when Close[T0+1] > 0.95*C0 (not upper-locked);",
    "         otherwise skipped and counted as not filled. Otherwise first session in T0+1..T0+5 with Low <= L (not upper-locked)",
    "         fills at min(Open, L). No fill in 5 sessions = not filled. Fill rate denominator = all liquid signals.",
    "Method B qualification: first session j in T0+1..T0+5 with Low <= 0.97*C0, where no close in T0+1..j is below EMA20.",
    "         sweep_low = min Low over T0+1..j. Entry: first m in (j, T0+15] with Close[m] > C0, fill at Open[m+1]",
    "         (m+1 must exist; skipped if m+1 is upper-locked). Stop after fill: first close < sweep_low; trailing as baseline.",
    "Exits (all methods): initial close < EMA20 (Method B: close < sweep_low); after any close >= fill*1.10 the stop is",
    "         close < EMA10; both checked from the fill session. Crash: Low <= fill*0.75 exits at min(0.75*fill, Open).",
    "         Sell exits on a lower-locked session are deferred with A.fill_exit to the first session with Low above the lower lock.",
    "         While an EMA-triggered exit is pending (lock deferral), the crash rule is not re-evaluated before that exit fills.",
    "         Open trades at data end are marked to the last close and flagged OPEN.",
    "Locks: upper lock = O==H==L at A.upper_lock(prev close) (no buy); lower lock = A.locked_down (no sell).",
    "Friction: net = gross - 0.45 percentage points on every filled trade.",
    "R: risk % = (fill - EMA20[T0]) / fill * 100; net R = net return % / risk %. Trades with risk <= 0 are excluded from E(R) (counted).",
    "Max Drawdown %: worst peak-to-trough of the compounded equity (start 1.0) from filled trades' net returns in entry-date order",
    "         (all patterns pooled, one method at a time, trades treated as sequential; overlapping trades are not capped).",
    "Table 3 dip: min Low over T0+1..T0+5 relative to C0 in [-4%, -3%] inclusive. Dip session d = first session of that minimum.",
    "         (a) recovered: a close >= C0 in d..T0+10. (b) reached +10%: a high >= 1.10*C0 in T0+1..T0+20.",
    "         (c) fell below EMA20: first close < EMA20 in T0+1..T0+10 occurs before any close >= C0 in that window.",
    "         Categories overlap; the mutually exclusive split uses priority +10% > recovered > fell below EMA20 > neither.",
    "         Dip stats need T0+20 to exist; signals without it are excluded from Table 3 only.",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    ap.add_argument("--symbols", default=None, help="comma list overriding the fire_config universe (testing)")
    a = ap.parse_args(argv)
    if not a.local_db and not (os.getenv("LIBSQL_URL") or os.getenv("TURSO_DATABASE_URL")):
        sys.exit("No data source: pass --local-db PATH or set LIBSQL_URL")
    a.host = None
    raw, src = A.open_db(a)               # source address deliberately not printed
    db = Y.GuardDB(raw)                   # refuses every statement except SELECT / PRAGMA
    have = A.table_names(db)
    if TABLE not in have:
        sys.exit(f"{TABLE} not found in data source")
    universe = ([s.strip().upper() for s in a.symbols.split(",") if s.strip()] if a.symbols
                else Y.load_universe())
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    def out(s=""):
        print(s)
        lines.append(s)

    out("[turso usage] read-only audit: SELECT/PRAGMA only (GuardDB). Rows written: 0 (no write statements issued).")
    out(f"Data source : {src}")
    out(f"Universe    : {len(universe)} symbols (fire_config.yaml stocks.universe)")
    out(f"Window      : {SRC_START} .. {END} (Phase D signals {PD_FROM} .. {PD_TO})")
    out("=" * 78)

    series, skipped = {}, []
    for sym in universe:
        rows = db.query(f"SELECT trade_date, open, high, low, close, volume FROM {TABLE} "
                        "WHERE symbol = ? AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
                        (sym, SRC_START, END))
        bars = D.as_bars(rows)
        if len(bars) < MIN_BARS:
            skipped.append((sym, len(bars)))
            continue
        series[sym] = bars
    out(f"Scanned: {len(series)} | skipped (<{MIN_BARS} bars): {len(skipped)}")

    signals, liq_fail, raw_count = [], 0, {p: 0 for p in PATTERNS}
    for sym, bars in series.items():
        closes = [b["close"] for b in bars]
        e20, e10 = D._ema(closes, 20), D._ema(closes, 10)
        cands = [(s["t"], s["pattern"]) for s in BK.scan(bars) if s["pattern"] in BK_KEEP]
        for t, sig in A.breakouts(bars):
            if not (PD_FROM <= sig["date"] <= PD_TO):
                continue
            badges = BD.compute_badges(bars[max(0, t - 399):t + 1], sig["ignition_date"], sig["date"])
            if badges["setup_grade"] in PD_GRADES:
                cands.append((t, PD_LABEL))
        for t, pat in cands:
            raw_count[pat] += 1
            if not liquid(bars, t):
                liq_fail += 1
                continue
            signals.append({"symbol": sym, "pattern": pat, "t": t, "t0_date": bars[t]["date"],
                            "c0": bars[t]["close"], "bars": bars, "e20": e20, "e10": e10})
    out(f"Raw signals (pre-liquidity): {sum(raw_count.values())} | liquidity-failed: {liq_fail} | "
        f"liquid signals: {len(signals)}")

    methods = {BASE: run_baseline, METH_A: run_method_a, METH_B: run_method_b}
    trades = []
    for s in signals:
        s["res"] = {}
        for mname, fn in methods.items():
            r = fn(s["bars"], s["t"], s["e20"], s["e10"])
            s["res"][mname] = r
            base = {"method": mname, "pattern": s["pattern"], "symbol": s["symbol"], "t0_date": s["t0_date"],
                    "c0": round(s["c0"], 2), "filled": r["filled"]}
            if r["filled"]:
                r.update(symbol=s["symbol"], t0_date=s["t0_date"], pattern=s["pattern"])
                trades.append(dict(base, note="", fill_date=r["fill_date"], entry_price=round(r["entry"], 2),
                                   risk_pct=round(r["risk"], 3), exit_date=r["exit_date"],
                                   exit_price=round(r["exit_px"], 2), exit_reason=r["reason"],
                                   gross_return_pct=round(r["gross"], 3), net_return_pct=round(r["net"], 3),
                                   net_r="" if r["net_r"] is None else round(r["net_r"], 3),
                                   mfe_pct=round(r["mfe"], 3), hold_sessions=r["hold"],
                                   open_at_end=r["open_at_end"]))
            else:
                trades.append(dict(base, note=r["note"], fill_date="", entry_price="", risk_pct="",
                                   exit_date="", exit_price="", exit_reason="", gross_return_pct="",
                                   net_return_pct="", net_r="", mfe_pct="", hold_sessions="", open_at_end=""))

    out("")
    out("Table 1 — Entry Method Comparison")
    t1 = []
    for m in METHODS:
        filled = [s["res"][m] for s in signals if s["res"][m]["filled"]]
        st = stats(filled)
        n_sig = len(signals)
        t1.append([m, n_sig, st["n"], f"{100 * st['n'] / n_sig:.1f}" if n_sig else "-", f(st["win"], 1),
                   f(st["exp_r"], 3), f(st["med"], 2), f(max_dd(filled), 2)])
    out("  " + "\n  ".join(table(["Method", "Total Signals", "Filled (n)", "Fill Rate %", "Net Win %",
                                   "Net Expectancy (R)", "Median Net Return %", "Max Drawdown %"], t1)))
    out("  Method A = limit bid -3.5% (0.965*C0); Method B = sweep & reclaim.")

    out("")
    out("Table 2 — by pattern (Filled n | Net Win % | Net Expectancy (R))")
    t2 = []
    for p in PATTERNS:
        row = [p]
        for m in METHODS:
            st = stats([s["res"][m] for s in signals if s["pattern"] == p and s["res"][m]["filled"]])
            row += [st["n"], f(st["win"], 1), f(st["exp_r"], 3)]
        t2.append(row)
    out("  " + "\n  ".join(table(["Pattern", "Base n", "Base Win%", "Base E(R)", "A n", "A Win%", "A E(R)",
                                   "B n", "B Win%", "B E(R)"], t2)))

    out("")
    out("Table 3 — dip outcomes (all liquid signals, dipper = min Low T0+1..T0+5 in [-4%, -3%] vs C0)")
    ds = []
    for s in signals:
        st = dip_stats(s["bars"], s["t"], s["e20"])
        if st is not None:
            s["dip"] = st
            ds.append(st)
    excluded = len(signals) - len(ds)
    dippers = [d for d in ds if d["dipper"]]
    nd = len(dippers)
    pct = lambda k: f"{100.0 * k / nd:.1f}%" if nd else "-"  # noqa: E731
    dip_share = f"{100.0 * nd / len(ds):.1f}%" if ds else "-"
    out(f"  Signals with complete forward window: {len(ds)} (excluded for missing T0+20: {excluded}); "
        f"dippers: {nd} ({dip_share} of them)")
    out("  Overlapping categories (share of dippers):")
    out(f"    (a) recovered (close >= C0 in d..T0+10): {sum(d['recovered'] for d in dippers)} = {pct(sum(d['recovered'] for d in dippers))}")
    out(f"    (b) reached +10% (high >= 1.10*C0 in T0+1..T0+20): {sum(d['reach10'] for d in dippers)} = {pct(sum(d['reach10'] for d in dippers))}")
    out(f"    (c) fell below EMA20 (T0+1..T0+10, before any recovery): {sum(d['fell'] for d in dippers)} = {pct(sum(d['fell'] for d in dippers))}")
    out("  Mutually exclusive split (priority: +10% > recovered > fell below EMA20 > neither):")
    for c in ["REACHED_+10%", "RECOVERED", "FELL_BELOW_EMA20", "NEITHER"]:
        k = sum(d["cls"] == c for d in dippers)
        out(f"    {c:<18} {k:>5}  {pct(k)}")

    out("")
    out("Assumptions:")
    for line in ASSUMPTIONS:
        out("  " + line)
    out("")
    out(f"Skipped symbols (< {MIN_BARS} bars): " + (", ".join(f"{s}({n})" for s, n in skipped) or "none"))
    out(f"[turso usage] reads: {db.reads} | write count: 0 | non-read statements refused: {db.writes_refused}")

    out_dir.joinpath("stop_hunt_report.txt").write_text("\n".join(lines) + "\n")
    with open(out_dir / "stop_hunt_trades.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["method", "pattern", "symbol", "t0_date", "c0", "filled", "note"]
                            + CSV_COLS[7:], extrasaction="ignore")
        wr.writeheader()
        wr.writerows(trades)
    print(f"saved {len(trades)} method rows -> {out_dir / 'stop_hunt_trades.csv'}")
    print(f"saved report -> {out_dir / 'stop_hunt_report.txt'}")


if __name__ == "__main__":
    main()
