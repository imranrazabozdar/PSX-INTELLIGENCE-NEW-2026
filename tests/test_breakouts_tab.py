"""Breakouts tab (Phase D Breakout & Shelf Tracker): renders on the deployed
Streamlit pin, summary metrics match the scan, the table keeps its order and
click-to-open, and the Patterns tab block is byte-identical to main."""
import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
HITS = [   # deliberately NOT in display order
    {"symbol": "OGDC", "signal_type": "ACTIVE_SHELF", "rvol": 0.8, "turnover_pkr": 9000000.0, "close": 250.0,
     "shelf_days": 4, "pct_change": -0.5, "base_or_shelf_high": 255.0, "up_down_vol_ratio": 1.9, "ignition_date": "2026-11-16"},
    {"symbol": "LUCK", "signal_type": "SOS_IGNITION", "rvol": 6.0, "turnover_pkr": 90000000.0, "close": 800.0,
     "shelf_days": 0, "pct_change": 6.0, "base_or_shelf_high": 790.0, "up_down_vol_ratio": None, "ignition_date": "2026-11-20"},
    {"symbol": "NBP", "signal_type": "ACTIVE_SHELF", "rvol": 0.63, "turnover_pkr": 404649683.0, "close": 175.9,
     "shelf_days": 11, "pct_change": 1.53, "base_or_shelf_high": 180.25, "up_down_vol_ratio": 2.0, "ignition_date": "2026-11-04",
     "ema20": 172.4, "ignition_floor": 160.1},
    {"symbol": "PASL", "signal_type": "SHELF_BREAKOUT", "rvol": 3.1, "turnover_pkr": 61234567.0, "close": 2.15,
     "shelf_days": 9, "pct_change": 7.5, "base_or_shelf_high": 2.0, "up_down_vol_ratio": 2.2, "ignition_date": "2026-11-09"},
    {"symbol": "HUBC", "signal_type": "ACTIVE_SHELF", "rvol": 0.7, "turnover_pkr": 8000000.0, "close": 150.0,
     "shelf_days": 6, "pct_change": 0.2, "base_or_shelf_high": 152.0, "up_down_vol_ratio": 2.4, "ignition_date": "2026-11-12"},
    {"symbol": "EFERT", "signal_type": "ACTIVE_SHELF", "rvol": 0.72, "turnover_pkr": 373286110.0, "close": 220.56,
     "shelf_days": 11, "pct_change": -0.92, "base_or_shelf_high": 224.0, "up_down_vol_ratio": 1.8, "ignition_date": "2026-11-04"},
]
ORDER = ["PASL", "EFERT", "NBP", "HUBC", "OGDC", "LUCK"]   # breakout; days 9-12 (11,11 by RVOL); days 3-8; ignition
FX = {"/patterns/phase-d-scan": {"status": "ok", "date": "2026-11-20", "scanned": 6, "_cache_age_seconds": 60,
                                 "hits": HITS},
      "/company-names": {"names": {"PASL": {"name": "Pak Aluminium"}}}}


@pytest.fixture(scope="module")
def backend():
    class H(BaseHTTPRequestHandler):
        def _s(self):
            body = FX.get(urlparse(self.path).path, {"status": "error", "reason": "not in fixture"})
            b = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        do_GET = do_POST = _s

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["PSX_BACKEND"] = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown()


def _run(backend):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=300)
    at.run()
    return at


