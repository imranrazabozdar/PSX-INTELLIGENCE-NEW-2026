#!/usr/bin/env python3
"""Universe-wide, unsupervised fingerprint extraction and cross-matching
across the 89 WATCHLIST_SYMBOLS stocks (backend/app.py) -- every mechanically
detected >=15%/10-trading-day move each of these stocks has actually had,
not a hand-picked set.

Four pre-registered steps, single execution pass, no re-runs:

STEP 1 -- mechanical move detection: for each stock's full history, scan
left-to-right for any 10-trading-day window with close return >= +15%;
once flagged, skip past that window's end before continuing the scan (no
overlapping flags for the same stock).

STEP 2 -- fingerprint extraction: reuse analyze_premove.py's indicator
functions verbatim (rsi/mfi/macd/bollinger/ema/atr/obv/scan_patterns) to
build one 14-feature vector per detected move, computed over the 10
trading days immediately before the move's start.

STEP 3 -- K-means clustering (k=4..12, chosen by silhouette score) on the
z-scored feature vectors; report every cluster's composition and whether
it is one stock's own repeating behavior or genuinely cross-stock.

STEP 4 -- out-of-sample validation: for every cluster with >=15 members,
turn its centroid into a fingerprint (same style as the SHFA/FNEL and
liquidity-tier fingerprints already tested in this project) and scan the
SAME 89-stock universe's full history for additional matches, then check
whether forward returns actually beat 50% (Wilson 95% CI, n>=20 floor,
same pre-registered rule as every other test in this project).

Does NOT proceed to Phase 2/ML regardless of any cluster's result.
"""
import sys
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
_ANALYSIS_DIR = str(Path(__file__).parent)
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from statsmodels.stats.proportion import proportion_confint

import turso_db
import analyze_premove as ap

# Copied verbatim from backend/app.py's WATCHLIST_SYMBOLS (89 symbols).
# NOT imported from backend/app.py directly -- that module is a FastAPI
# app with heavy unrelated side-effect imports (dps_scraper, ai_overlay,
# volume_engine, etc.) that have no business running inside a read-only
# analysis script; the list itself is static, so copying it verbatim is
# the correct "reuse without side effects" choice.
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

MOVE_PCT = 0.15
MOVE_WINDOW = 10
MIN_ANCHOR_IDX = 100  # needs ATR-90-median + EMA50 + MACD history before it
FWD_HORIZONS = (5, 10, 20)
N_FLOOR = 20
MIN_CLUSTER_FOR_VALIDATION = 15

FEATURE_ORDER = [
    "rsi14", "mfi14", "macd_hist", "macd_dir", "atr_ratio_90",
    "obv_delta10_normvol", "ema20_50_rel", "bb_sigma", "vol_ratio20",
    "pat_bullish_engulfing", "pat_morning_star", "pat_hammer", "pat_doji", "pat_piercing_line",
]
BOOLEAN_FEATURES = {"pat_bullish_engulfing", "pat_morning_star", "pat_hammer", "pat_doji", "pat_piercing_line"}
PATTERN_NAME_OF = {
    "pat_bullish_engulfing": "Bullish Engulfing", "pat_morning_star": "Morning Star",
    "pat_hammer": "Hammer", "pat_doji": "Doji", "pat_piercing_line": "Piercing Line",
}


def load_universe():
    conn = turso_db.get_connection()
    universe = {}
    missing = []
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
        if len(bars) < MIN_ANCHOR_IDX + MOVE_WINDOW + max(FWD_HORIZONS) + 1:
            missing.append((sym, len(bars)))
        if bars:
            universe[sym] = bars
    return universe, missing


def _rolling_median(values, window):
    out = [None] * len(values)
    for i in range(len(values)):
        vals = [v for v in values[max(0, i - window + 1):i + 1] if v is not None]
        if len(vals) >= max(10, window // 3):
            out[i] = statistics.median(vals)
    return out


def precompute(bars):
    """One pass per ticker, reusing analyze_premove.py's functions
    verbatim. Reused unchanged by Step 2 (move-anchor snapshots) AND
    Step 4 (full-history out-of-sample scan) -- computed once."""
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]
    rsi_l = ap.rsi(closes, 14)
    mfi_l = ap.mfi(bars, 14)
    _, _, hist_l = ap.macd(closes)
    bb_upper, bb_mid, bb_lower, bb_std = ap.bollinger(closes, 20, 2)
    ema20_l = ap.ema(closes, 20)
    ema50_l = ap.ema(closes, 50)
    atr_l = ap.atr(bars, 14)
    obv_l = ap.obv(bars)
    vol_avg20 = ap.sma(volumes, 20)
    atr_median90 = _rolling_median(atr_l, 90)
    pattern_flags = ap.scan_patterns(bars)  # {date: [(name, criteria), ...]}
    patterns_by_idx = [set(name for name, _ in pattern_flags.get(b["date"], [])) for b in bars]
    return {
        "bars": bars, "closes": closes, "volumes": volumes, "rsi": rsi_l, "mfi": mfi_l,
        "hist": hist_l, "bb_mid": bb_mid, "bb_std": bb_std, "ema20": ema20_l, "ema50": ema50_l,
        "atr": atr_l, "obv": obv_l, "vol_avg20": vol_avg20, "atr_median90": atr_median90,
        "patterns": patterns_by_idx,
    }


