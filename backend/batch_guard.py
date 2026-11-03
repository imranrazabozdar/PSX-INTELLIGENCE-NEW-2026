"""batch_guard.py — one authoritative successful run per PSX session date.

Each scheduled weekday batch is triggered twice (the Routine backstop and
GitHub's own, often hours-late, cron). Both triggers are kept -- the
backstop is not removed until its reliability is proven -- but only the
FIRST run that completes successfully for a session date does the work;
later triggers for that date see the marker and exit without touching data.

  * A run that fails or stops part-way writes no marker, so the next trigger
    retries it (all batch writes are upserts, so a retry is idempotent).
  * Explicit backfills (a --date / workflow `date` input) bypass the guard.
  * If the guard itself cannot read the DB it says "run" -- failing open to
    the pre-existing behaviour, never silently skipping a session.

Storage: table batch_runs(job, session_date, status, finished_at, detail),
created on first use (additive migration; no existing table touched).
Cost: 1 row read per check, 1 row written per completed run.

CLI (used by the workflows):
  python batch_guard.py check <job> [--date D]   -> prints skip=true|false (and to $GITHUB_OUTPUT)
  python batch_guard.py mark  <job> [--date D] [--detail TEXT]
  python batch_guard.py calendar --snapshot PATH [--date D] [--min-fresh 0.5]
                                                  -> prints trading=true|false
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DDL = ("CREATE TABLE IF NOT EXISTS batch_runs (job TEXT NOT NULL, session_date TEXT NOT NULL, "
       "status TEXT NOT NULL, finished_at TEXT, detail TEXT, PRIMARY KEY (job, session_date))")


def session_date():
    from fire_engine.market_hours import session_date as _sd
    return _sd()


def _conn(conn=None):
    if conn is not None:
        return conn
    import turso_db
    return turso_db.get_connection()


def already_done(job, date, conn=None):
    """True only if a completed marker exists for (job, date). Any error -> False."""
    try:
        c = _conn(conn)
        c.execute(DDL)
        row = c.execute("SELECT status FROM batch_runs WHERE job=? AND session_date=?", (job, date)).fetchone()
        if not row:
            return False
        st = row["status"] if not isinstance(row, (tuple, list)) else row[0]
        return st == "completed"
    except Exception as e:
        print(f"[batch_guard] check failed ({type(e).__name__}: {e}) -- running anyway")
        return False


def mark_done(job, date, detail="", conn=None):
    try:
        c = _conn(conn)
        c.execute(DDL)
        c.execute("INSERT INTO batch_runs(job, session_date, status, finished_at, detail) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(job, session_date) DO UPDATE SET status=excluded.status, "
                  "finished_at=excluded.finished_at, detail=excluded.detail",
                  (job, date, "completed", datetime.now(timezone.utc).isoformat(), detail[:500]))
        c.commit()
        print(f"[batch_guard] {job} {date}: marked completed")
        return True
    except Exception as e:
        print(f"[batch_guard] mark failed ({type(e).__name__}: {e})")
        return False


def fresh_fraction(snapshot_path, date, symbols=None):
    """Share of symbols whose newest bar in the local daily_ohlc snapshot is
    `date` -- 0 Turso reads. Below the threshold the session is treated as a
    PSX holiday / not yet published, and no fresh signals are generated."""
    if snapshot_path and os.path.exists(snapshot_path):
        c = sqlite3.connect(f"file:{snapshot_path}?mode=ro", uri=True)
        rows = c.execute("SELECT symbol, MAX(trade_date) FROM daily_ohlc GROUP BY symbol").fetchall()
        c.close()
        last = {s: d for s, d in rows}
    else:
        # No snapshot (its step failed): one indexed LIMIT-1 probe per
        # configured symbol, ~150 row reads.
        from fire_engine.config import load_config
        import turso_db
        tc = turso_db.get_connection()
        last = {}
        for sym in load_config()["stocks"]["universe"]:
            r = tc.execute("SELECT trade_date FROM daily_ohlc WHERE symbol=? ORDER BY trade_date DESC LIMIT 1",
                           (sym,)).fetchone()
            if r:
                last[sym] = r["trade_date"] if not isinstance(r, (tuple, list)) else r[0]
    pool = [s for s in (symbols or last) if s in last]
    if not pool:
        return 0.0, last
    return sum(1 for s in pool if last[s] == date) / len(pool), last


def _out(key, val):
    print(f"{key}={val}")
    gh = os.getenv("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"{key}={val}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "mark", "calendar"])
    ap.add_argument("job", nargs="?")
    ap.add_argument("--date", default=None)
    ap.add_argument("--detail", default="")
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--min-fresh", type=float, default=0.5)
    a = ap.parse_args()
    date = a.date or session_date()
    if a.cmd == "check":
        done = already_done(a.job, date)
        print(f"[batch_guard] {a.job} {date}: {'already completed -- skipping' if done else 'not yet completed -- running'}")
        _out("skip", "true" if done else "false")
        _out("session", date)
    elif a.cmd == "mark":
        mark_done(a.job, date, a.detail)
    else:
        frac, _ = fresh_fraction(a.snapshot, date)
        ok = frac >= a.min_fresh
        print(f"[batch_guard] calendar {date}: {frac:.0%} of symbols have a {date} bar -> "
              f"{'trading session' if ok else 'NOT a trading session / data not published -- no fresh signals'}")
        _out("trading", "true" if ok else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
