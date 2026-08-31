"""pdf_reporter.py — institutional-grade daily PDF intelligence brief:
full-market technical/DSS ranking, pattern breakouts, volume-anomaly
("smart money") footprinting, macro/sector/stock news gathering, a
Gemini synthesis over all of it, rendered to PDF and emailed. Read-only
against psx_v2.db.

HONEST SCOPING NOTES (read before trusting a number this script prints):

1. "DSS consensus score" — dss_engine.compute() is not a standalone
   function of historical price bars; its components (Wyckoff phase,
   sector regime, the live event-risk feed) are orchestrated LIVE from
   TODAY's market context in app.py's /dss/{symbol}, which cannot be
   faithfully replayed for an arbitrary past target_date. Exactly like
   run_dss_backtest.py before it, this script uses psx_brain.analyse()
   as the DSS-consensus proxy — self-contained, walk-forward-safe, "no
   API, no cost, runs offline" per its own docstring. To still produce
   two genuinely different top-10 lists (not the same ranking twice):
   "Top 10 Technical" ranks by psx_brain's raw additive `score`; "Top 10
   DSS" ranks by its 0-100 normalized `confidence` — different numbers
   from the same analysis, not two names for one list.

2. fetch_psx_announcements() does NOT scrape dps.psx.com.pk/announcements
   — that page is a client-side-rendered search shell with no
   server-rendered data (confirmed directly: the raw HTML contains only
   the search form, no announcement rows) and a naive guess at its
   backing AJAX endpoint got an immediate WAF block (DOSarrest). Rather
   than keep guessing paths against a third party's protected infra,
   this reuses the exact scraping technique app.py's own
   /announcement-intelligence/{symbol} already uses successfully:
   dps.psx.com.pk/company/{symbol}, which IS server-rendered — looped
   over the report's top symbols.

3. Gemini quota: gemini-3.6-flash's free tier is 20 requests/DAY (see
   ai_overlay.py). One full report run makes 1 synthesis call, so this
   script alone won't exhaust it — but the quota is shared across
   whatever else used the same key today.

4. Market Regime / RS / Fundamentals / News Veto (added for the
   Task-4 integration) reuse the EXISTING "V1" modules already wired
   into app.py (market_regime.py, fundamentals_analyzer.py, news_feed.py
   — do not rebuild these, they already implement the exact spec) —
   NOT rebuilt from scratch here. One honest caveat: market_regime's
   assess_regime()/relative_strength() and fundamentals_analyzer both
   read LIVE-fetched/cached data (data_fetcher.fetch_eod() hits the
   live PSX/Yahoo endpoints; fundamentals.json is whatever
   fundamentals_fetcher.py last cached) — they are NOT re-derived from
   daily_ohlc pinned to target_date the way the rest of this script is.
   So "Market Regime" and "RS Score" reflect conditions as of when this
   report was GENERATED, not strictly the historical target_date
   session. Labeled as such in the PDF rather than silently implied to
   be historically exact.
"""

import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import feedparser
import requests
import smtplib
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fpdf import FPDF

load_dotenv()

import patterns_engine as pe
import psx_brain
from ai_overlay import QuantLLMService
from morning_star_detector import MorningStarDetector

# Task 4: reuse the existing V1 modules already wired into app.py rather
# than rebuilding market regime / fundamentals / news-veto logic here.
import market_regime
import data_fetcher
import news_feed
import fundamentals_fetcher
import fundamentals_analyzer
from fundamentals_analyzer import analyze as analyze_fundamentals

BACKEND_DIR = Path(__file__).parent
DB_PATH = BACKEND_DIR / "psx_v2.db"
PDF_PATH = BACKEND_DIR / "psx_daily_report.pdf"

LIQUIDITY_MIN_VOLUME = 100_000
DSS_TECH_THRESHOLD_TOP_N = 10
VOLUME_ANOMALY_MULT = 2.0
VOLUME_ANOMALY_LOOKBACK = 20
NEWS_FETCH_TIMEOUT = 12
NEWS_ENTRIES_PER_QUERY = 8
TRUSTED_DOMAINS = ("brecorder.com", "dawn.com", "profit.pakistantoday.com.pk",
                    "tribune.com.pk", "mettisglobal.news")

HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

_morning_star_detector = MorningStarDetector()


