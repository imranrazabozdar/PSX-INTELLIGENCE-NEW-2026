#!/usr/bin/env python3
"""run_wyckoff_diagnostic.py — read-only historical diagnostic of the EXISTING
Wyckoff accumulation engine (fire_engine/wyckoff_detector.py).

Separate from the Volatility Intelligence Engine on purpose: it imports
nothing from it, changes nothing in the Wyckoff engine, and its findings are
NOT used to modify any production threshold or weight.

What it measures, per the user's request:
  * signal frequency (WATCH / READY / EXTREME per symbol-year)
  * forward returns after signals (entry next open; 5/10/20 sessions) vs all days
  * upper-circuit capture rate: share of upper-circuit days that had a
    Wyckoff signal on that stock in the prior 1-20 sessions
  * missed opportunities: upper-circuit days with no prior signal, and which
    Wyckoff condition was missing the day before

Two evidence sources, reported separately:
  A. REPLAY -- the unchanged WyckoffDetector run over full daily history.
     Limitation: 4-hour bars exist only for the last ~35 days (ohlcv_4h is a
     rolling cache), so the replay cannot award the 20-point 4-hour BB
     compression component. Replayed scores are therefore a LOWER BOUND
     (max 80) and replayed signal counts understate production. Nothing is
     loosened to compensate.
  B. STORED -- the signals the production batch actually wrote to
     wyckoff_accumulation (full engine incl. 4-hour data), for whatever
     period exists.

Turso: daily_ohlc comes from the local snapshot when PSX_DAILY_OHLC_SNAPSHOT
is set (0 reads); one query reads the stored signal rows; one analysis_cache
row is written ('wyckoff_diagnostic').
"""
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import pandas as pd

from fire_engine.config import load_config
from fire_engine.wyckoff_detector import WyckoffDetector

HORIZONS = (5, 10, 20)
CAPTURE_WINDOW = 20
REPORT = ROOT / "wyckoff_diagnostic_report.md"
CORP_ACTION = 0.11          # >11% one-day move is beyond PSX's circuit -> likely an adjustment


def wilson(k, n, z=1.96):
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h) * 100, 1), round(min(1, c + h) * 100, 1))


def load_daily(conn, symbols):
    out = {}
    for s in symbols:
        rows = conn.execute("SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
                            "WHERE symbol=? ORDER BY trade_date", (s,)).fetchall()
        if len(rows) < 60:
            continue
        df = pd.DataFrame([dict(r) for r in rows])
        df["date"] = pd.to_datetime(df.pop("trade_date"))
        out[s] = df.set_index("date").astype(float)
    return out


def circuit_limit(frames):
    """Empirical PSX upper limit: the level where the daily-return
    distribution piles up (excluding adjustment-sized jumps)."""
    r = np.concatenate([(d["close"] / d["close"].shift() - 1).dropna().to_numpy() for d in frames.values()])
    r = r[(r > 0.05) & (r <= CORP_ACTION)]
    if not len(r):
        return 0.10
    hist, edges = np.histogram(r, bins=np.arange(0.05, CORP_ACTION + 0.0025, 0.0025))
    return float(round(edges[int(np.argmax(hist))], 4))


def forward(d, t):
    O, C = d["open"].to_numpy(), d["close"].to_numpy()
    n = len(d)
    if t + 1 >= n or O[t + 1] <= 0:
        return None
    end = min(n, t + 1 + max(HORIZONS))
    if (np.abs(C[t + 1:end] / C[t:end - 1] - 1) > CORP_ACTION).any():
        return None
    rec = {f"r{h}": (C[t + h] / O[t + 1] - 1) * 100 for h in HORIZONS if t + h < n}
    return rec


