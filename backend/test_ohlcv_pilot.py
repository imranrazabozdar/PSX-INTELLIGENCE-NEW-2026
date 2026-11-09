import sqlite3
from datetime import datetime, timezone
import pytest
import ohlcv_pilot as p

HTML = """<table id="historicalTable"><tbody>
<tr><td>Nov 6, 2026</td><td>1.0</td><td>2.0</td><td>0.5</td><td>1.5</td><td>1,000</td></tr>
<tr><td>Nov 9, 2026</td><td>1.5</td><td>2.5</td><td>1.0</td><td>2.0</td><td>500</td></tr>
</tbody></table>"""


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
    c = sqlite3.connect(":memory:")
    rows = p._parse_historical_table(HTML, "APL")
    p.ingest(c, rows); p.ingest(c, rows)
    assert c.execute("select count(*) from market_bars").fetchone()[0] == 2


def test_dry_run_no_network(monkeypatch):
    monkeypatch.setattr(p.requests, "post", lambda *a, **k: pytest.fail("network"))
    assert p.run(False)["requests"] == 0


def test_live_jitter_and_cap(monkeypatch):
    s = S(); monkeypatch.setattr(p.requests, "post", s.post)
    sleeps = []
    c = sqlite3.connect(":memory:")
    out = p.run(True, c, sleep=sleeps.append)
    assert out["requests"] == 4 and len(sleeps) == 3
    assert all(3.5 <= x <= 8.5 for x in sleeps)
