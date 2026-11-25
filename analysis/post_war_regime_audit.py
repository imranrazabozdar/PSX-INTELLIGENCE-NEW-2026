#!/usr/bin/env python3
"""post_war_regime_audit.py -- READ-ONLY post-war setup comparison (entries 2025-06-01..2026-01-31).

Reuses, does not reimplement:
  analysis/watchlist_breakout_audit.py  open_db, breakouts, simulate (Rule 2), fill_exit, upper_lock, CRASH
  fire_engine/phase_d_badges.py         compute_badges -> SETUP_GRADE (A+ PRIME / STANDARD / WATCH_ONLY)
  analysis/bulkowski_psx_audit.py       scan() -> HIGH_TIGHT_FLAG_PSX_50_99, PIPE_BOTTOM_1D,
                                        BROADENING_BOTTOM, CUP_WITH_HANDLE (logic unchanged)
  analysis/stopping_volume_audit.py     scan_symbol() -> signal + S1/S2 bracket simulator (logic unchanged)
  analysis/phase_d_ytd_audit.py         GuardDB (SELECT/PRAGMA only), load_universe

New in this file: only the Phase D Hybrid Profit-Lock exit (hybrid()).

Window     : ENTRY DATE in 2025-06-01..2026-01-31. Trades run to their natural exit (no truncation);
             only trades still open at the data end (2026-11-24) are marked to last close (OPEN).
Liquidity  : median(Close*Volume) over the 20 sessions ending T0-1 >= PKR 5M.
Unfillable : entry session is an upper-circuit lock (O==H==L at upper lock of T0 close), or the
             Rule 2 simulator's UNFILLABLE_UPPER_LOCK flag. Dropped and counted separately.
Friction   : net = gross - 0.45 percentage points, once per fillable trade (blended for Hybrid).

  python analysis/post_war_regime_audit.py [--local-db PATH] [--out-dir DIR] [--symbols A,B]
"""
import argparse
import csv
import os
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend"), str(ROOT / "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)
import watchlist_breakout_audit as A  # noqa: E402
import phase_d_ytd_audit as Y  # noqa: E402
import bulkowski_psx_audit as BK  # noqa: E402
import stopping_volume_audit as SV  # noqa: E402
from fire_engine import phase_d_detector as D  # noqa: E402
from fire_engine import phase_d_badges as BD  # noqa: E402

TABLE = "daily_ohlc"
SRC_START, END = "2021-09-01", "2026-11-24"
WIN_LO, WIN_HI = "2025-06-01", "2026-01-31"
FRICTION = 0.45
LIQ_PKR = 5_000_000
BE_PCT = 5.0
HYB_ARM = 0.10     # close >= entry*1.10 -> breakeven floor
HYB_TRIM = 0.15    # high >= entry*1.15 -> sell 50%
BK_PATTERNS = ["HIGH_TIGHT_FLAG_PSX_50_99", "PIPE_BOTTOM_1D", "BROADENING_BOTTOM", "CUP_WITH_HANDLE"]
GRADES = [BD.GRADE_PRIME, BD.GRADE_STANDARD, BD.GRADE_WATCH]
OUT_CSV = "post_war_trades.csv"
OUT_RPT = "post_war_report.txt"


def in_win(d):
    return WIN_LO <= d <= WIN_HI


def liquid(B, t):
    if t < 20:
        return False
    return statistics.median(B[q]["close"] * B[q]["volume"] for q in range(t - 20, t)) >= LIQ_PKR


def locked_entry(B, t, e, sim):
    return SV.is_upper_lock(B[e], B[t]["close"]) or "UNFILLABLE_UPPER_LOCK" in sim["flags"]


