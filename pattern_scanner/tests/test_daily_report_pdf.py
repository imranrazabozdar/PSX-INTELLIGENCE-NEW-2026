"""Tests for analysis/daily_report_pdf.py: synthetic rows only, no database."""
import importlib.util
import json
import os
import sqlite3
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("daily_report_pdf", os.path.join(ROOT, "analysis", "daily_report_pdf.py"))
rpt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rpt)


def _section(n):
    rows = [{"symbol": f"SYM{i}", "signal_type": "SHELF_BREAKOUT" if i % 2 else "SOS_IGNITION",
             "grade": "A" if i % 3 else "B", "close": 10.5 + i, "note": "x" * 20} for i in range(n)]
    return rpt._section("Breakouts", "Phase D", "Synthetic breakouts", rows, "synthetic")


def test_pdf_starts_with_header_and_has_date_in_filename():
    with tempfile.TemporaryDirectory() as d:
        name = rpt.report_filename("2026-11-25")
        assert name == "PSX_Daily_Report_2026-11-25.pdf"
        path, pages, size = rpt.render_pdf(os.path.join(d, name), "2026-11-25", [_section(20)],
                                           generated_at="2026-11-26 06:00 UTC")
        with open(path, "rb") as f:
            assert f.read(5) == b"%PDF-"
        assert pages >= 2


def test_500_rows_under_1mb():
    with tempfile.TemporaryDirectory() as d:
        path, pages, size = rpt.render_pdf(os.path.join(d, "r.pdf"), "2026-11-25", [_section(500)],
                                           generated_at="2026-11-26 06:00 UTC")
        assert size < 1024 * 1024
        assert pages > 5


def test_fire_rows_are_dropped():
    rows = [{"symbol": "A", "signal_type": "FIRE_ENTRY"}, {"symbol": "B", "signal_type": "SOS_IGNITION"}]
    s = rpt._section("Breakouts", "Phase D", "t", rows, "src")
    assert [r["symbol"] for r in s["rows"]] == ["B"]
    assert s["excluded_fire"] == 1


