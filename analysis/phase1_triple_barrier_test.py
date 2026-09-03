#!/usr/bin/env python3
"""Pre-registered Phase 1 Triple-Barrier test on BB_OVERSOLD.

Tests whether BB_OVERSOLD (top performer in the old fixed-percentage
backtest, backend/indicator_backtest_summary.csv, 55.11% win rate under
"+10% in 10 days" labeling) still shows an edge under path-dependent,
volatility-scaled Triple-Barrier labeling, on a mechanically-defined
12-month holdout window.

BB_OVERSOLD's exact original definition, reused verbatim (NOT
redefined) from backend/indicator_backtester.py's _compute_signals():
    BB_OVERSOLD = _cross_below(close, bb_lo)
  i.e. close crosses below the lower Bollinger Band(20,2) THIS bar:
    close[t] < bb_lo[t]  AND  close[t-1] >= bb_lo[t-1]
  This is a one-bar CROSS event, not a persistent "close < lower band"
  condition. bb_lo = SMA(20) - 2*rolling_std(20) (indicator_backtester.py's
  _bollinger(), period=20, mult=2).

ATR(14) is reused verbatim from analysis/analyze_premove.py's atr()
(Wilder-smoothed true range) -- not reimplemented.

Runs in GitHub Actions (Turso secrets) since the local psx_v2.db stub
has no daily_ohlc table -- same constraint and same LIBSQL_URL /
LIBSQL_AUTH_TOKEN pattern already used by backend/run_fingerprint_scan.py
and the other run_*_backtest.py scripts in this repo.

Single-pass, no iteration: this script is written to run once. Do not
re-run to "double check" absent an actual bug.
"""
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
_ANALYSIS_DIR = str(Path(__file__).parent)
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

import pandas as pd
from statsmodels.stats.proportion import proportion_confint

import turso_db
from indicator_backtester import _bollinger, _cross_below  # reused verbatim
from analyze_premove import atr as atr_from_bars  # reused verbatim

MAX_HOLD = 15
N_FLOOR = 150
BB_OVERSOLD_DEFINITION = (
    "BB_OVERSOLD = close crosses below the lower Bollinger Band(20,2) on this bar: "
    "close[t] < bb_lo[t] AND close[t-1] >= bb_lo[t-1], where bb_lo = SMA(20) - 2*rolling_std(20). "
    "Reused verbatim from backend/indicator_backtester.py's _compute_signals() "
    "(_cross_below(close, bb_lo)) -- a one-bar cross event, not a persistent "
    "close-below-band condition."
)


def load_universe():
    conn = turso_db.get_connection()
    rows = conn.execute("SELECT DISTINCT symbol FROM daily_ohlc").fetchall()
    symbols = [r["symbol"] if isinstance(r, dict) else r[0] for r in rows]
    universe = {}
    for sym in symbols:
        recs = conn.execute(
            "SELECT trade_date, open, high, low, close, volume FROM daily_ohlc "
            "WHERE symbol = ? ORDER BY trade_date ASC", (sym,)
        ).fetchall()
        bars = []
        for r in recs:
            if isinstance(r, dict):
                d_, o, h, l, c, v = r["trade_date"], r["open"], r["high"], r["low"], r["close"], r["volume"]
            else:
                d_, o, h, l, c, v = r
            if None in (o, h, l, c, v):
                continue
            bars.append({"date": d_, "open": float(o), "high": float(h), "low": float(l),
                         "close": float(c), "volume": float(v)})
        if bars:
            universe[sym] = bars
    return universe


def label_trigger(bars, i, atr_i):
    """Chronological forward walk over bars[i+1 .. i+MAX_HOLD]. Same-day
    double-touch resolves to the lower barrier (conservative). Returns
    (label, exit_price, exit_offset)."""
    entry_close = bars[i]["close"]
    upper = entry_close + 2.0 * atr_i
    lower = entry_close - 1.5 * atr_i
    for k in range(1, MAX_HOLD + 1):
        day = bars[i + k]
        hit_upper = day["high"] >= upper
        hit_lower = day["low"] <= lower
        if hit_lower:
            return -1, lower, k
        if hit_upper:
            return 1, upper, k
    return 0, bars[i + MAX_HOLD]["close"], MAX_HOLD


