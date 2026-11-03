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
SORTS = {"Enhanced class (strongest first)": None, "Stock symbol (A→Z)": "symbol", "Original Wyckoff score": "orig_score",
         "Relative strength": "rs_q", "Absorption quality": "abs_q", "OBV divergence quality": "obv_q",
         "Accumulation structure": "struct_q", "Resistance proximity (closest first)": "dist_res_pct"}


def _agree(orig, enh):
    o = orig in ("READY", "EXTREME", "WATCH")
    e = enh in ("STRONG ACCUMULATION", "ADVANCED ACCUMULATION", "POTENTIAL BREAKOUT")
    return "both" if o and e else "original only" if o else "enhanced only" if e else "neither"


ENH_FLAG = ("STRONG ACCUMULATION", "ADVANCED ACCUMULATION", "POTENTIAL BREAKOUT")   # same set as _agree()


def _rows(research, prod, stats, names):
    prod_rows = {r["symbol"]: r for r in (prod.get("rows") or [])} if prod.get("status") == "ok" else {}
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
    secmap = _sectors()
    for x in rows:
        x["sector"] = secmap.get(x["symbol"], "Unknown")
    return rows, stale


def summary(get, company_names):
    research = get("/patterns/wyckoff2-research")
    base = {"id": "w2", "group": "Wyckoff 2.0", "category": "Research / Experimental",
            "name": "Wyckoff Institutional Accumulation 2.0", "timeframe": "1D", "status": "RESEARCH",
            "status_variant": "research", "count_label": "research flags"}
    if research.get("status") != "ok":
        return dict(base, count=0, flags=[], state_msg=("info", research.get("reason") or "Research scan unavailable."))
    rows, _ = _rows(research, get("/patterns/volatility-wyckoff"), get("/patterns/wyckoff2-research/stats"),
                    company_names() or {})
    fl = [x for x in rows if x["enh_class"] in ENH_FLAG]
    import patterns_ui as U
    return dict(base, count=len(fl), updated=U.friendly_age(iso=research.get("run_at")),
                flags=[(x["symbol"], None, f"Research: {x['enh_class'].title()}") for x in fl])


def _badges(x):
    out = [(x["enh_class"], "research")]
    if x.get("orig_class") and x["orig_class"] != "NO_SIGNAL":
        out.append((f"Original {x['orig_class']}", "info"))
    return out


