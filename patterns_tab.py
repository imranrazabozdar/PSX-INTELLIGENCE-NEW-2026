"""patterns_tab.py — Patterns tab layout (presentation only).

Same backend requests, same hit -> row construction, same recency filter and
same row order as the pre-redesign streamlit_app.py; only the layout changed:
Overview / Market Behaviour / Long / Short / Structural / Volatility /
Wyckoff 2.0 views, one shared module layout (patterns_ui), cards or table,
Show more instead of the old 50-row cap. Rule/warning text is rendered by
patterns_text (generated verbatim from the old file).
"""
import re
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import patterns_text as T
import patterns_ui as U

RECENT_SIGNAL_DAYS = 14
VIEWS = ["Overview", "Market Behaviour", "Long", "Short", "Structural", "Volatility", "Wyckoff 2.0"]
VIEW_ICONS = {"Overview": "🧭", "Market Behaviour": "🔥", "Long": "🟢", "Short": "🔴", "Structural": "📐",
              "Volatility": "📊", "Wyckoff 2.0": "🧪"}


# ------------------------------------------------------------ helpers --
def _state_msg(result, label):
    """Same three non-ok states (and messages) as the old _scan_status_banner."""
    if result.get("status") == "forbidden":
        return ("error", result.get("reason"))
    if result.get("status") == "running":
        return ("info", result.get("reason") or "Scan running in the background for the first time — check back shortly.")
    if result.get("status") != "ok":
        return ("warning", result.get("reason") or f"{label} scan unavailable right now.")
    return None


def _filter_recent(hits, date_key, checkbox_key):
    """The old _filter_recent, split: the checkbox itself is drawn in Details
    (same key), its current value is read here."""
    show_all = bool(st.session_state.get(checkbox_key, False))
    if show_all or not hits:
        return hits, 0
    cutoff = (datetime.now() - timedelta(days=RECENT_SIGNAL_DAYS)).date()

    def _is_recent(h):
        try:
            return datetime.strptime(str(h.get(date_key) or "")[:10], "%Y-%m-%d").date() >= cutoff
        except ValueError:
            return True

    kept = [h for h in hits if _is_recent(h)]
    return kept, len(hits) - len(kept)


def _hist_checkbox(key):
    st.checkbox("Show Historical Signals", key=key,
                help=f"Off: only signals from the last {RECENT_SIGNAL_DAYS} days are listed. On: every stored signal.")


def _age_str_min(scan):
    age = scan.get("_cache_age_seconds")
    return f"{int(age // 60)} min ago" if isinstance(age, (int, float)) else "—"


def _running(scan):
    return " · a background refresh is running right now" if scan.get("_background_refresh_running") else ""


def _plain(label):
    """'🟢 BUY SIGNAL' -> 'BUY SIGNAL' for a badge (the raw value stays in Table view)."""
    return re.sub(r"^[^\w(]+\s*", "", str(label or "")).strip()


def _action_variant(label):
    s = str(label or "").upper()
    if "BUY" in s:
        return "bull"
    if "SHORT" in s or "SELL" in s:
        return "bear"
    return "neutral"


def _direction(label):
    v = _action_variant(label)
    return v if v in ("bull", "bear") else None


def _action_badge(row):
    a = row.get("action") or row.get("Action")
    return [(_plain(a), _action_variant(a))] if a else []


def _sort_by_date(df, col):
    """Same ordering the old _render_pattern_table applied (newest first, stable)."""
    if col and col in df.columns:
        return df.sort_values(col, ascending=False, kind="stable").reset_index(drop=True)
    return df.reset_index(drop=True)


def _open_research(sym):
    st.session_state.research_symbol = sym
    st.toast(f"Opened {sym} in Stock Research →", icon="🎯")


TRADE_FIELDS = [
    U.F("symbol", "Symbol"), U.F("company", "Company"),
    U.F("action", "Action", help="The module's own signal label", card=False),
    U.F("entry", "Entry", "Rs %.2f", "num"),
    U.F("stop", "Stop-Loss (Risk)", "Rs %.2f", "num"),
    U.F("target 1", "Target (Reward)", "Rs %.2f", "num"),
    U.F("R:R", "R:R", help="Reward-to-risk, as the module states it"),
    U.F("date", "Date", kind="date"),
]


def _fields(overrides=None, extra=None, drop=()):
    out = []
    for f in TRADE_FIELDS:
        if f["col"] in drop:
            continue
        out.append(dict(f, **(overrides or {}).get(f["col"], {})))
    for f in extra or []:
        out.insert(len(out) - 1, f)
    return out


def _module(**kw):
    kw.setdefault("flags", [])
    kw.setdefault("warnings", [])
    return kw


def _scan_caption(what):
    def f(scan, n, hidden_n):
        return (f"📦 Scanned {scan.get('scanned', 0)} symbols with stored daily history · last run "
                f"{_age_str_min(scan)}{_running(scan)} · {n} symbol(s) currently showing {what}"
                f"{f' ({hidden_n} older than {RECENT_SIGNAL_DAYS}d hidden)' if hidden_n else ''}.")
    return f


