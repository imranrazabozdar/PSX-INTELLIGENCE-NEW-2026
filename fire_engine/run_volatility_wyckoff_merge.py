#!/usr/bin/env python3
"""run_volatility_wyckoff_merge.py — downstream step after run_wyckoff_batch.py.

Joins the Wyckoff batch's stored output (wyckoff_accumulation, unchanged)
with the Volatility Intelligence Engine's latest stored scan
(analysis_cache 'volatility_engine_scan', produced by the pattern-refresh
job) and saves the combined view as analysis_cache
'volatility_wyckoff_combined'. The pattern-refresh job runs the same merge
at its end, so whichever finishes later writes the freshest pairing.

Turso cost per run: ~150 rows read (latest Wyckoff rows) + 1 read + 1 write.
Never raises: it must not affect the FIRE / Wyckoff results.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def merge_and_save(conn, log=print):
    import volatility_engine as ve
    rows = ve.load_latest_wyckoff_rows(conn)
    r = conn.execute("SELECT result_json, run_at FROM analysis_cache WHERE cache_key=?",
                     ("volatility_engine_scan",)).fetchall()
    if not r:
        log("[vol x wyckoff] no volatility_engine_scan stored yet -- skipped")
        return None
    vol = json.loads(r[0]["result_json"])
    vol["_cache_run_at"] = r[0]["run_at"]
    combined = ve.combine_with_wyckoff(vol, [dict(x) for x in rows])
    conn.execute("""INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
        VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET run_at=excluded.run_at,
        run_at_epoch=excluded.run_at_epoch, result_json=excluded.result_json""",
                 ("volatility_wyckoff_combined", datetime.now(timezone.utc).isoformat(), time.time(),
                  json.dumps(combined)))
    conn.commit()
    log(f"[vol x wyckoff] merged {combined['n_wyckoff']} Wyckoff rows ({combined['wyckoff_date']}) with "
        f"{combined['n_volatility']} volatility rows ({combined['volatility_rows_date']}); "
        f"{sum(x['confluence'] for x in combined['rows'])} confluence, "
        f"{sum(x['conflict'] for x in combined['rows'])} conflict")
    return combined


def main():
    try:
        import turso_db
        merge_and_save(turso_db.get_connection())
        if hasattr(turso_db, "print_usage_report"):
            turso_db.print_usage_report(label="run_volatility_wyckoff_merge.py")
    except Exception as e:
        print(f"[vol x wyckoff] skipped: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