def summarise(recs, uc_hits=None):
    out = {"n": len(recs)}
    for h in HORIZONS:
        v = np.array([r[f"r{h}"] for r in recs if f"r{h}" in r])
        if len(v):
            k = int((v > 0).sum())
            out[f"mean_{h}d"] = round(float(v.mean()), 2)
            out[f"median_{h}d"] = round(float(np.median(v)), 2)
            out[f"p_up_{h}d"] = round(100 * k / len(v), 1)
            out[f"p_up_{h}d_ci"] = wilson(k, len(v))
    if uc_hits is not None and recs:
        k = sum(uc_hits)
        out["p_upper_circuit_20d"] = round(100 * k / len(uc_hits), 1)
        out["p_upper_circuit_20d_ci"] = wilson(k, len(uc_hits))
    return out


def replay(frames, det, limit):
    sig_events, base, uc_days = [], [], []
    freq = {}
    for s, df in frames.items():
        r = det.detect_stealth_accumulation(df, None)        # unchanged engine, no 4-hour data
        sig = r["signal_type"].to_numpy()
        ret = (df["close"] / df["close"].shift() - 1).to_numpy()
        locked = (df["close"] >= df["high"] * 0.999).to_numpy()
        uc = (ret >= limit - 0.005) & (ret <= CORP_ACTION) & locked
        n = len(df)
        years = max((df.index[-1] - df.index[0]).days / 365.25, 1e-9)
        freq[s] = {k: int((sig == k).sum()) / years for k in ("WATCH", "READY", "EXTREME")}
        uc_next = np.array([uc[t + 1:t + 21].any() for t in range(n)])
        # first bar of each signal run = one event (no overlap)
        prev = "NO_SIGNAL"
        for t in range(30, n):
            f = None
            if sig[t] != "NO_SIGNAL" and prev == "NO_SIGNAL":
                f = forward(df, t)
                if f:
                    sig_events.append({"symbol": s, "date": df.index[t], "cls": sig[t], **f,
                                       "uc20": bool(uc_next[t])})
            prev = sig[t]
            if t % 5 == 0:
                f = f or forward(df, t)
                if f:
                    base.append({**f, "uc20": bool(uc_next[t])})
        for t in np.flatnonzero(uc):
            if t < 40:
                continue
            w = sig[max(0, t - CAPTURE_WINDOW):t]
            caught = (w != "NO_SIGNAL").any()
            row = r.iloc[t - 1]
            missing = [name for name, ok in (
                ("consolidation gate", row["is_consolidating"]), ("MACD gate", row["macd_confirmation"]),
                ("supply exhaustion", row["dry_supply_flag"]), ("absorption", row["absorption_active"]),
                ("OBV divergence", row["obv_divergence"])) if not bool(ok)]
            uc_days.append({"symbol": s, "date": df.index[t].strftime("%Y-%m-%d"), "ret_pct": round(ret[t] * 100, 2),
                            "caught": bool(caught), "best_prior_class": max(
                                (x for x in w if x != "NO_SIGNAL"), key=["WATCH", "READY", "EXTREME"].index, default=None),
                            "score_day_before": int(row["accumulation_score"]), "missing_day_before": missing})
    return sig_events, base, uc_days, freq


def stored_signals(conn, frames, limit):
    try:
        rows = conn.execute("SELECT symbol, scan_date, signal_type, accumulation_score FROM wyckoff_accumulation "
                            "WHERE signal_type != 'NO_SIGNAL'").fetchall()
        span = conn.execute("SELECT MIN(scan_date) AS a, MAX(scan_date) AS b, COUNT(DISTINCT scan_date) AS n "
                            "FROM wyckoff_scans").fetchone()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    ev = []
    for r in rows:
        df = frames.get(r["symbol"])
        if df is None:
            continue
        idx = df.index.searchsorted(pd.Timestamp(r["scan_date"]))
        if idx >= len(df) or df.index[idx] != pd.Timestamp(r["scan_date"]):
            continue
        f = forward(df, idx)
        ret = (df["close"] / df["close"].shift() - 1).to_numpy()
        locked = (df["close"] >= df["high"] * 0.999).to_numpy()
        uc = (ret >= limit - 0.005) & (ret <= CORP_ACTION) & locked
        ev.append({"symbol": r["symbol"], "date": r["scan_date"], "cls": r["signal_type"],
                   "uc20": bool(uc[idx + 1:idx + 21].any()), **(f or {})})
    by = {c: summarise([e for e in ev if e["cls"] == c], [e["uc20"] for e in ev if e["cls"] == c])
          for c in ("WATCH", "READY", "EXTREME")}
    return {"scan_dates": dict(span) if span else None, "signals": len(ev), "by_class": by,
            "all": summarise(ev, [e["uc20"] for e in ev]),
            "rows": [{k: e[k] for k in ("symbol", "date", "cls", "uc20")} | {k: round(e[k], 2) for k in e if k.startswith("r")}
                     for e in sorted(ev, key=lambda x: x["date"])]}


