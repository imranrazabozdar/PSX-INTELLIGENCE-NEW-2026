#!/usr/bin/env python3
"""compare_obv_mfi_variants.py — research comparison, changes nothing in production.

Runs three versions of the OBV+MFI setup over IDENTICAL data (the local
daily_ohlc snapshot, same configured universe minus exclusions):

  P-live   production rule exactly as deployed: OBV level measured inside the
           260-bar window the daily job loads (window re-anchored every day)
  P-full   production rule with OBV accumulated over full history (what the
           earlier 5-year backtest measured)
  E-slope  experimental offset-invariant rule (obv_mfi_scanner_experimental)

Same evaluation for each: one trade per (symbol, Day 0), entry next open,
5/10/20/40-session returns, +15%/-8% close-based rule (as in
run_obv_mfi_backtest.py), 95% CIs clustered by signal date.
Writes a markdown report; 0 Turso writes.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

import obv_mfi_scanner as om
import obv_mfi_scanner_experimental as ox
import run_obv_mfi_backtest as omb
import turso_db
import volatility_engine as ve

LIVE_WINDOW = 260
REPORT = Path(__file__).parent.parent / "obv_mfi_variant_comparison.md"


def signals(d, variant):
    C, V, O, M, A, S = (d[c].to_numpy(float) for c in ("Close", "Volume", "OBV", "MFI", "ATR", "SMA20"))
    day0 = ((d["Close"] > d["PrevHighClose20"]) & (d["Volume"] > 3 * d["PrevVolSMA20"])
            & (d["OBV"] > d["PrevOBVHigh20"]) & (d["MFI"] > 80)).to_numpy()
    cv = np.concatenate([[0.0], np.cumsum(V)])
    idx = np.flatnonzero(day0)
    out = []
    for t in range(om.MIN_BARS_REQUIRED - 1, len(d)):
        base = O[max(0, t - LIVE_WINDOW + 1)]          # live window starts at OBV = 0
        for i0 in idx[(idx <= t - om.LOOKBACK_MIN) & (idx >= t - om.LOOKBACK_MAX)][::-1]:
            if variant == "P-live" and i0 < t - LIVE_WINDOW + 1:
                continue
            drop = (C[i0] - C[t]) / C[i0]
            if not (0.04 <= drop <= 0.30 and C[t] > S[t] and (cv[t + 1] - cv[i0 + 1]) / (t - i0) < 0.40 * V[i0]
                    and M[t] < 55 and A[t] < A[i0]):
                continue
            if variant == "P-full":
                keep = O[t] >= O[i0] - 0.10 * abs(O[i0])
            elif variant == "P-live":
                ot, oz = O[t] - base, O[i0] - base
                keep = ot >= oz - 0.10 * abs(oz)
            else:
                keep = O[t] - O[i0] >= -ox.OBV_GIVEBACK_FRAC * V[max(0, i0 - 19):i0 + 1].sum()
            if keep:
                out.append((t, i0))
                break
    return out


def cl_ci(flags, dates, z=1.96):
    n = len(flags)
    if not n:
        return (None, None)
    p = sum(flags) / n
    by = {}
    for f, d in zip(flags, dates):
        by.setdefault(d, [0, 0])
        by[d][0] += f
        by[d][1] += 1
    g = len(by)
    if g < 2:
        return ve.wilson(sum(flags), n)
    h = z * math.sqrt(sum((k - p * m) ** 2 for k, m in by.values()) / n ** 2 * g / (g - 1))
    return (round(max(0, p - h) * 100, 1), round(min(1, p + h) * 100, 1))


def main():
    conn = turso_db.get_connection()
    uni, exc = ve.configured_universe()
    res = {v: [] for v in ("P-live", "P-full", "E-slope")}
    for s in [u for u in uni if u not in set(exc)]:
        rows = conn.execute("SELECT trade_date, open, high, low, close, volume FROM daily_ohlc WHERE symbol=? "
                            "ORDER BY trade_date", (s,)).fetchall()
        if len(rows) < om.MIN_BARS_REQUIRED + 1:
            continue
        d = om.add_indicators(om._normalise(pd.DataFrame([dict(r) for r in rows])))
        for v in res:
            seen = set()
            for t, i0 in signals(d, v):
                if i0 in seen:
                    continue
                seen.add(i0)
                f = omb.fwd(d, t)
                if f:
                    res[v].append({"symbol": s, "date": d["Date"].iloc[t].strftime("%Y-%m-%d"),
                                   "day0": d["Date"].iloc[i0].strftime("%Y-%m-%d"), **f})
    keys = {v: {(e["symbol"], e["day0"]) for e in ev} for v, ev in res.items()}
    L = ["# OBV+MFI setup — production vs experimental OBV rule (identical data)", "",
         "| Variant | Signals | Mean 10d % | Mean 20d % | Mean 40d % | P(up 20d) % [95% CI, date-clustered] | Trade win % | Trade avg % | Trade PF |",
         "|---|---|---|---|---|---|---|---|---|"]
    for v, ev in res.items():
        def m(h):
            x = [e[f"r{h}"] for e in ev if e.get(f"r{h}") is not None]
            return round(float(np.mean(x)), 2) if x else None
        r20 = [(e["r20"], e["date"]) for e in ev if e.get("r20") is not None]
        fl = [int(x > 0) for x, _ in r20]
        ci = cl_ci(fl, [d for _, d in r20])
        done = [e for e in ev if e["outcome"] != "open"]
        gw = sum(e["trade_ret"] for e in done if e["trade_ret"] > 0)
        gl = -sum(e["trade_ret"] for e in done if e["trade_ret"] < 0)
        L.append(f"| {v} | {len(ev)} | {m(10)} | {m(20)} | {m(40)} | "
                 f"{round(100 * np.mean(fl), 1) if fl else None} [{ci[0]}–{ci[1]}] | "
                 f"{round(100 * sum(e['outcome'] == 'win' for e in done) / len(done), 1) if done else None} | "
                 f"{round(float(np.mean([e['trade_ret'] for e in done])), 2) if done else None} | "
                 f"{round(gw / gl, 2) if gl else None} |")
    L += ["", "## Overlap (by symbol + Day 0)", "",
          f"- P-live ∩ P-full: {len(keys['P-live'] & keys['P-full'])} · only P-live: {len(keys['P-live'] - keys['P-full'])} "
          f"· only P-full: {len(keys['P-full'] - keys['P-live'])}",
          f"- P-live ∩ E-slope: {len(keys['P-live'] & keys['E-slope'])} · only P-live: {len(keys['P-live'] - keys['E-slope'])} "
          f"· only E-slope: {len(keys['E-slope'] - keys['P-live'])}", "",
          "Signals that P-live and P-full disagree on are the window-dependence the audit found: identical data, "
          "different answer depending only on where OBV's running sum starts.", "",
          "_Research only. The production scanner (obv_mfi_scanner.py) is unchanged._"]
    REPORT.write_text("\n".join(L))
    print("\n".join(L))
    if hasattr(turso_db, "print_usage_report"):
        turso_db.print_usage_report(label="compare_obv_mfi_variants.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