# ============================================================================
# TASK 2 — full market sweep, ranking, pattern breakouts, volume anomalies
# ============================================================================

def _all_symbols(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM daily_ohlc").fetchall()]


def _symbol_rows(conn, symbol):
    raw = conn.execute(
        "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
        "WHERE symbol=? ORDER BY trade_date ASC", (symbol,)).fetchall()
    return [{"trade_date": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "volume": r[5]} for r in raw]


def _volume_anomaly(rows, target_date):
    """20-session SMA of volume computed over the sessions strictly BEFORE
    target_date (no lookahead into the anomaly's own reference window).
    Returns None if there's no target_date row or insufficient history."""
    idx = next((i for i, r in enumerate(rows) if r["trade_date"] == target_date), None)
    if idx is None or idx < VOLUME_ANOMALY_LOOKBACK:
        return None
    window = rows[idx - VOLUME_ANOMALY_LOOKBACK: idx]
    avg_vol = sum(r["volume"] for r in window) / len(window)
    if avg_vol <= 0:
        return None
    today = rows[idx]
    ratio = today["volume"] / avg_vol
    if ratio < VOLUME_ANOMALY_MULT:
        return None
    direction = "Accumulation" if today["close"] > today["open"] else \
                "Distribution" if today["close"] < today["open"] else "Neutral"
    return {"volume_ratio": round(ratio, 2), "avg_volume_20d": round(avg_vol),
            "classification": direction}


def run_market_sweep(target_date):
    """Returns a dict: top_technical, top_dss, pattern_breakouts,
    smart_money_movers, universe_scanned, universe_after_liquidity_filter."""
    conn = sqlite3.connect(DB_PATH)
    symbols = _all_symbols(conn)
    print(f"Sweeping {len(symbols)} symbols in daily_ohlc for {target_date}...")

    scored, breakouts, movers = [], [], []
    as_of_cutoff = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    n_liquid = 0

    for i, sym in enumerate(symbols):
        rows = _symbol_rows(conn, sym)
        session = next((r for r in rows if r["trade_date"] == target_date), None)
        if session is None or session["volume"] < LIQUIDITY_MIN_VOLUME:
            continue
        n_liquid += 1

        idx = rows.index(session)
        if idx < 200:  # not enough history for psx_brain's SMA200/weekly resample to be meaningful
            continue
        try:
            df_slice = _rows_to_df(rows[: idx + 1])
            r = psx_brain.analyse(sym, df_slice, bench=None, partial="raw")
            scored.append({"symbol": sym, "technical_score": r["score"],
                            "dss_confidence": r["confidence"], "verdict": r["verdict"],
                            "price": r["price"]})
        except Exception:
            pass

        for detector_name, fn in (("Bullish Engulfing", pe.detect_bullish_engulfing),
                                   ("Bearish Engulfing", pe.detect_bearish_engulfing),
                                   ("Three-Line Strike", pe.detect_three_line_strike)):
            try:
                res = fn(rows, date_key="trade_date", as_of=as_of_cutoff)
                if res.get("detected") and res.get("pattern_date") == target_date:
                    breakouts.append({"symbol": sym, "pattern": detector_name,
                                      "classification": res.get("classification")})
            except Exception:
                pass

        anomaly = _volume_anomaly(rows, target_date)
        if anomaly:
            movers.append({"symbol": sym, **anomaly})

        if (i + 1) % 100 == 0:
            print(f"  ...{i+1}/{len(symbols)} symbols scanned")

    # Morning Star -- detect_patterns() over the target_date's window, filtered to that date
    for sym in symbols:
        rows = _symbol_rows(conn, sym)
        session = next((r for r in rows if r["trade_date"] == target_date), None)
        if session is None or session["volume"] < LIQUIDITY_MIN_VOLUME:
            continue
        try:
            import pandas as pd
            idx = rows.index(session)
            if idx < 3:
                continue
            # MorningStarDetector wants a plain frame with a trade_date
            # COLUMN (string dates), not the DatetimeIndex frame
            # _rows_to_df() builds for psx_brain -- matches app.py's own
            # working usage: pd.DataFrame(rows) straight from ohlc_rows().
            df = pd.DataFrame(rows[: idx + 1])
            result = _morning_star_detector.detect_patterns(df, date_col="trade_date")
            if not result.empty:
                hit = result[result["date"].astype(str).str[:10] == target_date]
                if not hit.empty:
                    breakouts.append({"symbol": sym, "pattern": "Morning Star",
                                      "classification": hit.iloc[0]["strength_rating"]})
        except Exception:
            pass

    # Inverse H&S / Double Bottom -- reuse the already-cached market-wide scan,
    # filter to signals whose own signal_date is this target_date.
    try:
        from app import _run_advanced_pattern_scan_default
        adv = _run_advanced_pattern_scan_default()
        for h in adv.get("hits", []):
            if h.get("signal_date") == target_date:
                breakouts.append({"symbol": h["symbol"], "pattern": h.get("pattern_type"),
                                  "classification": h.get("pattern_subtype")})
    except Exception as e:
        print(f"  Advanced pattern scan unavailable: {type(e).__name__}: {e}")

    conn.close()
    top_technical = sorted(scored, key=lambda x: -x["technical_score"])[:DSS_TECH_THRESHOLD_TOP_N]
    top_dss = sorted(scored, key=lambda x: -x["dss_confidence"])[:DSS_TECH_THRESHOLD_TOP_N]
    print(f"Sweep complete: {n_liquid} passed the liquidity filter, {len(scored)} scored, "
          f"{len(breakouts)} pattern breakout(s), {len(movers)} smart-money mover(s).")
    return {"top_technical": top_technical, "top_dss": top_dss,
            "pattern_breakouts": breakouts, "smart_money_movers": movers,
            "universe_scanned": len(symbols), "universe_after_liquidity_filter": n_liquid}


def _rows_to_df(rows):
    import pandas as pd
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["trade_date"])
    return df.set_index("date")[["open", "high", "low", "close", "volume"]]


