"""One test group per approved audit correction (see the audit report)."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import batch_guard
import volatility_engine as ve
import run_volatility_backtest as bt


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def _df(n=400, seed=0, start="2024-01-01"):
    r = np.random.default_rng(seed).normal(0, 0.02, n)
    c = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame({"trade_date": pd.bdate_range(start, periods=n).strftime("%Y-%m-%d"), "open": c,
                         "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6})


# 1. one authoritative run per session ------------------------------------
def test_guard_marks_and_skips_only_completed_session():
    c = _conn()
    assert not batch_guard.already_done("fire_batch", "2026-11-03", c)
    batch_guard.mark_done("fire_batch", "2026-11-03", "ok", c)
    assert batch_guard.already_done("fire_batch", "2026-11-03", c)
    assert not batch_guard.already_done("fire_batch", "2026-11-04", c)        # next session runs
    assert not batch_guard.already_done("wyckoff_batch", "2026-11-03", c)     # per-job markers
    batch_guard.mark_done("fire_batch", "2026-11-03", "retry", c)            # idempotent re-mark
    assert c.execute("SELECT COUNT(*) FROM batch_runs").fetchone()[0] == 1


def test_guard_fails_open_when_db_unreadable():
    class Broken:
        def execute(self, *a):
            raise RuntimeError("db down")
    assert batch_guard.already_done("fire_batch", "2026-11-03", Broken()) is False


def test_workflows_queue_overlapping_triggers():
    import yaml
    for f in ("fire_engine_daily_batch.yml", "refresh_chart_patterns.yml"):
        y = yaml.safe_load(open(ROOT / ".github" / "workflows" / f))
        assert y["concurrency"]["cancel-in-progress"] is False


# 2. alerts persist across a same-session re-run --------------------------
def _row(sym, stage, det, d="2026-11-03", **k):
    base = {"symbol": sym, "stage": stage, "stage_detail": det, "stage_dir": k.get("dir", 0), "bbw_pct100": 4,
            "compression_score": 80, "bull_score": 30, "bear_score": 30, "bull_expansion_score": 0,
            "bear_expansion_score": 0, "liquidity": "Liquid", "mtf_alignment": "x", "hist": {}, "date": d,
            "last_bar_date": d}
    return base


def test_same_session_rerun_keeps_alerts_and_next_session_compares_to_previous():
    prev_session = {"session": "2026-11-02", "rows": [_row("A", 1, "Early compression", "2026-11-02")]}
    today = [_row("A", 2, "Advanced squeeze")]
    b1 = ve.alert_baseline(prev_session, "2026-11-03")
    first = ve.build_alerts(today, b1["kinds"])
    stored = {"session": "2026-11-03", "rows": today, "alert_baseline": b1, "alerts": first}
    b2 = ve.alert_baseline(stored, "2026-11-03")                      # second trigger, same session
    assert b2 == b1 and ve.build_alerts(today, b2["kinds"]) == first and len(first) == 1
    b3 = ve.alert_baseline(stored, "2026-11-04")                      # next session
    assert b3["session"] == "2026-11-03" and ve.build_alerts(today, b3["kinds"]) == []


# 3. calendar + latest-candle validation ----------------------------------
def test_calendar_fresh_fraction(tmp_path):
    p = tmp_path / "s.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE daily_ohlc(symbol TEXT, trade_date TEXT)")
    c.executemany("INSERT INTO daily_ohlc VALUES(?,?)", [("A", "2026-11-03"), ("B", "2026-11-03"), ("C", "2026-11-02")])
    c.commit()
    frac, last = batch_guard.fresh_fraction(str(p), "2026-11-03")
    assert frac == pytest.approx(2 / 3) and last["C"] == "2026-11-02"
    assert batch_guard.fresh_fraction(str(p), "2026-11-04")[0] == 0            # holiday: nobody has a bar


def test_wyckoff_skips_stale_symbols_and_stores_nothing_for_them(tmp_path):
    from fire_engine.database import DatabaseManager
    from fire_engine.config import load_config
    import fire_engine.wyckoff_scheduler as ws
    db = DatabaseManager(db_path=str(tmp_path / "w.db"))
    db.conn.execute("CREATE TABLE IF NOT EXISTS daily_ohlc(symbol TEXT, trade_date TEXT, open REAL, high REAL, "
                    "low REAL, close REAL, volume REAL, source TEXT, PRIMARY KEY(symbol,trade_date))")
    for sym, n in (("AAA", 120), ("BBB", 119)):                       # BBB is missing the last session
        d = _df(120, 1).iloc[:n]
        db.conn.executemany("INSERT INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)",
                            [(sym, r.trade_date, r.open, r.high, r.low, r.close, r.volume, "t") for r in d.itertuples()])
    db.conn.commit()
    cfg = load_config()
    cfg["stocks"]["universe"] = ["AAA", "BBB"]
    cfg["exclusion"]["enabled"] = False
    orig = ws.fetch_daily_and_4h
    ws.fetch_daily_and_4h = lambda db_, s, end_date=None, **k: (orig.__globals__["load_daily_df"](db_, s, end_date), None)
    try:
        date = _df(120, 1)["trade_date"].iloc[-1]
        res = ws.run_daily_wyckoff_batch(db, cfg, date=date, progress=lambda *_: None)
    finally:
        ws.fetch_daily_and_4h = orig
    assert [r["symbol"] for r in res["results"]] == ["AAA"]
    assert res["stale"] == [{"symbol": "BBB", "last_bar": _df(120, 1)["trade_date"].iloc[-2]}]
    stored = [r[0] for r in db.conn.execute("SELECT symbol FROM wyckoff_accumulation").fetchall()]
    assert stored == ["AAA"]


def test_volatility_marks_stale_rows_and_keeps_them_out_of_alerts():
    data = {"A": _df(400, 1).to_dict("records"), "B": _df(400, 2).iloc[:-3].to_dict("records")}
    res, _ = ve.analyze_universe(data, {})
    by = {r["symbol"]: r for r in res["rows"]}
    assert not by["A"]["stale"] and by["B"]["stale"]
    assert all(a["symbol"] != "B" for a in res["alerts"])
    assert res["stale_symbols"][0]["symbol"] == "B"


# 4. last stored candle re-fetched and corrected ---------------------------
def test_ohlc_refresh_corrects_only_the_last_stored_bar(monkeypatch):
    import run_ohlc_refresh as ro
    c = _conn()
    c.execute("CREATE TABLE daily_ohlc(symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, "
              "volume REAL, source TEXT, PRIMARY KEY(symbol, trade_date))")
    rows = [("AAA", "2026-10-30", 10, 11, 9, 10, 100, "s"), ("AAA", "2026-11-02", 10, 11, 9, 10.5, 50, "s"),
            ("BBB", "2026-10-30", 10, 11, 9, 10, 100, "s"), ("BBB", "2026-11-02", 10, 11, 9, 10, 100, "s")]
    c.executemany("INSERT INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)", rows)
    c.commit()

    def fake_fetch(sym, start_date=None, end_date=None):
        assert start_date == "2026-11-02"                          # re-fetch starts AT the last stored day
        last = {"AAA": (10, 11.2, 9, 10.8, 180), "BBB": (13, 14, 12, 13.5, 100)}[sym]   # BBB: +35% -> re-basing
        return pd.DataFrame([{"date": "2026-10-30", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
                             dict(zip(("date", "open", "high", "low", "close", "volume"), ("2026-11-02",) + last)),
                             {"date": "2026-11-03", "open": 10.8, "high": 11, "low": 10.5, "close": 10.9, "volume": 90}])
    monkeypatch.setattr(ro, "load_universe_symbols", lambda: ["AAA", "BBB"])
    monkeypatch.setattr(ro.turso_db, "get_connection", lambda: c)
    monkeypatch.setattr(ro.turso_db, "USING_TURSO", False)
    monkeypatch.setattr(ro.scs_daily, "fetch_scs_daily_ohlc", fake_fetch)
    monkeypatch.setattr(ro.time, "sleep", lambda *_: None)
    ro.main()
    get = lambda s, d: tuple(c.execute("SELECT close, volume FROM daily_ohlc WHERE symbol=? AND trade_date=?", (s, d)).fetchone())
    assert get("AAA", "2026-11-02") == (10.8, 180)           # corrected
    assert get("AAA", "2026-10-30") == (10, 100)             # history untouched (not overwritten by the 1.0 row)
    assert get("BBB", "2026-11-02") == (10, 100)             # >11% change = possible re-basing, kept
    assert get("AAA", "2026-11-03") == (10.9, 90)            # new bar inserted
    assert c.execute("SELECT COUNT(*) FROM daily_ohlc").fetchone()[0] == 6


# 5. universe alignment ----------------------------------------------------
def test_universe_alignment_excludes_and_reports_unavailable():
    data = {s: _df(400, i).to_dict("records") for i, s in enumerate(("A", "B", "X"))}
    res, _ = ve.analyze_universe(data, {}, universe=["A", "B", "X", "ECPL"], excluded=["X"])
    assert sorted(r["symbol"] for r in res["rows"]) == ["A", "B"]
    assert res["excluded"] == ["X"]
    assert res["unavailable"] == [{"symbol": "ECPL", "reason": "no price data in daily_ohlc"}]
    assert all(r["symbol"] != "ECPL" for r in res["alerts"])


def test_configured_universe_matches_fire_config():
    uni, exc = ve.configured_universe()
    assert len(uni) == 150 and set(exc) <= set(uni)


# 6. 4-hour cache cannot leak future candles into a backfill ----------------
def test_4h_cache_respects_end_date(tmp_path):
    from fire_engine.database import DatabaseManager
    from fire_engine import wyckoff_data_fetcher as wf
    db = DatabaseManager(db_path=str(tmp_path / "c.db"))
    db.ensure_stock("AAA")
    for d in ("2026-10-20", "2026-10-21", "2026-10-22"):
        for h in ("09:00:00", "13:00:00"):
            db.conn.execute("INSERT INTO ohlcv_4h(symbol, datetime, date, time_of_day, open, high, low, close, volume) "
                            "VALUES('AAA',?,?,?,1,1,1,1,1)", (f"{d} {h}", d, h[:5]))
    db.conn.commit()
    out = wf.load_4h_df(db, "AAA", "2026-10-21")
    assert out.index.max() < pd.Timestamp("2026-10-22")
    assert len(wf.load_4h_df(db, "AAA", "2026-10-22")) == 6


# 7. backtest execution / counting / clustered CIs ---------------------------
def _frame(close, opens=None, lows=None, highs=None):
    close = np.asarray(close, float)
    o = close if opens is None else np.asarray(opens, float)
    df = pd.DataFrame({"trade_date": pd.bdate_range("2024-01-01", periods=len(close)), "open": o,
                       "high": np.maximum(o, close) if highs is None else highs,
                       "low": np.minimum(o, close) if lows is None else lows, "close": close, "volume": 1e6})
    return ve.compute_frame(df)


def test_long_entry_into_upper_circuit_lock_is_unfilled():
    c = np.full(60, 100.0)
    c[31:] = 110.0                                     # day 31 opens and stays locked at +10%
    d = _frame(c, opens=c, lows=c, highs=c)
    f = bt.forward(d, 30, atrp=2.0)
    assert f["long_fix"][0] == "unfilled" and f["short_fix"][0] != "unfilled"


def test_gap_through_stop_fills_at_open():
    c = np.full(60, 100.0)
    o = c.copy()
    o[33] = 90.0
    c[33:] = 90.0                                      # gaps 10% below a 4% stop
    d = _frame(c, opens=o)
    res, bars, ret = bt.forward(d, 30, atrp=2.0)["long_fix"]
    assert res == "stop" and ret == pytest.approx(-0.10)


def test_cluster_ci_is_wider_when_signals_share_dates():
    flags = [1] * 30 + [0] * 30
    spread = bt.cluster_ci(flags, list(range(60)))
    clustered = bt.cluster_ci(flags, [0] * 30 + [1] * 30)
    assert (clustered[1] - clustered[0]) > (spread[1] - spread[0])


def test_diagnostic_counts_consecutive_upper_circuits_once_and_applies_exclusions():
    import fire_engine.run_wyckoff_diagnostic as dg
    from fire_engine.wyckoff_detector import WyckoffDetector
    c = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, 200)))
    for i in (150, 151, 152):                           # three consecutive locked upper circuits
        c[i:] *= 1.10
    df = pd.DataFrame({"open": c, "high": c, "low": c * 0.99, "close": c, "volume": 1e6},
                      index=pd.bdate_range("2024-01-01", periods=200))
    _, _, ucd, _ = dg.replay({"AAA": df}, WyckoffDetector(), 0.10)
    assert len(ucd) == 1 and ucd[0]["consecutive_locks"] == 3


# 8. Bollinger population std ------------------------------------------------
def test_bollinger_population_std_matches_reference():
    df = _df(300, 4)
    d = ve.compute_frame(df)
    w = df["close"].to_numpy()[-20:]
    assert d["BB_up"].iloc[-1] == pytest.approx(w.mean() + 2 * w.std(ddof=0), rel=1e-12)
    d1 = ve.compute_frame(df, ve.cfg_with({"bb_ddof": 1}))
    assert d1["BB_up"].iloc[-1] == pytest.approx(w.mean() + 2 * w.std(ddof=1), rel=1e-12)


# 10. experimental OBV variant (research only) --------------------------------
def test_live_variant_reproduces_production_scanner_on_260_bar_windows():
    import obv_mfi_scanner as om
    import compare_obv_mfi_variants as cmp
    rng = np.random.default_rng(5)
    n = 700
    ret = rng.normal(0, 0.02, n)
    ret[rng.integers(300, n, 10)] += 0.09
    c = 100 * np.exp(np.cumsum(ret))
    v = rng.lognormal(13, 0.5, n)
    v[ret > 0.06] *= 6
    df = pd.DataFrame({"trade_date": pd.bdate_range("2021-01-01", periods=n), "open": c * (1 - ret / 3),
                       "high": c * 1.01, "low": c * 0.99, "close": c, "volume": v})
    d = om.add_indicators(om._normalise(df))
    fast = {t for t, _ in cmp.signals(d, "P-live")}
    slow = {t for t in range(300, n) if om.scan_obv_mfi_setup(df.iloc[t - 259:t + 1])}
    assert {t for t in fast if t >= 300} == slow
    import obv_mfi_scanner_experimental as ox
    fe = {t for t, _ in cmp.signals(d, "E-slope")}
    assert {t for t in range(300, n) if ox.scan_obv_mfi_setup(df.iloc[:t + 1])} == {t for t in fe if t >= 300}
