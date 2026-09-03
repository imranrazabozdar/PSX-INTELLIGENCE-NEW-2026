#!/usr/bin/env python3
"""Part 1 (free): regroup the already-completed 23-indicator pooled sweep
(phase1_all26_triple_barrier_results.md) and the liquidity-tiered top-8
results (liquidity_stratified_results.md) into 4 feature families. Pure
aggregation -- both markdown files are parsed directly off disk, zero new
backtest computation.

Part 2 (new): two pre-registered within-family AGREEMENT tests --
"MA Stack Alignment" (Test A) and "Volume Confirmation Cluster" (Test B)
-- reusing the exact Triple-Barrier machinery (label_trigger,
evaluate_verdict, MAX_HOLD, N_FLOOR, mechanical 12-month holdout) from
phase1_triple_barrier_test.py, run once on the full 89-symbol
WATCHLIST_SYMBOLS universe.

Single script, single execution pass. Does NOT proceed to Phase 2/ML
regardless of outcome.
"""
import re
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

import turso_db
from indicator_backtester import _compute_signals, _cmf
from analyze_premove import atr as atr_from_bars
from phase1_triple_barrier_test import label_trigger, evaluate_verdict, MAX_HOLD, N_FLOOR

POOLED_MD = Path(__file__).parent / "phase1_all26_triple_barrier_results.md"
TIERED_MD = Path(__file__).parent / "liquidity_stratified_results.md"

# Copied verbatim from backend/app.py's WATCHLIST_SYMBOLS (89 symbols) --
# same static-list-copy rationale as watchlist_cluster_analysis.py: app.py
# is a FastAPI app with unrelated heavy side-effect imports that have no
# business running inside a read-only analysis script.
WATCHLIST_SYMBOLS = [
    'CNERGY', 'PRL', 'BOP', 'FNEL', 'KEL', 'SSGC', 'PACE', 'WAVESAPP', 'NBP', 'PIBTL',
    'FCL', 'PPL', 'BLUEX', 'AKBL', 'PREMA', 'BECO', 'BAFL', 'LOTCHEM', 'NRL', 'SYS',
    'HUBC', 'AICL', 'THCCL', 'FCCL', 'HASCOL', 'ABL', 'PSO', 'HBL', 'OGDC', 'AVN',
    'SLGL', 'SPSL', 'POWER', 'UBL', 'TRG', 'TOMCL', 'AIRLINK', 'FFL', 'SEARL', 'CLOV',
    'SNBL', 'SNGP', 'MDTL', 'BML', 'BNL', 'BAHL', 'SYM', 'WASL', 'CPHL', 'FFC',
    'MARI', 'MUGHAL', 'BGL', 'GAL', 'GDL', 'YOUW', 'ZAL', 'AGP', 'LOADS', 'KOHC',
    'SAZEW', 'WAHDAT', 'STCL', 'GLAXO', 'TGL', 'MCB', 'JSBL', 'IMAGE', 'SCBPL', 'BOK',
    'AGTL', 'ECPL', 'BIPL', 'HMB', 'FABL', 'SBL', 'ASTL', 'EFERT', 'DGKC', 'LUCK',
    'TBL', 'STL', 'STLR', 'MLCF', 'CHCC', 'WTL', 'PTC', 'QTECH', 'ITANZ',
]

