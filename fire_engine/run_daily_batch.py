#!/usr/bin/env python3
"""run_daily_batch.py — CLI entry point for the FIRE Engine's daily batch
(Phase 17). Intended to run on a schedule after PSX market close (e.g. a
GitHub Actions cron, the pattern this repo already uses for every other
Turso-dependent scheduled job -- see .github/workflows/
refresh_chart_patterns.yml -- rather than a long-lived APScheduler
process, since this environment has no always-on host to run one on).

By default writes into the SAME Turso database backend/app.py's
Patterns tab reads from (via backend/turso_db.get_connection()), so a
completed run is visible to /patterns/fire-scan immediately. Pass
--local-db PATH to use a standalone sqlite file instead (development/
testing only).
"""
import argparse
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fire_engine.config import load_config
from fire_engine.database import DatabaseManager
from fire_engine.scheduler import run_daily_batch


def main():
    parser = argparse.ArgumentParser(description="Run the PSX FIRE Engine daily batch.")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--local-db", default=None,
                         help="Path to a standalone sqlite file instead of the shared Turso DB "
                              "(development/testing only)")
    parser.add_argument("--config", default=None, help="Path to fire_config.yaml (default: bundled)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.local_db:
        db = DatabaseManager(db_path=args.local_db)
    else:
        import turso_db
        db = DatabaseManager(conn=turso_db.get_connection())

    try:
        result = run_daily_batch(db, cfg, date=args.date)
    finally:
        db.close()

    ok = sum(1 for r in result["results"] if r["status"] not in ("ERROR", "NO_DATA"))
    errors = [r for r in result["results"] if r["status"] == "ERROR"]
    total_events = sum(r.get("events_logged", 0) for r in result["results"])
    print(f"Daily batch for {result['date']}: {ok}/{len(result['results'])} symbols processed OK, "
          f"{total_events} events logged.")
    for r in result["results"]:
        print(f"  {r['symbol']}: status={r['status']} events={r.get('events_logged', 0)} "
              f"fire={r.get('fire_count', 0)} prefire={r.get('prefire_count', 0)}"
              + (f" ERROR={r.get('error')}" if r["status"] == "ERROR" else ""))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
