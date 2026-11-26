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
        assert pages >= 1  # empty scans are listed in the cover status bar, not printed


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


def test_badge_colours_for_buy_short_and_wait():
    assert rpt.badge_style("BUY SIGNAL")[0] == "#15803d"
    assert rpt.badge_style("SHORT SIGNAL")[0] == "#b91c1c"
    assert rpt.badge_style("WAIT")[0] == "#64748b"
    assert rpt.badge_style("  buy signal ")[0] == "#15803d"
    assert rpt.badge_style("Some other text") is None


def test_number_formatter_thousands_separators_no_scientific_notation():
    assert rpt._cell(1234567.891) == "1,234,567.89"
    assert rpt._cell(543943293.0) == "543,943,293.00"
    assert rpt._cell(12345) == "12,345"
    big = rpt._cell(1e20)
    assert "e" not in big.lower() and big.startswith("100,000,000,000,000,000,000")
    small = rpt._cell(0.000012)
    assert "e" not in small.lower()


def test_money_millions_formatter():
    assert rpt.money_m(59407086) == "59.4M"
    assert rpt.money_m(59407086.0) == "59.4M"
    assert rpt._pkr_cell(59407086.0) == "59.4M"
    assert rpt._pkr_cell(None) == "-" and rpt.money_m("n/a") == "-"
    assert "e" not in rpt._pkr_cell(1e20).lower()


def test_latex_dollar_delimiters_are_stripped():
    assert rpt.strip_latex("$z=3$") == "z=3"
    assert rpt.strip_latex(r"$\ge\sim217$") == ">=~217"
    assert rpt._cell(r"threshold $\le 5$ met") == "threshold <= 5 met"
    assert "$" not in rpt._cell("cost $z=3$ and $\\ge\\sim217$")
    assert rpt.strip_latex("no maths here, PKR 100") == "no maths here, PKR 100"


def test_wyckoff2_presentation_order_top_then_developing_then_no_clear():
    with tempfile.TemporaryDirectory() as d:
        db = _local_db_with(d)
        c = sqlite3.connect(db)
        rows = [{"symbol": "AAA", "close": 1.0, "enh_class": "NO CLEAR ACCUMULATION"},
                {"symbol": "BBB", "close": 2.0, "enh_class": "FAILED ACCUMULATION"},
                {"symbol": "CCC", "close": 3.0, "enh_class": "POTENTIAL BREAKOUT"},
                {"symbol": "DDD", "close": 4.0, "enh_class": "DEVELOPING ACCUMULATION"},
                {"symbol": "EEE", "close": 5.0, "enh_class": "STRONG ACCUMULATION"},
                {"symbol": "FFF", "close": 6.0, "enh_class": "NO CLEAR ACCUMULATION"}]
        c.execute("INSERT INTO analysis_cache VALUES ('wyckoff2_research_scan', '2026-11-25T06:00Z', ?)",
                  (json.dumps({"rows": rows}),))
        c.commit()
        c.close()
        conn = rpt.ReadOnlyConnection(_connect(db))
        _, sections = rpt.collect_sections(conn, session_date="2026-11-25")
        w2 = [s for s in sections if s["sub"].startswith("Wyckoff Institutional Accumulation 2.0")][0]
        assert len(w2["rows"]) == 6  # every stock stays present
        assert [r["Symbol"] for r in w2["rows"]] == ["CCC", "EEE", "BBB", "DDD", "AAA", "FFF"]
        tiers = w2["tiers"]
        assert [t["caption"] for t in tiers] == list(rpt.WYCKOFF2_TIER_CAPTIONS)
        assert [t["per_row"] for t in tiers] == [1, 2, 3]
        assert "Original Score" not in tiers[0]["cols"]  # every original value blank -> dropped
        assert tiers[1]["cols"] == ["Symbol", "Price", "Day %", "Enhanced Class"]
        assert tiers[2]["cols"] == ["Symbol", "Price", "Day %"]


def test_phase_d_stage_and_grade_pills_and_wyckoff_tints():
    for v in ("FINAL WINDOW", "BUILDING SHELF", "FRESH IGNITION", "A+ PRIME", "STANDARD", "WATCH_ONLY"):
        assert rpt.badge_style(v) is not None
    assert rpt._row_tints(["Signal"], [{"Signal": "EXTREME"}, {"Signal": "READY"}, {"Signal": "WATCH"}]) == [
        rpt.CRIMSON_SOFT_HEX, rpt.AMBER_SOFT_HEX, None]
    assert rpt.STAGE_PILL[2] == "FINAL WINDOW"


# ---- page 1 summary, Contents removal, LaTeX cleaner -------------------------------------------
import zlib


