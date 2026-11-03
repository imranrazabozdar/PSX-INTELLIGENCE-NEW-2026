"""vol_engine_ui.py — Streamlit rendering for the VOLATILITY INTELLIGENCE ENGINE
sub-tab (Patterns tab). Kept out of streamlit_app.py so the engine's UI is
self-contained; it only reads the three backend endpoints:

  /patterns/volatility-engine         daily scan (scores, stages, alerts)
  /patterns/volatility-engine/detail  per-symbol series for the diagnostic page
  /patterns/volatility-engine/stats   measured historical outcomes (Stage B)

Scores are heuristics; probabilities shown come only from the stats endpoint
and carry their sample size -- n below the minimum shows
"INSUFFICIENT HISTORICAL EVIDENCE" instead of a number.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

STAGES = {0: "0 · None", 1: "1 · Early Compression", 2: "2 · Advanced Squeeze", 3: "3 · Expansion Trigger",
          4: "4 · Confirmed Expansion", 5: "5 · Failed / Exhaustion"}
LIQ = ["Highly Liquid", "Liquid", "Moderate Liquidity", "Illiquid", "Unknown"]


def _hist_cell(h, direction):
    if not h or not h.get("available"):
        return "INSUFFICIENT HISTORICAL EVIDENCE"
    p = h.get("p_up_10d") if direction > 0 else h.get("p_down_10d")
    ci = h.get("p_up_10d_ci") if direction > 0 else h.get("p_down_10d_ci")
    word = "up" if direction > 0 else "down"
    return f"{p}% {word} in 10d [{ci[0]}–{ci[1]}], n={h.get('n')}"


FILTER_DEFAULTS = {"vol_f_liq": ["Highly Liquid", "Liquid", "Moderate Liquidity"], "vol_f_stage": [],
                   "vol_f_tv": 0.0, "vol_f_bbw": 100}


def _fval(k):
    return st.session_state.get(k, FILTER_DEFAULTS[k])


def _apply_filters(rows):
    """Same tests as the old per-tab _filters(), reading the shared panel's
    values (defaults identical to the old widgets' defaults)."""
    liq, stages, min_tv, max_bbw = _fval("vol_f_liq"), _fval("vol_f_stage"), _fval("vol_f_tv"), _fval("vol_f_bbw")
    out = []
    for r in rows:
        if liq and r["liquidity"] not in liq:
            continue
        if stages and STAGES[r["stage"]] not in stages:
            continue
        if (r.get("avg_traded_value") or 0) < min_tv * 1e6:
            continue
        if r.get("bbw_pct100") is not None and r["bbw_pct100"] > max_bbw:
            continue
        out.append(r)
    return out


def _filter_summary():
    liq, stages, tv, bbw = _fval("vol_f_liq"), _fval("vol_f_stage"), _fval("vol_f_tv"), _fval("vol_f_bbw")
    parts = [f"Liquidity: {', '.join(liq) if liq else 'any'}", f"Stage: {', '.join(stages) if stages else 'all'}"]
    if tv:
        parts.append(f"Min traded value {tv:g}m")
    if bbw < 100:
        parts.append(f"BBW percentile ≤ {bbw}")
    return " · ".join(parts)


def _filter_panel():
    with st.expander(f"Filters — {_filter_summary()}"):
        c1, c2 = st.columns(2)
        c1.multiselect("Liquidity", LIQ, default=FILTER_DEFAULTS["vol_f_liq"], key="vol_f_liq",
                       help="Liquidity bucket from average traded value")
        c2.multiselect("Stage", list(STAGES.values()), default=[], key="vol_f_stage", placeholder="All stages",
                       help="The engine's five-stage volatility label")
        c3, c4 = st.columns(2)
        c3.number_input("Min avg traded value (PKR m)", 0.0, 10000.0, 0.0, 5.0, key="vol_f_tv",
                        help="Hide stocks whose average daily traded value is below this, in million rupees")
        c4.slider("Max BBW percentile", 0, 100, 100, key="vol_f_bbw",
                  help="Bollinger Band width percentile over 100 days — lower means tighter (more compressed)")
        st.caption("These filters apply to Early Warning, Bullish Expansion and Bearish Expansion.")


def _detail(get, r, stats):
    sym = r["symbol"]
    st.markdown(f"#### {sym} — {r['stage_detail']}  ·  {r['bbw_class']}")
    m = st.columns(6)
    m[0].metric("Compression", r["compression_score"], help=f"data coverage {r['compression_coverage']}%")
    m[1].metric("Bullish evidence", r["bull_score"])
    m[2].metric("Bearish evidence", r["bear_score"])
    m[3].metric("BBW pct (100d)", r["bbw_pct100"])
    m[4].metric("ATR pct (100d)", r["atr_pct100"])
    m[5].metric("Squeeze run", f"{r['squeeze_run']} d" if r["squeeze_on"] else "off")
    det = get("/patterns/volatility-engine/detail", symbol=sym)
    if det.get("status") == "ok":
        s = det["series"]
        x = s["date"]
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25], vertical_spacing=0.04)
        fig.add_trace(go.Scatter(x=x, y=s["close"], name="Close", line=dict(width=1.6)), 1, 1)
        fig.add_trace(go.Scatter(x=x, y=s["box_hi"], name="20d range high", line=dict(dash="dot", width=1)), 1, 1)
        fig.add_trace(go.Scatter(x=x, y=s["box_lo"], name="20d range low", line=dict(dash="dot", width=1)), 1, 1)
        sq = [c if q else None for c, q in zip(s["close"], s["squeeze"])]
        fig.add_trace(go.Scatter(x=x, y=sq, mode="markers", name="BB inside KC", marker=dict(size=4)), 1, 1)
        fig.add_trace(go.Scatter(x=x, y=s["bbw_pct"], name="BBW pct", line=dict(width=1.3)), 2, 1)
        fig.add_trace(go.Scatter(x=x, y=s["atr_pct"], name="ATR% pct", line=dict(width=1.3)), 2, 1)
        fig.add_hline(y=20, line_dash="dot", row=2, col=1)
        fig.add_trace(go.Scatter(x=x, y=s["cmf"], name="CMF(20)", line=dict(width=1.2)), 3, 1)
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True, key=f"vol_detail_{sym}")
    n = r["narrative"]
    a, b = st.columns(2)
    with a:
        st.markdown("**What supports the bullish case**")
        for x in n["bull_case"] or ["Nothing measurable"]:
            st.markdown(f"- {x}")
        st.markdown(f"**Would confirm an upward expansion:** {n['confirm_up']}")
    with b:
        st.markdown("**What supports the bearish case**")
        for x in n["bear_case"] or ["Nothing measurable"]:
            st.markdown(f"- {x}")
        st.markdown(f"**Would confirm a downward expansion:** {n['confirm_down']}")
    st.markdown(f"**Invalidation:** {n['invalidation']}")
    for w in n["warnings"]:
        st.warning(w)
    with st.expander("All measurements"):
        keys = ["close", "atr5", "atr14", "atr20", "atr_pct_price", "atr_ratio", "atr_chg5", "atr_chg10",
                "atr_pct200", "hv10", "hv20", "hv60", "hv20_pct252", "hv_ratio", "bbw", "bbw_pct200",
                "squeeze_tightening", "squeeze_released", "dc20_hi", "dc20_lo", "dc55_hi", "dc55_lo",
                "dc_width", "dc_width_pct200", "range5", "range10", "range20", "range_contract",
                "dist_hi20", "dist_lo20", "rv20", "rv50", "vol_pct100", "vol_trend5", "vol_trend10",
                "updown_vol", "volume_state", "obv_slope20", "adl_slope20", "cmf20", "mfi", "mfi_chg5",
                "rs_market20", "rs_market60", "rs_sector20", "sector", "wk_bbw_pct", "wk_squeeze", "wk_trend",
                "wk_break", "mtf_alignment", "weekly_compressed_daily_expanding", "up_status", "dn_status",
                "break_level", "bars_since_break", "avg_traded_value", "avg_volume20", "zero_vol_sessions60",
                "liquidity", "corporate_action_dates", "evidence_coverage"]
        st.dataframe(pd.DataFrame([{"field": k, "value": str(r.get(k))} for k in keys]),
                     hide_index=True, use_container_width=True)
    h = r.get("hist") or {}
    st.markdown("**Historical outcomes after comparable setups** "
                f"(bucket `{h.get('bucket', '—')}`, all PSX symbols)")
    if h.get("available"):
        st.markdown(f"- n = {h['n']} events, {h.get('period')} · out-of-sample n = {h.get('oos_n')}"
                    f" (OOS P(up 10d) = {h.get('oos_p_up_10d')}%)\n"
                    f"- P(up after 10 sessions) {h['p_up_10d']}% [95% CI {h['p_up_10d_ci'][0]}–{h['p_up_10d_ci'][1]}] · "
                    f"P(down) {h['p_down_10d']}%\n"
                    f"- Mean / median 10-session return {h['mean_10d']}% / {h['median_10d']}% · "
                    f"P(|move| > 5%) {h['p_abs5_10d']}%\n"
                    f"- Average best / worst excursion within 20 sessions {h['mfe_20d']}% / {h['mae_20d']}%\n"
                    f"- ATR target (+3 ATR) hit before stop (−1.5 ATR): long {h['long_target_first']}% · "
                    f"short {h['short_target_first']}%")
    else:
        st.info(f"INSUFFICIENT HISTORICAL EVIDENCE (n={h.get('n', 0)}). {h.get('note', '')}")


