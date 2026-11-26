"""Dated PDF daily patterns report: the Chart Patterns, Patterns and Breakouts tabs only.

FIRE Engine content is excluded on purpose (no fire_scan, no FIRE-tagged rows).

Headings, table titles, column labels, row order and default filters follow the app's
Streamlit tabs (streamlit_app.py and vol_engine_ui.py). Defaults mirror the app:
  - Wyckoff v1: WATCH / READY / EXTREME rows only.
  - Candlestick and IHS / Double Bottom / Head & Shoulders tables: rows dated within the
    last 14 days of the session (the app's "Show Historical Signals" is off by default).
  - Volatility tables: liquidity = Highly Liquid + Liquid + Moderate Liquidity.
  - Wyckoff x Volatility: "Wyckoff signals only" (WATCH / READY / EXTREME, not stale).

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
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Top-level headings, in report order. Only these three app tabs are in the PDF.
GROUP_ORDER = ("Chart Patterns", "Patterns", "Breakouts")
RECENT_DAYS = 14  # the app's RECENT_SIGNAL_DAYS
LIQUIDITY_DEFAULT = ("Highly Liquid", "Liquid", "Moderate Liquidity")
WYCKOFF_SIGNALS = ("WATCH", "READY", "EXTREME")
DATE_KEYS = ("pattern_date", "signal_date", "date")
FIRE_TOKEN = "FIRE"
MAX_CELL = 300

# Chart Patterns tab: these four Bulkowski patterns only, each as a CONFIRMED and a FORMING table.
CHART_PATTERN_NAMES = ("CUP_WITH_HANDLE", "HIGH_TIGHT_FLAG_PSX", "PIPE_BOTTOM_1D", "BROADENING_BOTTOM")
CHART_STATES = ("CONFIRMED", "FORMING")
CHART_COLUMNS = [
    ("Symbol", ["symbol"]), ("Pattern", ["pattern"]), ("State", ["state"]), ("Signal Date", ["signal_date"]),
    ("RVOL", ["rvol"]), ("Median20 PKR", ["median20_pkr"]), ("Clear_Runway %", ["clear_runway_pct"]),
    ("Runway flag", ["runway_flag"]), ("Suggested Stop", ["suggested_stop"]),
    ("Breadth %", ["universe_breadth_pct"]),
]

PHASE_D_SUB = "Phase D Breakout & Shelf Tracker"
PHASE_D_COLUMNS = [
    ("Symbol", ["symbol"]), ("Stage / Action Status", ["status"]), ("Price", ["price"]), ("Day %", ["day_pct"]),
    ("RVOL", ["rvol"]), ("Shelf Ceiling", ["ceiling"]), ("Day", ["day"]), ("Turnover", ["turnover"]),
    ("Setup Grade", ["setup_grade"]), ("Price Tier", ["price_tier"]),
]

MARKET_BEHAVIOUR_SUB = "Market Behaviour"
MARKET_BEHAVIOUR_TITLE = "Wyckoff Institutional Accumulation"
WYCKOFF_V1_COLUMNS = [("Symbol", ["symbol"]), ("Company", ["company"]), ("Signal", ["signal"]),
                      ("Score", ["score"]), ("Price", ["price"])]

LONG_COLUMNS = [("Symbol", ["symbol"]), ("Company", ["company"]), ("Action", ["action"]), ("Date", ["date"]),
                ("Stop", ["stop"]), ("Target", ["target"]), ("R:R", ["rr"])]
SHORT_COLUMNS = [("Symbol", ["symbol"]), ("Company", ["company"]), ("Action", ["action"]),
                 ("Entry", ["entry"]), ("Stop-Loss (Risk)", ["stop"]), ("Target (Reward)", ["target"]),
                 ("Date", ["date"])]
STRUCTURAL_SUB = "Structural Patterns"
STRUCTURAL_TITLE = "Chart Patterns (IHS, Double Bottom & Head/Shoulders Top)"
STRUCTURAL_COLUMNS = [("Symbol", ["symbol"]), ("Company", ["company"]), ("Pattern", ["pattern"]),
                      ("Action", ["action"]), ("Entry", ["entry"]), ("Stop-Loss (Risk)", ["stop"]),
                      ("Target (Reward)", ["target"]), ("R:R", ["rr"]), ("Date", ["date"])]
ADV_PATTERN_LABELS = {"INVERSE_HS": "Inverse Head & Shoulders", "DOUBLE_BOTTOM": "Double Bottom",
                      "HEAD_SHOULDERS_TOP": "Head & Shoulders Top"}

VOL_SUB = "Volatility Intelligence"
EARLY_COLUMNS = [("Symbol", ["symbol"]), ("Company", ["company"]), ("Price", ["price"]),
                 ("Last Candle", ["last_candle"]), ("Compression", ["compression"]),
                 ("BBW pct (100d)", ["bbw_pct"]), ("ATR pct (100d)", ["atr_pct"]), ("Squeeze days", ["squeeze_d"])]
EXPANSION_COLUMNS = [("Rank", ["rank"]), ("Symbol", ["symbol"]), ("Company", ["company"]), ("Price", ["price"]),
                     ("Last Candle", ["last_candle"]), ("Compression", ["compression"]), ("Evidence", ["evidence"]),
                     ("Expansion", ["expansion"]), ("BBW pct (100d)", ["bbw_pct"]), ("ATR pct (100d)", ["atr_pct"]),
                     ("Rel. Volume", ["rel_vol"]), ("Break Level", ["break_level"]), ("Support", ["support"]),
                     ("Resistance", ["resistance"]), ("Stage", ["stage"]), ("History", ["history"]),
                     ("Liquidity", ["liquidity"])]
WYCKOFF_VOL_COLUMNS = [("Symbol", ["symbol"]), ("Company", ["company"]), ("Price", ["price"]),
                       ("Last Candle", ["last_candle"]), ("Stale", ["stale"]), ("Wyckoff Score", ["wyckoff_score"]),
                       ("Wyckoff", ["wyckoff"]), ("4h BB Compression", ["bb4h"]), ("Supply Exhaustion", ["supply_exh"]),
                       ("Absorption", ["absorption"]), ("OBV Divergence", ["obv_div"]),
                       ("Compression", ["compression"]), ("Bull", ["bull"]), ("Bear", ["bear"]),
                       ("Expansion Bull", ["expansion_bull"]), ("Expansion Bear", ["expansion_bear"]),
                       ("Stage", ["stage"]), ("Confluence", ["confluence"]), ("Conflict", ["conflict"]),
                       ("History", ["history"]), ("Liquidity", ["liquidity"])]
VALIDATION_COLUMNS = [("Setup", ["setup"]), ("N", ["n"]), ("Sufficient", ["sufficient"]),
                      ("P(up 10d)%", ["p_up"]), ("Mean 10d%", ["mean10"]), ("Median 10d%", ["median10"]),
                      ("Long target-first%", ["long_tf"]), ("Long expectancy%", ["long_exp"]), ("Long PF", ["long_pf"]),
                      ("Short target-first%", ["short_tf"]), ("Short expectancy%", ["short_exp"]),
                      ("OOS n", ["oos_n"]), ("OOS mean 10d%", ["oos_mean10"]),
                      ("OOS long expectancy%", ["oos_long_exp"])]

WYCKOFF2_SUB = "Wyckoff Institutional Accumulation 2.0 (RESEARCH)"
WYCKOFF2_COLUMNS = [("Symbol", ["symbol"]), ("Company", ["company"]), ("Price", ["price"]), ("Day %", ["day"]),
                    ("Original Score", ["orig_score"]), ("Original Class", ["orig_class"]),
                    ("Enhanced Class", ["enh_class"])]


def _dir(d):
    """Direction split: keep one side of a BULL/BEAR cache list. No direction field -> no rows."""
    def f(rows):
        if not any("direction" in r for r in rows):
            return []
        return [r for r in rows if str(r.get("direction", "")).upper() == d]
    return f


def _not_hst(rows):
    return [r for r in rows if str(r.get("pattern_type", "")).upper() != "HEAD_SHOULDERS_TOP"]


def _is_hst(rows):
    return [r for r in rows if str(r.get("pattern_type", "")).upper() == "HEAD_SHOULDERS_TOP"]


def _liq_ok(r):
    return r.get("liquidity") in LIQUIDITY_DEFAULT


def _is_stale(r):
    return bool(r.get("stale"))


def _vol_early(rows):
    out = [r for r in rows if not _is_stale(r) and _liq_ok(r)
           and (r.get("stage") in (1, 2) or (r.get("compression_score") or 0) >= 50)]
    return sorted(out, key=lambda r: -(r.get("compression_score") or 0))


def _vol_expansion(sgn):
    k = "bull" if sgn > 0 else "bear"

    def f(rows):
        out = [r for r in rows if not _is_stale(r) and _liq_ok(r)
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
        return []
    return [r for r in rows if str(r.get(field, "")).upper() in WYCKOFF_SIGNALS and not _is_stale(r)]


# Patterns > Long-Side and Short-Side candlestick and scan tables, in the app's order.
# (title, analysis_cache key, row transform, side, app empty-state text)
LONG_TABS = [
    ("OBV+MFI Setup with ATR Contraction", "obv_mfi_scan", None, "BULL",
     "No symbol currently shows an OBV+MFI setup with ATR contraction on its latest completed daily candles."),
    ("Bullish Engulfing", "bullish_engulfing_scan", None, "BULL",
     "No symbol currently shows Bullish Engulfing geometry on its latest completed daily candles."),
    ("Morning Star", "morning_star_scan", None, "BULL",
     "No symbol currently shows a Morning Star completing on its latest stored daily session."),
    ("Bullish Three-Line Strike", "three_line_strike_scan", None, "BULL",
     "No symbol currently shows a Bullish Three-Line Strike on its latest completed 4-candle window."),
    ("MHarris 5-Bar Reversal (Bullish)", "mharris_scan", _dir("BULL"), "BULL",
     "No symbol currently shows a Bullish 5-bar reversal on its latest completed daily candles."),
    ("Engulfing + Star Confirmed Reversal (Bullish)", "engulfing_star_scan", _dir("BULL"), "BULL",
     "No symbol currently shows a Bullish Engulfing+Star reversal on its latest completed daily candles."),
    ("MACD+EMA200 Trend Resumption (Bullish)", "macdema_scan", _dir("BULL"), "BULL",
     "No symbol currently shows a Bullish MACD+EMA200 trend-resumption on its latest completed daily candles."),
    ("Level Break Out (Resistance Breakout)", "level_breakout_scan", _dir("BULL"), "BULL",
     "No symbol currently shows a resistance breakout on its latest completed daily candles."),
    ("GP-Evolved Formula (Long Bias)", "gp_evolved_scan", _dir("BULL"), "BULL",
     "No symbol currently shows a GP-Evolved Formula long signal on its latest completed daily candles."),
]
SHORT_TABS = [
    ("Bearish Engulfing", "bearish_engulfing_scan", None, "BEAR",
     "No symbol currently shows Bearish Engulfing geometry on its latest completed daily candles."),
    ("Evening Star", "evening_star_scan", None, "BEAR",
     "No symbol currently shows an Evening Star completing on its latest stored daily session."),
    ("MHarris 5-Bar Reversal (Bearish)", "mharris_scan", _dir("BEAR"), "BEAR",
     "No symbol currently shows a Bearish 5-bar reversal on its latest completed daily candles."),
    ("Engulfing + Star Confirmed Reversal (Bearish)", "engulfing_star_scan", _dir("BEAR"), "BEAR",
     "No symbol currently shows a Bearish Engulfing+Star reversal on its latest completed daily candles."),
    ("Regression-Channel Triangle Squeeze", "triangle_regression_scan", None, "BEAR",
     "No symbol currently shows a Regression-Channel Triangle Squeeze on its latest completed daily candles."),
    ("Level Break Out (Support Breakdown)", "level_breakout_scan", _dir("BEAR"), "BEAR",
     "No symbol currently shows a support breakdown on its latest completed daily candles."),
    ("MACD+EMA200 Trend Resumption (Bearish)", "macdema_scan", _dir("BEAR"), "BEAR",
     "No symbol currently shows a Bearish MACD+EMA200 trend-resumption on its latest completed daily candles."),
    ("GP-Evolved Formula (Short Bias)", "gp_evolved_scan", _dir("BEAR"), "BEAR",
     "No symbol currently shows a GP-Evolved Formula short signal on its latest completed daily candles."),
]

_SUBS = {"—": "-", "–": "-", "→": "->", "≥": ">=", "≤": "<=", "×": "x",
         "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "₨": "Rs", "•": "-"}


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


def _first(r, keys):
    for k in keys:
        if r.get(k) not in (None, ""):
            return r[k]
    return None


def _recent(rows, keys, session, days=RECENT_DAYS):
    """The app's default: keep rows dated within `days` of the session. A row with no or an
    unparsable date is kept, as the app keeps it."""
    if not session:
        return rows
    cutoff = (datetime.strptime(session, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    for r in rows:
        d = str(_first(r, keys) or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or d >= cutoff:
            out.append(r)
    return out


def _project(rows, spec):
    """Keep only the table's columns. spec is [(label, [candidate keys])]; the first present key wins."""
    cols = [label for label, _ in spec]
    out = []
    for r in rows:
        out.append({label: next((r[c] for c in cands if c in r), None) for label, cands in spec})
    return cols, out


