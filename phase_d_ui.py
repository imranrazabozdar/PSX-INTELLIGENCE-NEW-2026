"""phase_d_ui.py — the dashboard's top-level "Breakouts" tab: the Phase D
Breakout & Shelf Tracker.

Self-contained and read-only: one GET (/patterns/phase-d-scan), no
computation. Independent of the Patterns tab, which it does not touch.
"""
import pandas as pd
import streamlit as st

TITLE = "Phase D Breakout & Shelf Tracker"
ENDPOINT = "/patterns/phase-d-scan"
DISCLAIMER = ("⚠️ **Completed-bar technical state tracker, not a buy recommendation.** Each row says only "
              "which frozen price/volume condition a stock's latest completed daily bar met (a volume "
              "ignition, a shelf holding above it, or a breakout from that shelf). It is not a prediction, "
              "not a probability, and these rules have not been backtested on PSX yet.")
LABELS = {"SHELF_BREAKOUT": "SHELF BREAKOUT", "SOS_IGNITION": "SOS IGNITION", "ACTIVE_SHELF": "ACTIVE SHELF"}


def rows(scan, names):
    return pd.DataFrame([{
        "symbol": h["symbol"], "company": names.get(h["symbol"], ""),
        "signal": LABELS.get(h.get("signal_type"), h.get("signal_type")),
        "rvol": h.get("rvol"), "turnover": h.get("turnover_pkr"), "price": h.get("close"),
        "shelf days": h.get("shelf_days"), "chg %": h.get("pct_change"),
        "base/shelf high": h.get("base_or_shelf_high"), "up/down vol": h.get("up_down_vol_ratio"),
        "ignition": h.get("ignition_date"), "signal_type": h.get("signal_type"),
    } for h in (scan.get("hits") or [])])


def column_config():
    return {
        "symbol": "Symbol", "company": "Company", "signal": "Signal",
        "rvol": st.column_config.NumberColumn("RVOL", format="%.2fx",
                                              help="Volume ÷ average of the previous 20 sessions"),
        "turnover": st.column_config.NumberColumn("Turnover (PKR)", format="localized", help="Close × volume"),
        "price": st.column_config.NumberColumn("Price", format="Rs %.2f"),
        "shelf days": st.column_config.NumberColumn("Shelf Days", format="%d",
                                                    help="Trading days since the ignition bar"),
    }


def rules():
    st.caption("**Frozen rules — completed daily bars only, nothing looks ahead.** RVOL and the volume tests "
               "use the average volume of the 20 sessions *before* the bar. Strong close = (close − low) / "
               "(high − low) ≥ 0.70, or a PSX upper lock (high = low and close above the previous close). "
               "Breakout-type days (SOS Ignition, Shelf Breakout) also need turnover (close × volume) ≥ "
               "PKR 5,000,000.")
    st.caption("**SOS IGNITION** — close above the highest high of the previous 20 sessions, volume ≥ 4.0× "
               "the 20-session average, the previous 20 sessions' range (max high − min low) / min low ≤ 30%, "
               "and a strong close.")
    st.caption("**ACTIVE SHELF** — an SOS Ignition 3 to 12 trading days ago (the most recent one); every "
               "close since stays above the ignition bar's midpoint (open + close) / 2 and above the 20-day "
               "EMA; the shelf's range (high − low) / low ≤ 28%; and average up-day volume ≥ 1.8× average "
               "down-day volume (when there are down days).")
    st.caption("**SHELF BREAKOUT** — the stock was an Active Shelf through yesterday, and today closes above "
               "that shelf's high on volume ≥ 2.5× the 20-session average with a strong close.")
    st.caption("One signal per stock per day, in priority Shelf Breakout > SOS Ignition > Active Shelf. Same "
               "universe and exclusion list as Wyckoff; stocks with fewer than 30 bars, or whose newest "
               "candle is not the session date (stale), are skipped. Last 90 daily bars from the shared "
               "daily_ohlc data. Runs once per weekday with the pattern refresh "
               "(fire_engine/run_phase_d_tracker.py). Standalone — independent of the Wyckoff 1.0 engine "
               "and its scores.")


def caption(scan):
    return (f"Last completed scan: {scan.get('date') or '—'} · {len(scan.get('hits') or [])} stock(s) in a "
            "Phase D state, ordered Shelf Breakout, SOS Ignition, Active Shelf, then RVOL.")


def counts(scan):
    hits = scan.get("hits") or []
    return {k: sum(1 for h in hits if h.get("signal_type") == k) for k in LABELS}


def render_tab(get, company_names, render_table, scan_status_banner, refresh_params):
    """Top-level Breakouts tab: summary metrics, disclaimer, table, rules."""
    st.markdown('<div class="psx-section-eyebrow">BREAKOUTS</div>'
                f'<div class="psx-section-title">🚀 {TITLE}</div>', unsafe_allow_html=True)
    scan = get(ENDPOINT, **refresh_params)
    ok = scan.get("status") == "ok"
    n = counts(scan) if ok else {k: None for k in LABELS}
    c1, c2, c3 = st.columns(3)
    c1.metric("Shelf Breakouts", "—" if n["SHELF_BREAKOUT"] is None else n["SHELF_BREAKOUT"],
              help="SHELF_BREAKOUT on the latest scanned session")
    c2.metric("SOS Ignitions", "—" if n["SOS_IGNITION"] is None else n["SOS_IGNITION"],
              help="SOS_IGNITION on the latest scanned session")
    c3.metric("Active Shelves", "—" if n["ACTIVE_SHELF"] is None else n["ACTIVE_SHELF"],
              help="ACTIVE_SHELF on the latest scanned session")
    st.warning(DISCLAIMER)
    if scan_status_banner(scan, TITLE):
        if not scan.get("hits"):
            st.info(scan.get("reason") or f"No stock is in a Phase D state on {scan.get('date') or 'the latest scan'}.")
        else:
            st.caption(caption(scan))
            df = rows(scan, company_names())
            render_table(df[["symbol", "company", "signal", "rvol", "turnover", "price", "shelf days"]], None,
                         "phase_d_scan_table", column_config())
    with st.expander(f"📖 View Rules & Metrics for {TITLE}"):
        rules()