def evaluate_verdict(n, n_pos):
    """Pre-registered evaluation rule, factored out so other scripts (the
    26-indicator sweep) can reuse the EXACT same logic rather than
    reimplementing it. Returns (verdict, precision_pct_or_None,
    ci_low_pct_or_None, ci_high_pct_or_None). Behavior is identical to
    the inline logic in main() below -- this is a pure extraction, not a
    change (added after BB_OVERSOLD's own run/report already existed)."""
    if n < N_FLOOR:
        return f"INCONCLUSIVE — insufficient sample size (n={n}, floor={N_FLOOR})", None, None, None
    precision = n_pos / n
    ci_low, ci_high = proportion_confint(n_pos, n, alpha=0.05, method="wilson")
    ci_low_pct, ci_high_pct = ci_low * 100, ci_high * 100
    if ci_low_pct > 50.0:
        verdict = "PASS — statistically significant edge, proceed to Phase 2 eligibility"
    else:
        verdict = ("FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 "
                   "under any circumstance regardless of how close the result was")
    return verdict, precision * 100, ci_low_pct, ci_high_pct


def main():
    now = datetime.now(timezone.utc)
    end_date = now.date()
    start_date = end_date - timedelta(days=365)
    window_str = f"{start_date.isoformat()} to {end_date.isoformat()}"

    universe = load_universe()

    records = []
    for sym, bars in universe.items():
        if len(bars) < 21:  # need >=20 bars for Bollinger + 1 to detect a cross
            continue
        closes = pd.Series([b["close"] for b in bars])
        _, _, bb_lo = _bollinger(closes, period=20, mult=2)
        trigger = _cross_below(closes, bb_lo)
        atr14 = atr_from_bars(bars, 14)

        for i in range(len(bars)):
            if not bool(trigger.iloc[i]):
                continue
            trig_date = bars[i]["date"]
            if not (start_date.isoformat() <= trig_date <= end_date.isoformat()):
                continue
            if atr14[i] is None:
                continue
            if i + MAX_HOLD >= len(bars):  # need 15 FULL forward trading days
                continue
            label, exit_price, exit_offset = label_trigger(bars, i, atr14[i])
            entry_price = bars[i]["close"]
            records.append({
                "ticker": sym, "trigger_date": trig_date, "entry_price": entry_price,
                "label": label, "exit_price": exit_price, "exit_offset_days": exit_offset,
                "pct_return": (exit_price - entry_price) / entry_price if entry_price else None,
                "forward_path_closes": [bars[i + k]["close"] for k in range(1, MAX_HOLD + 1)],
            })

    n = len(records)
    n_pos = sum(1 for r in records if r["label"] == 1)
    n_neg = sum(1 for r in records if r["label"] == -1)
    n_zero = sum(1 for r in records if r["label"] == 0)

    lines = []
    lines.append("# Phase 1 Triple-Barrier Test — BB_OVERSOLD")
    lines.append("")
    lines.append(f"**Run date (UTC):** {now.isoformat()}")
    lines.append("")
    lines.append("## Step 1 — BB_OVERSOLD definition used")
    lines.append("")
    lines.append(BB_OVERSOLD_DEFINITION)
    lines.append("")
    lines.append("## Step 3 — Holdout window (mechanical, calendar-date-derived)")
    lines.append("")
    lines.append(f"start_date = execution_date - 365 days = **{start_date.isoformat()}**")
    lines.append(f"end_date = execution_date = **{end_date.isoformat()}**")
    lines.append(f"Window: **{window_str}**")
    lines.append("")
    lines.append("## Step 4/5 — Triple-Barrier labeling results")
    lines.append("")
    lines.append(f"Universe scanned: {len(universe)} symbols (full history from Turso `daily_ohlc`).")
    lines.append("")
    lines.append(f"**n (total labeled triggers, all classes) = {n}**")
    lines.append(f"- label = +1 (upper barrier hit first): {n_pos}")
    lines.append(f"- label = -1 (lower barrier hit first, incl. same-day tie-break): {n_neg}")
    lines.append(f"- label = 0 (neither hit within {MAX_HOLD} trading days, vertical barrier): {n_zero}")
    lines.append("")

    if n < N_FLOOR:
        verdict = f"INCONCLUSIVE — insufficient sample size (n={n}, floor={N_FLOOR})"
        lines.append(f"## Verdict: {verdict}")
        lines.append("")
        lines.append(f"n={n} is below the pre-registered floor of {N_FLOOR}. Per spec, no win rate "
                      f"or confidence interval is computed. Test stops here.")
    else:
        precision = n_pos / n
        formula = "precision_of_+1 = count(label==+1) / n  (n = ALL triggered trades: wins + losses + timeouts, not wins/(wins+losses) only)"
        ci_low, ci_high = proportion_confint(n_pos, n, alpha=0.05, method="wilson")
        ci_low_pct, ci_high_pct = ci_low * 100, ci_high * 100

        if ci_low_pct > 50.0:
            verdict = "PASS — statistically significant edge, proceed to Phase 2 eligibility"
        else:
            verdict = "FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 under any circumstance regardless of how close the result was"

        lines.append(f"**Precision of +1 class:** {precision*100:.2f}%")
        lines.append(f"**Exact formula used:** {formula}")
        lines.append(f"**Wilson 95% CI:** [{ci_low_pct:.2f}%, {ci_high_pct:.2f}%]")
        lines.append("")
        lines.append(f"## Verdict: {verdict}")
        lines.append("")

        recs_with_ret = [r for r in records if r["pct_return"] is not None]
        top_pos = sorted(recs_with_ret, key=lambda r: r["pct_return"], reverse=True)[:15]
        top_neg = sorted(recs_with_ret, key=lambda r: r["pct_return"])[:15]

        def fmt_table(rows):
            out = ["| Ticker | Trigger date | Entry | Label | Exit | Exit offset (d) | Return | Forward path (closes, day 1-15) |",
                   "|---|---|---|---|---|---|---|---|"]
            for r in rows:
                path = ", ".join(f"{c:.2f}" for c in r["forward_path_closes"])
                out.append(f"| {r['ticker']} | {r['trigger_date']} | {r['entry_price']:.2f} | "
                            f"{r['label']:+d} | {r['exit_price']:.2f} | {r['exit_offset_days']} | "
                            f"{r['pct_return']*100:+.2f}% | {path} |")
            return "\n".join(out)

        lines.append("## Step 6 — 15 most positive individual trade outcomes")
        lines.append("")
        lines.append(fmt_table(top_pos))
        lines.append("")
        lines.append("## Step 6 — 15 most negative individual trade outcomes")
        lines.append("")
        lines.append(fmt_table(top_neg))
        lines.append("")

    lines.append("## Phase 2 confirmation")
    lines.append("")
    lines.append("Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run in this task, regardless of "
                  "verdict. Even if the verdict above is PASS, Phase 2 requires a separate, explicit "
                  "go-ahead in a future task — it was not auto-continued into here.")
    lines.append("")

    report_md = "\n".join(lines)

    out_path = Path(__file__).parent / "phase1_triple_barrier_result.md"
    out_path.write_text(report_md)

    summary = {
        "n": n, "n_pos": n_pos, "n_neg": n_neg, "n_zero": n_zero,
        "verdict": verdict, "window": window_str,
    }
    print("===JSON_START===")
    print(json.dumps(summary))
    print("===JSON_END===")
    print("===REPORT_MD_START===")
    print(report_md)
    print("===REPORT_MD_END===")


if __name__ == "__main__":
    main()
