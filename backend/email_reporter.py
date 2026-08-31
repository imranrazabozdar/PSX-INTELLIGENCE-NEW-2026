"""email_reporter.py — end-of-day HTML email summary for one PSX trading
session: candlestick signals (from patterns_engine.py, the same detector
the live scans use) plus a live Gemini 3-sentence read per symbol (from
ai_overlay.QuantLLMService, the same service the Streamlit AI panels
call). Read-only against psx_v2.db — never writes to it.

SCOPE NOTE: REPORT_SYMBOLS below is a curated ~15-symbol set (the same
liquid, sector-diverse universe run_dss_backtest.py already validated,
plus GTYR/KOHE/LEUL per this report's explicit requirement), not the
full ~89-symbol watchlist. Emailing a live Gemini call per symbol for
the whole watchlist would mean 89+ LLM calls per run (cost, latency,
and free-tier rate limits — see ai_overlay.py's module docstring on the
429s hit during testing) for a report that's meant to be a concise
end-of-day read, not a full market dump. Widen REPORT_SYMBOLS if a
larger report is actually wanted.
"""

import os
import smtplib
import sqlite3
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import patterns_engine as pe
from ai_overlay import QuantLLMService

DB_PATH = Path(__file__).parent / "psx_v2.db"

SESSION_DATE = "2026-08-28"  # the Friday session this report targets
AS_OF_CUTOFF = "2026-08-29"  # day after SESSION_DATE, so patterns_engine treats
                              # SESSION_DATE as the latest COMPLETED candle

REPORT_SYMBOLS = ["OGDC", "PPL", "HBL", "UBL", "LUCK", "FFC", "PSO", "MCB",
                  "SYS", "MARI", "BAFL", "HUBC", "GTYR", "KOHE", "LEUL"]

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")


def _load_symbol_rows(conn, symbol):
    """Raw daily_ohlc rows for one symbol, oldest-first, shaped for
    patterns_engine.py (which expects a `trade_date` key)."""
    raw = conn.execute(
        "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
        "WHERE symbol=? ORDER BY trade_date ASC", (symbol,)).fetchall()
    return [{"trade_date": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "volume": r[5]} for r in raw]


def compile_session_data(symbols=REPORT_SYMBOLS, session_date=SESSION_DATE):
    """For each symbol: the session's own OHLC row (if the session exists
    in daily_ohlc for that symbol), its Bullish Engulfing classification
    pinned to that exact session (as_of=AS_OF_CUTOFF — see module
    docstring), and a live Gemini 3-sentence summary from
    QuantLLMService.get_stock_research_summary(). A symbol with no data
    for this session is skipped, not padded with fake numbers.
    """
    conn = sqlite3.connect(DB_PATH)
    ai = QuantLLMService()
    results = []

    for sym in symbols:
        rows = _load_symbol_rows(conn, sym)
        session_row = next((r for r in rows if r["trade_date"] == session_date), None)
        if session_row is None:
            print(f"  {sym}: no daily_ohlc row for {session_date} — skipped")
            continue

        pattern = pe.detect_bullish_engulfing(rows, date_key="trade_date", as_of=AS_OF_CUTOFF)
        change_pct = None
        prev_close = next((r["close"] for r in reversed(rows)
                            if r["trade_date"] < session_date), None)
        if prev_close:
            change_pct = (session_row["close"] - prev_close) / prev_close * 100

        technical_data = {
            "session_date": session_date,
            "open": session_row["open"], "high": session_row["high"],
            "low": session_row["low"], "close": session_row["close"],
            "volume": session_row["volume"],
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "candlestick_pattern": pattern.get("classification"),
            "candlestick_detected": pattern.get("detected"),
        }

        print(f"  {sym}: generating AI summary...")
        ai_summary = ai.get_stock_research_summary(
            ticker=sym, dss_score=None, technical_data=technical_data, recent_news=[])

        results.append({
            "symbol": sym, "technical_data": technical_data,
            "ai_summary": ai_summary, "is_live": ai.is_live,
        })

    conn.close()
    return results


