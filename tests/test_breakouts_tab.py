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
HITS = [
    {"symbol": "PASL", "signal_type": "SHELF_BREAKOUT", "rvol": 3.1, "turnover_pkr": 61234567.0, "close": 2.15,
     "shelf_days": 9, "pct_change": 7.5, "base_or_shelf_high": 2.0, "up_down_vol_ratio": 2.2, "ignition_date": "2026-10-14"},
    {"symbol": "LUCK", "signal_type": "SOS_IGNITION", "rvol": 6.0, "turnover_pkr": 90000000.0, "close": 800.0,
     "shelf_days": 0, "pct_change": 6.0, "base_or_shelf_high": 790.0, "up_down_vol_ratio": None, "ignition_date": "2026-10-28"},
    {"symbol": "OGDC", "signal_type": "ACTIVE_SHELF", "rvol": 0.8, "turnover_pkr": 9000000.0, "close": 250.0,
     "shelf_days": 4, "pct_change": -0.5, "base_or_shelf_high": 255.0, "up_down_vol_ratio": 1.9, "ignition_date": "2026-10-22"},
    {"symbol": "HUBC", "signal_type": "ACTIVE_SHELF", "rvol": 0.7, "turnover_pkr": 8000000.0, "close": 150.0,
     "shelf_days": 6, "pct_change": 0.2, "base_or_shelf_high": 152.0, "up_down_vol_ratio": 2.4, "ignition_date": "2026-10-20"},
]
FX = {"/patterns/phase-d-scan": {"status": "ok", "date": "2026-10-28", "scanned": 4, "_cache_age_seconds": 60,
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
    assert m == {"Shelf Breakouts": "1", "SOS Ignitions": "1", "Active Shelves": "2"}
    assert any("not a buy recommendation" in w.value for w in tab.warning)
    df = next(d for d in tab.dataframe if "phase_d_scan_table" in (d.proto.id or "")).value
    df = getattr(df, "data", df)
    assert list(df.columns) == ["symbol", "company", "signal", "rvol", "turnover", "price", "shelf days"]
    assert list(df["symbol"]) == ["PASL", "LUCK", "OGDC", "HUBC"]       # endpoint order kept
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
