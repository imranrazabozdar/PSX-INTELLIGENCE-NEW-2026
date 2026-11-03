"""wyckoff2_ui.py — Patterns tab section "Wyckoff Institutional Accumulation".

Shows the ORIGINAL production Wyckoff result (unchanged, from the production
batch via /patterns/volatility-wyckoff) next to the Wyckoff Accumulation 2.0
RESEARCH classification (/patterns/wyckoff2-research). Read-only: three GET
endpoints, no computation here. Stale / missing-data stocks are listed
separately and never shown as actionable candidates.
"""
import pandas as pd
import streamlit as st

ENH = ["POTENTIAL BREAKOUT", "ADVANCED ACCUMULATION", "STRONG ACCUMULATION", "DEVELOPING ACCUMULATION",
       "FAILED ACCUMULATION", "NO CLEAR ACCUMULATION"]
RANK = {k: i for i, k in enumerate(ENH)}
SORTS = {"Enhanced class (strongest first)": None, "Original Wyckoff score": "orig_score",
         "Relative strength": "rs_q", "Absorption quality": "abs_q", "OBV divergence quality": "obv_q",
         "Accumulation structure": "struct_q", "Resistance proximity (closest first)": "dist_res_pct"}


def _agree(orig, enh):
    o = orig in ("READY", "EXTREME", "WATCH")
    e = enh in ("STRONG ACCUMULATION", "ADVANCED ACCUMULATION", "POTENTIAL BREAKOUT")
    return "both" if o and e else "original only" if o else "enhanced only" if e else "neither"


def render(get, company_names):
    st.markdown('<div class="psx-section-eyebrow">ACCUMULATION</div>'
                '<div class="psx-section-title">🏛️ Wyckoff Institutional Accumulation — 1D</div>',
                unsafe_allow_html=True)
    research = get("/patterns/wyckoff2-research")
    prod = get("/patterns/volatility-wyckoff")
    stats = get("/patterns/wyckoff2-research/stats")
    names = company_names() or {}
    prod_rows = {r["symbol"]: r for r in (prod.get("rows") or [])} if prod.get("status") == "ok" else {}
    st.warning("🧪 **Wyckoff Accumulation 2.0 is EXPERIMENTAL / NOT PRODUCTION.** The *Original Wyckoff* columns are "
               "the unchanged production engine. Research scores are heuristics (0–100), not probabilities.")
    if research.get("status") != "ok":
        st.info(research.get("reason") or "Research scan unavailable.")
        return
    th = research.get("thresholds") or {}
    st.caption(f"Research session {research.get('session')} · production Wyckoff batch {prod.get('wyckoff_date', '—')} · "
               f"benchmark {research.get('benchmark')} · thresholds ({research.get('thresholds_source')}): {th}")
    by_class = (stats or {}).get("by_class") or {}
    rows, stale = [], []
    for r in research.get("rows", []):
        p = prod_rows.get(r["symbol"], {})
        if r.get("stale") or p.get("stale"):
            stale.append({"symbol": r["symbol"], "last_candle": r.get("last_bar_date")})
            continue
        h = (by_class.get(r["enh_class"]) or {}).get("test") or {}
        rows.append({
            "symbol": r["symbol"], "company": names.get(r["symbol"], ""), "price": r.get("close"),
            "chg_pct": r.get("chg_pct"), "orig_score": p.get("wyckoff_score"), "orig_class": p.get("wyckoff_signal"),
            "enh_class": r["enh_class"], "abs_q": r.get("abs_q"), "obv_q": r.get("obv_q"),
            "struct_q": r.get("struct_q"), "rs_q": r.get("rs_q"), "dist_res_pct": r.get("dist_res_pct"),
            "confirming": r.get("confirming"), "signal_date": r.get("class_since"), "timeframe": "1D",
            "agreement": _agree(p.get("wyckoff_signal"), r["enh_class"]),
            "hist_test_10d": (f"{h.get('mean_10d')}% avg 10d, n={h.get('n')}" if h.get("n", 0) >= 30
                              else ("INSUFFICIENT EVIDENCE" if stats.get("status") == "ok" else "backtest not run")),
            "_raw": r, "_prod": p})
    c1, c2, c3 = st.columns(3)
    classes = c1.multiselect("Enhanced class", ENH, default=ENH[:4], key="w2_cls")
    view = c2.selectbox("Show", ["All", "Original READY / EXTREME only", "Original and enhanced agree",
                                 "Enhanced differs from original"], key="w2_view")
    sort = c3.selectbox("Sort by", list(SORTS), key="w2_sort")
    f = [x for x in rows if x["enh_class"] in classes] if classes else rows
    if view.startswith("Original READY"):
        f = [x for x in rows if x["orig_class"] in ("READY", "EXTREME")]
    elif view.startswith("Original and enhanced agree"):
        f = [x for x in f if x["agreement"] == "both"]
    elif view.startswith("Enhanced differs"):
        f = [x for x in rows if x["agreement"] in ("original only", "enhanced only")]
    key = SORTS[sort]
    if key is None:
        f.sort(key=lambda x: (RANK.get(x["enh_class"], 9), -(x["confirming"] or 0)))
    elif key == "dist_res_pct":
        f.sort(key=lambda x: x[key] if x[key] is not None else 1e9)
    else:
        f.sort(key=lambda x: -(x[key] if x[key] is not None else -1))
    if not f:
        st.info("No stock matches these filters.")
    else:
        df = pd.DataFrame([{k: v for k, v in x.items() if not k.startswith("_")} for x in f])
        ev = st.dataframe(df, hide_index=True, use_container_width=True, key="w2_table", on_select="rerun",
                          selection_mode="single-row", column_config={
            "price": st.column_config.NumberColumn("Price", format="Rs %.2f"),
            "chg_pct": st.column_config.NumberColumn("Day %", format="%.2f%%"),
            "orig_score": st.column_config.NumberColumn("Original score", format="%d"),
            "orig_class": "Original class", "enh_class": "Enhanced class (RESEARCH)",
            "abs_q": st.column_config.NumberColumn("Absorption", format="%.0f"),
            "obv_q": st.column_config.NumberColumn("OBV div.", format="%.0f"),
            "struct_q": st.column_config.NumberColumn("Structure", format="%.0f"),
            "rs_q": st.column_config.NumberColumn("RS vs KSE-100", format="%.0f"),
            "dist_res_pct": st.column_config.NumberColumn("To resistance", format="%.1f%%"),
            "confirming": "Confirming", "signal_date": "Class since", "hist_test_10d": "Out-of-sample history"})
        st.caption("Select a row for the stock-level explanation.")
        sel = getattr(getattr(ev, "selection", None), "rows", None) or []
        if sel:
            _detail(f[sel[0]], th)
    if stale or research.get("unavailable") or research.get("excluded"):
        with st.expander(f"Not shown as candidates: {len(stale)} stale, {len(research.get('unavailable') or [])} "
                         f"unavailable, {len(research.get('excluded') or [])} excluded"):
            if stale:
                st.markdown("**⚠️ Stale data — not actionable:**")
                st.dataframe(pd.DataFrame(stale), hide_index=True, key="w2_stale")
            if research.get("unavailable"):
                st.markdown("**Unavailable (missing price data):**")
                st.dataframe(pd.DataFrame(research["unavailable"]), hide_index=True, key="w2_unav")
            if research.get("excluded"):
                st.markdown("**Excluded by configuration:** " + ", ".join(research["excluded"]))
    _backtest_summary(stats)