SUBVIEWS = ["⚠️ Early Warning", "🟢 Bullish Expansion", "🔴 Bearish Expansion", "🧩 Wyckoff × Volatility",
            "🔔 Alerts", "🧪 Historical Validation"]
SUBVIEW_KEY = "vol_subview"
WV_SHOW = ["Wyckoff signals only (WATCH/READY/EXTREME)", "Confluence only", "All stocks"]

EW_FIELDS = None   # built lazily (needs patterns_ui)


def _U():
    import patterns_ui as U
    return U


def _ew_rows(rows, names):
    f = _apply_filters(rows)
    f = [r for r in f if r["stage"] in (1, 2) or (r["compression_score"] or 0) >= 50]
    f.sort(key=lambda r: -(r["compression_score"] or 0))
    return f, pd.DataFrame([{
        "symbol": r["symbol"], "company": names.get(r["symbol"], ""), "price": r["close"],
        "last_candle": r.get("last_bar_date") or r.get("date"),
        "compression": r["compression_score"], "bbw_pct": r["bbw_pct100"], "atr_pct": r["atr_pct100"],
        "squeeze_d": r["squeeze_run"], "dcw_pct": r["dc_width_pct200"], "vol_trend10": r["vol_trend10"],
        "bull": r["bull_score"], "bear": r["bear_score"], "stage": STAGES[r["stage"]],
        "mtf": r["mtf_alignment"], "liquidity": r["liquidity"], "hist_n": (r.get("hist") or {}).get("n", 0),
    } for r in f])


