#!/usr/bin/env python3
"""Triple-Barrier labeling (Lopez de Prado, "Advances in Financial Machine
Learning") + a RandomForest classifier trained on the resulting labels.

Replaces a fixed-percentage forward-return label (blind to volatility and
path) with three per-row barriers derived from ATR:
    upper (profit-take) = close + 2*ATR
    lower (stop-loss)   = close - 1.5*ATR
    vertical (time)     = 15 trading days

Drop-in usage:
    df = get_ohlcv_from_turso(symbol)          # your existing pipeline
    df = add_atr(df)
    df = add_features(df)                       # RSI/MFI/OBV/avg volume
    df = triple_barrier_label(df)
    model, report, importances = train_model(df)

Only pandas/numpy/pandas_ta/scikit-learn are required (xgboost is optional,
see train_model's `use_xgboost` flag).
"""
import numpy as np
import pandas as pd
import pandas_ta as ta


# --------------------------------------------------------------------- #
# Phase 1: dynamic barriers (ATR-based)
# --------------------------------------------------------------------- #

def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Adds an 'atr' column (Wilder ATR via pandas_ta) and the three
    per-row barrier levels. Must run before triple_barrier_label()."""
    df = df.copy()
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=period)

    df["upper_barrier"] = df["close"] + 2.0 * df["atr"]
    df["lower_barrier"] = df["close"] - 1.5 * df["atr"]
    return df


# --------------------------------------------------------------------- #
# Phase 2: the triple-barrier labeler (vectorized, no iterrows)
# --------------------------------------------------------------------- #

def triple_barrier_label(df: pd.DataFrame, max_hold: int = 15) -> pd.DataFrame:
    """For every row i, look forward up to `max_hold` bars and find which
    barrier is touched first:
        +1  high >= upper_barrier[i]  (profit target hit)
        -1  low  <= lower_barrier[i]  (stop-loss hit)
         0  neither hit within max_hold bars (vertical/time barrier)
       NaN  fewer than max_hold forward bars remain (outcome unknown --
            must be dropped before training, see drop_incomplete_labels())

    Vectorized via a rolling forward window built from shifted columns
    rather than a per-row Python loop: for each forward offset k=1..max_hold
    we compare that day's high/low (shifted back by -k so it aligns with
    row i) against row i's own barriers, then take the FIRST offset (per
    row) where either barrier was touched -- matching "whichever comes
    first" without ever iterating rows in Python.
    """
    n = len(df)
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    upper = df["upper_barrier"].to_numpy()
    lower = df["lower_barrier"].to_numpy()

    # hit_day[i] = offset (1..max_hold) of the first bar that touches
    # EITHER barrier; -1 if none touched within the window.
    first_hit_offset = np.full(n, -1, dtype=int)
    label = np.full(n, np.nan)
    still_open = np.ones(n, dtype=bool)  # rows not yet resolved

    for k in range(1, max_hold + 1):
        # forward-shifted high/low: value at i is the bar k days ahead
        fwd_high = np.roll(highs, -k)
        fwd_low = np.roll(lows, -k)
        valid = np.arange(n) < (n - k)  # rows with a real bar k days ahead

        hit_upper = valid & still_open & (fwd_high >= upper)
        hit_lower = valid & still_open & (fwd_low <= lower)

        # if both barriers are touched on the same forward bar, treat the
        # stop-loss as binding first (conservative, matches how a real
        # stop/limit order pair would resolve intrabar when only OHLC --
        # not tick data -- is available)
        label[hit_lower] = -1
        label[hit_upper & ~hit_lower] = 1
        first_hit_offset[hit_upper | hit_lower] = k
        still_open &= ~(hit_upper | hit_lower)

    # rows still open after max_hold forward bars checked:
    # - if a full max_hold-bar forward window existed and neither barrier
    #   was touched -> vertical/time barrier -> label 0
    # - if fewer than max_hold forward bars exist (near the end of the
    #   dataframe) -> outcome genuinely unknown -> NaN
    has_full_window = np.arange(n) < (n - max_hold)
    label[still_open & has_full_window] = 0
    # still_open & ~has_full_window stays NaN (unresolved, dropped later)

    df = df.copy()
    df["label"] = label
    df["barrier_touch_day"] = np.where(first_hit_offset > 0, first_hit_offset, np.nan)
    return df


def drop_incomplete_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Rows near the end of the dataframe whose 15-day vertical barrier
    hasn't expired yet have label=NaN (outcome unknown) -- must be
    dropped before training, never treated as a valid label."""
    return df.dropna(subset=["label"]).copy()


# --------------------------------------------------------------------- #
# Feature engineering (RSI, MFI, OBV, ATR already added, 20d avg volume)
# --------------------------------------------------------------------- #

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi_14"] = ta.rsi(df["close"], length=14)
    df["mfi_14"] = ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=14)
    df["obv"] = ta.obv(df["close"], df["volume"])
    df["vol_avg_20d"] = df["volume"].rolling(20).mean()
    # 'atr' already added by add_atr() -- required to run first
    return df


FEATURE_COLS = ["rsi_14", "mfi_14", "obv", "atr", "vol_avg_20d"]


# --------------------------------------------------------------------- #
# Phase 3: ML pipeline (time-series split, no shuffled K-Fold)
# --------------------------------------------------------------------- #

def train_model(df: pd.DataFrame, feature_cols=FEATURE_COLS, test_size: float = 0.2,
                 use_xgboost: bool = False, plot_importances: bool = True):
    """Trains on the first (1-test_size) fraction of rows chronologically,
    tests on the final test_size fraction -- a hard time split, never a
    shuffled K-Fold, so the model is never evaluated on data that precedes
    its own training window (no look-ahead leakage).

    Returns (model, classification_report_str, importances_series).
    """
    from sklearn.metrics import classification_report

    data = drop_incomplete_labels(df).dropna(subset=feature_cols)
    if len(data) < 50:
        raise ValueError(f"Only {len(data)} labeled rows after dropping NaNs -- "
                          f"not enough to train/test reliably.")

    X = data[feature_cols]
    y = data["label"].astype(int)

    split_idx = int(len(data) * (1 - test_size))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    if use_xgboost:
        from xgboost import XGBClassifier
        # xgboost needs 0..n_classes-1 labels, not {-1,0,1}
        label_map = {-1: 0, 0: 1, 1: 2}
        inv_map = {v: k for k, v in label_map.items()}
        model = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                               eval_metric="mlogloss", random_state=42)
        model.fit(X_train, y_train.map(label_map))
        y_pred = pd.Series(model.predict(X_test)).map(inv_map)
    else:
        from sklearn.ensemble import RandomForestClassifier
        model = RandomForestClassifier(n_estimators=300, max_depth=6,
                                        min_samples_leaf=20, class_weight="balanced",
                                        random_state=42, n_jobs=-1)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

    report = classification_report(y_test, y_pred, zero_division=0)
    print(report)

    importances = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)

    if plot_importances:
        import matplotlib.pyplot as plt
        importances.plot(kind="barh", figsize=(6, 4), title="Feature importance")
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig("feature_importance.png")
        plt.close()
        print("Saved feature_importance.png")

    return model, report, importances


# --------------------------------------------------------------------- #
# Example end-to-end usage
# --------------------------------------------------------------------- #

if __name__ == "__main__":
    # df = your_turso_fetch_function(symbol)   # columns: open/high/low/close/volume
    # df = add_atr(df)
    # df = add_features(df)
    # df = triple_barrier_label(df)
    # model, report, importances = train_model(df)
    pass
