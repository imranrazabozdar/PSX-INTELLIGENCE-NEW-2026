#!/usr/bin/env python3
"""Liquidity-stratified re-test of the Phase-1 Triple-Barrier program.

Two tasks, one combined pass over data loaded ONCE:

TASK 1 -- re-test the top 8 indicators from analysis/phase1_all26_sweep.py
(ranked by Wilson CI lower bound in analysis/phase1_all26_triple_barrier_results.md)
split into 3 liquidity terciles, reusing indicator_backtester.py's
_compute_signals() (the same authoritative source, unchanged) and
phase1_triple_barrier_test.py's label_trigger/evaluate_verdict (reused
verbatim via import, not reimplemented).

TASK 2 -- 9 new fingerprints, one per stock documented in
analysis/AICL_SHFA_premove_study.md (AICL, THCCL, MDTL, FPJM, DSIL, SYM,
PREMA, JSBL, ILP -- SHFA/FNEL already covered by run_fingerprint_scan.py,
BNL excluded as a disclosure-window false positive), scanned out-of-sample
across the full universe, split into the same 3 tiers, excluding each
stock's own documented report window when scanning that stock itself.
Reuses analyze_premove.py's list-based indicator functions (mfi/rsi/macd/
bollinger/ema/atr), the same pattern run_fingerprint_scan.py used.

Liquidity tiering: trailing 20-day average traded value (avg volume x avg
close over each ticker's OWN last 20 available bars), computed once per
ticker, then split into terciles (bottom/middle/top third by count) across
the whole universe. Tier A = least liquid third, Tier B = middle third,
Tier C = most liquid third.

Same pre-registered discipline as the prior sweep: n floor before any CI
is computed (150 for Task 1, 20 for Task 2 per the smaller expected sample
sizes of single-stock-derived fingerprints), Wilson 95% CI via
statsmodels (method="wilson"), PASS only if CI lower bound > 50.0%, no
threshold/window tuning after seeing results. Single execution pass --
this script is written to run once.
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

from indicator_backtester import _compute_signals
import analyze_premove as ap
from phase1_triple_barrier_test import load_universe, label_trigger, evaluate_verdict, MAX_HOLD, N_FLOOR

# ------------------------------------------------------------- Task 1 setup
TOP8 = [
    "BB_OVERBOUGHT", "BB_SQUEEZE_BREAK", "RSI_OVERBOUGHT", "MOM_CROSS_POS",
    "VOLUME_SPIKE", "CMF_POS", "RSI_HEALTHY", "OBV_DIVERGE_BULL",
]

# ------------------------------------------------------------- Task 2 setup
FP_FLOOR = 20

FP_EXCLUDE_WINDOWS = {
    "AICL": ("2026-07-08", "2026-08-07"),
    "THCCL": ("2026-06-15", "2026-07-09"),
    "MDTL": ("2026-07-08", "2026-07-27"),
    "FPJM": ("2026-07-29", "2026-09-03"),
    "DSIL": ("2026-07-16", "2026-08-12"),
    "SYM": ("2026-04-10", "2026-07-03"),
    "PREMA": ("2026-03-15", "2026-04-27"),
    "JSBL": ("2026-05-04", "2026-06-02"),
    "ILP": ("2026-05-18", "2026-06-30"),
}

FP_DEFINITIONS = {
    "FP_AICL": (
        "BB sigma <= -2.0 at bar t0 (sigma = (close-bb_mid)/bb_std, bollinger period=20,mult=2); "
        "within the next 5 bars, a bar k where volume_ratio(20d) >= 5.0 AND MFI(14) crosses above 70 "
        "(mfi[k]>=70, mfi[k-1]<70). Trigger date = k. Derived from AICL's documented Day-1 "
        "BB -2.4 sigma / Day+3 volume 8.7x / MFI 38.4->78.9 sequence."
    ),
    "FP_THCCL": (
        "At bar t0, MFI(14) <= 55 AND max(MFI over the prior 9 bars, inclusive of t0) >= 80 (a cool-off "
        "from an overbought MFI reading); within the next 5 bars, a bar k where volume_ratio(20d) >= 3.0 "
        "AND BB sigma >= 1.5. Trigger date = k. Derived from THCCL's documented MFI drift from the 80s "
        "down to 51.1 on Day 0, followed by the Day+5 volume 3.8x / BB +3.1 sigma breakout."
    ),
    "FP_MDTL": (
        "BB sigma <= -1.5 at bar t0; within the next 3 bars, a bar k where volume_ratio(20d) >= 5.0 AND "
        "MFI(14) crosses above 75 (mfi[k]>=75, mfi[k-1]<75). Trigger date = k. Derived from MDTL's "
        "documented Day-7 BB -2.3 sigma followed by the Day+1 same-bar 6.5x volume / MFI 82.3 breakout."
    ),
    "FP_FPJM": (
        "MFI(14) stays within [25,35] for 5 consecutive prior bars (t0-5..t0-1); at t0 itself, "
        "volume_ratio(20d) >= 2.5 AND BB sigma crosses up through 1.0 (sigma[t0]>=1.0, sigma[t0-1]<1.0). "
        "Trigger date = t0. Derived from FPJM's documented multi-week base with MFI in the low-mid 30s, "
        "then the Day+2 2.76x-volume breakout day that doubled as the BB-band expansion."
    ),
    "FP_DSIL": (
        "Within any 10-bar window [t0..t0+9], at least 3 of these 4 conditions each fire on some bar in "
        "the window: volume_ratio(20d) >= 2.0; MACD histogram crosses positive; EMA20 crosses above EMA50 "
        "(golden cross); close > open (bullish bar). Then, within the following 10 bars after the window, "
        "a bar k where volume_ratio(20d) >= 4.0. Trigger date = k. Derived from DSIL's documented cluster "
        "of early signals (>2x volume day, MACD sign flip, Piercing Line, golden cross, all pre-dating the "
        "reference move) followed by the real 4.35x-volume breakout day."
    ),
    "FP_SYM": (
        "A bar t0 where volume_ratio(20d) >= 6.0; within the next 10 bars, the bar L with the lowest close "
        "in that window (a local low); within the 10 bars after L, a bar k where the MACD histogram "
        "crosses positive. Trigger date = k. Derived from SYM's documented pre-dip volume spike (6.43x) "
        "followed by the dip low and the later (day +8) MACD sign flip into bullish territory."
    ),
    "FP_PREMA": (
        "BB sigma <= -2.0 at bar t0; within the next 20 bars, a bar V where volume_ratio(20d) >= 3.0; "
        "within the same 20-bar window, at or after V, a bar k where EMA20 crosses above EMA50 (golden "
        "cross). Trigger date = k. Derived from PREMA's documented BB -2.2 sigma on the reference date, "
        "the 3.24x-volume breakout roughly 3 weeks later, and the golden cross near the window's end."
    ),
    "FP_JSBL": (
        "MFI(14) crosses below 10 at bar t0 (mfi[t0]<10, mfi[t0-1]>=10); within the next 10 bars, a bar k "
        "where volume_ratio(20d) >= 2.5 AND the MACD histogram crosses positive on the same bar. Trigger "
        "date = k. Derived from JSBL's documented extreme MFI readings (3.2-4.5) around the reference "
        "date and the later 2.6x-volume breakout with a MACD sign flip."
    ),
    "FP_ILP": (
        "BB sigma <= -1.5 at bar t0; within the next 3 bars, a bar V where volume_ratio(20d) >= 8.0; "
        "within the 20 bars after V, a bar k where RSI(14) crosses above 75 (rsi[k]>=75, rsi[k-1]<75). "
        "Trigger date = k. Derived from ILP's documented BB -1.8 sigma base, the 9.5x single-day volume "
        "spike, and the later RSI climb into the high 70s/low 80s."
    ),
}


def evaluate_verdict_fp(n, n_pos):
    """Same Wilson-CI machinery as evaluate_verdict() (reused via
    proportion_confint, method='wilson'), with the pre-registered n=20
    floor for fingerprint cells instead of n=150 (Task 2's expected
    sample sizes are much smaller -- single-stock-derived, rarer
    patterns -- than the 23-indicator sweep's)."""
    if n < FP_FLOOR:
        return f"TOO FEW MATCHES (n={n}, floor={FP_FLOOR})", None, None, None
    precision = n_pos / n
    ci_low, ci_high = proportion_confint(n_pos, n, alpha=0.05, method="wilson")
    ci_low_pct, ci_high_pct = ci_low * 100, ci_high * 100
    if ci_low_pct > 50.0:
        verdict = "PASS — statistically significant edge, proceed to Phase 2 eligibility"
    else:
        verdict = ("FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 "
                   "under any circumstance regardless of how close the result was")
    return verdict, precision * 100, ci_low_pct, ci_high_pct


def _cross_up_list(vals, i, thresh):
    if vals[i] is None or vals[i - 1] is None:
        return False
    return vals[i] >= thresh and vals[i - 1] < thresh


def compute_fp_series(bars):
    """One precompute pass per ticker, reusing analyze_premove.py's
    list-based indicator functions verbatim (not reimplemented)."""
    closes = [b["close"] for b in bars]
    opens = [b["open"] for b in bars]
    volumes = [b["volume"] for b in bars]
    mfi_l = ap.mfi(bars, 14)
    rsi_l = ap.rsi(closes, 14)
    _, _, hist_l = ap.macd(closes)
    _, bb_mid, _, bb_std = ap.bollinger(closes, 20, 2)
    ema20_l = ap.ema(closes, 20)
    ema50_l = ap.ema(closes, 50)
    vol_avg20 = ap.sma(volumes, 20)
    sigma_l = [
        (closes[i] - bb_mid[i]) / bb_std[i]
        if bb_mid[i] is not None and bb_std[i] not in (None, 0) else None
        for i in range(len(bars))
    ]
    vol_ratio_l = [
        volumes[i] / vol_avg20[i] if vol_avg20[i] not in (None, 0) else None
        for i in range(len(bars))
    ]
    return {
        "closes": closes, "opens": opens, "mfi": mfi_l, "rsi": rsi_l, "hist": hist_l,
        "ema20": ema20_l, "ema50": ema50_l, "sigma": sigma_l, "vol_ratio": vol_ratio_l,
    }


def fp_scan_AICL(n, s):
    out = set()
    for i in range(n):
        if s["sigma"][i] is None or s["sigma"][i] > -2.0:
            continue
        for k in range(i + 1, min(i + 5, n - 1) + 1):
            if s["vol_ratio"][k] is not None and s["vol_ratio"][k] >= 5.0 and _cross_up_list(s["mfi"], k, 70):
                out.add(k)
    return out


def fp_scan_THCCL(n, s):
    out = set()
    for i in range(9, n):
        window = [v for v in s["mfi"][i - 9:i + 1] if v is not None]
        if s["mfi"][i] is None or s["mfi"][i] > 55 or not window or max(window) < 80:
            continue
        for k in range(i + 1, min(i + 5, n - 1) + 1):
            if s["vol_ratio"][k] is not None and s["vol_ratio"][k] >= 3.0 and s["sigma"][k] is not None and s["sigma"][k] >= 1.5:
                out.add(k)
    return out


def fp_scan_MDTL(n, s):
    out = set()
    for i in range(n):
        if s["sigma"][i] is None or s["sigma"][i] > -1.5:
            continue
        for k in range(i + 1, min(i + 3, n - 1) + 1):
            if s["vol_ratio"][k] is not None and s["vol_ratio"][k] >= 5.0 and _cross_up_list(s["mfi"], k, 75):
                out.add(k)
    return out


def fp_scan_FPJM(n, s):
    out = set()
    for i in range(5, n):
        prior = s["mfi"][i - 5:i]
        if any(v is None or v < 25 or v > 35 for v in prior):
            continue
        if s["vol_ratio"][i] is None or s["vol_ratio"][i] < 2.5:
            continue
        if s["sigma"][i] is None or s["sigma"][i - 1] is None:
            continue
        if s["sigma"][i] >= 1.0 and s["sigma"][i - 1] < 1.0:
            out.add(i)
    return out


def fp_scan_DSIL(n, s):
    out = set()
    for t0 in range(1, n - 19):
        hits = 0
        for k in range(t0, min(t0 + 10, n)):
            cond_vol = s["vol_ratio"][k] is not None and s["vol_ratio"][k] >= 2.0
            cond_macd = s["hist"][k] is not None and s["hist"][k - 1] is not None and s["hist"][k] > 0 and s["hist"][k - 1] <= 0
            cond_gold = (s["ema20"][k] is not None and s["ema50"][k] is not None and
                         s["ema20"][k - 1] is not None and s["ema50"][k - 1] is not None and
                         s["ema20"][k] > s["ema50"][k] and s["ema20"][k - 1] <= s["ema50"][k - 1])
            cond_bull = s["closes"][k] > s["opens"][k]
            hits += sum([cond_vol, cond_macd, cond_gold, cond_bull])
        if hits < 3:
            continue
        for k in range(t0 + 10, min(t0 + 20, n)):
            if s["vol_ratio"][k] is not None and s["vol_ratio"][k] >= 4.0:
                out.add(k)
    return out


def fp_scan_SYM(n, s):
    out = set()
    for i in range(n):
        if s["vol_ratio"][i] is None or s["vol_ratio"][i] < 6.0:
            continue
        lo, lo_idx = None, None
        for j in range(i + 1, min(i + 10, n - 1) + 1):
            if lo is None or s["closes"][j] < lo:
                lo, lo_idx = s["closes"][j], j
        if lo_idx is None:
            continue
        for k in range(lo_idx + 1, min(lo_idx + 10, n - 1) + 1):
            if s["hist"][k] is not None and s["hist"][k - 1] is not None and s["hist"][k] > 0 and s["hist"][k - 1] <= 0:
                out.add(k)
    return out


def fp_scan_PREMA(n, s):
    out = set()
    for i in range(n):
        if s["sigma"][i] is None or s["sigma"][i] > -2.0:
            continue
        v_idx = None
        for v in range(i + 1, min(i + 20, n - 1) + 1):
            if s["vol_ratio"][v] is not None and s["vol_ratio"][v] >= 3.0:
                v_idx = v
                break
        if v_idx is None:
            continue
        for k in range(v_idx, min(i + 20, n - 1) + 1):
            if (s["ema20"][k] is not None and s["ema50"][k] is not None and
                    s["ema20"][k - 1] is not None and s["ema50"][k - 1] is not None and
                    s["ema20"][k] > s["ema50"][k] and s["ema20"][k - 1] <= s["ema50"][k - 1]):
                out.add(k)
    return out


def fp_scan_JSBL(n, s):
    out = set()
    for i in range(n):
        if not _cross_up_list([-v if v is not None else None for v in s["mfi"]], i, -10):
            continue
        for k in range(i + 1, min(i + 10, n - 1) + 1):
            if (s["vol_ratio"][k] is not None and s["vol_ratio"][k] >= 2.5 and
                    s["hist"][k] is not None and s["hist"][k - 1] is not None and
                    s["hist"][k] > 0 and s["hist"][k - 1] <= 0):
                out.add(k)
    return out


def fp_scan_ILP(n, s):
    out = set()
    for i in range(n):
        if s["sigma"][i] is None or s["sigma"][i] > -1.5:
            continue
        v_idx = None
        for v in range(i + 1, min(i + 3, n - 1) + 1):
            if s["vol_ratio"][v] is not None and s["vol_ratio"][v] >= 8.0:
                v_idx = v
                break
        if v_idx is None:
            continue
        for k in range(v_idx + 1, min(v_idx + 20, n - 1) + 1):
            if _cross_up_list(s["rsi"], k, 75):
                out.add(k)
    return out


FP_SCANNERS = {
    "FP_AICL": ("AICL", fp_scan_AICL), "FP_THCCL": ("THCCL", fp_scan_THCCL),
    "FP_MDTL": ("MDTL", fp_scan_MDTL), "FP_FPJM": ("FPJM", fp_scan_FPJM),
    "FP_DSIL": ("DSIL", fp_scan_DSIL), "FP_SYM": ("SYM", fp_scan_SYM),
    "FP_PREMA": ("PREMA", fp_scan_PREMA), "FP_JSBL": ("JSBL", fp_scan_JSBL),
    "FP_ILP": ("ILP", fp_scan_ILP),
}


def main():
    now = datetime.now(timezone.utc)
    end_date = now.date()
    start_date = end_date - timedelta(days=365)
    window_str = f"{start_date.isoformat()} to {end_date.isoformat()}"

    universe = load_universe()

    # ---- single precompute pass over the whole universe, reused by both tasks
    per_ticker = {}
    liq_values = {}
    for sym, bars in universe.items():
        if len(bars) < 21:
            continue
        g = pd.DataFrame(bars)
        signals = _compute_signals(g)
        atr14 = ap.atr(bars, 14)
        fp_series = compute_fp_series(bars)
        per_ticker[sym] = {"bars": bars, "signals": signals, "atr14": atr14, "fp": fp_series}

        last20 = bars[-20:]
        if len(last20) == 20:
            avg_vol = sum(b["volume"] for b in last20) / 20
            avg_close = sum(b["close"] for b in last20) / 20
            liq_values[sym] = avg_vol * avg_close

    # ---- liquidity terciles
    ranked = sorted(liq_values.items(), key=lambda kv: kv[1])
    n_tot = len(ranked)
    cut1 = n_tot // 3
    cut2 = (2 * n_tot) // 3
    tier_of = {}
    for idx, (sym, _) in enumerate(ranked):
        tier_of[sym] = "A" if idx < cut1 else ("B" if idx < cut2 else "C")
    boundary_low_high = ranked[cut1 - 1][1] if cut1 > 0 else None
    boundary_mid_high = ranked[cut2 - 1][1] if cut2 > 0 else None
    tier_counts = {"A": cut1, "B": cut2 - cut1, "C": n_tot - cut2}

    # ================================================================ TASK 1
    task1_rows = []
    for indicator in TOP8:
        for tier in ("A", "B", "C"):
            records_label = []
            for sym, tier_sym in tier_of.items():
                if tier_sym != tier:
                    continue
                pt = per_ticker[sym]
                bars, atr14 = pt["bars"], pt["atr14"]
                sig_bool = pt["signals"][indicator]
                for i in range(len(bars)):
                    if not bool(sig_bool.iloc[i]):
                        continue
                    trig_date = bars[i]["date"]
                    if not (start_date.isoformat() <= trig_date <= end_date.isoformat()):
                        continue
                    if atr14[i] is None:
                        continue
                    if i + MAX_HOLD >= len(bars):
                        continue
                    label, _, _ = label_trigger(bars, i, atr14[i])
                    records_label.append(label)
            n = len(records_label)
            n_pos = sum(1 for l in records_label if l == 1)
            verdict, precision, ci_low, ci_high = evaluate_verdict(n, n_pos)
            task1_rows.append({
                "indicator": indicator, "tier": tier, "n": n, "n_pos": n_pos,
                "n_neg": sum(1 for l in records_label if l == -1),
                "n_zero": sum(1 for l in records_label if l == 0),
                "precision": precision, "ci_low": ci_low, "ci_high": ci_high, "verdict": verdict,
            })

    # ================================================================ TASK 2
    task2_rows = []
    for fp_name, (source_sym, scanner) in FP_SCANNERS.items():
        excl_start, excl_end = FP_EXCLUDE_WINDOWS[source_sym]
        for tier in ("A", "B", "C"):
            records_label = []
            for sym, tier_sym in tier_of.items():
                if tier_sym != tier:
                    continue
                pt = per_ticker[sym]
                bars, atr14, fp_s = pt["bars"], pt["atr14"], pt["fp"]
                n_bars = len(bars)
                match_idx = scanner(n_bars, fp_s)
                for i in match_idx:
                    trig_date = bars[i]["date"]
                    if not (start_date.isoformat() <= trig_date <= end_date.isoformat()):
                        continue
                    if sym == source_sym and excl_start <= trig_date <= excl_end:
                        continue
                    if atr14[i] is None:
                        continue
                    if i + MAX_HOLD >= n_bars:
                        continue
                    label, _, _ = label_trigger(bars, i, atr14[i])
                    records_label.append(label)
            n = len(records_label)
            n_pos = sum(1 for l in records_label if l == 1)
            verdict, precision, ci_low, ci_high = evaluate_verdict_fp(n, n_pos)
            task2_rows.append({
                "fingerprint": fp_name, "source_stock": source_sym, "tier": tier,
                "n": n, "n_pos": n_pos, "n_neg": sum(1 for l in records_label if l == -1),
                "n_zero": sum(1 for l in records_label if l == 0),
                "precision": precision, "ci_low": ci_low, "ci_high": ci_high, "verdict": verdict,
            })

    # ================================================================ report
    lines = []
    lines.append("# Liquidity-Stratified Re-Test — Top-8 Indicators + 9 New Fingerprints")
    lines.append("")
    lines.append(f"**Run date (UTC):** {now.isoformat()}")
    lines.append(f"**Holdout window:** {window_str} (mechanical, execution-date-derived, identical to the prior sweep)")
    lines.append("")
    lines.append("## Liquidity tiers")
    lines.append("")
    lines.append(f"Trailing 20-day average traded value = avg(volume) x avg(close) over each ticker's own "
                 f"last 20 available bars, computed once per ticker. Universe: {n_tot} tickers with >=20 bars "
                 f"(of {len(universe)} total tickers loaded).")
    lines.append("")
    lines.append(f"- **Tier A (least liquid third):** {tier_counts['A']} tickers, "
                 f"traded value <= {boundary_low_high:,.0f}" if boundary_low_high is not None else f"- **Tier A:** {tier_counts['A']} tickers")
    lines.append(f"- **Tier B (middle third):** {tier_counts['B']} tickers, "
                 f"traded value in ({boundary_low_high:,.0f}, {boundary_mid_high:,.0f}]" if boundary_low_high is not None and boundary_mid_high is not None else f"- **Tier B:** {tier_counts['B']} tickers")
    lines.append(f"- **Tier C (most liquid third):** {tier_counts['C']} tickers, "
                 f"traded value > {boundary_mid_high:,.0f}" if boundary_mid_high is not None else f"- **Tier C:** {tier_counts['C']} tickers")
    lines.append("")

    lines.append("## Task 1 — Top 8 indicators x 3 liquidity tiers")
    lines.append("")
    lines.append("Method identical to analysis/phase1_all26_sweep.py: upper barrier = entry close + "
                 "2.0xATR(14); lower barrier = entry close - 1.5xATR(14); vertical barrier = 15 trading "
                 "days; same-day double-touch resolves to the lower barrier; n>=150 required or "
                 "INCONCLUSIVE; PASS only if Wilson 95% CI lower bound on +1-class precision > 50.0%.")
    lines.append("")
    lines.append("| Indicator | Tier | n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in task1_rows:
        prec_s = f"{r['precision']:.2f}%" if r["precision"] is not None else "—"
        ci_s = f"[{r['ci_low']:.2f}%, {r['ci_high']:.2f}%]" if r["ci_low"] is not None else "—"
        lines.append(f"| {r['indicator']} | {r['tier']} | {r['n']} | {r['n_pos']} | {r['n_neg']} | "
                     f"{r['n_zero']} | {prec_s} | {ci_s} | {r['verdict']} |")
    lines.append("")

    lines.append("## Task 2 — 9 new fingerprints x 3 liquidity tiers")
    lines.append("")
    lines.append("Each fingerprint's exact trigger definition (derived from that stock's own documented "
                 "pre-move numbers in analysis/AICL_SHFA_premove_study.md, reused as the scan template from "
                 "backend/run_fingerprint_scan.py's SHFA/FNEL approach):")
    lines.append("")
    for fp_name, defn in FP_DEFINITIONS.items():
        lines.append(f"- **{fp_name}** (source: {FP_SCANNERS[fp_name][0]}): {defn}")
    lines.append("")
    lines.append(f"n>={FP_FLOOR} required per cell or reported as \"TOO FEW MATCHES\"; each stock's own "
                 f"documented report window is excluded when scanning that stock itself. Same Wilson 95% "
                 f"CI / >50.0% lower-bound PASS rule.")
    lines.append("")
    lines.append("| Fingerprint | Source stock | Tier | n | +1 | -1 | 0 | Precision | Wilson 95% CI | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in task2_rows:
        prec_s = f"{r['precision']:.2f}%" if r["precision"] is not None else "—"
        ci_s = f"[{r['ci_low']:.2f}%, {r['ci_high']:.2f}%]" if r["ci_low"] is not None else "—"
        lines.append(f"| {r['fingerprint']} | {r['source_stock']} | {r['tier']} | {r['n']} | {r['n_pos']} | "
                     f"{r['n_neg']} | {r['n_zero']} | {prec_s} | {ci_s} | {r['verdict']} |")
    lines.append("")

    n_pass_1 = sum(1 for r in task1_rows if r["verdict"].startswith("PASS"))
    n_pass_2 = sum(1 for r in task2_rows if r["verdict"].startswith("PASS"))
    lines.append("## Summary")
    lines.append("")
    lines.append(f"Task 1: {len(task1_rows)} cells (8 indicators x 3 tiers), {n_pass_1} PASS. "
                 f"Task 2: {len(task2_rows)} cells (9 fingerprints x 3 tiers), {n_pass_2} PASS. "
                 f"Combined: {n_pass_1 + n_pass_2} PASS out of {len(task1_rows) + len(task2_rows)} cells.")
    lines.append("")
    lines.append("**Multiple-testing note:** 51 total cells were tested in this single pass. A lone PASS "
                 "among 51 tests at the 95% confidence level is not, on its own, a discovery -- roughly 1 in "
                 "20 tests is expected to cross the 50% CI-lower-bound threshold by chance alone even with "
                 "zero true edge. Only a CLUSTER of related PASSes (e.g. the same indicator or fingerprint "
                 "passing across multiple tiers, or several fingerprints from economically related tiers "
                 "passing together) would be worth a second, independent look -- not a single isolated cell.")
    lines.append("")
    lines.append("Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run for any cell in this task, regardless "
                 "of verdict.")
    lines.append("")

    report_md = "\n".join(lines)
    out_path = Path(__file__).parent / "liquidity_stratified_results.md"
    out_path.write_text(report_md)

    summary = {
        "window": window_str, "n_universe": n_tot,
        "tier_counts": tier_counts,
        "boundary_low_high": boundary_low_high, "boundary_mid_high": boundary_mid_high,
        "task1_rows": task1_rows, "task2_rows": task2_rows,
        "n_pass_task1": n_pass_1, "n_pass_task2": n_pass_2,
    }
    print("===JSON_START===")
    print(json.dumps(summary, separators=(",", ":")))
    print("===JSON_END===")
    print("===REPORT_MD_START===")
    print(report_md)
    print("===REPORT_MD_END===")


if __name__ == "__main__":
    main()
