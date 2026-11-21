#!/usr/bin/env python3
"""run_phase_d_tracker.py — daily batch for the Phase D Breakout & Shelf
Tracker (fire_engine/phase_d_detector.py). Standalone: it never imports or
touches the Wyckoff 1.0 batch, its scheduler or wyckoff_accumulation.

  python fire_engine/run_phase_d_tracker.py [--date D] [--local-db PATH]
  python fire_engine/run_phase_d_tracker.py --replay PASL --from 2026-10-01 --to 2026-11-05

Batch: same universe + exclusion list as Wyckoff; last 90 daily bars per
symbol from daily_ohlc (served from the job's local snapshot when
PSX_DAILY_OHLC_SNAPSHOT is set -- 0 Turso reads -- else Turso); skips
symbols with < 30 bars or whose newest bar is not the session date (stale);
replaces that session's rows in phase_d_signals; writes the batch_runs
'phase_d_batch' completion record when >= 90% of symbols were current.

--replay: READ-ONLY. Evaluates one symbol for every trading date in a range
(each date on its own last-90-bars window, exactly as the batch would have)
and prints the signals. No table is created and nothing is written.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fire_engine import phase_d_detector as D  # noqa: E402

JOB = "phase_d_batch"
DDL = [
    """CREATE TABLE IF NOT EXISTS phase_d_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        scan_date DATE NOT NULL,
        signal_type TEXT NOT NULL,
        close DECIMAL(10,4),
        pct_change DECIMAL(8,3),
        rvol DECIMAL(8,3),
        turnover_pkr DECIMAL(18,2),
        base_or_shelf_high DECIMAL(10,4),
        shelf_days INTEGER,
        up_down_vol_ratio DECIMAL(8,3),
        ignition_date DATE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, scan_date)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_phase_d_scan_date ON phase_d_signals(scan_date)",
]
COLS = ("symbol", "scan_date", "signal_type", "close", "pct_change", "rvol", "turnover_pkr",
        "base_or_shelf_high", "shelf_days", "up_down_vol_ratio", "ignition_date")


def ensure_schema(conn):
    """Idempotent migration (CREATE ... IF NOT EXISTS), same convention as batch_guard's DDL."""
    for s in DDL:
        conn.execute(s)
    conn.commit()


def load_bars(conn, symbol, end_date, n=D.RULES["bars"]):
    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
        "WHERE symbol = ? AND trade_date <= ? ORDER BY trade_date DESC LIMIT ?", (symbol, end_date, n)).fetchall()
    rows = [dict(r) if not isinstance(r, (tuple, list)) else
            dict(zip(("trade_date", "open", "high", "low", "close", "volume"), r)) for r in rows]
    rows.reverse()
    return D.as_bars(rows)


def universe():
    from fire_engine.config import load_config
    from fire_engine.exclusions import filter_excluded_stocks, load_exclusions_from_config
    cfg = load_config()
    uni = cfg["stocks"]["universe"]
    if cfg["exclusion"]["enabled"]:
        uni = filter_excluded_stocks(uni, load_exclusions_from_config())
    return uni


def scan(conn, symbols, session, log=print):
    """Returns (signals, stale, short) for `session`. No writes."""
    sigs, stale, short = [], [], []
    for s in symbols:
        try:
            bars = load_bars(conn, s, session)
        except Exception as e:
            log(f"{s}: ERROR {e!r}")
            continue
        if len(bars) < D.RULES["min_bars"]:
            short.append(s)
            continue
        if bars[-1]["date"] != session:
            stale.append({"symbol": s, "last_bar": bars[-1]["date"]})
            continue
        r = D.evaluate(bars)
        if r:
            sigs.append(dict(r, symbol=s, scan_date=session))
    return sigs, stale, short


def _round(v, n):
    return None if v is None else round(float(v), n)


