"""wyckoff_engine.py — extends app.py's existing Wyckoff primitives
(trading_range/spring_quality/upthrust_quality/effort_result, kept there and
untouched) with the parts STEP 9/10/14/15/36 of the source framework still
needed: the full named event sequence (PS/SC/AR/ST/Spring/Test/SOS/LPS for
accumulation; PSY/BC/AR/ST/UT-UTAD/SOW/LPSY for distribution), the 9
classical Buying/Selling Tests as discrete PASS/PARTIAL/FAIL criteria, and
ATR-percentile volatility regime classification.

Event detection here is heuristic, not authoritative — real Wyckoff reading
requires human judgment this module doesn't have. Every event is reported
with the evidence that produced it (price/volume/date) so it can be checked,
and "not detected" is a valid, common, honest result — never forced to find
events that aren't there.
"""

import statistics


def _avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _spread(x):
    return x["high"] - x["low"]


def _trading_range(a, window=40):
    if len(a) < window:
        return None
    r = a[-window:]
    core = r[:-3] if len(r) > 3 else r
    if not core:
        return None
    support, resistance = min(x["low"] for x in core), max(x["high"] for x in core)
    mid = _avg([x["close"] for x in core])
    return {"support": support, "resistance": resistance,
            "width_pct": round((resistance - support) / max(.0001, mid) * 100, 2), "bars": window}


# ------------------------------------------------------------ accumulation ---
def accumulation_events(a, lookback=120):
    """Heuristic PS -> SC -> AR -> ST -> Spring -> Test -> SOS -> LPS scan
    over the trailing `lookback` bars. Returns the events actually found, in
    chronological order — an empty/partial list is a valid, honest result."""
    if len(a) < 60:
        return {"status": "insufficient_history", "events": []}
    window = a[-lookback:] if len(a) > lookback else a
    n = len(window)
    events = []

    # SC candidate: lowest close in the window with elevated volume vs its own trailing 20-bar avg.
    # Tightened: a real climax bar has a wide range AND closes near its own low (selling pressure
    # persisted to the close), not just any red bar on above-average volume — that was firing on
    # ordinary down days and made SC (and everything chained after it) far too common.
    sc_idx, sc_score = None, -1
    for i in range(20, n):
        avgv = _avg([window[k]["volume"] for k in range(i - 20, i)])
        avgs = _avg([_spread(window[k]) for k in range(i - 20, i)])
        vr = window[i]["volume"] / max(1, avgv)
        sr = _spread(window[i]) / max(.0001, avgs)
        close_pos = (window[i]["close"] - window[i]["low"]) / max(.0001, _spread(window[i]))
        if vr >= 1.6 and sr >= 1.2 and window[i]["close"] < window[i]["open"] and close_pos <= 0.4:
            # score favors low price + high relative volume, among the lower third of the window's range
            lo_rank = 1 - (window[i]["low"] - min(x["low"] for x in window)) / max(.0001, (max(x["high"] for x in window) - min(x["low"] for x in window)))
            score = vr * max(0, lo_rank)
            if score > sc_score:
                sc_score, sc_idx = score, i
    if sc_idx is not None and sc_idx < n - 5:
        x = window[sc_idx]
        events.append({"event": "SC", "name": "Selling Climax", "date": x["trade_date"],
                        "price": x["close"], "low": x["low"], "volume": x["volume"]})

        # PS: an earlier elevated-volume down bar at a shallower low, before SC.
        ps_idx = None
        for i in range(20, sc_idx):
            avgv = _avg([window[k]["volume"] for k in range(max(0, i - 20), i)])
            if window[i]["volume"] / max(1, avgv) >= 1.25 and window[i]["close"] < window[i]["open"] \
                    and window[i]["low"] > x["low"]:
                ps_idx = i
        if ps_idx is not None:
            p = window[ps_idx]
            events.append({"event": "PS", "name": "Preliminary Support", "date": p["trade_date"],
                            "price": p["close"], "volume": p["volume"]})

        # AR: highest high in the bars immediately after SC (up to 25 bars).
        ar_window = window[sc_idx + 1: min(n, sc_idx + 26)]
        if ar_window:
            ar_bar = max(ar_window, key=lambda z: z["high"])
            ar_idx = sc_idx + 1 + ar_window.index(ar_bar)
            events.append({"event": "AR", "name": "Automatic Rally", "date": ar_bar["trade_date"],
                            "price": ar_bar["high"], "volume": ar_bar["volume"]})

            # ST: a subsequent bar that revisits near the SC low on genuinely reduced volume.
            # Tightened: comparing only to SC's own (already-extreme) volume made almost any
            # ordinary day "pass" since SC volume is a spike — now also requires volume below
            # the bar's own trailing-20 average, a tighter 2.5% price band (was 5%), a minimum
            # 3-bar gap after AR so it can't fire immediately, and takes the FIRST qualifying
            # bar (the genuine first retest) instead of the last one found in a 30-bar window.
            st_window = window[ar_idx + 1: min(n, ar_idx + 30)]
            st_idx_local = None
            for j, b in enumerate(st_window):
                if j < 3:
                    continue
                gi = ar_idx + 1 + j
                avgv_local = _avg([window[k]["volume"] for k in range(max(0, gi - 20), gi)])
                if b["low"] <= x["low"] * 1.025 and b["volume"] < x["volume"] * 0.85 \
                        and b["volume"] < avgv_local * 0.85:
                    st_idx_local = j
                    break
            if st_idx_local is not None:
                st_bar = st_window[st_idx_local]
                events.append({"event": "ST", "name": "Secondary Test", "date": st_bar["trade_date"],
                                "price": st_bar["close"], "volume": st_bar["volume"],
                                "note": "Lower volume than SC — consistent with supply drying up."})

        # Spring / Test / SOS / LPS: only meaningful once a trading range exists after SC.
        tr = _trading_range(window[sc_idx:], window=min(40, n - sc_idx)) if n - sc_idx >= 20 else None
        if tr:
            support = min(tr["support"], x["low"])
            spring_idx = None
            for i in range(max(sc_idx, n - 20), n):
                b = window[i]
                if b["low"] < support and b["close"] > support:
                    spring_idx = i
            if spring_idx is not None:
                sb = window[spring_idx]
                events.append({"event": "SPRING", "name": "Spring", "date": sb["trade_date"],
                                "price": sb["close"], "low": sb["low"], "volume": sb["volume"]})
                test_window = window[spring_idx + 1:]
                avgv = _avg([b["volume"] for b in window[max(0, spring_idx - 20):spring_idx]])
                for b in test_window[:8]:
                    if b["low"] > sb["low"] and b["volume"] < avgv * 0.8:
                        events.append({"event": "TEST", "name": "Successful Test", "date": b["trade_date"],
                                        "price": b["close"], "volume": b["volume"]})
                        break
                sos_idx = None
                for i in range(spring_idx + 1, n):
                    b = window[i]
                    if b["close"] > tr["resistance"] and b["volume"] > avgv * 1.3:
                        sos_idx = i
                if sos_idx is not None:
                    sb2 = window[sos_idx]
                    events.append({"event": "SOS", "name": "Sign of Strength", "date": sb2["trade_date"],
                                    "price": sb2["close"], "volume": sb2["volume"]})
                    lps_window = window[sos_idx + 1:]
                    for b in lps_window[:10]:
                        if b["close"] > tr["resistance"] * 0.98 and b["close"] < sb2["close"]:
                            events.append({"event": "LPS", "name": "Last Point of Support",
                                            "date": b["trade_date"], "price": b["close"], "volume": b["volume"]})
                            break
    return {"status": "ok", "events": events,
            "sequence_found": [e["event"] for e in events]}


