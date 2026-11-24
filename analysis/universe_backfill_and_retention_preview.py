#!/usr/bin/env python3
"""universe_backfill_and_retention_preview.py -- read-only report + one approved write.

Step 1 (SELECT)  presence check of a 104-ticker list against daily_ohlc.
Step 2 (SELECT)  retention PREVIEW: the two proposed DELETE statements are
                 printed as text and NEVER executed. Only COUNT(*)/SUM(pgsize)
                 style SELECTs are issued for their affected-row and size
                 estimates.
Step 3 (WRITE)   the repo's standard historical OHLC backfill
                 (run_ohlc_refresh helpers + scs_daily fetch), limited to the
                 26 NEW_SYMBOLS that have zero stored bars, as
                 INSERT OR IGNORE into daily_ohlc. Runs ONLY against production
                 Turso (LIBSQL_URL + LIBSQL_AUTH_TOKEN set, table present). The
                 local SQLite fallback is opened read-only and never written.
                 Nothing else is written; no DELETE/UPDATE/DROP/TRUNCATE anywhere.

  python analysis/universe_backfill_and_retention_preview.py

Connection: LIBSQL_URL / LIBSQL_AUTH_TOKEN secrets (address is never printed);
otherwise the local fallback psx_v2.db, read-only.
"""
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

# Approved: exactly these 26 symbols are the only ones that may be backfilled.
NEW_SYMBOLS = ["ALTN", "EPQL", "KOHE", "LPL", "HTL", "TELE", "HUMNL", "OCTOPUS", "GGGL", "GCWL",
               "JSCL", "JSIL", "ABHI", "AGL", "BCL", "SGF", "QUICE", "NGLEL", "TSPL", "MACTER",
               "BFBIO", "AGSML", "UNITY", "ATRL", "FATIMA", "ICL"]

REQUESTED_104 = (
    "DCL,DBCI,GCWL,ICL,HIFA,HGFA,TSMF,BOK,HMB,SCBPL,MCB,BECO,AGHA,ITTEFAQ,BCL,JSMFETF,MIIETF,"
    "NBPGETF,UBLPETF,AGL,AHCL,FFC,FATIMA,UNITY,QUICE,GGGL,BGL,STCL,GHGL,TGL,TPLL,PIL,CSIL,UNIC,"
    "ALAC,CENI,PASL,LSEFSL,TSBL,FDPL,FCSC,ABHI,LSECL,PSX,JSCL,SIBL,AKDSL,DEL,ASL,JSIL,CJPL,PGLC,"
    "LEUL,SGF,STPL,OML,GAMON,FPRM,WASL,ORM,FEM,FPJM,FANM,TRSM,FTMM,FIBLM,FECM,UCAPM,FTSM,OBOY,"
    "SPSL,WAFI,HTL,APL,MACTER,BFBIO,GLAXO,NGLEL,TSPL,KAPCO,ALTN,EPQL,KOHE,LPL,JVDC,TPLP,TPLRF1,"
    "CNERGY,PRL,NRL,ATRL,TCORP,AGSML,PTC,TPLT,TELE,HUMNL,SELECT,QTECH,ITANZ,OCTOPUS,NETSOL,BLUEX,PNSC"
).split(",")

DSS_DELETE_SQL = ("DELETE FROM dss_history WHERE saved_at < datetime('now','-30 days') OR id NOT IN "
                  "(SELECT MAX(id) FROM dss_history WHERE saved_at >= datetime('now','-30 days') "
                  "GROUP BY symbol, substr(saved_at,1,10));")
CANDLES_DELETE_SQL = "DELETE FROM market_candles WHERE date < date('now','-35 days');"

DSS_PRED = ("saved_at < datetime('now','-30 days') OR id NOT IN "
            "(SELECT MAX(id) FROM dss_history WHERE saved_at >= datetime('now','-30 days') "
            "GROUP BY symbol, substr(saved_at,1,10))")
CANDLES_PRED = "date < date('now','-35 days')"

BACKFILL_BUDGET_SECONDS = int(os.getenv("PSX_UNIVERSE_BACKFILL_BUDGET_SECONDS", str(25 * 60)))
MIB = 1024 * 1024

_READ_PREFIXES = ("SELECT", "PRAGMA", "WITH")
_FORBIDDEN = re.compile(r"\b(DELETE|DROP|TRUNCATE|INSERT|UPDATE|ALTER|CREATE|REPLACE|VACUUM|ATTACH)\b",
                        re.IGNORECASE)


