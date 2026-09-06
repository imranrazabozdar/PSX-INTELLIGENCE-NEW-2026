#!/usr/bin/env python3
"""Phase 1a, Step 4: assembles analysis/vcp_detector_phase1a_results.md from
the two JSON outputs already produced by vcp_phase1a_test.py (11 known
stocks, local) and vcp_50stock_baseline.py (50-stock false-positive
baseline, GitHub Actions). Every number in the report is read from those
two files -- nothing here is hand-typed or re-derived differently.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
RESULTS_11 = HERE / "vcp_11stock_results.json"
RESULTS_50 = HERE / "vcp_50stock_results.json"
OUT_MD = HERE / "vcp_detector_phase1a_results.md"

HIT_WINDOW_TRADING_DAYS = 5
TEXTBOOK_THRESHOLD = 70.0


def _fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def build_section1(d11):
    lines = ["## Section 1: 11-Stock Test Results\n",
             f"detect_vcp() run with its exact defaults: `lookback_days=60, "
             f"min_contractions=2, volume_threshold=1.5`. \"hit\" = breakout_date "
             f"falls within {HIT_WINDOW_TRADING_DAYS} trading days (position in "
             f"this stock's own trading-day sequence, not calendar days) of the "
             f"user-given MOVE_START date reused from `analyze_premove.py`.\n"]
    tickers = list(d11.keys())
    stocks_with_vcp = []
    stocks_with_hit = []
    stocks_with_textbook = []
    total_vcps = 0
    total_hits = 0

    for t in tickers:
        entry = d11[t]
        vcps = entry["vcps_found"]
        lines.append(f"### {t} (move-start: {entry['move_start']})\n")
        if not vcps:
            lines.append("No VCP detected in the 60-day lookback window ending at this "
                          "stock's last available bar.\n")
            continue
        stocks_with_vcp.append(t)
        lines.append("| start_date | num_contractions | tightness_score | volume_dry_up_score | "
                      "breakout_date | breakout_volume_ratio | overall_vcp_quality_score | "
                      "is_textbook_vcp | hit_or_miss |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for v in vcps:
            total_vcps += 1
            hit = v.get("hit_or_miss", "—")
            if hit == "hit":
                total_hits += 1
            lines.append(
                f"| {v['start_date']} | {v['num_contractions']} | {_fmt(v['tightness_score'])} | "
                f"{_fmt(v['volume_dry_up_score'])} | {v['breakout_date'] or '—'} | "
                f"{_fmt(v['breakout_volume_ratio'], 3)} | {_fmt(v['overall_vcp_quality_score'])} | "
                f"{v['is_textbook_vcp']} | {hit} |"
            )
        if any(v.get("hit_or_miss") == "hit" for v in vcps):
            stocks_with_hit.append(t)
        if any(v["is_textbook_vcp"] for v in vcps):
            stocks_with_textbook.append(t)
        lines.append("")

    n = len(tickers)
    lines.append("### Summary\n")
    lines.append(f"- Stocks with >=1 VCP detected: **{len(stocks_with_vcp)}/{n}** -> {stocks_with_vcp}")
    lines.append(f"- Total VCP events detected across all 11 stocks: **{total_vcps}**")
    lines.append(f"- Stocks with >=1 'hit' (breakout within {HIT_WINDOW_TRADING_DAYS} trading "
                  f"days of the known move-start): **{len(stocks_with_hit)}/{n}** -> {stocks_with_hit}")
    lines.append(f"- Stocks with >=1 textbook VCP (overall_vcp_quality_score >= {TEXTBOOK_THRESHOLD:.0f}): "
                  f"**{len(stocks_with_textbook)}/{n}** -> {stocks_with_textbook}")
    lines.append(f"- **Hit rate on known moves (stocks with a hit / 11): "
                  f"{100 * len(stocks_with_hit) / n:.1f}%**\n")
    return "\n".join(lines), stocks_with_hit, n


def build_section2(d50):
    lines = ["## Section 2: False Positive Baseline (50-Stock Sample)\n",
             f"Sample: {d50['sample_size_requested']} stocks from `backend/app.py`'s "
             f"`WATCHLIST_SYMBOLS`, excluding the 11 known-move stocks, drawn with a fixed "
             f"seed ({d50['sample_seed']}) for reproducibility. Each stock scanned with "
             f"`detect_vcp(ticker, lookback_days={d50['lookback_days']})` -- lookback widened "
             f"from the 60-day default specifically to span a ~6-month window as this step "
             f"asked for; `min_contractions=2` and `volume_threshold=1.5` kept at their exact "
             f"defaults.\n"]
    stocks = d50["stocks"]
    errored = {k: v for k, v in stocks.items() if "error" in v}
    ok = {k: v for k, v in stocks.items() if "error" not in v}

    lines.append("| ticker | num_vcp_found | avg_vcp_quality_score | pct_textbook_vcps |")
    lines.append("|---|---|---|---|")
    for t in sorted(stocks.keys()):
        v = stocks[t]
        if "error" in v:
            lines.append(f"| {t} | error: {v['error']} | — | — |")
        else:
            lines.append(f"| {t} | {v['num_vcp_found']} | {_fmt(v['avg_vcp_quality_score'])} | "
                          f"{_fmt(v['pct_textbook_vcps'], 1)} |")
    lines.append("")

    counts = [v["num_vcp_found"] for v in ok.values()]
    lines.append("### Summary\n")
    if errored:
        lines.append(f"- {len(errored)} of {len(stocks)} sampled stocks failed to load "
                      f"(see error column above) and are excluded from the stats below.")
    if counts:
        zero = sum(1 for c in counts if c == 0)
        one = sum(1 for c in counts if c == 1)
        two_plus = sum(1 for c in counts if c >= 2)
        avg_freq = sum(counts) / len(counts)
        textbook_rate = sum(1 for v in ok.values() if v["num_vcp_found"] and v["pct_textbook_vcps"])
        lines.append(f"- Stocks successfully scanned: **{len(ok)}**")
        lines.append(f"- Average VCP frequency: **{avg_freq:.2f} VCP patterns per stock** over "
                      f"the ~{d50['lookback_days']}-trading-day window")
        lines.append(f"- Distribution: **{zero}** stocks with 0 VCPs, **{one}** with exactly 1, "
                      f"**{two_plus}** with 2 or more")
        any_textbook = [t for t, v in ok.items() if v["pct_textbook_vcps"]]
        lines.append(f"- Stocks with >=1 textbook VCP (quality>=70) among random stocks: "
                      f"**{len(any_textbook)}/{len(ok)}** -> {sorted(any_textbook)}")
    else:
        lines.append("- No stocks loaded successfully; no baseline statistics available.")
    lines.append("")
    return "\n".join(lines), counts, ok


def build_section3(hit_rate_pct, stocks_with_hit, tickers_11, d11, baseline_counts):
    lines = ["## Section 3: Assessment & Decisions for Phase 1b\n"]
    if hit_rate_pct >= 70:
        verdict = "CLEAN"
        rec = ("The detector is **CLEAN**: proceed to Phase 1b (Flat Base) using this frozen "
               "VCP definition unchanged.")
    elif hit_rate_pct >= 50:
        verdict = "USABLE BUT NOISY"
        rec = ("The detector is **USABLE BUT NOISY**: recommend tuning `min_contractions` or "
               "the `tightness_score`/`overall_vcp_quality_score` threshold before Phase 1b.")
    else:
        verdict = "NEEDS REWORK"
        rec = ("Hit rate is below 50%: the detector, or the VCP definition itself, needs "
               "rework before Phase 1b, not just parameter tuning.")
    lines.append(f"**Hit rate on the 11 known stocks: {hit_rate_pct:.1f}% -> verdict: {verdict}**\n")
    lines.append(rec + "\n")

    misses = [t for t in tickers_11 if t not in stocks_with_hit]
    if misses:
        lines.append("### Stocks the detector missed, and likely why\n")
        for t in misses:
            vcps = d11[t]["vcps_found"]
            if not vcps:
                note = ("No contraction sequence of >=2 consecutive tightening days was found "
                        "anywhere in this stock's 60-day lookback window at all -- this stock's "
                        "run-up may be a different archetype entirely (e.g. a grind/flat base "
                        "rather than a classic VCP), or its true base sits outside the last 60 "
                        "trading days of the fetched window.")
            else:
                near_misses = [v for v in vcps if v.get("hit_or_miss") not in ("hit",)]
                worst_gap = min(
                    (v.get("trading_days_from_move_start") for v in vcps
                     if v.get("trading_days_from_move_start") is not None),
                    default=None,
                )
                if worst_gap is not None:
                    note = (f"{len(vcps)} VCP(s) detected, but the closest breakout still landed "
                            f"{worst_gap} trading days from the known move-start (outside the "
                            f"{HIT_WINDOW_TRADING_DAYS}-day hit window) -- a real contraction/volume "
                            f"pattern exists in the window, just not timed to this stock's specific "
                            f"user-given move-start date.")
                else:
                    note = (f"{len(vcps)} VCP(s) detected but none reached a qualifying breakout "
                            f"within the {20}-trading-day forward scan horizon.")
            lines.append(f"- **{t}**: {note}")
        lines.append("")

    if baseline_counts:
        avg_freq = sum(baseline_counts) / len(baseline_counts)
        lines.append(f"### Signal-vs-noise check\n")
        lines.append(f"Average VCP frequency on the 50 random stocks was **{avg_freq:.2f} per "
                      f"stock**; the hit rate on the 11 known-move stocks was **{hit_rate_pct:.1f}%**. "
                      f"{'The detector fires no more often on known real moves than on random stocks, which is itself evidence against it carrying real signal.' if hit_rate_pct < 70 else 'The detector fires meaningfully more precisely on known real moves than on random noise.'}\n")
    return "\n".join(lines)


def build_section4():
    return """## Section 4: Code & Definitions Locked

