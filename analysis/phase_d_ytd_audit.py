#!/usr/bin/env python3
"""phase_d_ytd_audit.py -- READ-ONLY 2026 year-to-date Phase D audit.

Reuses, does not reimplement:
  analysis/watchlist_breakout_audit.py  open_db, load_bars, breakouts, simulate (Rule 2 + PSX circuits)
  fire_engine/phase_d_detector.py       evaluate (SOS_IGNITION / ACTIVE_SHELF / SHELF_BREAKOUT)
  fire_engine/phase_d_badges.py         compute_badges (SETUP_GRADE, PRICE_TIER)

Universe : fire_engine/config/fire_config.yaml stocks.universe
Warm-up  : daily_ohlc from 2025-01-01; the audit window is 2026-01-01 .. 2026-11-24.

Definitions
  Trade      SHELF_BREAKOUT dated in 2026; entry = next session open (A.simulate).
             UNFILLABLE_UPPER_LOCK trades are kept in Section C but excluded from stats.
             A breakout on the last bar has no next session -> PENDING_ENTRY, excluded.
  Return     A.simulate ret % (exit or last close for OPEN trades).
  Win rate   % of fillable trades with return > 0.
  Profit factor  sum(positive return %) / |sum(negative return %)| over fillable trades.
  R risk %   (entry - EMA20 at the signal close) / entry * 100  (EMA20 over the 2025+ series).
  Expectancy R  mean(return % / R risk %) over fillable trades with R risk > 0.
  Status     OPEN          still open at 2026-11-24 (exit reason starts with OPEN)
             SUSTAINED     a close >= entry * 1.10 during the hold, or return > 0 at exit
             FAILED        exit reason 20EMA_STOP or CRASH_STOP with return <= 0
             CLOSED_OTHER  anything else (checked in that order)
  Day-12 expiry  an ACTIVE_SHELF signal at shelf age 12 with no SHELF_BREAKOUT for that
             ignition on or before the next session.
  SOS_IGNITION / ACTIVE_SHELF are counted from D.evaluate on each 2026 date's 90-bar window
  (evaluate returns one signal per date, so a date with a breakout counts only as a breakout).

Read-only: every query goes through GuardDB, which refuses any statement that is not
SELECT or PRAGMA. Data source: --local-db PATH (SQLite, opened mode=ro) or LIBSQL_URL.

  python analysis/phase_d_ytd_audit.py [--local-db PATH] [--out-dir DIR]
"""
import argparse
import csv
import os
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)
import watchlist_breakout_audit as A  # noqa: E402
from fire_engine import phase_d_detector as D  # noqa: E402
from fire_engine import phase_d_badges as BD  # noqa: E402

R = D.RULES
SRC_START, YEAR_START, END = "2025-01-01", "2026-01-01", "2026-11-24"
TABLE = "daily_ohlc"
GRADES = [BD.GRADE_PRIME, BD.GRADE_STANDARD, BD.GRADE_WATCH]
TIERS = [BD.TIER_SWEET, BD.TIER_MID, BD.TIER_HEAVY]
TRADE_COLS = ["symbol", "ignition_date", "breakout_date", "signal_close", "ema20_signal", "setup_grade",
              "price_tier", "shelf_days", "rvol", "entry_price", "entry_flags", "fillable", "risk_pct",
              "peak_gain_pct", "exit_date", "exit_price", "return_pct", "exit_reason", "status"]


class GuardDB:
    """Wraps the A.open_db connection; refuses anything that is not a read."""

    def __init__(self, db):
        self.db = db
        self.reads = 0
        self.writes_refused = 0

    def query(self, sql, params=()):
        head = sql.strip().split(None, 1)[0].upper() if sql.strip() else ""
        if head not in ("SELECT", "PRAGMA"):
            self.writes_refused += 1
            raise RuntimeError("non-read statement refused by read-only audit")
        self.reads += 1
        return self.db.query(sql, params)


def load_universe():
    cfg = yaml.safe_load((ROOT / "fire_engine" / "config" / "fire_config.yaml").read_text())
    return list(dict.fromkeys(s.strip().upper() for s in cfg["stocks"]["universe"]))


def fmt(v, nd=2):
    if v is None or v == "":
        return "-"
    if isinstance(v, float):
        if v == float("inf"):
            return "inf"
        return f"{v:.{nd}f}"
    return str(v)