def _detail(x, th):
    r, p = x["_raw"], x["_prod"]
    ex = r.get("explain") or {}
    st.markdown(f"#### {x['symbol']} — {x['enh_class']} *(research)* · original {x['orig_class']} {x['orig_score']}")
    a, b = st.columns(2)
    with a:
        st.markdown("**Original Wyckoff (production, unchanged)**")
        st.markdown("\n".join(f"- {k}: {'✅' if p.get(f) else '—'}" for k, f in (
            ("4-hour BB compression (20)", "wy_bb4h_compression"), ("Supply exhaustion (20)", "wy_supply_exhaustion"),
            ("Absorption (30)", "wy_absorption"), ("OBV divergence (30)", "wy_obv_divergence"),
            ("Consolidation gate", "wy_consolidating"), ("MACD gate", "wy_macd_gate"))))
    with b:
        st.markdown("**Wyckoff 2.0 evidence (RESEARCH)**")
        st.markdown(f"- Absorption quality {r.get('abs_q')} · high-volume days {r.get('hv_days')}"
                    f"{' · two-sided' if r.get('two_sided') else ''}\n"
                    f"- OBV divergence quality {r.get('obv_q')}{' · divergence confirmed' if r.get('obv_div') else ''}\n"
                    f"- Structure {r.get('struct_q')} · ATR10/ATR40 {r.get('atr_contraction')} · position in base "
                    f"{r.get('pos_in_base')}\n"
                    f"- RS {r.get('rs_q')} · excess 20d {r.get('excess20')} pts · 60d {r.get('excess60')} pts · "
                    f"down-day resilience {r.get('down_day_resilience')} pts")
    st.markdown("**Why it is classified this way**")
    for s in ex.get("satisfied", []):
        st.markdown(f"- ✅ {s}")
    for s in ex.get("missing", []):
        st.markdown(f"- ⬜ {s}")
    st.markdown(f"**Location:** {ex.get('location')}")
    st.markdown(f"**Stage:** {'advanced / near breakout' if x['enh_class'] in ('ADVANCED ACCUMULATION', 'POTENTIAL BREAKOUT') else 'developing' if x['enh_class'] in ('DEVELOPING ACCUMULATION', 'STRONG ACCUMULATION') else 'no active setup'}")
    st.markdown(f"**Invalidation:** {ex.get('invalidation')}")


def _backtest_summary(stats):
    with st.expander("🧪 Historical RESEARCH backtest — original vs Wyckoff 2.0"):
        if not stats or stats.get("status") != "ok":
            st.info((stats or {}).get("reason") or "Not run yet.")
            return
        st.caption(f"{stats['data_from']} → {stats['data_to']} · train ≤ {stats['splits']['train_to']}, test after "
                   f"{stats['splits']['validation_to']} · {stats['original_note']} · entries into upper-circuit locks "
                   f"are unfilled; costs and slippage included.")
        rows = []
        for eng in ("original", "enhanced"):
            for sp in ("all", "test"):
                s = stats["engines"][eng][sp]
                rows.append({"engine": eng, "period": sp, "signals": s.get("n"), "avg 5d %": s.get("mean_5d"),
                             "avg 10d %": s.get("mean_10d"), "avg 20d %": s.get("mean_20d"), "win 10d %": s.get("win_10d"),
                             "breakout %": s.get("breakout_pct"), "failed b/o %": s.get("failed_breakout_pct"),
                             "MFE %": s.get("avg_mfe"), "MAE %": s.get("avg_mae"), "PF": s.get("profit_factor")})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, key="w2_bt")