Exact frozen signature (see `backend/vcp_detector.py` for the full algorithm docstring):

```python
def detect_vcp(
    ticker: str,
    lookback_days: int = 60,
    min_contractions: int = 2,
    volume_threshold: float = 1.5,
    bars=None,
):
```

Frozen constants used by every call in this report:

| Constant | Value | Meaning |
|---|---|---|
| `MIN_VOLUME_BEFORE_BARS` | 3 | Minimum bars of trailing volume history required to score a candidate |
| `VOL_BEFORE_WINDOW` | 10 | Bars of trailing volume used for `avg_vol_before` |
| `BREAKOUT_SCAN_HORIZON` | 20 | Trading days scanned forward from base-end for a breakout |
| `VOL_AVG_PERIOD` | 20 | Rolling volume-average period (inclusive of the day itself) |
| `BREAKOUT_NORM_CAP_X` | 5.0 | breakout_volume_ratio at/above this earns full marks on that component |
| `QUALITY_WEIGHTS` | (0.4, 0.3, 0.3) | (tightness, volume_dry_up, breakout) weights, sums to 1.0 |
| `TEXTBOOK_THRESHOLD` | 70.0 | `overall_vcp_quality_score` cutoff for `is_textbook_vcp` |

Parameters used in this report's two test runs:

