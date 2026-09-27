#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_turso_to_turso.py — one-off bulk copy of every table from one Turso
database to another, chunked so neither side takes an unbounded single request.

Why this exists: the production database's Turso account (imranraza786,
free tier) exhausted its 500M-reads/month quota from the Streamlit dashboard's
own live query traffic, blocking ALL reads against every database on that
account until the monthly cycle resets or the plan is upgraded. This script
moves the database to a fresh Turso account (a new free-tier quota), buying
headroom -- it is a stopgap, not a fix for the underlying read volume, which
is a separate caching effort (see backend/app.py cache work).

IMPORTANT: this script reads from the SOURCE account, so it can only run once
that account's reads are actually unblocked again (quota reset, or an
upgrade) -- while blocked, every SELECT below will raise the same
"reads are blocked" OperationalError this migration exists to get away from.

Usage:
    SRC_LIBSQL_URL="libsql://old-db.turso.io" \\
    SRC_LIBSQL_AUTH_TOKEN="..." \\
    DST_LIBSQL_URL="libsql://new-db.turso.io" \\
    DST_LIBSQL_AUTH_TOKEN="..." \\
    python scripts/migrate_turso_to_turso.py

Optional flags:
    --chunk-size N   Rows per read/write round trip (default 500)
    --tables a,b,c   Only migrate these tables (default: every user table)
    --dry-run        Print row counts and schema only, copy nothing

Safe to re-run: schema is created with CREATE TABLE/INDEX IF NOT EXISTS, and
every row insert is INSERT OR IGNORE against the destination. This correctly
dedupes on re-run PROVIDED each table has a PRIMARY KEY or UNIQUE constraint
(true for every table in this project's schema at the time of writing) --
a table without one would just accumulate duplicate rows on a second run, so
this script cross-checks final row counts per table and prints a warning
rather than silently trusting a match.
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import turso_db  # noqa: E402 — only for _TursoConnection, not its module-level singleton


def _connect(url, token, label):
    if not url or not token:
        print(f"Missing {label}_LIBSQL_URL / {label}_LIBSQL_AUTH_TOKEN")
        sys.exit(1)
    http_url = url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    conn = turso_db._TursoConnection(http_url, token)
    conn.execute("SELECT 1")  # fail fast if creds are wrong
    return conn


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunk-size", type=int, default=500)
    ap.add_argument("--tables", default=None, help="comma-separated table names; default: all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("=" * 70)
    print("TURSO -> TURSO MIGRATION")
    print("=" * 70)

    src = _connect(os.getenv("SRC_LIBSQL_URL"), os.getenv("SRC_LIBSQL_AUTH_TOKEN"), "SRC")
    print("Connected to source")
    dst = None if args.dry_run else _connect(os.getenv("DST_LIBSQL_URL"), os.getenv("DST_LIBSQL_AUTH_TOKEN"), "DST")
    if dst:
        print("Connected to destination")

    schema_rows = src.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE type IN ('table','index') AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL "
        "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END"
    ).fetchall()

    wanted = set(args.tables.split(",")) if args.tables else None
    table_names = [r["name"] for r in schema_rows if r["type"] == "table" and (not wanted or r["name"] in wanted)]

    if not table_names:
        print("No matching tables found.")
        sys.exit(1)

    print(f"\nTables to migrate ({len(table_names)}): {', '.join(table_names)}\n")

    if not args.dry_run:
        for row in schema_rows:
            if row["type"] == "index" and wanted and not any(t in row["sql"] for t in wanted):
                continue
            try:
                dst.execute(row["sql"].replace(f"{row['type'].upper()} ", f"{row['type'].upper()} IF NOT EXISTS ", 1)
                            if "IF NOT EXISTS" not in row["sql"].upper() else row["sql"])
            except Exception as e:
                print(f"   schema warning for {row['name']}: {e}")
        print("Schema created/verified on destination\n")

    total_copied = 0
    for table in table_names:
        pk_check = src.execute(f"PRAGMA table_info({table})").fetchall()
        has_pk = any(r["pk"] for r in pk_check)
        cols = [r["name"] for r in pk_check]
        col_list = ", ".join(cols)
        placeholders = ", ".join(["?"] * len(cols))

        total = src.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchall()[0]["c"]
        print(f"[{table}] {total} rows on source" + ("" if has_pk else "  ⚠️  no PRIMARY KEY — re-run will duplicate rows"))
        if total == 0 or args.dry_run:
            continue

        copied = 0
        offset = 0
        t0 = time.time()
        while offset < total:
            rows = src.execute(
                f"SELECT {col_list} FROM {table} LIMIT ? OFFSET ?", (args.chunk_size, offset)
            ).fetchall()
            if not rows:
                break
            queries = [
                (f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                 tuple(r[c] for c in cols))
                for r in rows
            ]
            dst.batch_query(queries)
            copied += len(rows)
            offset += args.chunk_size
            if copied % (args.chunk_size * 10) == 0 or offset >= total:
                print(f"   ...{copied}/{total}")
        elapsed = time.time() - t0
        print(f"   done in {elapsed:.1f}s")

        dst_count = dst.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchall()[0]["c"]
        status = "OK" if dst_count >= total else f"⚠️  MISMATCH (dest has {dst_count}, source has {total})"
        print(f"   verify: {dst_count} rows on destination — {status}\n")
        total_copied += copied

    print("=" * 70)
    print(f"Migration complete. {total_copied} rows copied across {len(table_names)} tables.")
    print("Next: point LIBSQL_URL / LIBSQL_AUTH_TOKEN (repo secrets + Streamlit Cloud secrets) at the new database.")
    print("=" * 70)


if __name__ == "__main__":
    main()
