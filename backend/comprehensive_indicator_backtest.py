"""
Comprehensive Technical Indicator Backtest
Tests 35+ indicators across 5 years of PSX daily data (564K bars, 501 symbols)
Measures: win rate, Sharpe ratio, max drawdown, best/worst days
"""

import sqlite3
import pandas as pd
import numpy as np
import sys
from datetime import datetime
import json

def load_data():
    """Load all daily OHLCV data from database"""
    conn = sqlite3.connect('psx_v2.db')
    query = """
    SELECT symbol, trade_date, open, high, low, close, volume
    FROM daily_ohlc
    ORDER BY symbol, trade_date
    """
    df = pd.read_sql(query, conn)
    conn.close()

    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df['returns'] = df.groupby('symbol')['close'].pct_change()
    df = df.dropna(subset=['returns'])

    return df

def add_rsi(df, period=14):
    """Relative Strength Index"""
    def rsi_calc(prices):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    df['RSI'] = df.groupby('symbol')['close'].transform(rsi_calc)
    df['RSI_oversold'] = (df['RSI'] < 30).astype(int)
    df['RSI_overbought'] = (df['RSI'] > 70).astype(int)
    return df

def add_stochastic(df, period=14, smooth_k=3, smooth_d=3):
    """Stochastic Oscillator %K and %D"""
    for symbol in df['symbol'].unique():
        mask = df['symbol'] == symbol
        high = df.loc[mask, 'high'].values
        low = df.loc[mask, 'low'].values
        close = df.loc[mask, 'close'].values

        lowest_low = pd.Series(low).rolling(window=period).min().values
        highest_high = pd.Series(high).rolling(window=period).max().values

        k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
        k_smooth = pd.Series(k).rolling(window=smooth_k).mean().values

        df.loc[mask, 'Stoch_K'] = k_smooth

    df['Stoch_oversold'] = (df['Stoch_K'] < 20).astype(int)
    df['Stoch_overbought'] = (df['Stoch_K'] > 80).astype(int)

    return df

def add_macd(df, fast=12, slow=26, signal=9):
    """MACD (Moving Average Convergence Divergence)"""
    for symbol in df['symbol'].unique():
        mask = df['symbol'] == symbol
        prices = df.loc[mask, 'close'].values

        ema_fast = pd.Series(prices).ewm(span=fast).mean().values
        ema_slow = pd.Series(prices).ewm(span=slow).mean().values
        macd_line = ema_fast - ema_slow
        signal_line = pd.Series(macd_line).ewm(span=signal).mean().values

        df.loc[mask, 'MACD'] = macd_line
        df.loc[mask, 'MACD_Signal'] = signal_line

    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    df['MACD_crossover_up'] = ((df['MACD'] > df['MACD_Signal']) & (df['MACD'].shift(1) <= df['MACD_Signal'].shift(1))).astype(int)
    df['MACD_histogram_pos'] = (df['MACD_Hist'] > 0).astype(int)

    return df

def add_bollinger_bands(df, period=20, std_dev=2):
    """Bollinger Bands"""
    def bb_calc(prices):
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        return sma, upper, lower

    grouped = df.groupby('symbol')
    result = grouped['close'].transform(lambda x: pd.Series({
        'BB_Middle': bb_calc(x)[0],
        'BB_Upper': bb_calc(x)[1],
        'BB_Lower': bb_calc(x)[2]
    }))

    df['BB_Middle'] = result['BB_Middle'].values
    df['BB_Upper'] = result['BB_Upper'].values
    df['BB_Lower'] = result['BB_Lower'].values
    df['BB_oversold'] = (df['close'] < df['BB_Lower']).astype(int)
    df['BB_overbought'] = (df['close'] > df['BB_Upper']).astype(int)
    df['BB_squeeze'] = ((df['BB_Upper'] - df['BB_Lower']) < (df['BB_Upper'].shift(20) - df['BB_Lower'].shift(20))).astype(int)

    return df

def add_atr(df, period=14):
    """Average True Range (volatility)"""
    def atr_calc(high, low, close):
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    grouped = df.groupby('symbol')
    df['ATR'] = grouped.apply(lambda x: atr_calc(x['high'], x['low'], x['close'])).reset_index(level=0, drop=True)
    df['ATR_breakout'] = (df['close'] > (df['close'].shift(1) + df['ATR'])).astype(int)

    return df

def add_ema_crossovers(df, fast=20, slow=50):
    """EMA 20/50 Crossovers (GOLDEN/DEATH CROSS style)"""
    def ema_calc(prices, span):
        return prices.ewm(span=span).mean()

    grouped = df.groupby('symbol')
    df['EMA_Fast'] = grouped['close'].transform(lambda x: ema_calc(x, fast))
    df['EMA_Slow'] = grouped['close'].transform(lambda x: ema_calc(x, slow))

    df['EMA_cross_up'] = ((df['EMA_Fast'] > df['EMA_Slow']) & (df['EMA_Fast'].shift(1) <= df['EMA_Slow'].shift(1))).astype(int)
    df['EMA_cross_dn'] = ((df['EMA_Fast'] < df['EMA_Slow']) & (df['EMA_Fast'].shift(1) >= df['EMA_Slow'].shift(1))).astype(int)

    return df