def hybrid(B, t, e20, e10):
    """Phase D Hybrid Profit-Lock. Initial stop before gains (close <= EMA20, as Rule 2). Once a close
    reaches entry*1.10 the stop is breakeven (close < entry) for the full position. When a bar's high
    reaches entry*1.15 (not an upper-locked bar) 50% is sold at entry*1.15. The remaining 50% then exits on
    close < EMA10 or close < entry (breakeven floor). Crash stop low <= entry*0.75 applies to whatever is held."""
    n, e = len(B), t + 1
    E = B[e]["open"]
    crash = E * (1 - A.CRASH)
    trimmed = armed = False
    exit_i = exit_px = reason = None
    for j in range(e, n):
        b, pc = B[j], B[j - 1]["close"]
        if b["low"] <= crash:
            exit_i, exit_px, reason = j, min(b["open"], crash), "CRASH_STOP_-25%"
            break
        if not trimmed and b["high"] >= E * (1 + HYB_TRIM) and not SV.is_upper_lock(b, pc):
            trimmed = True
        c = b["close"]
        if c >= E * (1 + HYB_ARM):
            armed = True
        if trimmed:
            hit = "10EMA_TRAIL" if c < e10[j] else ("BREAKEVEN" if c < E else None)
        elif armed:
            hit = "BREAKEVEN" if c < E else None
        else:
            hit = "20EMA_STOP" if c <= e20[j] else None
        if hit:
            k = A.fill_exit(B, j + 1)
            if k < n:
                exit_i, exit_px, reason = k, B[k]["open"], hit + ("_LLOCK_DEFERRED" if k > j + 1 else "")
            else:
                exit_i, exit_px, reason = n - 1, B[-1]["close"], f"OPEN({hit})"
            break
    if exit_i is None:
        exit_i, exit_px, reason = n - 1, B[-1]["close"], "OPEN"
    rem = (exit_px / E - 1) * 100.0
    gross = 0.5 * HYB_TRIM * 100.0 + 0.5 * rem if trimmed else rem
    mfe = (max(B[x]["high"] for x in range(e, exit_i + 1)) / E - 1) * 100.0
    return {"exit_i": exit_i, "exit_date": B[exit_i]["date"], "exit_price": exit_px, "gross": gross,
            "mfe": mfe, "reason": reason + ("+TRIM50" if trimmed else ""), "trimmed": trimmed}


def rec(strategy, sym, B, t, e, exit_i, exit_date, exit_px, gross, mfe, risk, grade, reason):
    E = B[e]["open"]
    net = gross - FRICTION
    return {"strategy": strategy, "symbol": sym, "setup_grade": grade, "signal_date": B[t]["date"],
            "entry_date": B[e]["date"], "entry_price": round(E, 4), "exit_date": exit_date,
            "exit_price": round(exit_px, 4), "exit_reason": reason,
            "status": "OPEN" if reason.startswith("OPEN") else "CLOSED",
            "gross_pct": round(gross, 4), "net_pct": round(net, 4), "peak_gain_pct": round(mfe, 4),
            "risk_pct": None if risk is None else round(risk, 4),
            "r_mult": round(net / risk, 4) if risk is not None and risk > 0 else None}


def phase_d(sym, B, out, dropped):
    if len(B) < A.R["min_bars"]:
        return
    closes = [b["close"] for b in B]
    e20, e10 = D._ema(closes, 20), D._ema(closes, 10)
    busy_r2 = busy_h = -1
    n = len(B)
    for t, sig in A.breakouts(B):
        e = t + 1
        if e >= n or B[e]["open"] <= 0 or not liquid(B, t):
            continue
        E = B[e]["open"]
        sim = A.simulate(B, t, e20, e10)
        if sim is None:
            continue
        w = in_win(B[e]["date"])
        if locked_entry(B, t, e, sim):
            if w:
                dropped["phase_d"] += 1
            continue
        risk = (E - e20[t]) / E * 100.0
        grade = None
        if t >= busy_r2:
            busy_r2 = sim["exit_i"] if not sim["reason"].startswith("OPEN") else n
            if w:
                grade = BD.compute_badges(B[max(0, t - BD.BARS + 1):t + 1], sig["ignition_date"],
                                          sig["date"])["setup_grade"]
                out.append(rec(f"Phase D {grade} (Rule 2)", sym, B, t, e, sim["exit_i"], sim["exit_date"],
                               sim["exit_price"], sim["ret"], sim["mfe"], risk, grade, sim["reason"]))
        if t >= busy_h:
            h = hybrid(B, t, e20, e10)
            busy_h = h["exit_i"] if not h["reason"].startswith("OPEN") else n
            if w:
                if grade is None:
                    grade = BD.compute_badges(B[max(0, t - BD.BARS + 1):t + 1], sig["ignition_date"],
                                              sig["date"])["setup_grade"]
                out.append(rec(f"Phase D {grade} (Hybrid)", sym, B, t, e, h["exit_i"], h["exit_date"],
                               h["exit_price"], h["gross"], h["mfe"], risk, grade, h["reason"]))