def test_breakouts_tab_renders(backend):
    at = _run(backend)
    assert not at.exception, [e.value for e in at.exception]
    top = ["🏠 Home", "⚡ Intraday", "🔍 Screener", "📰 Pulse", "🎯 Stock Research", "🕯️ Patterns", "🚀 Breakouts",
           "⚙️ More"]
    assert [t.label for t in at.tabs if t.label in top] == top           # Breakouts right after Patterns
    tab = next(t for t in at.tabs if t.label == "🚀 Breakouts")
    m = {x.label: x.value for x in tab.metric}
    assert m == {"Shelf Breakouts": "1", "SOS Ignitions": "1", "Active Shelves": "4"}
    assert any("not a buy recommendation" in w.value for w in tab.warning)
    df = next(d for d in tab.dataframe if "phase_d_scan_table" in (d.proto.id or "")).value
    df = getattr(df, "data", df)
    assert list(df.columns)[:8] == ["symbol", "status", "price", "day %", "rvol", "ceiling", "day", "turnover"]
    assert list(df["symbol"]) == ORDER
    assert list(df["turnover"])[:3] == ["61.2M", "373.3M", "404.6M"] and list(df["day"])[1] == "11/12"
    exp = [e for e in tab.expander if "Phase D" not in e.label]
    assert [e.label.split(" ")[1] for e in exp] == ORDER                 # one checklist per stock, same order
    first = exp[0]
    md = " ".join(x.value for x in first.markdown)
    assert "Entry conditions satisfied on Fri, Nov 20" in md and "Close > **Rs. 2.00**" in md
    nbp = " ".join(x.value for x in exp[2].markdown)
    assert "Final Breakout Window (Day 11 of 12)" in nbp and "Mon, Nov 23 – Tue, Nov 24" in nbp
    assert "closes at or below Rs. 172.40 on Mon, Nov 23" in nbp and "below Rs. 135.19" in nbp
    efert = " ".join(x.value for x in exp[1].markdown)
    assert "Do not enter if price closes below its 20 EMA" in efert            # no stored levels -> generic rule
    luck = " ".join(x.value for x in exp[5].markdown)
    assert "Too early to chase" in luck and "Wed, Nov 25 (Day 3)" in luck and "Tue, Dec 8 (Day 12)" in luck
    assert any(b.key == "phase_d_open_NBP" for b in tab.button)
    # auto-expanded: top stock, any breakout, Day 10-12 shelves; Day 3-8 shelves and ignitions start collapsed
    assert [e.proto.expanded for e in exp] == [True, True, True, False, False, False]
    assert any("View Rules & Metrics for Phase D" in e.label for e in tab.expander)
    # Phase D appears nowhere in the Patterns tab
    pat = next(t for t in at.tabs if t.label == "🕯️ Patterns")
    assert not any("phase_d" in (d.proto.id or "") for d in pat.dataframe)
    assert not any("Phase D" in str(getattr(x, "value", "")) for x in pat.markdown)


def test_row_click_opens_stock_research(backend):
    at = _run(backend)
    tab = next(t for t in at.tabs if t.label == "🚀 Breakouts")
    d = next(d for d in tab.dataframe if "phase_d_scan_table" in (d.proto.id or ""))
    at.session_state[d.key or d.proto.id.split("-", 2)[-1]] = {"selection": {"rows": [1], "columns": [], "cells": []}}
    at.run()
    assert at.session_state["research_symbol"] == ORDER[1]
    next(b for b in at.button if b.key == "phase_d_open_LUCK").click().run()
    assert at.session_state["research_symbol"] == "LUCK"


def test_patterns_tab_block_unchanged_vs_main():
    main = subprocess.run(["git", "show", "origin/main:streamlit_app.py"], cwd=ROOT, capture_output=True,
                          text=True).stdout
    here = (ROOT / "streamlit_app.py").read_text()

    def block(src):
        a = src.index("with tab_patterns:")
        b = src.index("# ---------------------------------------------------------------- More ----")
        cut = src.find("# ----------------------------------------------------------- Breakouts ----", a)
        return src[a:cut if cut != -1 else b]
    assert block(here) == block(main)


def test_priority_sort_and_weekend_dates_unit():
    import phase_d_ui as P
    assert [h["symbol"] for h in P.sort_hits(HITS)] == ORDER
    assert P.add_trading_days("2026-11-20", 1).isoformat() == "2026-11-23"      # Fri -> Mon
    assert P.add_trading_days("2026-11-20", 3).isoformat() == "2026-11-25"
    assert P.add_trading_days("2026-11-20", 12).isoformat() == "2026-12-08"
    dates, verdict = P.watch({"signal_type": "ACTIVE_SHELF", "shelf_days": 11}, "2026-11-20")
    assert "Mon, Nov 23 – Tue, Nov 24" in dates and "Day 11 of 12" in verdict
    assert P.fmt_turnover(404649683) == "404.6M" and P.fmt_turnover(4863226) == "4.9M"


def test_badges_string_and_blank_for_older_rows():
    import phase_d_ui as P
    assert P.badges({"coil_dryup": 1, "w1_leader": 0, "exhausted_pre_ign": 1}) == "COIL·EXH"
    assert P.badges({"coil_dryup": 0, "w1_leader": 1, "exhausted_pre_ign": 0}) == "1W"
    assert P.badges({}) == "" and P.badges({"coil_dryup": None, "w1_leader": None}) == ""   # pre-badge rows
    df = P.rows({"hits": [dict(HITS[3], setup_grade="A+ PRIME", price_tier="SWEET_SPOT", coil_dryup=1,
                               w1_leader=0, exhausted_pre_ign=0), HITS[0]]}, {})
    assert list(df.columns)[:8] == ["symbol", "status", "price", "day %", "rvol", "ceiling", "day", "turnover"]
    assert list(df["setup_grade"]) == ["A+ PRIME", ""] and list(df["badges"]) == ["COIL", ""]