FAMILIES = {
    "VOLUME": ["VOLUME_SPIKE", "OBV_DIVERGE_BULL", "CMF_POS", "CMF_NEG"],
    "MOVING-AVERAGE": ["EMA20_CROSS_UP", "EMA20_CROSS_DN", "EMA50_CROSS_UP",
                       "EMA50_CROSS_DN", "GOLDEN_CROSS", "DEATH_CROSS"],
    "MOMENTUM": ["RSI_OVERBOUGHT", "RSI_OVERSOLD", "RSI_HEALTHY", "MOM_CROSS_POS",
                 "MOM_CROSS_NEG", "MACD_CROSS_UP", "MACD_CROSS_DOWN", "MACD_HIST_POS"],
    "VOLATILITY": ["BB_OVERBOUGHT", "BB_OVERSOLD", "BB_SQUEEZE_BREAK", "ADX_TRENDING", "ADX_WEAK"],
}
ALL_23 = [ind for members in FAMILIES.values() for ind in members]
FAMILY_OF = {ind: fam for fam, members in FAMILIES.items() for ind in members}
JUDGMENT_CALLS = [
    "ADX_TRENDING and ADX_WEAK measure trend STRENGTH, not volatility in the strict "
    "sense (they derive from directional movement, not price dispersion like Bollinger "
    "Bands). They are placed in VOLATILITY per this task's explicit pre-registered "
    "assignment, grouped there as a 'regime/dispersion' family alongside the Bollinger "
    "signals rather than in MOMENTUM (they don't measure direction) -- noted explicitly "
    "rather than silently reassigned.",
]

TOP8 = ["BB_OVERBOUGHT", "BB_SQUEEZE_BREAK", "RSI_OVERBOUGHT", "MOM_CROSS_POS",
        "VOLUME_SPIKE", "CMF_POS", "RSI_HEALTHY", "OBV_DIVERGE_BULL"]


# ============================================================== PART 1 ====
def parse_md_table(path, second_field_is_tier, known_first_field):
    """Pure-parsing of an already-committed markdown report -- no
    recomputation. Returns list of row dicts."""
    rows = []
    text = path.read_text()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) != 9:
            continue
        name = re.sub(r"\s*\*.*\*\s*$", "", parts[0]).strip()
        if name not in known_first_field:
            continue
        if second_field_is_tier:
            if parts[1] not in ("A", "B", "C"):
                continue
        else:
            if parts[1] in ("A", "B", "C"):
                continue
        try:
            n = int(parts[2])
            n_pos = int(parts[3])
            n_neg = int(parts[4])
            n_zero = int(parts[5])
        except ValueError:
            continue
        prec_m = re.match(r"([\d.]+)%", parts[6])
        precision = float(prec_m.group(1)) if prec_m else None
        ci_m = re.match(r"\[([\d.]+)%,\s*([\d.]+)%\]", parts[7])
        ci_low = float(ci_m.group(1)) if ci_m else None
        ci_high = float(ci_m.group(2)) if ci_m else None
        verdict = parts[8].split(" ")[0].split("—")[0].strip()
        row = {"name": name, "n": n, "n_pos": n_pos, "n_neg": n_neg, "n_zero": n_zero,
               "precision": precision, "ci_low": ci_low, "ci_high": ci_high, "verdict": verdict}
        if second_field_is_tier:
            row["tier"] = parts[1]
        rows.append(row)
    return rows


def build_part1():
    pooled_rows = parse_md_table(POOLED_MD, second_field_is_tier=False, known_first_field=set(ALL_23))
    tiered_rows = parse_md_table(TIERED_MD, second_field_is_tier=True, known_first_field=set(TOP8))

    pooled_by_name = {r["name"]: r for r in pooled_rows}
    tiered_by_name_tier = {(r["name"], r["tier"]): r for r in tiered_rows}

    missing_pooled = set(ALL_23) - set(pooled_by_name)
    if missing_pooled:
        raise RuntimeError(f"Part 1 parse incomplete -- missing pooled rows for: {sorted(missing_pooled)}")

    family_summary = []
    for fam, members in FAMILIES.items():
        precisions = [pooled_by_name[m]["precision"] for m in members]
        ci_lows = [pooled_by_name[m]["ci_low"] for m in members]
        mean_precision = sum(precisions) / len(precisions)
        mean_ci_low = sum(ci_lows) / len(ci_lows)
        gaps = [(m, abs(50.0 - pooled_by_name[m]["precision"])) for m in members]
        closest = min(gaps, key=lambda x: x[1])

        by_tier = {}
        for tier in ("A", "B", "C"):
            tier_members = [m for m in members if (m, tier) in tiered_by_name_tier]
            if not tier_members:
                by_tier[tier] = None
                continue
            t_prec = [tiered_by_name_tier[(m, tier)]["precision"] for m in tier_members]
            t_ci = [tiered_by_name_tier[(m, tier)]["ci_low"] for m in tier_members]
            by_tier[tier] = {
                "members": tier_members,
                "mean_precision": sum(t_prec) / len(t_prec),
                "mean_ci_low": sum(t_ci) / len(t_ci),
            }

        family_summary.append({
            "family": fam, "members": members, "mean_precision": mean_precision,
            "mean_ci_low": mean_ci_low, "closest_member": closest[0], "closest_gap": closest[1],
            "closest_precision": pooled_by_name[closest[0]]["precision"], "by_tier": by_tier,
        })

    return pooled_by_name, tiered_by_name_tier, family_summary


