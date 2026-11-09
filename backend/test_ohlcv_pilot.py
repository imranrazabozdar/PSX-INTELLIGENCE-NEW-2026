import sqlite3
from datetime import datetime, timezone
import pytest
import ohlcv_pilot as p

HTML = """<table id="historicalTable"><tbody>
<tr><td>Nov 6, 2026</td><td>1.0</td><td>2.0</td><td>0.5</td><td>1.5</td><td>1,000</td></tr>
<tr><td>Nov 9, 2026</td><td>1.5</td><td>2.5</td><td>1.0</td><td>2.0</td><td>500</td></tr>
</tbody></table>"""


import os
SCHEMA = open(os.path.join(os.path.dirname(__file__), "fixtures", "market_bars_schema.sql")).read()


def db():
    c = sqlite3.connect(":memory:"); c.row_factory = None
    c.executescript(SCHEMA)
    return c


class R:
    text = HTML
    def raise_for_status(self): pass


class S:
    def __init__(self): self.calls = []
    def post(self, url, **kw): self.calls.append(kw); return R()


def test_constants():
    assert p.SYMBOLS == ["APL", "BAHL", "PACE", "DFML"] and p.REQUEST_CAP == 10
    assert (p.JITTER_MIN, p.JITTER_MAX) == (3.5, 8.5)


def test_cap_and_ua():
    b, s = p.RequestBudget(2), S()
    p.fetch_symbol("APL", b, s); p.fetch_symbol("BAHL", b, s)
    assert s.calls[0]["headers"]["User-Agent"] == p.USER_AGENT
    with pytest.raises(RuntimeError):
        p.fetch_symbol("PACE", b, s)


def test_drops_current_session():
    rows = p._parse_historical_table(HTML, "APL")
    now = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)
    assert [r["date"] for r in p.drop_undelayed(rows, now)] == ["2026-11-06"]


def test_ingest_idempotent():
    c = db()
    rows = p._parse_historical_table(HTML, "APL")
    assert p.ingest(c, rows) == 2
    assert p.ingest(c, rows) == 0  # OR IGNORE: no overwrite
    assert c.execute("select count(*) from market_bars").fetchone()[0] == 2
    assert c.execute("select count(*) from sources where source_id='psx_dps'").fetchone()[0] == 1
    assert c.execute("select count(*) from collector_runs").fetchone()[0] == 2
    r = c.execute("select timeframe,bar_start_utc,session_date_pkt,collection_run_id from market_bars order by 2 limit 1").fetchone()
    assert r == ("1d", "2026-11-06T00:00:00Z", "2026-11-06", 1)


def test_existing_source_reused_and_bars_not_overwritten():
    c = db()
    p.ensure_source(c)
    rows = p._parse_historical_table(HTML, "APL")
    p.ingest(c, rows)
    c.execute("update market_bars set close=1.1 where session_date_pkt='2026-11-06'")
    p.ingest(c, rows)
    assert c.execute("select count(*) from sources").fetchone()[0] == 1
    assert c.execute("select close from market_bars where session_date_pkt='2026-11-06'").fetchone()[0] == 1.1


def test_dry_run_no_network(monkeypatch):
    monkeypatch.setattr(p.requests, "post", lambda *a, **k: pytest.fail("network"))
    assert p.run(False)["requests"] == 0


def test_live_jitter_and_cap(monkeypatch):
    s = S(); monkeypatch.setattr(p.requests, "post", s.post)
    sleeps = []
    c = db()
    out = p.run(True, c, sleep=sleeps.append)
    assert out["requests"] == 4 and len(sleeps) == 3
    assert all(3.5 <= x <= 8.5 for x in sleeps)
