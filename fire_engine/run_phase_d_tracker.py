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
'phase_d_batch' completion record when >= 90% of symbols were current. Each signal also stores pre-ignition
badges and a setup grade (fire_engine/phase_d_badges.py, 400 bars): display only, never a gate.

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
from fire_engine import phase_d_badges as PB  # noqa: E402

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
        "base_or_shelf_high", "shelf_days", "up_down_vol_ratio", "ignition_date", "ema20", "ignition_floor",
        "coil_dryup", "w1_leader", "exhausted_pre_ign", "price_tier", "setup_grade")
# additive columns (shown in the Breakouts tab's invalidation levels and pre-ignition badges); added in place on
# existing tables. Badges (fire_engine/phase_d_badges.py) are display only and NULL when they could not be computed.
ADDED_COLS = {"ema20": "DECIMAL(10,4)", "ignition_floor": "DECIMAL(10,4)",
              "coil_dryup": "INTEGER", "w1_leader": "INTEGER", "exhausted_pre_ign": "INTEGER",
              "price_tier": "TEXT", "setup_grade": "TEXT"}
BADGE_KEYS = ("coil_dryup", "w1_leader", "exhausted_pre_ign", "price_tier", "setup_grade")


def ensure_schema(conn):
    """Idempotent migration (CREATE ... IF NOT EXISTS, then ADD COLUMN for any column the table lacks),
    same convention as batch_guard's DDL."""
    for s in DDL:
        conn.execute(s)
    def _name(r):
        try:
            return r["name"]
        except (TypeError, KeyError, IndexError):
            return r[1]
    have = {_name(r) for r in conn.execute("PRAGMA table_info(phase_d_signals)").fetchall()}
    for col, typ in ADDED_COLS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE phase_d_signals ADD COLUMN {col} {typ}")
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
            sigs.append(dict(r, symbol=s, scan_date=session, **_badges(conn, s, session, r, log)))
    return sigs, stale, short


def _badges(conn, symbol, session, sig, log=print):
    """Pre-ignition badges + setup grade for one signal, from up to 400 bars ending at the session.
    Non-blocking: any failure is logged in one line and leaves the badge columns NULL."""
    if not sig.get("ignition_date"):
        return dict.fromkeys(BADGE_KEYS)
    try:
        g = PB.compute_badges(load_bars(conn, symbol, session, n=PB.BARS), sig["ignition_date"], session)
        return {k: g[k] for k in BADGE_KEYS}
    except Exception as e:
        log(f"{symbol}: badges skipped {e!r}")
        return dict.fromkeys(BADGE_KEYS)


def _round(v, n):
    return None if v is None else round(float(v), n)