def store(conn, session, sigs):
    """Replace the session's rows (a re-run never leaves a row the current data no longer supports)."""
    stmts = [("DELETE FROM phase_d_signals WHERE scan_date = ?", (session,))]
    ins = (f"INSERT INTO phase_d_signals ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))}) "
           "ON CONFLICT(symbol, scan_date) DO UPDATE SET "
           + ", ".join(f"{c}=excluded.{c}" for c in COLS[2:]))
    for x in sigs:
        stmts.append((ins, (x["symbol"], x["scan_date"], x["signal_type"], _round(x["close"], 4),
                            _round(x["pct_change"], 3), _round(x["rvol"], 3), _round(x["turnover_pkr"], 2),
                            _round(x["base_or_shelf_high"], 4), x["shelf_days"],
                            _round(x["up_down_vol_ratio"], 3), x["ignition_date"])))
    if hasattr(conn, "batch_query"):
        conn.batch_query(stmts)
    else:
        for q, p in stmts:
            conn.execute(q, p)
    conn.commit()


def replay(conn, symbol, d_from, d_to):
    """READ-ONLY: one SELECT, then each date evaluated on its own last-90-bar window."""
    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT ?", (symbol, d_to, D.RULES["bars"] + 400)).fetchall()
    rows = [dict(r) if not isinstance(r, (tuple, list)) else
            dict(zip(("trade_date", "open", "high", "low", "close", "volume"), r)) for r in rows]
    rows.reverse()
    allbars = D.as_bars(rows)
    print(f"Replay {symbol} {d_from} → {d_to} (read-only, {len(allbars)} bars loaded)")
    print(f"{'date':10}  {'signal':15} {'close':>9} {'chg%':>7} {'rvol':>6} {'turnover PKR':>14} "
          f"{'base/shelf hi':>13} {'days':>4} {'up/dn':>6} ignition")
    out = []
    for k, b in enumerate(allbars):
        if not (d_from <= b["date"] <= d_to):
            continue
        window = allbars[max(0, k + 1 - D.RULES["bars"]):k + 1]
        r = D.evaluate(window) if len(window) >= D.RULES["min_bars"] else None
        f = lambda v, n=2: "—" if v is None else f"{v:.{n}f}"
        if r:
            out.append(r)
            print(f"{b['date']:10}  {r['signal_type']:15} {f(r['close']):>9} {f(r['pct_change']):>7} "
                  f"{f(r['rvol']):>6} {r['turnover_pkr']:>14,.0f} {f(r['base_or_shelf_high']):>13} "
                  f"{r['shelf_days']:>4} {f(r['up_down_vol_ratio']):>6} {r['ignition_date']}")
        else:
            print(f"{b['date']:10}  {'—':15} {f(b['close']):>9}")
    return out


