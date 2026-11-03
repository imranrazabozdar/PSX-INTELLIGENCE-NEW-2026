#!/usr/bin/env python3
"""wyckoff_pipeline_gate.py — explicit completion checks for the standalone
Original Wyckoff 1.0 workflow (wyckoff_daily.yml).

Orchestration only: no engine code, no scoring, no writes. It reads the
existing batch_runs markers / stored results and prints step outputs, so
the workflow runs each stage only when the stage before it really finished
for the SAME PSX session -- never on a timer.

  python -m fire_engine.wyckoff_pipeline_gate wyckoff [--date D]
      run=true  when the chart_refresh marker for the session exists (prices
                refreshed + trading-calendar check passed) and the
                wyckoff_batch marker does not (not already done).
  python -m fire_engine.wyckoff_pipeline_gate merge [--date D]
      run=true  when the wyckoff_batch marker exists AND the newest stored
                Wyckoff scan_date AND the stored Volatility scan's session
                are both the session date.

Turso cost: wyckoff = 2 marker reads; merge = 1 marker read + 1 MAX(scan_date)
query + 1 analysis_cache row. FIRE tables are never touched.
"""
import argparse
import json
import os
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def _val(row, key, idx=0):
    if row is None:
        return None
    return row[key] if not isinstance(row, (tuple, list)) else row[idx]


def wyckoff_ready(date, conn):
    import batch_guard
    if not batch_guard.already_done("chart_refresh", date, conn):
        return False, f"chart_refresh not completed for {date} (refresh failed, still running, or not a trading session)"
    if batch_guard.already_done("wyckoff_batch", date, conn):
        return False, f"wyckoff_batch already completed for {date}"
    return True, f"prices refreshed for {date}; Wyckoff 1.0 not yet run"


def merge_ready(date, conn):
    import batch_guard
    if not batch_guard.already_done("wyckoff_batch", date, conn):
        return False, f"wyckoff_batch not completed for {date} -- combined view left as is"
    w = _val(conn.execute("SELECT MAX(scan_date) AS d FROM wyckoff_accumulation").fetchone(), "d")
    if w != date:
        return False, f"newest Wyckoff scan_date is {w}, not {date}"
    r = conn.execute("SELECT result_json FROM analysis_cache WHERE cache_key=?",
                     ("volatility_engine_scan",)).fetchone()
    vs = json.loads(_val(r, "result_json")).get("session") if r else None
    if vs != date:
        return False, f"stored Volatility scan session is {vs}, not {date}"
    return True, f"Wyckoff and Volatility both fresh for {date}"


def _out(key, val):
    print(f"{key}={val}")
    gh = os.getenv("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"{key}={val}\n")


def main(argv=None, conn=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["wyckoff", "merge"])
    ap.add_argument("--date", default=None)
    a = ap.parse_args(argv)
    import batch_guard
    date = a.date or batch_guard.session_date()
    if conn is None:
        import turso_db
        conn = turso_db.get_connection()
    try:
        ok, why = (wyckoff_ready if a.stage == "wyckoff" else merge_ready)(date, conn)
    except Exception as e:   # fail closed: never run a stage on an unverified state
        ok, why = False, f"check failed ({type(e).__name__}: {e})"
    print(f"[wyckoff gate] {a.stage} {date}: {'RUN' if ok else 'SKIP'} -- {why}")
    _out("run", "true" if ok else "false")
    _out("session", date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
