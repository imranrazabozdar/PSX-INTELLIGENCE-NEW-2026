#!/usr/bin/env python3
"""run_retention_once.py -- ONE-OFF guarded retention cleanup (two DELETEs, once).

Executes exactly two statements, each once, in this order:

  a) dss_history: keep the last 30 days (Pakistan time, UTC+5) and, within that
     window, only the newest row (max id) per symbol per Pakistan calendar day.
  b) market_candles: drop rows whose date is more than 35 days old.

Nothing else is written: no DROP / TRUNCATE / VACUUM / UPDATE / INSERT.

Guards
  * refuses unless --confirm DELETE is passed
  * refuses unless dss_history and market_candles both exist
  * refuses unless LIBSQL_URL (and LIBSQL_AUTH_TOKEN) are set and the connection
    is really Turso (not the silent local fallback in backend/turso_db.py)
  * sanity check: datetime(saved_at,'+5 hours') must parse on a sample row,
    otherwise nothing is deleted
  * statement (b) is skipped if statement (a) raised

Test-only: --local-db PATH --allow-local runs the same SQL against a local SQLite
file (never used by the workflow).

  python analysis/run_retention_once.py --confirm DELETE
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

DSS_PRED = ("datetime(saved_at,'+5 hours') < datetime('now','+5 hours','-30 days') OR id NOT IN "
            "(SELECT MAX(id) FROM dss_history WHERE datetime(saved_at,'+5 hours') >= "
            "datetime('now','+5 hours','-30 days') GROUP BY symbol, date(datetime(saved_at,'+5 hours')))")
DSS_DELETE_SQL = f"DELETE FROM dss_history WHERE {DSS_PRED};"

CANDLES_PRED = "date < date('now','-35 days')"
CANDLES_DELETE_SQL = f"DELETE FROM market_candles WHERE {CANDLES_PRED};"


def _first_value(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


class Db:
    def __init__(self, conn):
        self.conn = conn

    def _clear_cache(self):
        # turso_db caches SELECT results for a short TTL; drop them so counts
        # taken after a DELETE are never stale.
        cache = getattr(self.conn, "_query_cache", None)
        if isinstance(cache, dict):
            cache.clear()

    def scalar(self, sql):
        self._clear_cache()
        cur = self.conn.cursor()
        cur.execute(sql)
        return _first_value(cur.fetchone())

    def table_exists(self, name):
        return scalar_exists(self, name)

    def write(self, sql):
        cur = self.conn.cursor()
        cur.execute(sql)
        self.conn.commit()
        self._clear_cache()
        return getattr(cur, "rowcount", -1)


def scalar_exists(db, name):
    return db.scalar(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{name}'") == 1


def open_connection(args):
    if args.allow_local:
        if not args.local_db:
            sys.exit("REFUSED: --allow-local requires --local-db")
        conn = sqlite3.connect(args.local_db)
        return Db(conn), f"LOCAL TEST SQLITE: {Path(args.local_db).name}"
    if not os.getenv("LIBSQL_URL"):
        sys.exit("REFUSED: LIBSQL_URL is not set")
    import turso_db
    conn = turso_db.get_connection()
    if not turso_db.USING_TURSO or turso_db._on_local_fallback:
        sys.exit("REFUSED: Turso connection unavailable; would fall back to a local file. Nothing deleted.")
    return Db(conn), "turso (production, via LIBSQL_URL secret -- address not printed)"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", default="", help="must be exactly DELETE")
    ap.add_argument("--local-db", default=None, help="test only: SQLite file")
    ap.add_argument("--allow-local", action="store_true", help="test only: permit --local-db")
    args = ap.parse_args()

    if args.confirm != "DELETE":
        sys.exit("REFUSED: pass --confirm DELETE to run")

    db, label = open_connection(args)
    print(f"connected: {label}")

    for t in ("dss_history", "market_candles"):
        if not db.table_exists(t):
            sys.exit(f"REFUSED: table {t} not present")

    sample = db.scalar("SELECT datetime(saved_at,'+5 hours') AS d FROM dss_history LIMIT 1")
    if sample is None:
        sys.exit("ABORT: datetime(saved_at,'+5 hours') returned NULL on sample row; nothing deleted")
    print("timestamp parse check: OK")

    # ---- (a) dss_history
    total = db.scalar("SELECT COUNT(*) FROM dss_history")
    matched = db.scalar(f"SELECT COUNT(*) FROM dss_history WHERE {DSS_PRED}")
    print(f"\n[a] dss_history before: total={total} matching_predicate={matched}")
    try:
        db.write(DSS_DELETE_SQL)
    except Exception as e:
        print(f"[a] DELETE raised {type(e).__name__}: {e}")
        print("[b] skipped because [a] raised")
        sys.exit(1)
    print(f"[a] dss_history after: remaining={db.scalar('SELECT COUNT(*) FROM dss_history')}")

    # ---- (b) market_candles
    total_c = db.scalar("SELECT COUNT(*) FROM market_candles")
    matched_c = db.scalar(f"SELECT COUNT(*) FROM market_candles WHERE {CANDLES_PRED}")
    print(f"\n[b] market_candles before: total={total_c} matching_predicate={matched_c}")
    try:
        db.write(CANDLES_DELETE_SQL)
    except Exception as e:
        print(f"[b] DELETE raised {type(e).__name__}: {e}")
        sys.exit(1)
    print(f"[b] market_candles after: remaining={db.scalar('SELECT COUNT(*) FROM market_candles')}")

    # ---- size
    page_size = db.scalar("PRAGMA page_size")
    page_count = db.scalar("PRAGMA page_count")
    freelist = db.scalar("PRAGMA freelist_count")
    mb = 1024 * 1024
    print(f"\npage_size={page_size} page_count={page_count} freelist_count={freelist}")
    print(f"DB size: {page_count * page_size / mb:.1f} MB; freelist: {freelist * page_size / mb:.1f} MB")

    try:
        import turso_db
        if hasattr(turso_db, "print_usage_report"):
            turso_db.print_usage_report(label="run_retention_once.py")
    except Exception as e:
        print(f"(usage report unavailable: {type(e).__name__})")


if __name__ == "__main__":
    main()