def _local_db_with(tmp):
    path = os.path.join(tmp, "s.db")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE daily_ohlc (symbol TEXT, trade_date TEXT, open REAL, high REAL, low REAL,
                                 close REAL, volume REAL);
        CREATE TABLE phase_d_signals (symbol TEXT, scan_date TEXT, signal_type TEXT, grade TEXT);
        CREATE TABLE wyckoff_accumulation (symbol TEXT, scan_date TEXT, accumulation_score REAL);
        CREATE TABLE analysis_cache (cache_key TEXT, run_at TEXT, result_json TEXT);
        INSERT INTO daily_ohlc VALUES ('AAA', '2026-11-24', 10, 11, 9, 10.5, 1000),
                                      ('AAA', '2026-11-26', 10.5, 11, 10, 10.8, 1200);
        INSERT INTO phase_d_signals VALUES ('AAA', '2026-11-24', 'SOS_IGNITION', 'A'),
                                           ('BBB', '2026-11-26', 'SHELF_BREAKOUT', 'B');
        INSERT INTO wyckoff_accumulation VALUES ('AAA', '2026-11-24', 5.0), ('BBB', '2026-11-26', 6.0);
    """)
    c.commit()
    c.close()
    return path


def test_session_date_option_pins_session_and_scan_dates():
    with tempfile.TemporaryDirectory() as d:
        db = _local_db_with(d)
        conn = rpt.ReadOnlyConnection(_connect(db))
        session, sections = rpt.collect_sections(conn, session_date="2026-11-25")
        assert session == "2026-11-25"
        assert rpt.report_filename(session) == "PSX_Daily_Report_2026-11-25.pdf"
        pd = [s for s in sections if s["group"] == "Breakouts"][0]
        assert "2026-11-25" in pd["title"]
        assert pd["rows"] == []  # no phase_d rows for that scan date
        wy = [s for s in sections if s["sub"] == "Market Behaviour"][0]
        assert "2026-11-25" in wy["title"]


def test_session_date_default_unchanged_uses_max():
    with tempfile.TemporaryDirectory() as d:
        db = _local_db_with(d)
        conn = rpt.ReadOnlyConnection(_connect(db))
        session, sections = rpt.collect_sections(conn)
        assert session == "2026-11-26"
        pd = [s for s in sections if s["group"] == "Breakouts"][0]
        assert [r["Symbol"] for r in pd["rows"]] == ["BBB"]


def test_headings_order_chart_patterns_patterns_breakouts():
    with tempfile.TemporaryDirectory() as d:
        conn = rpt.ReadOnlyConnection(_connect(_local_db_with(d)))
        _, sections = rpt.collect_sections(conn, session_date="2026-11-25")
        tree = rpt.heading_tree(sections)
        assert [g for g, _ in tree] == ["Chart Patterns", "Patterns", "Breakouts"]
        patterns_subs = [sub for g, subs in tree if g == "Patterns" for sub, _ in subs]
        assert patterns_subs == ["Market Behaviour", "Long-Side (Bullish)", "Short-Side (Bearish)",
                                 "Structural Patterns", "Volatility Intelligence",
                                 "Wyckoff Institutional Accumulation 2.0 (RESEARCH)"]
        assert [g for g, _ in tree] == ["Chart Patterns", "Patterns", "Breakouts"]


def test_wyckoff_2_is_its_own_subheading_outside_long_side():
    with tempfile.TemporaryDirectory() as d:
        conn = rpt.ReadOnlyConnection(_connect(_local_db_with(d)))
        _, sections = rpt.collect_sections(conn, session_date="2026-11-25")
        w2 = [s for s in sections if s["sub"].startswith("Wyckoff Institutional Accumulation 2.0")]
        assert w2 and all(s["sub"] != "Long-Side (Bullish)" for s in w2)
        long_titles = [s["title"] for s in sections if s["sub"] == "Long-Side (Bullish)"]
        assert long_titles[0] == "OBV+MFI Setup with ATR Contraction"
        assert "Level Break Out (Resistance Breakout)" in long_titles


def test_empty_section_prints_no_rows_line():
    s = rpt._section("Patterns", "Market Behaviour", "Wyckoff", [], "x", date="2026-11-25")
    assert s["empty_text"] == "No rows for 2026-11-25" and s["rows"] == []


def test_breakouts_checklist_matches_app_wording_when_streamlit_available():
    pytest.importorskip("streamlit")
    import importlib
    pdt = importlib.import_module("pattern_scanner.phase_d_text")
    P = importlib.import_module("phase_d_ui")
    h = {"symbol": "ABC", "signal_type": "ACTIVE_SHELF", "shelf_days": 10, "ema20": 12.0,
         "ignition_floor": 11.0, "base_or_shelf_high": 14.0, "rvol": 2.0}
    assert pdt.watch(h, "2026-11-25") == P.watch(h, "2026-11-25")
    assert pdt.tier(h) == P.tier(h) and pdt.sort_hits([h]) == P.sort_hits([h])
    assert [x.replace("**", "") for x in P.invalidation(h, "2026-11-25")] == pdt.invalidation(h, "2026-11-25")


def test_chart_pattern_subheadings_confirmed_forming():
    with tempfile.TemporaryDirectory() as d:
        conn = rpt.ReadOnlyConnection(_connect(_local_db_with(d)))
        _, sections = rpt.collect_sections(conn, session_date="2026-11-25")
        tree = rpt.heading_tree(sections)
        chart_subs = [sub for g, subs in tree if g == "Chart Patterns" for sub, _ in subs]
        assert chart_subs == ["CONFIRMED", "FORMING"]


def test_wyckoff_sections_present_even_when_empty():
    with tempfile.TemporaryDirectory() as d:
        conn = rpt.ReadOnlyConnection(_connect(_local_db_with(d)))
        _, sections = rpt.collect_sections(conn, session_date="2026-11-25")
        wy_v1 = [s for s in sections if s["sub"] == "Market Behaviour"]
        wy_20 = [s for s in sections if s["sub"].startswith("Wyckoff Institutional Accumulation 2.0")]
        assert len(wy_v1) == 1 and wy_v1[0]["rows"] == []
        assert wy_v1[0]["empty_text"] == "No WATCH/READY/EXTREME setups in the most recent completed daily batch."
        assert len(wy_20) == 1 and wy_20[0]["rows"] == []
        assert wy_20[0]["empty_text"].startswith("No symbol currently shows")


def test_cache_rows_empty_rows_list_is_not_replaced_by_scalars():
    with tempfile.TemporaryDirectory() as d:
        db = _local_db_with(d)
        c = sqlite3.connect(db)
        c.execute("INSERT INTO analysis_cache VALUES ('wyckoff2_research_scan', '2026-11-25T06:00Z', "
                  "'{\"status\": \"ok\", \"label\": \"RESEARCH\", \"rows\": []}')")
        c.commit()
        c.close()
        conn = rpt.ReadOnlyConnection(_connect(db))
        _, sections = rpt.collect_sections(conn, session_date="2026-11-25")
        w2 = [s for s in sections if s["sub"].startswith("Wyckoff Institutional Accumulation 2.0")][0]
        assert w2["rows"] == [] and "Stage / Action Status" not in w2["columns"] and "Enhanced Class" in w2["columns"]


def test_pdf_renders_with_empty_wyckoff_and_chart_sections():
    with tempfile.TemporaryDirectory() as d:
        conn = rpt.ReadOnlyConnection(_connect(_local_db_with(d)))
        _, sections = rpt.collect_sections(conn, session_date="2026-11-25")
        path, pages, size = rpt.render_pdf(os.path.join(d, "t.pdf"), "2026-11-25", sections,
                                           generated_at="2026-11-26 06:00 UTC")
        with open(path, "rb") as f:
            assert f.read(5) == b"%PDF-"
        assert pages >= 3


def test_session_date_rejects_bad_format():
    with tempfile.TemporaryDirectory() as d:
        conn = rpt.ReadOnlyConnection(_connect(_local_db_with(d)))
        with pytest.raises(ValueError):
            rpt.collect_sections(conn, session_date="25/11/2026")


def _connect(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def test_read_only_guard_refuses_writes():
    guard = rpt.ReadOnlyConnection(sqlite3.connect(":memory:"))
    guard.execute("SELECT 1")
    for bad in ("DELETE FROM t", "UPDATE t SET a=1", "INSERT INTO t VALUES(1)",
                "SELECT 1; DROP TABLE t", "DROP TABLE t", "WITH x AS (SELECT 1) DELETE FROM t"):
        with pytest.raises(rpt.ReadOnlyError):
            guard.execute(bad)


def test_no_scientific_notation_in_cells():
    for v in (1e-7, 2.5e-9, 1.5e12, 3.0e20, 0.0001234, 12345.678):
        s = rpt._cell(v)
        assert "e" not in s.lower(), s
    assert rpt._cell(1234567.5) == "1,234,567.50"
    assert rpt._cell(10.0) == "10.00"
    assert rpt._cell(None) == "-"
    assert rpt._cell(True) == "Yes"


def test_candlestick_labels_and_action_values():
    names = {"AAA": "Alpha Ltd"}
    short = rpt._candle_rows([{"symbol": "AAA", "classification": "VALID_BEARISH_ENGULFING",
                               "entry_price": 10.0, "stop_loss": 10.5, "target_1": 8.0,
                               "risk_reward_measured": 3.9, "pattern_date": "2026-11-24"},
                              {"symbol": "BBB", "classification": "INVALID_BEARISH_ENGULFING"}], names, "BEAR")
    assert [r["action"] for r in short] == ["SHORT SIGNAL", "WAIT (No Setup)"]
    assert short[0]["company"] == "Alpha Ltd" and short[1]["company"] == ""
    assert short[0]["rr"] == "3.9x" and short[1]["rr"] is None
    assert [label for label, _ in rpt.SHORT_COLUMNS] == ["Symbol", "Company", "Action", "Entry",
                                                         "Stop-Loss (Risk)", "Target (Reward)", "Date"]
    assert [label for label, _ in rpt.LONG_COLUMNS] == ["Symbol", "Company", "Action", "Date", "Stop",
                                                        "Target", "R:R"]
    assert [label for label, _ in rpt.PHASE_D_COLUMNS][:2] == ["Symbol", "Stage / Action Status"]


def test_fourteen_day_filter_keeps_recent_and_undated_rows():
    rows = [{"signal_date": "2026-11-25"}, {"signal_date": "2026-11-11"}, {"signal_date": "2026-11-10"},
            {"signal_date": ""}]
    kept = rpt._recent(rows, ("signal_date",), "2026-11-25")
    assert [r["signal_date"] for r in kept] == ["2026-11-25", "2026-11-11", ""]


def test_structural_table_applies_fourteen_day_window(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        db = _local_db_with(d)
        c = sqlite3.connect(db)
        c.execute("INSERT INTO analysis_cache VALUES ('advanced_pattern_scan', '2026-11-25T10:00:00', ?)",
                  (json.dumps({"hits": [
                      {"symbol": "NEW", "pattern_type": "DOUBLE_BOTTOM", "signal_date": "2026-11-20",
                       "entry_price": 5.0, "stop_loss": 4.5, "target_1": 6.0, "risk_reward_measured": 2.0},
                      {"symbol": "OLD", "pattern_type": "INVERSE_HS", "signal_date": "2026-10-30"}]}),))
        c.commit()
        c.close()
        conn = rpt.ReadOnlyConnection(_connect(db))
        sec = rpt._structural_section(conn, {}, "2026-11-25")
        assert [r["Symbol"] for r in sec["rows"]] == ["NEW"]
        assert sec["rows"][0]["Pattern"] == "Double Bottom" and sec["rows"][0]["Action"] == "BUY SIGNAL"


def test_no_fire_or_technical_field_names_in_labels():
    labels = []
    for spec in (rpt.CHART_COLUMNS, rpt.PHASE_D_COLUMNS, rpt.WYCKOFF_V1_COLUMNS, rpt.LONG_COLUMNS,
                 rpt.SHORT_COLUMNS, rpt.STRUCTURAL_COLUMNS, rpt.EARLY_COLUMNS, rpt.EXPANSION_COLUMNS,
                 rpt.WYCKOFF_VOL_COLUMNS, rpt.VALIDATION_COLUMNS, rpt.WYCKOFF2_COLUMNS):
        labels += [label for label, _ in spec]
    assert "signal_date" not in labels and "Median20 PKR" in labels
    assert all("_" not in x or x in ("Clear_Runway %",) for x in labels)
    assert "day %" not in labels and "Day %" in labels


def test_wyckoff_v1_default_filter_is_watch_ready_extreme():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "w.db")
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        c.executescript("""
            CREATE TABLE daily_ohlc (symbol TEXT, trade_date TEXT, close REAL);
            CREATE TABLE wyckoff_accumulation (symbol TEXT, scan_date TEXT, signal_type TEXT,
                                               accumulation_score INTEGER);
            INSERT INTO daily_ohlc VALUES ('A', '2026-11-25', 7.5), ('B', '2026-11-25', 9.0), ('C', '2026-11-25', 3.0);
            INSERT INTO wyckoff_accumulation VALUES ('A', '2026-11-25', 'READY', 75),
                ('B', '2026-11-25', 'NONE', 20), ('C', '2026-11-25', 'EXTREME', 90);
        """)
        c.commit()
        c.close()
        conn = rpt.ReadOnlyConnection(_connect(path))
        sec = rpt._wyckoff_v1_section(conn, {"A": "Alpha"}, "2026-11-25", "2026-11-25")
        assert [r["Symbol"] for r in sec["rows"]] == ["C", "A"]  # score desc from the query
        assert sec["rows"][1]["Signal"] == "READY" and sec["rows"][1]["Company"] == "Alpha"
        assert sec["rows"][1]["Price"] == 7.5
        assert sec["columns"] == ["Symbol", "Company", "Signal", "Score", "Price"]


def test_pdf_renders_wide_tables_landscape_and_text():
    with tempfile.TemporaryDirectory() as d:
        cols = [(f"Col {i} long heading", [f"c{i}"]) for i in range(20)]
        rows = [{f"c{i}": f"{1234.5 * i:,.2f} value text" for i in range(20)} for _ in range(30)]
        sec = rpt._section("Patterns", "Volatility Intelligence", "Wide", rows, "synthetic", spec=cols)
        path, pages, size = rpt.render_pdf(os.path.join(d, "wide.pdf"), "2026-11-25", [sec],
                                           generated_at="2026-11-26 06:00 UTC")
        assert pages >= 2 and size < 1024 * 1024