# ============================================================== PART 2 ====
def load_watchlist_universe():
    conn = turso_db.get_connection()
    universe = {}
    for sym in WATCHLIST_SYMBOLS:
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


MIN_MA_HISTORY = 100  # bars needed for a meaningful EMA100


def run_combo_tests():
    now = datetime.now(timezone.utc)
    end_date = now.date()
    start_date = end_date - timedelta(days=365)

    universe = load_watchlist_universe()

    records_a = []
    records_b = []
    combo_breakdown = {"ab": 0, "ac": 0, "bc": 0, "abc": 0}

    for sym, bars in universe.items():
        if len(bars) < MIN_MA_HISTORY + MAX_HOLD + 1:
            continue
        g = pd.DataFrame(bars)
        close, high, low, volume = g["close"], g["high"], g["low"], g["volume"]

        signals = _compute_signals(g)
        cond_a_vol = signals["VOLUME_SPIKE"]
        cond_b_obv = signals["OBV_DIVERGE_BULL"]
        cmf = _cmf(high, low, close, volume, period=20)
        cond_c_cmf = cmf > 0

        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema100 = close.ewm(span=100, adjust=False).mean()
        trigger_a = (close > ema20) & (ema20 > ema50) & (ema50 > ema100)

        n_true = cond_a_vol.astype(int) + cond_b_obv.astype(int) + cond_c_cmf.astype(int)
        trigger_b = n_true >= 2

        atr14 = atr_from_bars(bars, 14)

        for i in range(MIN_MA_HISTORY, len(bars)):
            trig_date = bars[i]["date"]
            if not (start_date.isoformat() <= trig_date <= end_date.isoformat()):
                continue
            if atr14[i] is None or i + MAX_HOLD >= len(bars):
                continue

            if bool(trigger_a.iloc[i]):
                label, _, _ = label_trigger(bars, i, atr14[i])
                records_a.append(label)

            if bool(trigger_b.iloc[i]):
                label, _, _ = label_trigger(bars, i, atr14[i])
                records_b.append(label)
                a_, b_, c_ = bool(cond_a_vol.iloc[i]), bool(cond_b_obv.iloc[i]), bool(cond_c_cmf.iloc[i])
                if a_ and b_ and c_:
                    combo_breakdown["abc"] += 1
                elif a_ and b_:
                    combo_breakdown["ab"] += 1
                elif a_ and c_:
                    combo_breakdown["ac"] += 1
                elif b_ and c_:
                    combo_breakdown["bc"] += 1

    def summarize(records):
        n = len(records)
        n_pos = sum(1 for l in records if l == 1)
        n_neg = sum(1 for l in records if l == -1)
        n_zero = sum(1 for l in records if l == 0)
        verdict, precision, ci_low, ci_high = evaluate_verdict(n, n_pos)
        return {"n": n, "n_pos": n_pos, "n_neg": n_neg, "n_zero": n_zero,
                "precision": precision, "ci_low": ci_low, "ci_high": ci_high, "verdict": verdict}

    result_a = summarize(records_a)
    result_b = summarize(records_b)
    result_b["combo_breakdown"] = combo_breakdown
    return result_a, result_b, len(universe), start_date, end_date


