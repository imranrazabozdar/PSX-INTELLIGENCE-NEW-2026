"""reporting.py — Phase 15: daily HTML report, one section per symbol plus
a summary. Reads directly from fire_events/daily_reports via a
DatabaseManager; does not recompute anything -- the daily batch
(scheduler.py) is what runs the detectors and writes fire_events first.
"""
from html import escape

STATUS_EMOJI = {
    "FIRE": "🔴", "PRE_FIRE": "🟡", "WATCH": "🟠", "NO_SETUP": "⚪",
}


def _symbol_summary(db, symbol: str, report_date: str) -> dict:
    from fire_engine.events import query_fire_events

    events = query_fire_events(db, symbol=symbol, date_from=report_date, date_to=report_date)
    fire_events = [e for e in events if e["event_type"] == "FIRE"]
    pre_fire_events = [e for e in events if e["event_type"] == "PRE_FIRE"]
    absorption_events = [e for e in events if e["event_type"].startswith("ABSORPTION")]
    near_close_events = [e for e in events if e["near_close"]]

    highest_score = max((e["fire_score"] for e in events if e["fire_score"] is not None), default=0)
    highest_mfi_accel = max(
        (e["mfi_acceleration_15m"] for e in events if e["mfi_acceleration_15m"] is not None),
        default=0.0,
    )

    if fire_events:
        status = "FIRE"
    elif pre_fire_events:
        status = "PRE_FIRE"
    elif highest_score >= 40:
        status = "WATCH"
    else:
        status = "NO_SETUP"

    session = db.conn.execute(
        "SELECT total_candles, expected_candles, data_quality_status FROM trading_sessions "
        "WHERE session_id = ?", (f"{symbol}:{report_date}",),
    ).fetchone()
    data_quality = session["data_quality_status"] if session else "UNKNOWN"
    candle_note = (
        f"{session['total_candles']} candles" if session else "no session record"
    )

    return {
        "symbol": symbol, "status": status, "score": highest_score,
        "data_quality": data_quality, "candle_note": candle_note,
        "highest_mfi_acceleration": highest_mfi_accel,
        "fire_events": fire_events, "pre_fire_events": pre_fire_events,
        "absorption_events": absorption_events, "near_close_events": near_close_events,
    }


def generate_daily_report(db, report_date: str, symbols: list) -> dict:
    """Returns the same shape as reporting.py's spec:
    {report_date, symbols: {SYM: {...}}, summary: {...}}"""
    symbol_reports = {sym: _symbol_summary(db, sym, report_date) for sym in symbols}
    summary = {
        "total_fire_events": sum(len(r["fire_events"]) for r in symbol_reports.values()),
        "total_pre_fire_events": sum(len(r["pre_fire_events"]) for r in symbol_reports.values()),
        "total_absorption_events": sum(len(r["absorption_events"]) for r in symbol_reports.values()),
        "highest_score": max((r["score"] for r in symbol_reports.values()), default=0),
    }
    return {"report_date": report_date, "symbols": symbol_reports, "summary": summary}


def format_daily_report_html(report: dict) -> str:
    lines = [
        "<html><head><meta charset='utf-8'><title>PSX FIRE Engine - Daily Report</title>",
        "<style>body{font-family:monospace;background:#111;color:#eee;padding:20px}"
        "h2{color:#ff8800}.sym{margin-bottom:24px;padding:12px;border:1px solid #333}"
        ".label{color:#888}</style></head><body>",
        "<h1>PSX FIRE ENGINE - Daily Report</h1>",
        f"<p>Date: {escape(report['report_date'])}</p>",
    ]
    for sym, r in report["symbols"].items():
        emoji = STATUS_EMOJI.get(r["status"], "⚪")
        lines.append(f"<div class='sym'><h2>{escape(sym)}</h2>")
        lines.append(f"<p>Status: {emoji} {escape(r['status'])} | Score: {r['score']}/100</p>")
        lines.append(f"<p class='label'>Session Quality: {escape(r['data_quality'])} ({escape(r['candle_note'])})</p>")
        lines.append(f"<p class='label'>Highest MFI Acceleration: +{r['highest_mfi_acceleration']:.1f}</p>")
        if r["absorption_events"]:
            types = ", ".join(e["notes"] or e["event_type"] for e in r["absorption_events"])
            lines.append(f"<p>Absorption: {escape(types)}</p>")
        if r["near_close_events"]:
            times = ", ".join(str(e["event_time"]) for e in r["near_close_events"])
            lines.append(f"<p>Near-Close: events at {escape(times)}</p>")
        action = "MONITOR" if r["status"] in ("WATCH", "PRE_FIRE") else (
            "FIRE CONFIRMED" if r["status"] == "FIRE" else "NO ACTION"
        )
        lines.append(f"<p><b>Action: {escape(action)}</b></p></div>")

    s = report["summary"]
    lines.append("<h2>SUMMARY</h2><ul>")
    lines.append(f"<li>FIRE Events: {s['total_fire_events']}</li>")
    lines.append(f"<li>PRE-FIRE Events: {s['total_pre_fire_events']}</li>")
    lines.append(f"<li>Absorption Events: {s['total_absorption_events']}</li>")
    lines.append(f"<li>Highest Score: {s['highest_score']}</li>")
    lines.append("</ul></body></html>")
    return "\n".join(lines)


def save_report_to_db(db, report_date: str, symbol: str, report_html: str, symbol_report: dict):
    db.conn.execute(
        """INSERT INTO daily_reports
           (report_date, symbol, data_quality_status, highest_mfi_acceleration,
            highest_fire_score, pre_fire_count, fire_count, absorption_count,
            failed_setup_count, near_close_events_count, report_html)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(report_date, symbol) DO UPDATE SET
             data_quality_status=excluded.data_quality_status,
             highest_mfi_acceleration=excluded.highest_mfi_acceleration,
             highest_fire_score=excluded.highest_fire_score,
             pre_fire_count=excluded.pre_fire_count, fire_count=excluded.fire_count,
             absorption_count=excluded.absorption_count,
             failed_setup_count=excluded.failed_setup_count,
             near_close_events_count=excluded.near_close_events_count,
             report_html=excluded.report_html, generated_at=CURRENT_TIMESTAMP""",
        (report_date, symbol, symbol_report["data_quality"], symbol_report["highest_mfi_acceleration"],
         symbol_report["score"], len(symbol_report["pre_fire_events"]), len(symbol_report["fire_events"]),
         len(symbol_report["absorption_events"]), 0, len(symbol_report["near_close_events"]), report_html),
    )
    db.conn.commit()
