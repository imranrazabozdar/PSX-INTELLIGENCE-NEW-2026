#!/usr/bin/env python3
"""run_obv_mfi_backtest.py — walk-forward backtest of obv_mfi_scanner.py's
"OBV+MFI Setup with ATR Contraction" over every symbol in daily_ohlc.

Turso cost: daily_ohlc is read from the local snapshot when
PSX_DAILY_OHLC_SNAPSHOT is set (the workflow builds it once, ~160K reads);
the backtest itself then reads 0 Turso rows and writes 1 analysis_cache row.

Method (no lookahead -- indicators are causal, and every bar t is judged with
exactly the rule the daily scanner applies on bar t):
  * One trade per (symbol, Day 0): the first day the setup completes.
  * Entry at the NEXT session's open.
  * Fixed-horizon returns at 5/10/20/40 sessions (close vs entry).
  * Trade rule: +15% target / -8% stop on closes, 40-session max hold.
  * Baseline: the same forward returns from every eligible bar in the same
    universe, so "edge" = signal minus what a random day would have done.
"""
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
import turso_db
import obv_mfi_scanner as om

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

YEARS = 5
HORIZONS = (5, 10, 20, 40)
TARGET, STOP, MAX_HOLD = 0.15, -0.08, 40
REPORT_PATH = Path(__file__).parent.parent / "obv_mfi_backtest_report.md"


def load_universe():
    conn = turso_db.get_connection()
    syms = [r["symbol"] for r in conn.execute("SELECT DISTINCT symbol FROM daily_ohlc").fetchall()]
    out = {}
    for s in syms:
        rows = conn.execute("SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
                            "WHERE symbol=? ORDER BY trade_date", (s,)).fetchall()
        df = pd.DataFrame([dict(r) for r in rows])
        if len(df) >= om.MIN_BARS_REQUIRED + 1:
            out[s] = om.add_indicators(om._normalise(df))
    return out


def signals_for(d: pd.DataFrame):
    """Yield (t, i0) for every bar t the scanner would flag, same rules and
    same newest-first Day 0 choice as om.scan_obv_mfi_setup."""
    C, V, O, M, A, S = (d[c].to_numpy(float) for c in ("Close", "Volume", "OBV", "MFI", "ATR", "SMA20"))
    day0 = ((d["Close"] > d["PrevHighClose20"]) & (d["Volume"] > 3 * d["PrevVolSMA20"])
            & (d["OBV"] > d["PrevOBVHigh20"]) & (d["MFI"] > 80)).to_numpy()
    cv = np.concatenate([[0.0], np.cumsum(V)])
    d0_idx = np.flatnonzero(day0)
    for t in range(om.MIN_BARS_REQUIRED - 1, len(d)):
        cands = d0_idx[(d0_idx <= t - om.LOOKBACK_MIN) & (d0_idx >= t - om.LOOKBACK_MAX)][::-1]
        for i0 in cands:
            drop = (C[i0] - C[t]) / C[i0]
            avg_after = (cv[t + 1] - cv[i0 + 1]) / (t - i0)
            if (0.04 <= drop <= 0.30 and C[t] > S[t] and avg_after < 0.40 * V[i0]
                    and M[t] < 55 and O[t] >= O[i0] - 0.10 * abs(O[i0]) and A[t] < A[i0]):
                yield t, i0
                break


def fwd(d, t):
    O, C = d["Open"].to_numpy(float), d["Close"].to_numpy(float)
    if t + 1 >= len(d):
        return None
    e = O[t + 1]
    res = {f"r{h}": (C[t + h] / e - 1) * 100 if t + h < len(d) else None for h in HORIZONS}
    outcome, ret, held = "open", None, None
    for j in range(1, MAX_HOLD + 1):
        if t + j >= len(d):
            break
        r = C[t + j] / e - 1
        if r >= TARGET:
            outcome, ret, held = "win", TARGET * 100, j; break
        if r <= STOP:
            outcome, ret, held = "loss", STOP * 100, j; break
    else:
        outcome, ret, held = "timeout", (C[t + MAX_HOLD] / e - 1) * 100, MAX_HOLD
    res.update(outcome=outcome, trade_ret=ret, held=held)
    return res


def summarise(vals):
    v = np.array([x for x in vals if x is not None], float)
    if not len(v):
        return None
    return {"n": int(len(v)), "mean": round(float(v.mean()), 2), "median": round(float(np.median(v)), 2),
            "pct_positive": round(float((v > 0).mean() * 100), 1)}