class ReadOnlyDB:
    """Every read goes through here. Only SELECT/PRAGMA/WITH statements that
    contain no write keyword are accepted; anything else raises."""

    def __init__(self, conn):
        self._conn = conn

    def query(self, sql, params=()):
        head = sql.strip().split(None, 1)[0].upper() if sql.strip() else ""
        if head not in _READ_PREFIXES or _FORBIDDEN.search(sql):
            raise PermissionError(f"read helper refused non-read SQL: {sql[:60]!r}")
        return self._conn.execute(sql, params).fetchall()

    def scalar(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0][0] if rows else None

    def has_table(self, name):
        return bool(self.query("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def open_db():
    """Production Turso when LIBSQL_URL + LIBSQL_AUTH_TOKEN are set (address not
    printed); otherwise the local fallback opened read-only. Returns
    (ReadOnlyDB, label, is_turso, raw_conn)."""
    if os.getenv("LIBSQL_URL") and os.getenv("LIBSQL_AUTH_TOKEN"):
        import turso_db
        conn = turso_db.get_connection()
        return ReadOnlyDB(conn), "turso (production, via LIBSQL_URL secret -- address not printed)", True, conn
    local = ROOT / "psx_v2.db"
    conn = sqlite3.connect(f"file:{local}?mode=ro", uri=True)
    return ReadOnlyDB(conn), f"sqlite fallback (read-only): {local.name}", False, None


def step1_presence(db):
    print("=== STEP 1: 104-ticker presence in daily_ohlc (SELECT) ===")
    if not db.has_table("daily_ohlc"):
        print("daily_ohlc not present in this database -- every ticker counts as missing.")
        present = set()
    else:
        present = {str(r[0]).upper() for r in db.query("SELECT DISTINCT symbol FROM daily_ohlc") if r[0]}
    dupes = sorted(s for s, n in Counter(t.strip().upper() for t in REQUESTED_104).items() if n > 1)
    unique = list(dict.fromkeys(t.strip().upper() for t in REQUESTED_104))
    print(f"requested entries: {len(REQUESTED_104)}  unique: {len(unique)}  "
          f"duplicates: {dupes if dupes else 'none'}")
    have = [s for s in unique if s in present]
    miss = [s for s in unique if s not in present]
    print(f"present in daily_ohlc: {len(have)}")
    print("  " + ", ".join(have) if have else "  (none)")
    print(f"missing from daily_ohlc: {len(miss)}")
    print("  " + ", ".join(miss) if miss else "  (none)")
    print(f"distinct symbols in daily_ohlc overall: {len(present)}")
    return present


def _size_bytes(db, names):
    try:
        rows = db.query("SELECT name, SUM(pgsize) FROM dbstat WHERE name IN (%s) GROUP BY name"
                        % ",".join("?" * len(names)), tuple(names))
        got = {r[0]: int(r[1] or 0) for r in rows}
        return got, sum(got.values())
    except Exception as e:  # dbstat not compiled into this SQLite build
        return {}, None


def step2_retention(db):
    print("\n=== STEP 2: retention PREVIEW (DELETE statements printed, NOT executed) ===")
    print("-- a) dss_history")
    print(DSS_DELETE_SQL)
    print("-- b) market_candles")
    print(CANDLES_DELETE_SQL)
    print("")
    if db.has_table("dss_history"):
        total = int(db.scalar("SELECT COUNT(*) FROM dss_history") or 0)
        dele = int(db.scalar(f"SELECT COUNT(*) FROM dss_history WHERE {DSS_PRED}") or 0)
        kept = total - dele
        sizes, tot_b = _size_bytes(db, ["dss_history", "ix_dss_history_symbol"])
        freed = (dele / total * tot_b / MIB) if (total and tot_b) else None
        print(f"a) dss_history: total={total:,}  rows_to_delete={dele:,}  rows_kept={kept:,}")
        print(f"   dbstat bytes: {sizes or 'unavailable'}  est. MiB freed: "
              f"{'unavailable (no dbstat)' if freed is None else f'{freed:.2f}'}")
    else:
        print("a) dss_history: table not present in this database")
    cutoff = db.scalar("SELECT date('now','-35 days')") if db.has_table("market_candles") else None
    if db.has_table("market_candles"):
        total = int(db.scalar("SELECT COUNT(*) FROM market_candles") or 0)
        dele = int(db.scalar(f"SELECT COUNT(*) FROM market_candles WHERE {CANDLES_PRED}") or 0)
        kept = total - dele
        names = ["market_candles", "sqlite_autoindex_market_candles_1", "idx_candles_symbol_date"]
        sizes, tot_b = _size_bytes(db, names)
        freed = (dele / total * tot_b / MIB) if (total and tot_b) else None
        print(f"b) market_candles: cutoff date={cutoff}  total={total:,}  rows_to_delete={dele:,}  "
              f"rows_kept={kept:,}")
        print(f"   dbstat bytes: {sizes or 'unavailable'}  est. MiB freed: "
              f"{'unavailable (no dbstat)' if freed is None else f'{freed:.2f}'}")
    else:
        print(f"b) market_candles: table not present in this database (cutoff date={cutoff})")


def _ohlc_good_rows(symbol, df):
    import scs_daily
    good = []
    for _, x in df.iterrows():
        try:
            o, h, l, c = float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])
            if not (l <= min(o, c) <= max(o, c) <= h) or c <= 0:
                continue
            good.append((symbol.upper(), x["date"], o, h, l, c, float(x["volume"] or 0),
                         scs_daily.SOURCE_LABEL))
        except Exception:
            continue
    return good