# ------------------------------------------------------------ modules --
def _fire_module(get, params, names):
    scan = get("/patterns/fire-scan", **params)
    m = _module(id="fire", group="Market Behaviour", category="Market behaviour",
                name="PSX FIRE Engine — Priority Setups", timeframe="1-minute intraday, daily batch",
                age=scan.get("_cache_age_seconds"), always_show=True, details=lambda: T.fire_rules())
    st_msg = _state_msg(scan, "PSX FIRE Engine")
    if st_msg:
        m.update(state_msg=st_msg, count=0)
        return m
    hits = scan.get("hits") or []
    VOL = {"NORMAL_OR_THIN": "Normal or thin", "ELEVATED_OR_ABOVE": "Elevated or above",
           "ABNORMAL_OR_ABOVE": "Abnormal or above", "UNKNOWN": "Unknown"}
    rows = [{
        "rank": i + 1, "symbol": h["symbol"], "company": names.get(h["symbol"], ""),
        "status": "FIRE" if h["classification"] == "FIRE" else "PRE-FIRE",
        "fire score": h.get("fire_score"), "mfi": h.get("mfi_value"),
        "relative volume": h.get("relative_volume"),
        "volume": VOL.get(h.get("volume_condition"), h.get("volume_condition")),
        "volume condition": h.get("volume_condition"),
        "time": str(h.get("event_time") or "")[-8:], "notes": h.get("notes"),
        "classification": h.get("classification"),
    } for i, h in enumerate(hits)]
    df = pd.DataFrame(rows)
    n_fire = sum(r["status"] == "FIRE" for r in rows)
    n_ab = sum(r["volume condition"] == "ABNORMAL_OR_ABOVE" for r in rows)
    fields = [
        U.F("symbol", "Symbol"), U.F("status", "Status", card=False),
        U.F("rank", "Engine rank", "%d", "num", help="Position in the engine's own order (highest FIRE score first)"),
        U.F("company", "Company"),
        U.F("fire score", "FIRE Score", "%d", "num", help="0–100 strength score — not a probability or profitability claim"),
        U.F("mfi", "MFI(14)", "%.1f", "num", help="Money Flow Index at the event"),
        U.F("relative volume", "Rel. Volume", "%.2fx", "num",
            help="Volume vs the median for the same time of day"),
        U.F("volume", "Volume", help="Engine's volume condition, in plain words", card=False),
        U.F("time", "Event time (PKT)",
            help="Time of the 1-minute candle at which this stored highest-score FIRE / PRE-FIRE event was detected"),
        U.F("notes", "Engine notes", card=False,
            help="Text the engine stored with the event (FIRE: rating and confidence; PRE-FIRE: usually empty)"),
        U.F("volume condition", "Volume (raw)", primary=False, card=False),
        U.F("classification", "Classification (raw)", primary=False, card=False),
    ]

    def badge_fn(r):
        return [(r["status"], "fire" if r["status"] == "FIRE" else "caution"),
                (r["volume"], "info")] if r.get("volume") else [(r["status"], "fire" if r["status"] == "FIRE" else "caution")]

    def body():
        if not hits:
            st.info(scan.get("reason") or "No PRE-FIRE/FIRE setups in the most recent completed daily batch.")
            return
        st.caption("A strength score, not a probability or profitability claim.")
        U.summary_tiles([("Total", len(rows)), ("FIRE", n_fire), ("PRE-FIRE", len(rows) - n_fire),
                         ("Abnormal or above volume", n_ab)])
        with st.expander("Filter, sort and search", expanded=False):
            c1, c2 = st.columns(2)
            status = c1.selectbox("Status", ["All", "FIRE", "PRE-FIRE"], key="fire_f_status")
            vol_opts = ["All"] + [v for v in VOL.values() if v in set(df["volume"])]
            vol = c2.selectbox("Volume", vol_opts, key="fire_f_vol")
            c3, c4 = st.columns(2)
            q = c3.text_input("Search symbol or company", key="fire_f_q").strip().lower()
            sort = c4.selectbox("Sort by", ["Engine rank", "FIRE score", "MFI", "Rel. Volume"], key="fire_f_sort")
        f = df
        if status != "All":
            f = f[f["status"] == status]
        if vol != "All":
            f = f[f["volume"] == vol]
        if q:
            f = f[f["symbol"].str.lower().str.contains(q, regex=False) | f["company"].fillna("").str.lower().str.contains(q, regex=False)]
        col = {"Engine rank": None, "FIRE score": "fire score", "MFI": "mfi", "Rel. Volume": "relative volume"}[sort]
        if col:
            f = f.sort_values(col, ascending=False, kind="stable", na_position="last")
        active = [x for x in (status != "All" and f"status {status}", vol != "All" and f"volume {vol}",
                              q and f"search “{q}”", sort != "Engine rank" and f"sorted by {sort}") if x]
        st.caption(f"Showing {len(f)} of {len(df)}" + (f" · {', '.join(active)}" if active else " · engine order"))
        sections = [("FIRE", f[f["status"] == "FIRE"]), ("PRE-FIRE", f[f["status"] == "PRE-FIRE"])] \
            if status == "All" else [(status, f)]
        for title, part in sections:
            if status == "All":
                st.markdown(U.badge(f"{title} · {len(part)}", "fire" if title == "FIRE" else "caution"),
                            unsafe_allow_html=True)
            U.results(part.reset_index(drop=True), f"fire_scan_table_{title}", fields, badge_fn=badge_fn,
                      note_cols=("notes",), on_open=_open_research, empty_msg=f"No {title} rows match.")

    def details():
        st.caption(f"Last completed scan: {scan.get('date') or '—'} · {scan.get('scanned', 0)} "
                   "symbol(s) with an active setup, ranked by FIRE score (highest priority first). "
                   "A strength score, not a probability or profitability claim.")
        T.fire_rules()

    m.update(count=len(rows), body=body, details=details, df=df, updated=f"Scan {scan.get('date') or '—'} · "
             + U.friendly_age(scan.get("_cache_age_seconds")),
             flags=[(r["symbol"], None, r["status"]) for r in rows])
    return m


SIGNAL_TEXT = {"EXTREME": "EXTREME", "READY": "READY", "WATCH": "WATCH"}