def _signal_color(technical_data):
    """Green for a bullish close-over-open session or a confirmed Bullish
    Engulfing, red for a bearish close-under-open session, grey/neutral
    otherwise."""
    if technical_data.get("candlestick_detected"):
        return "#1a7f37"  # confirmed Bullish Engulfing -- green
    o, c = technical_data.get("open"), technical_data.get("close")
    if o is not None and c is not None:
        if c > o:
            return "#1a7f37"
        if c < o:
            return "#c0392b"
    return "#555555"


def build_html_report(rows, session_date=SESSION_DATE):
    cards = []
    for r in rows:
        td = r["technical_data"]
        color = _signal_color(td)
        chg = td.get("change_pct")
        chg_str = f"{chg:+.2f}%" if chg is not None else "—"
        pattern_label = td.get("candlestick_pattern") or "No pattern"
        cards.append(f"""
        <div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;margin-bottom:14px;
                     font-family:Arial,Helvetica,sans-serif;">
          <div style="font-size:16px;font-weight:bold;color:#111111;">
            {r['symbol']}
            <span style="color:{color};font-weight:bold;">&nbsp;{chg_str}</span>
          </div>
          <div style="font-size:12px;color:#666666;margin:4px 0 10px 0;">
            O {td.get('open')} &nbsp;H {td.get('high')} &nbsp;L {td.get('low')} &nbsp;
            C {td.get('close')} &nbsp;Vol {td.get('volume')} &nbsp;|&nbsp;
            <span style="color:{color};font-weight:bold;">{pattern_label}</span>
          </div>
          <div style="font-size:13px;color:#222222;line-height:1.5;">
            {r['ai_summary']}
          </div>
        </div>""")

    live_note = ("Live Gemini summaries." if rows and rows[0]["is_live"]
                 else "MOCK summaries — no LLM key configured on the backend.")
    return f"""
    <html>
      <body style="background-color:#f7f7f7;padding:20px;font-family:Arial,Helvetica,sans-serif;">
        <div style="max-width:640px;margin:0 auto;background-color:#ffffff;padding:24px;
                     border-radius:10px;">
          <h2 style="color:#111111;margin-top:0;">PSX End-of-Day Report — {session_date}</h2>
          <p style="font-size:12px;color:#888888;margin-top:-8px;">{live_note}
             Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}.</p>
          {''.join(cards) if cards else '<p>No session data available for the requested date.</p>'}
        </div>
      </body>
    </html>
    """


def send_report(html_body, session_date=SESSION_DATE):
    """Sends the report via SMTP STARTTLS. Never raises — an auth/connection
    failure is caught, printed, and reported back as {"status": "error"}
    rather than crashing the caller."""
    if not all([SMTP_SERVER, SMTP_USER, SMTP_PASSWORD, RECIPIENT_EMAIL]):
        missing = [name for name, val in [
            ("SMTP_SERVER", SMTP_SERVER), ("SMTP_USER", SMTP_USER),
            ("SMTP_PASSWORD", SMTP_PASSWORD), ("RECIPIENT_EMAIL", RECIPIENT_EMAIL)] if not val]
        reason = f"Missing required .env variable(s): {', '.join(missing)}."
        print(f"[email_reporter] {reason} Email NOT sent.")
        return {"status": "error", "reason": reason}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"PSX End-of-Day Report — {session_date}"
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"[email_reporter] Report sent to {RECIPIENT_EMAIL}.")
        return {"status": "ok", "recipient": RECIPIENT_EMAIL}
    except smtplib.SMTPAuthenticationError as e:
        reason = f"SMTP authentication failed: {e}"
        print(f"[email_reporter] {reason}")
        return {"status": "error", "reason": reason}
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        print(f"[email_reporter] Email send failed: {reason}")
        return {"status": "error", "reason": reason}


def main():
    print(f"Compiling {SESSION_DATE} session data for {len(REPORT_SYMBOLS)} symbols...")
    rows = compile_session_data()
    print(f"\n{len(rows)}/{len(REPORT_SYMBOLS)} symbols had data for {SESSION_DATE}.")
    html = build_html_report(rows)
    result = send_report(html)
    print(f"\nResult: {result}")
    return result


if __name__ == "__main__":
    main()