def _count_line(rows, key, label):
    if not rows:
        return f"{label}: none"
    counts = {}
    for r in rows:
        v = str(r.get(key, "") or "-")
        counts[v] = counts.get(v, 0) + 1
    return f"{label}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def _section(group, sub, title, rows, source, note=None, date=None, spec=None, checklist=None, summary=None,
             empty=None):
    kept = [r for r in rows if not _is_fire(r)]
    empty_text = empty or (f"No rows for {date}" if date else "No rows for this section.")
    if spec is not None:
        cols, out = _project(kept, spec)
    else:
        cols = []
        for r in kept:
            for k in r:
                if k not in cols:
                    cols.append(k)
        out = kept
    return {"group": group, "sub": sub, "title": title, "source": source, "columns": cols,
            "rows": out, "summary": summary or [], "note": note, "excluded_fire": len(rows) - len(kept),
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


def _company_names(names):
    return names or {}


def _candle_rows(rows, names, side):
    """Display rows for a candlestick or scan table. Missing geometry shows '-', never an invented value."""
    out = []
    for r in rows:
        sym = r.get("symbol")
        out.append({
            "symbol": sym, "company": names.get(sym) or "", "action": _action(r, side),
            "date": _first(r, DATE_KEYS), "entry": _first(r, ("entry_price", "entry")),
            "stop": _first(r, ("stop_loss", "stop")), "target": _first(r, ("target_1", "target")),
            "rr": _rr(r),
        })
    return out


def _action(r, side):
    cls = str(r.get("classification") or "").upper()
    word = "BUY SIGNAL" if side == "BULL" else "SHORT SIGNAL"
    if not cls or ("VALID" in cls and "INVALID" not in cls):
        return word
    return "WAIT (No Setup)"


def _rr(r):
    v = _first(r, ("risk_reward_measured", "rr"))
    try:
        return f"{float(v):.1f}x"
    except (TypeError, ValueError):
        return None


def _candle_section(conn, names, session, sub, title, key, transform, side, empty, short):
    spec = SHORT_COLUMNS if short else LONG_COLUMNS
    run_at, rows, meta = _cache_rows(conn, key)
    if meta is None:
        return _section("Patterns", sub, title, [], f"analysis_cache '{key}'",
                        f"cache key '{key}' is not in analysis_cache: no data to show", spec=spec, empty=empty)
    if transform is not None:
        rows = transform(rows)
    rows = _recent([r for r in rows if not _is_fire(r)], DATE_KEYS, session)
    disp = _candle_rows(rows, names, side)
    note = f"cached at {run_at}" if run_at else "cached (no run time stored)"
    if not disp and (meta.get("message") or meta.get("reason")):
        note += f". App message: {meta.get('message') or meta.get('reason')}"
    return _section("Patterns", sub, title, disp, f"analysis_cache '{key}'", note, spec=spec, empty=empty,
                    summary=[_count_line(disp, "action", "Action")])


def _wyckoff_v1_section(conn, names, session_date, session):
    wd = session_date
    if wd is None:
        w = _rows(conn, "SELECT MAX(scan_date) AS d FROM wyckoff_accumulation")
        wd = w[0]["d"] if w else None
    wd = str(wd)[:10] if wd else None
    raw = _rows(conn, "SELECT * FROM wyckoff_accumulation WHERE scan_date = ? "
                      "ORDER BY accumulation_score DESC", (wd,)) if wd else []
    prices = {}
    if wd:
        for r in _rows(conn, "SELECT symbol, close FROM daily_ohlc WHERE substr(trade_date,1,10) = ?", (wd,)):
            prices[r["symbol"]] = r["close"]
    hits = [r for r in raw if str(r.get("signal_type", "")).upper() in WYCKOFF_SIGNALS]
    disp = [{"symbol": r.get("symbol"), "company": names.get(r.get("symbol")) or "",
             "signal": str(r.get("signal_type")).upper(), "score": r.get("accumulation_score"),
             "price": prices.get(r.get("symbol"))} for r in hits]
    return _section("Patterns", MARKET_BEHAVIOUR_SUB, f"{MARKET_BEHAVIOUR_TITLE} (scan {wd or 'none'})", disp,
                    "wyckoff_accumulation (scan_date)",
                    note="WATCH = score 60-69, READY = 70-84, EXTREME = 85+. A pattern-strength score, "
                         "not a probability or profitability claim.",
                    spec=WYCKOFF_V1_COLUMNS, date=wd or "none",
                    empty="No WATCH/READY/EXTREME setups in the most recent completed daily batch.",
                    summary=[_count_line(disp, "signal", "Signal")])


def _structural_section(conn, names, session):
    _, adv, _ = _cache_rows(conn, "advanced_pattern_scan")
    _, hst, _ = _cache_rows(conn, "hstop_scan")
    rows = _not_hst(adv) + hst
    rows = _recent([r for r in rows if not _is_fire(r)], ("signal_date",), session)
    rows.sort(key=lambda r: (str(r.get("signal_date") or ""), str(r.get("symbol") or "")), reverse=True)
    disp = []
    for r in rows:
        sym = r.get("symbol")
        is_hst = str(r.get("pattern_type", "")).upper() == "HEAD_SHOULDERS_TOP"
        disp.append({
            "symbol": sym, "company": names.get(sym) or "",
            "pattern": ADV_PATTERN_LABELS.get(r.get("pattern_type"), str(r.get("pattern_type") or "")),
            "action": "SELL SIGNAL" if is_hst else "BUY SIGNAL",
            "entry": r.get("entry_price"), "stop": r.get("stop_loss"), "target": r.get("target_1"),
            "rr": _rr(r), "date": r.get("signal_date"),
        })
    return _section("Patterns", STRUCTURAL_SUB, STRUCTURAL_TITLE, disp,
                    "advanced_pattern_scan + hstop_scan (analysis_cache)",
                    note=f"Only signals dated within the last {RECENT_DAYS} days, as the app shows by default.",
                    spec=STRUCTURAL_COLUMNS,
                    empty="No Inverse Head & Shoulders, Double Bottom, or Head & Shoulders Top signals right now.",
                    summary=[_count_line(disp, "action", "Action")])


def _hist_cell(h, direction):
    if not h or not h.get("available"):
        return "INSUFFICIENT HISTORICAL EVIDENCE"
    p = h.get("p_up_10d") if direction > 0 else h.get("p_down_10d")
    ci = h.get("p_up_10d_ci") if direction > 0 else h.get("p_down_10d_ci")
    word = "up" if direction > 0 else "down"
    return f"{p}% {word} in 10d [{ci[0]}-{ci[1]}], n={h.get('n')}"


def _vol_sections(conn, names, session):
    run_at, vrows, vmeta = _cache_rows(conn, "volatility_engine_scan")
    fresh = [r for r in vrows if not _is_stale(r)]
    cov = (f"Session {session} · {len(fresh)} stocks with a current candle · "
           f"{len(vrows) - len(fresh)} stale. Liquidity filter: Highly Liquid, Liquid, Moderate Liquidity.")
    sec = []

    def mk(title, columns, disp, empty, note=cov, summary=None):
        src = "analysis_cache 'volatility_engine_scan'"
        if vmeta is None:
            return _section("Patterns", VOL_SUB, title, [], src,
                            "cache key 'volatility_engine_scan' is not in analysis_cache: no data to show",
                            spec=columns, empty=empty)
        return _section("Patterns", VOL_SUB, title, disp, src, note, spec=columns, empty=empty,
                        summary=summary)

    early = _vol_early(vrows)
    sec.append(mk("Early Warning", EARLY_COLUMNS, [{
        "symbol": r.get("symbol"), "company": names.get(r.get("symbol")) or "", "price": r.get("close"),
        "last_candle": _first(r, ("last_bar_date", "date")), "compression": r.get("compression_score"),
        "bbw_pct": r.get("bbw_pct100"), "atr_pct": r.get("atr_pct100"), "squeeze_d": r.get("squeeze_run"),
    } for r in early], "No symbol currently shows an early-warning compression setup."))

    for title, sgn, empty in (
            ("Bullish Expansion", 1, "No symbol currently shows a bullish volatility expansion."),
            ("Bearish Expansion", -1, "No symbol currently shows a bearish volatility expansion.")):
        k = "bull" if sgn > 0 else "bear"
        rows = _vol_expansion(sgn)(vrows)
        disp = [{
            "rank": i + 1, "symbol": r.get("symbol"), "company": names.get(r.get("symbol")) or "",
            "price": r.get("close"), "last_candle": _first(r, ("last_bar_date", "date")),
            "compression": r.get("compression_score"), "evidence": r.get(f"{k}_score"),
            "expansion": r.get(f"{k}_expansion_score"), "bbw_pct": r.get("bbw_pct100"),
            "atr_pct": r.get("atr_pct100"), "rel_vol": r.get("rv20"),
            "break_level": r.get("break_level") or (r.get("box_hi") if sgn > 0 else r.get("box_lo")),
            "support": r.get("box_lo"), "resistance": r.get("box_hi"), "stage": r.get("stage_detail"),
            "history": _hist_cell(r.get("hist"), sgn), "liquidity": r.get("liquidity"),
        } for i, r in enumerate(rows)]
        sec.append(mk(title, EXPANSION_COLUMNS, disp, empty))

    _, wrows, wmeta = _cache_rows(conn, "volatility_wyckoff_combined")
    wv = _wyckoff_signal_only(wrows)
    wdisp = [{
        "symbol": r.get("symbol"), "company": names.get(r.get("symbol")) or "", "price": r.get("close"),
        "last_candle": r.get("last_bar_date"), "stale": "Yes" if _is_stale(r) else "No",
        "wyckoff_score": r.get("wyckoff_score"), "wyckoff": r.get("wyckoff_signal"),
        "bb4h": r.get("wy_bb4h_compression"), "supply_exh": r.get("wy_supply_exhaustion"),
        "absorption": r.get("wy_absorption"), "obv_div": r.get("wy_obv_divergence"),
        "compression": r.get("compression_score"), "bull": r.get("bull_score"), "bear": r.get("bear_score"),
        "expansion_bull": r.get("bull_expansion_score"), "expansion_bear": r.get("bear_expansion_score"),
        "stage": r.get("stage_detail"), "confluence": r.get("confluence"), "conflict": r.get("conflict"),
        "history": (r.get("hist") or {}).get("label") or "INSUFFICIENT HISTORICAL EVIDENCE",
        "liquidity": r.get("liquidity"),
    } for r in wv]
    sec.append(_section("Patterns", VOL_SUB, "Wyckoff x Volatility",
                        wdisp, "analysis_cache 'volatility_wyckoff_combined'",
                        note="Shows: Wyckoff signals only (WATCH/READY/EXTREME, not stale). Wyckoff's score and "
                             "class are the existing engine's output; the volatility scores are separate.",
                        spec=WYCKOFF_VOL_COLUMNS,
                        empty="No stock matches this view today: no WATCH/READY/EXTREME Wyckoff signal."))

    alerts = [a for a in (vmeta or {}).get("alerts") or [] if isinstance(a, dict)]
    akeys = []
    for a in alerts:
        for k in a:
            if k not in akeys:
                akeys.append(k)
    aspec = [(k.replace("_", " ").title(), [k]) for k in akeys]
    sec.append(_section("Patterns", VOL_SUB, "Alerts", alerts, "analysis_cache 'volatility_engine_scan' (alerts)",
                        note="Only condition CHANGES since the previous daily run are listed.",
                        spec=aspec or None,
                        empty="No new alerts: no symbol's condition changed since the previous run."))

    _, _, smeta = _cache_rows(conn, "volatility_engine_stats")
    sdisp = _validation_rows(smeta) if smeta and smeta.get("status") == "ok" else []
    snote = None
    if smeta and smeta.get("status") == "ok":
        snote = (f"Run {str(smeta.get('run_at'))[:16]} UTC · {smeta.get('universe')} symbols · "
                 f"{smeta.get('data_from')} to {smeta.get('data_to')} · out-of-sample after "
                 f"{(smeta.get('splits') or {}).get('validation_to')} · cost "
                 f"{(smeta.get('assumptions') or {}).get('cost_round_trip_pct')}% round trip")
    sec.append(_section("Patterns", VOL_SUB, "Historical Validation", sdisp,
                        "analysis_cache 'volatility_engine_stats'", snote, spec=VALIDATION_COLUMNS,
                        empty=(smeta or {}).get("reason") or "Not run yet."))
    return sec


def _validation_rows(stats):
    out = []
    by_split = stats.get("by_split") or {}
    for k, g in (stats.get("groups") or {}).items():
        g = g or {}
        o = (by_split.get(k) or {}).get("oos") or {}
        la = g.get("long_atr") or {}
        sa = g.get("short_atr") or {}
        out.append({"setup": k, "n": g.get("n"), "sufficient": g.get("sufficient"), "p_up": g.get("p_up_10d"),
                    "mean10": g.get("mean_10d"), "median10": g.get("median_10d"),
                    "long_tf": la.get("target_first_pct"), "long_exp": la.get("expectancy"),
                    "long_pf": la.get("profit_factor"), "short_tf": sa.get("target_first_pct"),
                    "short_exp": sa.get("expectancy"), "oos_n": o.get("n"), "oos_mean10": o.get("mean_10d"),
                    "oos_long_exp": (o.get("long_atr") or {}).get("expectancy")})
    return out


def _wyckoff2_section(conn, names):
    run_at, rows, meta = _cache_rows(conn, "wyckoff2_research_scan")
    disp = [{"symbol": r.get("symbol"), "company": names.get(r.get("symbol")) or "", "price": r.get("close"),
             "day": r.get("chg_pct"), "orig_score": r.get("orig_score"), "orig_class": r.get("orig_class"),
             "enh_class": r.get("enh_class")} for r in rows]
    note = (f"cached at {run_at}" if meta is not None else
            "cache key 'wyckoff2_research_scan' is not in analysis_cache: no data to show")
    return _section("Patterns", WYCKOFF2_SUB, "Enhanced-class table (research)", disp,
                    "analysis_cache 'wyckoff2_research_scan'",
                    note=note + ". EXPERIMENTAL / NOT PRODUCTION: research scores are heuristics (0-100), not probabilities.",
                    spec=WYCKOFF2_COLUMNS,
                    empty="No symbol currently shows an enhanced Wyckoff 2.0 class in the research scan.")


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
    summary = [f"Shelf Breakouts: {n['SHELF_BREAKOUT']}", f"SOS Ignitions: {n['SOS_IGNITION']}",
               f"Active Shelves: {n['ACTIVE_SHELF']}"]
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
        "day_pct": h.get("pct_change"), "rvol": h.get("rvol"), "ceiling": h.get("base_or_shelf_high"),
        "day": f"{int(h.get('shelf_days') or 0)}/{pdt.MAX_SHELF_DAY}",
        "turnover": pdt.fmt_turnover(h.get("turnover_pkr")),
        "setup_grade": h.get("setup_grade") or "", "price_tier": h.get("price_tier") or "",
    } for h in hits]
    note = (f"Last completed scan: {pd_date or 'none'} · {len(recs)} stock(s), closest to an entry first: "
            "breakouts today, shelves in their final days (9-12), shelves still building (3-8), then fresh "
            "ignitions.")
    return _section("Breakouts", PHASE_D_SUB, f"Phase D breakouts and shelves (session {pd_date or 'none'})",
                    recs, "phase_d_signals (scan_date)", note=note, date=pd_date or "none", spec=PHASE_D_COLUMNS,
                    checklist=checklist, summary=summary,
                    empty=f"No symbol currently shows a shelf breakout, SOS ignition or active shelf for {pd_date or 'none'}.")


