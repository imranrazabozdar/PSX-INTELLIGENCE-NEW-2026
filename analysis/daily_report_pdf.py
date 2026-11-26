"""Dated PDF daily patterns report: the Chart Patterns, Patterns and Breakouts tabs only.

FIRE Engine content is excluded on purpose (no fire_scan, no FIRE-tagged rows).

READ-ONLY: every query goes through ReadOnlyConnection, which accepts only a single
SELECT or PRAGMA statement and refuses everything else.

Usage:
    python3 analysis/daily_report_pdf.py                    # Turso via backend/turso_db (SELECT only)
    python3 analysis/daily_report_pdf.py --local-db PATH    # local SQLite copy (tests)
    python3 analysis/daily_report_pdf.py --local-db PATH --dry-run
    python3 analysis/daily_report_pdf.py --session-date 2026-11-25

Output: out/PSX_Daily_Report_<YYYY-MM-DD>.pdf, where the date is the latest daily_ohlc
trade_date (session date). Nothing is sent anywhere by this script.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Top-level headings, in report order. Only these three app tabs are in the PDF.
GROUP_ORDER = ("Chart Patterns", "Patterns", "Breakouts")
# Chart Patterns tab: these four Bulkowski patterns only, each as a CONFIRMED and a FORMING table.
CHART_PATTERN_NAMES = ("CUP_WITH_HANDLE", "HIGH_TIGHT_FLAG_PSX", "PIPE_BOTTOM_1D", "BROADENING_BOTTOM")
CHART_STATES = ("CONFIRMED", "FORMING")
# Same columns as the app's Chart Patterns tab: (label, candidate field names).
CHART_COLUMNS = [
    ("Symbol", ["symbol"]), ("Pattern", ["pattern"]), ("State", ["state"]), ("Signal Date", ["signal_date"]),
    ("RVOL", ["rvol"]), ("Median20 PKR", ["median20_pkr"]), ("Clear_Runway %", ["clear_runway_pct"]),
    ("Runway flag", ["runway_flag"]), ("Suggested Stop", ["suggested_stop"]),
    ("Breadth %", ["universe_breadth_pct"]),
]
PHASE_D_SUB = "Phase D Breakout & Shelf Tracker"
PHASE_D_COLUMNS = [
    ("symbol", ["symbol"]), ("stage", ["status"]), ("price", ["price"]), ("day %", ["day %"]),
    ("RVOL", ["rvol"]), ("shelf ceiling", ["ceiling"]), ("day", ["day"]), ("turnover", ["turnover"]),
    ("setup grade", ["setup_grade"]), ("price tier", ["price_tier"]),
]
WYCKOFF2_SUB = "Wyckoff Institutional Accumulation 2.0 (RESEARCH)"
WYCKOFF2_COLUMNS = [
    ("symbol", ["symbol"]), ("price", ["close"]), ("day %", ["chg_pct"]),
    ("original score", ["orig_score"]), ("original class", ["orig_class"]), ("enhanced class", ["enh_class"]),
]
WYCKOFF_SIGNALS = ("WATCH", "READY", "EXTREME")
MARKET_BEHAVIOUR_SUB = "Market Behaviour"
MARKET_BEHAVIOUR_TITLE = "Wyckoff Institutional Accumulation"


def _dir(d):
    """Direction split: keep one side of a BULL/BEAR cache list. No direction field -> no rows."""
    def f(rows):
        if not any("direction" in r for r in rows):
            return []
        return [r for r in rows if str(r.get("direction", "")).upper() == d]
    return f


def _not_hst(rows):
    return [r for r in rows if str(r.get("pattern_type", "")).upper() != "HEAD_SHOULDERS_TOP"]


def _vol_early(rows):
    out = [r for r in rows if not r.get("stale")
           and (r.get("stage") in (1, 2) or (r.get("compression_score") or 0) >= 50)]
    return sorted(out, key=lambda r: -(r.get("compression_score") or 0))


def _vol_expansion(sgn):
    k = "bull" if sgn > 0 else "bear"

    def f(rows):
        out = [r for r in rows if not r.get("stale")
               and (r.get(f"{k}_score") or 0) >= 40
               and (r.get("stage", 0) > 0 or (r.get("compression_score") or 0) >= 40)
               and not (r.get("stage") == 5 and r.get("stage_dir") == sgn)]
        return sorted(out, key=lambda r: -((r.get(f"{k}_score") or 0) * 0.5
                                           + (r.get(f"{k}_expansion_score") or 0) * 0.3
                                           + (r.get("compression_score") or 0) * 0.2))
    return f


def _wyckoff_signal_only(rows):
    field = next((k for k in ("wyckoff_signal", "signal") if any(k in r for r in rows)), None)
    if field is None:
        return rows
    return [r for r in rows if str(r.get(field, "")).upper() in WYCKOFF_SIGNALS]


# Patterns tab, in the app's order: (sub-heading, [(tab title, analysis_cache key, row transform, field)]).
# Transforms filter one side of a direction-split cache list. Titles are the app's section names.
PATTERN_TABS = [
    ("Long-Side (Bullish)", [
        ("OBV+MFI Setup with ATR Contraction", "obv_mfi_scan", None, None),
        ("Bullish Engulfing", "bullish_engulfing_scan", None, None),
        ("Morning Star", "morning_star_scan", None, None),
        ("Bullish Three-Line Strike", "three_line_strike_scan", None, None),
        ("MHarris 5-Bar Reversal (Bullish)", "mharris_scan", _dir("BULL"), None),
        ("Engulfing + Star Confirmed Reversal (Bullish)", "engulfing_star_scan", _dir("BULL"), None),
        ("MACD+EMA200 Trend Resumption (Bullish)", "macdema_scan", _dir("BULL"), None),
        ("Level Break Out (Resistance Breakout)", "level_breakout_scan", _dir("BULL"), None),
        ("GP-Evolved Formula (Long Bias)", "gp_evolved_scan", _dir("BULL"), None),
    ]),
    ("Short-Side (Bearish)", [
        ("Bearish Engulfing", "bearish_engulfing_scan", None, None),
        ("Evening Star", "evening_star_scan", None, None),
        ("MHarris 5-Bar Reversal (Bearish)", "mharris_scan", _dir("BEAR"), None),
        ("Engulfing + Star Confirmed Reversal (Bearish)", "engulfing_star_scan", _dir("BEAR"), None),
        ("Regression-Channel Triangle Squeeze", "triangle_regression_scan", None, None),
        ("Level Break Out (Support Breakdown)", "level_breakout_scan", _dir("BEAR"), None),
        ("MACD+EMA200 Trend Resumption (Bearish)", "macdema_scan", _dir("BEAR"), None),
        ("GP-Evolved Formula (Short Bias)", "gp_evolved_scan", _dir("BEAR"), None),
    ]),
    ("Structural Patterns", [
        ("Chart Patterns (IHS, Double Bottom)", "advanced_pattern_scan", _not_hst, None),
        ("Head & Shoulders Top", "hstop_scan", None, None),
    ]),
    ("Volatility Intelligence", [
        ("Early Warning", "volatility_engine_scan", _vol_early, None),
        ("Bullish Expansion", "volatility_engine_scan", _vol_expansion(1), None),
        ("Bearish Expansion", "volatility_engine_scan", _vol_expansion(-1), None),
        ("Wyckoff x Volatility", "volatility_wyckoff_combined", _wyckoff_signal_only, None),
        ("Alerts", "volatility_engine_scan", None, "alerts"),
        ("Historical Validation", "volatility_engine_stats", None, None),
    ]),
]
SUMMARY_KEYS = ("signal_type", "grade", "pattern", "state", "classification", "status")
FIRE_TOKEN = "FIRE"
MAX_CELL = 48


class ReadOnlyError(PermissionError):
    pass


class ReadOnlyConnection:
    """Wraps a DB connection. Only a single SELECT or PRAGMA statement is allowed."""

    _ALLOWED = ("SELECT", "PRAGMA")

    def __init__(self, conn):
        self._conn = conn

    def check(self, sql):
        body = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip()
        stmts = [s for s in body.split(";") if s.strip()]
        if len(stmts) != 1 or not stmts[0].lstrip().upper().startswith(self._ALLOWED):
            raise ReadOnlyError("read-only report: only a single SELECT or PRAGMA is allowed")

    def execute(self, sql, params=()):
        self.check(sql)
        return self._conn.execute(sql, params)


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _cache_rows(conn, key, field=None):
    """One analysis_cache result -> (run_at, rows, meta). meta is the whole stored result, for the
    app's own message line. Key absent -> (None, [], None). `field` picks one list in the result."""
    got = conn.execute("SELECT run_at, result_json FROM analysis_cache WHERE cache_key=?", (key,)).fetchall()
    if not got:
        return None, [], None
    d = dict(got[0])
    run_at = d.get("run_at")
    result = json.loads(d["result_json"])
    meta = result if isinstance(result, dict) else {}
    if field is not None:
        lst = result.get(field) if isinstance(result, dict) else None
        return run_at, [r for r in (lst or []) if isinstance(r, dict)], meta
    if isinstance(result, list):
        return run_at, [r for r in result if isinstance(r, dict)], meta
    if not isinstance(result, dict):
        return run_at, [], meta
    # Explicit "hits" (signal scans) or "rows" (research/volatility) lists are authoritative, even
    # when empty; an empty list must not fall through to the scalar fields below.
    for name in ("hits", "rows"):
        if isinstance(result.get(name), list):
            return run_at, [r for r in result[name] if isinstance(r, dict)], meta
    lists = [v for v in result.values() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
    if lists:
        return run_at, max(lists, key=len), meta
    scalars = {k: v for k, v in result.items() if not isinstance(v, (list, dict))}
    return run_at, [{"field": k, "value": v} for k, v in scalars.items()], meta


def _is_fire(row):
    for k in ("pattern", "signal_type", "state", "classification", "source", "scanner"):
        v = row.get(k)
        if isinstance(v, str) and FIRE_TOKEN in v.upper():
            return True
    return False


def _project(rows, spec):
    """Keep only the app's columns. spec is [(label, [candidate fields])]; the first present field wins."""
    cols = [label for label, _ in spec]
    out = []
    for r in rows:
        out.append({label: next((r[c] for c in cands if c in r), None) for label, cands in spec})
    return cols, out


def _section(group, sub, title, rows, source, note=None, date=None, spec=None, checklist=None, summary=None):
    kept = [r for r in rows if not _is_fire(r)]
    empty_text = f"No rows for {date}" if date else "No rows for this section."
    if spec is not None:
        cols, out = _project(kept, spec)
    else:
        cols = []
        for r in kept:
            for k in r:
                if k not in cols:
                    cols.append(k)
        out = kept
    if summary is None:
        summary = []
        for key in SUMMARY_KEYS:
            if key in cols:
                counts = {}
                for r in kept:
                    v = str(r.get(key, "") or "-")
                    counts[v] = counts.get(v, 0) + 1
                summary.append(f"{key}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return {"group": group, "sub": sub, "title": title, "source": source, "columns": cols,
            "rows": out, "summary": summary, "note": note, "excluded_fire": len(rows) - len(kept),
            "empty_text": empty_text, "checklist": checklist or []}


def heading_tree(sections):
    """Ordered (group, [(sub, [(title, row_count), ...]), ...]) tree the PDF is built from."""
    tree = []
    for s in sections:
        if not tree or tree[-1][0] != s["group"]:
            tree.append((s["group"], []))
        subs = tree[-1][1]
        if not subs or subs[-1][0] != s["sub"]:
            subs.append((s["sub"], []))
        subs[-1][1].append((s["title"], len(s["rows"])))
    return tree


def _pattern_section(conn, sub, title, key, transform, field, session):
    run_at, rows, meta = _cache_rows(conn, key, field)
    if meta is None:
        note = f"cache key '{key}' is not in analysis_cache: no data to show"
    else:
        note = f"cached at {run_at}" if run_at else "cached (no run time stored)"
        if transform is not None:
            rows = transform(rows)
        if not rows and (meta.get("message") or meta.get("reason")):
            note += f". App message: {meta.get('message') or meta.get('reason')}"
    return _section("Patterns", sub, title, rows, f"analysis_cache '{key}'", note, date=session)


def _breakouts_section(conn, session_date):
    if session_date is not None:
        pd_date = session_date
    else:
        latest = _rows(conn, "SELECT MAX(scan_date) AS d FROM phase_d_signals")
        pd_date = latest[0]["d"] if latest else None
    pd_rows = _rows(conn, "SELECT * FROM phase_d_signals WHERE scan_date = ? ORDER BY signal_type, symbol",
                    (pd_date,)) if pd_date else []
    from pattern_scanner import phase_d_text as pdt
    kept = [r for r in pd_rows if not _is_fire(r)]
    hits = pdt.sort_hits(kept)
    n = pdt.counts(kept)
    summary = [f"Shelf breakouts: {n['SHELF_BREAKOUT']}", f"SOS ignitions: {n['SOS_IGNITION']}",
               f"Active shelves: {n['ACTIVE_SHELF']}"]
    checklist = []
    for h in hits:
        dates, verdict = pdt.watch(h, pd_date)
        checklist.append(f"{h['symbol']} ({pdt.LABELS.get(h.get('signal_type'), h.get('signal_type'))}): "
                         f"{pdt.TIERS[pdt.tier(h)][1]}. {verdict}.")
        checklist.append(f"   Dates to watch: {dates}")
        for line in pdt.invalidation(h, pd_date) or []:
            checklist.append(f"   Cancel level: {line}")
    recs = [{
        "symbol": h["symbol"], "status": pdt.TIERS[pdt.tier(h)][0], "price": h.get("close"),
        "day %": h.get("pct_change"), "rvol": h.get("rvol"), "ceiling": h.get("base_or_shelf_high"),
        "day": f"{int(h.get('shelf_days') or 0)}/{pdt.MAX_SHELF_DAY}",
        "turnover": pdt.fmt_turnover(h.get("turnover_pkr")),
        "setup_grade": h.get("setup_grade") or "", "price_tier": h.get("price_tier") or "",
    } for h in hits]
    return _section("Breakouts", PHASE_D_SUB, f"Phase D breakouts and shelves (session {pd_date or 'none'})",
                    recs, "phase_d_signals (scan_date)", date=pd_date or "none", spec=PHASE_D_COLUMNS,
                    checklist=checklist, summary=summary)


def collect_sections(conn, root_dir=ROOT, session_date=None):
    """Read every section through the guarded connection. Returns (session_date, sections).

    session_date (YYYY-MM-DD) pins the report to that session instead of MAX(...) for the
    header, the file name, phase_d_signals and wyckoff_accumulation. None keeps the default.
    """
    conn = conn if isinstance(conn, ReadOnlyConnection) else ReadOnlyConnection(conn)
    if session_date is not None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", session_date):
            raise ValueError(f"--session-date must be YYYY-MM-DD, got {session_date!r}")
        session = session_date
    else:
        r = _rows(conn, "SELECT MAX(trade_date) AS d FROM daily_ohlc")
        session = str(r[0]["d"])[:10] if r and r[0]["d"] else None
    if not session:
        raise RuntimeError("daily_ohlc has no trade_date; cannot name the report")
    sections = []

    # Chart Patterns: the same Bulkowski scan the Streamlit view uses (shared helper), four patterns
    # only, one CONFIRMED and one FORMING table, sorted as the app sorts them (Signal Date desc, Symbol).
    from pattern_scanner.chart_scan import scan_chart_patterns
    cp = scan_chart_patterns(conn, root_dir)
    for state in CHART_STATES:
        cp_rows = [s for s in cp["signals"]
                   if str(s.get("state", "")).upper() == state
                   and str(s.get("pattern", "")).upper() in CHART_PATTERN_NAMES]
        cp_rows.sort(key=lambda s: str(s.get("symbol", "")))
        cp_rows.sort(key=lambda s: str(s.get("signal_date", "")), reverse=True)
        sections.append(_section("Chart Patterns", state, "Chart Patterns (Bulkowski, last 250 daily bars)",
                                 cp_rows, "pattern_scanner.chart_scan.scan_chart_patterns (daily_ohlc)",
                                 date=session, spec=CHART_COLUMNS))

    # Patterns: sub-headings and tables in the app's order.
    for sub, tables in PATTERN_TABS:
        for title, key, transform, field in tables:
            sections.append(_pattern_section(conn, sub, title, key, transform, field, session))
    # Wyckoff 2.0 research has its own sub-heading, outside Long-Side.
    run_at, w2rows, meta = _cache_rows(conn, "wyckoff2_research_scan")
    w2_note = (f"cached at {run_at}" if meta is not None else
               "cache key 'wyckoff2_research_scan' is not in analysis_cache: no data to show")
    sections.append(_section("Patterns", WYCKOFF2_SUB, "Enhanced-class table (research)", w2rows,
                             "analysis_cache 'wyckoff2_research_scan'", w2_note, date=session,
                             spec=WYCKOFF2_COLUMNS))
    # Market Behaviour: Wyckoff v1 from wyckoff_accumulation for the session date.
    wd = session_date
    if wd is None:
        w = _rows(conn, "SELECT MAX(scan_date) AS d FROM wyckoff_accumulation")
        wd = w[0]["d"] if w else None
    wrows = _rows(conn, "SELECT * FROM wyckoff_accumulation WHERE scan_date = ? "
                        "ORDER BY accumulation_score DESC", (wd,)) if wd else []
    sections.append(_section("Patterns", MARKET_BEHAVIOUR_SUB,
                             f"{MARKET_BEHAVIOUR_TITLE} (scan {wd or 'none'})",
                             wrows, "wyckoff_accumulation (scan_date)", date=wd or "none"))

    # Breakouts: Phase D summary, table and per-stock checklist.
    sections.append(_breakouts_section(conn, session_date))

    # Top-level order is fixed: Chart Patterns, Patterns, Breakouts (stable sort keeps sub-order).
    sections.sort(key=lambda s: GROUP_ORDER.index(s["group"]))
    return session, sections


def report_filename(session_date):
    return f"PSX_Daily_Report_{session_date}.pdf"


def _cell(v):
    if v is None:
        s = ""
    elif isinstance(v, float):
        s = f"{v:.4g}"
    else:
        s = str(v)
    s = s.replace("\n", " ")
    if len(s) > MAX_CELL:
        s = s[:MAX_CELL - 1] + "~"
    return s.encode("latin-1", "replace").decode("latin-1")


def render_pdf(path, session_date, sections, generated_at=None):
    """Write the report to `path`. `sections` are dicts from _section(). Returns (path, pages, bytes)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)
    from xml.sax.saxutils import escape as _esc

    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = landscape(A4)
    width = page[0] - 56
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=22, leading=26)
    grp = ParagraphStyle("grp", parent=ss["Heading1"], fontSize=18, leading=22, spaceBefore=4, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, leading=16, spaceBefore=6, spaceAfter=4)
    ttl = ParagraphStyle("ttl", parent=ss["Heading3"], fontSize=10, leading=13, spaceAfter=2)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, leading=10)
    tiny = ParagraphStyle("tiny", parent=ss["Normal"], fontSize=6.5, leading=8)
    mono = ParagraphStyle("mono", parent=ss["Normal"], fontSize=7, leading=9)
    dark = colors.HexColor("#1f2d3d")
    band = colors.HexColor("#eef2f6")
    header_text = f"PSX Daily Patterns Report  |  Session {session_date}  |  Generated {generated_at}"

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(28, page[1] - 18, header_text)
        canvas.drawRightString(page[0] - 28, 14, f"Page {doc.page}")
        canvas.restoreState()

    story = [Spacer(1, 60), Paragraph("PSX Daily Patterns Report", h1), Spacer(1, 8),
             Paragraph(f"<b>Session date:</b> {session_date}", small),
             Paragraph(f"<b>Generated:</b> {generated_at}", small),
             Paragraph("Covers Chart Patterns, Patterns and Breakouts. FIRE Engine content is excluded.", small),
             Spacer(1, 18), Paragraph("Contents", h2)]
    for g, subs in heading_tree(sections):
        story.append(Paragraph(f"<b>{_esc(g)}</b>", small))
        for sub, tables in subs:
            story.append(Paragraph(f"&nbsp;&nbsp;{_esc(sub)}", tiny))
            for title, n in tables:
                story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{_esc(title)} ({n} rows)", tiny))
    story.append(PageBreak())

    current_group = current_sub = None
    for s in sections:
        if s["group"] != current_group:
            if current_group is not None:
                story.append(PageBreak())
            current_group, current_sub = s["group"], None
            story.append(Paragraph(_esc(s["group"]), grp))
        if s["sub"] != current_sub:
            current_sub = s["sub"]
            story.append(Paragraph(_esc(s["sub"]), h2))
        story.append(Paragraph(_esc(s["title"]), ttl))
        summary = " | ".join(s["summary"]) if s["summary"] else "no rows"
        story.append(Paragraph(f"<b>Total rows:</b> {len(s['rows'])}. {_esc(summary)}", small))
        story.append(Paragraph(_esc(f"Source: {s['source']}" + (f". {s['note']}" if s.get("note") else "")), tiny))
        story.append(Spacer(1, 6))
        if s["rows"]:
            cols = s["columns"]
            data = [[_cell(c) for c in cols]]
            for r in s["rows"]:
                data.append([_cell(r.get(c)) for c in cols])
            weights = []
            for c in cols:
                longest = max([len(str(_cell(r.get(c)))) for r in s["rows"][:200]] + [len(c)])
                weights.append(min(max(longest, 4), 30))
            total = float(sum(weights))
            widths = [max(width * w / total, 22) for w in weights]
            scale = width / sum(widths)
            widths = [w * scale for w in widths]
            t = Table(data, colWidths=widths, repeatRows=1)
            style = [("FONT", (0, 0), (-1, -1), "Helvetica", 6.5),
                     ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 6.5),
                     ("BACKGROUND", (0, 0), (-1, 0), dark),
                     ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                     ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                     ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                     ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]
            for i in range(1, len(data)):
                if i % 2 == 0:
                    style.append(("BACKGROUND", (0, i), (-1, i), band))
            t.setStyle(TableStyle(style))
            story.append(t)
        else:
            story.append(Paragraph(_esc(s["empty_text"]), small))
        for line in s.get("checklist") or []:
            story.append(Paragraph(_esc(line), mono))
        story.append(Spacer(1, 14))

    doc = SimpleDocTemplate(path, pagesize=page, leftMargin=28, rightMargin=28, topMargin=32, bottomMargin=28,
                            title="PSX Daily Patterns Report", author="PSX Intelligence",
                            subject=f"Session {session_date}", pageCompression=1)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        pages = len(re.findall(rb"/Type\s*/Page(?!s)", f.read()))
    return path, pages, size


def build_report(conn, out_dir=None, root_dir=ROOT, session_date=None):
    session, sections = collect_sections(conn, root_dir, session_date)
    out_dir = out_dir or os.path.join(root_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, report_filename(session))
    return (session, sections) + render_pdf(path, session, sections)


def _open_connection(local_db):
    if local_db:
        c = sqlite3.connect(local_db)
        c.row_factory = sqlite3.Row
        return c
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    import turso_db
    return turso_db.get_connection()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local-db", help="read a local SQLite file instead of Turso (tests)")
    ap.add_argument("--out-dir", help="output folder (default: <repo>/out)")
    ap.add_argument("--dry-run", action="store_true", help="write the PDF only; no delivery step exists")
    ap.add_argument("--session-date", metavar="YYYY-MM-DD",
                    help="report this session date instead of the latest one in the database")
    args = ap.parse_args(argv)
    conn = ReadOnlyConnection(_open_connection(args.local_db))
    session, sections, path, pages, size = build_report(conn, args.out_dir, session_date=args.session_date)
    print(f"report: {os.path.basename(path)}")
    print(f"session: {session}  sections: {len(sections)}  rows: {sum(len(s['rows']) for s in sections)}")
    print(f"pages: {pages}  size: {size // 1024} KB  path: {path}")
    if size > 20 * 1024 * 1024:
        print("WARNING: report is over 20 MB; reduce rows per page or the font subset")
    if args.dry_run:
        print("dry-run: PDF written to out/ only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