def bulkowski(sym, B, out, dropped):
    if len(B) < BK.MIN_BARS:
        return
    closes = [b["close"] for b in B]
    e20, e10 = D._ema(closes, 20), D._ema(closes, 10)
    n = len(B)
    for s in BK.scan(B):
        if s["pattern"] not in BK_PATTERNS:
            continue
        t = s["t"]
        e = t + 1
        if e >= n or B[e]["open"] <= 0 or not liquid(B, t):
            continue
        sim = A.simulate(B, t, e20, e10)
        if sim is None:
            continue
        w = in_win(B[e]["date"])
        if locked_entry(B, t, e, sim):
            if w:
                dropped["bulkowski"] += 1
            continue
        if w:
            E = B[e]["open"]
            out.append(rec(f"{s['pattern']} (Rule 2)", sym, B, t, e, sim["exit_i"], sim["exit_date"],
                           sim["exit_price"], sim["ret"], sim["mfe"], (E - e20[t]) / E * 100.0, "",
                           sim["reason"]))


def stopping(sym, B, out, dropped):
    rows, lock_n = SV.scan_symbol(sym, B)
    dropped["stopping_full_history"] += lock_n
    idx = {b["date"]: i for i, b in enumerate(B)}
    n = len(B)
    for r in rows:
        if not in_win(r["entry_date"]):
            continue
        e = idx[r["entry_date"]]
        E = r["entry_price"]
        for s, label in (("S1", "STOPPING_VOLUME S1 (+6%/ATR/10d)"), ("S2", "STOPPING_VOLUME S2 (+8%/ATR/15d)")):
            risk = r[f"{s}_risk_pct"]
            if r[f"{s}_cens"]:
                exit_i, px = n - 1, B[-1]["close"]
                gross, reason = (px / E - 1) * 100.0, "OPEN(CENSORED)"
            else:
                exit_i = e + r[f"{s}_days"] - 1
                gross = r[f"{s}_gross"]
                px, reason = E * (1 + gross / 100.0), r[f"{s}_reason"]
            mfe = (max(B[x]["high"] for x in range(e, exit_i + 1)) / E - 1) * 100.0
            out.append(rec(label, sym, B, e - 1, e, exit_i, B[exit_i]["date"], px, gross, mfe, risk, "",
                           reason))


# ---------------------------------------------------------------- stats + output
def stats(rs):
    n = len(rs)
    if n == 0:
        return {"n": 0, "be": None, "win": None, "expR": None, "peak": None, "med": None}
    Rs = [r["r_mult"] for r in rs if r["r_mult"] is not None]
    return {"n": n,
            "be": 100.0 * sum(r["peak_gain_pct"] >= BE_PCT for r in rs) / n,
            "win": 100.0 * sum(r["net_pct"] > 0 for r in rs) / n,
            "expR": statistics.mean(Rs) if Rs else None,
            "peak": statistics.median(r["peak_gain_pct"] for r in rs),
            "med": statistics.median(r["net_pct"] for r in rs)}


def f(x, nd=2, suffix=""):
    return "-" if x is None else f"{x:.{nd}f}{suffix}"


