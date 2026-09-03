#!/usr/bin/env python3
"""Pre-registered Triple-Barrier sweep across every indicator signal
defined in backend/indicator_backtester.py's _compute_signals() -- the
exact same source file used to verify BB_OVERSOLD's original trigger
definition in the first Phase 1 run (analysis/phase1_triple_barrier_test.py).

IMPORTANT NOTE ON COUNT: the task that requested this sweep referred to
"26 indicators." The authoritative source (_compute_signals() in
backend/indicator_backtester.py, the same file already used to verify
BB_OVERSOLD) defines exactly 23 signal types, not 26. A different,
separate script (backend/indicator_backtester_volume_extended.py) does
define additional signals (MFI, VROC, AD, PVT, VWMA, ForceIndex,
Klinger...), but that is a DIFFERENT methodology/source that was never
used to validate BB_OVERSOLD, and borrowing from it would violate the
"reuse the exact same source, do not approximate" instruction. Per the
task's own fallback rule ("if any indicator's exact original definition
cannot be located in the codebase, report SKIPPED rather than
guessing"), this sweep covers all 23 signals found in the authoritative
source and reports the count mismatch explicitly rather than silently
padding the list to 26.

Reuses (does not reimplement):
  - label_trigger(), MAX_HOLD, N_FLOOR, evaluate_verdict() from
    analysis/phase1_triple_barrier_test.py
  - _compute_signals(), _SIGNAL_INDICATOR from backend/indicator_backtester.py
  - atr() from analysis/analyze_premove.py
  - load_universe() from analysis/phase1_triple_barrier_test.py (loaded ONCE)

BB_OVERSOLD is NOT re-run -- its already-reported result (n=1115, +1=321,
-1=541, 0=253, precision 28.79%, Wilson CI [26.21%, 31.52%], verdict FAIL)
is carried over unchanged into the summary table, per instruction.

Single pass: universe loaded once, each ticker's full signal dict and
ATR series computed once, then looped across all 22 remaining
indicators reusing those cached per-ticker series -- no per-indicator
reload or recompute of shared underlying series (EMA/RSI/MACD/etc. are
each computed exactly once per ticker inside _compute_signals()).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
_ANALYSIS_DIR = str(Path(__file__).parent)
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

import pandas as pd

from indicator_backtester import _compute_signals, _SIGNAL_INDICATOR
from analyze_premove import atr as atr_from_bars
from phase1_triple_barrier_test import (
    load_universe, label_trigger, evaluate_verdict, MAX_HOLD, N_FLOOR,
)

# BB_OVERSOLD's already-known, already-reported result -- carried over
# unchanged, NOT re-run (per instruction).
BB_OVERSOLD_KNOWN_RESULT = {
    "indicator": "BB_OVERSOLD",
    "definition": "close crosses below lower Bollinger Band(20,2) this bar "
                   "(close[t]<bb_lo[t] AND close[t-1]>=bb_lo[t-1])",
    "n": 1115, "n_pos": 321, "n_neg": 541, "n_zero": 253,
    "precision_pct": 28.79, "ci_low_pct": 26.21, "ci_high_pct": 31.52,
    "verdict": "FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 "
               "under any circumstance regardless of how close the result was",
    "carried_over": True,
}

# One-line exact trigger definitions, transcribed directly from
# backend/indicator_backtester.py's _compute_signals() source (not from
# memory) -- BB_OVERSOLD excluded (carried over above, not re-run).
SIGNAL_DEFINITIONS = {
    "RSI_OVERSOLD": "RSI(14) crosses below 30 this bar",
    "RSI_OVERBOUGHT": "RSI(14) crosses above 70 this bar",
    "RSI_HEALTHY": "RSI(14) in [45,65] this bar AND RSI(14) was <45 the prior bar",
    "MACD_CROSS_UP": "MACD line crosses above its signal line this bar",
    "MACD_CROSS_DOWN": "MACD line crosses below its signal line this bar",
    "MACD_HIST_POS": "MACD histogram turns positive this bar (>0 now, <=0 prior bar)",
    "EMA20_CROSS_UP": "close crosses above EMA(20) this bar",
    "EMA50_CROSS_UP": "close crosses above EMA(50) this bar",
    "EMA20_CROSS_DN": "close crosses below EMA(20) this bar",
    "EMA50_CROSS_DN": "close crosses below EMA(50) this bar",
    "GOLDEN_CROSS": "EMA(20) crosses above EMA(50) this bar",
    "DEATH_CROSS": "EMA(20) crosses below EMA(50) this bar",
    "VOLUME_SPIKE": "volume >= 1.8x its own 20-day rolling average",
    "OBV_DIVERGE_BULL": "OBV higher than 30 bars ago AND close <=1% higher than 30 bars ago",
    "BB_SQUEEZE_BREAK": "Bollinger bandwidth was at/below its own 60-bar 10th percentile the "
                         "prior bar and widens this bar",
    "BB_OVERBOUGHT": "close crosses above upper Bollinger Band(20,2) this bar",
    "MOM_CROSS_POS": "20-bar momentum (pct_change*100) crosses above 0 this bar",
    "MOM_CROSS_NEG": "20-bar momentum (pct_change*100) crosses below 0 this bar",
    "ADX_TRENDING": "ADX crosses above 25 this bar",
    "ADX_WEAK": "ADX crosses below 20 this bar",
    "CMF_POS": "Chaikin Money Flow(20) crosses above 0 this bar",
    "CMF_NEG": "Chaikin Money Flow(20) crosses below 0 this bar",
}

# Sanity check: the two independent enumerations of the signal set
# (_SIGNAL_INDICATOR's keys, minus BB_OVERSOLD; and this file's own
# SIGNAL_DEFINITIONS) must agree exactly, or the sweep stops rather
# than silently running a mismatched set.
_expected = set(_SIGNAL_INDICATOR.keys()) - {"BB_OVERSOLD"}
assert set(SIGNAL_DEFINITIONS.keys()) == _expected, (
    f"Signal set mismatch: {set(SIGNAL_DEFINITIONS.keys()) ^ _expected}")


def main():
    now = datetime.now(timezone.utc)
    end_date = now.date()
    start_date = end_date - timedelta(days=365)

    universe = load_universe()

    # Compute each ticker's full signal dict + ATR series ONCE.
    per_ticker = {}
    for sym, bars in universe.items():
        if len(bars) < 21:
            continue
        g = pd.DataFrame(bars)
        signals = _compute_signals(g)
        atr14 = atr_from_bars(bars, 14)
        per_ticker[sym] = (bars, signals, atr14)

    results = [BB_OVERSOLD_KNOWN_RESULT]

    for name, definition in SIGNAL_DEFINITIONS.items():
        records = []
        for sym, (bars, signals, atr14) in per_ticker.items():
            trig = signals[name]
            for i in range(len(bars)):
                if not bool(trig.iloc[i]):
                    continue
                trig_date = bars[i]["date"]
                if not (start_date.isoformat() <= trig_date <= end_date.isoformat()):
                    continue
                if atr14[i] is None:
                    continue
                if i + MAX_HOLD >= len(bars):
                    continue
                label, _, _ = label_trigger(bars, i, atr14[i])
                records.append(label)

        n = len(records)
        n_pos = sum(1 for l in records if l == 1)
        n_neg = sum(1 for l in records if l == -1)
        n_zero = sum(1 for l in records if l == 0)
        verdict, precision_pct, ci_low, ci_high = evaluate_verdict(n, n_pos)

        results.append({
            "indicator": name, "definition": definition,
            "n": n, "n_pos": n_pos, "n_neg": n_neg, "n_zero": n_zero,
            "precision_pct": precision_pct, "ci_low_pct": ci_low, "ci_high_pct": ci_high,
            "verdict": verdict, "carried_over": False,
        })

    # Sort by Wilson CI lower bound descending (display only; INCONCLUSIVE
    # rows, which have no CI, sort to the bottom).
    def sort_key(r):
        return r["ci_low_pct"] if r["ci_low_pct"] is not None else -1.0
    results_sorted = sorted(results, key=sort_key, reverse=True)

    n_pass = sum(1 for r in results if r["verdict"].startswith("PASS"))
    n_fail = sum(1 for r in results if r["verdict"].startswith("FAIL"))
    n_inconclusive = sum(1 for r in results if r["verdict"].startswith("INCONCLUSIVE"))
    n_skipped = 0  # nothing skipped this run -- all 23 defs found in source

    lines = []
    lines.append("# Phase 1 Triple-Barrier Sweep — All Indicators")
    lines.append("")
    lines.append(f"**Run date (UTC):** {now.isoformat()}")
    lines.append(f"**Holdout window:** {start_date.isoformat()} to {end_date.isoformat()} "
                  "(mechanical, execution-date-derived; identical for every indicator below)")
    lines.append("")
    lines.append("**Count note:** the source task referred to \"26 indicators.\" The authoritative "
                  "source file for this sweep, `backend/indicator_backtester.py`'s "
                  "`_compute_signals()` -- the exact same file used to verify BB_OVERSOLD's original "
                  "definition -- defines exactly **23** signal types, not 26. A separate script "
                  "(`backend/indicator_backtester_volume_extended.py`) defines additional signals "
                  "under a different methodology that was never used to validate BB_OVERSOLD; "
                  "borrowing from it would violate the reuse-the-same-source rule, so this sweep "
                  "covers all 23 signals found in the authoritative source and reports this "
                  "discrepancy plainly rather than padding the count. Zero indicators were SKIPPED "
                  "for a missing definition -- all 23 were located directly in the source.")
    lines.append("")
    lines.append("**Method (identical for every indicator, unchanged from the BB_OVERSOLD run):** "
                  f"upper barrier = entry close + 2.0×ATR(14); lower barrier = entry close − "
                  f"1.5×ATR(14); vertical barrier = {MAX_HOLD} trading days; same-day double-touch "
                  "resolves to the lower barrier; pass/fail rule = Wilson 95% CI lower bound on "
                  f"+1-class precision > 50.0%, with n≥{N_FLOOR} required or INCONCLUSIVE. No "
                  "threshold was adjusted per-indicator.")
    lines.append("")
    lines.append("## Summary table (sorted by Wilson CI lower bound, descending — display order only)")
    lines.append("")
    lines.append("| Indicator | Trigger definition | n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in results_sorted:
        prec = f"{r['precision_pct']:.2f}%" if r["precision_pct"] is not None else "n/a"
        ci = f"[{r['ci_low_pct']:.2f}%, {r['ci_high_pct']:.2f}%]" if r["ci_low_pct"] is not None else "n/a"
        carried = " *(carried over, not re-run)*" if r.get("carried_over") else ""
        lines.append(f"| {r['indicator']}{carried} | {r['definition']} | {r['n']} | {r['n_pos']} | "
                      f"{r['n_neg']} | {r['n_zero']} | {prec} | {ci} | {r['verdict']} |")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"Of the 23 indicators evaluated (including BB_OVERSOLD, carried over from its "
                  f"prior run): **{n_pass} PASS**, **{n_fail} FAIL**, **{n_inconclusive} INCONCLUSIVE**, "
                  f"**{n_skipped} SKIPPED** (no missing definitions this run).")
    lines.append("")

    if n_pass > 0:
        lines.append(f"**Multiple-testing caveat (applies because {n_pass} indicator(s) PASSed):** "
                      "this sweep ran the same 95% confidence test independently across 23 "
                      "hypotheses. Even with an identical, unadjusted statistical bar applied to "
                      "each, running 23 independent 95% CI tests carries a non-trivial chance of at "
                      "least one false PASS by chance alone (roughly 1-(0.95)^23 ≈ 69% chance of at "
                      "least one spurious PASS somewhere in a batch this size, under the null that "
                      "none of them have a real edge). **No PASS result above should be treated as a "
                      "standalone validated edge without a correction (e.g. Bonferroni: require the "
                      "CI to clear a stricter significance level than 95%/alpha=0.05) or, better, "
                      "confirmation on a second, independent holdout period before any further "
                      "action.**")
    else:
        lines.append("No indicator PASSed in this sweep, so the multiple-testing caveat about "
                      "trusting a PASS does not apply here -- there is no PASS to caveat. The "
                      "general point still holds for any future rerun of this sweep that does "
                      "produce one or more PASSes.")
    lines.append("")
    lines.append("Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run for any indicator in this "
                  "task, regardless of verdict.")
    lines.append("")

    out_path = Path(__file__).parent / "phase1_all26_triple_barrier_results.md"
    out_path.write_text("\n".join(lines))
    print(f"Wrote {out_path}")
    print(f"PASS={n_pass} FAIL={n_fail} INCONCLUSIVE={n_inconclusive} SKIPPED={n_skipped}")


if __name__ == "__main__":
    main()
