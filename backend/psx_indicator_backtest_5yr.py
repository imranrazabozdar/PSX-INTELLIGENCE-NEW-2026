"""
PSX Indicator Backtest - 5 Years Historical Data
Simple, reliable vectorized backtest for technical indicators
Tests across 564K bars, 501 symbols, 5 years of data
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

def load_data():
    """Load daily OHLCV from database"""
    conn = sqlite3.connect('psx_v2.db')
    df = pd.read_sql("""
        SELECT symbol, trade_date, open, high, low, close, volume
        FROM daily_ohlc
        ORDER BY symbol, trade_date
    """, conn)
    conn.close()

    df['trade_date'] = pd.to_datetime(df['trade_date'])
    print(f"Loaded {len(df):,} bars from {df['trade_date'].min().date()} to {df['trade_date'].max().date()}")
    return df.reset_index(drop=True)

def compute_indicators(df):
    """Compute all technical indicators"""
    results = []

    for symbol in df['symbol'].unique():
        subset = df[df['symbol'] == symbol].copy().reset_index(drop=True)
        if len(subset) < 50:
            continue

        h = subset['high'].values
        l = subset['low'].values
        c = subset['close'].values
        v = subset['volume'].values

        # RSI (14)
        delta = np.diff(c, prepend=c[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).rolling(14, min_periods=1).mean().values
        avg_loss = pd.Series(loss).rolling(14, min_periods=1).mean().values
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))

        # Bollinger Bands (20, 2)
        sma20 = pd.Series(c).rolling(20, min_periods=1).mean().values
        std20 = pd.Series(c).rolling(20, min_periods=1).std().values
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20

        # MACD (12, 26, 9)
        ema12 = pd.Series(c).ewm(span=12).mean().values
        ema26 = pd.Series(c).ewm(span=26).mean().values
        macd = ema12 - ema26
        macd_signal = pd.Series(macd).ewm(span=9).mean().values
        macd_hist = macd - macd_signal

        # Stochastic (14)
        ll = pd.Series(l).rolling(14, min_periods=1).min().values
        hh = pd.Series(h).rolling(14, min_periods=1).max().values
        stoch_k = 100 * (c - ll) / (hh - ll + 1e-10)

        # Volume MA
        vol_ma = pd.Series(v).rolling(20, min_periods=1).mean().values

        # EMA 20/50
        ema20 = pd.Series(c).ewm(span=20).mean().values
        ema50 = pd.Series(c).ewm(span=50).mean().values

        # ATR (14)
        tr = np.maximum(
            h - l,
            np.maximum(
                np.abs(h - np.roll(c, 1)),
                np.abs(l - np.roll(c, 1))
            )
        )
        atr = pd.Series(tr).rolling(14, min_periods=1).mean().values

        # Forward returns
        forward_ret_1d = np.roll(c, -1) / c - 1
        forward_ret_5d = np.roll(c, -5) / c - 1
        forward_ret_10d = np.roll(c, -10) / c - 1
        forward_ret_20d = np.roll(c, -20) / c - 1

        subset['rsi'] = rsi
        subset['bb_upper'] = bb_upper
        subset['bb_lower'] = bb_lower
        subset['macd'] = macd
        subset['macd_signal'] = macd_signal
        subset['macd_hist'] = macd_hist
        subset['stoch_k'] = stoch_k
        subset['vol_ma'] = vol_ma
        subset['ema20'] = ema20
        subset['ema50'] = ema50
        subset['atr'] = atr
        subset['vol_spike'] = v > vol_ma * 1.5
        subset['ret_1d'] = forward_ret_1d
        subset['ret_5d'] = forward_ret_5d
        subset['ret_10d'] = forward_ret_10d
        subset['ret_20d'] = forward_ret_20d

        results.append(subset)

    return pd.concat(results, ignore_index=True)

def backtest_signal(df, signal_name, signal_array):
    """Backtest a signal"""
    # Ensure signal is a boolean array
    if isinstance(signal_array, pd.Series):
        signal_array = signal_array.values
    elif isinstance(signal_array, pd.DataFrame):
        signal_array = signal_array.iloc[:, 0].values

    signal_days = df[signal_array].copy()

    if len(signal_days) < 20:
        return {
            'signal': signal_name,
            'n_signals': len(signal_days),
            'win_rate_1d': None,
            'win_rate_5d': None,
            'win_rate_10d': None,
            'win_rate_20d': None,
            'avg_ret_10d': None
        }

    wr_1d = (signal_days['ret_1d'] > 0).sum() / len(signal_days) * 100
    wr_5d = (signal_days['ret_5d'] > 0).sum() / len(signal_days) * 100
    wr_10d = (signal_days['ret_10d'] > 0).sum() / len(signal_days) * 100
    wr_20d = (signal_days['ret_20d'] > 0).sum() / len(signal_days) * 100
    avg_ret_10d = signal_days['ret_10d'].mean() * 100

    return {
        'signal': signal_name,
        'n_signals': len(signal_days),
        'win_rate_1d': wr_1d,
        'win_rate_5d': wr_5d,
        'win_rate_10d': wr_10d,
        'win_rate_20d': wr_20d,
        'avg_ret_10d': avg_ret_10d
    }

def main():
    print("=" * 80)
    print("PSX 5-YEAR INDICATOR BACKTEST")
    print("=" * 80)

    print("\nLoading data...")
    df = load_data()

    print("Computing indicators...")
    df = compute_indicators(df)

    print("Backtesting signals...")
    results = []

    # RSI signals
    results.append(backtest_signal(df, 'RSI_Oversold', df['rsi'] < 30))
    results.append(backtest_signal(df, 'RSI_Overbought', df['rsi'] > 70))

    # Bollinger Bands
    results.append(backtest_signal(df, 'BB_Oversold', df['close'] < df['bb_lower']))
    results.append(backtest_signal(df, 'BB_Overbought', df['close'] > df['bb_upper']))

    # MACD
    results.append(backtest_signal(df, 'MACD_HistPos', df['macd_hist'] > 0))
    macd_cross_up = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
    results.append(backtest_signal(df, 'MACD_CrossUp', macd_cross_up))

    # Stochastic
    results.append(backtest_signal(df, 'Stoch_Oversold', df['stoch_k'] < 20))
    results.append(backtest_signal(df, 'Stoch_Overbought', df['stoch_k'] > 80))

    # Volume
    results.append(backtest_signal(df, 'Volume_Spike', df['vol_spike']))

    # EMA Crosses
    ema_cross_up = (df['ema20'] > df['ema50']) & (df['ema20'].shift(1) <= df['ema50'].shift(1))
    results.append(backtest_signal(df, 'EMA_CrossUp', ema_cross_up))

    ema_cross_dn = (df['ema20'] < df['ema50']) & (df['ema20'].shift(1) >= df['ema50'].shift(1))
    results.append(backtest_signal(df, 'EMA_CrossDn', ema_cross_dn))

    # Baseline (random)
    df['random'] = np.random.rand(len(df)) > 0.5
    results.append(backtest_signal(df, 'BASELINE_Random', df['random']))

    # Print results
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('win_rate_10d', ascending=False, na_position='last')

    print("\n" + "=" * 100)
    print(f"{'Signal':<25} {'# Signals':>12} {'Win 1d':>10} {'Win 5d':>10} {'Win 10d':>10} {'Win 20d':>10} {'Ret 10d':>10}")
    print("=" * 100)

    baseline_wr = results_df[results_df['signal'] == 'BASELINE_Random']['win_rate_10d'].values[0]

    for _, row in results_df.iterrows():
        marker = " *BEST*" if row['win_rate_10d'] > baseline_wr + 2 else ""
        print(f"{row['signal']:<25} {row['n_signals']:>12,.0f} {row['win_rate_1d']:>9.1f}% {row['win_rate_5d']:>9.1f}% {row['win_rate_10d']:>9.1f}% {row['win_rate_20d']:>9.1f}% {row['avg_ret_10d']:>9.2f}%{marker}")

    # Save to CSV
    results_df.to_csv('psx_5yr_backtest_results.csv', index=False)
    print(f"\nResults saved to: psx_5yr_backtest_results.csv")
    print(f"Baseline win rate (random): {baseline_wr:.2f}%")

if __name__ == "__main__":
    start = datetime.now()
    main()
    elapsed = (datetime.now() - start).total_seconds()
    print(f"\nCompleted in {elapsed:.1f} seconds")