def render(get, company_names):
    import patterns_ui as U
    research = get("/patterns/wyckoff2-research")
    prod = get("/patterns/volatility-wyckoff")
    stats = get("/patterns/wyckoff2-research/stats")
    names = company_names() or {}
    with st.container(border=True):
        U.module_header({"category": "Research / Experimental", "name": "Wyckoff Institutional Accumulation 2.0",
                         "timeframe": "1D", "status": "RESEARCH · EXPERIMENTAL / NOT PRODUCTION",
                         "status_variant": "research",
                         "updated": (f"Trading date {research.get('session')} · "
                                     + U.friendly_age(iso=research.get("run_at"))) if research.get("status") == "ok" else None})
        st.warning("🧪 **Wyckoff Accumulation 2.0 is EXPERIMENTAL / NOT PRODUCTION.** The *Original Wyckoff* columns are "
                   "the unchanged production engine. Research scores are heuristics (0–100), not probabilities.")
        if research.get("status") != "ok":
            st.info(research.get("reason") or "Research scan unavailable.")
            return
        th = research.get("thresholds") or {}
        if prod.get("wyckoff_date") and research.get("session") and str(research["session"]) < str(prod["wyckoff_date"]):
            st.error(f"⚠️ OUTDATED: research results are for {research['session']}, older than the latest Wyckoff 1.0 batch "
                     f"({prod['wyckoff_date']}). Do not treat them as current.")
        rows, stale = _rows(research, prod, stats, names)
        cls_sel = st.session_state.get("w2_cls", ENH)
        with st.expander("Filter and sort — " + (
                f"{st.session_state.get('w2_view', 'All')} · {st.session_state.get('w2_sort', list(SORTS)[0])}"
                + (f" · {len(cls_sel)} of {len(ENH)} classes" if cls_sel != ENH else "")
                + (f" · sectors: {', '.join(st.session_state.get('w2_sec'))}" if st.session_state.get("w2_sec") else ""))):
            c1, c2 = st.columns(2)
            classes = c1.multiselect("Enhanced class", ENH, default=ENH, key="w2_cls",
                                     help="Wyckoff 2.0 research class")
            view = c2.selectbox("Show", ["All", "Original READY / EXTREME only", "Original and enhanced agree",
                                         "Enhanced differs from original"], key="w2_view")
            c3, c4 = st.columns(2)
            sort = c3.selectbox("Sort by", list(SORTS), key="w2_sort")
            secs = c4.multiselect("Sector", sorted({x["sector"] for x in rows}), default=[], key="w2_sec",
                                  placeholder="All sectors")
        f = [x for x in rows if x["enh_class"] in classes] if classes else rows
        if view.startswith("Original READY"):
            f = [x for x in rows if x["orig_class"] in ("READY", "EXTREME")]
        elif view.startswith("Original and enhanced agree"):
            f = [x for x in f if x["agreement"] == "both"]
        elif view.startswith("Enhanced differs"):
            f = [x for x in rows if x["agreement"] in ("original only", "enhanced only")]
        if secs:
            f = [x for x in f if x["sector"] in secs]
        key = SORTS[sort]
        if key == "symbol":
            f.sort(key=lambda x: x["symbol"])
        elif key is None:
            f.sort(key=lambda x: (RANK.get(x["enh_class"], 9), -(x["confirming"] or 0)))
        elif key == "dist_res_pct":
            f.sort(key=lambda x: x[key] if x[key] is not None else 1e9)
        else:
            f.sort(key=lambda x: -(x[key] if x[key] is not None else -1))
        if not f:
            st.info("No stock matches these filters.")
        else:
            df = pd.DataFrame([{k: v for k, v in x.items() if not k.startswith("_")} for x in f])
            F = U.F
            fields = [F("symbol", "Symbol"), F("enh_class", "Enhanced class (RESEARCH)", card=False),
                      F("company", "Company"), F("orig_class", "Original class", card=False,
                                                 help="Wyckoff 1.0 production class, unchanged"),
                      F("orig_score", "Original score", "%d", "num"), F("price", "Price", "Rs %.2f", "num"),
                      F("chg_pct", "Day %", "%.2f%%", "num"),
                      F("abs_q", "Absorption", "%.0f", "num", help="Research absorption quality 0–100"),
                      F("obv_q", "OBV div.", "%.0f", "num", help="Research OBV divergence quality 0–100"),
                      F("struct_q", "Structure", "%.0f", "num", help="Research accumulation-structure quality 0–100"),
                      F("rs_q", "RS vs KSE-100", "%.0f", "num", help="Research relative-strength quality 0–100"),
                      F("dist_res_pct", "To resistance", "%.1f%%", "num"),
                      F("confirming", "Confirming", "%g", "num", primary=False),
                      F("signal_date", "Class since", kind="date", primary=False),
                      F("agreement", "Original vs research", primary=False),
                      F("sector", "Sector", primary=False), F("timeframe", "Timeframe", primary=False),
                      F("hist_test_10d", "Out-of-sample history", primary=False)]
            picked = []
            U.results(df, "w2_table", fields, badge_fn=_badges, on_open=picked.append,
                      open_label="🔎 Explain {sym}")
            st.caption("Select a row (or Open on a card) for the stock-level explanation.")
            sym = picked[0] if picked else (st.session_state.get("w2_table__card_open")
                                            if st.session_state.get("pui_layout", "Cards") == "Cards" else None)
            x = next((x for x in f if x["symbol"] == sym), None) if sym else None
            if x is not None:
                _detail(x, th)
        with st.expander("Details — thresholds, batch and stocks not shown"):
            st.caption(f"Research scan for trading date **{research.get('session')}** · saved {str(research.get('run_at', '—'))[:19]} UTC · "
                       f"original Wyckoff 1.0 batch {prod.get('wyckoff_date', '—')} · benchmark {research.get('benchmark')} · "
                       f"thresholds ({research.get('thresholds_source')}): {th}")
            if stale or research.get("unavailable") or research.get("excluded"):
                st.markdown(f"**Not shown as candidates: {len(stale)} stale, {len(research.get('unavailable') or [])} "
                            f"unavailable, {len(research.get('excluded') or [])} excluded**")
                if stale:
                    st.markdown("**⚠️ Stale data — not actionable:**")
                    st.dataframe(pd.DataFrame(stale), hide_index=True, key="w2_stale")
                if research.get("unavailable"):
                    st.markdown("**Unavailable (missing price data):**")
                    st.dataframe(pd.DataFrame(research["unavailable"]), hide_index=True, key="w2_unav")
                if research.get("excluded"):
                    st.markdown("**Excluded by configuration:** " + ", ".join(research["excluded"]))
        _backtest_summary(stats)


def _sectors():
    """Sector per symbol from the repository's cached PSX symbol directory
    (backend/symbol_names.json) -- a local file, no network or database call."""
    import json
    import os
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "symbol_names.json")
        m = json.load(open(p, encoding="utf-8")).get("map", {})
        return {k: (v or {}).get("sector") or "Unknown" for k, v in m.items()}
    except Exception:
        return {}


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
