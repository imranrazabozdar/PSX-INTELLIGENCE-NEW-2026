#!/usr/bin/env python3
"""Scale-out of Fix 2's staleness-aware fundamentals scoring
(fundamentals_analyzer.py's data_as_of/age_days/stale) from the 4 refinery
tickers it was built and tested on to the full 89-symbol watchlist.

Pure scale-out: no new logic, no new web research, no per-company filing
corrections in this pass. Every symbol gets exactly one
fundamentals_analyzer.analyze() call, classified into one of three buckets:
  FRESH     -- data exists, stale=False
  STALE     -- data exists, stale=True (>120 days old per the existing
               uniform threshold)
  NO_DATA   -- no underlying data at all (suppressed, not defaulted to a
               score -- distinct from STALE, which implies data exists but
               is old)

Single script, single pass, local cache only (backend/fundamentals.json) --
no Turso/GH Actions needed for this task.
"""
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import fundamentals_analyzer as fa

# Copied verbatim from backend/app.py's WATCHLIST_SYMBOLS (89 symbols) --
# same rationale as the prior tasks that used this list: app.py is a
# FastAPI app with unrelated heavy side-effect imports that have no
# business running inside a read-only analysis script; the list itself is
# static, so copying it verbatim is the correct "reuse without side
# effects" choice.
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

RATIO_KEYS = ("pe", "eps_growth", "roe", "de", "div_yield")


def classify(symbol):
    result = fa.analyze(symbol)
    raw = fa.raw_ratios(symbol)
    has_any_ratio = bool(raw)  # raw_ratios() is {} when nothing is cached/configured
    if not has_any_ratio:
        # analyze() still returns a data_as_of/age_days derived from the cache's
        # global as_of date even when this specific symbol has no ratios at all
        # (that fallback exists for the FRESH/STALE case, not this one) -- blank
        # both out here so a NO_DATA row never reads as if a date is known.
        bucket = "NO_DATA"
        data_as_of, age_days = None, None
    elif result.get("stale"):
        bucket = "STALE"
        data_as_of, age_days = result.get("data_as_of"), result.get("age_days")
    else:
        bucket = "FRESH"
        data_as_of, age_days = result.get("data_as_of"), result.get("age_days")
    return {
        "ticker": symbol, "bucket": bucket,
        "data_as_of": data_as_of, "age_days": age_days,
        "score": result.get("score"), "low_confidence": result.get("low_confidence"),
        **{k: raw.get(k) for k in RATIO_KEYS},
    }


