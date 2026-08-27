"""walkforward_engine.py — the three layers explicitly deferred when the
backtest engine first shipped: STEP 52 (chronological train/validation/
out-of-sample partitioning — never shuffled, so 'test' is genuinely unseen
future data relative to 'train'), STEP 53 (configurable transaction costs,
net-of-cost expectancy alongside gross), STEP 65 (feature importance — plain
point-biserial correlation between concrete boolean features and the forward
win outcome, reported as correlation, not a trained model, not causation),
and STEP 66 (probability calibration — TRAIN-derived win-rate buckets,
checked against the ACTUAL win rate in the held-out TEST partition, not
assumed to transfer).

This reuses backtest_engine.py's exact detection functions (candle_patterns_at,
spring_at, upthrust_at, breakout_at, forward_return, stats_from_returns) so
results are directly comparable to the single-pass /backtest/run numbers —
this is the same detection, partitioned differently, not a second opinion.
"""

import statistics
import candlestick_engine as _candles
from backtest_engine import (HORIZONS, candle_patterns_at, spring_at, upthrust_at,
                              breakout_at, forward_return, stats_from_returns)

DEFAULT_ROUND_TRIP_COST_PCT = 0.30  # brokerage + CVT + SST, both legs — a configurable estimate, not authoritative


def _signals_with_index(rows, symbol, combo_window=10):
    """Identical detection to backtest_engine.scan_symbol_patterns, but each
    signal also carries its own bar index and the symbol's total bar count,
    so it can be assigned to train/validation/test by chronological position
    without re-running detection per partition."""
    out = []
    n = len(rows)
    last_spring_i = None
    for i in range(n):
        pats = list(candle_patterns_at(rows, i))
        sp = spring_at(rows, i)
        if sp:
            pats.append(sp)
            last_spring_i = i
        ut = upthrust_at(rows, i)
        if ut:
            pats.append(ut)
        bo = breakout_at(rows, i)
        if bo:
            pats.append(bo)
        if last_spring_i is not None and 0 < i - last_spring_i <= combo_window:
            for cp in candle_patterns_at(rows, i):
                pats.append(f"Spring + {cp}")
        for p in pats:
            rets = {h: forward_return(rows, i, h) for h in HORIZONS}
            out.append({"symbol": symbol, "date": rows[i]["trade_date"], "pattern": p,
                        "index": i, "total": n, "returns": rets})
    return out


def _partition_of(sig, train_frac, val_frac):
    frac = sig["index"] / max(1, sig["total"] - 1)
    if frac < train_frac:
        return "train"
    if frac < train_frac + val_frac:
        return "validation"
    return "test"


def _aggregate(sigs, horizon, cost_pct):
    by_pattern = {}
    for s in sigs:
        r = s["returns"].get(horizon)
        if r is None:
            continue
        by_pattern.setdefault(s["pattern"], []).append(r)
    out = {}
    for pat, rets in by_pattern.items():
        gross = stats_from_returns(rets)
        net_rets = [r - cost_pct for r in rets]
        net = stats_from_returns(net_rets)
        out[pat] = {**gross, "net_avg_return": net["avg_return"], "net_expectancy": net["expectancy"],
                    "net_win_rate": net["win_rate"]}
    return out


def _feature_importance(train_signals, horizon):
    """STEP 65: point-biserial correlation between concrete boolean features
    and the forward-win outcome, pooled over TRAIN-partition signals only
    (never test, to avoid the importance ranking itself leaking future data).
    Plain stats — no trained model, no implied causation."""
    def feat_bull(s):
        return s["pattern"] in _candles.BULLISH_PATTERNS or s["pattern"] == "Spring" or s["pattern"].startswith("Spring + ")

    def feat_bear(s):
        return s["pattern"] in _candles.BEARISH_PATTERNS or s["pattern"] == "Upthrust"

    features = {
        "bullish_candlestick_family": feat_bull,
        "bearish_candlestick_family": feat_bear,
        "resistance_breakout": lambda s: s["pattern"] == "Resistance Breakout",
        "support_breakdown": lambda s: s["pattern"] == "Support Breakdown",
        "spring_present": lambda s: s["pattern"] == "Spring" or s["pattern"].startswith("Spring + "),
        "spring_plus_candle_combo": lambda s: s["pattern"].startswith("Spring + "),
    }
    rows = [(s, 1 if s["returns"].get(horizon, 0) and s["returns"][horizon] > 0 else 0)
            for s in train_signals if s["returns"].get(horizon) is not None]
    if len(rows) < 30:
        return {"status": "insufficient_sample", "n": len(rows)}

    y = [w for _, w in rows]
    y_mean = statistics.mean(y)
    y_var = sum((v - y_mean) ** 2 for v in y)
    ranked = []
    for name, fn in features.items():
        x = [1 if fn(s) else 0 for s, _ in rows]
        x_mean = statistics.mean(x)
        if x_mean in (0, 1):
            ranked.append({"feature": name, "correlation": None, "n_positive": sum(x), "note": "no variance in this sample"})
            continue
        cov = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(len(x)))
        x_var = sum((v - x_mean) ** 2 for v in x)
        denom = (x_var * y_var) ** 0.5
        ranked.append({"feature": name, "correlation": round(cov / denom, 3) if denom else None, "n_positive": sum(x)})
    ranked.sort(key=lambda r: -(abs(r["correlation"]) if r["correlation"] is not None else -1))
    return {"status": "ok", "n_signals": len(rows), "ranked": ranked,
            "note": "Point-biserial correlation with forward-return-positive at the horizon, TRAIN "
                    "partition only. Correlation, not causation — a first honest read of which concrete "
                    "features actually track outcomes in this universe, nothing more."}