def _flag(v):
    return None if v is None else int(bool(v))


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
                            _round(x["up_down_vol_ratio"], 3), x["ignition_date"],
                            _round(x.get("ema20"), 4), _round(x.get("ignition_floor"), 4),
                            _flag(x.get("coil_dryup")), _flag(x.get("w1_leader")),
                            _flag(x.get("exhausted_pre_ign")), x.get("price_tier"), x.get("setup_grade"))))
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
          f"{'base/shelf hi':>13} {'days':>4} {'up/dn':>6} {'ignition':10}  setup grade")
    out = []
    for k, b in enumerate(allbars):
        if not (d_from <= b["date"] <= d_to):
            continue
        window = allbars[max(0, k + 1 - D.RULES["bars"]):k + 1]
        r = D.evaluate(window) if len(window) >= D.RULES["min_bars"] else None
        f = lambda v, n=2: "—" if v is None else f"{v:.{n}f}"
        if r:
            out.append(r)
            grade = PB.compute_badges(allbars[max(0, k + 1 - PB.BARS):k + 1], r["ignition_date"], b["date"])
            print(f"{b['date']:10}  {r['signal_type']:15} {f(r['close']):>9} {f(r['pct_change']):>7} "
                  f"{f(r['rvol']):>6} {r['turnover_pkr']:>14,.0f} {f(r['base_or_shelf_high']):>13} "
                  f"{r['shelf_days']:>4} {f(r['up_down_vol_ratio']):>6} {r['ignition_date']:10}  "
                  f"{grade['setup_grade']}")
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
    print("| Date | Close | Volume | EMA20 | Shelf Days | Floor Value | Above Floor & EMA20? | Pullback Depth % | "
          "<= 25%? | Up/Down Vol Ratio | Shelf Vol / Ignition Vol | Volume Test | Final Signal |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
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
                  f"| — | {sig} |")
            continue
        age = t - ign
        m = D.shelf_metrics(w, ign, t, ema, r)
        early = " (under 3: too early)" if age < r["shelf_min_age"] else ""
        held = "Pass" if m["held"] else "Fail (" + ", ".join(m["broke_on"]) + ")"
        ratio = "—" if m["ratio"] is None else f"{m['ratio']:.2f}x"
        tv = "—" if m["throwback_vol"] is None else f"{m['throwback_vol']:.2f}x"
        vol = f"{pf(m['vol_ok'])} ({m['vol_path']}: {m['up_days']} up / {m['down_days']} down)"
        print(f"| {b['date']} | {b['close']:.2f} | {b['volume']:,.0f} | {ema[t]:.3f} | {age}{early} | "
              f"{m['floor']:.3f} | {held} | {m['depth'] * 100:.2f}% | {pf(m['depth_ok'])} | {ratio} | {tv} | "
              f"{vol} | {sig} |")
    print("\nIgnition used: most recent SOS_IGNITION 1–12 trading days back. 'Above Floor & EMA20' must hold on "
          "EVERY close since it. Volume test: up/down = at least one up day and ratio >= 1.5x (or no down days); "
          "throwback = no up day and shelf volume <= 0.40x the ignition bar's.")


def run_session(conn, session, log=print):
    """One daily batch for `session`: scan, replace that session's rows, completion record."""
    import batch_guard
    syms = universe()
    sigs, stale, short = scan(conn, syms, session)
    n_ok = len(syms) - len(stale) - len(short)
    store(conn, session, sigs)
    by = {k: sum(1 for x in sigs if x["signal_type"] == k) for k in D.PRIORITY}
    log(f"[phase d] {session}: {n_ok} scanned, {len(stale)} stale {[x['symbol'] for x in stale]}, "
        f"{len(short)} with < {D.RULES['min_bars']} bars · signals {by}")
    if n_ok and n_ok >= 0.9 * (n_ok + len(stale)):
        batch_guard.mark_done(JOB, session, f"{n_ok} scanned, {len(stale)} stale, {len(sigs)} signals", conn)
    else:
        log("[phase d] fewer than 90% of symbols current -- no completion record (a later run retries)")
    return sigs


def trading_sessions(conn, n, until, probe=12):
    """The last `n` PSX trading dates <= `until`, taken from the data itself (a date on which at least half
    of the first `probe` universe symbols have a bar), so holidays are skipped. ~probe * (n + 10) rows read."""
    from collections import Counter
    seen = Counter()
    syms = universe()[:probe]
    for s in syms:
        for r in conn.execute("SELECT trade_date FROM daily_ohlc WHERE symbol = ? AND trade_date <= ? "
                              "ORDER BY trade_date DESC LIMIT ?", (s, until, n + 10)).fetchall():
            seen[r["trade_date"] if not isinstance(r, (tuple, list)) else r[0]] += 1
    days = sorted(d for d, c in seen.items() if c >= len(syms) / 2)
    return days[-n:]


