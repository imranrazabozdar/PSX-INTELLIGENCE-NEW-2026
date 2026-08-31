"""ema_sustained_backtest.py — completes the Change 2 investigation
deferred in CALIBRATION_LOG.md ("INDICATOR BACKTEST RESULTS — 2026-08-30").

indicator_backtester.py tested discrete CROSSING events (e.g. "MACD line
crosses above signal line today"). This script tests the different,
narrower question analyze()'s actual scoring asks: on any given day where
a SUSTAINED CONDITION currently holds (price is above EMA20 right now,
regardless of how long it's been there), what is the forward return
distribution? Every eligible day where the condition holds counts as its
own observation -- consecutive days sharing the same state are NOT
deduplicated into one "episode", since analyze() itself re-evaluates and
re-scores this condition fresh on every call, every day.

Read-only, same as indicator_backtester.py: reads daily_ohlc directly,
writes nothing back to the database, does not import or modify
technical_analyzer.py/dss_engine.py/scoring_engine.py.
"""

import os
import time

import pandas as pd

from indicator_backtester import (
    DB_PATH, MIN_HISTORY_DAYS, FORWARD_HORIZONS,
    _load_all_ohlc, _macd,
)


def _compute_sustained_signals(g: pd.DataFrame) -> dict:
    close = g["close"]
    macd_line, macd_sig, macd_hist = _macd(close)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    return {
        "EMA20_ABOVE": close > ema20,
        "EMA50_ABOVE": close > ema50,
        "MACD_BULL": macd_line > macd_sig,
        "MACD_HIST_BULL": macd_hist > 0,
    }


def run(db_path=DB_PATH, min_history_days=MIN_HISTORY_DAYS):
    all_df = _load_all_ohlc(db_path)
    records = []
    baseline_records = []
    max_h = max(FORWARD_HORIZONS)

    for symbol, g in all_df.groupby("symbol", sort=False):
        g = g.sort_values("trade_date").reset_index(drop=True)
        n = len(g)
        if n < min_history_days + max_h + 1:
            continue

        close = g["close"].astype(float)
        fwd = {h: (close.shift(-h) - close) / close for h in FORWARD_HORIZONS}

        signals = _compute_sustained_signals(g)

        eligible = pd.Series(False, index=g.index)
        eligible.iloc[min_history_days:] = True
        eligible &= fwd[max_h].notna()

        dates = g["trade_date"]

        base_idx = g.index[eligible]
        for i in base_idx:
            baseline_records.append((
                symbol, dates.iat[i],
                fwd[1].iat[i], fwd[5].iat[i], fwd[10].iat[i], fwd[20].iat[i],
            ))

        for sig_name, sig_bool in signals.items():
            active = (sig_bool & eligible).fillna(False)
            idx = g.index[active]
            for i in idx:
                records.append({
                    "symbol": symbol, "date": dates.iat[i], "signal_type": sig_name,
                    "forward_1d": fwd[1].iat[i], "forward_5d": fwd[5].iat[i],
                    "forward_10d": fwd[10].iat[i], "forward_20d": fwd[20].iat[i],
                })

    signal_df = pd.DataFrame(records)
    baseline_df = pd.DataFrame(
        baseline_records,
        columns=["symbol", "date", "forward_1d", "forward_5d", "forward_10d", "forward_20d"],
    )
    return signal_df, baseline_df


def summarize(signal_df: pd.DataFrame, baseline_df: pd.DataFrame) -> pd.DataFrame:
    total_eligible_bars = len(baseline_df)
    rows = []
    for signal_type, grp in signal_df.groupby("signal_type"):
        n = len(grp)
        rows.append({
            "signal_type": signal_type, "n_signals": n,
            "win_rate_1d": (grp["forward_1d"] > 0).mean() * 100,
            "win_rate_5d": (grp["forward_5d"] > 0).mean() * 100,
            "win_rate_10d": (grp["forward_10d"] > 0).mean() * 100,
            "win_rate_20d": (grp["forward_20d"] > 0).mean() * 100,
            "avg_return_10d": grp["forward_10d"].mean() * 100,
            "median_return_10d": grp["forward_10d"].median() * 100,
            "signal_frequency_pct": n / total_eligible_bars * 100 if total_eligible_bars else 0.0,
        })
    summary = pd.DataFrame(rows)

    baseline_row = {
        "signal_type": "BASELINE (ANY_RANDOM_BAR)",
        "n_signals": total_eligible_bars,
        "win_rate_1d": (baseline_df["forward_1d"] > 0).mean() * 100,
        "win_rate_5d": (baseline_df["forward_5d"] > 0).mean() * 100,
        "win_rate_10d": (baseline_df["forward_10d"] > 0).mean() * 100,
        "win_rate_20d": (baseline_df["forward_20d"] > 0).mean() * 100,
        "avg_return_10d": baseline_df["forward_10d"].mean() * 100,
        "median_return_10d": baseline_df["forward_10d"].median() * 100,
        "signal_frequency_pct": 100.0,
    }
    summary = pd.concat([summary, pd.DataFrame([baseline_row])], ignore_index=True)
    summary = summary.sort_values("win_rate_10d", ascending=False).reset_index(drop=True)
    return summary


if __name__ == "__main__":
    t0 = time.time()
    print("Loading daily_ohlc and scanning sustained-position signals ...")
    signal_df, baseline_df = run()
    print(f"Scan complete in {time.time() - t0:.1f}s -- "
          f"{len(signal_df)} sustained-condition day-observations, {len(baseline_df)} eligible baseline bars.")

    summary = summarize(signal_df, baseline_df)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    signal_df.to_csv(os.path.join(out_dir, "ema_sustained_backtest_results.csv"), index=False)
    summary.to_csv(os.path.join(out_dir, "ema_sustained_backtest_summary.csv"), index=False)

    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 220)
    print("\n" + summary.round(2).to_string(index=False))

    baseline_win_10d = summary.loc[
        summary["signal_type"] == "BASELINE (ANY_RANDOM_BAR)", "win_rate_10d"].iloc[0]
    print(f"\nBaseline win_rate_10d: {baseline_win_10d:.2f}%")

    non_baseline = summary[summary["signal_type"] != "BASELINE (ANY_RANDOM_BAR)"]
    above = non_baseline[non_baseline["win_rate_10d"] >= baseline_win_10d]
    below = non_baseline[non_baseline["win_rate_10d"] < baseline_win_10d]

    print(f"\nABOVE baseline (keep in scoring) -- {len(above)}:")
    print(above[["signal_type", "win_rate_10d", "n_signals"]].round(2).to_string(index=False)
          if len(above) else "(none)")

    print(f"\nBELOW baseline (should be removed per Change 2's own rule) -- {len(below)}:")
    print(below[["signal_type", "win_rate_10d", "n_signals"]].round(2).to_string(index=False)
          if len(below) else "(none)")

    print(f"\nTotal elapsed: {time.time() - t0:.1f}s")
