"""Equivalence + safety tests for the standalone Wyckoff 1.0 workflow.

The separated workflow runs the SAME runner (fire_engine.run_wyckoff_batch ->
wyckoff_scheduler.run_daily_wyckoff_batch -> WyckoffDetector) and the SAME
merge (run_volatility_wyckoff_merge.merge_and_save). The only data-path
difference is that daily_ohlc SELECTs are answered from the refresh run's
local snapshot (turso_db's existing routing) instead of Turso. These tests
run the real code twice on identical inputs through a fake Turso HTTP
endpoint -- once reading Turso, once with the snapshot -- and require
byte-identical wyckoff_accumulation rows and combined-view rows.
"""
import base64
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import turso_db  # noqa: E402
from fire_engine import wyckoff_data_fetcher, wyckoff_pipeline_gate  # noqa: E402
from fire_engine.config import load_config  # noqa: E402
from fire_engine.database import DatabaseManager  # noqa: E402
from fire_engine.wyckoff_scheduler import run_daily_wyckoff_batch  # noqa: E402

SESSION = "2026-11-03"
FIRE_TABLES = ("market_candles", "fire_events", "volume_baseline", "daily_reports")


# ------------------------------------------------------------ fake Turso --
def _cell(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


def _arg(a):
    t = a["type"]
    return None if t == "null" else int(a["value"]) if t == "integer" else \
        float(a["value"]) if t == "float" else a["value"]


class FakeTurso(turso_db._TursoConnection):
    """_TursoConnection whose HTTP pipeline executes against a local sqlite
    file -- every real code path (snapshot routing, cursors, batch_query,
    decoding) runs unchanged."""

    def __init__(self, path):
        self._remote = sqlite3.connect(path)
        self._query_cache = {}
        self.sql_log = []

    def _post(self, reqs, max_retries=4):
        out = []
        for r in reqs:
            sql = r["stmt"]["sql"]
            args = [_arg(a) for a in r["stmt"].get("args", [])]
            self.sql_log.append(sql)
            cur = self._remote.execute(sql, args)
            rows = cur.fetchall()
            self._remote.commit()
            cols = [d[0] for d in (cur.description or [])]
            out.append({"type": "ok", "response": {"type": "execute", "result": {
                "cols": [{"name": c} for c in cols], "rows": [[_cell(v) for v in row] for row in rows],
                "affected_row_count": cur.rowcount, "last_insert_rowid": str(cur.lastrowid or 0)}}})
        return {"results": out}


# --------------------------------------------------------------- fixtures --
def _daily_rows(symbols, n=260, last_date=SESSION):
    """Mixed regimes. Even symbols end in a quiet accumulation base (tight
    range, high-volume narrow up days, dry down days, OBV rising against a
    flat price) so WATCH/READY/EXTREME signals and their gates are exercised."""
    import pandas as pd
    dates = pd.bdate_range(end=last_date, periods=n).strftime("%Y-%m-%d").tolist()
    rows = []
    for k, s in enumerate(symbols):
        rng = np.random.default_rng(1000 + k)
        price = base = 50 + 10 * k
        acc = k % 2 == 0
        for i, d in enumerate(dates):
            in_base = acc and i >= n - 45
            if in_base:
                up = i % 2 == 0
                c = base * (1 + (0.006 if up else -0.006) + rng.normal(0, 0.001))
                o = price
                h, lo = max(o, c) * 1.002, min(o, c) * 0.998
                v = float(int(1_000_000 * ((2.2 + rng.random() * 0.5) if up and i % 6 == 0
                                           else (0.25 if not up else 0.9))))
            else:
                vol = [0.02, 0.012, 0.03][k % 3]
                c = price * (1 + rng.normal(-0.001 if acc else 0.001, vol))
                o = price
                h = max(o, c) * (1 + abs(rng.normal(0, vol / 2)))
                lo = min(o, c) * (1 - abs(rng.normal(0, vol / 2)))
                v = float(int(rng.integers(300_000, 2_000_000)))
                base = c
            rows.append((s, d, round(o, 3), round(h, 3), round(lo, 3), round(c, 3), v, "scs"))
            price = c
    return rows


def _fake_4h(symbol, end_date, lookback_days=30, **kw):
    import pandas as pd
    rng = np.random.default_rng(abs(hash(symbol)) % 2**32)
    out, price = [], 100.0
    for d in pd.bdate_range(end=end_date, periods=22).strftime("%Y-%m-%d"):
        for t in ("09:00", "13:00"):
            c = price * (1 + rng.normal(0, 0.002 if int(symbol[1:]) % 2 == 0 else 0.02))
            out.append({"datetime": f"{d} {t}:00", "date": d, "time_of_day": t, "open": price,
                        "high": max(price, c) * 1.003, "low": min(price, c) * 0.997, "close": c,
                        "volume": int(rng.integers(10_000, 500_000))})
            price = c
    return out


@pytest.fixture
def world(tmp_path, monkeypatch):
    symbols = [f"T{k:02d}" for k in range(16)]
    rows = _daily_rows(symbols)
    rows = [r for r in rows if not (r[0] == "T14" and r[1] == SESSION)]   # stale symbol
    rows = [r for r in rows if r[0] != "T15" or r[1] >= "2026-10-20"]      # thin history
    base = tmp_path / "remote.db"
    c = sqlite3.connect(base)
    c.execute("CREATE TABLE daily_ohlc(symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, "
              "close REAL, volume REAL, source TEXT, PRIMARY KEY(symbol, trade_date))")
    c.executemany("INSERT INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)", rows)
    c.execute("CREATE TABLE analysis_cache(cache_key TEXT PRIMARY KEY, run_at TEXT, run_at_epoch REAL, "
              "result_json TEXT)")
    c.commit()
    c.close()
    snap = tmp_path / "snapshot.db"
    shutil.copy(base, snap)   # the refresh run's snapshot holds the same daily_ohlc
    cfg = load_config()
    cfg["stocks"]["universe"] = symbols
    cfg["exclusion"]["enabled"] = False
    monkeypatch.setattr(wyckoff_data_fetcher, "fetch_4h_ohlcv", _fake_4h)
    return {"base": base, "snap": snap, "cfg": cfg, "tmp": tmp_path}


def _run(world, name, use_snapshot, monkeypatch):
    db_path = world["tmp"] / f"{name}.db"
    shutil.copy(world["base"], db_path)
    monkeypatch.setattr(turso_db, "_SNAPSHOT_PATH", str(world["snap"]) if use_snapshot else None)
    monkeypatch.setitem(turso_db._snapshot, "conn", None)
    monkeypatch.setitem(turso_db._snapshot, "disabled", False)
    conn = FakeTurso(db_path)
    db = DatabaseManager(conn=conn)
    result = run_daily_wyckoff_batch(db, world["cfg"], date=SESSION, progress=lambda m: None)
    cols = [r[1] for r in conn._remote.execute("PRAGMA table_info(wyckoff_accumulation)")]
    keep = [c for c in cols if c not in ("id", "scan_id", "created_at")]
    out = conn._remote.execute(f"SELECT {', '.join(keep)} FROM wyckoff_accumulation "
                               "ORDER BY symbol").fetchall()
    return conn, result, keep, out


def test_wyckoff_identical_with_snapshot(world, monkeypatch):
    c_a, res_a, cols, rows_a = _run(world, "turso", False, monkeypatch)
    c_b, res_b, _, rows_b = _run(world, "snap", True, monkeypatch)
    assert len(rows_a) == 14 and rows_a == rows_b                     # every column, exact
    assert [s["symbol"] for s in res_a["stale"]] == [s["symbol"] for s in res_b["stale"]] == ["T14"]
    assert res_a["stocks_with_signal"] == res_b["stocks_with_signal"]
    assert "T15" not in {r[cols.index("symbol")] for r in rows_a}    # insufficient history skipped
    # snapshot run: zero daily_ohlc statements reached "Turso"
    reads = lambda c: [s for s in c.sql_log if s.lstrip().upper().startswith("SELECT") and "FROM daily_ohlc" in s]
    assert reads(c_b) == []
    assert len(reads(c_a)) == 16
    for conn in (c_a, c_b):   # no FIRE table rows written
        for t in FIRE_TABLES:
            n = conn._remote.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            assert n == 0, t
        assert not [s for s in conn.sql_log if re.match(r"\s*(INSERT|UPDATE|DELETE)\b.*\b(" +
                                                        "|".join(FIRE_TABLES) + r")\b", s, re.S | re.I)]


def test_combined_view_identical(world, monkeypatch):
    from fire_engine.run_volatility_wyckoff_merge import merge_and_save
    combos = []
    for name, snap in (("ta", False), ("tb", True)):
        conn, *_ = _run(world, name, snap, monkeypatch)
        vol = {"session": SESSION, "rows": [
            {"symbol": f"T{k:02d}", "classification": ["EXPANSION", "COMPRESSION", "NORMAL"][k % 3],
             "last_bar_date": SESSION if k != 14 else "2026-11-02", "stale": k == 14,
             "liquidity": "OK", "volume_state": "HIGH", "date": SESSION if k != 14 else "2026-11-02",
             "stage": 1 + k % 5, "stage_dir": (k % 3) - 1, "bull_score": 10 * (k % 7),
             "bear_score": 9 * (k % 5), "compression_score": 5 * k} for k in range(16)]}
        conn.execute("INSERT INTO analysis_cache VALUES(?,?,?,?)",
                     ("volatility_engine_scan", "2026-11-03T12:00:00", 0.0, json.dumps(vol)))
        combo = merge_and_save(conn, log=lambda m: None)
        combos.append(combo)
    assert combos[0] == combos[1] and combos[0]["wyckoff_date"] == SESSION
    assert combos[0]["n_wyckoff"] == 14 and any(r["confluence"] for r in combos[0]["rows"]) \
        and any(r["conflict"] for r in combos[0]["rows"])


def _gate(conn, stage):
    out = []
    import builtins
    orig = builtins.print
    builtins.print = lambda *a, **k: out.append(" ".join(map(str, a)))
    try:
        wyckoff_pipeline_gate.main([stage, "--date", SESSION], conn=conn)
    finally:
        builtins.print = orig
    return dict(x.split("=", 1) for x in out if re.match(r"^(run|session)=", x))["run"]


def test_gates(world, monkeypatch):
    import batch_guard
    conn = FakeTurso(world["base"])
    assert _gate(conn, "wyckoff") == "false"                 # refresh not done / holiday
    assert _gate(conn, "merge") == "false"
    batch_guard.mark_done("chart_refresh", SESSION, conn=conn)
    conn._query_cache.clear()
    assert _gate(conn, "wyckoff") == "true"
    # Wyckoff failed: no marker -> combined view must not be refreshed
    assert _gate(conn, "merge") == "false"
    batch_guard.mark_done("wyckoff_batch", SESSION, conn=conn)
    conn._query_cache.clear()
    assert _gate(conn, "wyckoff") == "false"                 # duplicate trigger -> no-op
    conn._remote.execute("CREATE TABLE IF NOT EXISTS wyckoff_accumulation(scan_date TEXT)")
    conn._remote.execute("INSERT INTO wyckoff_accumulation VALUES(?)", (SESSION,))
    conn._remote.execute("INSERT INTO analysis_cache VALUES('volatility_engine_scan','x',0,?)",
                         (json.dumps({"session": "2026-11-02"}),))
    conn._remote.commit()
    conn._query_cache.clear()
    assert _gate(conn, "merge") == "false"                   # Volatility stale
    conn._remote.execute("UPDATE analysis_cache SET result_json=? WHERE cache_key='volatility_engine_scan'",
                         (json.dumps({"session": SESSION}),))
    conn._remote.commit()
    conn._query_cache.clear()
    assert _gate(conn, "merge") == "true"


def test_gate_fails_closed_on_db_error():
    class Broken:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("down")
    assert _gate(Broken(), "wyckoff") == "false"
    assert _gate(Broken(), "merge") == "false"


def test_workflows_never_invoke_fire():
    wf = ROOT / ".github" / "workflows"
    fire_entry = re.compile(r"run_daily_batch|fire_engine\.scheduler|fire_engine_daily_batch\.yml")
    offenders = []
    for f in wf.glob("*.yml"):
        if f.name == "fire_engine_daily_batch.yml":
            continue
        for line in f.read_text().splitlines():
            code = line.split("#", 1)[0]
            if fire_entry.search(code):
                offenders.append(f"{f.name}: {line.strip()}")
    assert offenders == []
    w = (wf / "wyckoff_daily.yml").read_text()
    assert "schedule:" not in w and "workflows: [\"Refresh pattern scans (daily after market close)\"]" in w
    assert "--retention-days 35" in w


def test_retry_is_idempotent(world, monkeypatch):
    conn, _, cols, first = _run(world, "retry", True, monkeypatch)
    db = DatabaseManager(conn=conn)
    run_daily_wyckoff_batch(db, world["cfg"], date=SESSION, progress=lambda m: None)   # retry / duplicate
    again = conn._remote.execute(f"SELECT {', '.join(cols)} FROM wyckoff_accumulation ORDER BY symbol").fetchall()
    assert again == first
    assert conn._remote.execute("SELECT COUNT(*) FROM wyckoff_scans").fetchone()[0] == 1