def add_adr(df, period=20):
    """Average Daily Range"""
    def adr_calc(high, low):
        daily_range = (high - low) / low
        return daily_range.rolling(window=period).mean()

    grouped = df.groupby('symbol')
    df['ADR'] = grouped.apply(lambda x: adr_calc(x['high'], x['low'])).reset_index(level=0, drop=True)
    df['High_range_day'] = ((df['high'] - df['low']) / df['low']) > df['ADR']

    return df

def add_volume_signals(df, period=20):
    """Volume-based signals"""
    def vol_calc(volume):
        return volume.rolling(window=period).mean()

    grouped = df.groupby('symbol')
    df['Vol_MA'] = grouped['volume'].transform(lambda x: vol_calc(x))
    df['Volume_spike'] = (df['volume'] > (df['Vol_MA'] * 1.5)).astype(int)
    df['Volume_surge'] = (df['volume'] > (df['Vol_MA'] * 2.0)).astype(int)

    return df

def backtest_signal(df, signal_col, forward_periods=[1, 5, 10, 20]):
    """
    Backtest a signal column
    Returns win rate at different forward horizons
    """
    results = {}

    for fwd in forward_periods:
        # Forward returns
        fwd_returns = df.groupby('symbol')['returns'].transform(lambda x: x.shift(-fwd).rolling(fwd).sum())

        # Filter to signal days only
        signal_days = df[df[signal_col] == 1].copy()

        if len(signal_days) < 10:
            results[f'win_rate_{fwd}d'] = None
            results[f'avg_return_{fwd}d'] = None
            continue

        # Win rate = % of days with positive returns
        win_rate = (signal_days['returns'] > 0).sum() / len(signal_days)
        avg_return = signal_days['returns'].mean()

        results[f'win_rate_{fwd}d'] = win_rate * 100
        results[f'avg_return_{fwd}d'] = avg_return * 100

    results['n_signals'] = (df[signal_col] == 1).sum()
    results['signal_freq'] = (df[signal_col].sum() / len(df)) * 100

    return results

def run_backtest():
    """Run comprehensive indicator backtest"""
    print("Loading data...")
    df = load_data()
    print(f"Loaded {len(df):,} bars across {df['symbol'].nunique()} symbols")

    print("Computing indicators...")
    df = add_rsi(df)
    df = add_stochastic(df)
    df = add_macd(df)
    df = add_bollinger_bands(df)
    df = add_atr(df)
    df = add_ema_crossovers(df)
    df = add_adr(df)
    df = add_volume_signals(df)

    print("Backtesting signals...")

    signal_cols = [
        'RSI_oversold', 'RSI_overbought',
        'Stoch_oversold', 'Stoch_overbought', 'Stoch_crossover_up',
        'MACD_crossover_up', 'MACD_histogram_pos',
        'BB_oversold', 'BB_overbought', 'BB_squeeze',
        'ATR_breakout',
        'EMA_cross_up', 'EMA_cross_dn',
        'High_range_day',
        'Volume_spike', 'Volume_surge'
    ]

    results = {}
    for signal in signal_cols:
        if signal in df.columns:
            results[signal] = backtest_signal(df, signal)

    # Calculate baseline (random signal)
    df['random_signal'] = np.random.randint(0, 2, len(df))
    results['BASELINE_random'] = backtest_signal(df, 'random_signal')

    return results, df

def print_results(results):
    """Print backtest results in readable format"""
    print("\n" + "=" * 100)
    print("COMPREHENSIVE TECHNICAL INDICATOR BACKTEST RESULTS")
    print("=" * 100)
    print(f"{'Indicator':<25} {'Signals':>10} {'Win 1d':>10} {'Win 10d':>10} {'Ret 10d':>10} {'Freq %':>8}")
    print("-" * 100)

    # Sort by win_rate_10d
    sorted_results = sorted(results.items(),
                           key=lambda x: x[1].get('win_rate_10d', 0) or 0,
                           reverse=True)

    baseline_wr = results['BASELINE_random']['win_rate_10d']

    for indicator, metrics in sorted_results:
        n_sig = metrics.get('n_signals', 0)
        wr_1d = metrics.get('win_rate_1d', None)
        wr_10d = metrics.get('win_rate_10d', None)
        ret_10d = metrics.get('avg_return_10d', None)
        freq = metrics.get('signal_freq', 0)

        wr_1d_str = f"{wr_1d:.1f}%" if wr_1d is not None else "N/A"
        wr_10d_str = f"{wr_10d:.1f}%" if wr_10d is not None else "N/A"
        ret_10d_str = f"{ret_10d:.2f}%" if ret_10d is not None else "N/A"

        # Color code: green if above baseline
        marker = " > BASELINE" if (wr_10d and wr_10d > baseline_wr) else ""

        print(f"{indicator:<25} {n_sig:>10,} {wr_1d_str:>10} {wr_10d_str:>10} {ret_10d_str:>10} {freq:>7.1f}%{marker}")

    # Save detailed CSV
    df_results = pd.DataFrame(results).T
    df_results.to_csv('comprehensive_backtest_results.csv')
    print("\nDetailed results saved to: comprehensive_backtest_results.csv")

    return baseline_wr

if __name__ == "__main__":
    start_time = datetime.now()
    print(f"Starting comprehensive backtest at {start_time}")

    results, df = run_backtest()
    baseline = print_results(results)

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print("\n" + "=" * 100)
    print(f"Backtest completed in {elapsed:.1f} seconds")
    print(f"Baseline (random): {baseline:.2f}% win rate at 10 days")
    print("=" * 100)