def _dir_rows(rows, names, sgn):
    k = "bull" if sgn > 0 else "bear"
    f = _apply_filters(rows)
    f = [r for r in f if (r[f"{k}_score"] or 0) >= 40 and (r["stage"] > 0 or (r["compression_score"] or 0) >= 40)
         and not (r["stage"] == 5 and r["stage_dir"] == sgn)]
    f.sort(key=lambda r: -((r[f"{k}_score"] or 0) * 0.5 + (r[f"{k}_expansion_score"] or 0) * 0.3
                           + (r["compression_score"] or 0) * 0.2))
    return f, pd.DataFrame([{
        "rank": i + 1, "symbol": r["symbol"], "company": names.get(r["symbol"], ""), "price": r["close"],
        "last_candle": r.get("last_bar_date") or r.get("date"),
        "compression": r["compression_score"], "evidence": r[f"{k}_score"],
        "expansion": r[f"{k}_expansion_score"], "bbw_pct": r["bbw_pct100"], "atr_pct": r["atr_pct100"],
        "rel_vol": r["rv20"], "break_level": r["break_level"] or (r["box_hi"] if sgn > 0 else r["box_lo"]),
        "support": r["box_lo"], "resistance": r["box_hi"], "stage": r["stage_detail"],
        "history": _hist_cell(r.get("hist"), sgn), "liquidity": r["liquidity"],
    } for i, r in enumerate(f)])


