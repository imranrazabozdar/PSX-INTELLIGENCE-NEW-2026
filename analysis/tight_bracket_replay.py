#!/usr/bin/env python3
"""tight_bracket_replay.py -- READ-ONLY bracket replay of PSX breakouts on daily_ohlc.

Trade list (not hand-typed):
  (a) Bulkowski chart-pattern breakouts from analysis/bulkowski_psx_audit.py  -> BK.scan(B)
  (b) 2026 Phase D SHELF_BREAKOUT entries from analysis/watchlist_breakout_audit.py -> A.breakouts(B)
      (breakout dated 2026-01-01 .. 2026-11-24, tagged PHASE_D_2026)
Each trade is replayed independently under three brackets (A, B, C), net of 0.45% round-trip friction.

Universe : fire_engine/config/fire_config.yaml stocks.universe (no exclusions)
Window   : daily_ohlc 2021-09-01 .. 2026-11-24 (SELECT only)
Liquidity: median(Close*Volume) over the 20 sessions ending t-1 >= PKR 5,000,000
Entry    : next session open; UNFILLABLE upper-lock entry sessions (O==H==L at upper lock) dropped
Outputs  : <out-dir>/tight_bracket_trades.csv, <out-dir>/tight_bracket_report.txt

  python analysis/tight_bracket_replay.py [--local-db PATH] [--out-dir DIR]
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

TABLE = "daily_ohlc"
SRC_START, END = "2021-09-01", "2026-11-24"
PHASE_D_FROM = "2026-01-01"
PHASE_D = "PHASE_D_2026"
MIN_BARS = 120
LIQ_PKR = 5_000_000
FRICTION = 0.45                      # round-trip, % of entry
TICK = A.TICK
# bracket -> (target %, stop %, max hold in sessions; day 1 = entry session)
BRACKETS = {"A": (6.0, 3.0, 10), "B": (7.0, 3.5, 12), "C": (8.0, 4.0, 15)}
T1_BRACKET = "B"
T2_PATTERNS = ["HIGH_TIGHT_FLAG_PSX_50_99", "PIPE_BOTTOM_1D", "BROADENING_BOTTOM", PHASE_D]
COLS_CSV = ["symbol", "pattern", "signal_date", "entry_date", "entry_open", "med20_value_pkr", "regime"]


# ---------------------------------------------------------------- circuit helpers
def at_lock(b, lock, upper):
    """O==H==L session sitting at the upper (or lower) circuit lock."""
    if abs(b["open"] - b["high"]) >= TICK or abs(b["high"] - b["low"]) >= TICK:
        return False
    return b["open"] >= lock - TICK if upper else b["open"] <= lock + TICK


# ---------------------------------------------------------------- bracket replay
def simulate_bracket(B, e, tgt, stp, hold):
    """Replay one trade. e = entry index (next session open), day 1 = session e.
    Returns outcome/days/gross/net/net_r/exit_date, or None if the entry bar does not exist."""
    n = len(B)
    if e >= n:
        return None
    E = B[e]["open"]
    T = E * (1 + tgt / 100.0)
    S = E * (1 - stp / 100.0)
    last = min(n - 1, e + hold - 1)
    exit_i = exit_px = outcome = None
    censored = False
    for j in range(e, last + 1):
        b = B[j]
        prev = B[j - 1]["close"]
        o, h, lo = b["open"], b["high"], b["low"]
        if o > T:                                   # gap-through upside: fill at the open
            exit_i, exit_px, outcome = j, o, "TARGET"
            break
        up_locked = at_lock(b, A.upper_lock(prev), upper=True)
        tgt_hit = (not up_locked) and h >= T        # limit cannot fill on an upper-locked session
        stp_hit = lo <= S
        if stp_hit:                                 # same bar: STOP first (gap-up case handled above)
            outcome = "STOP"
            if o < S:
                if at_lock(b, A.lower_lock(prev), upper=False):
                    k = A.fill_exit(B, j + 1)       # defer past lower-circuit locked sessions
                    if k < n:
                        exit_i, exit_px = k, B[k]["open"]
                    else:
                        exit_i, exit_px, outcome, censored = n - 1, B[n - 1]["close"], "TIME", True
                else:
                    exit_i, exit_px = j, o
            else:
                exit_i, exit_px = j, S
            break
        if tgt_hit:
            exit_i, exit_px, outcome = j, T, "TARGET"
            break
    if exit_i is None:                              # neither touched by max hold (or data end)
        exit_i, exit_px, outcome = last, B[last]["close"], "TIME"
        censored = e + hold - 1 > n - 1
    gross = (exit_px / E - 1.0) * 100.0
    net = gross - FRICTION
    return {"outcome": outcome, "days": exit_i - e + 1, "gross": gross, "net": net,
            "net_r": net / stp, "exit_date": B[exit_i]["date"], "censored": censored}


# ---------------------------------------------------------------- trade construction
def build_rows(sym, B, cands, stats_skip):
    """cands: list of (t, pattern). Applies entry, liquidity and fillability filters, then replays brackets."""
    n = len(B)
    rows = []
    for t, pat in cands:
        e = t + 1
        if e >= n or B[e]["open"] <= 0:
            stats_skip["no_entry"] += 1
            continue
        if t < 20:
            stats_skip["illiquid"] += 1
            continue
        med = statistics.median(B[q]["close"] * B[q]["volume"] for q in range(t - 20, t))
        if med < LIQ_PKR:
            stats_skip["illiquid"] += 1
            continue
        if at_lock(B[e], A.upper_lock(B[t]["close"]), upper=True):
            stats_skip["unfillable_upper_lock"] += 1
            continue
        if t >= 49:
            sma = sum(B[q]["close"] for q in range(t - 49, t + 1)) / 50.0
            c = B[t]["close"]
            regime = "BULL" if c > sma else "BEAR" if c < sma else "NA"
        else:
            regime = "NA"
        row = {"symbol": sym, "pattern": pat, "signal_date": B[t]["date"], "entry_date": B[e]["date"],
               "entry_open": B[e]["open"], "med20_value_pkr": round(med), "regime": regime}
        for br, (tg, sp, hd) in BRACKETS.items():
            row[br] = simulate_bracket(B, e, tg, sp, hd)
        rows.append(row)
    stats_skip["kept"] += len(rows)
    return rows


# ---------------------------------------------------------------- stats + tables
def f1(x):
    return "-" if x is None else f"{x:.1f}"


def f2(x):
    return "-" if x is None else f"{x:.2f}"


def summarize(rows, br):
    n = len(rows)
    if not n:
        return None
    outs = [r[br]["outcome"] for r in rows]
    nets = [r[br]["net"] for r in rows]
    rs = [r[br]["net_r"] for r in rows]
    days = [r[br]["days"] for r in rows]
    return {"n": n,
            "tgt": 100.0 * outs.count("TARGET") / n,
            "stp": 100.0 * outs.count("STOP") / n,
            "tm": 100.0 * outs.count("TIME") / n,
            "win": 100.0 * sum(1 for x in nets if x > 0) / n,
            "exp": statistics.mean(rs),
            "avg": statistics.mean(nets),
            "med_days": statistics.median(days)}


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
    raw, _src = A.open_db(a)                 # source address deliberately not printed
    db = Y.GuardDB(raw)                     # refuses every statement except SELECT / PRAGMA
    if TABLE not in A.table_names(db):
        sys.exit(f"{TABLE} not found in data source")
    universe = Y.load_universe()
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    series, skipped = {}, []
    for sym in universe:
        bars = [b for b in A.load_bars(db, TABLE, sym) if SRC_START <= b["date"] <= END]
        if len(bars) < MIN_BARS:
            skipped.append(f"{sym}({len(bars)})")
            continue
        series[sym] = bars

    stats_skip = {"no_entry": 0, "illiquid": 0, "unfillable_upper_lock": 0, "kept": 0}
    all_rows = []
    for sym, B in series.items():
        bk_cands = [(s["t"], s["pattern"]) for s in BK.scan(B)]
        pd_cands = [(t, PHASE_D) for t, sig in A.breakouts(B)
                    if PHASE_D_FROM <= sig["date"] <= END]
        all_rows += build_rows(sym, B, bk_cands + pd_cands, stats_skip)
    all_rows.sort(key=lambda r: (r["signal_date"], r["symbol"], r["pattern"]))

    # per-trade CSV (one row per trade, all brackets)
    csv_cols = COLS_CSV + [f"{br}_{k}" for br in BRACKETS for k in
                           ("outcome", "days", "gross_pct", "net_pct", "net_r", "exit_date", "censored")]
    with open(out_dir / "tight_bracket_trades.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(csv_cols)
        for r in all_rows:
            base = [r[c] for c in COLS_CSV]
            ext = []
            for br in BRACKETS:
                x = r[br]
                ext += [x["outcome"], x["days"], f"{x['gross']:.3f}", f"{x['net']:.3f}", f"{x['net_r']:.4f}",
                        x["exit_date"], int(x["censored"])]
            w.writerow(base + ext)

    cens = {br: sum(1 for r in all_rows if r[br]["censored"]) for br in BRACKETS}
    L = []
    L.append(f"[turso usage] read-only replay: SELECT/PRAGMA only; reads issued: {db.reads}; "
             f"non-read statements refused: {db.writes_refused}; rows written: 0")
    L.append(f"Universe {len(universe)} | scanned {len(series)} | skipped (<{MIN_BARS} bars): {len(skipped)}")
    L.append("Skipped: " + (", ".join(skipped) if skipped else "none"))
    L.append(f"Candidate breakouts: Bulkowski (9 patterns) + Phase D SHELF_BREAKOUT {PHASE_D_FROM}..{END}")
    L.append(f"Dropped: no entry bar {stats_skip['no_entry']} | illiquid (<PKR 5M median) "
             f"{stats_skip['illiquid']} | unfillable upper-lock entry {stats_skip['unfillable_upper_lock']}")
    L.append(f"Liquid fillable trades replayed: {stats_skip['kept']} "
             f"(Phase D {sum(1 for r in all_rows if r['pattern'] == PHASE_D)}) | "
             f"right-censored at data end: A {cens['A']}, B {cens['B']}, C {cens['C']}")
    L.append("")
    L.append(f"Table 1 - Pattern performance under Bracket B (+7.0% / -3.5%, max hold 12, net of {FRICTION}%)")
    t1 = []
    for pat in list(BK.PATTERNS) + [PHASE_D, "TOTAL"]:
        rows = all_rows if pat == "TOTAL" else [r for r in all_rows if r["pattern"] == pat]
        s = summarize(rows, T1_BRACKET)
        if s is None:
            t1.append([pat, 0, "-", "-", "-", "-", "-", "-", "-"])
        else:
            t1.append([pat, s["n"], f1(s["tgt"]), f1(s["stp"]), f1(s["tm"]), f1(s["win"]),
                       f2(s["exp"]), f2(s["avg"]), f1(s["med_days"])])
    L.append(table(["Pattern", "Liquid Fillable Trades (n)", "Target Hit %", "Stop Hit %", "Time-Exit %",
                    "Net Win %", "Net Expectancy (R)", "Net Avg Return %", "Median Days to Exit"],
                   t1, [30, 24, 14, 12, 13, 11, 20, 18, 20]))
    L.append("")
    L.append("Table 2 - Bracket sensitivity by regime at breakout (Bull = Close > SMA50, Bear = Close < SMA50)")
    t2 = []
    for pat in T2_PATTERNS:
        for reg in ("BULL", "BEAR"):
            for br, (tg, sp, hd) in BRACKETS.items():
                rows = [r for r in all_rows if r["pattern"] == pat and r["regime"] == reg]
                s = summarize(rows, br)
                name = f"{br} (+{tg:.1f}%/-{sp:.1f}%)"
                if s is None:
                    t2.append([pat, reg.title(), name, 0, "-", "-", "-"])
                else:
                    t2.append([pat, reg.title(), name, s["n"], f1(s["win"]), f2(s["exp"]), f2(s["avg"])])
    L.append(table(["Pattern", "Regime", "Bracket", "n", "Net Win %", "Net Expectancy (R)", "Net Avg Return %"],
                   t2, [30, 8, 22, 6, 11, 20, 18]))
    L.append("")
    L.append("Assumptions")
    L += [
        "- Universe: fire_config.yaml stocks.universe (207 symbols, no exclusions). Data: daily_ohlc 2021-09-01..2026-11-24, SELECT only.",
        f"- Minimum {MIN_BARS} bars in window; shorter symbols listed as skipped.",
        "- Trade list: Bulkowski breakouts from bulkowski_psx_audit.scan (cooldown 20 bars per pattern name, unchanged); "
        f"Phase D SHELF_BREAKOUT from watchlist_breakout_audit.breakouts dated {PHASE_D_FROM}..{END}.",
        "- Overlapping trades in the same symbol are replayed independently (no one-position-per-symbol filter).",
        "- Entry = next session open E. Day 1 = entry session. Target T = E*(1+tgt), stop S = E*(1-stp).",
        "- Fills: gap rule first: if a session opens above T, exit at the open. (On day 1 this cannot occur, since E is day-1 open.)",
        "- Limit target: if High >= T exit at T, except on a session that is O==H==L at the upper lock (cannot fill; keep holding).",
        "- Stop: if Low <= S exit at S, or at the open if the session opened below S. Lower-lock O==H==L: stop deferred via watchlist_breakout_audit.fill_exit to the first later session with Low > lower lock, filled at that open.",
        "- Same bar touching both T and S (and not gapped above T): STOP first.",
        "- Time exit: no touch within max hold -> Close of day max_hold (A 10, B 12, C 15). Data-end censoring uses last available close (counted as TIME, see censored count).",
        f"- Friction: {FRICTION}% round-trip deducted from gross to give net %. Net R = net % / stop %.",
        "- Liquidity: median(Close*Volume) over the 20 sessions ending t-1 >= PKR 5,000,000.",
        "- Unfillable: entry session with O==H==L at the upper circuit lock (prior close + max(10%, Rs 1.00)) is dropped.",
        "- Regime: per-symbol Close vs own 50-session SMA at the breakout session (not the market proxy). NA regimes excluded from Table 2.",
        "- Win % = net return > 0. Expectancy = mean net R. Avg return = mean net %. Median days = median of exit session count (entry day = 1).",
        "- Full per-trade detail: tight_bracket_trades.csv in the same output directory.",
    ]
    report = "\n".join(L) + "\n"
    (out_dir / "tight_bracket_report.txt").write_text(report)
    print(report)
    print(f"Wrote {out_dir / 'tight_bracket_trades.csv'} ({len(all_rows)} trades) and "
          f"{out_dir / 'tight_bracket_report.txt'}")
    print("[turso usage] footer: rows written: 0")


if __name__ == "__main__":
    main()