def _insert_or_ignore(conn, good):
    """The single write path: INSERT OR IGNORE into daily_ohlc, chunked the same
    way run_ohlc_refresh does it. Nothing else is ever sent to the database."""
    CHUNK = 400
    if hasattr(conn, "batch_query"):
        queries = []
        for ci in range(0, len(good), CHUNK):
            part = good[ci:ci + CHUNK]
            sql = "INSERT OR IGNORE INTO daily_ohlc VALUES" + ",".join(["(?,?,?,?,?,?,?,?)"] * len(part))
            assert sql.startswith("INSERT OR IGNORE INTO daily_ohlc")
            queries.append((sql, [v for row in part for v in row]))
        conn.batch_query(queries)
    else:
        conn.executemany("INSERT OR IGNORE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)", good)
        conn.commit()


def step3_backfill(db, raw_conn, is_turso):
    print("\n=== STEP 3: standard historical OHLC backfill, 26 new symbols (WRITE) ===")
    if not is_turso:
        print("SKIPPED: not production Turso (no LIBSQL_URL/LIBSQL_AUTH_TOKEN). No write issued.")
        return
    if not db.has_table("daily_ohlc"):
        print("SKIPPED: daily_ohlc not present. The table is not created here. No write issued.")
        return
    import run_ohlc_refresh as R  # the repo's standard backfill helpers
    import scs_daily
    start_run = time.monotonic()
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for i, sym in enumerate(NEW_SYMBOLS):
        if time.monotonic() - start_run > BACKFILL_BUDGET_SECONDS:
            print(f"time budget reached before {sym}; remaining symbols need a re-run")
            break
        last = R.get_last_stored_bar(raw_conn, sym)
        if last:
            print(f"  {sym}: already has bars (latest {last['trade_date']}), not re-fetched")
            continue
        start = (datetime.now(timezone.utc) - timedelta(days=1827)).strftime("%Y-%m-%d")
        try:
            df = scs_daily.fetch_scs_daily_ohlc(sym, start_date=start, end_date=end_date)
        except Exception as e:
            print(f"  {sym}: fetch failed -- {type(e).__name__}: {e}")
            continue
        good = _ohlc_good_rows(sym, df) if df is not None and not df.empty else []
        if not good:
            print(f"  {sym}: no usable bars returned")
            time.sleep(0.5)
            continue
        _insert_or_ignore(raw_conn, good)
        print(f"  [{i + 1}/{len(NEW_SYMBOLS)}] {sym}: submitted {len(good)} bars (INSERT OR IGNORE)")
        time.sleep(1.0)


def step3_verify(db):
    print("\n=== STEP 3b: bars per new symbol after backfill (SELECT) ===")
    if not db.has_table("daily_ohlc"):
        print("daily_ohlc not present in this database.")
        return
    zero = []
    for sym in NEW_SYMBOLS:
        n, mn, mx = db.query("SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM daily_ohlc "
                             "WHERE symbol=?", (sym,))[0]
        print(f"  {sym:8s} bars={n:>6}  min={mn}  max={mx}")
        if not n:
            zero.append(sym)
    print(f"symbols with 0 bars: {zero if zero else 'none'}")


def main():
    db, label, is_turso, raw = open_db()
    print(f"Database: {label}")
    present = step1_presence(db)
    step2_retention(db)
    try:
        step3_backfill(db, raw, is_turso)
    except Exception as e:
        print(f"WRITE STEP ERROR: {type(e).__name__}: {e}")
        if is_turso:
            return 1
    step3_verify(db)
    if is_turso:
        try:
            import turso_db
            turso_db.print_usage_report(label="universe_backfill_preview")
        except Exception as e:
            print(f"(usage report unavailable: {type(e).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