def text_table(headers, rows):
    cols = list(zip(*([headers] + rows)))
    w = [max(len(str(c)) for c in col) for col in cols]
    lines = ["  ".join(str(h).ljust(w[i]) for i, h in enumerate(headers)),
             "  ".join("-" * w[i] for i in range(len(headers)))]
    for r in rows:
        lines.append("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    ap.add_argument("--symbols", default=None, help="optional comma list overriding the universe (testing)")
    a = ap.parse_args(argv)
    if not a.local_db and not (os.getenv("LIBSQL_URL") or os.getenv("TURSO_DATABASE_URL")):
        sys.exit("No data source: pass --local-db PATH or set LIBSQL_URL")
    raw, _src = A.open_db(SimpleNamespace(local_db=a.local_db, host=None))  # address not printed
    db = Y.GuardDB(raw)
    print("[turso usage] read-only audit: SELECT/PRAGMA only; rows written: 0 "
          "(GuardDB refuses all other statements)")
    if TABLE not in A.table_names(db):
        sys.exit(f"{TABLE} not found in data source")
    universe = ([s.strip().upper() for s in a.symbols.split(",") if s.strip()] if a.symbols
                else Y.load_universe())
    universe = list(dict.fromkeys(universe))

    out, dropped, skipped = [], {"phase_d": 0, "bulkowski": 0, "stopping_full_history": 0}, []
    for sym in universe:
        rows = db.query(f"SELECT trade_date, open, high, low, close, volume FROM {TABLE} "
                        "WHERE symbol = ? AND trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
                        (sym, SRC_START, END))
        B = D.as_bars(rows)
        if len(B) < SV.MIN_BARS:
            skipped.append(f"{sym}({len(B)})")
            continue
        phase_d(sym, B, out, dropped)
        bulkowski(sym, B, out, dropped)
        stopping(sym, B, out, dropped)

    out.sort(key=lambda r: (r["entry_date"], r["symbol"], r["strategy"]))
    od = Path(a.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    cols = list(out[0].keys()) if out else ["strategy"]
    with open(od / OUT_CSV, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        wr.writerows(out)

    by = lambda name: [r for r in out if r["strategy"] == name]  # noqa: E731
    pd_rule2 = {g: [r for r in out if r["strategy"] == f"Phase D {g} (Rule 2)"] for g in GRADES}
    pd_hyb = {g: [r for r in out if r["strategy"] == f"Phase D {g} (Hybrid)"] for g in GRADES}
    bk_names = [f"{p} (Rule 2)" for p in BK_PATTERNS]
    sv_names = ["STOPPING_VOLUME S1 (+6%/ATR/10d)", "STOPPING_VOLUME S2 (+8%/ATR/15d)"]
    leaderboard = []
    for g in GRADES:
        leaderboard.append((f"Phase D {g} (Rule 2)", pd_rule2[g]))
    for g in GRADES:
        leaderboard.append((f"Phase D {g} (Hybrid)", pd_hyb[g]))
    for nm in bk_names:
        leaderboard.append((nm, by(nm)))
    for nm in sv_names:
        leaderboard.append((nm, by(nm)))

    L = []
    L.append("POST-WAR SETUP COMPARISON (read-only)")
    L.append("[turso usage] read-only audit: SELECT/PRAGMA only; rows written: 0")
    L.append(f"Universe: {len(universe)} symbols | skipped (<{SV.MIN_BARS} bars): "
             + (", ".join(skipped) if skipped else "none"))
    L.append(f"Entry window: {WIN_LO}..{WIN_HI} (by entry date) | data {SRC_START}..{END}")
    L.append(f"Trades in window: {len(out)} rows (all strategies) | OPEN at data end: "
             f"{sum(1 for r in out if r['status'] == 'OPEN')}")
    L.append(f"Dropped as unfillable entry-lock (in window): Phase D {dropped['phase_d']} | "
             f"Bulkowski {dropped['bulkowski']} | Stopping-volume: {dropped['stopping_full_history']} "
             "(full history, not window-filtered)")
    L.append("")
    L.append("Table 1 - Strategy Leaderboard (fillable liquid trades in window, net of 0.45%)")
    t1 = []
    for name, rs in leaderboard:
        s = stats(rs)
        t1.append([name, s["n"], f(s["be"], 1, "%"), f(s["win"], 1, "%"), f(s["expR"], 3),
                   f(s["peak"], 2, "%"), f(s["med"], 2, "%")])
    L += text_table(["Strategy / Setup", "Fillable Liquid Trades (n)", "Break-Even Hit % (>=+5%)",
                     "Net Win %", "Net Expectancy (R)", "Median Peak Gain %", "Median Net Return %"], t1)
    L.append("")
    L.append("Table 2 - Phase D exit comparison (Standard Rule 2 vs Hybrid Profit-Lock)")
    t2 = []
    for g in GRADES:
        sr, sh = stats(pd_rule2[g]), stats(pd_hyb[g])
        t2.append([g, sr["n"], f(sr["win"], 1, "%"), f(sr["expR"], 3), f(sr["med"], 2, "%"),
                   sh["n"], f(sh["win"], 1, "%"), f(sh["expR"], 3), f(sh["med"], 2, "%")])
    L += text_table(["Grade", "Rule2 n", "Rule2 Net Win %", "Rule2 Exp R", "Rule2 Med Net %",
                     "Hybrid n", "Hybrid Net Win %", "Hybrid Exp R", "Hybrid Med Net %"], t2)
    L.append("")
    L.append("Table 3 - Top 15 winning trades in window (net return > 0, all strategies, desc)")
    wins = sorted((r for r in out if r["net_pct"] > 0), key=lambda r: r["net_pct"], reverse=True)[:15]
    t3 = [[r["symbol"], r["strategy"], r["entry_date"], f(r["entry_price"]), f(r["peak_gain_pct"]),
           r["exit_date"], f(r["net_pct"])] for r in wins]
    L += text_table(["Symbol", "Strategy", "Entry Date", "Entry Price", "Peak Gain %", "Exit Date",
                     "Net Return %"], t3)
    L.append("")
    L.append("Assumptions")
    L.append("- Window: ENTRY date 2025-06-01..2026-01-31 inclusive; entry = next session open after T0.")
    L.append("- Trades run to natural exit (no truncation at 2026-01-31). Trades still open at 2026-11-24 are "
             "marked to last close and flagged OPEN.")
    L.append("- Liquidity: median(Close*Volume) over 20 sessions ending T0-1 >= PKR 5M (LIQUID).")
    L.append("- Unfillable: entry session O==H==L at upper lock of T0 close, or Rule 2 UNFILLABLE_UPPER_LOCK flag. "
             "Dropped and counted separately; never in statistics.")
    L.append("- Friction: net = gross - 0.45 pp once per fillable trade (blended for Hybrid).")
    L.append("- Rule 2: A.simulate (initial close<=EMA20; once close>=entry*1.10 stop = close<EMA10; crash "
             "low<=entry*0.75; lower-lock deferral via A.fill_exit).")
    L.append("- Hybrid Profit-Lock (Phase D only): initial stop as Rule 2 until a close >= entry*1.10; then breakeven "
             "(close<entry) for the full position. When a bar high >= entry*1.15 (not upper-locked) 50% is sold at "
             "entry*1.15; remaining 50% exits on close<EMA10 or close<entry (breakeven floor), next Open. "
             "If no trim, the full position follows the stop. Blended return = 50%*15% + 50%*remaining leg.")
    L.append("- Phase D overlap: one open position per symbol per method (Rule 2 and Hybrid tracked separately); "
             "only taken (liquid, fillable) signals block. Grade from compute_badges on bars through T0 (<=400 bars).")
    L.append("- Phase D risk % = (entry - EMA20 at T0)/entry*100; R omitted when risk <= 0.")
    L.append("- Bulkowski: scan() unchanged; patterns HIGH_TIGHT_FLAG_PSX_50_99, PIPE_BOTTOM_1D, BROADENING_BOTTOM, "
             "CUP_WITH_HANDLE; Rule 2 exits; risk % = (entry - EMA20 at T0)/entry*100. No per-symbol overlap rule "
             "(as in the Bulkowski audit). CUP_WITH_HANDLE is its own label in scan() output.")
    L.append("- Stopping volume: SV.scan_symbol unchanged (signal, 10-session cooldown, ATR stop with 0.96E floor, "
             "S1 +6%/10d, S2 +8%/15d, 0.45% friction). Entry-lock drops are full-history counts. "
             "R = net/(E-S)/E.")
    L.append(f"- PSX lock rules: circuit band max(10% prev close, Rs 1.00); TICK {A.TICK}.")
    L.append(f"- Universe: fire_config.yaml stocks.universe, {len(universe)} symbols, no exclusions.")
    L.append("")
    report = "\n".join(L) + "\n"
    (od / OUT_RPT).write_text(report)
    print(report)
    print(f"Saved: {od / OUT_CSV} ({len(out)} rows)")
    print(f"Saved: {od / OUT_RPT}")
    print(f"[turso usage] end of run: {db.reads} SELECT/PRAGMA, refused non-reads: {db.writes_refused}, "
          "rows written: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