def _wv_rows(res, names, show):
    rows = res.get("rows") or []
    # Stale rows (kept for audit) never appear in the actionable views.
    if show.startswith("Wyckoff"):
        rows = [r for r in rows if r.get("wyckoff_signal") in ("WATCH", "READY", "EXTREME") and not r.get("stale")]
    elif show.startswith("Confluence"):
        rows = [r for r in rows if r.get("confluence") and not r.get("stale")]
    return rows, pd.DataFrame([{
        "symbol": r["symbol"], "company": names.get(r["symbol"], ""), "price": r.get("close"),
        "last_candle": r.get("last_bar_date"),
        "stale": "⚠️ STALE — audit only, not actionable" if r.get("stale") else "",
        "wyckoff_score": r.get("wyckoff_score"), "wyckoff": r.get("wyckoff_signal"),
        "4h_bb": r.get("wy_bb4h_compression"), "supply_exh": r.get("wy_supply_exhaustion"),
        "absorption": r.get("wy_absorption"), "obv_div": r.get("wy_obv_divergence"),
        "compression": r.get("compression_score"), "bull": r.get("bull_score"), "bear": r.get("bear_score"),
        "expansion_bull": r.get("bull_expansion_score"), "expansion_bear": r.get("bear_expansion_score"),
        "stage": r.get("stage_detail"), "confluence": r.get("confluence"), "conflict": r.get("conflict"),
        "history": ((r.get("hist") or {}).get("label") or "INSUFFICIENT HISTORICAL EVIDENCE"),
        "liquidity": r.get("liquidity"),
    } for r in rows])