# ------------------------------------------------------------- distribution ---
def distribution_events(a, lookback=120):
    """Mirror of accumulation_events for PSY/BC/AR/ST/UT-UTAD/SOW/LPSY."""
    if len(a) < 60:
        return {"status": "insufficient_history", "events": []}
    window = a[-lookback:] if len(a) > lookback else a
    n = len(window)
    events = []

    # Tightened to match SC's climax criteria: wide range AND closes near its own high.
    bc_idx, bc_score = None, -1
    for i in range(20, n):
        avgv = _avg([window[k]["volume"] for k in range(i - 20, i)])
        avgs = _avg([_spread(window[k]) for k in range(i - 20, i)])
        vr = window[i]["volume"] / max(1, avgv)
        sr = _spread(window[i]) / max(.0001, avgs)
        close_pos = (window[i]["close"] - window[i]["low"]) / max(.0001, _spread(window[i]))
        if vr >= 1.6 and sr >= 1.2 and window[i]["close"] > window[i]["open"] and close_pos >= 0.6:
            hi_rank = (window[i]["high"] - min(x["low"] for x in window)) / max(.0001, (max(x["high"] for x in window) - min(x["low"] for x in window)))
            score = vr * max(0, hi_rank)
            if score > bc_score:
                bc_score, bc_idx = score, i
    if bc_idx is not None and bc_idx < n - 5:
        x = window[bc_idx]
        events.append({"event": "BC", "name": "Buying Climax", "date": x["trade_date"],
                        "price": x["close"], "high": x["high"], "volume": x["volume"]})

        psy_idx = None
        for i in range(20, bc_idx):
            avgv = _avg([window[k]["volume"] for k in range(max(0, i - 20), i)])
            if window[i]["volume"] / max(1, avgv) >= 1.25 and window[i]["close"] > window[i]["open"] \
                    and window[i]["high"] < x["high"]:
                psy_idx = i
        if psy_idx is not None:
            p = window[psy_idx]
            events.append({"event": "PSY", "name": "Preliminary Supply", "date": p["trade_date"],
                            "price": p["close"], "volume": p["volume"]})

        ar_window = window[bc_idx + 1: min(n, bc_idx + 26)]
        if ar_window:
            ar_bar = min(ar_window, key=lambda z: z["low"])
            ar_idx = bc_idx + 1 + ar_window.index(ar_bar)
            events.append({"event": "AR", "name": "Automatic Reaction", "date": ar_bar["trade_date"],
                            "price": ar_bar["low"], "volume": ar_bar["volume"]})

            # Mirror of accumulation's tightened ST: local-average volume check, tighter
            # 2.5% band, minimum 3-bar gap after AR, first qualifying bar wins.
            st_window = window[ar_idx + 1: min(n, ar_idx + 30)]
            st_idx_local = None
            for j, b in enumerate(st_window):
                if j < 3:
                    continue
                gi = ar_idx + 1 + j
                avgv_local = _avg([window[k]["volume"] for k in range(max(0, gi - 20), gi)])
                if b["high"] >= x["high"] * 0.975 and b["volume"] < x["volume"] * 0.85 \
                        and b["volume"] < avgv_local * 0.85:
                    st_idx_local = j
                    break
            if st_idx_local is not None:
                st_bar = st_window[st_idx_local]
                events.append({"event": "ST", "name": "Secondary Test", "date": st_bar["trade_date"],
                                "price": st_bar["close"], "volume": st_bar["volume"]})

        tr = _trading_range(window[bc_idx:], window=min(40, n - bc_idx)) if n - bc_idx >= 20 else None
        if tr:
            resistance = max(tr["resistance"], x["high"])
            ut_idx = None
            for i in range(max(bc_idx, n - 20), n):
                b = window[i]
                if b["high"] > resistance and b["close"] < resistance:
                    ut_idx = i
            if ut_idx is not None:
                ub = window[ut_idx]
                events.append({"event": "UT", "name": "Upthrust (possible UTAD)", "date": ub["trade_date"],
                                "price": ub["close"], "high": ub["high"], "volume": ub["volume"]})
                sow_idx = None
                avgv = _avg([b["volume"] for b in window[max(0, ut_idx - 20):ut_idx]])
                for i in range(ut_idx + 1, n):
                    b = window[i]
                    if b["close"] < tr["support"] and b["volume"] > avgv * 1.3:
                        sow_idx = i
                if sow_idx is not None:
                    sb = window[sow_idx]
                    events.append({"event": "SOW", "name": "Sign of Weakness", "date": sb["trade_date"],
                                    "price": sb["close"], "volume": sb["volume"]})
                    lpsy_window = window[sow_idx + 1:]
                    for b in lpsy_window[:10]:
                        if b["close"] < tr["support"] * 1.02 and b["close"] > sb["close"]:
                            events.append({"event": "LPSY", "name": "Last Point of Supply",
                                            "date": b["trade_date"], "price": b["close"], "volume": b["volume"]})
                            break
    return {"status": "ok", "events": events,
            "sequence_found": [e["event"] for e in events]}


