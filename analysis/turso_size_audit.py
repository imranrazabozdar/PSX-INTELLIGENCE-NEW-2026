#!/usr/bin/env python3
"""turso_size_audit.py -- READ-ONLY size / row-count audit of the Turso database.

Only SELECT and PRAGMA statements are issued; every statement goes through q(),
which refuses anything else. Nothing is written and no schema is changed.

  python analysis/turso_size_audit.py [--local-db PATH] [--host HOST]

Data source (same resolution as watchlist_breakout_audit.open_db):
  --local-db PATH   SQLite snapshot (opened mode=ro)
  LIBSQL_URL env    production Turso via backend/turso_db.py (address is never printed)
  --host HOST       Turso HTTP pipeline (default: psx-library test DB)
"""
import argparse
import atexit
import os
import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
ROOT = str(Path(__file__).resolve().parent.parent)
for p in (ROOT, str(Path(ROOT) / "backend"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
import watchlist_breakout_audit as A  # noqa: E402

DATE_COLS = ["trade_date", "scan_date", "session_date", "date", "datetime", "saved_at",
             "created_at", "run_at", "fetched_at", "ts", "bar_time"]
PRESENCE_SYMBOLS = ("CNERGY,KAPCO,ALTN,EPQL,KOHE,LPL,WAFI,HTL,PTC,TELE,HUMNL,OCTOPUS,BLUEX,TPLT,"
                    "ITANZ,QTECH,GGGL,BGL,GHGL,TGL,STCL,GCWL,ASL,STPL,DCL,JVDC,PSX,JSCL,JSIL,ABHI,"
                    "AKDSL,AHCL,AGL,BCL,SGF,QUICE,NGLEL,TSPL,MACTER,BFBIO,AGSML,UNITY,NRL,ATRL,"
                    "NETSOL,GLAXO,FFC,FATIMA,ICL,MCB,HMB").split(",")


def q(sql):
    """Single gateway for every query. Only read-only statements are allowed."""
    head = sql.lstrip().upper()
    if not (head.startswith("SELECT") or head.startswith("PRAGMA")):
        raise ValueError(f"refused non-read statement: {sql[:40]!r}")
    return DB.query(sql)


def first_value(row):
    return list(row.values())[0]


def num(v):
    return float(v) if v is not None else 0.0


def main(argv=None):
    global DB
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", default=None)
    ap.add_argument("--host", default=None)
    a = ap.parse_args(argv)

    DB, src = A.open_db(a)
    print(f"Source: {src}")

    # ---- database size -------------------------------------------------
    page_size = None
    try:
        page_count = num(first_value(q("PRAGMA page_count")[0]))
        page_size = num(first_value(q("PRAGMA page_size")[0]))
        print(f"DB size: {page_count * page_size / 1e6:,.1f} MB "
              f"({int(page_count):,} pages x {int(page_size):,} bytes)")
    except Exception as e:  # noqa: BLE001
        print(f"DB size: unavailable ({type(e).__name__})")
    try:
        freelist = num(first_value(q("PRAGMA freelist_count")[0]))
        if page_size:
            print(f"Freelist: {freelist * page_size / 1e6:,.1f} MB ({int(freelist):,} pages)")
        else:
            print(f"Freelist: {int(freelist):,} pages")
    except Exception as e:  # noqa: BLE001
        print(f"Freelist: unavailable ({type(e).__name__})")

    # ---- schema --------------------------------------------------------
    objs = q("SELECT name, type, tbl_name FROM sqlite_master WHERE type IN ('table','index') "
             "ORDER BY type, name")
    tables = [r["name"] for r in objs if r["type"] == "table"]
    indexes = [r["name"] for r in objs if r["type"] == "index"]
    print(f"Schema: {len(tables)} tables, {len(indexes)} indexes")
    for r in objs:
        print(f"  {r['type']:<5} {r['name']}  (on {r['tbl_name']})")

    # ---- per-table rows / date range / symbols -------------------------
    print("Tables:")
    for t in tables:
        try:
            n = int(num(q(f'SELECT COUNT(*) AS n FROM "{t}"')[0]["n"]))
            cols = [c["name"] for c in q(f'PRAGMA table_info("{t}")')]
            dcol = next((c for c in DATE_COLS if c in cols), None)
            parts = [f"{t}: rows={n:,}"]
            if dcol:
                rng = q(f'SELECT MIN("{dcol}") AS lo, MAX("{dcol}") AS hi FROM "{t}"')[0]
                parts.append(f"{dcol} {rng['lo']}..{rng['hi']}")
            if "symbol" in cols:
                ns = int(num(q(f'SELECT COUNT(DISTINCT symbol) AS n FROM "{t}"')[0]["n"]))
                parts.append(f"symbols={ns:,}")
            print("  " + " | ".join(parts))
        except Exception as e:  # noqa: BLE001
            print(f"  {t}: error ({type(e).__name__})")

    # ---- daily_ohlc coverage -------------------------------------------
    if "daily_ohlc" in tables:
        try:
            counts = sorted(int(num(r["n"])) for r in
                            q("SELECT symbol, COUNT(*) AS n FROM daily_ohlc GROUP BY symbol"))
            if counts:
                mid = len(counts) // 2
                median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
                print(f"daily_ohlc rows per symbol: min={counts[0]:,} median={median:,.0f} "
                      f"max={counts[-1]:,} (n={len(counts)} symbols)")
            present = {r["symbol"] for r in q("SELECT DISTINCT symbol FROM daily_ohlc")}
            present = {str(s).upper() for s in present}
            have = [s for s in PRESENCE_SYMBOLS if s in present]
            missing = [s for s in PRESENCE_SYMBOLS if s not in present]
            print(f"daily_ohlc presence ({len(PRESENCE_SYMBOLS)} checked): "
                  f"present={len(have)} missing={len(missing)}")
            print(f"  present: {','.join(have) or '-'}")
            print(f"  missing: {','.join(missing) or '-'}")
        except Exception as e:  # noqa: BLE001
            print(f"daily_ohlc coverage: error ({type(e).__name__})")
    else:
        print("daily_ohlc: table not present in this database")

    # ---- per-object storage via dbstat ---------------------------------
    print("Storage by object (dbstat):")
    try:
        rows = q("SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC")
        for r in rows:
            print(f"  {num(r['bytes']) / 1e6:>10,.2f} MB  {r['name']}")
    except Exception as e:  # noqa: BLE001
        print(f"  unavailable ({type(e).__name__})")

    # ---- usage report, if the Turso layer was used ---------------------
    tdb = sys.modules.get("turso_db")
    if tdb is not None and hasattr(tdb, "print_usage_report"):
        # The module may already have registered its own atexit copy (PSX_TURSO_USAGE_REPORT);
        # drop it so the block is printed once.
        atexit.unregister(tdb.print_usage_report)
        tdb.print_usage_report(label="turso_size_audit.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