def _fields(kind):
    U = _U()
    F = U.F
    common_tail = [F("liquidity", "Liquidity"), F("last_candle", "Last candle", kind="date", primary=False)]
    if kind == "ew":
        return [F("symbol", "Symbol"), F("stage", "Stage", card=False), F("company", "Company"),
                F("price", "Price", "%.2f", "num"),
                F("compression", "Compression", kind="num", bar="info", help="0–100, no direction; higher = tighter"),
                F("bull", "Bullish evidence", kind="num", bar="bull", help="0–100, scored independently of bearish"),
                F("bear", "Bearish evidence", kind="num", bar="bear", help="0–100, scored independently of bullish"),
                F("bbw_pct", "BBW pct (100d)", "%g", "num", help="Bollinger Band width percentile, lower = tighter"),
                F("atr_pct", "ATR pct (100d)", "%g", "num", help="Average True Range percentile, lower = calmer"),
                F("squeeze_d", "Squeeze days", "%g", "num", help="Consecutive days with Bollinger Bands inside Keltner"),
                F("dcw_pct", "Donchian width pct", "%g", "num", primary=False),
                F("vol_trend10", "Volume trend 10d", "%g", "num", primary=False),
                F("mtf", "Weekly alignment", primary=False), F("hist_n", "History n", "%g", "num", primary=False),
                ] + common_tail
    if kind in ("bull", "bear"):
        v = "bull" if kind == "bull" else "bear"
        return [F("symbol", "Symbol"), F("stage", "Stage", card=False), F("rank", "Rank", "%d", "num",
                                                                       help="The view's own order"),
                F("company", "Company"), F("price", "Price", "%.2f", "num"),
                F("compression", "Compression", kind="num", bar="info", help="0–100, no direction"),
                F("evidence", "Bullish evidence" if v == "bull" else "Bearish evidence", kind="num", bar=v,
                  help="0–100 heuristic, not a probability"),
                F("expansion", "Expansion", kind="num", bar=v, help="0–100 expansion confirmation"),
                F("break_level", "Break level", "%.2f", "num"), F("support", "Support", "%.2f", "num", primary=False),
                F("resistance", "Resistance", "%.2f", "num", primary=False),
                F("rel_vol", "Rel. volume", "%g", "num", primary=False),
                F("bbw_pct", "BBW pct (100d)", "%g", "num", primary=False),
                F("atr_pct", "ATR pct (100d)", "%g", "num", primary=False),
                F("history", "Historical evidence", help="Measured outcome after comparable setups, with sample size"),
                ] + common_tail
    if kind == "wv":
        return [F("symbol", "Symbol"), F("wyckoff", "Wyckoff", card=False), F("company", "Company"),
                F("stale", "Stale", card=False), F("price", "Price", "%.2f", "num"),
                F("wyckoff_score", "Wyckoff score", "%g", "num", help="Existing Wyckoff 1.0 score, unchanged"),
                F("compression", "Compression", kind="num", bar="info"),
                F("bull", "Bullish evidence", kind="num", bar="bull"), F("bear", "Bearish evidence", kind="num", bar="bear"),
                F("stage", "Stage"), F("confluence", "Confluence", kind="bool"), F("conflict", "Conflict", kind="bool"),
                F("4h_bb", "4h BB compression", kind="bool", primary=False),
                F("supply_exh", "Supply exhaustion", kind="bool", primary=False),
                F("absorption", "Absorption", kind="bool", primary=False),
                F("obv_div", "OBV divergence", kind="bool", primary=False),
                F("expansion_bull", "Bullish expansion", "%g", "num", primary=False),
                F("expansion_bear", "Bearish expansion", "%g", "num", primary=False),
                F("history", "Historical evidence", primary=False)] + common_tail
    return None


def _stage_badge(r):
    return [(r.get("stage"), "neutral")] if r.get("stage") else []


def _wv_badges(r):
    out = []
    if r.get("wyckoff"):
        out.append((r["wyckoff"], "info"))
    if r.get("confluence"):
        out.append(("Confluence", "info"))
    if r.get("conflict"):
        out.append(("Conflict — check before acting", "caution"))
    if r.get("stale"):
        out.append((r["stale"], "caution"))
    return out


def summaries(get, company_names):
    """Module records for the Overview (same rows the sub-views show)."""
    res = get("/patterns/volatility-engine")
    names = company_names() or {}
    age = res.get("_cache_age_seconds")
    base = {"group": "Volatility", "category": "Volatility", "timeframe": "1D / 1W", "age": age}
    if res.get("status") != "ok":
        return [dict(base, id="vol", name="Volatility Intelligence Engine", count=0, flags=[],
                     state_msg=("info", res.get("reason") or "Volatility engine unavailable right now."))]
    rows = [r for r in (res.get("rows") or []) if not r.get("stale")]
    ew, _ = _ew_rows(rows, names)
    bu, _ = _dir_rows(rows, names, 1)
    be, _ = _dir_rows(rows, names, -1)
    wv = get("/patterns/volatility-wyckoff")
    wvr, _ = _wv_rows(wv, names, st.session_state.get("vw_show", WV_SHOW[0])) if wv.get("status") == "ok" else ([], None)
    al = res.get("alerts") or []
    return [
        dict(base, id="vol_ew", name="Early Warning", sub=SUBVIEWS[0], count=len(ew),
             flags=[(r["symbol"], None, f"Compression · {STAGES[r['stage']]}") for r in ew]),
        dict(base, id="vol_bull", name="Bullish Expansion", sub=SUBVIEWS[1], count=len(bu),
             flags=[(r["symbol"], "bull", f"Bullish expansion · {r['stage_detail']}") for r in bu]),
        dict(base, id="vol_bear", name="Bearish Expansion", sub=SUBVIEWS[2], count=len(be),
             flags=[(r["symbol"], "bear", f"Bearish expansion · {r['stage_detail']}") for r in be]),
        dict(base, id="vol_wv", name="Wyckoff × Volatility", sub=SUBVIEWS[3], count=len(wvr), flags=[]),
        dict(base, id="vol_alerts", name="Alerts", sub=SUBVIEWS[4], count=len(al), flags=[]),
        dict(base, id="vol_val", name="Historical Validation", sub=SUBVIEWS[5], count=None, flags=[]),
    ]