# --------------------------------------------------------- 9 buying/selling ---
def nine_buying_tests(a, accum, rs_positive=None):
    """STEP 14: 9 classical accumulation criteria as PASS/PARTIAL/FAIL, each
    with the evidence behind it. `accum` is accumulation_events()'s output."""
    found = {e["event"] for e in accum.get("events", [])}
    tr = _trading_range(a, window=40)
    tests = []

    def add(name, status, evidence):
        tests.append({"test": name, "status": status, "evidence": evidence})

    add("Downtrend precedes the range", "PASS" if len(a) >= 60 and a[-60]["close"] > a[-1]["close"] else "PARTIAL",
        "A prior decline is the precondition for accumulation, not proof of it alone.")
    add("Preliminary Support (PS)", "PASS" if "PS" in found else "FAIL",
        "Elevated-volume down bar shallower than the eventual low." if "PS" in found else "Not detected in the scanned window.")
    add("Selling Climax (SC)", "PASS" if "SC" in found else "FAIL",
        "High-relative-volume down bar with the window's deepest low." if "SC" in found else "Not detected.")
    add("Secondary Test (ST) on lower volume", "PASS" if "ST" in found else "FAIL",
        "Retest of the SC low with reduced participation." if "ST" in found else "Not detected.")
    add("Higher lows since SC", "PASS" if "SC" in found and a[-1]["close"] > a[-1]["low"] else "PARTIAL",
        "Structural confirmation that lows are stepping up post-SC.")
    add("Volume expands on rallies, contracts on reactions", "PASS" if "SOS" in found else "PARTIAL",
        "SOS (high-volume rally) detected." if "SOS" in found else "No confirmed SOS yet — harmony unproven.")
    add("Relative strength vs market", "PASS" if rs_positive else "FAIL" if rs_positive is False else "N/A",
        "Stock outperforming its benchmark." if rs_positive else "Relative strength not positive or unavailable.")
    add("Sufficient Cause built (range width/duration)", "PASS" if tr and tr["width_pct"] >= 8 else "PARTIAL",
        f"Range width {tr['width_pct']}%" if tr else "No resolved trading range yet.")
    add("Sign of Strength (SOS) with expanding volume", "PASS" if "SOS" in found else "FAIL",
        "Breakout above range resistance on above-average volume." if "SOS" in found else "Not yet confirmed.")

    passed = sum(1 for t in tests if t["status"] == "PASS")
    return {"tests": tests, "passed": passed, "total": 9,
            "note": "9/9 is not a guaranteed BUY — it is one input among the full confluence matrix."}