def _wyckoff_module(get, params, names):
    scan = get("/patterns/wyckoff-scan", **params)
    m = _module(id="wyckoff", group="Market Behaviour", category="Market behaviour",
                name="Wyckoff Institutional Accumulation", timeframe="1D + 4H",
                age=scan.get("_cache_age_seconds"), always_show=True, details=lambda: T.wyckoff_rules())
    st_msg = _state_msg(scan, "Wyckoff Accumulation")
    if st_msg:
        m.update(state_msg=st_msg, count=0, body=T.wyckoff_warning)
        return m
    hits = scan.get("hits") or []
    rows = [{"symbol": h["symbol"], "company": names.get(h["symbol"], ""),
             "signal": SIGNAL_TEXT.get(h.get("signal_type"), h.get("signal_type")),
             "score": h.get("accumulation_score"), "price": h.get("current_price")} for h in hits]
    df = pd.DataFrame(rows)
    fields = [U.F("symbol", "Symbol"), U.F("signal", "Strength", card=False,
                                         help="How complete the Wyckoff pattern is — a strength label, not a direction"),
              U.F("company", "Company"),
              U.F("score", "Score", "%d", "num", help="Pattern-strength score 0–100, not a probability"),
              U.F("price", "Price", "%.2f", "num")]

    def body():
        T.wyckoff_warning()
        if not hits:
            st.info(scan.get("reason") or "No WATCH/READY/EXTREME setups in the most recent completed daily batch.")
            return
        U.results(df, "wyckoff_scan_table", fields, badge_fn=lambda r: [(f"{r['signal']}", "info")],
                  on_open=_open_research)

    def details():
        st.caption(f"Last completed scan: {scan.get('date') or '—'} · {scan.get('scanned', 0)} "
                   "symbol(s) scanned, ranked by accumulation score (highest priority first) -- "
                   "a pattern-strength score, not a probability or profitability claim.")
        if hits:
            T.wyckoff_components({"wyckoff_hits": hits, "signal_badge": SIGNAL_TEXT})
        T.wyckoff_rules()

    m.update(count=len(rows), body=body, details=details, df=df,
             updated=f"Scan {scan.get('date') or '—'} · " + U.friendly_age(scan.get("_cache_age_seconds")),
             flags=[(r["symbol"], None, f"Wyckoff {r['signal']}") for r in rows])
    return m


def _obv_mfi_module(get, names):
    scan = get("/patterns/obv-mfi-scan")
    m = _module(id="obv_mfi", group="Long", category="Accumulation footprint",
                name="OBV+MFI Setup with ATR Contraction", timeframe="1D", age=scan.get("_cache_age_seconds"),
                details=lambda: T.obv_mfi_rules(),
                empty_msg="No symbol completes the impulse → quiet-pullback sequence on its latest daily candle.")
    st_msg = _state_msg(scan, "OBV+MFI Setup")
    if st_msg:
        m.update(state_msg=st_msg, count=0)
        return m
    hits = scan.get("hits") or []
    df = pd.DataFrame([{
        "symbol": h["symbol"], "company": names.get(h["symbol"], ""),
        "close": h.get("close"), "day0": h.get("day0_date"),
        "days": h.get("days_since_day0"), "pullback": h.get("pullback_pct"),
        "vol_drought": h.get("vol_drought_pct"), "mfi": h.get("mfi_now"),
        "obv_kept": h.get("obv_retention_pct"), "atr_ratio": h.get("atr_ratio"),
    } for h in hits])
    fields = [U.F("symbol", "Symbol"), U.F("company", "Company"),
              U.F("close", "Close", "Rs %.2f", "num"),
              U.F("day0", "Day 0 (impulse)", kind="date", help="The high-volume breakout day the setup starts from"),
              U.F("days", "Days since", "%d", "num"),
              U.F("pullback", "Pullback", "%.1f%%", "num", help="How far the close is below Day 0"),
              U.F("vol_drought", "Avg vol vs Day 0", "%.1f%%", "num"),
              U.F("mfi", "MFI now", "%.1f", "num"),
              U.F("obv_kept", "OBV kept", "%.1f%%", "num", help="Share of Day 0's OBV still held"),
              U.F("atr_ratio", "ATR now / Day 0", "%.2f", "num")]
    age = scan.get("_cache_age_seconds")
    cap = (f"📦 Scanned {scan.get('scanned', 0)} symbols · last run "
           f"{f'{int(age // 3600)} h ago' if isinstance(age, (int, float)) else '—'} · "
           f"{len(hits)} symbol(s) completing the full sequence today.")

    def details():
        st.caption(cap)
        T.obv_mfi_rules()

    m.update(count=len(df), df=df, details=details, warnings=[("caption", "Not yet backtested on PSX — not a probability of profit.")],
             body=lambda: U.results(df, "obv_mfi_scan_table", fields, badge_fn=lambda r: [("SETUP COMPLETE", "bull")],
                                    on_open=_open_research, empty_msg=m["empty_msg"]),
             flags=[(r, "bull", "OBV+MFI setup") for r in df.get("symbol", [])])
    return m


