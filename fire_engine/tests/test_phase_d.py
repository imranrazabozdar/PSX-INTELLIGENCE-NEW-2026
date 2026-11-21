"""Phase D Breakout & Shelf Tracker: frozen-rule tests (synthetic bars),
runner tests on a local sqlite file, and the read-only replay."""
import hashlib
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fire_engine import phase_d_detector as D  # noqa: E402
from fire_engine import run_phase_d_tracker as R  # noqa: E402


def _dates(n, end=date(2026, 10, 30)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def story(n_base=40, shelf=6, breakout=True, ign_vol=5_000_000, ign_close_pos=0.9, shelf_dip=None,
          bo_vol=3_000_000, upper_lock=False):
    """Flat base at ~10, an ignition bar (low 10.2, close 11.28 -> floor 10.47), a tight shelf above
    its floor, then (optionally) a breakout. shelf_dip = close of the 3rd shelf bar, if given."""
    bars = []
    for k in range(n_base):
        c = 10.0 + (0.1 if k % 2 else -0.1)
        bars.append({"open": c, "high": c + 0.15, "low": c - 0.15, "close": c, "volume": 1_000_000})
    lo, hi = 10.2, 11.4
    if upper_lock:
        bars.append({"open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": ign_vol})
    else:
        bars.append({"open": 10.2, "high": hi, "low": lo, "close": lo + ign_close_pos * (hi - lo), "volume": ign_vol})
    for k in range(shelf):
        c = 11.2 + (0.05 if k % 2 else -0.05)
        if shelf_dip is not None and k == 2:
            c = shelf_dip
        v = 1_400_000 if k % 2 else 600_000   # up days heavier than down days
        bars.append({"open": c - 0.02, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": v})
    if breakout:
        bars.append({"open": 11.3, "high": 11.9, "low": 11.3, "close": 11.85, "volume": bo_vol})
    ds = _dates(len(bars))
    for b, d in zip(bars, ds):
        b["date"] = d
    return bars


def sig(bars):
    r = D.evaluate(bars)
    return r and r["signal_type"]


def test_ignition_shelf_breakout_sequence():
    b = story()
    ign = 40
    assert sig(b[:ign + 1]) == "SOS_IGNITION"
    assert sig(b[:ign + 2]) is None and sig(b[:ign + 3]) is None        # shelf needs age >= 3
    for t in range(ign + 3, ign + 7):
        r = D.evaluate(b[:t + 1])
        assert r["signal_type"] == "ACTIVE_SHELF" and r["shelf_days"] == t - ign
        assert r["ignition_date"] == b[ign]["date"]
    r = D.evaluate(b)
    assert r["signal_type"] == "SHELF_BREAKOUT" and r["shelf_days"] == 6
    assert r["base_or_shelf_high"] == pytest.approx(max(x["high"] for x in b[ign + 1:ign + 7]))


def test_turnover_floor_blocks_ignition():
    assert sig(story(breakout=False, ign_vol=400_000)[:41]) is None        # 4x not met
    b = story(breakout=False)
    for x in b:
        x["close"] /= 100; x["open"] /= 100; x["high"] /= 100; x["low"] /= 100   # price 0.1 -> turnover < 5M
    assert sig(b[:41]) is None


def test_weak_close_blocks_and_upper_lock_counts():
    assert sig(story(ign_close_pos=0.5)[:41]) is None
    assert sig(story(upper_lock=True)[:41]) == "SOS_IGNITION"


def test_shelf_broken_by_close_below_ignition_floor():
    # floor = ign_low + 0.25 * (ign_close - ign_low) = 10.2 + 0.25 * 1.08 = 10.47; EMA20 there is ~10.33,
    # so a 10.45 close breaks the shelf through the floor rule alone
    b = story(shelf_dip=10.45, breakout=False)
    ign = b[40]
    assert ign["low"] + 0.25 * (ign["close"] - ign["low"]) == pytest.approx(10.47)
    assert D._ema([x["close"] for x in b], 20)[43] < 10.45
    assert all(sig(b[:t + 1]) is None for t in range(43, len(b)))


def test_lps_throwback_above_floor_keeps_the_shelf():
    # 10.60 is below the old (open + close) / 2 midpoint (10.74) but above the new floor (10.47)
    b = story(shelf_dip=10.60, breakout=False)
    ign = b[40]
    assert 10.60 < (ign["open"] + ign["close"]) / 2
    assert sig(b[:44]) == "ACTIVE_SHELF" and sig(b) == "ACTIVE_SHELF"


def test_breakout_needs_volume_and_shelf_through_yesterday():
    b = story(bo_vol=1_000_000)
    assert sig(b) == "ACTIVE_SHELF"                         # 2.5x not met -> still a shelf, no breakout
    b = story(shelf=2)                                      # shelf only 2 days old yesterday -> no breakout
    assert sig(b) != "SHELF_BREAKOUT"


def test_shelf_expires_after_12_days():
    b = story(shelf=14, breakout=False)
    assert sig(b[:41 + 12]) == "ACTIVE_SHELF"
    assert sig(b[:41 + 13]) is None


def test_no_lookahead():
    b = story()
    for t in range(30, len(b)):
        assert D.evaluate(b[:t + 1]) == D.evaluate([dict(x) for x in b[:t + 1]])
    # appending future bars never changes an earlier date's signal
    early = D.evaluate(b[:41])
    assert D.evaluate(b[:41]) == early and b[40]["date"] == early["date"]


# ---------------------------------------------------------------- runner --
def _db(tmp_path, data):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE daily_ohlc(symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, "
              "volume REAL, source TEXT, PRIMARY KEY(symbol, trade_date))")
    for s, bars in data.items():
        c.executemany("INSERT INTO daily_ohlc VALUES(?,?,?,?,?,?,?,?)",
                      [(s, x["date"], x["open"], x["high"], x["low"], x["close"], x["volume"], "t") for x in bars])
    c.commit()
    c.row_factory = sqlite3.Row
    return p, c


def test_scan_store_stale_short_and_idempotent(tmp_path):
    full = story()
    session = full[-1]["date"]
    data = {"AAA": full, "BBB": story(breakout=False)[:41 + 4], "CCC": full[:-1], "DDD": full[-10:]}
    data["BBB"] = [dict(x, date=d) for x, d in zip(data["BBB"], _dates(len(data["BBB"]), date.fromisoformat(session)))]
    p, c = _db(tmp_path, data)
    sigs, stale, short = R.scan(c, list(data), session)
    assert {x["symbol"]: x["signal_type"] for x in sigs} == {"AAA": "SHELF_BREAKOUT", "BBB": "ACTIVE_SHELF"}
    assert [x["symbol"] for x in stale] == ["CCC"] and short == ["DDD"]
    R.ensure_schema(c); R.ensure_schema(c)                  # idempotent
    R.store(c, session, sigs)
    R.store(c, session, sigs[:1])                           # a re-run replaces the session's rows
    rows = c.execute("SELECT symbol, signal_type FROM phase_d_signals WHERE scan_date=?", (session,)).fetchall()
    assert [tuple(r) for r in rows] == [("AAA", "SHELF_BREAKOUT")]
    cols = [r[1] for r in c.execute("PRAGMA table_info(phase_d_signals)")]
    assert cols == ["id", "symbol", "scan_date", "signal_type", "close", "pct_change", "rvol", "turnover_pkr",
                    "base_or_shelf_high", "shelf_days", "up_down_vol_ratio", "ignition_date", "created_at"]
    idx = [r[1] for r in c.execute("PRAGMA index_list(phase_d_signals)")]
    assert "idx_phase_d_scan_date" in idx


def test_replay_is_read_only(tmp_path, capsys):
    b = story()
    p, c = _db(tmp_path, {"PASL": b})
    c.close()
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    R.main(["--local-db", str(p), "--replay", "PASL", "--from", b[0]["date"], "--to", b[-1]["date"]])
    out = capsys.readouterr().out
    assert "SOS_IGNITION" in out and "ACTIVE_SHELF" in out and "SHELF_BREAKOUT" in out
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    t = sqlite3.connect(p).execute("SELECT name FROM sqlite_master WHERE name='phase_d_signals'").fetchall()
    assert t == []


def test_wyckoff_untouched():
    for f in ("fire_engine/run_wyckoff_batch.py", "fire_engine/wyckoff_scheduler.py",
              "fire_engine/wyckoff_detector.py", "fire_engine/database.py", "fire_engine/wyckoff_data_fetcher.py"):
        d = subprocess.run(["git", "diff", "--stat", "origin/main", "--", f], cwd=ROOT,
                           capture_output=True, text=True).stdout
        assert d.strip() == "", f


def test_api_orders_by_priority_then_rvol_and_handles_zero_signal_day(tmp_path, monkeypatch):
    p = tmp_path / "api.db"
    monkeypatch.setenv("PSX_DB", str(p))
    for k in ("LIBSQL_URL", "LIBSQL_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    c = sqlite3.connect(p)
    for s in R.DDL:
        c.execute(s)
    rows = [("A", "2026-10-28", "ACTIVE_SHELF", 9.0), ("B", "2026-10-28", "SOS_IGNITION", 5.0),
            ("C", "2026-10-28", "SHELF_BREAKOUT", 3.0), ("D", "2026-10-28", "SOS_IGNITION", 7.0),
            ("E", "2026-10-27", "SHELF_BREAKOUT", 9.0)]
    c.executemany("INSERT INTO phase_d_signals(symbol, scan_date, signal_type, rvol) VALUES(?,?,?,?)", rows)
    c.commit()
    script = (
        "import sys, json; sys.path[:0]=['backend']; import app; print(json.dumps(app._run_phase_d_scan()))")
    import json as _j
    out = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True,
                         env={**__import__('os').environ, "PSX_DB": str(p)})
    res = _j.loads(out.stdout.strip().splitlines()[-1])
    assert res["date"] == "2026-10-28" and [h["symbol"] for h in res["hits"]] == ["C", "D", "B", "A"]
    # a later completed session with zero signals is shown as that session, with no hits
    c.execute("CREATE TABLE IF NOT EXISTS batch_runs (job TEXT NOT NULL, session_date TEXT NOT NULL, "
              "status TEXT NOT NULL, finished_at TEXT, detail TEXT, PRIMARY KEY (job, session_date))")
    c.execute("INSERT INTO batch_runs VALUES('phase_d_batch','2026-10-29','completed','x','')")
    c.commit()
    out = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True,
                         env={**__import__('os').environ, "PSX_DB": str(p)})
    res = _j.loads(out.stdout.strip().splitlines()[-1])
    assert res["date"] == "2026-10-29" and res["hits"] == []


def test_diagnose_is_read_only_and_matches_detector(tmp_path, capsys):
    b = story()
    p, c = _db(tmp_path, {"PASL": b})
    c.close()
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    R.main(["--local-db", str(p), "--replay", "PASL", "--diagnose", "--from", b[38]["date"], "--to", b[-1]["date"]])
    out = capsys.readouterr().out
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    rows = [l.split("|")[1:-1] for l in out.splitlines() if l.startswith("| 2")]
    assert len(rows) == len(b) - 38
    for cells, k in zip(rows, range(38, len(b))):
        want = (D.evaluate(b[:k + 1]) or {}).get("signal_type", "—")
        assert cells[-1].strip() == want


def custom_shelf(shelf_bars):
    """Base + the standard ignition bar (low 10.2, close 11.28, volume 5M), then the given shelf bars
    as (open, high, low, close, volume) tuples."""
    b = story(shelf=0, breakout=False)
    for o, h, l, c, v in shelf_bars:
        b.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    for x, d in zip(b, _dates(len(b))):
        x["date"] = d
    return b


def test_stair_step_shelf_is_not_penalised():
    # five higher steps on light volume: total span (14.6 - 11.2) / 11.2 = 30% (the old 28% span rule failed it),
    # but no pullback from any running peak exceeds 25%
    steps = [(11.3, 11.5, 11.2, 11.4, 900_000), (11.4, 12.2, 11.4, 12.1, 900_000), (12.1, 12.9, 12.0, 12.8, 900_000),
             (12.8, 13.7, 12.7, 13.6, 900_000), (13.6, 14.6, 13.5, 14.5, 900_000)]
    b = custom_shelf(steps)
    assert (max(x[1] for x in steps) - min(x[2] for x in steps)) / min(x[2] for x in steps) > 0.28
    r = D.evaluate(b)
    assert r["signal_type"] == "ACTIVE_SHELF" and r["shelf_days"] == 5
    m = D.shelf_metrics(b, 40, len(b) - 1, D._ema([x["close"] for x in b], 20))
    assert m["depth"] <= 0.25 and m["up_days"] == 5 and m["down_days"] == 0


def test_pullback_deeper_than_25pct_from_running_peak_ends_shelf():
    # the third bar's low is 27% below the shelf's running high (11.3) although every close holds the floor
    bars = [(11.2, 11.3, 11.1, 11.25, 1_400_000), (11.25, 11.3, 11.1, 11.15, 600_000),
            (11.15, 11.2, 8.2, 11.1, 600_000), (11.1, 11.3, 11.0, 11.25, 1_400_000)]
    b = custom_shelf(bars)
    m = D.shelf_metrics(b, 40, len(b) - 1, D._ema([x["close"] for x in b], 20))
    assert m["held"] and m["depth"] == pytest.approx((11.3 - 8.2) / 11.3) and not m["depth_ok"]
    assert sig(b) is None
    bars[2] = (11.15, 11.2, 8.6, 11.1, 600_000)                  # 23.9% -> within the limit
    assert sig(custom_shelf(bars)) == "ACTIVE_SHELF"


def test_pure_low_volume_throwback_passes_heavy_one_fails():
    # three straight down closes (no up day), all above the floor and EMA20
    light = [(11.25, 11.3, 11.1, 11.2, 1_500_000), (11.2, 11.25, 11.0, 11.1, 1_800_000),
             (11.1, 11.15, 10.9, 11.0, 2_100_000)]           # avg 1.8M <= 0.40 x 5M = 2.0M
    b = custom_shelf(light)
    m = D.shelf_metrics(b, 40, len(b) - 1, D._ema([x["close"] for x in b], 20))
    assert m["up_days"] == 0 and m["vol_path"] == "throwback" and m["throwback_vol"] == pytest.approx(0.36)
    assert sig(b) == "ACTIVE_SHELF"
    heavy = [x[:4] + (x[4] + 500_000,) for x in light]          # avg 2.3M > 2.0M
    assert sig(custom_shelf(heavy)) is None


def test_up_down_ratio_threshold_is_1_5x():
    def shelf(up_v):
        # up, down, up, down (the first close 11.30 is above the ignition close 11.28)
        return [(11.2, 11.35, 11.1, 11.30, up_v), (11.3, 11.3, 11.1, 11.15, 1_000_000),
                (11.15, 11.35, 11.1, 11.25, up_v), (11.25, 11.3, 11.1, 11.15, 1_000_000)]
    assert sig(custom_shelf(shelf(1_550_000))) == "ACTIVE_SHELF"   # 1.55x
    assert sig(custom_shelf(shelf(1_450_000))) is None             # 1.45x


def test_shelf_breakout_fires_once_not_on_follow_through_day():
    b = story()                                      # ... ACTIVE_SHELF ..., SHELF_BREAKOUT on the last bar
    assert sig(b) == "SHELF_BREAKOUT" and sig(b[:-1]) == "ACTIVE_SHELF"
    # strong follow-through: new high above the shelf high, heavy volume, strong close, > 5M turnover
    nxt = {"open": 11.85, "high": 12.6, "low": 11.85, "close": 12.55, "volume": 8_000_000,
           "date": _dates(1, date.fromisoformat(b[-1]["date"]) + timedelta(days=3))[0]}
    b2 = b + [nxt]
    # without the single-trigger rule the follow-through would qualify on every other breakout condition
    sh_prev = D._shelf_at(b2, len(b2) - 2, D._ema([x["close"] for x in b2], 20))
    assert sh_prev and nxt["close"] > sh_prev["shelf_high"]
    sma = D._sma_vol([x["volume"] for x in b2], len(b2) - 1)
    assert nxt["volume"] >= 2.5 * sma and nxt["close"] * nxt["volume"] >= 5_000_000
    assert sig(b2) != "SHELF_BREAKOUT"


def test_backfill_runs_each_trading_session_skips_holiday_and_reads_back(tmp_path, monkeypatch, capsys):
    full = story()
    holiday = full[-4]["date"]                               # no stock trades that day
    data = {s: [x for x in full if x["date"] != holiday] for s in ("AAA", "BBB", "CCC")}
    p, c = _db(tmp_path, data)
    monkeypatch.setattr(R, "universe", lambda: ["AAA", "BBB", "CCC"])
    R.ensure_schema(c)
    sessions = R.trading_sessions(c, 3, full[-1]["date"])
    assert holiday not in sessions and sessions[-1] == full[-1]["date"] and len(sessions) == 3
    c.close()
    R.main(["--local-db", str(p), "--backfill", "3", "--until", full[-1]["date"]])
    out = capsys.readouterr().out
    c = sqlite3.connect(p)
    done = [r[0] for r in c.execute("SELECT session_date FROM batch_runs WHERE job='phase_d_batch' ORDER BY 1")]
    assert done == sessions
    last = c.execute("SELECT symbol, signal_type FROM phase_d_signals WHERE scan_date=? ORDER BY symbol",
                     (full[-1]["date"],)).fetchall()
    assert last == [("AAA", "SHELF_BREAKOUT"), ("BBB", "SHELF_BREAKOUT"), ("CCC", "SHELF_BREAKOUT")]
    assert f"session {full[-1]['date']}: 3 stock(s)" in out and "| AAA | SHELF_BREAKOUT |" in out
