"""wyckoff_detector.py — Phase 2: the Wyckoff Institutional Stealth
Accumulation detection engine.

Five metrics, each with a PSX-calibrated threshold (see the 4 approved
corrections below, validated against real PSX cases -- notably FCL's
2026-08-07 absorption day, which the original prompt's stricter numbers
would have missed):

  1. Consolidation Bounds  -- df_daily. (High_20d - Low_20d) / Low_20d
     <= 0.08 OR (High_20d - Low_20d) / ATR_14 <= 4.5. The prompt's very
     first draft used <= 1.5 for the ATR ratio, which is mathematically
     impossible over a 20-bar window (a 20-day range can't be smaller
     than a small multiple of a single day's ATR) -- corrected to 4.5.
  2. Supply Exhaustion -- df_daily, 10-day lookback. >= 2 days (not 3)
     with Volume < 0.50 x SMA(Volume, 20) flips a rolling(10)-day memory
     flag, so the signal doesn't vanish the instant volume normalizes.
  3. Absorption Footprint -- df_daily, 8-day memory (not 5). Volume >=
     2.0x SMA(Volume, 20) AND ((High-Low)/ATR_14 <= 1.45 OR
     abs(Close-Open)/ATR_14 <= 0.85) -- the original 1.00 ATR spread cap
     would have excluded FCL's real absorption day.
  4. OBV Divergence -- df_daily. Both OBV and Close get z-normalized
     (within each rolling window, so no lookahead) before their slopes
     are compared -- OBV and price live on completely different scales,
     so comparing raw slopes would be comparing unlike units.
  5. BB Compression -- THE ONE METRIC ON df_4h, not df_daily. Computed
     entirely on 4-hour bars, then resampled to daily via last() BEFORE
     being merged into df_daily (the "Data Alignment Rule") -- pandas
     aligns a Series-to-column assignment by index label, so doing the
     resample first and assigning after is what makes that merge land on
     the right day instead of silently misaligning.

No 1-hour data or indicator is computed anywhere in this module --
that timeframe is deliberately left to a manual chart open once a
WATCH/READY/EXTREME signal fires (see module-level workflow note in
wyckoff_scheduler.py).
"""
import numpy as np
import pandas as pd

DEFAULT_CONFIG = {
    "consolidation_pct_threshold": 0.08,
    "consolidation_atr_multiplier": 4.5,

    "supply_exhaustion_volume_pct": 0.50,
    "supply_exhaustion_count_threshold": 2,
    "supply_exhaustion_lookback": 10,
    "supply_exhaustion_memory": 10,

    "absorption_spread_atr_threshold": 1.45,
    "absorption_co_atr_threshold": 0.85,
    "absorption_volume_multiplier": 2.0,
    "absorption_memory": 8,

    "obv_slope_threshold": 0.05,
    "price_slope_threshold": 0.02,
    "slope_lookback": 15,

    "bb_width_threshold": 0.10,
    "bb_period": 20,
    "bb_std": 2.0,

    "bb_width_points": 20,
    "supply_exhaustion_points": 20,
    "absorption_points": 30,
    "obv_divergence_points": 30,

    "watch_threshold": 60,
    "ready_threshold": 70,
    "extreme_threshold": 85,

    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
}