def readback(conn):
    """What the Breakouts tab will show: the latest session's rows, in the endpoint's order."""
    row = conn.execute("SELECT MAX(scan_date) AS d FROM phase_d_signals").fetchone()
    done = conn.execute("SELECT MAX(session_date) AS d FROM batch_runs WHERE job = ? AND status = 'completed'",
                        (JOB,)).fetchone()
    pick = lambda x: (x["d"] if not isinstance(x, (tuple, list)) else x[0]) if x else None
    d = max([v for v in (pick(row), pick(done)) if v], default=None)
    rows = conn.execute(
        "SELECT symbol, signal_type, close, pct_change, rvol, turnover_pkr, shelf_days, ignition_date, "
        "base_or_shelf_high, ema20, ignition_floor FROM phase_d_signals WHERE scan_date = ? ORDER BY CASE signal_type WHEN 'SHELF_BREAKOUT' THEN 0 "
        "WHEN 'SOS_IGNITION' THEN 1 WHEN 'ACTIVE_SHELF' THEN 2 ELSE 3 END, rvol DESC", (d,)).fetchall()
    rows = [dict(r) if not isinstance(r, (tuple, list)) else dict(zip(
        ("symbol", "signal_type", "close", "pct_change", "rvol", "turnover_pkr", "shelf_days", "ignition_date",
         "base_or_shelf_high", "ema20", "ignition_floor"), r))
        for r in rows]
    print(f"\n### Breakouts tab (read back from phase_d_signals) — session {d}: {len(rows)} stock(s)\n")
    print("| Symbol | Signal | Price | Day % | RVOL | Turnover (PKR) | Shelf Days | Ignition | Ceiling | "
          "20-EMA | Ignition floor | Cancel if close <= |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    f = lambda v, n=2: "—" if v is None else f"{float(v):.{n}f}"
    for x in rows:
        print(f"| {x['symbol']} | {x['signal_type']} | {f(x['close'])} | {f(x['pct_change'])} | {f(x['rvol'])}x | "
              f"{float(x['turnover_pkr'] or 0):,.0f} | {x['shelf_days']} | {x['ignition_date']} | "
              f"{f(x['base_or_shelf_high'])} | {f(x['ema20'])} | {f(x['ignition_floor'])} | "
              f"{f(max(v for v in (x['ema20'], x['ignition_floor']) if v is not None)) if (x['ema20'] or x['ignition_floor']) else '—'} |")
    totals = conn.execute("SELECT scan_date, signal_type, COUNT(*) AS n FROM phase_d_signals GROUP BY scan_date, "
                          "signal_type ORDER BY scan_date").fetchall()
    print("\nRows per session: " + "; ".join(
        f"{(t['scan_date'] if not isinstance(t, (tuple, list)) else t[0])} "
        f"{(t['signal_type'] if not isinstance(t, (tuple, list)) else t[1])}="
        f"{(t['n'] if not isinstance(t, (tuple, list)) else t[2])}" for t in totals))
    return d, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase D Breakout & Shelf Tracker")
    ap.add_argument("--date", default=None)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--replay", default=None, metavar="SYMBOL")
    ap.add_argument("--from", dest="d_from", default=None)
    ap.add_argument("--to", dest="d_to", default=None)
    ap.add_argument("--diagnose", action="store_true", help="with --replay: per-day ACTIVE_SHELF rule breakdown")
    ap.add_argument("--backfill", type=int, default=None, metavar="N",
                    help="run the daily batch for each of the last N PSX trading sessions up to --until")
    ap.add_argument("--until", default=None, help="with --backfill: last session date (default: current session)")
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
    if a.backfill:
        ensure_schema(conn)
        sessions = trading_sessions(conn, a.backfill, a.until or batch_guard.session_date())
        print(f"[phase d] backfill {len(sessions)} PSX sessions: {sessions}")
        for d in sessions:
            run_session(conn, d)
        readback(conn)
    else:
        session = a.date or os.getenv("PSX_SESSION_DATE") or batch_guard.session_date()
        if not a.date and batch_guard.already_done(JOB, session, conn):
            print(f"[phase d] {session} already completed -- nothing to do")
            return 0
        ensure_schema(conn)
        run_session(conn, session)
    if hasattr(sys.modules.get("turso_db"), "print_usage_report"):
        sys.modules["turso_db"].print_usage_report(label="run_phase_d_tracker.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
