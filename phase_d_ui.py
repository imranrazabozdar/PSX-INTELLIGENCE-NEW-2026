"""phase_d_ui.py — the dashboard's top-level "Breakouts" tab: the Phase D
Breakout & Shelf Tracker.

Self-contained and read-only: one GET (/patterns/phase-d-scan), no
computation. Independent of the Patterns tab, which it does not touch.
"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

TITLE = "Phase D Breakout & Shelf Tracker"
ENDPOINT = "/patterns/phase-d-scan"
DISCLAIMER = ("⚠️ **Completed-bar technical state tracker, not a buy recommendation.** Each row says only "
              "which frozen price/volume condition a stock's latest completed daily bar met (a volume "
              "ignition, a shelf holding above it, or a breakout from that shelf). It is not a prediction, "
              "not a probability, and these rules have not been backtested on PSX yet.")
LABELS = {"SHELF_BREAKOUT": "SHELF BREAKOUT", "SOS_IGNITION": "SOS IGNITION", "ACTIVE_SHELF": "ACTIVE SHELF"}


MAX_SHELF_DAY = 12
INVALIDATION = ("Do not enter if price closes below its 20 EMA or falls back into the ignition base, "
                "or if no breakout occurs by Day 12.")
# (rank, short badge, stage name) -- display grouping only; the detector decides the signal
TIERS = {
    1: ("🟢 Entry triggered today", "Entry Triggered Today"),
    2: ("🟠 Final breakout window", "Final Breakout Window (Days 9–12)"),
    3: ("🔵 Building shelf", "Building Shelf (Days 3–8)"),
    4: ("⚪ Fresh ignition — wait", "Fresh Ignition (Wait 3 Sessions for Shelf)"),
}


def tier(h):
    t, d = h.get("signal_type"), int(h.get("shelf_days") or 0)
    if t == "SHELF_BREAKOUT":
        return 1
    if t == "ACTIVE_SHELF":
        return 2 if d >= 9 else 3
    return 4


def sort_hits(hits):
    """Closest to an actionable entry first: breakouts (RVOL desc); shelves on days 9-12, then days 3-8
    (shelf days desc, then RVOL desc); fresh ignitions (RVOL desc)."""
    def key(h):
        k, rv, d = tier(h), float(h.get("rvol") or 0), int(h.get("shelf_days") or 0)
        return (k, 0 if k in (1, 4) else -d, -rv)
    return sorted(hits or [], key=key)


def add_trading_days(d, n):
    """`d` plus `n` PSX trading weekdays (Mon-Fri; weekends skipped -- exchange holidays are not known here)."""
    d = date.fromisoformat(d) if isinstance(d, str) else d
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _fmt_day(d):
    return f"{d:%a}, {d:%b} {d.day}"


def _fmt_range(a, b):
    return _fmt_day(a) if a == b else f"{_fmt_day(a)} – {_fmt_day(b)}"


def fmt_turnover(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.1f}{suf}"
    return f"{v:.0f}"


def watch(h, scan_date):
    """(dates text, verdict) for one stock, from its scan date and shelf day."""
    t, d = h.get("signal_type"), int(h.get("shelf_days") or 0)
    if t == "SHELF_BREAKOUT":
        return (f"Entry conditions satisfied on {_fmt_day(date.fromisoformat(scan_date))} (Day 1 of the breakout).",
                f"Entry Triggered Today (shelf Day {d}) — every breakout condition was met on the latest close")
    if t == "SOS_IGNITION":
        a, b = add_trading_days(scan_date, 3), add_trading_days(scan_date, MAX_SHELF_DAY)
        return (f"Shelf window opens {_fmt_day(a)} (Day 3) and runs to {_fmt_day(b)} (Day 12): "
                f"{_fmt_range(a, b)}.",
                "Fresh Ignition (Day 0) — Too early to chase; wait 3 sessions to see if a shelf forms")
    # a breakout fires on the session AFTER a valid shelf day, so the last breakout chance is the
    # session after Day 12 (the shelf must still be valid through Day 12)
    first, last = add_trading_days(scan_date, 1), add_trading_days(scan_date, MAX_SHELF_DAY + 1 - d)
    verdict = (f"Final Breakout Window (Day {d} of 12) — Watch closely for breakout trigger" if d >= 9 else
               f"Building Shelf (Day {d} of 12) — Shelf still forming; watch for a breakout")
    return (f"Breakout can trigger on: {_fmt_range(first, last)} — the last chance is the session after "
            f"Day 12, and only while the shelf still holds.", verdict)


def invalidation(h, scan_date):
    """Exact next-session cancel levels from the stored EMA20 / ignition floor. None when not stored.
    EMA20 recursion: close[t+1] > EMA20[t+1] <=> close[t+1] > EMA20[t], so tonight's EMA20 is tomorrow's line."""
    ema, flo = h.get("ema20"), h.get("ignition_floor")
    if ema is None and flo is None:
        return None
    ema = float(ema) if ema is not None else None
    flo = float(flo) if flo is not None else None
    lvl = max(v for v in (ema, flo) if v is not None)
    nxt = _fmt_day(add_trading_days(scan_date, 1))
    why = " and ".join(x for x in ((f"20-EMA Rs. {ema:.2f}" if ema is not None else ""),
                                   (f"ignition floor Rs. {flo:.2f}" if flo is not None else "")) if x)
    out = [f"Cancelled if it **closes at or below Rs. {lvl:.2f} on {nxt}** (the higher of {why})."]
    hi = h.get("base_or_shelf_high")
    if h.get("signal_type") == "ACTIVE_SHELF" and hi is not None:
        out.append(f"Also cancelled if any day's **low trades below Rs. {0.75 * float(hi):.2f}** "
                   f"(25% under the shelf peak Rs. {float(hi):.2f}).")
    out.append("The level is recalculated after every close — check the updated figure each evening. "
               "Weak up-day vs down-day volume can also end the shelf (no price equivalent).")
    return out


BADGE_LABELS = (("coil_dryup", "COIL"), ("w1_leader", "1W"), ("exhausted_pre_ign", "EXH"))


def badges(h):
    """Compact pre-ignition badges, e.g. 'COIL·1W·EXH'. Blank when a row has none (older rows, or NULL)."""
    return "·".join(lbl for key, lbl in BADGE_LABELS if h.get(key) in (1, True))


def rows(scan, names):
    return pd.DataFrame([{
        "symbol": h["symbol"], "status": TIERS[tier(h)][0],
        "price": h.get("close"), "day %": h.get("pct_change"), "rvol": h.get("rvol"),
        "ceiling": h.get("base_or_shelf_high"),
        "day": f"{int(h.get('shelf_days') or 0)}/{MAX_SHELF_DAY}",
        "turnover": fmt_turnover(h.get("turnover_pkr")),
        "setup_grade": h.get("setup_grade") or "", "price_tier": h.get("price_tier") or "",
        "badges": badges(h), "company": names.get(h["symbol"], ""),
    } for h in sort_hits(scan.get("hits") or [])])


def column_config():
    return {
        "symbol": st.column_config.TextColumn("Symbol", pinned=True),
        "status": st.column_config.TextColumn("Stage / Action Status", help="Where the stock stands now"),
        "price": st.column_config.NumberColumn("Price", format="Rs %.2f"),
        "day %": st.column_config.NumberColumn("Day %", format="%.2f%%"),
        "rvol": st.column_config.NumberColumn("RVOL", format="%.2fx",
                                              help="Today's volume ÷ average of the previous 20 sessions"),
        "ceiling": st.column_config.NumberColumn("Shelf Ceiling", format="Rs %.2f",
                                                 help="Highest price of the shelf (for a fresh ignition: the "
                                                      "ignition's 20-day base high)"),
        "day": st.column_config.TextColumn("Day", help="Trading days since the ignition, out of the 12-day window"),
        "turnover": st.column_config.TextColumn("Turnover", help="Close × volume, in PKR"),
        "setup_grade": st.column_config.TextColumn(
            "Setup Grade", help="A+ PRIME: price ≤ Rs 100, not exhausted before the ignition, and a COIL or a 1W "
                                "leader. STANDARD: 1W leader and price ≤ Rs 100. WATCH_ONLY: otherwise. Display only."),
        "price_tier": st.column_config.TextColumn(
            "Price Tier", help="SWEET_SPOT ≤ Rs 25 · MID_CAP ≤ Rs 100 · HEAVY_CAP_CAUTION above Rs 100"),
        "badges": st.column_config.TextColumn(
            "Pre-ignition", help="COIL = ATR contraction and volume dry-up before the ignition · 1W = weekly leader · "
                                 "EXH = exhausted before the ignition (MFI14 > 80, or a >12% run in the 10 days before)"),
        "company": "Company",
    }


def _open_research(sym):
    st.session_state.research_symbol = sym
    st.toast(f"Opened {sym} in Stock Research →", icon="🎯")


def checklist(scan, names):
    """One expander per stock, in the same order as the table."""
    hits = sort_hits(scan.get("hits") or [])
    sd = scan.get("date")
    st.markdown("#### 📋 Stock-by-Stock Entry Checklist & Watch Dates")
    for k, h in enumerate(hits):
        sym, t, d = h["symbol"], h.get("signal_type"), int(h.get("shelf_days") or 0)
        dates, verdict = watch(h, sd)
        hi = h.get("base_or_shelf_high")
        auto = k == 0 or t == "SHELF_BREAKOUT" or (t == "ACTIVE_SHELF" and d >= 10)
        with st.expander(f"{TIERS[tier(h)][0].split(' ', 1)[0]} {sym} — {TIERS[tier(h)][1]}", expanded=auto):
            co = names.get(sym)
            if co:
                st.caption(co)
            st.markdown(f"**{verdict}**")
            st.markdown(f"**📅 Dates to watch:** {dates}")
            if t == "SOS_IGNITION":
                ceiling = ("Close above the shelf ceiling — the highest price of the shelf, set once the shelf forms"
                           + (f" (the ignition's 20-day base high was Rs. {hi:.2f})" if hi is not None else ""))
            else:
                ceiling = f"Close > **Rs. {hi:.2f}** (breaks the shelf ceiling)" if hi is not None else \
                    "Close above the shelf ceiling"
            head = ("**✅ Entry conditions (all met on the latest close):**" if t == "SHELF_BREAKOUT"
                    else "**🎯 Entry conditions (all three on the same daily close):**")
            st.markdown(f"{head}\n"
                        f"- {ceiling}\n"
                        f"- Volume ≥ **2.5×** the 20-day average (**RVOL ≥ 2.50×**; today {float(h.get('rvol') or 0):.2f}×)\n"
                        f"- Strong close in the **top 30%** of the day's range (or a PSX upper lock)")
            inv = invalidation(h, sd)
            if inv:
                st.markdown("**⛔ Invalidation / cancel levels:**\n" + "\n".join(f"- {x}" for x in inv))
            else:
                st.markdown(f"**⛔ Invalidation / cancel rule:** {INVALIDATION}")
            st.caption(f"Price Rs. {float(h.get('close') or 0):.2f} · day {float(h.get('pct_change') or 0):+.2f}% · "
                       f"turnover {fmt_turnover(h.get('turnover_pkr'))} · ignition {h.get('ignition_date') or '—'}")
            st.button(f"🎯 Open {sym} in Stock Research", key=f"phase_d_open_{sym}", on_click=_open_research,
                      args=(sym,))


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
               "close since stays above the ignition floor low + 25% × (close − low) of the ignition bar and "
               "above the 20-day EMA; no pullback deeper than 25% from the shelf's running peak (the largest "
               "(running high − low) / running high across the shelf bars, so stepping higher inside the shelf "
               "is not penalised); and volume confirms — either at least one up day with average up-day volume "
               "≥ 1.5× average down-day volume (or no down days), or, for a pure throwback with no up day yet, "
               "average shelf volume ≤ 40% of the ignition bar's volume.")
    st.caption("**SHELF BREAKOUT** — yesterday's signal was Active Shelf, and today closes above that shelf's "
               "high on volume ≥ 2.5× the 20-session average with a strong close. It fires once, on the initial "
               "break: the day after a Shelf Breakout cannot fire another one.")
    st.caption("One signal per stock per day, in priority Shelf Breakout > SOS Ignition > Active Shelf. Same "
               "universe and exclusion list as Wyckoff; stocks with fewer than 30 bars, or whose newest "
               "candle is not the session date (stale), are skipped. Last 90 daily bars from the shared "
               "daily_ohlc data. Runs once per weekday with the pattern refresh "
               "(fire_engine/run_phase_d_tracker.py). Standalone — independent of the Wyckoff 1.0 engine "
               "and its scores.")


def caption(scan):
    return (f"Last completed scan: {scan.get('date') or '—'} · {len(scan.get('hits') or [])} stock(s), closest to "
            "an entry first: breakouts today, shelves in their final days (9–12), shelves still building (3–8), "
            "then fresh ignitions.")


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
            names = company_names() or {}
            df = rows(scan, names)
            render_table(df, None, "phase_d_scan_table", column_config())
            checklist(scan, names)
    with st.expander(f"📖 View Rules & Metrics for {TITLE}"):
        rules()
