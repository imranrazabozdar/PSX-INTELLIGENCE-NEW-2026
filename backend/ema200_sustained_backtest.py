"""ema200_sustained_backtest.py — single-signal sustained-position
backtest for EMA200_ABOVE (price > EMA200 right now), same methodology
as ema_sustained_backtest.py (EMA20/EMA50/MACD). Requires >=200 days of
history per symbol before a bar is eligible, matching
technical_analyzer.py's own EMA-200 availability gate.

Read-only: reads daily_ohlc directly, writes nothing back to the
database, does not import technical_analyzer.py/dss_engine.py.
"""

import time

import pandas as pd

from indicator_backtester import DB_PATH, FORWARD_HORIZONS, _load_all_ohlc

MIN_HISTORY_DAYS = 200  # EMA200 needs 200 bars of warmup


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
        ema200 = close.ewm(span=200, adjust=False).mean()
        fwd = {h: (close.shift(-h) - close) / close for h in FORWARD_HORIZONS}

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

        active = ((close > ema200) & eligible).fillna(False)
        idx = g.index[active]
        for i in idx:
            records.append({
                "symbol": symbol, "date": dates.iat[i], "signal_type": "EMA200_ABOVE",
                "forward_1d": fwd[1].iat[i], "forward_5d": fwd[5].iat[i],
                "forward_10d": fwd[10].iat[i], "forward_20d": fwd[20].iat[i],
            })

    signal_df = pd.DataFrame(records)
    baseline_df = pd.DataFrame(
        baseline_records,
        columns=["symbol", "date", "forward_1d", "forward_5d", "forward_10d", "forward_20d"],
    )
    return signal_df, baseline_df


if __name__ == "__main__":
    t0 = time.time()
    print("Loading daily_ohlc and scanning EMA200_ABOVE ...")
    signal_df, baseline_df = run()
    n = len(signal_df)
    total_eligible = len(baseline_df)
    win_10d = (signal_df["forward_10d"] > 0).mean() * 100 if n else float("nan")
    freq = n / total_eligible * 100 if total_eligible else 0.0

    print(f"n_signals: {n}")
    print(f"win_rate_10d: {win_10d:.2f}%")
    print(f"signal_frequency_pct: {freq:.2f}%")
    print(f"eligible baseline bars (>=200d history): {total_eligible}")
    print(f"baseline win_rate_10d: 44.55%")
    print(f"Decision: {'KEEP' if win_10d >= 44.55 else 'REMOVE'}")
    print(f"Elapsed: {time.time() - t0:.1f}s")