def run_walkforward(universe, train_frac=0.6, val_frac=0.2, cost_pct=DEFAULT_ROUND_TRIP_COST_PCT, horizon=20):
    """universe: {symbol: rows}. Chronological per-symbol split — train_frac
    of each symbol's OWN history, not a global date cutoff, so every symbol
    contributes to every partition regardless of when it was backfilled."""
    all_signals = []
    for sym, rows in universe.items():
        if not rows or len(rows) < 100:
            continue
        sigs = _signals_with_index(rows, sym)
        for s in sigs:
            s["partition"] = _partition_of(s, train_frac, val_frac)
        all_signals.extend(sigs)

    partitions = {"train": [], "validation": [], "test": []}
    for s in all_signals:
        partitions[s["partition"]].append(s)

    train_stats = _aggregate(partitions["train"], horizon, cost_pct)
    val_stats = _aggregate(partitions["validation"], horizon, cost_pct)
    test_stats = _aggregate(partitions["test"], horizon, cost_pct)

    oos_check = []
    for pat, tr in train_stats.items():
        te = test_stats.get(pat)
        if not te or tr["low_sample"]:
            continue
        holds = (te["expectancy"] > 0) == (tr["expectancy"] > 0)
        oos_check.append({
            "pattern": pat, "train_n": tr["n"], "train_expectancy": tr["expectancy"],
            "train_net_expectancy": tr["net_expectancy"], "train_win_rate": tr["win_rate"],
            "test_n": te["n"], "test_expectancy": te["expectancy"], "test_net_expectancy": te["net_expectancy"],
            "test_win_rate": te["win_rate"], "test_low_sample": te["low_sample"],
            "direction_holds_out_of_sample": holds,
        })
    oos_check.sort(key=lambda r: -(r["train_expectancy"] or 0))

    # STEP 66: bucket patterns by TRAIN win-rate, check pooled ACTUAL win-rate in TEST.
    calib_rows = [r for r in oos_check if not r["test_low_sample"]]
    calib_rows.sort(key=lambda r: r["train_win_rate"] or 0)
    calibration = []
    if calib_rows:
        n_bins = min(5, len(calib_rows))
        bin_size = max(1, len(calib_rows) // n_bins)
        for b in range(n_bins):
            chunk = calib_rows[b * bin_size:(b + 1) * bin_size] if b < n_bins - 1 else calib_rows[b * bin_size:]
            if not chunk:
                continue
            predicted = statistics.mean([c["train_win_rate"] for c in chunk])
            pat_set = {c["pattern"] for c in chunk}
            pooled = [s["returns"].get(horizon) for s in partitions["test"]
                      if s["pattern"] in pat_set and s["returns"].get(horizon) is not None]
            actual = (sum(1 for r in pooled if r > 0) / len(pooled) * 100) if pooled else None
            calibration.append({
                "bin": b + 1, "patterns": sorted(pat_set),
                "predicted_win_rate_from_train": round(predicted, 1),
                "actual_win_rate_in_test": round(actual, 1) if actual is not None else None,
                "test_n": len(pooled),
                "calibration_gap": round(actual - predicted, 1) if actual is not None else None,
            })

    feature_importance = _feature_importance(partitions["train"], horizon)

    return {
        "train_frac": train_frac, "val_frac": val_frac, "test_frac": round(1 - train_frac - val_frac, 2),
        "cost_pct_per_round_trip": cost_pct, "horizon": horizon,
        "counts": {"train": len(partitions["train"]), "validation": len(partitions["validation"]),
                   "test": len(partitions["test"])},
        "train_stats": train_stats, "validation_stats": val_stats, "test_stats": test_stats,
        "out_of_sample_check": oos_check,
        "calibration": calibration,
        "feature_importance": feature_importance,
        "note": "STEP 52-53/65-66. train/validation/test are chronological per-symbol splits, never "
                "shuffled — 'test' is genuine unseen future data relative to 'train'. Net figures "
                f"subtract a configurable {cost_pct}% round-trip cost estimate (brokerage+CVT+SST — tune "
                "for your actual broker via cost_pct). Feature importance is plain correlation over the "
                "TRAIN partition only, not a trained classifier and not causal. Calibration bins are small "
                "by construction (this universe is ~48 symbols) — read the gap column, don't over-trust "
                "any single bin.",
    }
