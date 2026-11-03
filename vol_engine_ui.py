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


def _filters(rows, key):
    c1, c2, c3, c4 = st.columns(4)
    liq = c1.multiselect("Liquidity", LIQ, default=["Highly Liquid", "Liquid", "Moderate Liquidity"], key=f"{key}_liq")
    stages = c2.multiselect("Stage", list(STAGES.values()), default=[], key=f"{key}_stage",
                            placeholder="All stages")
    min_tv = c3.number_input("Min avg traded value (PKR m)", 0.0, 10000.0, 0.0, 5.0, key=f"{key}_tv")
    max_bbw = c4.slider("Max BBW percentile", 0, 100, 100, key=f"{key}_bbw")
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


def render(get, company_names):
    st.markdown('<div class="psx-section-eyebrow">VOLATILITY</div>'
                '<div class="psx-section-title">📊 VOLATILITY INTELLIGENCE ENGINE — 1D / 1W</div>',
                unsafe_allow_html=True)
    res = get("/patterns/volatility-engine")
    if res.get("status") != "ok":
        st.info(res.get("reason") or "Volatility engine unavailable right now.")
        return
    stats = get("/patterns/volatility-engine/stats")
    rows = res.get("rows") or []
    names = company_names() or {}
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

    v1, v2, v3, v4, v5 = st.tabs(["⚠️ Early Warning", "🟢 Bullish Expansion", "🔴 Bearish Expansion",
                                  "🔔 Alerts", "🧪 Historical Validation"])
    with v1:
        f = _filters(rows, "vew")
        f = [r for r in f if r["stage"] in (1, 2) or (r["compression_score"] or 0) >= 50]
        f.sort(key=lambda r: -(r["compression_score"] or 0))
        df = pd.DataFrame([{
            "symbol": r["symbol"], "company": names.get(r["symbol"], ""), "price": r["close"],
            "compression": r["compression_score"], "bbw_pct": r["bbw_pct100"], "atr_pct": r["atr_pct100"],
            "squeeze_d": r["squeeze_run"], "dcw_pct": r["dc_width_pct200"], "vol_trend10": r["vol_trend10"],
            "bull": r["bull_score"], "bear": r["bear_score"], "stage": STAGES[r["stage"]],
            "mtf": r["mtf_alignment"], "liquidity": r["liquidity"], "hist_n": (r.get("hist") or {}).get("n", 0),
        } for r in f])
        _table(df, "vol_ew", rows, get)
    for tab, sgn in ((v2, 1), (v3, -1)):
        with tab:
            k = "bull" if sgn > 0 else "bear"
            f = _filters(rows, f"v{k}")
            f = [r for r in f if (r[f"{k}_score"] or 0) >= 40 and (r["stage"] > 0 or (r["compression_score"] or 0) >= 40)
                 and not (r["stage"] == 5 and r["stage_dir"] == sgn)]
            f.sort(key=lambda r: -((r[f"{k}_score"] or 0) * 0.5 + (r[f"{k}_expansion_score"] or 0) * 0.3
                                   + (r["compression_score"] or 0) * 0.2))
            df = pd.DataFrame([{
                "rank": i + 1, "symbol": r["symbol"], "company": names.get(r["symbol"], ""), "price": r["close"],
                "compression": r["compression_score"], "evidence": r[f"{k}_score"],
                "expansion": r[f"{k}_expansion_score"], "bbw_pct": r["bbw_pct100"], "atr_pct": r["atr_pct100"],
                "rel_vol": r["rv20"], "break_level": r["break_level"] or (r["box_hi"] if sgn > 0 else r["box_lo"]),
                "support": r["box_lo"], "resistance": r["box_hi"], "stage": r["stage_detail"],
                "history": _hist_cell(r.get("hist"), sgn), "liquidity": r["liquidity"],
            } for i, r in enumerate(f)])
            _table(df, f"vol_{k}", rows, get)
    with v4:
        al = res.get("alerts") or []
        if not al:
            st.info("No new alerts — no symbol's condition changed since the previous run.")
        else:
            st.dataframe(pd.DataFrame(al), hide_index=True, use_container_width=True, key="vol_alerts")
            st.caption("Only condition CHANGES since the previous daily run are listed. Priority blends "
                       "compression, directional evidence, expansion confirmation, liquidity, weekly alignment and "
                       "whether measured history exists. A compression alert is an early warning, not a buy signal.")
    with v5:
        _validation(stats)


def _table(df, key, rows, get):
    if df.empty:
        st.info("No symbol matches these filters today.")
        return
    ev = st.dataframe(df, hide_index=True, use_container_width=True, key=key,
                      on_select="rerun", selection_mode="single-row")
    sel = getattr(getattr(ev, "selection", None), "rows", None) or []
    st.caption("Select a row to open its detailed analysis.")
    if sel:
        sym = df.iloc[sel[0]]["symbol"]
        r = next(x for x in rows if x["symbol"] == sym)
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