def _pdf_text(path):
    """Everything drawn in the PDF: reportlab writes ASCII85 + Flate content streams, so decode both."""
    import base64
    data = open(path, "rb").read()
    out = [data]
    i = 0
    while True:
        s = data.find(b"stream", i)
        if s < 0:
            break
        i = s + 6
        if data[s - 3:s] == b"end":
            continue
        st = s + 6
        if data[st:st + 2] == b"\r\n":
            st += 2
        elif data[st:st + 1] == b"\n":
            st += 1
        raw = data[st:data.find(b"endstream", st)].strip()
        if raw.endswith(b"~>"):
            raw = raw[:-2]
        try:
            out.append(zlib.decompress(base64.a85decode(raw, ignorechars=b" \t\r\n\x0b\x0c")))
        except Exception:
            pass
    return b"\n".join(out)


def _candle(title, rows):
    return rpt._section("Patterns", "Long-Side (Bullish)", title, rows, "synthetic", spec=rpt.LONG_COLUMNS)


def _overlap_sections():
    engulf = _candle("Bullish Engulfing", [
        {"symbol": "AAA", "company": "Alpha", "action": "BUY SIGNAL", "date": "2026-11-25"},
        {"symbol": "BBB", "company": "Beta", "action": "BUY SIGNAL", "date": "2026-11-25"},
        {"symbol": "CCC", "company": "Gamma", "action": "WAIT (No Setup)", "date": "2026-11-25"},
        {"symbol": "DDD", "company": "Delta", "action": "BUY SIGNAL", "date": "2026-11-25"},
    ])
    obv = _candle("OBV+MFI Setup with ATR Contraction", [
        {"symbol": "AAA", "company": "Alpha", "action": "BUY SIGNAL", "date": "2026-11-25"},
        {"symbol": "BBB", "company": "Beta", "action": "BUY SIGNAL", "date": "2026-11-25"},
        {"symbol": "CCC", "company": "Gamma", "action": "WAIT (No Setup)", "date": "2026-11-25"},
    ])
    struct = rpt._section("Patterns", rpt.STRUCTURAL_SUB, rpt.STRUCTURAL_TITLE, [
        {"symbol": "BBB", "company": "Beta", "pattern": "Double Bottom", "action": "BUY SIGNAL"},
    ], "synthetic", spec=rpt.STRUCTURAL_COLUMNS)
    phase_d = rpt._section("Breakouts", rpt.PHASE_D_SUB, "Phase D breakouts and shelves (session 2026-11-25)", [
        {"symbol": "CCC", "status": "ENTRY TRIGGERED", "price": 10.0, "setup_grade": "A+ PRIME"},
        {"symbol": "DDD", "status": "BUILDING SHELF", "price": 5.0, "setup_grade": "B"},
    ], "synthetic", spec=rpt.PHASE_D_COLUMNS)
    return [engulf, obv, struct, phase_d]


def test_page1_tables_exclude_wait_no_setup_rows():
    summary = rpt.page1_summary(_overlap_sections(), "2026-11-25")
    for key in ("hot", "bear", "caution"):
        for r in summary[key]:
            assert "WAIT" not in " ".join(str(v) for v in r.values()).upper()
    # CCC is WAIT (No Setup) on the Bullish Engulfing and OBV+MFI tables: those rows never count.
    assert "WAIT" not in str(summary)
    assert "CCC" not in {r["Symbol"] for r in summary["hot"]}  # its only qualifying module is Phase D (1 module)


def test_hot_favourites_need_two_modules_and_sort_by_count_desc():
    summary = rpt.page1_summary(_overlap_sections(), "2026-11-25")
    hot = summary["hot"]
    assert [r["Symbol"] for r in hot] == ["BBB", "AAA"]  # BBB: 3 modules, AAA: 2; DDD and CCC have one each
    assert [r["Count"] for r in hot] == [3, 2]
    assert list(hot[0].keys()) == rpt.HOT_HEADERS
    assert hot[0]["Company"] == "Beta" and hot[0]["Price"] is None
    assert "Structural BUY SIGNAL" in hot[0]["Bullish Setups Triggered"]


def test_empty_summary_tables_are_empty_lists_not_errors():
    assert rpt.page1_summary([], "2026-11-25") == {"hot": [], "bear": [], "caution": []}


def test_contents_section_absent_and_empty_scans_footnote_present():
    with tempfile.TemporaryDirectory() as d:
        empty = rpt._section("Patterns", "Long-Side (Bullish)", "Morning Star", [], "synthetic",
                             spec=rpt.LONG_COLUMNS, empty="none")
        path, pages, size = rpt.render_pdf(os.path.join(d, "p1.pdf"), "2026-11-25",
                                           _overlap_sections() + [empty], generated_at="2026-11-26 06:00 UTC")
        text = _pdf_text(path)
        assert b"(Contents)" not in text
        assert b"Scans with no rows this session" in text
        assert b"Hot Bullish Favourites" in text and b"Caution" in text
        assert b"Signal overlaps from the scanners, not recommendations." in text