def render(get, company_names):
    U = _U()
    res = get("/patterns/volatility-engine")
    with st.container(border=True):
        U.module_header({"category": "Volatility", "name": "Volatility Intelligence Engine", "timeframe": "1D / 1W",
                         "age": res.get("_cache_age_seconds")})
        if res.get("status") != "ok":
            st.info(res.get("reason") or "Volatility engine unavailable right now.")
            return
        stats = get("/patterns/volatility-engine/stats")
        all_rows = res.get("rows") or []
        # Stale rows (newest candle older than the session) are never ranked.
        rows = [r for r in all_rows if not r.get("stale")]
        names = company_names() or {}
        st.caption("Scores are configurable heuristics (0–100), **not probabilities**. Compression has no direction; "
                   "bullish and bearish evidence are scored independently.")
        _coverage(res, all_rows)
        with st.expander("Details — session, market regime and how to read this engine"):
            age = res.get("_cache_age_seconds")
            reg = res.get("regime") or {}
            st.caption(f"📦 {res.get('scanned')} symbols · last run {int(age // 3600) if isinstance(age, (int, float)) else '—'} h ago · "
                       f"market: {res.get('market_source')} · regime {reg.get('trend')} "
                       f"(index vol pct {reg.get('vol20_pct252')}, breadth {reg.get('breadth_above_sma50_pct')}% above SMA50"
                       f"{', RISK-OFF' if reg.get('risk_off') else ''}) · 4-hour: not used (35-day cache too short).")
            st.caption("Universe = only the stocks loaded in your database; 'market' strength is measured against their equal-weight index. "
                       "Scores are configurable heuristics (0–100), **not probabilities**. Compression has no direction; "
                       "bullish and bearish evidence are scored independently. Measured outcomes appear only where "
                       f"enough history exists" + ("" if res.get("stats_available") else
                                                   " — the historical engine has not been run yet, so every setup shows "
                                                   "INSUFFICIENT HISTORICAL EVIDENCE."))
            _coverage_detail(res, all_rows)
    sub = st.pills("Volatility view", SUBVIEWS, default=SUBVIEWS[0], key=SUBVIEW_KEY, required=True, wrap=True,
                   label_visibility="collapsed", width="stretch")
    if sub in SUBVIEWS[:3]:
        _filter_panel()
    with st.container(border=True):
        if sub == SUBVIEWS[0]:
            _sub_header(U, "Early Warning", "Stocks in early compression or an advanced squeeze, tightest first.")
            _, df = _ew_rows(rows, names)
            _table(df, "vol_ew", rows, get, "ew")
        elif sub in SUBVIEWS[1:3]:
            sgn = 1 if sub == SUBVIEWS[1] else -1
            _sub_header(U, "Bullish Expansion" if sgn > 0 else "Bearish Expansion",
                        "Bullish and bearish evidence are scored independently — neither is a probability.")
            _, df = _dir_rows(rows, names, sgn)
            _table(df, "vol_bull" if sgn > 0 else "vol_bear", rows, get, "bull" if sgn > 0 else "bear")
        elif sub == SUBVIEWS[3]:
            _wyckoff_view(get, names)
        elif sub == SUBVIEWS[4]:
            _sub_header(U, "Alerts", "Only condition changes since the previous daily run.")
            al = res.get("alerts") or []
            if not al:
                st.info("No new alerts — no symbol's condition changed since the previous run.")
            else:
                adf = pd.DataFrame(al)
                fields = [U.F(c, c.replace("_", " ").capitalize(),
                              "%g" if pd.api.types.is_numeric_dtype(adf[c]) else None,
                              "num" if pd.api.types.is_numeric_dtype(adf[c]) else "text") for c in adf.columns]
                U.results(adf, "vol_alerts", fields,
                          badge_fn=lambda r: [(r.get("alert"), "info")] if r.get("alert") else [],
                          company_col=None)
                st.caption("Only condition CHANGES since the previous daily run are listed. Priority blends "
                           "compression, directional evidence, expansion confirmation, liquidity, weekly alignment and "
                           "whether measured history exists. A compression alert is an early warning, not a buy signal.")
        else:
            _sub_header(U, "Historical Validation", "Measured outcomes, separate from the heuristic scores.")
            _validation(stats)