def diagnose(conn, symbol, d_from, d_to):
    """READ-ONLY per-day breakdown of the ACTIVE_SHELF checks (markdown table).
    Uses the detector's own helpers on the same last-90-bar window per date."""
    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT ?", (symbol, d_to, D.RULES["bars"] + 400)).fetchall()
    rows = [dict(r) if not isinstance(r, (tuple, list)) else
            dict(zip(("trade_date", "open", "high", "low", "close", "volume"), r)) for r in rows]
    rows.reverse()
    allbars = D.as_bars(rows)
    r = D.RULES
    pf = lambda ok: "Pass" if ok else "Fail"
    print(f"### {symbol} ACTIVE_SHELF diagnostic {d_from} → {d_to} (read-only)\n")
    print("| Date | Close | Volume | EMA20 | Shelf Days | Floor Value | Above Floor & EMA20? | Shelf Range % | "
          "<= 28%? | Up/Down Vol Ratio | >= 1.8x? | Final Signal |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, b in enumerate(allbars):
        if not (d_from <= b["date"] <= d_to):
            continue
        w = allbars[max(0, k + 1 - r["bars"]):k + 1]
        t = len(w) - 1
        ema = D._ema([x["close"] for x in w], r["ema_span"])
        sig = (D.evaluate(w) or {}).get("signal_type", "—")
        ign = next((t - a for a in range(1, r["shelf_max_age"] + 1) if t - a >= 0 and D._sos_at(w, t - a, r)), None)
        if ign is None:
            print(f"| {b['date']} | {b['close']:.2f} | {b['volume']:,.0f} | {ema[t]:.3f} | — | — | — | — | — | — | — "
                  f"| {sig} |")
            continue
        age = t - ign
        g = w[ign]
        floor = g["low"] + 0.25 * (g["close"] - g["low"])
        bad = [w[j]["date"] for j in range(ign + 1, t + 1) if not (w[j]["close"] > floor and w[j]["close"] > ema[j])]
        shelf = w[ign + 1:t + 1]
        hi, lo = max(x["high"] for x in shelf), min(x["low"] for x in shelf)
        rng = (hi - lo) / lo * 100 if lo > 0 else None
        up = [w[j]["volume"] for j in range(ign + 1, t + 1) if w[j]["close"] > w[j - 1]["close"]]
        dn = [w[j]["volume"] for j in range(ign + 1, t + 1) if w[j]["close"] < w[j - 1]["close"]]
        ratio = (sum(up) / len(up) if up else 0.0) / (sum(dn) / len(dn)) if dn else None
        early = " (age < 3: too early)" if age < r["shelf_min_age"] else ""
        held = "Pass" if not bad else "Fail (" + ", ".join(bad) + ")"
        print(f"| {b['date']} | {b['close']:.2f} | {b['volume']:,.0f} | {ema[t]:.3f} | {age}{early} | {floor:.3f} | "
              f"{held} | {rng:.2f}% | {pf(rng is not None and rng <= r['shelf_max_range'] * 100)} | "
              f"{'no down days' if ratio is None else f'{ratio:.2f}x'} | "
              f"{pf(ratio is None or ratio >= r['shelf_updown_vol'])} | {sig} |")
    print(f"\nIgnition used: most recent SOS_IGNITION 1–12 trading days back. Floor = ign_low + 0.25 × "
          "(ign_close − ign_low). 'Above Floor & EMA20' must hold on EVERY close since the ignition "
          "(failing dates listed). Shelf range and up/down volume are over all bars since the ignition.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase D Breakout & Shelf Tracker")
    ap.add_argument("--date", default=None)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--replay", default=None, metavar="SYMBOL")
    ap.add_argument("--from", dest="d_from", default=None)
    ap.add_argument("--to", dest="d_to", default=None)
    ap.add_argument("--diagnose", action="store_true", help="with --replay: per-day ACTIVE_SHELF rule breakdown")
    a = ap.parse_args(argv)

    if a.local_db:
        import sqlite3
        conn = sqlite3.connect(a.local_db)
        conn.row_factory = sqlite3.Row
    else:
        import turso_db
        conn = turso_db.get_connection()

    if a.replay:
        if a.diagnose:
            diagnose(conn, a.replay.upper(), a.d_from or "2026-10-15", a.d_to or "2026-10-28")
        else:
            replay(conn, a.replay.upper(), a.d_from or "2026-10-01", a.d_to or a.d_from or "2026-11-05")
        if hasattr(sys.modules.get("turso_db"), "print_usage_report"):
            sys.modules["turso_db"].print_usage_report(label="run_phase_d_tracker.py --replay")
        return 0

    import batch_guard
    session = a.date or os.getenv("PSX_SESSION_DATE") or batch_guard.session_date()
    if not a.date and batch_guard.already_done(JOB, session, conn):
        print(f"[phase d] {session} already completed -- nothing to do")
        return 0
    ensure_schema(conn)
    syms = universe()
    sigs, stale, short = scan(conn, syms, session)
    n_ok = len(syms) - len(stale) - len(short)
    store(conn, session, sigs)
    by = {k: sum(1 for x in sigs if x["signal_type"] == k) for k in D.PRIORITY}
    print(f"[phase d] {session}: {n_ok} scanned, {len(stale)} stale {[x['symbol'] for x in stale]}, "
          f"{len(short)} with < {D.RULES['min_bars']} bars · signals {by}")
    if n_ok and n_ok >= 0.9 * (n_ok + len(stale)):
        batch_guard.mark_done(JOB, session, f"{n_ok} scanned, {len(stale)} stale, {len(sigs)} signals", conn)
    else:
        print("[phase d] fewer than 90% of symbols current -- no completion record (a later run retries)")
    if hasattr(sys.modules.get("turso_db"), "print_usage_report"):
        sys.modules["turso_db"].print_usage_report(label="run_phase_d_tracker.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