def test_latex_cleaner_on_sample_strings():
    assert rpt.strip_latex("$READY=25$") == "READY=25"
    assert rpt.strip_latex("$n=771$") == "n=771"
    assert rpt.strip_latex("$10/12$ and $0/12$") == "10/12 and 0/12"
    assert rpt.strip_latex("$z=3$") == "z=3"
    assert "$" not in rpt._cell("Wyckoff $READY=25$ of $n=771$")
    assert rpt._cell("Wyckoff $READY=25$") == "Wyckoff READY=25"


def _bear_candle(title, rows):
    return rpt._section("Patterns", "Long-Side (Bullish)", title, rows, "synthetic", spec=rpt.SHORT_COLUMNS)


def test_bullish_and_bearish_symbol_goes_to_caution_only():
    # AAA is bullish (Bullish Engulfing + OBV+MFI, 2 modules) and has a Bearish Engulfing SHORT SIGNAL.
    sections = _overlap_sections() + [_bear_candle("Bearish Engulfing", [
        {"symbol": "AAA", "company": "Alpha", "action": "SHORT SIGNAL", "date": "2026-11-25"},
        {"symbol": "FFF", "company": "Foxtrot", "action": "SHORT SIGNAL", "date": "2026-11-25"},
    ])]
    summary = rpt.page1_summary(sections, "2026-11-25")
    hot = {r["Symbol"] for r in summary["hot"]}
    bear = {r["Symbol"] for r in summary["bear"]}
    caution = {r["Symbol"]: r for r in summary["caution"]}
    assert "AAA" not in hot and "AAA" not in bear
    assert caution["AAA"]["Risk / Conflict Reason"] == rpt.CONFLICT_REASON
    assert "BBB" in hot and "BBB" not in caution  # bullish-only symbols are unaffected
    assert "FFF" in bear and "FFF" not in caution  # bearish-only symbol stays in the Bearish table


def test_bearish_symbol_with_caution_flag_leaves_bearish_table():
    alerts = rpt._section("Patterns", "Volatility Intelligence", "Alerts", [
        {"symbol": "EEE", "company": "Echo", "note": "FAILED BULLISH BREAKOUT"}], "synthetic",
        spec=[("Symbol", ["symbol"]), ("Company", ["company"]), ("Note", ["note"])])
    sections = [_bear_candle("Bearish Engulfing", [
        {"symbol": "EEE", "company": "Echo", "action": "SHORT SIGNAL", "date": "2026-11-25"}]), alerts]
    summary = rpt.page1_summary(sections, "2026-11-25")
    assert "EEE" not in {r["Symbol"] for r in summary["bear"]}
    assert "EEE" in {r["Symbol"] for r in summary["caution"]}


def test_no_symbol_in_both_hot_or_bearish_and_caution():
    sections = _overlap_sections() + [_bear_candle("Bearish Engulfing", [
        {"symbol": "AAA", "company": "Alpha", "action": "SHORT SIGNAL", "date": "2026-11-25"}])]
    summary = rpt.page1_summary(sections, "2026-11-25")
    caution = {r["Symbol"] for r in summary["caution"]}
    assert not caution & {r["Symbol"] for r in summary["hot"]}
    assert not caution & {r["Symbol"] for r in summary["bear"]}


def _page_chunks(path):
    """Decoded content stream of each page-level stream, kept separate so one page can be checked."""
    import base64
    data = open(path, "rb").read()
    chunks, i = [], 0
    while True:
        s = data.find(b"stream", i)
        if s < 0:
            break
        i = s + 6
        if data[s - 3:s] == b"end":
            continue
        st = s + 6
        st += 2 if data[st:st + 2] == b"\r\n" else 1 if data[st:st + 1] == b"\n" else 0
        raw = data[st:data.find(b"endstream", st)].strip()
        if raw.endswith(b"~>"):
            raw = raw[:-2]
        try:
            chunks.append(zlib.decompress(base64.a85decode(raw, ignorechars=b" \t\r\n\x0b\x0c")))
        except Exception:
            pass
    return chunks


