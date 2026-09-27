"""snapshot_daily_ohlc.py — copy daily_ohlc from Turso into a local SQLite
file once per GitHub Actions job, so the pattern scan and backtest steps
after it read that file instead of Turso (see turso_db's "daily_ohlc
snapshot" section for the routing, and PSX_DAILY_OHLC_SNAPSHOT for the path).

Pages through the table by rowid, so the whole copy costs about one read
per stored row (~160K) instead of the ~3M the later steps would otherwise
read between them. Never fails the job: if the copy can't be made, the
later steps simply read Turso as before.
"""
import os
import sqlite3
import sys
import time

import turso_db

PAGE = 20000
COLS = "symbol, trade_date, open, high, low, close, volume, source"


def main():
    path = os.getenv("PSX_DAILY_OHLC_SNAPSHOT")
    if not path:
        print("[snapshot] PSX_DAILY_OHLC_SNAPSHOT not set -- nothing to do")
        return 0
    turso_db._snapshot["disabled"] = True   # this process must read Turso itself
    tmp = path + ".tmp"
    t0 = time.time()
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        out = sqlite3.connect(tmp)
        out.execute("CREATE TABLE daily_ohlc(symbol TEXT, trade_date TEXT, open REAL, high REAL, "
                    "low REAL, close REAL, volume REAL, source TEXT, PRIMARY KEY(symbol, trade_date))")
        src = turso_db.get_connection()
        last, total = 0, 0
        while True:
            rows = src.execute(f"SELECT rowid AS rid, {COLS} FROM daily_ohlc "
                               f"WHERE rowid > ? ORDER BY rowid LIMIT {PAGE}", (last,)).fetchall()
            if not rows:
                break
            out.executemany("INSERT OR IGNORE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)",
                            [tuple(r[c.strip()] for c in COLS.split(",")) for r in rows])
            last = rows[-1]["rid"]
            total += len(rows)
            if len(rows) < PAGE:
                break
        out.commit()
        syms = out.execute("SELECT COUNT(DISTINCT symbol) FROM daily_ohlc").fetchone()[0]
        out.close()
        os.replace(tmp, path)
        print(f"[snapshot] {total:,} rows / {syms} symbols -> {path} in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"[snapshot] failed ({type(e).__name__}: {e}) -- later steps will read Turso directly")
        for p in (tmp, path):
            try:
                os.remove(p)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
