#!/usr/bin/env python3
"""Phase 1a, Step 3: false-positive baseline for backend/vcp_detector.py.

Runs detect_vcp() on 50 stocks NOT among the 11 known-move stocks tested
in vcp_phase1a_test.py, sampled deterministically (fixed seed=42) from
backend/app.py's own WATCHLIST_SYMBOLS. Each stock's own most recent ~126
trading days (~6 calendar months) of daily_ohlc is scanned in one
detect_vcp() call (lookback_days=126) -- min_contractions and
volume_threshold are kept at their exact defaults (2 and 1.5), per the
task's "same parameters" instruction; only lookback_days changes, to
actually span 6 months instead of 60 days, and that deviation is called
out explicitly here and in the final report rather than silently reusing
60.

Requires real daily_ohlc access via backend/turso_db.py (LIBSQL_URL /
LIBSQL_AUTH_TOKEN secrets) -- this sandbox can't reach that DB directly,
so this script runs in GitHub Actions
(.github/workflows/vcp_phase1a_baseline.yml), the same constraint and
pattern already used by analysis/phase1_triple_barrier_test.py and
analysis/phase1_all26_sweep.py.

Single pass, no iteration: writes analysis/vcp_50stock_results.json.
"""
import json
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from vcp_detector import detect_vcp, random_watchlist_sample, _bars_from_db

KNOWN_11 = {"AICL", "SHFA", "THCCL", "FNEL", "MDTL", "FPJM", "DSIL", "SYM", "PREMA", "JSBL", "ILP"}
BASELINE_LOOKBACK_DAYS = 126  # ~6 trading months; see module docstring
SAMPLE_SIZE = 50
SAMPLE_SEED = 42
OUT_PATH = str(Path(__file__).parent / "vcp_50stock_results.json")


def main():
    sample = random_watchlist_sample(KNOWN_11, n=SAMPLE_SIZE, seed=SAMPLE_SEED)
    out = {"sample_seed": SAMPLE_SEED, "sample_size_requested": SAMPLE_SIZE,
           "lookback_days": BASELINE_LOOKBACK_DAYS, "stocks": {}}

    for ticker in sample:
        try:
            bars = _bars_from_db(ticker)
        except Exception as exc:
            out["stocks"][ticker] = {"error": str(exc)}
            continue
        if not bars:
            out["stocks"][ticker] = {"error": "zero rows returned"}
            continue
        vcps = detect_vcp(ticker, lookback_days=BASELINE_LOOKBACK_DAYS, bars=bars)
        scores = [v["overall_vcp_quality_score"] for v in vcps]
        textbook = [v for v in vcps if v["is_textbook_vcp"]]
        out["stocks"][ticker] = {
            "num_bars_available": len(bars),
            "num_vcp_found": len(vcps),
            "avg_vcp_quality_score": round(sum(scores) / len(scores), 2) if scores else None,
            "pct_textbook_vcps": round(100 * len(textbook) / len(vcps), 1) if vcps else None,
            "vcps": vcps,
        }

    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    ok = {k: v for k, v in out["stocks"].items() if "error" not in v}
    counts = [v["num_vcp_found"] for v in ok.values()]
    print(f"Wrote {OUT_PATH}")
    print(f"Sampled {len(sample)} stocks, {len(ok)} loaded successfully, {len(out['stocks']) - len(ok)} errored.")
    if counts:
        zero = sum(1 for c in counts if c == 0)
        one = sum(1 for c in counts if c == 1)
        two_plus = sum(1 for c in counts if c >= 2)
        print(f"VCP count distribution: 0 VCPs: {zero}, 1 VCP: {one}, 2+ VCPs: {two_plus}")
        print(f"Average VCPs per stock: {sum(counts) / len(counts):.2f}")


if __name__ == "__main__":
    main()