def main():
    st = turso_db.status()
    if st.get("on_local_fallback"):
        log.error("On local fallback -- no data. Aborting.")
        return 1
    uni = load_universe()
    end = max(d["Date"].iloc[-1] for d in uni.values())
    start = end - pd.DateOffset(years=YEARS)
    first = min(d["Date"].iloc[0] for d in uni.values())
    log.info(f"Universe {len(uni)} symbols, data {first.date()} -> {end.date()}, window from {start.date()}")

    trades, base = [], {h: [] for h in HORIZONS}
    for sym, d in uni.items():
        seen = set()
        for t, i0 in signals_for(d):
            if d["Date"].iloc[t] < start or i0 in seen:
                continue
            seen.add(i0)
            f = fwd(d, t)
            if f:
                trades.append({"symbol": sym, "date": d["Date"].iloc[t].strftime("%Y-%m-%d"),
                               "day0": d["Date"].iloc[i0].strftime("%Y-%m-%d"), **f})
        C, O = d["Close"].to_numpy(float), d["Open"].to_numpy(float)
        dates = d["Date"].to_numpy()
        for t in range(om.MIN_BARS_REQUIRED - 1, len(d) - 1):
            if dates[t] < np.datetime64(start):
                continue
            for h in HORIZONS:
                if t + h < len(d):
                    base[h].append((C[t + h] / O[t + 1] - 1) * 100)

    res = {"status": "ok", "run_at": datetime.now(timezone.utc).isoformat(),
           "universe": len(uni), "data_from": str(first.date()), "data_to": str(end.date()),
           "window_from": str(max(start, first).date()), "signals": len(trades),
           "rule": f"+{TARGET*100:.0f}% target / {STOP*100:.0f}% stop on closes, {MAX_HOLD}-session max",
           "horizons": {}, "baseline": {}}
    for h in HORIZONS:
        res["horizons"][h] = summarise([t[f"r{h}"] for t in trades])
        res["baseline"][h] = summarise(base[h])
    done = [t for t in trades if t["outcome"] != "open"]
    w = [t for t in done if t["outcome"] == "win"]; l = [t for t in done if t["outcome"] == "loss"]
    to = [t for t in done if t["outcome"] == "timeout"]
    gw = sum(t["trade_ret"] for t in done if t["trade_ret"] > 0)
    gl = -sum(t["trade_ret"] for t in done if t["trade_ret"] < 0)
    res["trade_rule"] = {"closed": len(done), "wins": len(w), "losses": len(l), "timeouts": len(to),
                         "still_open": len(trades) - len(done),
                         "win_rate_pct": round(len(w) / len(done) * 100, 1) if done else None,
                         "avg_ret_pct": round(float(np.mean([t["trade_ret"] for t in done])), 2) if done else None,
                         "profit_factor": round(gw / gl, 2) if gl else None,
                         "avg_hold": round(float(np.mean([t["held"] for t in done])), 1) if done else None}
    by_year = {}
    for t in trades:
        by_year.setdefault(t["date"][:4], []).append(t["r20"])
    res["by_year_r20"] = {y: summarise(v) for y, v in sorted(by_year.items())}
    res["trades"] = sorted(trades, key=lambda x: x["date"])

    L = [f"# OBV+MFI Setup with ATR Contraction — {YEARS}-year PSX backtest", "",
         f"Run {res['run_at'][:16]} UTC · {len(uni)} symbols · data {res['data_from']} → {res['data_to']} · "
         f"signals counted from {res['window_from']}", "",
         f"**Signals:** {len(trades)} (one per symbol per Day 0; entry next open)", "",
         "## Forward returns vs baseline (all days, same stocks)", "",
         "| Horizon | Signals n | Mean % | Median % | % positive | Baseline mean % | Baseline % positive | Edge (mean) |",
         "|---|---|---|---|---|---|---|---|"]
    for h in HORIZONS:
        s, b = res["horizons"][h], res["baseline"][h]
        if s and b:
            L.append(f"| {h}d | {s['n']} | {s['mean']:+.2f} | {s['median']:+.2f} | {s['pct_positive']} | "
                     f"{b['mean']:+.2f} | {b['pct_positive']} | {s['mean']-b['mean']:+.2f} |")
    tr = res["trade_rule"]
    L += ["", f"## Trade rule ({res['rule']})", "",
          f"Closed {tr['closed']} · wins {tr['wins']} · losses {tr['losses']} · timeouts {tr['timeouts']} · "
          f"still open {tr['still_open']}", "",
          f"Win rate **{tr['win_rate_pct']}%** · avg return **{tr['avg_ret_pct']}%** · "
          f"profit factor **{tr['profit_factor']}** · avg hold {tr['avg_hold']} sessions", "",
          "## 20-day return by signal year", "", "| Year | n | Mean % | % positive |", "|---|---|---|---|"]
    for y, s in res["by_year_r20"].items():
        if s:
            L.append(f"| {y} | {s['n']} | {s['mean']:+.2f} | {s['pct_positive']} |")
    L += ["", "## All signals", "", "| Signal date | Symbol | Day 0 | 5d % | 20d % | 40d % | Trade |",
          "|---|---|---|---|---|---|---|"]
    fm = lambda x: "—" if x is None else f"{x:+.1f}"
    for t in res["trades"]:
        L.append(f"| {t['date']} | {t['symbol']} | {t['day0']} | {fm(t['r5'])} | {fm(t['r20'])} | "
                 f"{fm(t['r40'])} | {t['outcome']} |")
    report = "\n".join(L)
    REPORT_PATH.write_text(report)
    print(report)

    try:
        conn = turso_db.get_connection()
        conn.execute("""INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
            VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET run_at=excluded.run_at,
            run_at_epoch=excluded.run_at_epoch, result_json=excluded.result_json""",
                     ("obv_mfi_backtest", res["run_at"], time.time(), json.dumps(res, default=str)))
        conn.commit()
    except Exception as e:
        log.warning(f"analysis_cache save failed: {e}")
    turso_db.print_usage_report(label="run_obv_mfi_backtest.py") if hasattr(turso_db, "print_usage_report") else None
    return 0


if __name__ == "__main__":
    sys.exit(main())