def main():
    import turso_db
    t0 = time.time()
    conn = turso_db.get_connection()
    cfg = load_config()
    det = WyckoffDetector(cfg)
    universe = cfg["stocks"]["universe"]
    frames = load_daily(conn, universe)
    limit = circuit_limit(frames)
    ev, base, ucd, freq = replay(frames, det, limit)
    res = {"status": "ok", "run_at": datetime.now(timezone.utc).isoformat(),
           "universe_config": len(universe), "symbols_with_data": len(frames),
           "data_from": str(min(d.index[0] for d in frames.values()).date()),
           "data_to": str(max(d.index[-1] for d in frames.values()).date()),
           "upper_circuit_definition": f"close-to-close >= {round((limit - 0.005) * 100, 2)}% (empirical limit "
                                       f"{round(limit * 100, 2)}%), close at the day's high, <= 11%",
           "replay_limitation": "4-hour BB compression (20 pts) unavailable historically -> replayed scores are a lower bound (max 80)",
           "thresholds_used_unchanged": {k: det.config[k] for k in ("watch_threshold", "ready_threshold", "extreme_threshold")}}
    res["replay"] = {
        "signals": len(ev),
        "by_class": {c: summarise([e for e in ev if e["cls"] == c], [e["uc20"] for e in ev if e["cls"] == c])
                     for c in ("WATCH", "READY", "EXTREME")},
        "all_signals": summarise(ev, [e["uc20"] for e in ev]),
        "baseline_every_5th_day": summarise(base, [b["uc20"] for b in base]),
        "signals_per_symbol_year": {c: round(float(np.mean([f[c] for f in freq.values()])), 2)
                                    for c in ("WATCH", "READY", "EXTREME")},
        "symbols_never_signalling": sum(1 for f in freq.values() if not any(f.values())),
        "by_year": {str(y): summarise([e for e in ev if e["date"].year == y], [e["uc20"] for e in ev if e["date"].year == y])
                    for y in sorted({e["date"].year for e in ev})},
    }
    caught = [u for u in ucd if u["caught"]]
    miss = [u for u in ucd if not u["caught"]]
    from collections import Counter
    res["upper_circuit"] = {
        "days": len(ucd), "captured": len(caught),
        "capture_rate_pct": round(100 * len(caught) / len(ucd), 1) if ucd else None,
        "capture_rate_ci": wilson(len(caught), len(ucd)),
        "missed": len(miss),
        "missing_condition_counts_day_before": dict(Counter(m for u in miss for m in u["missing_day_before"]).most_common()),
        "missed_score_distribution_day_before": dict(Counter(u["score_day_before"] for u in miss).most_common()),
        "recent_missed": sorted(miss, key=lambda u: u["date"])[-40:],
        "captured_list": sorted(caught, key=lambda u: u["date"])[-40:],
    }
    res["stored"] = stored_signals(conn, frames, limit)
    res["elapsed_s"] = round(time.time() - t0)
    write_report(res)
    try:
        conn.execute("""INSERT INTO analysis_cache(cache_key, run_at, run_at_epoch, result_json)
            VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET run_at=excluded.run_at,
            run_at_epoch=excluded.run_at_epoch, result_json=excluded.result_json""",
                     ("wyckoff_diagnostic", res["run_at"], time.time(), json.dumps(res, default=str)))
        conn.commit()
    except Exception as e:
        print(f"save failed: {e}")
    if hasattr(turso_db, "print_usage_report"):
        turso_db.print_usage_report(label="run_wyckoff_diagnostic.py")
    return 0