class WyckoffDetector:
    def __init__(self, config: dict = None):
        """`config` may be the `wyckoff` section of fire_config.yaml
        directly, or the full loaded config (in which case its `wyckoff`
        key is used); omit it entirely to fall back to DEFAULT_CONFIG,
        so this class is usable standalone in tests without a yaml file."""
        if config is None:
            self.config = dict(DEFAULT_CONFIG)
        else:
            self.config = dict(DEFAULT_CONFIG)
            self.config.update(config.get("wyckoff", config))

    @staticmethod
    def rolling_slope(series: pd.Series, window: int = 15, z_normalize: bool = True) -> pd.Series:
        """Linear-regression slope over a trailing `window`-bar span.

        z_normalize=True z-scores EACH WINDOW independently (its own mean
        and std, not the whole series') before fitting -- required to
        compare OBV's slope against price's slope, since raw OBV lives on
        a totally different scale than price. Using each window's own
        stats (rather than the full series') keeps this lookahead-free:
        the value at bar t never depends on data after t.
        """
        x = np.arange(window, dtype=float)

        def _slope(y):
            if np.any(np.isnan(y)):
                return np.nan
            if z_normalize:
                std = y.std()
                if std == 0:
                    return 0.0
                y = (y - y.mean()) / std
            return np.polyfit(x, y, 1)[0]

        return series.rolling(window).apply(_slope, raw=True)

    @staticmethod
    def calculate_obv(df: pd.DataFrame) -> pd.Series:
        """On-Balance Volume: OBV[0] = 0, OBV[t] = OBV[t-1] +/- Volume[t]
        by the sign of Close[t] - Close[t-1] (unchanged on a flat close)."""
        direction = np.sign(df["close"].diff()).fillna(0)
        return (direction * df["volume"]).cumsum()

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Wilder-style ATR (approximated via an EWM with alpha=1/period,
        which converges to the same recurrence Wilder's smoothing uses
        after the seed bars) -- same definition fire_engine/compression.py
        uses for intraday data, just vectorized for a daily DataFrame."""
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20,
                                   std_multiplier: float = 2.0) -> tuple:
        """Returns (SMA, Upper Band, Lower Band)."""
        sma = df["close"].rolling(period).mean()
        std = df["close"].rolling(period).std(ddof=0)
        return sma, sma + std_multiplier * std, sma - std_multiplier * std

    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26,
                        signal: int = 9) -> tuple:
        """Returns (MACD Line, Signal Line, Histogram)."""
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, signal_line, macd_line - signal_line

    def detect_stealth_accumulation(self, df_daily: pd.DataFrame,
                                     df_4h: pd.DataFrame = None) -> pd.DataFrame:
        """MAIN ENGINE. `df_daily` must have open/high/low/close/volume
        columns indexed by date (see wyckoff_data_fetcher.load_daily_df()).
        `df_4h`, same columns indexed by 4-hour-bar datetime, is used for
        BB Compression ONLY -- every other metric is daily-only. Returns
        df_daily with every intermediate and final column attached."""
        cfg = self.config
        df = df_daily.copy()

        df["atr_14"] = self.calculate_atr(df, period=14)
        df["volume_sma_20"] = df["volume"].rolling(20).mean()
        df["obv"] = self.calculate_obv(df)
        df["macd_line"], df["macd_signal"], df["macd_hist"] = self.calculate_macd(
            df, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"]
        )

        # Step 1: Consolidation Bounds (df_daily)
        high_20d = df["high"].rolling(20).max()
        low_20d = df["low"].rolling(20).min()
        df["consolidation_pct"] = (high_20d - low_20d) / low_20d
        df["consolidation_atr"] = (high_20d - low_20d) / df["atr_14"]
        df["is_consolidating"] = (
            (df["consolidation_pct"] <= cfg["consolidation_pct_threshold"])
            | (df["consolidation_atr"] <= cfg["consolidation_atr_multiplier"])
        ).fillna(False)

        # Step 2: Supply Exhaustion (df_daily, 10-day memory)
        dry_day = df["volume"] < (cfg["supply_exhaustion_volume_pct"] * df["volume_sma_20"])
        dry_count = dry_day.rolling(cfg["supply_exhaustion_lookback"]).sum()
        exhaustion_bar = dry_count >= cfg["supply_exhaustion_count_threshold"]
        df["dry_supply_flag"] = (
            exhaustion_bar.rolling(cfg["supply_exhaustion_memory"]).max().fillna(0).astype(bool)
        )

        # Step 3: Absorption Footprint (df_daily, 8-day memory)
        df["spread_atr_ratio"] = (df["high"] - df["low"]) / df["atr_14"]
        df["co_atr_ratio"] = (df["close"] - df["open"]).abs() / df["atr_14"]
        absorption_bar = (
            (df["volume"] >= cfg["absorption_volume_multiplier"] * df["volume_sma_20"])
            & (
                (df["spread_atr_ratio"] <= cfg["absorption_spread_atr_threshold"])
                | (df["co_atr_ratio"] <= cfg["absorption_co_atr_threshold"])
            )
        )
        df["absorption_active"] = (
            absorption_bar.rolling(cfg["absorption_memory"]).max().fillna(0).astype(bool)
        )

        # Step 4: OBV Divergence (df_daily)
        df["obv_slope"] = self.rolling_slope(df["obv"], window=cfg["slope_lookback"], z_normalize=True)
        df["price_slope"] = self.rolling_slope(df["close"], window=cfg["slope_lookback"], z_normalize=True)
        df["obv_divergence"] = (
            (df["obv_slope"] > cfg["obv_slope_threshold"])
            & (df["price_slope"] <= cfg["price_slope_threshold"])
        ).fillna(False)

        # Step 5: BB Compression -- CRITICAL: computed on df_4h, resampled
        # to daily via last(), THEN merged (Data Alignment Rule).
        if df_4h is not None and not df_4h.empty:
            sma4, upper4, lower4 = self.calculate_bollinger_bands(
                df_4h, period=cfg["bb_period"], std_multiplier=cfg["bb_std"]
            )
            bb_width_4h = (upper4 - lower4) / sma4
            bb_compression_4h = bb_width_4h <= cfg["bb_width_threshold"]
            df["bb_width"] = bb_width_4h.resample("D").last()
            df["bb_compression"] = bb_compression_4h.resample("D").last()
            df["bb_compression"] = df["bb_compression"].fillna(False).astype(bool)
        else:
            df["bb_width"] = np.nan
            df["bb_compression"] = False

        # Step 6: MACD Confirmation (df_daily)
        macd_bullish_cross = df["macd_line"] > df["macd_signal"]
        macd_hist_rising_positive = (df["macd_hist"] > 0) & (df["macd_hist"] > df["macd_hist"].shift(1))
        df["macd_confirmation"] = (macd_bullish_cross | macd_hist_rising_positive).fillna(False)

        # Step 7: Scoring (0-100)
        df["bb_width_score"] = np.where(df["bb_compression"], cfg["bb_width_points"], 0)
        df["dry_supply_score"] = np.where(df["dry_supply_flag"], cfg["supply_exhaustion_points"], 0)
        df["absorption_score"] = np.where(df["absorption_active"], cfg["absorption_points"], 0)
        df["obv_divergence_score"] = np.where(df["obv_divergence"], cfg["obv_divergence_points"], 0)
        df["accumulation_score"] = (
            df["bb_width_score"] + df["dry_supply_score"]
            + df["absorption_score"] + df["obv_divergence_score"]
        )

        # Step 8: Signal Generation -- both gates required at every tier.
        gates = df["is_consolidating"] & df["macd_confirmation"]
        df["signal_type"] = np.select(
            [
                (df["accumulation_score"] >= cfg["extreme_threshold"]) & gates,
                (df["accumulation_score"] >= cfg["ready_threshold"]) & gates,
                (df["accumulation_score"] >= cfg["watch_threshold"]) & gates,
            ],
            ["EXTREME", "READY", "WATCH"],
            default="NO_SIGNAL",
        )

        return df

    def prepare_for_db_and_ui(self, df: pd.DataFrame, symbol: str, scan_date: str) -> dict:
        """Clean and format the LATEST row of detect_stealth_accumulation()'s
        output for Turso insertion + Streamlit display. NaN -> 0/False,
        floats rounded to 2 decimals, numpy scalars -> native Python."""
        if df.empty:
            raise ValueError(f"{symbol}: empty DataFrame, nothing to prepare")
        row = df.iloc[-1]

        def _f(key, default=0.0):
            val = row.get(key)
            return default if val is None or pd.isna(val) else round(float(val), 2)

        def _b(key):
            val = row.get(key)
            return bool(val) if val is not None and not pd.isna(val) else False

        def _i(key, default=0):
            val = row.get(key)
            return default if val is None or pd.isna(val) else int(val)

        components = {
            "bb_compression": _b("bb_compression"),
            "supply_exhaustion": _b("dry_supply_flag"),
            "absorption": _b("absorption_active"),
            "obv_divergence": _b("obv_divergence"),
            "is_consolidating": _b("is_consolidating"),
            "macd_confirmation": _b("macd_confirmation"),
        }

        import json
        return {
            "symbol": symbol,
            "scan_date": scan_date,
            "accumulation_score": _i("accumulation_score"),
            "signal_type": str(row.get("signal_type", "NO_SIGNAL")),
            "bb_width_score": _i("bb_width_score"),
            "dry_supply_score": _i("dry_supply_score"),
            "absorption_score": _i("absorption_score"),
            "obv_divergence_score": _i("obv_divergence_score"),
            "is_consolidating": _b("is_consolidating"),
            "macd_confirmation": _b("macd_confirmation"),
            "bb_width": _f("bb_width"),
            "obv_slope": _f("obv_slope"),
            "price_slope": _f("price_slope"),
            "consolidation_pct": _f("consolidation_pct"),
            "consolidation_atr": _f("consolidation_atr"),
            "spread_atr_ratio": _f("spread_atr_ratio"),
            "co_atr_ratio": _f("co_atr_ratio"),
            "volume_sma_20": _i("volume_sma_20"),
            "atr_14": _f("atr_14"),
            "current_price": _f("close"),
            "current_volume": _i("volume"),
            "components": json.dumps(components),
        }