def print_table(rows, cols):
    lines = []
    if not rows:
        return ["  (none)"]
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    lines.append("  " + "  ".join(c.ljust(w[c]) for c in cols))
    lines.append("  " + "  ".join("-" * w[c] for c in cols))
    for r in rows:
        lines.append("  " + "  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols))
    return lines


def perf(rows):
    rets = [r["return_pct"] for r in rows]
    n = len(rets)
    wins = [x for x in rets if x > 0]
    loss = [x for x in rets if x < 0]
    pf = (sum(wins) / abs(sum(loss))) if loss else (float("inf") if wins else None)
    rs = [r["return_pct"] / r["risk_pct"] for r in rows if r["risk_pct"] > 0]
    return {"n": n, "wr": 100.0 * len(wins) / n if n else None, "pf": pf,
            "exp": statistics.mean(rs) if rs else None, "exp_n": len(rs)}


def trade_row(sym, bars, t, sig, e20, e10):
    badges = BD.compute_badges(bars[max(0, t - 399):t + 1], sig["ignition_date"], sig["date"])
    row = {"symbol": sym, "ignition_date": sig["ignition_date"], "breakout_date": sig["date"],
           "signal_close": round(sig["close"], 2), "ema20_signal": round(e20[t], 4),
           "setup_grade": badges["setup_grade"], "price_tier": badges["price_tier"],
           "shelf_days": sig["shelf_days"], "rvol": round(sig["rvol"], 2) if sig["rvol"] else ""}
    sim = A.simulate(bars, t, e20, e10)
    if sim is None:
        row.update(entry_price="", entry_flags="NO_NEXT_SESSION", fillable=False, risk_pct="",
                   peak_gain_pct="", exit_date="", exit_price="", return_pct="", exit_reason="",
                   status="PENDING_ENTRY")
        return row
    entry = sim["next_open"]
    reached10 = any(bars[j]["close"] >= entry * 1.10 for j in range(t + 1, sim["exit_i"] + 1))
    reason = sim["reason"]
    if reason.startswith("OPEN"):
        status = "OPEN"
    elif reached10 or sim["ret"] > 0:
        status = "SUSTAINED"
    elif reason.startswith(("20EMA_STOP", "CRASH_STOP")):
        status = "FAILED"
    else:
        status = "CLOSED_OTHER"
    row.update(entry_price=round(entry, 2), entry_flags=sim["flags"],
               fillable="UNFILLABLE_UPPER_LOCK" not in sim["flags"],
               risk_pct=round((entry - e20[t]) / entry * 100, 4),
               peak_gain_pct=round(sim["mfe"], 2), exit_date=sim["exit_date"],
               exit_price=round(sim["exit_price"], 2), return_pct=round(sim["ret"], 2),
               exit_reason=reason, status=status)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    a = ap.parse_args(argv)
    if not a.local_db and not (os.getenv("LIBSQL_URL") or os.getenv("TURSO_DATABASE_URL")):
        sys.exit("No data source: pass --local-db PATH or set LIBSQL_URL")
    a.host = None
    raw, src = A.open_db(a)
    db = GuardDB(raw)
    have = A.table_names(db)
    if TABLE not in have:
        sys.exit(f"{TABLE} not found in data source")
    universe = load_universe()

    print("=" * 78)
    print(f"Data source : {src}")
    print(f"Universe    : {len(universe)} symbols (fire_config.yaml stocks.universe)")
    print(f"Window      : warm-up {SRC_START} | audit {YEAR_START} .. {END}")
    print("=" * 78)

    trades, skipped = [], []
    sos_count, active_obs, shelves = 0, 0, set()
    active_at12 = []          # (sym, ign, day_index, date)
    brk_idx = {}              # (sym, ignition_date) -> breakout indices (all dates)
    for sym in universe:
        bars = [b for b in A.load_bars(db, TABLE, sym) if SRC_START <= b["date"] <= END]
        if len(bars) < 60:
            skipped.append((sym, len(bars)))
            continue
        dates = [b["date"] for b in bars]
        closes = [b["close"] for b in bars]
        e20, e10 = D._ema(closes, 20), D._ema(closes, 10)

        for t, sig in A.breakouts(bars):
            brk_idx.setdefault((sym, sig["ignition_date"]), []).append(t)

        for t in range(len(bars)):
            if dates[t] < YEAR_START:
                continue
            sig = D.evaluate(bars[max(0, t - R["bars"] + 1):t + 1])
            if not sig:
                continue
            st = sig["signal_type"]
            if st == "SOS_IGNITION":
                sos_count += 1
            elif st == "ACTIVE_SHELF":
                active_obs += 1
                shelves.add((sym, sig["ignition_date"]))
                if sig["shelf_days"] == R["shelf_max_age"] and t + 1 < len(bars):
                    active_at12.append((sym, sig["ignition_date"], t))

        for t, sig in A.breakouts(bars):
            if dates[t] >= YEAR_START:
                trades.append(trade_row(sym, bars, t, sig, e20, e10))

    # Day-12 expiry: age-12 active shelf with no breakout for that ignition through the next session
    expiries = 0
    for sym, ign, t in active_at12:
        bi = brk_idx.get((sym, ign), [])
        if any(x <= t + 1 for x in bi):
            continue
        expiries += 1

    trades.sort(key=lambda r: (r["breakout_date"], r["symbol"]))
    fill = [r for r in trades if r["fillable"]]
    pend = [r for r in trades if r["status"] == "PENDING_ENTRY"]
    unf = [r for r in trades if not r["fillable"] and r["status"] != "PENDING_ENTRY"]
    p = perf(fill)

    out = []
    if skipped:
        out.append(f"Skipped (<60 bars from {SRC_START}): " + ", ".join(f"{s}({n})" for s, n in skipped))
    else:
        out.append("Skipped (<60 bars): none")
    out.append(f"Symbols audited: {len(universe) - len(skipped)} of {len(universe)}")
    out.append("")
    out.append("SECTION A -- 2026 YTD SUMMARY (phase D, fillable trades only for stats)")
    out.append(f"  SOS_IGNITION events               : {sos_count}")
    out.append(f"  ACTIVE_SHELF distinct shelves     : {len(shelves)}   (ACTIVE_SHELF day-signals: {active_obs})")
    out.append(f"  SHELF_BREAKOUT                    : {len(trades)}   (fillable {len(fill)}, "
               f"upper-lock unfillable {len(unf)}, pending entry {len(pend)})")
    out.append(f"  Day-12 expiries                   : {expiries}")
    out.append(f"  Win rate                          : {fmt(p['wr'])}%")
    out.append(f"  Profit factor                     : {fmt(p['pf'])}")
    out.append(f"  Expectancy R                      : {fmt(p['exp'], 3)}   (n={p['exp_n']}; R risk = (entry - EMA20 at signal close)/entry)")
    out.append("")
    out.append("SECTION B -- STRATIFIED BY SETUP_GRADE AND PRICE_TIER (fillable trades)")
    brows = []
    for dim, key, buckets in (("grade", "setup_grade", GRADES), ("tier", "price_tier", TIERS)):
        for bkt in buckets:
            rs = [r for r in fill if r[key] == bkt]
            rets = [r["return_pct"] for r in rs]
            gains = [x for x in rets if x > 0]
            losses = [x for x in rets if x < 0]
            pp = perf(rs)
            brows.append({"dim": dim, "bucket": bkt, "count": len(rs), "win_pct": fmt(pp["wr"]),
                          "avg_gain_pct": fmt(statistics.mean(gains)) if gains else "-",
                          "avg_loss_pct": fmt(statistics.mean(losses)) if losses else "-",
                          "SUSTAINED": sum(r["status"] == "SUSTAINED" for r in rs),
                          "FAILED": sum(r["status"] == "FAILED" for r in rs),
                          "OPEN": sum(r["status"] == "OPEN" for r in rs)})
    out += print_table(brows, ["dim", "bucket", "count", "win_pct", "avg_gain_pct", "avg_loss_pct",
                               "SUSTAINED", "FAILED", "OPEN"])
    out.append("")
    out.append("SECTION C -- EVERY 2026 SHELF_BREAKOUT (chronological)")
    crows = []
    for r in trades:
        note = [x for x in r["entry_flags"].split(";") if x]
        crows.append({"Symbol": r["symbol"], "Tier": r["price_tier"], "Grade": r["setup_grade"],
                      "Breakout Date": r["breakout_date"],
                      "Entry Price": fmt(r["entry_price"]) if r["entry_price"] != "" else "-",
                      "Peak Gain %": fmt(r["peak_gain_pct"]) if r["peak_gain_pct"] != "" else "-",
                      "Exit Date": "OPEN" if r["status"] == "OPEN" else (r["exit_date"] or "-"),
                      "Exit Price": fmt(r["exit_price"]) if r["exit_price"] != "" else "-",
                      "Return %": fmt(r["return_pct"]) if r["return_pct"] != "" else "-",
                      "Status": r["status"],
                      "Note": ", ".join(note + ([] if r["fillable"] or r["status"] == "PENDING_ENTRY"
                                                 else ["excluded from stats"])) or "-"})
    out += print_table(crows, ["Symbol", "Tier", "Grade", "Breakout Date", "Entry Price", "Peak Gain %",
                               "Exit Date", "Exit Price", "Return %", "Status", "Note"])
    report = "\n".join(out) + "\n"

    od = Path(a.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    with open(od / "phase_d_ytd_trades.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=TRADE_COLS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(trades)
    (od / "phase_d_ytd_report.txt").write_text(report)

    print(report)
    print(f"Saved: {od / 'phase_d_ytd_trades.csv'} ({len(trades)} rows)")
    print(f"Saved: {od / 'phase_d_ytd_report.txt'}")
    print(f"Read statements: {db.reads} | write statements refused: {db.writes_refused} | rows written: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