def load_company_names():
    """{SYMBOL: official name} from the PSX symbol directory the app uses. Empty on any failure:
    the Company column then stays blank rather than guessing."""
    try:
        backend = os.path.join(ROOT, "backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)
        import names as _names
        m = _names.load() or {}
        return {k: (v or {}).get("name") or "" for k, v in m.items()}
    except Exception:
        return {}


def report_filename(session_date):
    return f"PSX_Daily_Report_{session_date}.pdf"


def collect_sections(conn, root_dir=ROOT, session_date=None, names=None):
    """Read every section through the guarded connection. Returns (session_date, sections).

    session_date (YYYY-MM-DD) pins the report to that session instead of MAX(...) for the
    header, the file name, phase_d_signals and wyckoff_accumulation. None keeps the default.
    names maps SYMBOL -> company name; None loads the PSX directory (see load_company_names).
    """
    conn = conn if isinstance(conn, ReadOnlyConnection) else ReadOnlyConnection(conn)
    if names is None:
        names = load_company_names()
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

    # Chart Patterns tab: the Bulkowski scan (shared helper), four patterns only, one CONFIRMED and
    # one FORMING table, sorted as the app sorts them (Signal Date desc, Symbol).
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
                                 date=session, spec=CHART_COLUMNS,
                                 empty=f"No symbol currently shows a {state} chart pattern."))

    # Patterns, in the app's order: Market Behaviour, Long-Side, Short-Side, Structural, Volatility,
    # then Wyckoff 2.0 research.
    sections.append(_wyckoff_v1_section(conn, names, session_date, session))
    for title, key, transform, side, empty in LONG_TABS:
        sections.append(_candle_section(conn, names, session, "Long-Side (Bullish)", title, key, transform,
                                        side, empty, short=False))
    for title, key, transform, side, empty in SHORT_TABS:
        sections.append(_candle_section(conn, names, session, "Short-Side (Bearish)", title, key, transform,
                                        side, empty, short=True))
    sections.append(_structural_section(conn, names, session))
    sections.extend(_vol_sections(conn, names, session))
    sections.append(_wyckoff2_section(conn, names))

    # Breakouts: Phase D summary, table and per-stock checklist.
    sections.append(_breakouts_section(conn, session_date))

    # Top-level order is fixed: Chart Patterns, Patterns, Breakouts (stable sort keeps sub-order).
    sections.sort(key=lambda s: GROUP_ORDER.index(s["group"]))
    return session, sections


