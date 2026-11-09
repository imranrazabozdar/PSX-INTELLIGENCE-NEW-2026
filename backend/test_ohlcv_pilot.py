import os
import sqlite3
from datetime import datetime, timezone
import pytest
import ohlcv_pilot as p

SCHEMA = open(os.path.join(os.path.dirname(__file__), "fixtures", "market_bars_schema.sql")).read()
# 2026-11-05, 06, 09 at 00:00Z
PAYLOAD = {"s": "ok", "t": [1793836800, 1793923200, 1794182400], "o": [1, 2, 3], "h": [2, 3, 4],
           "l": [0.5, 1, 2], "c": [1.5, 2.5, 3.5], "v": [10, 20, 30]}


def db():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    c.execute("INSERT INTO sources(source_id,name,source_type,created_at_utc,updated_at_utc) "
              "VALUES('scs_chart','x','data_provider','t','t')")
    return c


class R:
    def raise_for_status(self): pass
    def json(self): return PAYLOAD


class S:
    def __init__(self): self.calls = []
    def get(self, url, **kw): self.calls.append((url, kw)); return R()


NOW = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)


def test_params():
    assert p.SYMBOLS == ["APL", "BAHL", "PACE", "DFML"] and p.ROW_CAP == 500 and p.TRADING_DAYS == 30
    assert (p.JITTER_MIN, p.JITTER_MAX) == (3.5, 8.5)


def test_ua_and_cap():
    b, s = p.RequestBudget(1), S()
    p.fetch_symbol("APL", b, s)
    assert s.calls[0][1]["headers"]["User-Agent"] == p.USER_AGENT
    with pytest.raises(RuntimeError):
        p.fetch_symbol("BAHL", b, s)


def test_drops_current_session_and_limits_30():
    rows = p.parse_udf(PAYLOAD, "APL")
    assert [r["date"] for r in rows] == ["2026-11-05", "2026-11-06", "2026-11-09"]
    assert [r["date"] for r in p.drop_undelayed(rows, NOW)] == ["2026-11-05", "2026-11-06"]
    many = [{"date": f"2026-01-{i:02d}"} for i in range(1, 31)] * 2
    assert len(p.last_n(many)) == 30


def test_ingest_or_ignore_and_provenance():
    c = db()
    rows = p.drop_undelayed(p.parse_udf(PAYLOAD, "APL"), NOW)
    assert p.ingest(c, rows, 1) == 2
    assert p.ingest(c, rows, 1) == 0
    assert c.execute("select count(*) from market_bars").fetchone()[0] == 2
    assert c.execute("select count(*) from collector_runs where job=?", (p.APPROVAL_ID,)).fetchone()[0] == 2
    r = c.execute("select source_id,timeframe,bar_start_utc,session_date_pkt,collection_run_id from market_bars order by 3 limit 1").fetchone()
    assert r == ("scs_chart", "1d", "2026-11-05T00:00:00Z", "2026-11-05", 1)
    assert c.execute("select count(*) from sources").fetchone()[0] == 1


def test_no_overwrite():
    c = db(); rows = p.drop_undelayed(p.parse_udf(PAYLOAD, "APL"), NOW)
    p.ingest(c, rows)
    c.execute("update market_bars set close=1.1 where session_date_pkt='2026-11-05'")
    p.ingest(c, rows)
    assert c.execute("select close from market_bars where session_date_pkt='2026-11-05'").fetchone()[0] == 1.1


def test_row_cap_and_missing_source():
    c = db()
    with pytest.raises(RuntimeError):
        p.ingest(c, [{}] * 501)
    c2 = sqlite3.connect(":memory:"); c2.executescript(SCHEMA)
    with pytest.raises(RuntimeError):
        p.ingest(c2, [])


def test_dry_run_no_network(monkeypatch):
    monkeypatch.setattr(p.requests, "get", lambda *a, **k: pytest.fail("network"))
    assert p.run(False)["requests"] == 0


def test_live_jitter(monkeypatch):
    sleeps = []
    out = p.run(True, db(), sleep=sleeps.append, session=S())
    assert out["requests"] == 4 and len(sleeps) == 3 and all(3.5 <= x <= 8.5 for x in sleeps)
