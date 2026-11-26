"""Breakouts-tab text for the daily PDF report, without streamlit.

Mirrors the pure helpers of phase_d_ui.py (tier, sort_hits, watch, invalidation, badges,
fmt_turnover, add_trading_days) so the PDF can print the same per-stock checklist the app
shows. phase_d_ui imports streamlit, which the report job does not install, so the wording is
kept here. tests/ compares the two when streamlit is available (pattern_scanner/tests).
"""
from datetime import date, timedelta

MAX_SHELF_DAY = 12
LABELS = {"SHELF_BREAKOUT": "SHELF BREAKOUT", "SOS_IGNITION": "SOS IGNITION", "ACTIVE_SHELF": "ACTIVE SHELF"}
TIERS = {
    1: ("🟢 Entry triggered today", "Entry Triggered Today"),
    2: ("🟠 Final breakout window", "Final Breakout Window (Days 9–12)"),
    3: ("🔵 Building shelf", "Building Shelf (Days 3–8)"),
    4: ("⚪ Fresh ignition — wait", "Fresh Ignition (Wait 3 Sessions for Shelf)"),
}
BADGE_LABELS = (("coil_dryup", "COIL"), ("w1_leader", "1W"), ("exhausted_pre_ign", "EXH"))


def tier(h):
    t, d = h.get("signal_type"), int(h.get("shelf_days") or 0)
    if t == "SHELF_BREAKOUT":
        return 1
    if t == "ACTIVE_SHELF":
        return 2 if d >= 9 else 3
    return 4


def sort_hits(hits):
    """Same order as phase_d_ui.sort_hits."""
    def key(h):
        k, rv, d = tier(h), float(h.get("rvol") or 0), int(h.get("shelf_days") or 0)
        return (k, 0 if k in (1, 4) else -d, -rv)
    return sorted(hits or [], key=key)


def counts(hits):
    hs = hits or []
    return {k: sum(1 for h in hs if h.get("signal_type") == k) for k in LABELS}


def add_trading_days(d, n):
    """`d` plus `n` Mon-Fri weekdays (exchange holidays are not known here), as phase_d_ui."""
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


def badges(h):
    return "·".join(lbl for key, lbl in BADGE_LABELS if h.get(key) in (1, True))


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
    first, last = add_trading_days(scan_date, 1), add_trading_days(scan_date, MAX_SHELF_DAY + 1 - d)
    verdict = (f"Final Breakout Window (Day {d} of 12) — Watch closely for breakout trigger" if d >= 9 else
               f"Building Shelf (Day {d} of 12) — Shelf still forming; watch for a breakout")
    return (f"Breakout can trigger on: {_fmt_range(first, last)} — the last chance is the session after "
            f"Day 12, and only while the shelf still holds.", verdict)


def invalidation(h, scan_date):
    """Next-session cancel levels from stored EMA20 / ignition floor; None when neither is stored.
    Lines keep the app's wording, without its markdown bold markers."""
    ema, flo = h.get("ema20"), h.get("ignition_floor")
    if ema is None and flo is None:
        return None
    ema = float(ema) if ema is not None else None
    flo = float(flo) if flo is not None else None
    lvl = max(v for v in (ema, flo) if v is not None)
    nxt = _fmt_day(add_trading_days(scan_date, 1))
    why = " and ".join(x for x in ((f"20-EMA Rs. {ema:.2f}" if ema is not None else ""),
                                   (f"ignition floor Rs. {flo:.2f}" if flo is not None else "")) if x)
    out = [f"Cancelled if it closes at or below Rs. {lvl:.2f} on {nxt} (the higher of {why})."]
    hi = h.get("base_or_shelf_high")
    if h.get("signal_type") == "ACTIVE_SHELF" and hi is not None:
        out.append(f"Also cancelled if any day's low trades below Rs. {0.75 * float(hi):.2f} "
                   f"(25% under the shelf peak Rs. {float(hi):.2f}).")
    out.append("The level is recalculated after every close — check the updated figure each evening. "
               "Weak up-day vs down-day volume can also end the shelf (no price equivalent).")
    return out
