#!/usr/bin/env python3
"""db_prune_cache.py — deletes ohlcv_4h rows older than `retention_days`.

Nothing else ever deletes from ohlcv_4h: wyckoff_data_fetcher.store_4h_data()
and backfill_4h.py only INSERT/UPSERT, so without this the cache table grows
forever. daily_ohlc is deliberately NOT touched here -- it's backend/'s own
table (populated by backend/run_ohlc_refresh.py), holds intentionally
unbounded history for the rolling daily windows, and pruning it is out of
this module's scope.

Uses the same DatabaseManager(conn=turso_db.get_connection()) / --local-db
convention as every other fire_engine entry point (run_daily_batch.py,
run_wyckoff_batch.py, backfill_4h.py) -- not a separate raw url/token
connection path.
"""
import argparse
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def prune_ohlcv_4h_cache(db, retention_days: int = 35) -> tuple:
    """Delete ohlcv_4h rows whose `datetime` is older than `retention_days`
    days ago. Returns (rows_deleted, status_message). Idempotent -- a
    DELETE ... WHERE is safe to run repeatedly; rows already gone just
    don't match the WHERE clause again.

    SQLite/libSQL has no NOW()/INTERVAL (that's MySQL/Postgres syntax) --
    the equivalent here is datetime('now', '-N days')."""
    try:
        cur = db.conn.execute(
            "DELETE FROM ohlcv_4h WHERE datetime < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        db.conn.commit()
        deleted = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        return deleted, f"Pruned {deleted} row(s) from ohlcv_4h (retained last {retention_days} days)"
    except Exception as exc:
        # Never let a prune failure take down the batch run around it --
        # this is housekeeping, not a step anything downstream depends on.
        return 0, f"ohlcv_4h prune failed ({type(exc).__name__}: {exc}); left cache untouched"


def audit_table_row_counts(db, tables: list) -> dict:
    """Row counts for a small set of tables -- the cheap, always-available
    substitute for a real per-table byte-size query. SQLite/libSQL has no
    portable per-table size pragma (pragma_page_count/pragma_page_size
    return ONE whole-database number, not one row per table, and dbstat
    is a compile-time-optional virtual table not guaranteed to exist on
    Turso) -- row counts are what's actually queryable everywhere, and at
    this project's scale (low thousands of rows) they're what matters
    for confirming pruning is working, not exact bytes."""
    counts = {}
    for table in tables:
        try:
            row = db.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            counts[table] = row["n"]
        except Exception as exc:
            counts[table] = f"unavailable ({type(exc).__name__})"
    return counts


def main():
    parser = argparse.ArgumentParser(description="Prune ohlcv_4h rows older than --retention-days.")
    parser.add_argument("--retention-days", type=int, default=35)
    parser.add_argument("--local-db", default=None,
                         help="Path to a standalone sqlite file instead of the shared Turso DB "
                              "(development/testing only)")
    args = parser.parse_args()

    from fire_engine.database import DatabaseManager
    if args.local_db:
        db = DatabaseManager(db_path=args.local_db)
    else:
        import turso_db
        db = DatabaseManager(conn=turso_db.get_connection())

    try:
        deleted, message = prune_ohlcv_4h_cache(db, retention_days=args.retention_days)
        print(message, flush=True)

        counts = audit_table_row_counts(db, ["ohlcv_4h", "wyckoff_accumulation", "wyckoff_scans"])
        print("\nRow-count audit (daily_ohlc intentionally excluded -- unbounded by design):")
        for table, n in counts.items():
            print(f"  {table}: {n} rows")
    finally:
        db.close()


if __name__ == "__main__":
    main()