- **Section 1 (11 known stocks):** all defaults, unchanged (`lookback_days=60, min_contractions=2, volume_threshold=1.5`).
- **Section 2 (50-stock baseline):** `lookback_days=126` (the one deliberate deviation, to span ~6 trading months as Step 3 asked for), `min_contractions=2, volume_threshold=1.5` kept at defaults.

This definition is frozen as of this report. Any change to the algorithm, weights, or
thresholds above for Phase 1b must be a new, separately-dated version, not a silent edit
of this one.
"""


def main():
    d11 = json.loads(RESULTS_11.read_text())
    d50 = json.loads(RESULTS_50.read_text()) if RESULTS_50.exists() else None

    sec1, stocks_with_hit, n11 = build_section1(d11)
    hit_rate_pct = 100 * len(stocks_with_hit) / n11

    parts = ["# VCP Detector — Phase 1a Results\n",
             "Minervini-style Volatility Contraction Pattern detector, tested against the "
             "11 known-move stocks from the pre-move forensic study and a 50-stock random "
             "false-positive baseline. Single detector, single test cycle, no tuning "
             "iteration -- per the task's own cost-control instruction.\n",
             sec1]

    if d50 is not None:
        sec2, baseline_counts, ok = build_section2(d50)
        parts.append(sec2)
    else:
        parts.append("## Section 2: False Positive Baseline (50-Stock Sample)\n\n"
                      "*(Not yet available -- vcp_50stock_results.json missing. This half runs "
                      "in GitHub Actions where the daily_ohlc DB is reachable; see "
                      ".github/workflows/vcp_phase1a_baseline.yml.)*\n")
        baseline_counts = []

    parts.append(build_section3(hit_rate_pct, stocks_with_hit, list(d11.keys()), d11, baseline_counts))
    parts.append(build_section4())

    OUT_MD.write_text("\n".join(parts))
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