def get_features(pc, i):
    n = len(pc["bars"])
    if i < MIN_ANCHOR_IDX or i < MOVE_WINDOW - 1 or i >= n:
        return None
    rsi_v, mfi_v = pc["rsi"][i], pc["mfi"][i]
    hist_v, hist_prev = pc["hist"][i], pc["hist"][i - 1]
    atr_v, atrmed_v = pc["atr"][i], pc["atr_median90"][i]
    ema20_v, ema50_v = pc["ema20"][i], pc["ema50"][i]
    bb_mid_v, bb_std_v = pc["bb_mid"][i], pc["bb_std"][i]
    vol_v, volavg_v = pc["volumes"][i], pc["vol_avg20"][i]
    obv_i, obv_i10 = pc["obv"][i], pc["obv"][i - (MOVE_WINDOW - 1)]
    close_v = pc["closes"][i]
    required = (rsi_v, mfi_v, hist_v, hist_prev, atr_v, atrmed_v, ema20_v, ema50_v,
                bb_mid_v, bb_std_v, vol_v, volavg_v, obv_i, obv_i10, close_v)
    if any(v is None for v in required):
        return None
    if bb_std_v == 0 or volavg_v in (None, 0) or atrmed_v in (None, 0) or close_v == 0:
        return None
    macd_dir = 1.0 if hist_v > hist_prev else (-1.0 if hist_v < hist_prev else 0.0)
    window_patterns = set()
    for j in range(i - (MOVE_WINDOW - 1), i + 1):
        window_patterns |= pc["patterns"][j]
    return {
        "rsi14": rsi_v, "mfi14": mfi_v, "macd_hist": hist_v, "macd_dir": macd_dir,
        "atr_ratio_90": atr_v / atrmed_v, "obv_delta10_normvol": (obv_i - obv_i10) / volavg_v,
        "ema20_50_rel": (ema20_v - ema50_v) / close_v, "bb_sigma": (close_v - bb_mid_v) / bb_std_v,
        "vol_ratio20": vol_v / volavg_v,
        "pat_bullish_engulfing": 1.0 if "Bullish Engulfing" in window_patterns else 0.0,
        "pat_morning_star": 1.0 if "Morning Star" in window_patterns else 0.0,
        "pat_hammer": 1.0 if "Hammer" in window_patterns else 0.0,
        "pat_doji": 1.0 if "Doji" in window_patterns else 0.0,
        "pat_piercing_line": 1.0 if "Piercing Line" in window_patterns else 0.0,
    }


def detect_moves(bars):
    """Mechanical, left-to-right, non-overlapping >=15%/10-day scan."""
    closes = [b["close"] for b in bars]
    n = len(bars)
    moves = []
    i = 0
    while i + MOVE_WINDOW < n:
        c0 = closes[i]
        if c0:
            pct = (closes[i + MOVE_WINDOW] - c0) / c0
            if pct >= MOVE_PCT:
                moves.append({"start_idx": i, "end_idx": i + MOVE_WINDOW, "magnitude": pct})
                i = i + MOVE_WINDOW + 1
                continue
        i += 1
    return moves


def evaluate_verdict_hits(n, n_hit):
    if n < N_FLOOR:
        return f"TOO FEW MATCHES (n={n}, floor={N_FLOOR})", None, None, None
    win_rate = n_hit / n
    ci_low, ci_high = proportion_confint(n_hit, n, alpha=0.05, method="wilson")
    ci_low_pct, ci_high_pct = ci_low * 100, ci_high * 100
    if ci_low_pct > 50.0:
        verdict = "PASS — statistically significant edge, proceed to Phase 2 eligibility"
    else:
        verdict = ("FAIL — indistinguishable from noise, Phase 2 is KILLED, do not run Phase 2 "
                   "under any circumstance regardless of how close the result was")
    return verdict, win_rate * 100, ci_low_pct, ci_high_pct