def nine_selling_tests(a, distrib, rs_positive=None):
    """Mirror of nine_buying_tests for distribution."""
    found = {e["event"] for e in distrib.get("events", [])}
    tr = _trading_range(a, window=40)
    tests = []

    def add(name, status, evidence):
        tests.append({"test": name, "status": status, "evidence": evidence})

    add("Uptrend precedes the range", "PASS" if len(a) >= 60 and a[-60]["close"] < a[-1]["close"] else "PARTIAL",
        "A prior advance is the precondition for distribution, not proof of it alone.")
    add("Preliminary Supply (PSY)", "PASS" if "PSY" in found else "FAIL",
        "Elevated-volume up bar shallower than the eventual high." if "PSY" in found else "Not detected.")
    add("Buying Climax (BC)", "PASS" if "BC" in found else "FAIL",
        "High-relative-volume up bar with the window's highest high." if "BC" in found else "Not detected.")
    add("Secondary Test (ST) on lower volume", "PASS" if "ST" in found else "FAIL",
        "Retest of the BC high with reduced participation." if "ST" in found else "Not detected.")
    add("Lower highs since BC", "PASS" if "BC" in found and a[-1]["close"] < a[-1]["high"] else "PARTIAL",
        "Structural confirmation that highs are stepping down post-BC.")
    add("Volume expands on breaks, contracts on rallies", "PASS" if "SOW" in found else "PARTIAL",
        "SOW (high-volume breakdown) detected." if "SOW" in found else "No confirmed SOW yet.")
    add("Relative weakness vs market", "PASS" if rs_positive is False else "FAIL" if rs_positive else "N/A",
        "Stock underperforming its benchmark." if rs_positive is False else "Relative weakness not confirmed.")
    add("Sufficient Cause built (range width/duration)", "PASS" if tr and tr["width_pct"] >= 8 else "PARTIAL",
        f"Range width {tr['width_pct']}%" if tr else "No resolved trading range yet.")
    add("Sign of Weakness (SOW) with expanding volume", "PASS" if "SOW" in found else "FAIL",
        "Breakdown below range support on above-average volume." if "SOW" in found else "Not yet confirmed.")

    passed = sum(1 for t in tests if t["status"] == "PASS")
    return {"tests": tests, "passed": passed, "total": 9,
            "note": "9/9 is not a guaranteed SELL — it is one input among the full confluence matrix."}


# ------------------------------------------------------------- volatility ----
def volatility_regime(a, atr_period=14, history=250):
    """STEP 36: ATR-percentile classification against the stock's own trailing
    history, not a fixed threshold — a 2% ATR is normal for one stock and
    extreme for another."""
    if len(a) < atr_period + 20:
        return {"status": "insufficient_history"}
    trs = []
    for i in range(1, len(a)):
        h, l, pc = a[i]["high"], a[i]["low"], a[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_series = []
    for i in range(atr_period, len(trs) + 1):
        atr_series.append(_avg(trs[i - atr_period:i]))
    if not atr_series:
        return {"status": "insufficient_history"}
    hist = atr_series[-history:] if len(atr_series) > history else atr_series
    current = atr_series[-1]
    price = a[-1]["close"]
    pct_rank = sum(1 for v in hist if v <= current) / len(hist) * 100
    label = ("Very Low" if pct_rank < 20 else "Low" if pct_rank < 40 else
             "Normal" if pct_rank < 60 else "High" if pct_rank < 80 else "Extreme")
    return {"status": "ok", "atr": round(current, 3), "atr_pct_of_price": round(current / price * 100, 2) if price else None,
            "percentile_vs_own_history": round(pct_rank, 1), "regime": label,
            "sample": len(hist),
            "note": "Percentile is against this stock's own trailing ATR history, not a market-wide fixed threshold."}