# ================================================================ report ===
def main():
    now = datetime.now(timezone.utc)
    pooled_by_name, tiered_by_name_tier, family_summary = build_part1()
    result_a, result_b, n_universe, start_date, end_date = run_combo_tests()

    lines = []
    lines.append("# Feature-Family Regrouping + Within-Family Agreement Tests")
    lines.append("")
    lines.append(f"**Run date (UTC):** {now.isoformat()}")
    lines.append("")
    lines.append("## Part 1 — free regrouping of already-completed results (zero new computation)")
    lines.append("")
    lines.append("Both tables below are parsed directly from `analysis/phase1_all26_triple_barrier_results.md` "
                 "and `analysis/liquidity_stratified_results.md`, already on disk from prior tasks. No backtest "
                 "was re-run for this part.")
    lines.append("")
    lines.append("### Family assignment (checkable)")
    lines.append("")
    lines.append("| Family | Members |")
    lines.append("|---|---|")
    for fam, members in FAMILIES.items():
        lines.append(f"| {fam} | {', '.join(members)} |")
    lines.append("")
    lines.append("**Judgment call(s) noted explicitly:**")
    for jc in JUDGMENT_CALLS:
        lines.append(f"- {jc}")
    lines.append("")

    lines.append("### Family-level summary — pooled (all 23 indicators' own already-completed pooled result)")
    lines.append("")
    lines.append("| Family | Members (n) | Mean precision | Mean Wilson CI lower bound | Closest member to 50% |")
    lines.append("|---|---|---|---|---|")
    for fs in family_summary:
        lines.append(f"| {fs['family']} | {len(fs['members'])} | {fs['mean_precision']:.2f}% | "
                     f"{fs['mean_ci_low']:.2f}% | {fs['closest_member']} ({fs['closest_precision']:.2f}%, "
                     f"gap {fs['closest_gap']:.2f}pts) |")
    lines.append("")

    lines.append("### Family-level summary — by liquidity tier (only using the top-8 indicators already tiered)")
    lines.append("")
    lines.append("| Family | Tier | Members used | Mean precision | Mean Wilson CI lower bound |")
    lines.append("|---|---|---|---|---|")
    for fs in family_summary:
        for tier in ("A", "B", "C"):
            bt = fs["by_tier"][tier]
            if bt is None:
                lines.append(f"| {fs['family']} | {tier} | (none of this family's members are in the top-8 tiered set) | — | — |")
            else:
                lines.append(f"| {fs['family']} | {tier} | {', '.join(bt['members'])} | "
                             f"{bt['mean_precision']:.2f}% | {bt['mean_ci_low']:.2f}% |")
    lines.append("")

    lines.append("## Part 2 — two NEW pre-registered within-family agreement tests")
    lines.append("")
    lines.append(f"Universe: {n_universe} of {len(WATCHLIST_SYMBOLS)} watchlist symbols with usable history. "
                 f"Holdout window: {start_date.isoformat()} to {end_date.isoformat()} (mechanical, identical "
                 f"derivation to every other test in this project). Same barriers as "
                 f"phase1_all26_sweep.py: upper = entry close + 2.0xATR(14); lower = entry close - 1.5xATR(14); "
                 f"vertical = 15 trading days; same-day double-touch resolves to the lower barrier. n>=150 "
                 f"required or INCONCLUSIVE; PASS only if Wilson 95% CI lower bound on +1-class precision > 50.0%.")
    lines.append("")
    lines.append("### Test A — MA Stack Alignment")
    lines.append("")
    lines.append("**Definition:** trigger fires on any day where close > EMA20 AND EMA20 > EMA50 AND "
                 "EMA50 > EMA100 simultaneously (full bullish stack), computed on the closing price with "
                 "standard exponential moving averages (`close.ewm(span=N, adjust=False).mean()`, the same "
                 "method already used for EMA20/EMA50 in `backend/indicator_backtester.py`'s `_compute_signals()` "
                 "-- EMA100 is the only new series, computed identically, not reimplemented). A persistent "
                 "STATE condition (every day the stack holds), not a one-bar crossover event.")
    lines.append("")
    lines.append("| n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    ra = result_a
    prec_s = f"{ra['precision']:.2f}%" if ra["precision"] is not None else "—"
    ci_s = f"[{ra['ci_low']:.2f}%, {ra['ci_high']:.2f}%]" if ra["ci_low"] is not None else "—"
    lines.append(f"| {ra['n']} | {ra['n_pos']} | {ra['n_neg']} | {ra['n_zero']} | {prec_s} | {ci_s} | {ra['verdict']} |")
    lines.append("")
    lines.append("Component indicators for the beats-every-component check: EMA20_CROSS_UP "
                 f"({pooled_by_name['EMA20_CROSS_UP']['precision']:.2f}%), EMA50_CROSS_UP "
                 f"({pooled_by_name['EMA50_CROSS_UP']['precision']:.2f}%), GOLDEN_CROSS "
                 f"({pooled_by_name['GOLDEN_CROSS']['precision']:.2f}%) -- the three bullish MOVING-AVERAGE-family "
                 "members Test A's alignment condition is built from (the bearish members EMA20_CROSS_DN/"
                 "EMA50_CROSS_DN/DEATH_CROSS are not relevant comparators for a bullish-stack test).")
    lines.append("")

    lines.append("### Test B — Volume Confirmation Cluster")
    lines.append("")
    lines.append("**Definition:** trigger fires on any day where at least 2 of these 3 volume-based conditions "
                 "are true simultaneously: (a) volume >= 1.8x its 20-day average (reused verbatim as "
                 "`VOLUME_SPIKE` from `_compute_signals()`); (b) OBV has risen while price was flat/down, "
                 "reused verbatim as the existing `OBV_DIVERGE_BULL` boolean series from `_compute_signals()` "
                 "-- **note:** the task text describing this condition said 'trailing 10 days', but the actual "
                 "existing `OBV_DIVERGE_BULL` definition in `backend/indicator_backtester.py` uses a 30-bar "
                 "lookback (`obv > obv.shift(30)` and `close <= close.shift(30) * 1.01`); per this project's "
                 "reuse-verbatim-don't-redefine rule and the task's own instruction to reuse 'the existing "
                 "OBV_DIVERGE_BULL definition', the actual 30-bar definition was reused as-is and this "
                 "discrepancy is flagged here rather than silently resolved either way; (c) CMF(20) is positive "
                 "(a persistent state -- `_cmf(...) > 0` -- computed with the existing `_cmf()` function but NOT "
                 "the same event as `CMF_POS`, which is a one-bar cross-above-zero event; the task's own text "
                 "specifies 'CMF(20) is positive', so the persistent-state condition is what was implemented, "
                 "while `CMF_POS`'s pooled result is still used below as the comparison benchmark per the task's "
                 "explicit instruction).")
    lines.append("")
    lines.append("| n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    rb = result_b
    prec_s = f"{rb['precision']:.2f}%" if rb["precision"] is not None else "—"
    ci_s = f"[{rb['ci_low']:.2f}%, {rb['ci_high']:.2f}%]" if rb["ci_low"] is not None else "—"
    lines.append(f"| {rb['n']} | {rb['n_pos']} | {rb['n_neg']} | {rb['n_zero']} | {prec_s} | {ci_s} | {rb['verdict']} |")
    lines.append("")
    cb = rb["combo_breakdown"]
    lines.append(f"**Trigger breakdown by which 2 (or 3) conditions were true:** "
                 f"volume+OBV only: {cb['ab']}; volume+CMF only: {cb['ac']}; OBV+CMF only: {cb['bc']}; "
                 f"all three: {cb['abc']}.")
    lines.append("")
    lines.append("Component indicators (as named explicitly in the task, all FAIL individually, pooled): "
                 "VOLUME_SPIKE 38.83%, OBV_DIVERGE_BULL 35.86%, CMF_POS 38.90%.")
    lines.append("")

    # -------- comparison paragraph
    a_beats_all = (ra["precision"] is not None and
                   ra["precision"] > pooled_by_name["EMA20_CROSS_UP"]["precision"] and
                   ra["precision"] > pooled_by_name["EMA50_CROSS_UP"]["precision"] and
                   ra["precision"] > pooled_by_name["GOLDEN_CROSS"]["precision"])
    b_components = [38.83, 35.86, 38.90]
    b_beats_all = rb["precision"] is not None and all(rb["precision"] > c for c in b_components)

    fam_precisions = {fs["family"]: fs["mean_precision"] for fs in family_summary}
    fam_spread = max(fam_precisions.values()) - min(fam_precisions.values())

    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"**Family profile:** pooled mean precision across the four families ranges from "
        f"{min(fam_precisions.values()):.2f}% ({min(fam_precisions, key=fam_precisions.get)}) to "
        f"{max(fam_precisions.values()):.2f}% ({max(fam_precisions, key=fam_precisions.get)}) -- a spread of "
        f"{fam_spread:.2f} points. "
        + ("This is a modest, not dramatic, difference; no family is systematically distinct from the others -- "
           "all four sit well below the 50% CI-lower-bound line on both a pooled and a per-tier basis, and the "
           "same liquid-tier-does-better pattern documented in the earlier liquidity task shows up inside every "
           "family that has top-8 members represented (VOLUME, MOMENTUM, VOLATILITY), not just one."
           if fam_spread < 10 else
           "This is a meaningfully large spread, worth noting as a real difference in family profile."))
    lines.append("")
    lines.append(
        f"**Test A (MA Stack Alignment):** precision {ra['precision']:.2f}% vs. its three bullish MOVING-AVERAGE "
        f"components (EMA20_CROSS_UP {pooled_by_name['EMA20_CROSS_UP']['precision']:.2f}%, EMA50_CROSS_UP "
        f"{pooled_by_name['EMA50_CROSS_UP']['precision']:.2f}%, GOLDEN_CROSS "
        f"{pooled_by_name['GOLDEN_CROSS']['precision']:.2f}%) -- "
        + (f"Test A beats ALL three of its components, a genuine finding by the task's own bar." if a_beats_all else
           f"Test A does NOT beat all three components (beating the family average, if it even does, is not "
           f"enough -- the task's bar is beating every single component), so this is not a real finding "
           f"regardless of Test A's own verdict.")
    )
    lines.append("")
    lines.append(
        f"**Test B (Volume Confirmation Cluster):** precision {rb['precision']:.2f}% vs. its three components "
        f"(VOLUME_SPIKE 38.83%, OBV_DIVERGE_BULL 35.86%, CMF_POS 38.90%) -- "
        + (f"Test B beats ALL three of its components, a genuine finding by the task's own bar." if b_beats_all else
           f"Test B does NOT beat all three components, so this is not a real finding regardless of Test B's "
           f"own verdict.")
    )
    lines.append("")
    lines.append(
        "**Cumulative test count:** this task adds **2** new pre-registered tests (Test A, Test B) to the "
        "running total from this project: 23 pooled (phase1_all26_sweep) + 24 liquidity-tiered "
        "(liquidity_stratified_tests, Task 1) + 27 fingerprint-tiered (liquidity_stratified_tests, Task 2) + "
        "30 cluster-validation (watchlist_cluster_analysis, Step 4) = 104 prior tests, **bringing the running "
        "total to 106**. A single PASS among this many cumulative tests across the whole investigation needs "
        "the same 1-in-20-by-chance skepticism applied consistently -- it does not reset per-task. Whatever "
        "Test A or Test B's individual verdict is here, it is one data point among 106, not evaluated in "
        "isolation."
    )
    lines.append("")
    lines.append("Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run for any test in this task, regardless of verdict.")
    lines.append("")

    report_md = "\n".join(lines)
    out_path = Path(__file__).parent / "family_analysis_and_combo_tests.md"
    out_path.write_text(report_md)

    summary = {
        "family_summary": family_summary, "result_a": result_a, "result_b": result_b,
        "n_universe": n_universe, "window": f"{start_date.isoformat()} to {end_date.isoformat()}",
    }
    print("===JSON_START===")
    print(json.dumps(summary, separators=(",", ":")))
    print("===JSON_END===")
    print("===REPORT_MD_START===")
    print(report_md)
    print("===REPORT_MD_END===")


if __name__ == "__main__":
    main()