def _gp_module(scan, ranking, names, direction, name, action_label, mid):
    classification = "BUY" if direction == "BULL" else "SELL"
    m = _module(id=mid, group="Long" if direction == "BULL" else "Short", category="Chart patterns", name=name,
                timeframe="1D", age=(scan or {}).get("_cache_age_seconds"),
                details=lambda: T.gp_rules({"gp_ranking": ranking}),
                empty_msg=f"No trained model is currently signaling {classification}.")
    if not scan or scan.get("status") == "not_trained_yet":
        m.update(count=0, state_msg=("info", "No GP-evolved models trained yet — run the 'GP evolution training (manual)' "
                                     "GitHub Actions workflow first (long-running, offline, one model per watchlist "
                                     "symbol; see backend/run_gp_evolution_training.py)."))
        return m
    st_msg = _state_msg(scan, "GP-Evolved Formula")
    if st_msg:
        m.update(state_msg=st_msg, count=0)
        return m
    all_hits = [h for h in (scan.get("hits") or []) if h.get("classification") == classification]
    rows = [{
        "symbol": h["symbol"], "company": names.get(h["symbol"], ""),
        "action": action_label, "target exposure": h.get("desired_pct"),
        "oos return": (h.get("test_stats") or {}).get("total_return_pct"),
        "oos sharpe": (h.get("test_stats") or {}).get("sharpe"),
        "oos win rate": (h.get("test_stats") or {}).get("win_rate_pct"),
        "oos pf": (h.get("test_stats") or {}).get("profit_factor"),
    } for h in all_hits]
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values("target exposure", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    fields = [U.F("symbol", "Symbol"), U.F("action", "Action", card=False), U.F("company", "Company"),
              U.F("target exposure", "Target Exposure", "%.1f%%", "num", help="The formula's position reading today, -100% to +100%"),
              U.F("oos return", "Out-of-Sample Return", "%.2f%%", "num"),
              U.F("oos sharpe", "Out-of-Sample Sharpe", "%.2f", "num"),
              U.F("oos win rate", "Out-of-Sample Win Rate", "%.1f%%", "num"),
              U.F("oos pf", "Out-of-Sample Profit Factor", "%.2f", "num")]
    cap = (f"📦 Scanned {scan.get('scanned', 0)} trained model(s) · last run {_age_str_min(scan)}"
           f"{_running(scan)} · {len(all_hits)} currently signaling {classification}.")

    def details():
        st.caption(cap)
        T.gp_rules({"gp_ranking": ranking})

    m.update(count=len(df), df=df, details=details,
             body=lambda: U.results(df, f"{mid}_scan_table", fields, badge_fn=_action_badge, on_open=_open_research,
                                    empty_msg=m["empty_msg"]),
             flags=[(r["symbol"], _direction(action_label), _plain(action_label)) for r in rows])
    return m


def _structural_module(get, params, names, rr_label):
    adv = get("/patterns/advanced-scan", **params)
    hst = get("/patterns/hstop-scan", **params)
    m = _module(id="structural", group="Structural", category="Chart patterns",
                name="Chart Patterns (IHS, Double Bottom & Head/Shoulders)", timeframe="1D",
                age=min([a for a in (adv.get("_cache_age_seconds"), hst.get("_cache_age_seconds"))
                         if isinstance(a, (int, float))], default=None),
                details=lambda: T.structural_rules(),
                empty_msg="No Inverse Head & Shoulders, Double Bottom, or Head & Shoulders Top signals right now.")
    if adv.get("status") not in ("ok",) and hst.get("status") not in ("ok",):
        m.update(count=0, state_msg=("info", adv.get("reason") or "Chart pattern scan unavailable right now."))
        return m
    LABELS = {"INVERSE_HS": "Inverse Head & Shoulders", "DOUBLE_BOTTOM": "Double Bottom",
              "HEAD_SHOULDERS_TOP": "Head & Shoulders Top"}
    all_hits = ((adv.get("hits") or []) if adv.get("status") == "ok" else []) + \
               ((hst.get("hits") or []) if hst.get("status") == "ok" else [])
    flt = st.session_state.get("adv_pattern_filter", "All")
    if flt != "All":
        raw = {v: k for k, v in LABELS.items()}[flt]
        all_hits = [h for h in all_hits if h.get("pattern_type") == raw]
    hits, hidden_n = _filter_recent(all_hits, "signal_date", "be_adv_hist_checkbox")
    rows = [{
        "Symbol": h.get("symbol"), "Company": names.get(h.get("symbol"), ""),
        "Pattern": ("⚠️ " if h.get("pattern_type") == "INVERSE_HS" else "")
                   + LABELS.get(h.get("pattern_type"), str(h.get("pattern_type"))),
        "Action": "🔴 SELL SIGNAL" if h.get("pattern_type") == "HEAD_SHOULDERS_TOP" else "🟢 BUY SIGNAL",
        "Entry": h.get("entry_price"), "Stop": h.get("stop_loss"), "Target": h.get("target_1"),
        "R:R": rr_label(h.get("risk_reward_measured")), "Date": h.get("signal_date"),
    } for h in hits]
    df = _sort_by_date(pd.DataFrame(rows), "Date") if rows else pd.DataFrame(rows)
    fields = [U.F("Symbol", "Symbol"), U.F("Action", "Action", card=False), U.F("Company", "Company"),
              U.F("Pattern", "Pattern"), U.F("Entry", "Entry", "Rs %.2f", "num"),
              U.F("Stop", "Stop-Loss (Risk)", "Rs %.2f", "num"), U.F("Target", "Target (Reward)", "Rs %.2f", "num"),
              U.F("R:R", "R:R"), U.F("Date", "Date", kind="date")]

    def body():
        st.selectbox("Pattern type", ["All", "Inverse Head & Shoulders", "Double Bottom", "Head & Shoulders Top"],
                     key="adv_pattern_filter")
        if hidden_n:
            st.caption(f"{hidden_n} signal(s) older than {RECENT_SIGNAL_DAYS}d hidden.")
        U.results(df, "advanced_pattern_scan_table", fields, symbol_col="Symbol", company_col="Company",
                  badge_fn=_action_badge, on_open=_open_research, empty_msg=m["empty_msg"])

    def details():
        _hist_checkbox("be_adv_hist_checkbox")
        T.structural_rules()

    m.update(count=len(df), df=df, body=body, details=details, always_show=flt != "All",
             flags=[(r["Symbol"], _direction(r["Action"]), _plain(r["Action"]) + " · " + r["Pattern"].replace("⚠️ ", ""))
                    for r in rows])
    return m


def build_modules(get, params, names, rr_label):
    st.session_state["_pui_company_names"] = names
    mods = [_fire_module(get, params, names), _wyckoff_module(get, params, names)]
    mh = get("/patterns/mharris-scan", **params)
    es = get("/patterns/engulfing-star-scan", **params)
    me = get("/patterns/macdema-scan", **params)
    tr = get("/patterns/triangle-regression-scan", **params)
    lb = get("/patterns/level-breakout-scan", **params)
    gp = get("/patterns/gp-evolved-scan", **params)
    gpr = get("/patterns/gp-evolved-ranking")
    be = get("/patterns/bullish-engulfing-scan", **params)
    ms = get("/patterns/morning-star-scan", **params)
    tl = get("/patterns/three-line-strike-scan", **params)
    bre = get("/patterns/bearish-engulfing-scan", **params)
    evs = get("/patterns/evening-star-scan", **params)

    def tm(**kw):
        return _trade_module_rr(rr_label, **kw)

    long_mods = [
        _obv_mfi_module(get, names),
        tm(mid="patterns", group="Long", category="Candlestick patterns", name="Bullish Engulfing", scan=be,
           label="Bullish Engulfing", direction_filter=None, hist_key="be_bull_hist_checkbox", date_key="pattern_date",
           action_label=lambda h: "🟢 BUY SIGNAL" if "VALID" in str(h.get("classification") or "") else "⚪ WAIT (No Setup)",
           row_extra=lambda h: {"Stop": "—", "Target": "—", "R:R": "—"}, rules=T.bullish_engulfing_rules,
           fields=[U.F("symbol", "Symbol"), U.F("action", "Action", card=False), U.F("company", "Company"),
                   U.F("date", "Date", kind="date"), U.F("Stop", "Stop", primary=False), U.F("Target", "Target", primary=False),
                   U.F("R:R", "R:R", primary=False)],
           empty_msg="No symbol currently shows Bullish Engulfing geometry on its latest completed daily candles.",
           caption_fn=_scan_caption("engulfing geometry"), drop_trade=True),
        tm(mid="morning_star", group="Long", category="Candlestick patterns", name="Morning Star", scan=ms,
           label="Morning Star", direction_filter=None, hist_key="be_ms_hist_checkbox", date_key="date",
           action_label="🟢 BUY SIGNAL", rules=T.morning_star_rules, rr=True,
           empty_msg="No symbol currently shows a Morning Star completing on its latest stored daily session.",
           caption_fn=lambda s, n, hn: (f"📦 Scanned {s.get('scanned', 0)} symbols with stored daily history · last run "
                                        f"{_age_str_min(s)}{_running(s)} · {n} symbol(s) with a Morning Star "
                                        f"completing on their latest stored session"
                                        f"{f' ({hn} older than {RECENT_SIGNAL_DAYS}d hidden)' if hn else ''}.")),
        tm(mid="three_line_strike", group="Long", category="Candlestick patterns", name="Bullish Three-Line Strike",
           scan=tl, label="Three-Line Strike", direction_filter=None, hist_key="be_tls_hist_checkbox",
           date_key="pattern_date", status="PRODUCTION READY - RARE SIGNAL (MONITORED)", status_variant="caution",
           action_label=lambda h: "🟢 BUY SIGNAL" if "VALID" in str(h.get("classification") or "") else "⚪ WAIT (No Setup)",
           rules=T.three_line_strike_rules, pre=T.three_line_strike_warning,
           short_warning="⚠️ Ultra-rare signal on a thin sample (64 PSX signals); Target 2 is unvalidated (0%). "
                         "Trade with caution — full wording in Details.",
           fields=[f for f in TRADE_FIELDS if f["col"] != "R:R"],
           empty_msg="No symbol currently shows a Bullish Three-Line Strike on its latest completed 4-candle window.",
           caption_fn=lambda s, n, hn: (f"📦 Scanned {s.get('scanned', 0)} symbols with stored daily history · last run "
                                        f"{_age_str_min(s)}{_running(s)} · {n} symbol(s) currently showing a "
                                        f"Three-Line Strike on their latest completed 4-candle window"
                                        f"{f' ({hn} older than {RECENT_SIGNAL_DAYS}d hidden)' if hn else ''}.")),
        tm(mid="mharris_bull", group="Long", category="Candlestick patterns", name="MHarris 5-Bar Reversal (Bullish)",
           scan=mh, label="MHarris 5-Bar Reversal", filter_val="BULL", hist_key="mharris_bull_hist_checkbox",
           date_key="pattern_date", action_label="🟢 BUY SIGNAL", rules=T.mharris_rules,
           fields=[f for f in TRADE_FIELDS if f["col"] != "R:R"],
           empty_msg="No symbol currently shows an MHarris Bullish 5-bar reversal on its latest completed daily candles.",
           caption_fn=_scan_caption("this reversal")),
        tm(mid="engulfing_star_bull", group="Long", category="Candlestick patterns",
           name="Engulfing + Star Confirmed Reversal (Bullish)", scan=es, label="Engulfing + Star Confirmed Reversal",
           filter_val="BULL", hist_key="engulfing_star_bull_hist_checkbox", date_key="pattern_date",
           action_label="🟢 BUY SIGNAL", rules=T.engulfing_star_rules, fields=[f for f in TRADE_FIELDS if f["col"] != "R:R"],
           empty_msg="No symbol currently shows an Engulfing+Star Bullish reversal on its latest completed daily candle.",
           caption_fn=_scan_caption("this reversal")),
        tm(mid="macdema_bull", group="Long", category="Trend + momentum", name="MACD+EMA200 Trend Resumption (Bullish)",
           scan=me, label="MACD+EMA200 Trend Resumption", filter_val="BULL", hist_key="macdema_bull_hist_checkbox",
           date_key="pattern_date", action_label="🟢 BUY SIGNAL", rules=T.macdema_rules, target_none_label="Trailing",
           fields=_macd_fields(),
           empty_msg="No symbol currently shows a Bullish MACD+EMA200 trend-resumption signal on its latest completed "
                     "daily candle. Coverage grows as the full-market OHLC backfill loads more history per symbol.",
           caption_fn=_macd_caption),
        tm(mid="level_breakout_bull", group="Long", category="Chart patterns", name="Level Break Out (Resistance Breakout)",
           scan=lb, label="Level Break Out", filter_val="BULL", hist_key="level_breakout_bull_hist_checkbox",
           date_key="pattern_date", action_label="🟢 BUY SIGNAL", rules=T.level_breakout_rules,
           row_extra=lambda h: {"level": h.get("level_price")}, fields=_lb_fields(),
           empty_msg="No symbol currently shows a resistance breakout on its latest completed daily candle.",
           caption_fn=_scan_caption("this breakout")),
        _gp_module(gp, gpr, names, "BULL", "GP-Evolved Formula (Long Bias)", "🟢 BUY SIGNAL", "gp_evolved_bull"),
    ]
    short_mods = [
        tm(mid="bearish_engulfing", group="Short", category="Candlestick patterns · bearish", name="Bearish Engulfing",
           scan=bre, label="Bearish Engulfing", hist_key="be_bear_hist_checkbox", date_key="pattern_date",
           action_label=lambda h: "🔴 SHORT SIGNAL" if "VALID" in str(h.get("classification") or "") else "⚪ WAIT (No Setup)",
           rules=T.bearish_engulfing_rules, rr=True,
           empty_msg="No symbol currently shows Bearish Engulfing geometry on its latest completed daily candles.",
           caption_fn=_scan_caption("bearish engulfing geometry")),
        tm(mid="evening_star", group="Short", category="Candlestick patterns · bearish", name="Evening Star", scan=evs,
           label="Evening Star", hist_key="be_es_hist_checkbox", date_key="date", action_label="🔴 SHORT SIGNAL",
           rules=T.evening_star_rules, pre=T.evening_star_warning,
           short_warning="⚠️ Very thin sample (n=39); Target 2 win rate 0% — treat this edge as unvalidated. "
                         "Full wording in Details.", fields=[f for f in TRADE_FIELDS if f["col"] != "R:R"],
           empty_msg="No symbol currently shows an Evening Star completing on its latest stored daily session.",
           caption_fn=lambda s, n, hn: (f"📦 Scanned {s.get('scanned', 0)} symbols with stored daily history · last run "
                                        f"{_age_str_min(s)}{_running(s)} · {n} symbol(s) with an Evening Star "
                                        f"completing on their latest stored session"
                                        f"{f' ({hn} older than {RECENT_SIGNAL_DAYS}d hidden)' if hn else ''}.")),
        tm(mid="mharris_bear", group="Short", category="Candlestick patterns", name="MHarris 5-Bar Reversal (Bearish)",
           scan=mh, label="MHarris 5-Bar Reversal", filter_val="BEAR", hist_key="mharris_bear_hist_checkbox",
           date_key="pattern_date", action_label="🔴 SHORT SIGNAL", rules=T.mharris_rules,
           fields=[f for f in TRADE_FIELDS if f["col"] != "R:R"],
           empty_msg="No symbol currently shows an MHarris Bearish 5-bar reversal on its latest completed daily candles.",
           caption_fn=_scan_caption("this reversal")),
        tm(mid="engulfing_star_bear", group="Short", category="Candlestick patterns",
           name="Engulfing + Star Confirmed Reversal (Bearish)", scan=es, label="Engulfing + Star Confirmed Reversal",
           filter_val="BEAR", hist_key="engulfing_star_bear_hist_checkbox", date_key="pattern_date",
           action_label="🔴 SHORT SIGNAL", rules=T.engulfing_star_rules, fields=[f for f in TRADE_FIELDS if f["col"] != "R:R"],
           empty_msg="No symbol currently shows an Engulfing+Star Bearish reversal on its latest completed daily candle.",
           caption_fn=_scan_caption("this reversal")),
        tm(mid="macdema_bear", group="Short", category="Trend + momentum", name="MACD+EMA200 Trend Resumption (Bearish)",
           scan=me, label="MACD+EMA200 Trend Resumption", filter_val="BEAR", hist_key="macdema_bear_hist_checkbox",
           date_key="pattern_date", action_label="🔴 SHORT SIGNAL", rules=T.macdema_rules, target_none_label="Trailing",
           fields=_macd_fields(),
           empty_msg="No symbol currently shows a Bearish MACD+EMA200 trend-resumption signal on its latest completed "
                     "daily candle. Coverage grows as the full-market OHLC backfill loads more history per symbol.",
           caption_fn=_macd_caption),
        tm(mid="triangle_regression", group="Short", category="Chart patterns", name="Regression-Channel Triangle Squeeze",
           scan=tr, label="Regression-Channel Triangle Squeeze", hist_key="triangle_reg_hist_checkbox",
           date_key="pattern_date", action_label="🔴 SHORT SIGNAL", rules=T.triangle_rules,
           fields=[f for f in TRADE_FIELDS if f["col"] != "R:R"],
           empty_msg="No symbol currently shows a Regression-Channel Triangle Squeeze on its latest completed daily candle.",
           caption_fn=_scan_caption("this squeeze"), table_key="triangle_regression_scan_table"),
        tm(mid="level_breakout_bear", group="Short", category="Chart patterns", name="Level Break Out (Support Breakdown)",
           scan=lb, label="Level Break Out", filter_val="BEAR", hist_key="level_breakout_bear_hist_checkbox",
           date_key="pattern_date", action_label="🔴 SHORT SIGNAL", rules=T.level_breakout_rules,
           row_extra=lambda h: {"level": h.get("level_price")}, fields=_lb_fields(),
           empty_msg="No symbol currently shows a support breakdown on its latest completed daily candle.",
           caption_fn=_scan_caption("this breakout")),
        _gp_module(gp, gpr, names, "BEAR", "GP-Evolved Formula (Short Bias)", "🔴 SELL SIGNAL", "gp_evolved_bear"),
    ]
    return mods + long_mods + short_mods + [_structural_module(get, params, names, rr_label)]


def _macd_fields():
    return [U.F("symbol", "Symbol"), U.F("action", "Action", card=False), U.F("company", "Company"),
            U.F("entry", "Entry", "Rs %.2f", "num"), U.F("stop", "Initial Stop (ATR trail)", "Rs %.2f", "num"),
            U.F("target 1", "Target", help="Always Trailing — this strategy has no fixed target"),
            U.F("date", "Date", kind="date")]


def _lb_fields():
    return [U.F("symbol", "Symbol"), U.F("action", "Action", card=False), U.F("company", "Company"),
            U.F("entry", "Entry", "Rs %.2f", "num"), U.F("stop", "Stop-Loss (Risk)", "Rs %.2f", "num"),
            U.F("target 1", "Target (Reward)", "Rs %.2f", "num"),
            U.F("level", "Level Broken", "Rs %.2f", "num", help="The horizontal level the close moved beyond"),
            U.F("date", "Date", kind="date")]


def _macd_caption(scan, n, hidden_n):
    return (f"📦 Scanned {scan.get('scanned', 0)} symbols with >= ~217 days of stored "
            f"daily history (EMA200 needs it) · last run {_age_str_min(scan)}{_running(scan)} · "
            f"{n} symbol(s) currently showing this signal"
            f"{f' ({hidden_n} older than {RECENT_SIGNAL_DAYS}d hidden)' if hidden_n else ''}.")


def _trade_module_rr(rr_label, pre=None, drop_trade=False, table_key=None, direction_filter=None,
                     short_warning=None, **kw):
    fields = kw.pop("fields", None)
    if fields is None:
        fields = TRADE_FIELDS if kw.get("rr") else [f for f in TRADE_FIELDS if f["col"] != "R:R"]
    kw["fields"] = fields
    m = _trade_module_impl(rr_label, **kw)
    if pre:
        m["pre"] = pre
        # full text also inside Details, so it is reachable when the module is collapsed
        d = m.get("details")
        m["details"] = (lambda d=d: ((m.get("count") or 0) == 0 and pre(), d and d()))
    if short_warning:
        m["short_warning"] = short_warning
    return m


def _trade_module_impl(rr_label, *, mid, group, category, name, scan, label, action_label, hist_key, date_key,
                       empty_msg, caption_fn, fields, row_extra=None, rules=None, status=None, status_variant=None,
                       target_none_label=None, rr=False, filter_val=None):
    names = st.session_state.get("_pui_company_names") or {}
    m = _module(id=mid, group=group, category=category, name=name, timeframe="1D", status=status,
                status_variant=status_variant, age=scan.get("_cache_age_seconds"), empty_msg=empty_msg)
    st_msg = _state_msg(scan, label)
    if st_msg:
        m.update(state_msg=st_msg, count=0, details=(lambda: rules()) if rules else None)
        return m
    all_hits = scan.get("hits") or []
    if filter_val is not None:
        all_hits = [h for h in all_hits if h.get("direction") == filter_val]
    hits, hidden_n = _filter_recent(all_hits, date_key, hist_key)
    rows = []
    for h in hits:
        r = {"symbol": h["symbol"], "company": names.get(h["symbol"], ""),
             "action": action_label(h) if callable(action_label) else action_label,
             "entry": h.get("entry_price"), "stop": h.get("stop_loss"),
             "target 1": (target_none_label if (target_none_label and h.get("target_1") is None) else h.get("target_1")),
             "date": h.get(date_key)}
        if row_extra:
            r.update(row_extra(h))
        rows.append(r)
    df = pd.DataFrame(rows)
    if rr and len(df):
        df["R:R"] = df.apply(lambda r: rr_label(
            (r["target 1"] - r["entry"]) / (r["entry"] - r["stop"])
            if r.get("entry") and r.get("stop") and r.get("target 1") and (r["entry"] - r["stop"]) != 0
            else None), axis=1)
    if len(df):
        df = _sort_by_date(df, "date")
    caption = caption_fn(scan, len(hits), hidden_n)

    def body():
        if m.get("pre"):
            m["pre"]()
        if hidden_n:
            st.caption(f"{hidden_n} older than {RECENT_SIGNAL_DAYS}d hidden — turn on Show Historical Signals in Details.")
        U.results(df, f"{mid}_scan_table" if mid != "patterns" else "patterns_scan_table", fields,
                  badge_fn=_action_badge, on_open=_open_research, empty_msg=empty_msg)

    def details():
        _hist_checkbox(hist_key)
        st.caption(caption)
        if rules:
            rules()

    m.update(count=len(df), body=body, details=details, df=df,
             flags=[(r["symbol"], _direction(r["action"]), _plain(r["action"])) for r in rows])
    return m


# ------------------------------------------------------------- render --
def _goto(view, sub=None):
    st.session_state[U.VIEW_KEY] = view
    if sub:
        st.session_state["vol_subview"] = sub


def _overview(mods, extra, names):
    allm = mods + extra
    live = [m for m in allm if not m.get("state_msg")]
    zero = [m for m in live if (m.get("count") or 0) == 0 and m.get("count") is not None]
    flags = {}
    for m in allm:
        for sym, direction, label in m.get("flags", []):
            flags.setdefault(sym, []).append((m, direction, label))
    ages = [m.get("age") for m in allm if isinstance(m.get("age"), (int, float))]
    U.summary_tiles([("Active modules", len(live)), ("No current signal", len(zero)),
                     ("Stocks flagged", len(flags)),
                     ("Latest update", U.friendly_age(min(ages)).replace("Updated ", "") if ages else "—")])
    st.caption("Counts list what each existing module shows today. Flags are never added together, and a stock "
               "with more flags is not ranked higher.")
    tab = st.segmented_control("Overview list", ["By module", "By stock"], default="By module", key="pui_ov_mode",
                               label_visibility="collapsed") or "By module"
    if tab == "By module":
        for g in VIEWS[1:]:
            gm = [m for m in allm if m["group"] == g]
            if not gm:
                continue
            st.markdown(f'<div class="pui-eyebrow" style="margin-top:6px">{VIEW_ICONS[g]} {U.esc(g)}</div>',
                        unsafe_allow_html=True)
            for i, m in enumerate(gm):
                c1, c2 = st.columns([4, 1], vertical_alignment="center")
                tags = []
                if m.get("status"):
                    tags.append((m["status"], m.get("status_variant") or "neutral"))
                if m.get("state_msg"):
                    tags.append(("Unavailable", "caution"))
                elif m.get("count") is not None:
                    n = m["count"]
                    tags.append((f"{n} {m.get('count_label', 'signal' if n == 1 else 'signals')}",
                                 "info" if n else "neutral"))
                c1.markdown(f"**{U.esc(m['name'])}** {U.badges(tags)}<br><span class='pui-meta'>"
                            f"{U.esc(m.get('updated') or U.friendly_age(m.get('age')))}</span>",
                            unsafe_allow_html=True)
                c2.button("Open", key=f"pui_open_{m['id']}", on_click=_goto, args=(g, m.get("sub")),
                          use_container_width=True)
    else:
        q = st.text_input("Search symbol or company", key="pui_ov_q").strip().lower()
        recs = []
        for sym in sorted(flags):
            fl = flags[sym]
            dirs = {d for _, d, _ in fl if d}
            co = names.get(sym, "")
            if q and q not in sym.lower() and q not in (co or "").lower():
                continue
            recs.append({"symbol": sym, "company": co,
                         "direction": "Mixed" if dirs == {"bull", "bear"} else
                                      ("Bullish" if dirs == {"bull"} else "Bearish" if dirs == {"bear"} else ""),
                         "modules": " · ".join(f"{m['name']}: {lab}" for m, _, lab in fl),
                         "_fl": fl})
        st.caption(f"{len(recs)} stock(s), A→Z.")
        df = pd.DataFrame([{k: v for k, v in r.items() if k != "_fl"} for r in recs])
        badge_by = {r["symbol"]: r["_fl"] for r in recs}

        def bf(row):
            out = []
            if row.get("direction") == "Mixed":
                out.append(("Mixed", "caution"))
            for m, d, lab in badge_by[row["symbol"]]:
                v = d if d in ("bull", "bear") else ("fire" if lab == "FIRE" else "caution" if lab == "PRE-FIRE"
                                                     else "research" if m["group"] == "Wyckoff 2.0" else "info")
                out.append((f"{m['name']}: {lab}", v))
            return out

        fields = [U.F("symbol", "Symbol"), U.F("direction", "Direction", card=False,
                                             help="Mixed = at least one bullish and one bearish flag"),
                  U.F("company", "Company"), U.F("modules", "Flagged by", card=False)]
        U.results(df, "pui_overview_stocks", fields, badge_fn=bf, on_open=_open_research,
                  empty_msg="No stock is flagged by any module right now.")


def render(get, company_names, rr_label, refresh_params):
    U.inject_css()
    names = company_names() or {}
    mods = build_modules(get, refresh_params, names, rr_label)
    import vol_engine_ui as V
    import wyckoff2_ui as W
    extra = []
    try:
        extra += V.summaries(get, company_names)
    except Exception as e:   # same isolation the old tab had around this engine
        extra.append({"id": "vol", "group": "Volatility", "name": "Volatility Intelligence Engine", "count": 0,
                      "flags": [], "state_msg": ("warning", f"Volatility Intelligence Engine unavailable: {type(e).__name__}: {e}")})
    try:
        extra.append(W.summary(get, company_names))
    except Exception as e:
        extra.append({"id": "w2", "group": "Wyckoff 2.0", "name": "Wyckoff Institutional Accumulation 2.0",
                      "count": 0, "flags": [], "status": "RESEARCH", "status_variant": "research",
                      "state_msg": ("warning", f"Wyckoff Institutional Accumulation section unavailable: {type(e).__name__}: {e}")})

    view = st.pills("Patterns view", VIEWS, default="Overview", key=U.VIEW_KEY, required=True, wrap=True,
                    format_func=lambda v: f"{VIEW_ICONS[v]} {v}", label_visibility="collapsed", width="stretch")
    st.segmented_control("Layout", ["Cards", "Table"], default="Cards", key=U.LAYOUT_KEY, required=True,
                         label_visibility="collapsed", help="Cards suit phones; Table shows columns")
    view = view or "Overview"

    if view == "Overview":
        _overview(mods, extra, names)
    elif view == "Volatility":
        try:
            V.render(get, company_names)
        except Exception as _e:
            st.warning(f"Volatility Intelligence Engine unavailable: {type(_e).__name__}: {_e}")
    elif view == "Wyckoff 2.0":
        try:
            W.render(get, company_names)
        except Exception as _e:
            st.warning(f"Wyckoff Institutional Accumulation section unavailable: {type(_e).__name__}: {_e}")
    else:
        if view == "Short":
            T.short_side_warning()
        if view == "Market Behaviour":
            st.caption("PSX FIRE (intraday behaviour) and Wyckoff (accumulation pattern) are reported separately; "
                       "neither is a direction call.")
        U.render_view([m for m in mods if m["group"] == view])
    st.caption("More patterns (Hammer, Piercing Pattern, Harami, Three White Soldiers) will be added to "
               "this tab as separate detectors, each scanned the same way.")