def _safe(s):
    for k, v in _SUBS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _cell(v):
    """Display text for one table cell, as the app formats it: 2 decimals with thousands separators,
    fixed-point only (never scientific notation), Yes/No for booleans, '-' for a missing value."""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return "-"
        if v != 0 and abs(v) < 0.01:
            return f"{v:.6f}"
        return f"{v:,.2f}"
    s = str(v).replace("\n", " ").strip()
    if not s:
        return "-"
    if len(s) > MAX_CELL:
        s = s[:MAX_CELL - 3] + "..."
    return _safe(s)


# Palette and badge mapping (styling only; text and data are never changed here).
NAVY_HEX = "#0f172a"
TEAL_HEX = "#14b8a6"
ZEBRA_HEX = "#f4f7f9"
INK_HEX = "#1e293b"
MUTED_HEX = "#64748b"
RULE_HEX = "#e2e8f0"
BADGE_COLUMNS = ("Action", "Signal", "State")
# value -> (text colour, pill fill)
BADGE_STYLES = {
    "BUY SIGNAL": ("#15803d", "#dcfce7"),
    "CONFIRMED": ("#15803d", "#dcfce7"),
    "READY": ("#15803d", "#dcfce7"),
    "EXTREME": ("#15803d", "#dcfce7"),
    "SHORT SIGNAL": ("#b91c1c", "#fee2e2"),
    "WAIT": ("#64748b", "#e2e8f0"),
    "WATCH": ("#b45309", "#fef3c7"),
}
_NUM_RE = re.compile(r"^[-+]?\d[\d,]*(\.\d+)?%?$")


