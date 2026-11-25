#!/usr/bin/env python3
"""chart_patterns_sanity.py -- READ-ONLY sanity run of pattern_scanner.bulkowski_detector on daily_ohlc.

Reads daily_ohlc (2021-09-01 onward) for the 207-symbol universe via GuardDB (SELECT/PRAGMA only),
runs the detector, and writes <out-dir>/chart_patterns_sanity.txt with:
  latest trade_date, per-pattern/state counts, CUP raw (loose) vs tightened counts,
  Universe_Breadth_Pct on the latest date, and the latest 15 CONFIRMED and FORMING signals.

CONFIRMED counts are events over history (one per pattern instance). FORMING counts are live
setups on the latest bar only.

  python analysis/chart_patterns_sanity.py [--local-db PATH] [--out-dir DIR]
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend"), str(ROOT / "analysis")):
    if p not in sys.path:
        sys.path.insert(0, p)
import watchlist_breakout_audit as A  # noqa: E402
import phase_d_ytd_audit as Y  # noqa: E402
from pattern_scanner.bulkowski_detector import scan_universe, CONFIRMED, FORMING  # noqa: E402

TABLE = "daily_ohlc"
SRC_START = "2021-09-01"
PATTERNS = ["CUP_WITH_HANDLE", "HIGH_TIGHT_FLAG_PSX", "PIPE_BOTTOM_1D", "BROADENING_BOTTOM"]


def loose_cup_bases(df):
    """ORIGINAL loose cup test only: right lip = close swing high (N=3), left lip = highest close in
    the first part of a 35..130 bar base, lips within 10%, depth 10%..50%. No handle, OBV, volume
    or liquidity conditions. Returns the set of right-lip indices that pass."""
    c = df["close"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    n = len(c)
    out = set()
    for r in range(34, n - 3):
        if c[r] != c[r - 3:r + 4].max():
            continue
        lo, hi = max(0, r - 129), r - 34
        lb = lo + int(np.argmax(c[lo:hi + 1]))
        Lp, Rp = c[lb], c[r]
        if abs(Rp - Lp) / Lp > 0.10:
            continue
        ref = min(Lp, Rp)
        depth = (ref - l[lb:r + 1].min()) / ref
        if 0.10 <= depth <= 0.50:
            out.add(r)
    return out


def _fmt(v, nd=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return str(v)


def _table(rows, cols):
    if not rows:
        return ["  (none)"]
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    lines = ["  " + "  ".join(c.ljust(widths[c]) for c in cols)]
    lines.append("  " + "  ".join("-" * widths[c] for c in cols))
    for r in rows:
        lines.append("  " + "  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    a = ap.parse_args(argv)
    if not a.local_db and not (os.getenv("LIBSQL_URL") or os.getenv("TURSO_DATABASE_URL")):
        sys.exit("No data source: pass --local-db PATH or set LIBSQL_URL")
    a.host = None
    raw, _src = A.open_db(a)                  # source address deliberately not printed
    db = Y.GuardDB(raw)                       # refuses every statement except SELECT / PRAGMA
    print("[turso usage] read-only sanity run: SELECT/PRAGMA only, rows written: 0 "
          "(GuardDB refuses all other statements)")
    if TABLE not in A.table_names(db):
        sys.exit(f"{TABLE} not found in data source")

    latest = db.query(f"SELECT MAX(trade_date) AS d FROM {TABLE}")[0]["d"]
    universe = Y.load_universe()
    frames, missing = {}, []
    for sym in universe:
        rows = db.query(f"SELECT trade_date AS date, open, high, low, close, volume FROM {TABLE} "
                        "WHERE symbol = ? AND trade_date >= ? ORDER BY trade_date", (sym, SRC_START))
        if not rows:
            missing.append(sym)
            continue
        frames[sym] = pd.DataFrame([dict(r) for r in rows])

    signals, breadth = scan_universe(frames)

    loose_total = 0
    for df in frames.values():
        loose_total += len(loose_cup_bases(df.sort_values("date").reset_index(drop=True)))

    L = []
    L.append("[turso usage] read-only sanity run: SELECT/PRAGMA only; reads issued: "
             f"{db.reads}; writes refused: {db.writes_refused}; rows written: 0")
    L.append(f"Chart-pattern sanity report (daily_ohlc from {SRC_START})")
    L.append(f"Latest trade_date in daily_ohlc: {latest}")
    L.append(f"Universe: {len(universe)} symbols; with data: {len(frames)}; no rows: {len(missing)}")
    L.append(f"Universe_Breadth_Pct on latest date (Close > SMA50): {_fmt(breadth)}%")
    L.append("")
    L.append("Signals per pattern and state (CONFIRMED = events over history; FORMING = latest bar):")
    counts = {(p, s): 0 for p in PATTERNS for s in (CONFIRMED, FORMING)}
    for s in signals:
        counts[(s["pattern"], s["state"])] += 1
    L.append(f"  {'pattern'.ljust(22)}{'CONFIRMED'.rjust(11)}{'FORMING'.rjust(10)}")
    for p in PATTERNS:
        L.append(f"  {p.ljust(22)}{str(counts[(p, CONFIRMED)]).rjust(11)}{str(counts[(p, FORMING)]).rjust(10)}")
    L.append("")
    cup_tight = counts[("CUP_WITH_HANDLE", CONFIRMED)] + counts[("CUP_WITH_HANDLE", FORMING)]
    L.append("CUP_WITH_HANDLE raw vs tightened:")
    L.append(f"  raw loose bases (depth 10-50%, lips within 10%; right-lip dates, no handle/OBV/volume/"
             f"liquidity): {loose_total}")
    L.append(f"  tightened signals (CONFIRMED events + FORMING latest): {cup_tight}")
    L.append("")
    L.append("Latest 15 CONFIRMED signals:")
    conf = sorted((s for s in signals if s["state"] == CONFIRMED),
                  key=lambda s: (s["signal_date"], s["symbol"]), reverse=True)[:15]
    fm = sorted((s for s in signals if s["state"] == FORMING), key=lambda s: s["symbol"])[:15]
    cols = ["symbol", "pattern", "state", "signal_date", "rvol", "median20_pkr", "clear_runway_pct",
            "runway_flag", "suggested_stop", "stop_basis", "universe_breadth_pct"]

    def _rows(xs):
        return [{k: _fmt(v) if k not in ("symbol", "pattern", "state", "signal_date", "runway_flag",
                                         "stop_basis") else v for k, v in s.items() if k in cols}
                for s in xs]

    L += _table(_rows(conf), cols)
    L.append("")
    L.append("Latest FORMING signals (up to 15):")
    L += _table(_rows(fm), cols)
    L.append("")
    L.append(f"[turso usage] footer: rows written: 0 (writes refused by GuardDB: {db.writes_refused})")

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = "\n".join(L) + "\n"
    (out_dir / "chart_patterns_sanity.txt").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