def _row(name, s, uc=True):
    if not s or not s.get("n"):
        return f"| {name} | 0 | | | | | |"
    ci = s.get("p_up_10d_ci", (None, None))
    return (f"| {name} | {s['n']} | {s.get('mean_5d')} | {s.get('mean_10d')} | {s.get('mean_20d')} | "
            f"{s.get('p_up_10d')} [{ci[0]}–{ci[1]}] | {s.get('p_upper_circuit_20d', '—')} |")


def write_report(res):
    rp, uc, stv = res["replay"], res["upper_circuit"], res["stored"]
    H = "| Group | n | Mean 5d % | Mean 10d % | Mean 20d % | P(up 10d) [95% CI] | P(upper circuit within 20d) % |\n|---|---|---|---|---|---|---|"
    L = ["# Wyckoff engine — historical diagnostic (read-only)", "",
         f"Run {res['run_at'][:16]} UTC · {res['symbols_with_data']}/{res['universe_config']} configured symbols with data · "
         f"{res['data_from']} → {res['data_to']}", "",
         f"Upper circuit = {res['upper_circuit_definition']}. Thresholds used unchanged: {res['thresholds_used_unchanged']}.", "",
         f"**Limitation:** {res['replay_limitation']}.", "",
         "## A. Replay of the unchanged detector (daily data)", "", H]
    for c in ("WATCH", "READY", "EXTREME"):
        L.append(_row(c, rp["by_class"][c]))
    L += [_row("All signals", rp["all_signals"]), _row("Baseline (every 5th session)", rp["baseline_every_5th_day"]), "",
          f"Signals per symbol per year: {rp['signals_per_symbol_year']} (signal-days). "
          f"Symbols that never signalled: {rp['symbols_never_signalling']}.", "", "### By year", "", H]
    for y, s in rp["by_year"].items():
        L.append(_row(y, s))
    L += ["", "## Upper-circuit capture", "",
          f"Upper-circuit days: **{uc['days']}** · captured (signal in prior {CAPTURE_WINDOW} sessions): **{uc['captured']}** "
          f"→ capture rate **{uc['capture_rate_pct']}%** [95% CI {uc['capture_rate_ci'][0]}–{uc['capture_rate_ci'][1]}] · missed {uc['missed']}", "",
          f"Conditions failing on the day before a missed upper circuit: {uc['missing_condition_counts_day_before']}", "",
          f"Replayed score the day before missed upper circuits: {uc['missed_score_distribution_day_before']}", "",
          "### Most recent missed upper circuits", "", "| Date | Symbol | Move % | Score day before | Missing |", "|---|---|---|---|---|"]
    for u in uc["recent_missed"][-25:]:
        L.append(f"| {u['date']} | {u['symbol']} | {u['ret_pct']} | {u['score_day_before']} | {', '.join(u['missing_day_before'])} |")
    L += ["", "### Captured upper circuits (most recent)", "", "| Date | Symbol | Move % | Best prior signal |", "|---|---|---|---|"]
    for u in uc["captured_list"][-25:]:
        L.append(f"| {u['date']} | {u['symbol']} | {u['ret_pct']} | {u['best_prior_class']} |")
    L += ["", "## B. Signals actually stored by the production batch (full engine incl. 4-hour data)", ""]
    if "error" in stv:
        L.append(f"Unavailable: {stv['error']}")
    else:
        L += [f"Scan dates: {stv['scan_dates']} · signals: {stv['signals']}", "", H]
        for c in ("WATCH", "READY", "EXTREME"):
            L.append(_row(c, stv["by_class"][c]))
        L.append(_row("All stored signals", stv["all"]))
    L += ["", "_Diagnostic only. No production threshold or weight was changed; samples below ~30 are not reliable._"]
    REPORT.write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