def _sub_header(U, name, note):
    st.markdown(f'<div class="pui-title">{U.esc(name)}</div>', unsafe_allow_html=True)
    st.caption(note)


def _table(df, key, rows, get, kind):
    U = _U()
    if df.empty:
        st.info("No symbol matches these filters today.")
        return
    picked = []
    U.results(df, key, _fields(kind), badge_fn=_stage_badge, on_open=picked.append, company_col="company",
              open_label="🔎 Show {sym} detailed analysis")
    st.caption("Select a row (or Open on a card) for its detailed analysis.")
    sym = picked[0] if picked else (st.session_state.get(f"{key}__card_open")
                                    if st.session_state.get("pui_layout", "Cards") == "Cards" else None)
    r = next((x for x in rows if x["symbol"] == sym), None) if sym else None
    if r is not None and sym in set(df["symbol"]):
        _detail(get, r, None)


def _validation(stats):
    if not stats or stats.get("status") != "ok":
        st.info((stats or {}).get("reason") or "Not run yet.")
        return
    st.caption(f"Run {str(stats.get('run_at'))[:16]} UTC · {stats['universe']} symbols · "
               f"{stats['data_from']} → {stats['data_to']} · train ≤ {stats['splits']['train_to']}, "
               f"validation ≤ {stats['splits']['validation_to']}, out-of-sample after · "
               f"cost {stats['assumptions']['cost_round_trip_pct']}% round trip · benchmark {stats['market_source']}")
    rows = []
    for k, g in stats["groups"].items():
        o = (stats["by_split"].get(k) or {}).get("oos") or {}
        la = (g or {}).get("long_atr") or {}
        sa = (g or {}).get("short_atr") or {}
        rows.append({"setup": k, "n": g["n"], "sufficient": g["sufficient"], "P(up 10d)%": g["p_up_10d"],
                     "mean 10d%": g["mean_10d"], "median 10d%": g["median_10d"],
                     "long target-first%": la.get("target_first_pct"), "long expectancy%": la.get("expectancy"),
                     "long PF": la.get("profit_factor"), "short target-first%": sa.get("target_first_pct"),
                     "short expectancy%": sa.get("expectancy"), "OOS n": o.get("n"),
                     "OOS mean 10d%": o.get("mean_10d"), "OOS long expectancy%": (o.get("long_atr") or {}).get("expectancy")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, key="vol_val")
    cal = stats.get("calibration") or {}
    for k, c in cal.items():
        if c and "brier" in c:
            st.markdown(f"**Calibration ({k})** — OOS n={c['n_oos']}, Brier {c['brier']} vs no-skill "
                        f"{c['brier_no_skill']} (skill {c['skill_vs_base_pct']}%)")
            st.dataframe(pd.DataFrame(c["reliability"]), hide_index=True, use_container_width=True, key=f"vol_cal_{k}")
    st.caption("Benchmarks: 'Baseline' = every 5th session of every stock; 'Simple BBW percentile < 10'; and the "
               "existing OBV+MFI+ATR and Regression-triangle modules, all measured the same way. Bearish trades "
               "assume shorting, which PSX restricts — read them as avoid/exit evidence.")


def _wyckoff_view(get, names):
    U = _U()
    res = get("/patterns/volatility-wyckoff")
    _sub_header(U, "Wyckoff × Volatility", "Existing Wyckoff 1.0 output next to the volatility engine — never added together.")
    if res.get("status") != "ok":
        st.info(res.get("reason") or "Combined view unavailable.")
        return
    with st.expander("Details — batches and how this view is built"):
        st.caption(f"Wyckoff batch {res.get('wyckoff_date')} ({res.get('n_wyckoff')} stocks) · volatility scan "
                   f"{res.get('volatility_rows_date')} ({res.get('n_volatility')} stocks). The Wyckoff score and "
                   "classification are the existing engine's output, unchanged. The volatility scores are separate; "
                   "neither is a probability and they are never added together. Wyckoff's 4-hour BB compression is "
                   "shown as its own flag and is not part of the volatility compression score (that uses daily BBW "
                   "percentiles), so nothing is counted twice.")
        st.caption("Confluence = a Wyckoff signal while the volatility engine shows compression or upside expansion "
                   "with bullish evidence ≥ bearish. Conflict = a Wyckoff signal while bearish evidence leads by "
                   "15+ points or a bearish expansion/failed breakout is active — check before acting.")
    st.caption(f"Wyckoff batch {res.get('wyckoff_date')} · volatility scan {res.get('volatility_rows_date')} · "
               "neither score is a probability.")
    only = st.radio("Show", WV_SHOW, horizontal=True, key="vw_show")
    rows, df = _wv_rows(res, names, only)
    if not rows:
        st.info("No stock matches this view today.")
        return
    U.results(df, "vw_table", _fields("wv"), badge_fn=_wv_badges)


def _coverage(res, all_rows):
    stale = [r for r in all_rows if r.get("stale")]
    unav = res.get("unavailable") or []
    exc = res.get("excluded") or []
    ranked = res.get("fresh", len(all_rows) - len(stale))
    st.caption(f"🗓️ Session {res.get('session', '—')} · Universe {res.get('universe_size', '—')} · Excluded {len(exc)} · "
               f"Unavailable {len(unav)} · Stale {len(stale)} · Ranked {ranked}")


def _coverage_detail(res, all_rows):
    stale = [r for r in all_rows if r.get("stale")]
    unav = res.get("unavailable") or []
    exc = res.get("excluded") or []
    st.caption(f"🗓️ Session {res.get('session', '—')} · {res.get('fresh', len(all_rows) - len(stale))} stocks with a "
               f"current candle · {len(stale)} stale · {len(unav)} unavailable · {len(exc)} excluded by the "
               f"configured exclusion list (universe {res.get('universe_size', '—')}).")
    if stale:
        st.markdown("**⚠️ Stale data** — newest candle older than the session; not ranked, no alerts:")
        st.dataframe(pd.DataFrame([{"symbol": r["symbol"], "last_candle": r.get("last_bar_date")} for r in stale]),
                     hide_index=True, key="vol_stale")
    if unav:
        st.markdown("**Unavailable** — no usable price data (not a negative signal):")
        st.dataframe(pd.DataFrame(unav), hide_index=True, key="vol_unav")
    if exc:
        st.markdown("**Excluded** by the configured exclusion list: " + ", ".join(exc))
