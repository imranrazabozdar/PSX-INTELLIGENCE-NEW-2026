#!/usr/bin/env python3
"""Phase 1b, single combined script: tests backend/flat_base_detector.py's
detect_flat_base() against the same 11 known-move stocks and the same
50-stock false-positive baseline methodology as Phase 1a's VCP test --
reusing, not reimplementing:
  - analyze_premove.py's MOVE_START (hit-window check)
  - vcp_detector.py's _bars_from_premove_json / _bars_from_db /
    random_watchlist_sample (identical data loaders and watchlist sample,
    same seed=42, so the 50-stock sample is the EXACT same 50 tickers
    Phase 1a already tested, not a new draw)
  - The same report shape (Sections 1-4) as
    analysis/vcp_detector_phase1a_results.md, for direct comparison.

One script instead of three (test / baseline / report-builder) per this
task's own "minimum token usage, no new test infrastructure" instruction.
Section 2 requires live daily_ohlc access (Turso) unavailable in this
sandbox; running locally still produces a complete Section 1 and a
placeholder Section 2, exactly like Phase 1a's local-then-Actions split --
running in GitHub Actions (with LIBSQL secrets) fills in Section 2 too.
"""
import json
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from flat_base_detector import detect_flat_base
from vcp_detector import _bars_from_premove_json, _bars_from_db, random_watchlist_sample
from analyze_premove import MOVE_START  # reused verbatim, not redefined

TICKERS = ["AICL", "SHFA", "THCCL", "FNEL", "MDTL", "FPJM", "DSIL", "SYM", "PREMA", "JSBL", "ILP"]
HIT_WINDOW_TRADING_DAYS = 5
TEXTBOOK_THRESHOLD = 70.0
BASELINE_LOOKBACK_DAYS = 126  # ~6 trading months, same as Phase 1a's VCP baseline
SAMPLE_SIZE = 50
SAMPLE_SEED = 42  # same seed as Phase 1a -> identical 50-ticker sample, not a new draw
OUT_MD = Path(__file__).parent / "flat_base_detector_phase1b_results.md"


def _trading_day_distance(bars, date_a, date_b):
    dates = sorted(b["date"] for b in bars)
    if date_a not in dates or date_b not in dates:
        return None
    return abs(dates.index(date_a) - dates.index(date_b))


def _fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def run_section1():
    d11 = {}
    for ticker in TICKERS:
        bars = _bars_from_premove_json(ticker)
        fbs = detect_flat_base(ticker, df=bars)  # exact defaults
        move_start = MOVE_START.get(ticker)
        for fb in fbs:
            if fb["breakout_date"] is None:
                fb["hit_or_miss"] = "no_breakout_in_horizon"
                continue
            dist = _trading_day_distance(bars, fb["breakout_date"], move_start)
            if dist is None:
                fb["hit_or_miss"] = "move_start_date_not_in_window"
            else:
                fb["trading_days_from_move_start"] = dist
                fb["hit_or_miss"] = "hit" if dist <= HIT_WINDOW_TRADING_DAYS else "miss"
        d11[ticker] = {"move_start": move_start, "flat_bases_found": fbs}
    return d11


def run_section2():
    known_11 = set(TICKERS)
    sample = random_watchlist_sample(known_11, n=SAMPLE_SIZE, seed=SAMPLE_SEED)
    stocks = {}
    for ticker in sample:
        try:
            bars = _bars_from_db(ticker)
        except Exception as exc:
            stocks[ticker] = {"error": str(exc)}
            continue
        if not bars:
            stocks[ticker] = {"error": "zero rows returned"}
            continue
        fbs = detect_flat_base(ticker, df=bars, lookback_days=BASELINE_LOOKBACK_DAYS)
        scores = [f["overall_flat_base_quality_score"] for f in fbs]
        textbook = [f for f in fbs if f["is_textbook_flat_base"]]
        stocks[ticker] = {
            "num_bars_available": len(bars),
            "num_flat_base_found": len(fbs),
            "avg_flat_base_quality_score": round(sum(scores) / len(scores), 2) if scores else None,
            "pct_textbook_flat_bases": round(100 * len(textbook) / len(fbs), 1) if fbs else None,
        }
    return {"sample_seed": SAMPLE_SEED, "sample_size_requested": SAMPLE_SIZE,
            "lookback_days": BASELINE_LOOKBACK_DAYS, "stocks": stocks}


