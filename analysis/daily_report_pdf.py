"""Dated PDF daily patterns report: Breakouts, Patterns and Chart Patterns tabs.

FIRE Engine content is excluded on purpose (no fire_scan, no FIRE-tagged rows).

READ-ONLY: every query goes through ReadOnlyConnection, which accepts only a single
SELECT or PRAGMA statement and refuses everything else.

Usage:
    python3 analysis/daily_report_pdf.py                    # Turso via backend/turso_db (SELECT only)
    python3 analysis/daily_report_pdf.py --local-db PATH    # local SQLite copy (tests)
    python3 analysis/daily_report_pdf.py --local-db PATH --dry-run

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

# (group, sub-group, title, analysis_cache key or None for a table read)
ANALYSIS_SECTIONS = [
    ("Patterns", "Long-Side", "Wyckoff Institutional Accumulation 2.0 (research)", "wyckoff2_research_scan"),
    ("Patterns", "Long-Side", "Bullish Engulfing", "bullish_engulfing_scan"),
    ("Patterns", "Long-Side", "Morning Star", "morning_star_scan"),
    ("Patterns", "Long-Side", "Bullish Three-Line Strike", "three_line_strike_scan"),
    ("Patterns", "Short-Side", "Bearish Engulfing", "bearish_engulfing_scan"),
    ("Patterns", "Short-Side", "Evening Star", "evening_star_scan"),
    ("Patterns", "Short-Side", "Regression-Channel Triangle Squeeze", "triangle_regression_scan"),
    ("Patterns", "Short-Side", "Level Break Out", "level_breakout_scan"),
    ("Patterns", "Volatility Intelligence", "Alerts (volatility engine scan)", "volatility_engine_scan"),
    ("Patterns", "Volatility Intelligence", "Historical Validation", "volatility_engine_stats"),
    ("Patterns", "Volatility Intelligence", "Wyckoff x Volatility", "volatility_wyckoff_combined"),
    ("Patterns", "Market Behaviour", "Wyckoff Institutional Accumulation v1", "__wyckoff_table__"),
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


def _cache_rows(conn, key):
    """Pull one analysis_cache result and return (run_at, list-of-dict rows)."""
    got = conn.execute("SELECT run_at, result_json FROM analysis_cache WHERE cache_key=?", (key,)).fetchall()
    if not got:
        return None, []
    result = json.loads(dict(got[0])["result_json"])
    run_at = dict(got[0]).get("run_at")
    if isinstance(result, list):
        return run_at, [r for r in result if isinstance(r, dict)]
    if not isinstance(result, dict):
        return run_at, []
    lists = [v for v in result.values() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
    if lists:
        return run_at, max(lists, key=len)
    scalars = {k: v for k, v in result.items() if not isinstance(v, (list, dict))}
    return run_at, [{"field": k, "value": v} for k, v in scalars.items()]


def _is_fire(row):
    for k in ("pattern", "signal_type", "state", "classification", "source", "scanner"):
        v = row.get(k)
        if isinstance(v, str) and FIRE_TOKEN in v.upper():
            return True
    return False


def _section(group, sub, title, rows, source, note=None):
    kept = [r for r in rows if not _is_fire(r)]
    cols = []
    for r in kept:
        for k in r:
            if k not in cols:
                cols.append(k)
    summary = []
    for key in SUMMARY_KEYS:
        if key in cols:
            counts = {}
            for r in kept:
                v = str(r.get(key, "") or "-")
                counts[v] = counts.get(v, 0) + 1
            summary.append(f"{key}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return {"group": group, "sub": sub, "title": title, "source": source, "columns": cols,
            "rows": kept, "summary": summary, "note": note, "excluded_fire": len(rows) - len(kept)}


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

    # Breakouts tab: phase_d_signals for the latest scanned session, all signal types and grades.
    if session_date is not None:
        pd_date = session_date
    else:
        latest = _rows(conn, "SELECT MAX(scan_date) AS d FROM phase_d_signals")
        pd_date = latest[0]["d"] if latest else None
    pd_rows = _rows(conn, "SELECT * FROM phase_d_signals WHERE scan_date = ? ORDER BY signal_type, symbol",
                    (pd_date,)) if pd_date else []
    sections.append(_section("Breakouts", "Phase D", f"Phase D breakouts and shelves (session {pd_date or 'none'})",
                             pd_rows, "phase_d_signals (latest scan_date)"))

    for group, sub, title, key in ANALYSIS_SECTIONS:
        if key == "__wyckoff_table__":
            if session_date is not None:
                wd = session_date
            else:
                w = _rows(conn, "SELECT MAX(scan_date) AS d FROM wyckoff_accumulation")
                wd = w[0]["d"] if w else None
            wrows = _rows(conn, "SELECT * FROM wyckoff_accumulation WHERE scan_date = ? "
                                "ORDER BY accumulation_score DESC", (wd,)) if wd else []
            sections.append(_section(group, sub, f"{title} (scan {wd or 'none'})", wrows,
                                     "wyckoff_accumulation (latest scan_date)"))
            continue
        run_at, rows = _cache_rows(conn, key)
        note = f"cached at {run_at}" if run_at else "no cached result yet"
        sections.append(_section(group, sub, title, rows, f"analysis_cache '{key}'", note))

    # Chart Patterns tab: same Bulkowski scan the Streamlit tab uses, via the shared helper.
    from pattern_scanner.chart_scan import scan_chart_patterns
    cp = scan_chart_patterns(conn, root_dir)
    cp_rows = [s for s in cp["signals"] if str(s.get("state", "")).upper() in ("CONFIRMED", "FORMING")]
    cp_rows.sort(key=lambda s: (0 if str(s.get("state", "")).upper() == "CONFIRMED" else 1,
                                str(s.get("pattern", "")), str(s.get("symbol", ""))))
    sections.append(_section("Chart Patterns", "CONFIRMED then FORMING",
                             "Chart Patterns (Bulkowski, last 250 daily bars)", cp_rows,
                             "pattern_scanner.chart_scan.scan_chart_patterns (daily_ohlc)"))
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

    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = landscape(A4)
    width = page[0] - 56
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=22, leading=26)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, leading=16, spaceAfter=4)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, leading=10)
    tiny = ParagraphStyle("tiny", parent=ss["Normal"], fontSize=6.5, leading=8)
    dark = colors.HexColor("#1f2d3d")
    band = colors.HexColor("#eef2f6")
    header_text = (f"PSX Daily Patterns Report  |  Session {session_date}  |  Generated {generated_at}")

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
             Paragraph("Covers Breakouts, Patterns and Chart Patterns. FIRE Engine content is excluded.", small),
             Spacer(1, 18), Paragraph("Contents", h2)]
    for i, s in enumerate(sections, 1):
        story.append(Paragraph(f"{i}. {s['group']} / {s['sub']}: {s['title']} ({len(s['rows'])} rows)", small))
    story.append(PageBreak())

    for s in sections:
        story.append(Paragraph(f"{s['group']} / {s['sub']}", small))
        story.append(Paragraph(s["title"], h2))
        summary = " | ".join(s["summary"]) if s["summary"] else "no rows"
        story.append(Paragraph(f"<b>Total rows:</b> {len(s['rows'])}. {summary}", small))
        story.append(Paragraph(f"Source: {s['source']}" + (f". {s['note']}" if s.get("note") else ""), tiny))
        story.append(Spacer(1, 6))
        if s["rows"]:
            cols = s["columns"]
            data = [[_cell(c) for c in cols]]
            for r in s["rows"]:
                data.append([_cell(r.get(c)) for c in cols])
            weights = []
            for ci, c in enumerate(cols):
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
            story.append(Paragraph("No rows for this section.", small))
        story.append(PageBreak())

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
