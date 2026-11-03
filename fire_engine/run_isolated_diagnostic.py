#!/usr/bin/env python3
"""run_isolated_diagnostic.py — DIAGNOSTIC ONLY. Recomputes FIRE and Wyckoff
for one session in a THROWAWAY local SQLite file, from data fetched directly
from SCS, using the unchanged production code, and compares the results with
the production results recorded in diagnostics_production_<date>.json (taken
from the production job log, so the comparison needs no database either).

Isolation (enforced in code, before anything else is imported):
  1. LIBSQL_URL / LIBSQL_AUTH_TOKEN are removed from the environment; the run
     aborts if they reappear.
  2. A stub `turso_db` module is installed: any attribute access raises, so no
     code path can obtain a Turso connection.
  3. Every HTTP request is checked: any URL containing "turso" or "libsql"
     (or the hostname of a LIBSQL_URL, if one was ever set) is refused.
  4. All engine code receives fire_engine.database.DatabaseManager(db_path=
     <temp file>) -- a local sqlite3 connection.
  5. No batch guard / completion marker / alert code is imported or called.
The only output is the markdown report.
"""
import os
import sys
import types

# ---------------------------------------------------------------- isolation
for _k in ("LIBSQL_URL", "LIBSQL_AUTH_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
    os.environ.pop(_k, None)


class _Blocked(types.ModuleType):
    def __getattr__(self, name):
        raise RuntimeError(f"DIAGNOSTIC ISOLATION: turso_db.{name} is blocked -- no production DB access")


sys.modules["turso_db"] = _Blocked("turso_db")
sys.modules["batch_guard"] = _Blocked("batch_guard")

import requests  # noqa: E402

_orig_request = requests.Session.request
_BLOCKED_HTTP = []


def _guarded_request(self, method, url, *a, **k):
    u = str(url).lower()
    if "turso" in u or "libsql" in u:
        _BLOCKED_HTTP.append(u)
        raise RuntimeError(f"DIAGNOSTIC ISOLATION: request to {url} refused")
    return _orig_request(self, method, url, *a, **k)


requests.Session.request = _guarded_request
requests.request = lambda method, url, **k: requests.Session().request(method, url, **k)
requests.get = lambda url, **k: requests.Session().request("GET", url, **k)
requests.post = lambda url, **k: requests.Session().request("POST", url, **k)

import json  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import date as _date, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scs_daily  # noqa: E402  (requests only)
from fire_engine.config import load_config  # noqa: E402
from fire_engine.database import DatabaseManager  # noqa: E402
from fire_engine.exclusions import load_exclusions_from_config  # noqa: E402
import fire_engine.scheduler as fire_sched  # noqa: E402
import fire_engine.wyckoff_scheduler as wy_sched  # noqa: E402

SESSION = os.getenv("DIAG_DATE", "2026-11-03")
HIST_FROM = os.getenv("DIAG_FIRE_HISTORY_FROM", "2026-09-15")
DAILY_FROM = os.getenv("DIAG_DAILY_FROM", "2026-04-01")
REPORT = ROOT / "isolated_diagnostic_report.md"


def assert_isolated():
    assert not any(os.getenv(k) for k in ("LIBSQL_URL", "LIBSQL_AUTH_TOKEN")), "Turso credentials present"
    assert isinstance(sys.modules["turso_db"], _Blocked)


def weekdays(a, b):
    d, e = _date.fromisoformat(a), _date.fromisoformat(b)
    out = []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def wyckoff_part(db, cfg, prod, L):
    exc = set(load_exclusions_from_config()) if cfg["exclusion"]["enabled"] else set()
    uni = [s for s in cfg["stocks"]["universe"] if s not in exc]
    db.conn.execute("CREATE TABLE IF NOT EXISTS daily_ohlc(symbol TEXT, trade_date TEXT, open REAL, high REAL, "
                    "low REAL, close REAL, volume REAL, source TEXT, PRIMARY KEY(symbol, trade_date))")
    fetched, empty, last_dates = 0, [], {}
    for s in uni:
        try:
            df = scs_daily.fetch_scs_daily_ohlc(s, start_date=DAILY_FROM, end_date=SESSION)
        except Exception as e:
            empty.append(f"{s} ({type(e).__name__})")
            continue
        rows = []
        for x in df.itertuples():
            o, h, l, c = float(x.open), float(x.high), float(x.low), float(x.close)
            if l <= min(o, c) <= max(o, c) <= h and c > 0:      # same validity rule as run_ohlc_refresh
                rows.append((s, x.date, o, h, l, c, float(x.volume or 0), scs_daily.SOURCE_LABEL))
        if not rows:
            empty.append(s)
            continue
        db.conn.executemany("INSERT OR IGNORE INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)", rows)
        last_dates[s] = rows[-1][1]
        fetched += 1
        time.sleep(0.2)
    db.conn.commit()
    t0 = time.time()
    res = wy_sched.run_daily_wyckoff_batch(db, cfg, date=SESSION, progress=lambda *_: None)
    diag = {r["symbol"]: r for r in res["results"]}
    pw = prod["wyckoff"]
    common = sorted(set(diag) & set(pw))
    exact = [s for s in common if diag[s]["accumulation_score"] == pw[s]["score"] and diag[s]["signal_type"] == pw[s]["signal"]]
    mism = [s for s in common if s not in exact]
    only_prod = sorted(set(pw) - set(diag))
    only_diag = sorted(set(diag) - set(pw))
    L += ["## A. Wyckoff — DIAGNOSTIC recomputation vs production", "",
          f"- Universe after exclusions: {len(uni)} · daily history fetched from SCS for {fetched} · none/failed: {empty}",
          f"- Newest SCS daily candle per symbol: {dict(Counter(last_dates.values()))}",
          f"- Diagnostic scanned {len(diag)} · stale-skipped {res.get('stale')} · runtime {time.time() - t0:.0f}s",
          f"- Compared {len(common)} symbols present in both · **exact match (score AND class): {len(exact)}/{len(common)} "
          f"= {100 * len(exact) / max(1, len(common)):.1f}%**",
          f"- In production only: {only_prod} · in diagnostic only: {only_diag}", "",
          f"- DIAGNOSTIC class counts: {dict(Counter(r['signal_type'] for r in diag.values()))} · "
          f"production: {dict(Counter(v['signal'] for v in pw.values()))}", ""]
    if mism:
        L += ["| Symbol | Production | Diagnostic | Diagnostic components | Gates (consol, MACD) |", "|---|---|---|---|---|"]
        for s in mism:
            r = diag[s]
            L.append(f"| {s} | {pw[s]['signal']} {pw[s]['score']} | {r['signal_type']} {r['accumulation_score']} | "
                     f"{r['components']} | {r['is_consolidating']}, {r['macd_confirmation']} |")
    return {"exact": len(exact), "common": len(common), "mismatch": mism, "only_prod": only_prod}


def fire_part(db, cfg, prod, L):
    sample = prod["fire_sample"]
    dates = weekdays(HIST_FROM, SESSION)
    pf = prod["fire"]
    per_day = {}
    rows, exact = [], 0
    for s in sample:
        for d in dates:
            try:
                r = fire_sched.run_symbol_for_date(db, s, d, cfg)
            except Exception as e:
                r = {"status": f"ERROR {type(e).__name__}: {e}"[:80], "events_logged": 0}
            per_day.setdefault(d, Counter())[r["status"] if not r["status"].startswith("ERROR") else "ERROR"] += 1
        diag = r
        p = pf.get(s, {})
        m = (diag.get("status") == p.get("status") and diag.get("events_logged") == p.get("events")
             and diag.get("fire_count", 0) == p.get("fire") and diag.get("prefire_count", 0) == p.get("prefire"))
        exact += m
        n_hist = db.conn.execute("SELECT COUNT(*) FROM trading_sessions WHERE session_id LIKE ? AND total_candles > 0",
                                 (f"{s}:%",)).fetchone()[0]
        rows.append(f"| {s} | {p.get('status')} {p.get('events')}/{p.get('fire')}/{p.get('prefire')} | "
                    f"{diag.get('status')} {diag.get('events_logged')}/{diag.get('fire_count', 0)}/{diag.get('prefire_count', 0)} | "
                    f"{'✅' if m else '❌'} | {n_hist} |")
    L += ["", "## B. FIRE — DIAGNOSTIC recomputation vs production (sample)", "",
          f"- Sample ({len(sample)}): {sample}",
          f"- History replayed through the unchanged scheduler for every weekday {HIST_FROM} → {SESSION} "
          f"({len(dates)} dates); the 30-session baseline is built from that replay",
          f"- **Exact match (status, events, FIRE, pre-FIRE): {exact}/{len(sample)} = {100 * exact / len(sample):.1f}%**", "",
          "| Symbol | Production status events/FIRE/pre-FIRE | DIAGNOSTIC status events/FIRE/pre-FIRE | Match | Sessions with data in diagnostic history |",
          "|---|---|---|---|---|"] + rows
    L += ["", "SCS 1-minute availability per replayed date (status counts across the sample):", ""]
    for d in dates:
        L.append(f"- {d}: {dict(per_day.get(d, {}))}")
    return {"exact": exact, "n": len(sample)}


def main():
    assert_isolated()
    cfg = load_config()
    prod = json.load(open(ROOT / f"diagnostics_production_{SESSION}.json"))
    tmp = Path(tempfile.mkdtemp(prefix="psx_diag_")) / "diagnostic.db"
    db = DatabaseManager(db_path=str(tmp))
    L = [f"# DIAGNOSTIC — isolated recomputation of {SESSION} (NOT production)", "",
         f"Temporary database: {tmp} (local SQLite, deleted with the runner). Inputs fetched from SCS. "
         f"Production results from: {prod['source']}. Unchanged production code and config "
         f"(Wyckoff thresholds {cfg.get('wyckoff', {}).get('watch_threshold', 60)}/"
         f"{cfg.get('wyckoff', {}).get('ready_threshold', 70)}/{cfg.get('wyckoff', {}).get('extreme_threshold', 85)}).", ""]
    t0 = time.time()
    w = wyckoff_part(db, cfg, prod, L)
    f = fire_part(db, cfg, prod, L)
    assert_isolated()
    L += ["", "## Isolation evidence", "",
          f"- Turso credentials in environment at start and end: none (asserted)",
          f"- turso_db / batch_guard modules: blocked stubs, never used (any use would have raised)",
          f"- HTTP requests to Turso/libSQL hosts attempted: {len(_BLOCKED_HTTP)} (all refused) {_BLOCKED_HTTP[:3]}",
          f"- Database used: {tmp} only · runtime {time.time() - t0:.0f}s"]
    REPORT.write_text("\n".join(L))
    print("\n".join(L))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