def test_latex_strings_are_stripped_in_rendered_pdf(tmp_path):
    sample = "$=3,$ and $READY=25$ with $n=771$ at $10/12$ or $0/12$"
    rows = [{"symbol": "ZZZ", "company": "Zulu $n=771$", "signal": "READY", "score": 72, "price": 10.0}]
    sec = rpt._section("Patterns", rpt.MARKET_BEHAVIOUR_SUB, "Wyckoff test", rows, "synthetic",
                       note=sample, spec=rpt.WYCKOFF_V1_COLUMNS, summary=[sample])
    path, _, _ = rpt.render_pdf(str(tmp_path / "latex.pdf"), "2026-11-25", [sec],
                                generated_at="2026-11-26 06:00 UTC")
    text = b"\n".join(_page_chunks(path))  # decoded page content only, not the compressed bytes
    assert b"READY=25" in text and b"n=771" in text and b"10/12" in text and b"0/12" in text
    assert b"=3," in text
    assert b"$" not in text
    assert rpt.strip_latex("$=3,$") == "=3,"
    assert rpt.strip_latex("$READY=25$") == "READY=25"
    assert rpt.strip_latex("$n=771$") == "n=771"
    assert rpt.strip_latex("$10/12$") == "10/12"
    assert rpt.strip_latex("$0/12$") == "0/12"


def test_wyckoff1_header_is_on_the_same_page_as_its_table(tmp_path):
    filler = rpt._section("Patterns", "Long-Side (Bullish)", "Filler", [
        {"symbol": f"F{i:02d}", "company": "x", "action": "BUY SIGNAL", "date": "2026-11-25"} for i in range(40)],
        "synthetic", spec=rpt.LONG_COLUMNS)
    rows = [{"symbol": f"WY{i:02d}", "company": "Co", "signal": "READY", "score": 70 + i % 10, "price": 5.0 + i}
            for i in range(28)]
    wy = rpt._section("Patterns", rpt.MARKET_BEHAVIOUR_SUB, rpt.MARKET_BEHAVIOUR_TITLE + " (scan 2026-11-25)",
                      rows, "synthetic", note="WATCH = score 60-69, READY = 70-84, EXTREME = 85+.",
                      spec=rpt.WYCKOFF_V1_COLUMNS)
    path, _, _ = rpt.render_pdf(str(tmp_path / "wy.pdf"), "2026-11-25", [filler, wy],
                                generated_at="2026-11-26 06:00 UTC")
    chunks = _page_chunks(path)
    title = rpt.MARKET_BEHAVIOUR_TITLE.encode()
    # Title, disclaimer and first table row share one page, and the title comes before the rows.
    pages = [c for c in chunks if title in c]
    assert pages, "Wyckoff 1.0 title not found"
    page = pages[0]
    assert page.index(title) < page.index(b"WATCH = score 60-69") < page.index(b"WY00")
    assert b"WY00" in page and b"WY27" in page


def test_wyckoff2_potential_breakout_rows_are_one_table_row_each(tmp_path):
    names = ["SCBPL", "NATF", "FCEPL", "HMB", "CSIL"]
    tiers = [{"caption": rpt.WYCKOFF2_TIER_CAPTIONS[0], "per_row": 1,
              "cols": ["Symbol", "Price", "Day %", "Enhanced Class"],
              "rows": [{"Symbol": n, "Price": 10.0 + i, "Day %": "1.00", "Enhanced Class": "POTENTIAL BREAKOUT"}
                       for i, n in enumerate(names)]}]
    sec = rpt._section("Patterns", rpt.WYCKOFF2_SUB, "Enhanced-class table (research)", tiers[0]["rows"],
                       "synthetic")
    sec["tiers"] = tiers
    path, _, _ = rpt.render_pdf(str(tmp_path / "w2.pdf"), "2026-11-25", [sec],
                                generated_at="2026-11-26 06:00 UTC")
    text = _pdf_text(path)
    for n in names:
        assert n.encode() in text


def test_history_lambda_sample_size_becomes_plain_n_equals():
    assert rpt.strip_latex(r"n $\lambda=1759$") == "n=1759"
    assert rpt.strip_latex(r"history n $\lambda=12$ ok") == "history n=12 ok"


def test_history_remaining_dollar_delimiters_are_stripped_numbers_unchanged():
    assert rpt.strip_latex("$|=10$") == "|=10"
    assert rpt.strip_latex("$10/12$") == "10/12"
    assert rpt.strip_latex("$0/12$") == "0/12"
    assert rpt.strip_latex(r"n $\lambda=1759$, $|=10$, $10/12$, $0/12$") == "n=1759, |=10, 10/12, 0/12"
    assert "$" not in rpt.strip_latex(r"n $\lambda=1759$, $|=10$, $10/12$, $0/12$")


def test_banners_are_marked_keep_with_next():
    from reportlab.platypus import HRFlowable, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    banner = Paragraph("Bullish Expansion", ParagraphStyle("t"))
    rule = HRFlowable(width=100)
    out = rpt.keep_with_next([banner, rule])
    assert out == [banner, rule]
    assert banner.keepWithNext == 1 and rule.keepWithNext == 1
    assert not getattr(Spacer(1, 1), "keepWithNext", 0)