def badge_style(value):
    """(text colour, fill colour) for a pill badge, or None when the value is not a badge."""
    return BADGE_STYLES.get(str(value or "").strip().upper())


def _numeric_column(texts):
    hits = [t for t in texts if t != "-"]
    return bool(hits) and all(_NUM_RE.match(t) for t in hits)


def render_pdf(path, session_date, sections, generated_at=None):
    """Write the report to `path`. `sections` are dicts from _section(). Returns (path, pages, bytes)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas as _cv
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable,
                                    KeepTogether, HRFlowable)
    from xml.sax.saxutils import escape as _esc

    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = landscape(A4)
    margin = 14 * mm
    width = page[0] - 2 * margin
    NAVY, TEAL = colors.HexColor(NAVY_HEX), colors.HexColor(TEAL_HEX)
    ZEBRA, INK, MUTED = colors.HexColor(ZEBRA_HEX), colors.HexColor(INK_HEX), colors.HexColor(MUTED_HEX)
    RULE, WHITE = colors.HexColor(RULE_HEX), colors.white
    header_text = f"PSX Daily Patterns Report  |  Session {session_date}  |  Generated {generated_at}"
    total_rows = sum(len(s["rows"]) for s in sections)

    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=28, leading=32, textColor=WHITE)
    cover_meta = ParagraphStyle("cover_meta", fontName="Helvetica", fontSize=9, leading=13,
                                textColor=colors.HexColor("#cbd5e1"))
    kicker = ParagraphStyle("kicker", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=TEAL)
    grp = ParagraphStyle("grp", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=NAVY)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=NAVY,
                        spaceBefore=4, spaceAfter=4)
    ttl = ParagraphStyle("ttl", fontName="Helvetica-BoldOblique", fontSize=10, leading=13, textColor=NAVY,
                         spaceAfter=2)
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK)
    tiny = ParagraphStyle("tiny", fontName="Helvetica", fontSize=7, leading=9, textColor=MUTED)
    mono = ParagraphStyle("mono", fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.2, leading=9, textColor=INK)
    cell_r = ParagraphStyle("cell_r", parent=cell, alignment=TA_RIGHT)
    hcell = ParagraphStyle("hcell", parent=cell, fontName="Helvetica-Bold", textColor=WHITE)
    hcell_r = ParagraphStyle("hcell_r", parent=hcell, alignment=TA_RIGHT)
    kpi_num = ParagraphStyle("kpi_num", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=NAVY)
    kpi_lbl = ParagraphStyle("kpi_lbl", parent=kicker, fontSize=7, leading=9)
    empty_style = ParagraphStyle("empty", fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED,
                                 alignment=TA_CENTER)

    class _Pill(Flowable):
        """Rounded coloured badge for Action / Signal / State values."""

        def __init__(self, text, fg, bg):
            Flowable.__init__(self)
            self.label, self.fg, self.bg = text, fg, bg
            self.width = stringWidth(text, "Helvetica-Bold", 6.8) + 12
            self.height = 11

        def wrap(self, aw, ah):
            return self.width, self.height

        def draw(self):
            c = self.canv
            c.setFillColor(self.bg)
            c.roundRect(0, 0, self.width, self.height, 5.5, stroke=0, fill=1)
            c.setFillColor(self.fg)
            c.setFont("Helvetica-Bold", 6.8)
            c.drawString(6, 3, self.label)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, page[1] - 22, page[0], 22, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(WHITE)
        canvas.drawString(margin, page[1] - 14, _safe(header_text))
        canvas.restoreState()

    class _NumberedCanvas(_cv.Canvas):
        """Two-pass canvas so the footer can print 'Page x of y'."""

        def __init__(self, *args, **kwargs):
            _cv.Canvas.__init__(self, *args, **kwargs)
            self._page_states = []

        def showPage(self):
            self._page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._page_states)
            for state in self._page_states:
                self.__dict__.update(state)
                self.setStrokeColor(RULE)
                self.line(margin, 24, page[0] - margin, 24)
                self.setFont("Helvetica", 7)
                self.setFillColor(MUTED)
                self.drawString(margin, 14, f"Session {session_date}")
                self.drawRightString(page[0] - margin, 14, f"Page {self._pageNumber} of {total}")
                _cv.Canvas.showPage(self)
            _cv.Canvas.save(self)

    story = [Spacer(1, 4 * mm)]
    banner = [Paragraph("PSX Daily Patterns Report", h1), Spacer(1, 8),
              Paragraph("Covers Chart Patterns, Patterns and Breakouts. FIRE Engine content is excluded.",
                        cover_meta)]
    banner_tbl = Table([[banner]], colWidths=[width])
    banner_tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 22), ("RIGHTPADDING", (0, 0), (-1, -1), 22),
                                    ("TOPPADDING", (0, 0), (-1, -1), 22), ("BOTTOMPADDING", (0, 0), (-1, -1), 20)]))
    story += [banner_tbl, Spacer(1, 10)]
    tile_vals = [str(len(sections)), f"{total_rows:,}", session_date, generated_at]
    tile_labels = ["Sections", "Rows", "Session date", "Generated"]
    tiles = Table([[Paragraph(_esc(v), kpi_num) for v in tile_vals],
                   [Paragraph(_esc(l.upper()), kpi_lbl) for l in tile_labels]],
                  colWidths=[width / 4] * 4)
    tiles.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
                               ("LINEABOVE", (0, 0), (-1, 0), 2, TEAL),
                               ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, 0), 10),
                               ("BOTTOMPADDING", (0, -1), (-1, -1), 10)]))
    story += [tiles, Spacer(1, 16), Paragraph("Contents", grp), HRFlowable(width=width, thickness=1.5, color=TEAL),
              Spacer(1, 6)]
    for g, subs in heading_tree(sections):
        story.append(Paragraph(_esc(g.upper()), kicker))
        for sub, tables in subs:
            story.append(Paragraph(_esc(_safe(sub)), small))
            for title, n in tables:
                story.append(Paragraph(f"{_esc(_safe(title))} ({n} rows)", tiny))
        story.append(Spacer(1, 4))
    story.append(PageBreak())

    current_group = current_sub = None
    for s in sections:
        if s["group"] != current_group:
            if current_group is not None:
                story.append(PageBreak())
            current_group, current_sub = s["group"], None
            story += [Paragraph(_esc(s["group"]), grp), HRFlowable(width=width, thickness=1.5, color=TEAL),
                      Spacer(1, 6)]
        head = []
        if s["sub"] != current_sub:
            current_sub = s["sub"]
            head += [Paragraph(_esc(s["group"].upper()), kicker), Paragraph(_esc(_safe(s["sub"])), h2)]
        head.append(Paragraph(_esc(_safe(s["title"])), ttl))
        summary = " | ".join(s["summary"]) if s["summary"] else ""
        line = f"<b>Total rows:</b> {len(s['rows'])}."
        if summary:
            line += " " + _esc(_safe(summary))
        head.append(Paragraph(line, small))
        if s.get("note"):
            head.append(Paragraph(_esc(_safe(s["note"])), tiny))
        head.append(Paragraph(_esc(_safe(f"Source: {s['source']}")), tiny))
        head.append(Spacer(1, 6))
        body = []
        if s["rows"] and s["columns"]:
            cols = s["columns"]
            texts = {c: [_cell(r.get(c)) for r in s["rows"]] for c in cols}
            numeric = {c: _numeric_column(texts[c]) for c in cols}
            data = [[Paragraph(_esc(_safe(c)), hcell_r if numeric[c] else hcell) for c in cols]]
            for ri, r in enumerate(s["rows"]):
                row = []
                for c in cols:
                    txt = texts[c][ri]
                    style_pair = badge_style(txt) if c in BADGE_COLUMNS else None
                    if style_pair:
                        row.append(_Pill(txt, colors.HexColor(style_pair[0]), colors.HexColor(style_pair[1])))
                    else:
                        row.append(Paragraph(_esc(txt), cell_r if numeric[c] else cell))
                data.append(row)
            weights = []
            for c in cols:
                longest = max([len(t) for t in texts[c][:300]] + [min(len(c), 14)])
                weights.append(min(max(longest, 6), 40))
            total = float(sum(weights))
            widths = [max(width * w / total, 28) for w in weights]
            scale = width / sum(widths)
            widths = [w * scale for w in widths]
            t = Table(data, colWidths=widths, repeatRows=1)
            style = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
                     ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                     ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
                     ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                     ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE)]
            for ci, c in enumerate(cols):
                if numeric[c]:
                    style.append(("ALIGN", (ci, 0), (ci, -1), "RIGHT"))
            for i in range(2, len(data), 2):
                style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
            t.setStyle(TableStyle(style))
            body.append(t)
        else:
            box = Table([[Paragraph(_esc(_safe(s["empty_text"])), empty_style)]], colWidths=[width])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                                     ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                                     ("TOPPADDING", (0, 0), (-1, -1), 12),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
            body.append(box)
        for line in s.get("checklist") or []:
            body.append(Paragraph(_esc(_safe(line)), mono))
        story.append(KeepTogether(head))
        story += body
        story.append(Spacer(1, 14))

    doc = SimpleDocTemplate(path, pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=margin,
                            bottomMargin=margin, title="PSX Daily Patterns Report", author="PSX Intelligence",
                            subject=f"Session {session_date}", pageCompression=1)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page, canvasmaker=_NumberedCanvas)
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        pages = len(re.findall(rb"/Type\s*/Page(?!s)", f.read()))
    return path, pages, size


def build_report(conn, out_dir=None, root_dir=ROOT, session_date=None, names=None):
    session, sections = collect_sections(conn, root_dir, session_date, names=names)
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
