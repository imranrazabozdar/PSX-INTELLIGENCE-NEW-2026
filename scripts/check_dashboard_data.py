"""check_dashboard_data.py — print the data date behind each dashboard tab,
read from the live Turso DB through the same backend code the dashboard
runs. For "the dashboard isn't showing today's data" reports: it separates
"the daily jobs didn't store it" from "the dashboard isn't showing what's
stored". Read-only, and only small indexed queries (a few thousand rows).

Run from the repo root with LIBSQL_URL / LIBSQL_AUTH_TOKEN set.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import turso_db  # noqa: E402


def main():
    conn = turso_db.get_connection()
    print(f"DB: {'Turso' if turso_db.USING_TURSO else 'LOCAL SQLITE (secrets missing?)'}")

    print("\n== daily_ohlc (prices) ==")
    for sym in ("OGDC", "LUCK", "HUBC", "CNERGY"):
        rows = conn.execute("SELECT trade_date, close, source FROM daily_ohlc WHERE symbol=? "
                            "ORDER BY trade_date DESC LIMIT 2", (sym,)).fetchall()
        print(f"  {sym}: " + ", ".join(f"{r['trade_date']} close={r['close']}" for r in rows))

    print("\n== FIRE / Wyckoff tables ==")
    r = conn.execute("SELECT MAX(event_date) AS d FROM fire_events").fetchone()
    print(f"  fire_events latest event_date: {r['d']}")
    r = conn.execute("SELECT MAX(scan_date) AS d FROM wyckoff_accumulation").fetchone()
    print(f"  wyckoff_accumulation latest scan_date: {r['d']}")

    print("\n== analysis_cache (what the Patterns/Screener tabs serve) ==")
    now = time.time()
    for row in conn.execute("SELECT cache_key, run_at, run_at_epoch, result_json FROM analysis_cache "
                            "ORDER BY run_at_epoch DESC").fetchall():
        try:
            res = json.loads(row["result_json"] or "{}")
        except Exception:
            res = {}
        info = {k: res.get(k) for k in ("date", "latest_date", "as_of", "scanned", "status") if k in res}
        hits = res.get("hits")
        if isinstance(hits, list):
            info["hits"] = len(hits)
        age_h = (now - (row["run_at_epoch"] or 0)) / 3600
        print(f"  {row['cache_key']:<26} saved {row['run_at']}  ({age_h:5.1f}h ago)  {info}")

    print("\n== backend functions the dashboard calls ==")
    os.environ.setdefault("PSX_DISABLE_SCAN_AUTOREFRESH", "1")
    import app  # noqa: E402  (no startup loops: those only run under uvicorn)
    fire = app._run_fire_scan()
    print(f"  /patterns/fire-scan    -> date={fire.get('date')} hits={len(fire.get('hits', []))} "
          f"top={[h['symbol'] for h in fire.get('hits', [])[:5]]}")
    wy = app._run_wyckoff_scan()
    print(f"  /patterns/wyckoff-scan -> date={wy.get('date')} hits={len(wy.get('hits', []))}")
    mw = app.market_watch()
    as_of = sorted({r.get('as_of') for r in mw if r.get('as_of')})
    print(f"  /market                -> {len(mw)} rows, as_of={as_of or 'live PSX quotes'}")
    turso_db.print_usage_report(label="check_dashboard_data")


if __name__ == "__main__":
    main()