def build_report(d11, d50):
    lines = ["# Flat Base Detector — Phase 1b Results\n",
              "Flat/Tight Base detector, tested against the same 11 known-move stocks and "
              "the same 50-stock random false-positive baseline (identical seed=42 sample) "
              "as Phase 1a's VCP detector, for direct comparison. Single detector, single "
              "test cycle, no tuning iteration.\n",
              "## Section 1: 11-Stock Test Results\n",
              "detect_flat_base() run with its exact defaults: `min_days=12, max_days=35, "
              "max_range_pct=12.0, volume_contraction=0.75, volume_threshold=1.5, "
              "lookback_days=60`. \"hit\" = breakout_date falls within "
              f"{HIT_WINDOW_TRADING_DAYS} trading days of the user-given MOVE_START date.\n"]

    stocks_with_fb, stocks_with_hit, stocks_with_textbook, total_fb = [], [], [], 0
    for t in TICKERS:
        entry = d11[t]
        fbs = entry["flat_bases_found"]
        lines.append(f"### {t} (move-start: {entry['move_start']})\n")
        if not fbs:
            lines.append("No flat base detected in the 60-day lookback window.\n")
            continue
        stocks_with_fb.append(t)
        lines.append("| start_date | end_date | num_days | range_pct | volume_contraction_ratio | "
                      "breakout_date | breakout_volume_ratio | overall_flat_base_quality_score | "
                      "is_textbook_flat_base | hit_or_miss |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for fb in fbs:
            total_fb += 1
            hit = fb.get("hit_or_miss", "—")
            if hit == "hit":
                stocks_with_hit.append(t) if t not in stocks_with_hit else None
            lines.append(
                f"| {fb['start_date']} | {fb['end_date']} | {fb['num_days']} | "
                f"{_fmt(fb['range_pct'])} | {_fmt(fb['volume_contraction_ratio'], 3)} | "
                f"{fb['breakout_date'] or '—'} | {_fmt(fb['breakout_volume_ratio'], 3)} | "
                f"{_fmt(fb['overall_flat_base_quality_score'])} | {fb['is_textbook_flat_base']} | {hit} |"
            )
        if any(fb["is_textbook_flat_base"] for fb in fbs):
            stocks_with_textbook.append(t)
        lines.append("")

    n = len(TICKERS)
    hit_rate_pct = 100 * len(stocks_with_hit) / n
    lines.append("### Summary\n")
    lines.append(f"- Stocks with >=1 flat base detected: **{len(stocks_with_fb)}/{n}** -> {stocks_with_fb}")
    lines.append(f"- Total flat base events detected across all 11 stocks: **{total_fb}**")
    lines.append(f"- Stocks with >=1 'hit': **{len(stocks_with_hit)}/{n}** -> {stocks_with_hit}")
    lines.append(f"- Stocks with >=1 textbook flat base (quality >= {TEXTBOOK_THRESHOLD:.0f}): "
                  f"**{len(stocks_with_textbook)}/{n}** -> {stocks_with_textbook}")
    lines.append(f"- **Hit rate on known moves: {hit_rate_pct:.1f}%**\n")

    lines.append("## Section 2: False Positive Baseline (50-Stock Sample)\n")
    baseline_counts = []
    if d50 is not None:
        lines.append(f"Sample: same {d50['sample_size_requested']} stocks as Phase 1a's VCP "
                      f"baseline (seed={d50['sample_seed']}), scanned with "
                      f"`detect_flat_base(ticker, lookback_days={d50['lookback_days']})` -- "
                      f"other params at their exact defaults.\n")
        stocks = d50["stocks"]
        ok = {k: v for k, v in stocks.items() if "error" not in v}
        if not ok and stocks:
            lines.append(f"*(All {len(stocks)} sampled stocks failed to load -- e.g. "
                          f"`{next(iter(stocks.values()))['error']}` -- this environment can't "
                          f"reach the daily_ohlc DB. Run in GitHub Actions with LIBSQL secrets "
                          f"to populate this table.)*\n")
        else:
            lines.append("| ticker | num_flat_base_found | avg_flat_base_quality_score | pct_textbook_flat_bases |")
            lines.append("|---|---|---|---|")
            for t in sorted(stocks.keys()):
                v = stocks[t]
                if "error" in v:
                    lines.append(f"| {t} | error: {v['error']} | — | — |")
                else:
                    lines.append(f"| {t} | {v['num_flat_base_found']} | {_fmt(v['avg_flat_base_quality_score'])} | "
                                  f"{_fmt(v['pct_textbook_flat_bases'], 1)} |")
            lines.append("")
        baseline_counts = [v["num_flat_base_found"] for v in ok.values()]
        lines.append("### Summary\n")
        if baseline_counts:
            zero = sum(1 for c in baseline_counts if c == 0)
            one = sum(1 for c in baseline_counts if c == 1)
            two_plus = sum(1 for c in baseline_counts if c >= 2)
            avg_freq = sum(baseline_counts) / len(baseline_counts)
            any_textbook = [t for t, v in ok.items() if v["pct_textbook_flat_bases"]]
            lines.append(f"- Stocks successfully scanned: **{len(ok)}**")
            lines.append(f"- Average flat base frequency: **{avg_freq:.2f} per stock** over "
                          f"~{d50['lookback_days']} trading days")
            lines.append(f"- Distribution: **{zero}** with 0, **{one}** with exactly 1, **{two_plus}** with 2+")
            lines.append(f"- Stocks with >=1 textbook flat base among random stocks: "
                          f"**{len(any_textbook)}/{len(ok)}** -> {sorted(any_textbook)}")
        else:
            lines.append("- No stocks loaded successfully; no baseline statistics available.")
        lines.append("")
    else:
        lines.append("*(Not yet available -- this half needs live daily_ohlc access via Turso, "
                      "unreachable from this sandbox; run in GitHub Actions to fill this in.)*\n")

    lines.append("## Section 3: Assessment & Decisions for Phase 1c\n")
    if hit_rate_pct >= 70:
        verdict, rec = "CLEAN", "proceed to Phase 1c using this frozen definition unchanged."
    elif hit_rate_pct >= 50:
        verdict, rec = "USABLE BUT NOISY", "recommend tuning before Phase 1c."
    else:
        verdict, rec = "NEEDS REWORK", "the detector or definition needs rework before Phase 1c, not just tuning."
    lines.append(f"**Hit rate on the 11 known stocks: {hit_rate_pct:.1f}% -> verdict: {verdict}**\n")
    lines.append(f"The detector is **{verdict}**: {rec}\n")
    misses = [t for t in TICKERS if t not in stocks_with_hit]
    if misses:
        lines.append("### Stocks the detector missed, and likely why\n")
        for t in misses:
            fbs = d11[t]["flat_bases_found"]
            if not fbs:
                note = ("No 12-35 day window with range<=12% and volume contracted to <=75% of "
                        "its prior level was found anywhere in the 60-day lookback -- this "
                        "stock's pre-move structure isn't a flat/tight base by this definition.")
            else:
                gaps = [fb.get("trading_days_from_move_start") for fb in fbs
                        if fb.get("trading_days_from_move_start") is not None]
                if gaps:
                    note = (f"{len(fbs)} flat base(s) detected, but the closest breakout still "
                            f"landed {min(gaps)} trading days from the known move-start (outside "
                            f"the {HIT_WINDOW_TRADING_DAYS}-day hit window).")
                else:
                    note = f"{len(fbs)} flat base(s) detected but none reached a qualifying breakout in the scan horizon."
            lines.append(f"- **{t}**: {note}")
        lines.append("")
    if baseline_counts:
        avg_freq = sum(baseline_counts) / len(baseline_counts)
        lines.append("### Signal-vs-noise check\n")
        lines.append(f"Average flat base frequency on the 50 random stocks was **{avg_freq:.2f} per "
                      f"stock**; the hit rate on known moves was **{hit_rate_pct:.1f}%**. "
                      f"{'Firing no more often on known real moves than on random stocks is evidence against real signal.' if hit_rate_pct < 70 else 'The detector fires meaningfully more precisely on known real moves than on random noise.'}\n")

    lines.append("## Section 4: Code & Definitions Locked\n")
    lines.append("```python\n"
                  "def detect_flat_base(\n"
                  "    ticker: str,\n"
                  "    df: pd.DataFrame = None,\n"
                  "    min_days: int = 12,\n"
                  "    max_days: int = 35,\n"
                  "    max_range_pct: float = 12.0,\n"
                  "    volume_contraction: float = 0.75,\n"
                  "    volume_threshold: float = 1.5,\n"
                  "    lookback_days: int = 60,\n"
                  ") -> list:\n"
                  "```\n")
    lines.append("Reused, unchanged, from `backend/vcp_detector.py` (so Phase 1a/1b scores are on "
                  "the same scale): `MIN_VOLUME_BEFORE_BARS=3`, `VOL_BEFORE_WINDOW=10`, "
                  "`BREAKOUT_SCAN_HORIZON=20`, `VOL_AVG_PERIOD=20`, `BREAKOUT_NORM_CAP_X=5.0`, "
                  "`QUALITY_WEIGHTS=(0.4, 0.3, 0.3)`, `TEXTBOOK_THRESHOLD=70.0`.\n")
    lines.append("Section 2 sample: identical 50 tickers and seed (42) as Phase 1a's VCP "
                  "baseline; `lookback_days=126` there, other params at defaults.\n")
    return "\n".join(lines)


def main():
    d11 = run_section1()
    d50 = None
    try:
        d50 = run_section2()
    except Exception as exc:
        print(f"Section 2 (50-stock baseline) unavailable in this environment: {exc}")

    report = build_report(d11, d50)
    OUT_MD.write_text(report)
    print(f"Wrote {OUT_MD}")

    stocks_with_hit = [t for t in TICKERS if any(
        fb.get("hit_or_miss") == "hit" for fb in d11[t]["flat_bases_found"])]
    print(f"Hit rate: {len(stocks_with_hit)}/{len(TICKERS)} -> {stocks_with_hit}")


if __name__ == "__main__":
    main()