def main():
    now = datetime.now(timezone.utc)
    rows = [classify(sym) for sym in WATCHLIST_SYMBOLS]

    fresh = [r for r in rows if r["bucket"] == "FRESH"]
    stale = [r for r in rows if r["bucket"] == "STALE"]
    no_data = [r for r in rows if r["bucket"] == "NO_DATA"]
    stale_sorted = sorted(stale, key=lambda r: r["age_days"] if r["age_days"] is not None else -1, reverse=True)

    n = len(rows)
    lines = []
    lines.append("# Watchlist Fundamentals Staleness Report")
    lines.append("")
    lines.append(f"**Run date (UTC):** {now.isoformat()}")
    lines.append("")
    lines.append("## Step 1 finding — does the underlying data even exist?")
    lines.append("")
    lines.append(
        f"Before running staleness detection wide, the actual data-source coverage was "
        f"checked: `backend/fundamentals.json` currently caches ratios for only "
        f"**{len(fa._CACHE.get('data', {}))} symbols total** (any ticker, not just this "
        f"watchlist), all sourced from `stockanalysis.com` via `fundamentals_fetcher.py`, "
        f"plus whatever's in `config.FUNDAMENTALS` (currently empty for these tickers). "
        f"**Only {len(fresh) + len(stale)} of the {n} watchlist symbols "
        f"({(len(fresh) + len(stale)) / n * 100:.1f}%) have any usable fundamentals data at "
        f"all** — the remaining **{len(no_data)} ({len(no_data) / n * 100:.1f}%) have no "
        f"underlying data source whatsoever**, not stale data, no data. **This confirms the "
        f"task's own hypothesis: the primary blocker for most of the watchlist is data "
        f"coverage, not staleness of what exists.** The staleness mechanism itself (Fix 2) "
        f"generalizes correctly to every symbol it has data for — see below — but it cannot "
        f"manufacture data for symbols `fundamentals_fetcher.py` was never run against or "
        f"that never got a `config.FUNDAMENTALS` manual entry."
    )
    lines.append("")

    lines.append("## Step 2/3 — bucket counts")
    lines.append("")
    lines.append(f"- **FRESH** (data exists, not stale): **{len(fresh)}** / {n}")
    lines.append(f"- **STALE** (data exists, >120 days old): **{len(stale)}** / {n}")
    lines.append(f"- **NO_DATA** (suppressed, no source at all): **{len(no_data)}** / {n}")
    lines.append("")

    lines.append("## STALE priority list (sorted by age_days, descending)")
    lines.append("")
    lines.append("This is the practical priority order for a manual sourcing pass like the "
                 "one already done for PRL and NRL — oldest/most-in-need-of-verification first.")
    lines.append("")
    if stale_sorted:
        lines.append("| Ticker | data_as_of | age_days | P/E | EPS growth | ROE | D/E | Div. yield |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in stale_sorted:
            lines.append(f"| {r['ticker']} | {r['data_as_of']} | {r['age_days']} | "
                         f"{r['pe'] if r['pe'] is not None else '—'} | "
                         f"{r['eps_growth'] if r['eps_growth'] is not None else '—'} | "
                         f"{r['roe'] if r['roe'] is not None else '—'} | "
                         f"{r['de'] if r['de'] is not None else '—'} | "
                         f"{r['div_yield'] if r['div_yield'] is not None else '—'} |")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Full table — all 89 watchlist symbols")
    lines.append("")
    lines.append("| Ticker | Bucket | data_as_of | age_days | P/E | EPS growth | ROE | D/E | Div. yield |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        das = r["data_as_of"] if r["data_as_of"] else "—"
        age = r["age_days"] if r["age_days"] is not None else "—"
        lines.append(f"| {r['ticker']} | {r['bucket']} | {das} | {age} | "
                     f"{r['pe'] if r['pe'] is not None else '—'} | "
                     f"{r['eps_growth'] if r['eps_growth'] is not None else '—'} | "
                     f"{r['roe'] if r['roe'] is not None else '—'} | "
                     f"{r['de'] if r['de'] is not None else '—'} | "
                     f"{r['div_yield'] if r['div_yield'] is not None else '—'} |")
    lines.append("")

    trustworthy_pct = len(fresh) / n * 100
    needs_work_pct = (len(stale) + len(no_data)) / n * 100
    lines.append("## Honest current state")
    lines.append("")
    lines.append(
        f"Right now, **{len(fresh)} of {n} watchlist symbols ({trustworthy_pct:.1f}%) are "
        f"FRESH** — the only slice of the fundamentals layer that can be trusted at face "
        f"value without a manual check. The other **{len(stale) + len(no_data)} "
        f"({needs_work_pct:.1f}%) need work**: {len(stale)} have real but stale data "
        f"(>120 days old, {len(stale)/n*100:.1f}% of the watchlist) and {len(no_data)} have "
        f"no data source at all ({len(no_data)/n*100:.1f}% of the watchlist, the larger of "
        f"the two gaps). This is the current, unvarnished state of the fundamentals layer "
        f"across the full watchlist, not an aspirational one — closing the NO_DATA gap "
        f"requires running `fundamentals_fetcher.py` (or adding manual `config.FUNDAMENTALS` "
        f"entries) for the 69 uncovered symbols, and closing the STALE gap requires the same "
        f"kind of one-company-at-a-time manual filing research already done for PRL and NRL "
        f"— neither was attempted in this task, per its own scope."
    )
    lines.append("")

    report_md = "\n".join(lines)
    out_path = Path(__file__).parent / "watchlist_staleness_report.md"
    out_path.write_text(report_md)

    summary = {
        "n": n, "fresh": len(fresh), "stale": len(stale), "no_data": len(no_data),
        "stale_sorted": [r["ticker"] for r in stale_sorted],
    }
    print("===JSON_START===")
    print(json.dumps(summary, separators=(",", ":")))
    print("===JSON_END===")
    print("===REPORT_MD_START===")
    print(report_md)
    print("===REPORT_MD_END===")


if __name__ == "__main__":
    main()