# ============================================================================
# TASK 3 — macro-intelligence gathering (Google News RSS search — no API
# key required; feedparser reads it like any other RSS feed)
# ============================================================================

def _google_news_rss(query, limit=NEWS_ENTRIES_PER_QUERY):
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-PK&gl=PK&ceid=PK:en"
    try:
        d = feedparser.parse(url, request_headers=HEAD)
        return [{"title": e.title, "source": getattr(e, "source", {}).get("title", ""),
                 "published": getattr(e, "published", "")} for e in d.entries[:limit]]
    except Exception as e:
        print(f"  [macro-intel] RSS fetch failed for '{query}': {type(e).__name__}: {e}")
        return []


def fetch_macro_news():
    return _google_news_rss("State Bank of Pakistan OR SBP OR Crude Oil OR US Iran OR Imran Khan")


def fetch_sector_news():
    return _google_news_rss("Refinery policy OR Gas circular debt OR Fertilizer OR FIPI LIPI Pakistan")


def fetch_trusted_stock_news(symbol):
    site_filter = " OR ".join(f"site:{d}" for d in TRUSTED_DOMAINS)
    query = f"{symbol} Pakistan stock ({site_filter})"
    return _google_news_rss(query, limit=5)


def fetch_psx_announcements(symbols):
    """See module docstring point 2 — reuses the same server-rendered
    dps.psx.com.pk/company/{symbol} page app.py's own
    /announcement-intelligence/{symbol} scrapes, looped over `symbols`.
    A symbol whose page fails to fetch/parse is skipped, not fatal."""
    out = {}
    for sym in symbols:
        try:
            resp = requests.get(f"https://dps.psx.com.pk/company/{sym.upper()}",
                                headers=HEAD, timeout=NEWS_FETCH_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            items = []
            for tr in soup.select("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.select("td")]
                if len(cells) >= 2 and any(k in cells[1].lower() for k in
                        ["financial", "material", "board", "dividend", "report", "meeting"]):
                    items.append({"date": cells[0][:40], "title": cells[1][:200]})
            out[sym] = items[:5]
        except Exception as e:
            print(f"  [announcements] {sym}: {type(e).__name__}: {e} — skipped")
            out[sym] = []
        time.sleep(0.5)
    return out


def gather_intelligence(top_symbols):
    print("Fetching macro news...")
    macro = fetch_macro_news()
    print("Fetching sector news...")
    sector = fetch_sector_news()
    print(f"Fetching trusted-source news for {len(top_symbols)} top symbols...")
    stock_news = {}
    for sym in top_symbols:
        stock_news[sym] = fetch_trusted_stock_news(sym)
        time.sleep(0.3)
    print("Fetching PSX company announcements for top symbols...")
    announcements = fetch_psx_announcements(top_symbols)
    return {"macro_news": macro, "sector_news": sector,
            "stock_news": stock_news, "announcements": announcements}


# ============================================================================
# TASK 4 — Gemini synthesis
# ============================================================================

def build_synthesis_prompt(sweep, intel, target_date, regime=None, vetoes=None):
    def _fmt_list(items, keys):
        return "\n".join(" | ".join(f"{k}={it.get(k)}" for k in keys) for it in items) or "(none)"

    regime_line = (regime or {}).get("note", "(regime unavailable)")
    veto_block = "\n".join(
        f"{v['symbol']}: {v.get('summary','')}" for v in (vetoes or [])) or "(none triggered)"
    top_tech = _fmt_list(sweep["top_technical"], ["symbol", "technical_score", "verdict", "price"])
    top_dss = _fmt_list(sweep["top_dss"], ["symbol", "dss_confidence", "verdict", "price"])
    breakouts = _fmt_list(sweep["pattern_breakouts"], ["symbol", "pattern", "classification"])
    movers = _fmt_list(sweep["smart_money_movers"], ["symbol", "classification", "volume_ratio"])
    macro_titles = "\n".join(f"- {n['title']}" for n in intel["macro_news"]) or "(none fetched)"
    sector_titles = "\n".join(f"- {n['title']}" for n in intel["sector_news"]) or "(none fetched)"
    stock_news_block = "\n".join(
        f"{sym}: " + "; ".join(n["title"] for n in items[:3]) if items else f"{sym}: (no trusted-source hits)"
        for sym, items in intel["stock_news"].items())
    ann_block = "\n".join(
        f"{sym}: " + "; ".join(a["title"] for a in items[:2]) if items else f"{sym}: (no announcements found)"
        for sym, items in intel["announcements"].items())

    return (
        "You are a quantitative research analyst producing an institutional daily brief for "
        f"the PSX (Pakistan Stock Exchange) session of {target_date}. Use ONLY the data below "
        "— never invent a price, score, headline, or company detail not present in it. If a "
        "section has no data, say so plainly rather than fabricating content. Structure your "
        "response into EXACTLY these 5 headed sections, plain text, no markdown formatting "
        "characters (no #, no **):\n\n"
        "SECTION 1: MACRO & GEO-POLITICAL CLIMATE (US-Iran, SBP, Oil, Politics)\n"
        "SECTION 2: SECTOR CATALYSTS & INSTITUTIONAL FLOW (Gas, Refineries, FIPI/LIPI context)\n"
        "SECTION 3: SMART MONEY FOOTPRINTS (analyze the Accumulation/Distribution list)\n"
        "SECTION 4: TOP TECHNICAL PICKS & ASSOCIATED FUNDAMENTAL RISKS (cross-reference the "
        "top technical/DSS picks against their specific news/announcements)\n"
        "SECTION 5: PATTERN BREAKOUT ANALYSIS\n\n"
        f"=== TOP 10 TECHNICAL (by psx_brain raw score) ===\n{top_tech}\n\n"
        f"=== TOP 10 DSS-CONSENSUS (by psx_brain confidence) ===\n{top_dss}\n\n"
        f"=== PATTERN BREAKOUTS ({target_date}) ===\n{breakouts}\n\n"
        f"=== SMART MONEY MOVERS (volume >= {VOLUME_ANOMALY_MULT}x 20-session avg) ===\n{movers}\n\n"
        f"=== MACRO NEWS HEADLINES ===\n{macro_titles}\n\n"
        f"=== SECTOR NEWS HEADLINES ===\n{sector_titles}\n\n"
        f"=== TRUSTED-SOURCE NEWS PER TOP SYMBOL ===\n{stock_news_block}\n\n"
        f"=== PSX COMPANY ANNOUNCEMENTS PER TOP SYMBOL ===\n{ann_block}\n\n"
        f"=== MARKET REGIME ===\n{regime_line}\n\n"
        f"=== MATERIAL BAD-NEWS VETOES TRIGGERED ===\n{veto_block}\n"
    )


# ============================================================================
# TASK 4 — Market Regime, Fundamentals, RS, and Material News Veto (reuses
# the existing market_regime.py / fundamentals_analyzer.py / news_feed.py —
# see module docstring point 4 for the live-vs-historical caveat).
# ============================================================================

def gather_regime_fundamentals_and_vetoes(top_symbols):
    """Returns (regime_dict, {symbol: {fund_score, rs_score}}, [veto dicts])."""
    print("Assessing market regime (live)...")
    try:
        regime = market_regime.assess_regime()
    except Exception as e:
        regime = {"regime": "unknown", "note": f"assess_regime() failed: {type(e).__name__}: {e}"}
    print(f"  Regime: {regime.get('regime')} — {regime.get('note')}")

    index_eod = None
    try:
        index_eod, _ = market_regime.fetch_index()
    except Exception as e:
        print(f"  Benchmark index fetch failed: {type(e).__name__}: {e} — RS scores will be skipped.")

    # ---- Task 2: just-in-time fundamentals fetch. The Top 10 tables are
    # ranked by raw psx_brain score across the WHOLE liquid universe, so
    # which symbols land there varies day to day and routinely misses the
    # curated ~17-name fundamentals.json cache entirely (confirmed: a real
    # run put small/mid-caps like MSOT/TSPL/ABOT/AICL at the top, none of
    # which were cached, so every Fund Score printed 50.0). Rather than
    # pre-seeding an ever-growing static list, fetch ONLY the specific
    # symbols that actually ranked top-10 this run and are missing.
    cached_symbols = set(fundamentals_fetcher.load_cache().get("data", {}))
    missing = [s for s in top_symbols if s not in cached_symbols]
    if missing:
        print(f"Fundamentals cache is missing {len(missing)} top-ranked symbol(s) "
              f"({', '.join(missing)}) — fetching just those, live...")
        session = requests.Session()
        session.headers.update(fundamentals_fetcher.UA)
        new_data = {}
        for sym in missing:
            d = fundamentals_fetcher.fetch(sym, session)
            if d:
                new_data[sym] = d
            print(f"  {sym}: {d or 'no data available from stockanalysis.com'}")
            time.sleep(0.5)  # same politeness delay fetch_all() already uses
        fundamentals_fetcher.merge_and_save(new_data)
        # analyze_fundamentals's cache + sector-peer index were loaded at
        # import time -- reload so the fetch above is actually visible to
        # the scoring loop below, not silently ignored until next process
        # restart.
        fundamentals_analyzer.reload_cache()

    per_symbol = {}
    vetoes = []
    print(f"Scoring fundamentals + RS for {len(top_symbols)} top symbols...")
    for sym in top_symbols:
        fund_score = None
        try:
            fund = analyze_fundamentals(sym)
            fund_score = fund.get("score")
        except Exception as e:
            print(f"  {sym}: fundamentals_analyzer failed: {type(e).__name__}: {e}")

        rs_score = None
        if index_eod is not None:
            try:
                stock_eod, _ = data_fetcher.fetch_eod(sym)
                rs = market_regime.relative_strength(stock_eod, index_eod)
                rs_score = rs.get("rs_score") if rs else None
            except Exception as e:
                print(f"  {sym}: relative_strength failed: {type(e).__name__}: {e}")

        per_symbol[sym] = {"fund_score": fund_score, "rs_score": rs_score}

        try:
            verdict = news_feed.get(sym)
            if verdict and verdict.get("materiality") == "material_negative":
                vetoes.append({"symbol": sym, "summary": verdict.get("summary"),
                               "headlines": verdict.get("headlines", [])[:2]})
        except Exception as e:
            print(f"  {sym}: news_feed.get() failed: {type(e).__name__}: {e}")

    print(f"  {len(vetoes)} material bad-news veto(es) triggered.")
    return regime, per_symbol, vetoes


def generate_synthesis(sweep, intel, target_date, regime=None, vetoes=None):
    prompt = build_synthesis_prompt(sweep, intel, target_date, regime, vetoes)
    svc = QuantLLMService()
    print(f"Requesting Gemini synthesis (is_live={svc.is_live})...")
    result = svc._call_llm(prompt, max_tokens=4096)
    if result is not None:
        return result, True
    return ("[MOCK — Gemini unavailable: no key configured, or the daily quota was hit. "
            "See ai_overlay.py's module docstring for the 20-request/day free-tier limit.] "
            "A live synthesis of the macro climate, sector catalysts, smart-money footprints, "
            "top technical/DSS picks and their news, and pattern breakouts would appear here."), False


# ============================================================================
# TASK 5 — PDF generation & email dispatch
# ============================================================================

def _pdf_safe(text):
    """fpdf2's core 'helvetica' font is Latin-1 only -- strip anything
    outside that range (emoji, curly quotes, arrows) rather than crash
    mid-render on Gemini/news text that may contain them."""
    if text is None:
        return ""
    return str(text).encode("latin-1", errors="ignore").decode("latin-1")


class _ReportPDF(FPDF):
    regime_label = "Market Regime: unavailable"

    def header(self):
        self.set_font("helvetica", "B", 14)
        self.cell(0, 10, _pdf_safe("PSX Daily Intelligence Report"), ln=True)
        self.set_font("helvetica", "", 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, _pdf_safe(f"Session: {self.session_date}  |  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"), ln=True)
        regime_color = (26, 127, 55) if "risk-on" in self.regime_label.lower() else \
                       (192, 57, 43) if "risk-off" in self.regime_label.lower() else (100, 100, 100)
        self.set_font("helvetica", "B", 9)
        self.set_text_color(*regime_color)
        self.cell(0, 6, _pdf_safe(self.regime_label), ln=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def section_title(self, text):
        self.set_font("helvetica", "B", 12)
        self.set_fill_color(230, 230, 230)
        self.cell(0, 8, _pdf_safe(text), ln=True, fill=True)
        self.ln(1)

    def body_text(self, text):
        self.set_font("helvetica", "", 10)
        self.multi_cell(0, 5.5, _pdf_safe(text))
        self.ln(2)

    def table_row(self, cells, bold=False, widths=None):
        self.set_font("helvetica", "B" if bold else "", 9)
        widths = widths or [190 / len(cells)] * len(cells)
        for c, w in zip(cells, widths):
            self.cell(w, 6, _pdf_safe(c), border=1)
        self.ln()


def build_pdf(sweep, intel, synthesis, target_date, is_live, regime=None, symbol_scores=None, vetoes=None):
    regime = regime or {}
    symbol_scores = symbol_scores or {}
    vetoes = vetoes or []

    pdf = _ReportPDF()
    pdf.session_date = target_date
    pdf.regime_label = f"Market Regime: {(regime.get('regime') or 'unavailable').upper()}" + \
                       (f" — {regime['note']}" if regime.get("note") else "")
    pdf.add_page()

    pdf.section_title(f"Market Sweep Summary")
    pdf.body_text(
        f"Universe scanned: {sweep['universe_scanned']} symbols. "
        f"{sweep['universe_after_liquidity_filter']} passed the >= {LIQUIDITY_MIN_VOLUME:,}-share "
        f"liquidity filter. {len(sweep['pattern_breakouts'])} pattern breakout(s), "
        f"{len(sweep['smart_money_movers'])} smart-money mover(s) flagged.")

    def _fund(sym):
        s = symbol_scores.get(sym, {}).get("fund_score")
        return f"{s}" if s is not None else "n/a"

    def _rs(sym):
        s = symbol_scores.get(sym, {}).get("rs_score")
        return f"{s}" if s is not None else "n/a"

    pdf.section_title("Top 10 Technical Stocks (psx_brain raw score)")
    pdf.body_text("Fund Score = fundamentals_analyzer.py (0-100, sector-relative blend). "
                   "RS Score = market_regime.py relative strength vs KSE-100 (0-100, 50=in-line). "
                   "Both reflect live/cached data as of report generation, not target_date specifically.")
    pdf.table_row(["Symbol", "Tech Score", "Fund Score", "RS Score", "Verdict"], bold=True,
                  widths=[30, 32, 32, 32, 64])
    for r in sweep["top_technical"]:
        pdf.table_row([r["symbol"], str(r["technical_score"]), _fund(r["symbol"]),
                       _rs(r["symbol"]), r["verdict"]], widths=[30, 32, 32, 32, 64])
    pdf.ln(3)

    pdf.section_title("Top 10 DSS-Consensus Stocks (psx_brain confidence)")
    pdf.table_row(["Symbol", "Confidence", "Fund Score", "RS Score", "Verdict"], bold=True,
                  widths=[30, 32, 32, 32, 64])
    for r in sweep["top_dss"]:
        pdf.table_row([r["symbol"], str(r["dss_confidence"]), _fund(r["symbol"]),
                       _rs(r["symbol"]), r["verdict"]], widths=[30, 32, 32, 32, 64])
    pdf.ln(3)

    pdf.section_title("Risk Analysis — Material Bad-News Vetoes")
    if vetoes:
        pdf.body_text(f"{len(vetoes)} top symbol(s) have a MATERIAL NEGATIVE news verdict "
                       "(news_feed.py, materiality='material_negative') — treat any bullish "
                       "technical/DSS read on these as overridden by fundamental/news risk:")
        for v in vetoes:
            pdf.body_text(f"VETO — {v['symbol']}: {v.get('summary','')}")
    else:
        pdf.body_text("No material bad-news vetoes triggered for the top technical/DSS symbols. "
                       "(Reflects only symbols with a fresh, non-stale news_signals.json entry — "
                       "see news_feed.py's freshness contract.)")
    pdf.ln(3)

    pdf.section_title("Smart Money Footprint (Volume Anomalies)")
    if sweep["smart_money_movers"]:
        pdf.table_row(["Symbol", "Class", "Vol Ratio", "20d Avg Vol"], bold=True, widths=[40, 50, 40, 60])
        for m in sweep["smart_money_movers"][:25]:
            pdf.table_row([m["symbol"], m["classification"], f"{m['volume_ratio']}x",
                           f"{m['avg_volume_20d']:,}"], widths=[40, 50, 40, 60])
    else:
        pdf.body_text("No symbols crossed the 2.0x volume-anomaly threshold this session.")
    pdf.ln(3)

    pdf.section_title("Pattern Breakouts")
    if sweep["pattern_breakouts"]:
        for b in sweep["pattern_breakouts"]:
            pdf.body_text(f"{b['symbol']}: {b['pattern']} ({b['classification']})")
    else:
        pdf.body_text("No pattern breakouts detected for this session.")

    pdf.add_page()
    pdf.section_title(f"AI Synthesis {'(LIVE Gemini)' if is_live else '(MOCK — see note below)'}")
    for line in re.split(r"\n{2,}|(?=SECTION \d)", synthesis):
        line = line.strip()
        if line:
            pdf.body_text(line)

    pdf.output(str(PDF_PATH))
    print(f"PDF written to {PDF_PATH}")
    return PDF_PATH


def send_report_email(pdf_path, target_date):
    if not all([SMTP_SERVER, SMTP_USER, SMTP_PASSWORD, RECIPIENT_EMAIL]):
        missing = [n for n, v in [("SMTP_SERVER", SMTP_SERVER), ("SMTP_USER", SMTP_USER),
                                   ("SMTP_PASSWORD", SMTP_PASSWORD), ("RECIPIENT_EMAIL", RECIPIENT_EMAIL)] if not v]
        reason = f"Missing required .env variable(s): {', '.join(missing)}."
        print(f"[pdf_reporter] {reason} Email NOT sent.")
        return {"status": "error", "reason": reason}

    msg = MIMEMultipart()
    msg["Subject"] = f"PSX Daily Intelligence Report — {target_date}"
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(
        f"Attached: the institutional PSX intelligence brief for {target_date}.", "plain"))
    with open(pdf_path, "rb") as f:
        part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=Path(pdf_path).name)
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"[pdf_reporter] Report emailed to {RECIPIENT_EMAIL}.")
        return {"status": "ok", "recipient": RECIPIENT_EMAIL}
    except smtplib.SMTPAuthenticationError as e:
        reason = f"SMTP authentication failed: {e}"
        print(f"[pdf_reporter] {reason}")
        return {"status": "error", "reason": reason}
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        print(f"[pdf_reporter] Email send failed: {reason}")
        return {"status": "error", "reason": reason}


def main(target_date="2026-08-28"):
    sweep = run_market_sweep(target_date)
    top_symbols = sorted({r["symbol"] for r in sweep["top_technical"] + sweep["top_dss"]})
    intel = gather_intelligence(top_symbols)
    regime, symbol_scores, vetoes = gather_regime_fundamentals_and_vetoes(top_symbols)
    synthesis, is_live = generate_synthesis(sweep, intel, target_date, regime, vetoes)
    pdf_path = build_pdf(sweep, intel, synthesis, target_date, is_live, regime, symbol_scores, vetoes)
    result = send_report_email(pdf_path, target_date)
    print(f"\nFinal result: {result}")
    return result


if __name__ == "__main__":
    main()