def main():
    now = datetime.now(timezone.utc)
    universe, missing = load_universe()
    per_ticker = {sym: precompute(bars) for sym, bars in universe.items()}

    # ================================================================ STEP 1+2
    all_moves = []           # every mechanically-detected move (Step 1 total)
    fingerprinted = []       # subset with a usable pre-move feature vector
    for sym, bars in universe.items():
        moves = detect_moves(bars)
        for mv in moves:
            all_moves.append({"ticker": sym, **mv})
            anchor = mv["start_idx"] - 1
            feat = get_features(per_ticker[sym], anchor)
            if feat is None:
                continue
            fingerprinted.append({
                "ticker": sym, "move_start_date": bars[mv["start_idx"]]["date"],
                "anchor_idx": anchor, "magnitude": mv["magnitude"], "features": feat,
            })

    total_moves_step1 = len(all_moves)

    # ================================================================ STEP 3
    X_raw = np.array([[m["features"][f] for f in FEATURE_ORDER] for m in fingerprinted])
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)

    silhouette_scores = {}
    best_k, best_score, best_labels, best_model = None, -2.0, None, None
    n_samples = len(fingerprinted)
    for k in range(4, 13):
        if k >= n_samples:
            continue
        model = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = model.fit_predict(X_scaled)
        score = silhouette_score(X_scaled, labels)
        silhouette_scores[k] = score
        if score > best_score:
            best_k, best_score, best_labels, best_model = k, score, labels, model

    clusters = {c: [] for c in range(best_k)}
    for idx, lbl in enumerate(best_labels):
        clusters[lbl].append(idx)

    cluster_reports = []
    for c in range(best_k):
        member_idxs = clusters[c]
        members = [fingerprinted[i] for i in member_idxs]
        size = len(members)
        tickers = [m["ticker"] for m in members]
        ticker_counts = Counter(tickers)
        top_ticker, top_count = ticker_counts.most_common(1)[0]
        dominated = (top_count / size) >= 0.5

        feat_mean_raw = {f: float(np.mean([m["features"][f] for m in members])) for f in FEATURE_ORDER}
        feat_std_raw = {f: float(np.std([m["features"][f] for m in members])) for f in FEATURE_ORDER}
        global_mean = {f: float(np.mean(X_raw[:, j])) for j, f in enumerate(FEATURE_ORDER)}
        global_std = {f: float(np.std(X_raw[:, j])) or 1.0 for j, f in enumerate(FEATURE_ORDER)}
        z_of_cluster = {f: (feat_mean_raw[f] - global_mean[f]) / global_std[f] for f in FEATURE_ORDER}

        numeric_feats = [f for f in FEATURE_ORDER if f not in BOOLEAN_FEATURES]
        top_desc_feats = sorted(numeric_feats, key=lambda f: -abs(z_of_cluster[f]))[:3]
        desc_parts = []
        for f in top_desc_feats:
            if abs(z_of_cluster[f]) < 0.3:
                continue
            direction = "high" if z_of_cluster[f] > 0 else "low"
            desc_parts.append(f"{direction} {f}")
        for bf in BOOLEAN_FEATURES:
            if feat_mean_raw[bf] >= 0.5:
                desc_parts.append(f"{PATTERN_NAME_OF[bf]} common ({feat_mean_raw[bf]*100:.0f}% of moves)")
        description = "; ".join(desc_parts) if desc_parts else "no strongly distinguishing feature vs. the overall dataset"

        cluster_reports.append({
            "cluster": c, "size": size, "dominated": dominated,
            "top_ticker": top_ticker, "top_ticker_count": top_count,
            "n_distinct_tickers": len(ticker_counts),
            "feat_mean_raw": feat_mean_raw, "feat_std_raw": feat_std_raw,
            "description": description, "member_idxs": member_idxs,
        })

    # ================================================================ STEP 4
    step4_rows = []
    for cr in cluster_reports:
        if cr["size"] < MIN_CLUSTER_FOR_VALIDATION:
            continue
        members = [fingerprinted[i] for i in cr["member_idxs"]]
        original_keys = set((m["ticker"], m["move_start_date"]) for m in members)

        mean_raw, std_raw = cr["feat_mean_raw"], cr["feat_std_raw"]
        bool_majority = {bf: (mean_raw[bf] >= 0.5) for bf in BOOLEAN_FEATURES}

        def in_band(feat):
            for f in FEATURE_ORDER:
                if f in BOOLEAN_FEATURES:
                    if bool_majority[f] and feat[f] < 0.5:
                        return False
                    continue
                half_width = max(1.0 * std_raw[f], 1e-6)
                lo, hi = mean_raw[f] - half_width, mean_raw[f] + half_width
                if not (lo <= feat[f] <= hi):
                    return False
            return True

        horizon_records = {h: [] for h in FWD_HORIZONS}
        for sym, bars in universe.items():
            pc = per_ticker[sym]
            n_bars = len(bars)
            max_h = max(FWD_HORIZONS)
            for i in range(MIN_ANCHOR_IDX, n_bars - max_h - 1):
                if (sym, bars[i + 1]["date"]) in original_keys:
                    continue
                feat = get_features(pc, i)
                if feat is None or not in_band(feat):
                    continue
                entry_close = pc["closes"][i]
                for h in FWD_HORIZONS:
                    fwd_close = pc["closes"][i + h]
                    ret = (fwd_close - entry_close) / entry_close if entry_close else None
                    if ret is not None:
                        horizon_records[h].append(1 if ret > 0 else 0)

        for h in FWD_HORIZONS:
            hits = horizon_records[h]
            n = len(hits)
            n_hit = sum(hits)
            verdict, win_rate, ci_low, ci_high = evaluate_verdict_hits(n, n_hit)
            step4_rows.append({
                "cluster": cr["cluster"], "horizon": h, "n": n, "n_hit": n_hit,
                "win_rate": win_rate, "ci_low": ci_low, "ci_high": ci_high, "verdict": verdict,
            })

    # ================================================================ report
    lines = []
    lines.append("# Watchlist-Wide Unsupervised Fingerprint Clustering (89 stocks)")
    lines.append("")
    lines.append(f"**Run date (UTC):** {now.isoformat()}")
    lines.append("")
    lines.append("## Step 1 — mechanical move detection")
    lines.append("")
    lines.append(f"Rule: close return >= +{MOVE_PCT*100:.0f}% over any {MOVE_WINDOW}-trading-day window; "
                 f"once flagged, scan skips past that window's end (no overlapping flags per stock). "
                 f"Identical rule applied to all {len(WATCHLIST_SYMBOLS)} watchlist symbols, no manual selection.")
    lines.append("")
    lines.append(f"**Total moves found across all watchlist stocks: {total_moves_step1}** "
                 f"(from {len(universe)} of {len(WATCHLIST_SYMBOLS)} symbols with usable cached history).")
    lines.append(f"Of these, {len(fingerprinted)} moves had a complete pre-move feature vector "
                 f"(anchor bar with full indicator history available) and were carried into clustering; "
                 f"{total_moves_step1 - len(fingerprinted)} were detected but skipped from clustering for "
                 f"insufficient pre-move history at the anchor bar.")
    lines.append("")
    if missing:
        lines.append(f"**{len(missing)} symbol(s) with insufficient cached history "
                     f"(< {MIN_ANCHOR_IDX + MOVE_WINDOW + max(FWD_HORIZONS) + 1} bars needed):**")
        lines.append(", ".join(f"{s} ({n} bars)" for s, n in missing))
    else:
        lines.append("All 89 watchlist symbols had sufficient cached history.")
    lines.append("")

    lines.append("## Step 3 — clustering")
    lines.append("")
    lines.append("Silhouette scores tested (k = number of clusters):")
    lines.append("")
    lines.append("| k | Silhouette score |")
    lines.append("|---|---|")
    for k in sorted(silhouette_scores):
        marker = " **<- chosen**" if k == best_k else ""
        lines.append(f"| {k} | {silhouette_scores[k]:.4f}{marker} |")
    lines.append("")
    lines.append(f"**Chosen k = {best_k}** (highest silhouette score, {best_score:.4f}), "
                 f"per the pre-registered selection rule.")
    lines.append("")
    lines.append("| Cluster | Size | Dominant stock? | Description |")
    lines.append("|---|---|---|---|")
    for cr in cluster_reports:
        dom_s = (f"YES — {cr['top_ticker']} is {cr['top_ticker_count']}/{cr['size']} "
                 f"({cr['top_ticker_count']/cr['size']*100:.0f}%) of this cluster's moves; NOT cross-stock"
                 if cr["dominated"] else
                 f"No — spread across {cr['n_distinct_tickers']} distinct stocks, "
                 f"top ticker ({cr['top_ticker']}) only {cr['top_ticker_count']/cr['size']*100:.0f}%")
        lines.append(f"| {cr['cluster']} | {cr['size']} | {dom_s} | {cr['description']} |")
    lines.append("")
    lines.append("### Per-cluster mean feature profile")
    lines.append("")
    header = "| Cluster | " + " | ".join(FEATURE_ORDER) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(FEATURE_ORDER) + 1))
    for cr in cluster_reports:
        vals = " | ".join(f"{cr['feat_mean_raw'][f]:.3f}" for f in FEATURE_ORDER)
        lines.append(f"| {cr['cluster']} | {vals} |")
    lines.append("")

    lines.append(f"## Step 4 — out-of-sample validation (clusters with >= {MIN_CLUSTER_FOR_VALIDATION} members)")
    lines.append("")
    tested_clusters = sorted(set(r["cluster"] for r in step4_rows))
    if not tested_clusters:
        lines.append(f"No cluster reached the >= {MIN_CLUSTER_FOR_VALIDATION}-member threshold for validation.")
    else:
        lines.append(f"Clusters tested: {tested_clusters}. For each, the cluster centroid (mean +/- 1.0 std "
                     f"per numeric feature; majority-presence required for pattern flags seen in >=50% of "
                     f"members) is scanned as a fingerprint against the full 89-stock history, excluding "
                     f"each cluster's own original member dates. Hit = forward return > 0%. n>={N_FLOOR} "
                     f"required per cell or reported as \"TOO FEW MATCHES\". PASS only if Wilson 95% CI "
                     f"lower bound on win rate > 50.0%.")
        lines.append("")
        lines.append("| Cluster | Horizon | n | Hits | Win rate | Wilson 95% CI | Verdict |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in step4_rows:
            wr_s = f"{r['win_rate']:.2f}%" if r["win_rate"] is not None else "—"
            ci_s = f"[{r['ci_low']:.2f}%, {r['ci_high']:.2f}%]" if r["ci_low"] is not None else "—"
            lines.append(f"| {r['cluster']} | +{r['horizon']}d | {r['n']} | {r['n_hit']} | {wr_s} | {ci_s} | {r['verdict']} |")
    lines.append("")

    n_pass = sum(1 for r in step4_rows if r["verdict"].startswith("PASS"))
    n_fail = sum(1 for r in step4_rows if r["verdict"].startswith("FAIL"))
    n_toofew = sum(1 for r in step4_rows if r["verdict"].startswith("TOO FEW"))
    lines.append("## Summary")
    lines.append("")
    lines.append(f"Across the {len(tested_clusters)} cluster(s) validated in Step 4 "
                 f"({len(step4_rows)} cluster x horizon cells): {n_pass} PASS, {n_fail} FAIL, "
                 f"{n_toofew} TOO FEW MATCHES. "
                 + (f"{n_pass} cell(s) showed real out-of-sample evidence of predicting a positive forward "
                    f"return beyond chance; the remaining cells are descriptive groupings of the specific "
                    f"moves that happened to form them, with no demonstrated predictive power once scanned "
                    f"out-of-sample."
                    if len(step4_rows) else
                    "No cluster reached the validation threshold, so no out-of-sample evidence either way "
                    "was produced in this run."))
    lines.append("")
    lines.append(f"**Multiple-testing note:** {len(step4_rows)} cluster x horizon cells were tested in this "
                 f"single pass ({len(tested_clusters)} clusters x up to {len(FWD_HORIZONS)} horizons each). "
                 f"A lone PASS among this many tests at the 95% confidence level is not, on its own, a "
                 f"discovery -- roughly 1 in 20 tests is expected to cross the 50% CI-lower-bound threshold "
                 f"by chance alone even with zero true edge. What would actually be interesting is "
                 f"consistency: the SAME cluster passing across multiple horizons, or a PASS with a wide "
                 f"CI margin well clear of 50% -- not a single isolated cell.")
    lines.append("")
    lines.append("Phase 2 (RandomForest/XGBoost/SHAP) was **NOT** run for any cluster in this task, "
                 "regardless of verdict.")
    lines.append("")

    report_md = "\n".join(lines)
    out_path = Path(__file__).parent / "watchlist_cluster_analysis.md"
    out_path.write_text(report_md)

    summary = {
        "total_moves_step1": total_moves_step1, "n_fingerprinted": len(fingerprinted),
        "missing_symbols": missing, "silhouette_scores": silhouette_scores, "best_k": best_k,
        "clusters": [{"cluster": cr["cluster"], "size": cr["size"], "dominated": cr["dominated"],
                      "top_ticker": cr["top_ticker"]} for cr in cluster_reports],
        "step4_rows": step4_rows,
    }
    print("===JSON_START===")
    print(json.dumps(summary, separators=(",", ":")))
    print("===JSON_END===")
    print("===REPORT_MD_START===")
    print(report_md)
    print("===REPORT_MD_END===")


if __name__ == "__main__":
    main()
