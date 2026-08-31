"""advanced_pattern_engine.py — deterministic, auditable chart-pattern
detector for PSX daily OHLCV data: Inverse Head & Shoulders and Eve & Eve
Double Bottom.

================================================================================
§0. NO-LOOKAHEAD -- THE HIGHEST-PRIORITY REQUIREMENT IN THIS MODULE
================================================================================
A swing pivot at bar i cannot be known at bar i -- it needs k bars to its
RIGHT to confirm (see pivots.py). Every Pivot therefore carries both its
own index/date and confirmed_at_index/confirmed_at_date = index + k.

Enforced here by construction, not by hope:
  - A pattern is only ASSEMBLED from pivots pivots.find_pivots already
    returned, which are themselves only ever built from bars at or before
    the point being evaluated (the caller controls how much history it
    hands in -- see the lookahead test in test_advanced_patterns.py, which
    proves a truncated series produces the identical signal set).
  - A breakout is only ever searched for on bars at or after
    max(confirmed_at_index) across all of a pattern's pivots -- see
    _scan_breakout.
  - `signal_date`/`signal_index` are ALWAYS the breakout bar, never a pivot
    bar.
  - `_assert_no_lookahead` is called immediately before every signal is
    emitted and raises if any pivot or the breakout bar itself has an
    index greater than the evaluation index being used.

================================================================================
§11. DOCUMENTATION HONESTY -- read before trusting any number this emits
================================================================================
Bulkowski reports an ~83% breakout-direction rate for inverse head-and-
shoulders and ~88% for Eve & Eve double bottoms. These are NOT win rates.
They measure how often price continued in the breakout direction to an
ultimate extreme, in US equities, in bull markets, with no stop loss,
commission, or slippage. The proportion of trades reaching a measured-move
target before stopping out is substantially lower. None of these figures
have been validated on PSX. Treat them as a prior to be tested, not as
this engine's expected performance. Nothing in this file claims a win
rate, and nothing should be added that does.

All non-Nison/non-Bulkowski numerical thresholds (amplitude %, symmetry %,
span limits, V-ness ratio, etc.) are STARTING GUESSES requiring PSX
calibration, not researched constants -- every one is a named, documented
constructor parameter for exactly this reason. See README_advanced_pattern_engine.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

from pivots import Pivot, find_pivots

ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class AdvancedPatternConfig:
    """Every tunable threshold, named and defaulted in one place. Defaults
    are starting guesses (per spec §11 / the README), not researched PSX
    constants."""

    # Pivot detection (pivots.py)
    k: int = 5
    min_swing_pct: float = 3.0
    atr_multiplier: float = 1.5

    # Pre-flight validation (§1)
    min_history_sessions: int = 200
    min_traded_sessions_ratio: float = 0.90
    min_turnover_pkr: float = 5_000_000.0
    unadjusted_gap_pct: float = 15.0

    # Prior trend prerequisite (§3)
    prior_decline_pct: float = 10.0
    prior_decline_min_sessions: int = 20
    prior_decline_max_sessions: int = 40

    # Inverse H&S (§4)
    ihs_head_discount_pct: float = 2.0          # hard filter: head >=2% below both shoulders
    ihs_shoulder_symmetry_max_pct: float = 5.0   # hard filter
    ihs_min_span: int = 25  # PSX calibration, 2026-08-29: was 40 -- 2021-2026 full-universe scan showed a
                            # valid-looking IHS completing in 28 sessions, rejected by the US-equity-derived
                            # default; ihs_max_span (150) left untouched
    ihs_max_span: int = 150
    neckline_mode: str = "horizontal_max"        # or "sloped"

    # Breakout (§4.4 / §5.5, shared)
    breakout_vol_mult: float = 1.5
    confirmation_window: int = 30

    # Double bottom (§5)
    bottom_tolerance_pct: float = 6.0  # PSX calibration, 2026-08-29: was 3.0 -- 2021-2026 full-universe scan
                                        # showed a legitimate-looking double bottom at 12.62% misalignment,
                                        # rejected by the US-equity-derived default
    min_peak_rise_pct: float = 8.0
    db_min_spacing: int = 15
    db_max_spacing: int = 60
    flat_band_pct: float = 3.0
    min_flat_bars: int = 3
    min_trough_width: int = 7
    max_vness: float = 1.2

    # Risk/reward
    min_risk_reward_measured: float = 1.0  # gate -- see stop_loss/risk_reward_measured in README
    # CALIBRATION ROUND 3, Change 2: the Round-2 two-stop system (pattern-
    # geometry ATR stop vs a flat 8% entry-based stop, tighter wins) turned
    # out to be dead code -- Investigation 3 on the 5-year backtest found
    # the flat 8% stop bound 100% of the time, 0% from the ATR/pattern-low
    # stop. Replaced with a single volatility-scaled stop.
    #
    # STOP FORMULA FINAL (Round 4, iteration 2): the Round 3/4 flat
    # max_loss_pct cap (first 8%, then 5%) was retired entirely in favor
    # of a pure ATR stop -- a diagnostic on Group B (the 230 double-bottom
    # signals present under both the 8% and 5% caps) found 16 signals that
    # would have hit TARGET_1 or TARGET_2 under the 8% cap got STOPPED_OUT
    # under the 5% cap, all 16 bound by the flat cap itself, not by ATR.
    #
    # STOP FORMULA ITERATION 3: the pure-ATR run (no bound at all) then
    # produced stop distances up to 12.36% and a worse avg_loss_when_stopped
    # (-8.25%) -- some PSX names have an ATR/price ratio high enough that
    # 2x ATR alone is wider than the pattern provides edge for. A literal
    # "clip(atr14*atr_stop_mult, atr14*min_atr_mult, atr14*max_atr_mult)"
    # bound (as originally proposed with min_atr_mult=1.5, max_atr_mult=3.0)
    # is a mathematical no-op: clip(k*x, a*x, b*x) == k*x for any x >= 0
    # whenever a <= k <= b, which holds here for every ATR value since the
    # bounds are just fixed multiples of the SAME atr14 being bounded --
    # it would have reproduced the pure-ATR run byte-for-byte. Flagged and
    # confirmed with the user before implementing an alternative that
    # actually binds: bound the ATR/price RATIO itself (min_atr_ratio/
    # max_atr_ratio below), which is independent of the individual stock's
    # raw atr14, before multiplying by atr_stop_mult.
    atr_stop_mult: float = 2.0
    # Floor/ceiling on atr14/entry_price BEFORE multiplying by
    # atr_stop_mult -- NOT multiples of atr_stop_mult (see above for why
    # that formulation cannot bind). Defaults chosen to keep the 16
    # Group-B winners' stops (observed ~6-7%) unclamped while cutting the
    # pure-ATR run's 12.36% tail: min_atr_ratio=1.5% -> floor stop 3.0% at
    # atr_stop_mult=2.0; max_atr_ratio=3.5% -> ceiling stop 7.0%.
    min_atr_ratio: float = 0.015
    max_atr_ratio: float = 0.035
    throwback_risk_pct: float = 5.0

    # Head & Shoulders Top (bearish mirror of Inverse H&S) -- own fields,
    # not reused from ihs_*, so calibrating one pattern never silently
    # moves the other. Defaults mirror IHS's own starting-guess values
    # exactly (same reasoning, same numbers) except hst_breakout_vol_mult,
    # which is 1.3 per explicit spec, not the shared breakout_vol_mult
    # (1.5) every other pattern in this engine uses.
    prior_rise_pct: float = 10.0
    prior_rise_min_sessions: int = 20
    prior_rise_max_sessions: int = 40
    hst_head_premium_pct: float = 2.0           # mirror of ihs_head_discount_pct
    hst_shoulder_symmetry_max_pct: float = 5.0   # mirror of ihs_shoulder_symmetry_max_pct
    hst_min_span: int = 25                       # mirror of ihs_min_span
    hst_max_span: int = 150                      # mirror of ihs_max_span
    hst_breakout_vol_mult: float = 1.3           # per exact spec -- NOT breakout_vol_mult (1.5)

    engine_version: str = ENGINE_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


# ============================================================== scoring ==
def _linear_ramp(value: float, zero_at: float, full_at: float) -> float:
    """0 at `zero_at`, 1 at `full_at`, linear between, clipped outside.
    Works for either direction -- pass zero_at > full_at for a "smaller is
    better" ramp (e.g. shoulder symmetry)."""
    if pd.isna(value):
        return 0.0
    if full_at == zero_at:
        return 1.0 if value >= full_at else 0.0
    t = (value - zero_at) / (full_at - zero_at)
    return float(np.clip(t, 0.0, 1.0))


def _plateau_score(value: float, low_zero: float, low_full: float,
                    high_full: float, high_zero: float) -> float:
    """Full credit on [low_full, high_full], decaying linearly to 0 at
    low_zero/high_zero outside that plateau. Used for time_symmetry."""
    if pd.isna(value):
        return 0.0
    if low_full <= value <= high_full:
        return 1.0
    if value < low_full:
        return _linear_ramp(value, low_zero, low_full)
    return _linear_ramp(value, high_zero, high_full)


def score_ihs_confidence(shoulder_symmetry_pct: float, head_discount_pct: float,
                          volume_staircase_tier: str, breakout_vol_ratio: float,
                          prior_decline_pct_actual: float, time_symmetry_ratio: float) -> tuple[float, dict]:
    """§7 Inverse H&S table, implemented exactly: fixed weights summing to
    1.0, every component a pure function of its own inputs. Returns
    (total_score, component_breakdown) so any score is auditable."""
    components = {
        "shoulder_symmetry": 0.20 * _linear_ramp(shoulder_symmetry_pct, zero_at=5.0, full_at=2.0),
        "head_prominence": 0.15 * _linear_ramp(head_discount_pct, zero_at=2.0, full_at=5.0),
        "volume_staircase": 0.20 * {"full": 1.0, "partial": 0.5, "none": 0.0}[volume_staircase_tier],
        "breakout_volume": 0.20 * _linear_ramp(breakout_vol_ratio, zero_at=1.5, full_at=2.0),
        "prior_decline": 0.15 * _linear_ramp(prior_decline_pct_actual, zero_at=10.0, full_at=20.0),
        "time_symmetry": 0.10 * _plateau_score(time_symmetry_ratio, 0.5, 0.8, 1.25, 2.0),
    }
    return round(sum(components.values()), 4), {k: round(v, 4) for k, v in components.items()}


def score_double_bottom_confidence(bottom_alignment_pct: float, eve_count: int,
                                    undercut_pct: float, breakout_vol_ratio: float,
                                    prior_decline_pct_actual: float, peak_rise_pct: float) -> tuple[float, dict]:
    """§7 Double Bottom table. `eve_count` is 0/1/2 -- how many of the two
    troughs classified as Eve."""
    undercut_bonus = 1.0 if -3.0 <= undercut_pct <= 0.0 else 0.0
    components = {
        "bottom_alignment": 0.15 * _linear_ramp(bottom_alignment_pct, zero_at=3.0, full_at=1.0),
        # CALIBRATION ROUND 2, Fix 3: PSX 5-year backtest found ADAM_ADAM
        # win rate 73.3% vs EVE_EVE 49% -- the opposite of Bulkowski's
        # Eve-outperforms-Adam assumption the old {0:0.0,1:0.5,2:1.0}
        # lookup encoded. Now scores CONSISTENCY of trough character, not
        # "how many are Eve": both troughs the same shape (ADAM_ADAM or
        # EVE_EVE) get full credit; a mixed pair (EVE_ADAM/ADAM_EVE) gets
        # zero. eve_count==0 can only mean ADAM_ADAM and eve_count==2 can
        # only mean EVE_EVE (two troughs, each either eve or adam), so
        # this is still a pure function of eve_count -- only the mapping
        # changed.
        "eve_shape": 0.25 * {0: 1.0, 1: 0.0, 2: 1.0}[eve_count],
        "undercut_bonus": 0.10 * undercut_bonus,
        "breakout_volume": 0.20 * _linear_ramp(breakout_vol_ratio, zero_at=1.5, full_at=2.0),
        "prior_decline": 0.15 * _linear_ramp(prior_decline_pct_actual, zero_at=10.0, full_at=20.0),
        "peak_prominence": 0.15 * _linear_ramp(peak_rise_pct, zero_at=8.0, full_at=15.0),
    }
    return round(sum(components.values()), 4), {k: round(v, 4) for k, v in components.items()}


# ======================================================= lookahead guard ==
class LookaheadError(Exception):
    pass


def _assert_no_lookahead(referenced_indices: list[int], eval_index: int, context: str) -> None:
    """Raises if any index a pattern is about to emit a signal from (a
    pivot's own bar, or the breakout bar) exceeds eval_index -- the bar the
    signal is being evaluated/emitted on. Called immediately before every
    signal is emitted; never bypassed."""
    bad = [i for i in referenced_indices if i > eval_index]
    if bad:
        raise LookaheadError(f"{context}: indices {bad} exceed eval_index {eval_index}")


# ============================================================= engine ====
class AdvancedPatternEngine:
    """Detects Inverse Head & Shoulders and Eve & Eve Double Bottom
    patterns across many PSX symbols. See module docstring §0 for the
    no-lookahead contract and §11 for the Bulkowski-figures disclaimer.

    Usage:
        engine = AdvancedPatternEngine()
        result = engine.scan(df_long, known_signal_keys=previously_seen_keys)
        result.signals_df   # one row per confirmed signal
        result.signals      # same, as a list of full dicts (pivots included)
        result.expired      # patterns whose breakout window lapsed
        result.rejected     # patterns that failed a hard filter, with reason
        result.all_signal_keys  # persist this and pass back in next time
    """

    def __init__(self, config: Optional[AdvancedPatternConfig] = None) -> None:
        self.config = config or AdvancedPatternConfig()

    # ------------------------------------------------------------ public --
    def scan(self, df_long: pd.DataFrame, known_signal_keys: Optional[set] = None) -> "ScanResult":
        known_signal_keys = set(known_signal_keys or set())
        signals: list[dict] = []
        expired: list[dict] = []
        rejected: list[dict] = []
        new_keys: set = set()

        if df_long is None or len(df_long) == 0:
            return ScanResult(pd.DataFrame(), [], [], [], known_signal_keys)

        required_cols = {"symbol", "date", "open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df_long.columns):
            return ScanResult(pd.DataFrame(), [], [], [], known_signal_keys)

        for symbol, raw in df_long.groupby("symbol", sort=False):
            df = raw.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

            ok, reason = self._preflight(df)
            if not ok:
                rejected.append({"symbol": symbol, "pattern_type": None, "reason": reason})
                continue

            enriched = self._enrich(df)
            pivots = find_pivots(enriched, k=self.config.k, min_swing_pct=self.config.min_swing_pct,
                                  atr_multiplier=self.config.atr_multiplier)
            if len(pivots) < 3:
                continue

            for sig in self._scan_inverse_hs(symbol, enriched, pivots):
                self._route(sig, known_signal_keys, new_keys, signals, expired, rejected)
            for sig in self._scan_double_bottom(symbol, enriched, pivots):
                self._route(sig, known_signal_keys, new_keys, signals, expired, rejected)

        signals_df = pd.DataFrame(signals) if signals else pd.DataFrame(columns=_OUTPUT_COLUMNS)
        return ScanResult(signals_df, signals, expired, rejected, known_signal_keys | new_keys)

    # ------------------------------------------------ public: H&S Top -----
    def detect_head_shoulders_top(self, df_long: pd.DataFrame, known_signal_keys: Optional[set] = None) -> "ScanResult":
        """Independently-callable entry point for Head & Shoulders Top
        ONLY -- mirrors scan()'s exact per-symbol pipeline (pre-flight,
        enrich, find_pivots with the SAME k/min_swing_pct/atr_multiplier)
        but runs _scan_head_shoulders_top instead of the two bullish
        pattern scans. scan() itself is UNCHANGED -- still only IHS +
        Double Bottom, exactly as before. Kept as a separate method
        (not folded into scan()) because Head & Shoulders Top has not
        been backtested yet and must not be wired into any live caller
        of scan() by accident."""
        known_signal_keys = set(known_signal_keys or set())
        signals: list[dict] = []
        expired: list[dict] = []
        rejected: list[dict] = []
        new_keys: set = set()

        if df_long is None or len(df_long) == 0:
            return ScanResult(pd.DataFrame(), [], [], [], known_signal_keys)

        required_cols = {"symbol", "date", "open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df_long.columns):
            return ScanResult(pd.DataFrame(), [], [], [], known_signal_keys)

        for symbol, raw in df_long.groupby("symbol", sort=False):
            df = raw.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

            ok, reason = self._preflight(df)
            if not ok:
                rejected.append({"symbol": symbol, "pattern_type": None, "reason": reason})
                continue

            enriched = self._enrich(df)
            pivots = find_pivots(enriched, k=self.config.k, min_swing_pct=self.config.min_swing_pct,
                                  atr_multiplier=self.config.atr_multiplier)
            if len(pivots) < 5:
                continue

            for sig in self._scan_head_shoulders_top(symbol, enriched, pivots):
                self._route(sig, known_signal_keys, new_keys, signals, expired, rejected)

        signals_df = pd.DataFrame(signals) if signals else pd.DataFrame(columns=_HST_OUTPUT_COLUMNS)
        return ScanResult(signals_df, signals, expired, rejected, known_signal_keys | new_keys)

    @staticmethod
    def _route(sig: dict, known_keys: set, new_keys: set, signals: list, expired: list, rejected: list) -> None:
        if sig["_status"] == "rejected":
            rejected.append(sig)
            return
        if sig["_status"] == "expired":
            expired.append(sig)
            return
        key = sig["_dedup_key"]
        if key in known_keys or key in new_keys:
            return  # already emitted in a prior scan -- do not re-emit
        new_keys.add(key)
        signals.append({k: v for k, v in sig.items() if not k.startswith("_")})

    # --------------------------------------------------- §1 pre-flight ----
    def _preflight(self, df: pd.DataFrame) -> tuple[bool, Optional[str]]:
        cfg = self.config
        if len(df) < cfg.min_history_sessions:
            return False, "insufficient_history"
        if not df["date"].is_monotonic_increasing:
            return False, "unsorted_dates"  # already sorted above, defensive
        if df["date"].duplicated().any():
            return False, "duplicate_dates"  # already deduped above, defensive

        traded_ratio = (df["volume"] > 0).mean()
        if traded_ratio < cfg.min_traded_sessions_ratio:
            return False, "too_illiquid"

        turnover = (df["close"] * df["volume"]).rolling(20, min_periods=20).mean()
        if turnover.median(skipna=True) < cfg.min_turnover_pkr or pd.isna(turnover.median(skipna=True)):
            return False, "untradeable_turnover"

        prev_close = df["close"].shift(1)
        gap_pct = (df["close"] - prev_close).abs() / prev_close.replace(0, np.nan) * 100.0
        vol_avg = df["volume"].rolling(20, min_periods=5).mean()
        unmatched_gap = (gap_pct > cfg.unadjusted_gap_pct) & (df["volume"] < 1.5 * vol_avg)
        if unmatched_gap.fillna(False).any():
            return False, "unadjusted_corporate_action_suspected"

        return True, None

    # ------------------------------------------------------ §1 PSX flags --
    def _enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adds is_locked, atr14 (Wilder's, locked bars excluded), and
        avg_volume_20 (locked bars excluded) -- every other method in this
        class reads these columns rather than recomputing them."""
        work = df.copy()
        median_vol = work.loc[work["volume"] > 0, "volume"].median()
        abnormally_low_vol = work["volume"] < (0.1 * median_vol if pd.notna(median_vol) and median_vol > 0 else 1)
        work["is_locked"] = (work["high"] == work["low"]) & abnormally_low_vol

        prev_close = work["close"].shift(1)
        true_range = pd.concat([
            work["high"] - work["low"],
            (work["high"] - prev_close).abs(),
            (work["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        true_range_for_atr = true_range.where(~work["is_locked"])
        work["atr14"] = true_range_for_atr.ewm(alpha=1.0 / 14, adjust=False, ignore_na=True,
                                                min_periods=14).mean()

        volume_for_avg = work["volume"].where(~work["is_locked"])
        work["avg_volume_20"] = volume_for_avg.rolling(20, min_periods=10).mean()
        return work

    # -------------------------------------------------- §3 prior trend ----
    def _prior_trend(self, df: pd.DataFrame, first_trough_index: int) -> tuple[bool, float, int]:
        """Looks back over the min..max session window immediately before
        the first trough, finds the actual highest high in that window,
        and measures the decline from THAT specific high to the trough.
        Returns (ok, prior_decline_pct_actual, prior_decline_sessions)."""
        cfg = self.config
        lookback_start = max(0, first_trough_index - cfg.prior_decline_max_sessions)
        if lookback_start >= first_trough_index:
            return False, 0.0, 0
        window = df["high"].iloc[lookback_start:first_trough_index]
        if window.empty:
            return False, 0.0, 0
        pre_high = float(window.max())
        pre_high_index = lookback_start + int(window.values.argmax())
        sessions = first_trough_index - pre_high_index
        trough_low = float(df["low"].iloc[first_trough_index])
        decline_pct = (pre_high - trough_low) / pre_high * 100.0 if pre_high else 0.0
        ok = (decline_pct >= cfg.prior_decline_pct
              and cfg.prior_decline_min_sessions <= sessions <= cfg.prior_decline_max_sessions)
        return ok, round(decline_pct, 2), sessions

    def _prior_uptrend(self, df: pd.DataFrame, first_peak_index: int) -> tuple[bool, float, int]:
        """Exact mirror of _prior_trend, direction inverted, for Head &
        Shoulders Top's "clear prior UPTREND" requirement: looks back
        over the min..max session window immediately before the left
        shoulder, finds the actual LOWEST low in that window, and
        measures the RISE from that low to the left shoulder's high.
        Returns (ok, prior_rise_pct_actual, prior_rise_sessions)."""
        cfg = self.config
        lookback_start = max(0, first_peak_index - cfg.prior_rise_max_sessions)
        if lookback_start >= first_peak_index:
            return False, 0.0, 0
        window = df["low"].iloc[lookback_start:first_peak_index]
        if window.empty:
            return False, 0.0, 0
        pre_low = float(window.min())
        pre_low_index = lookback_start + int(window.values.argmin())
        sessions = first_peak_index - pre_low_index
        peak_high = float(df["high"].iloc[first_peak_index])
        rise_pct = (peak_high - pre_low) / pre_low * 100.0 if pre_low else 0.0
        ok = (rise_pct >= cfg.prior_rise_pct
              and cfg.prior_rise_min_sessions <= sessions <= cfg.prior_rise_max_sessions)
        return ok, round(rise_pct, 2), sessions

    # --------------------------------------------------- shared breakout --
    def _scan_breakout(self, df: pd.DataFrame, level_at_bar, confirmed_from_index: int,
                        direction: str = "above", vol_mult_override: Optional[float] = None) -> Optional[dict]:
        """Scans forward from confirmed_from_index for the first bar whose
        CLOSE strictly crosses `level_at_bar(bar_index)` (a callable, so the
        sloped-neckline case can vary the level per bar) on
        >= breakout_vol_mult x the 20-session average volume (locked bars
        excluded). Returns None (caller logs "expired") if no qualifying
        bar appears within confirmation_window sessions.

        `direction` ("above"/"below") and `vol_mult_override` are additive,
        backward-compatible parameters -- every existing caller (IHS,
        Double Bottom, Cup & Handle, Ascending Triangle) passes neither,
        so their behavior is byte-for-byte unchanged (strictly above the
        level, on cfg.breakout_vol_mult). Added for Head & Shoulders Top,
        which needs a downside breakout (close strictly BELOW the
        neckline) on a per-spec 1.3x volume floor, not the shared 1.5x
        breakout_vol_mult every other pattern in this engine uses."""
        cfg = self.config
        vol_mult = vol_mult_override if vol_mult_override is not None else cfg.breakout_vol_mult
        last_index = min(len(df) - 1, confirmed_from_index + cfg.confirmation_window)
        for i in range(confirmed_from_index, last_index + 1):
            level = level_at_bar(i)
            if pd.isna(level):
                continue
            close = df["close"].iat[i]
            avg_vol = df["avg_volume_20"].iat[i]
            vol = df["volume"].iat[i]
            crossed = (close > level) if direction == "above" else (close < level)
            if crossed and pd.notna(avg_vol) and avg_vol > 0 and vol >= vol_mult * avg_vol:
                return {"breakout_index": i, "breakout_date": df["date"].iat[i], "level": level}
        return None

    # =============================================== §4 Inverse H&S ======
    def _scan_inverse_hs(self, symbol: str, df: pd.DataFrame, pivots: list[Pivot]) -> list[dict]:
        cfg = self.config
        out = []
        for j in range(len(pivots) - 4):
            window = pivots[j:j + 5]
            if window[0].kind != "low":
                continue
            t1, p1, t2, p2, t3 = window

            span = t3.index - t1.index
            if not (cfg.ihs_min_span <= span <= cfg.ihs_max_span):
                out.append(self._rejected("INVERSE_HS", symbol, t1, t3, "span_out_of_range"))
                continue

            head_below_shoulders = (t2.price < t1.price * (1 - cfg.ihs_head_discount_pct / 100.0)
                                     and t2.price < t3.price * (1 - cfg.ihs_head_discount_pct / 100.0))
            if not head_below_shoulders:
                out.append(self._rejected("INVERSE_HS", symbol, t1, t3, "head_not_below_shoulders"))
                continue

            shoulder_symmetry_pct = abs(t1.price - t3.price) / min(t1.price, t3.price) * 100.0
            if shoulder_symmetry_pct > cfg.ihs_shoulder_symmetry_max_pct:
                out.append(self._rejected("INVERSE_HS", symbol, t1, t3, "shoulders_not_symmetric"))
                continue

            trend_ok, decline_pct_actual, decline_sessions = self._prior_trend(df, t1.index)
            if not trend_ok:
                out.append(self._rejected("INVERSE_HS", symbol, t1, t3, "no_prior_downtrend"))
                continue

            max_confirmed = max(t1.confirmed_at_index, p1.confirmed_at_index, t2.confirmed_at_index,
                                 p2.confirmed_at_index, t3.confirmed_at_index)
            _assert_no_lookahead([t1.index, p1.index, t2.index, p2.index, t3.index],
                                  max_confirmed, "IHS pre-breakout pivot check")

            neckline_horizontal = max(p1.price, p2.price)
            slope = (p2.price - p1.price) / (p2.index - p1.index) if p2.index != p1.index else 0.0

            def sloped_level(i, _p1=p1, _slope=slope):
                return p1.price + _slope * (i - _p1.index)

            neckline_mode_fn = sloped_level if cfg.neckline_mode == "sloped" else (lambda i: neckline_horizontal)

            breakout = self._scan_breakout(df, neckline_mode_fn, max_confirmed)
            if breakout is None:
                out.append(self._expired("INVERSE_HS", symbol, t1, t2, t3, max_confirmed))
                continue

            _assert_no_lookahead([t1.index, p1.index, t2.index, p2.index, t3.index, breakout["breakout_index"]],
                                  breakout["breakout_index"], "IHS breakout emission")

            sig = self._build_ihs_signal(symbol, df, t1, p1, t2, p2, t3, breakout, neckline_horizontal,
                                          shoulder_symmetry_pct, decline_pct_actual, decline_sessions)
            out.append(sig)
        return out

    def _build_ihs_signal(self, symbol, df, t1, p1, t2, p2, t3, breakout, neckline_horizontal,
                           shoulder_symmetry_pct, decline_pct_actual, decline_sessions) -> dict:
        cfg = self.config
        k = cfg.k
        vol_ls = float(df["volume"].iloc[max(0, t1.index - k):t1.index + k + 1].mean())
        vol_head = float(df["volume"].iloc[max(0, t2.index - k):t2.index + k + 1].mean())
        vol_rs = float(df["volume"].iloc[max(0, t3.index - k):t3.index + k + 1].mean())
        if vol_rs < vol_head < vol_ls:
            tier = "full"
        elif vol_rs < vol_ls:
            tier = "partial"
        else:
            tier = "none"

        time_symmetry_ratio = ((t2.index - t1.index) / (t3.index - t2.index)
                                if (t3.index - t2.index) != 0 else np.nan)

        bi = breakout["breakout_index"]
        entry_price = float(df["close"].iat[bi])
        atr14 = float(df["atr14"].iat[bi]) if pd.notna(df["atr14"].iat[bi]) else 0.0
        pattern_low = t2.price
        slope = (p2.price - p1.price) / (p2.index - p1.index) if p2.index != p1.index else 0.0
        neckline_sloped = p1.price + slope * (bi - p1.index)
        neckline_at_breakout = neckline_sloped if cfg.neckline_mode == "sloped" else neckline_horizontal

        # STOP FORMULA ITERATION 3: ATR/price ratio bounded BEFORE
        # multiplying by atr_stop_mult, floored at pattern_low. See the
        # config-level comment on min_atr_ratio/max_atr_ratio.
        atr_ratio = (atr14 / entry_price) if entry_price else 0.0
        atr_ratio_bounded = min(max(atr_ratio, cfg.min_atr_ratio), cfg.max_atr_ratio)
        stop_loss_atr_component = atr_ratio_bounded * entry_price * cfg.atr_stop_mult
        stop_loss_final = max(entry_price - stop_loss_atr_component, pattern_low)
        stop_loss_pct_from_entry = (entry_price - stop_loss_final) / entry_price if entry_price else 0.0
        pattern_height = neckline_at_breakout - pattern_low
        target_partial = neckline_at_breakout + 0.5 * pattern_height       # target_1 -- unchanged
        # CALIBRATION ROUND 2, Fix 1: the full measured move (1.0x height)
        # was never reached in 139 signals over 5 years of PSX data --
        # target_measured now means the 0.75x target (what the adapter
        # exposes as target_2, and what risk_reward_measured gates on).
        # target_full_measured (target_3) is the old 1.0x value, kept for
        # reference only -- never used in any gate.
        target_measured = neckline_at_breakout + 0.75 * pattern_height     # target_2
        target_full_measured = neckline_at_breakout + pattern_height       # target_3, reference only
        risk = entry_price - stop_loss_final
        target_breakeven = entry_price + risk if risk > 0 else np.nan
        rr_partial = (target_partial - entry_price) / risk if risk > 0 else np.nan
        rr_measured = (target_measured - entry_price) / risk if risk > 0 else np.nan

        if pd.isna(rr_measured) or rr_measured < cfg.min_risk_reward_measured:
            return self._rejected("INVERSE_HS", symbol, t1, t3, "risk_reward_measured_below_minimum")

        avg_vol20_bo = float(df["avg_volume_20"].iat[bi]) if pd.notna(df["avg_volume_20"].iat[bi]) else np.nan
        breakout_volume = float(df["volume"].iat[bi])
        breakout_vol_ratio = breakout_volume / avg_vol20_bo if avg_vol20_bo else np.nan

        confidence_score, confidence_components = score_ihs_confidence(
            shoulder_symmetry_pct, head_discount_pct=(1 - t2.price / min(t1.price, t3.price)) * 100.0,
            volume_staircase_tier=tier, breakout_vol_ratio=breakout_vol_ratio,
            prior_decline_pct_actual=decline_pct_actual, time_symmetry_ratio=time_symmetry_ratio)

        throwback_risk = bool(entry_price > neckline_at_breakout * (1 + cfg.throwback_risk_pct / 100.0))

        pivots_out = [self._pivot_dict(p) for p in (t1, p1, t2, p2, t3)]
        dedup_key = (symbol, "INVERSE_HS", t1.date, t2.date, t3.date)

        return {
            "_status": "signal", "_dedup_key": dedup_key,
            "symbol": symbol, "pattern_type": "INVERSE_HS", "pattern_subtype": "INVERSE_HS",
            "signal_date": breakout["breakout_date"], "signal_index": bi,
            "pivots": pivots_out,
            "neckline_price": neckline_at_breakout, "neckline_mode": cfg.neckline_mode,
            "neckline_horizontal": neckline_horizontal, "neckline_sloped": neckline_sloped,
            "prior_decline_pct_actual": decline_pct_actual, "prior_decline_sessions": decline_sessions,
            "pattern_span_sessions": t3.index - t1.index,
            "vol_ls": vol_ls, "vol_head": vol_head, "vol_rs": vol_rs,
            "breakout_volume": breakout_volume, "avg_volume_20": avg_vol20_bo,
            "breakout_volume_ratio": breakout_vol_ratio,
            "atr14": atr14, "entry_price": entry_price,
            "stop_loss": stop_loss_final,
            "stop_loss_atr_component": stop_loss_atr_component,
            "stop_loss_pct_from_entry": stop_loss_pct_from_entry,
            "target_breakeven": target_breakeven, "target_partial": target_partial,
            "target_measured": target_measured, "target_full_measured": target_full_measured,
            "risk_reward_partial": rr_partial, "risk_reward_measured": rr_measured,
            "throwback_risk": throwback_risk,
            "confidence_score": confidence_score, "confidence_components": confidence_components,
            "params_used": cfg.as_dict(), "engine_version": cfg.engine_version,
        }

    # ======================================= Head & Shoulders Top (bearish)
    def _scan_head_shoulders_top(self, symbol: str, df: pd.DataFrame, pivots: list[Pivot]) -> list[dict]:
        """Exact bearish mirror of _scan_inverse_hs: P1(high,left shoulder)
        -> T1(low) -> P2(high,head) -> T2(low) -> P3(high,right shoulder),
        high-first (the natural inversion of IHS's low-first window)."""
        cfg = self.config
        out = []
        for j in range(len(pivots) - 4):
            window = pivots[j:j + 5]
            if window[0].kind != "high":
                continue
            p1, t1, p2, t2, p3 = window

            span = p3.index - p1.index
            if not (cfg.hst_min_span <= span <= cfg.hst_max_span):
                out.append(self._rejected("HEAD_SHOULDERS_TOP", symbol, p1, p3, "span_out_of_range"))
                continue

            head_above_shoulders = (p2.price > p1.price * (1 + cfg.hst_head_premium_pct / 100.0)
                                     and p2.price > p3.price * (1 + cfg.hst_head_premium_pct / 100.0))
            if not head_above_shoulders:
                out.append(self._rejected("HEAD_SHOULDERS_TOP", symbol, p1, p3, "head_not_above_shoulders"))
                continue

            shoulder_symmetry_pct = abs(p1.price - p3.price) / min(p1.price, p3.price) * 100.0
            if shoulder_symmetry_pct > cfg.hst_shoulder_symmetry_max_pct:
                out.append(self._rejected("HEAD_SHOULDERS_TOP", symbol, p1, p3, "shoulders_not_symmetric"))
                continue

            trend_ok, rise_pct_actual, rise_sessions = self._prior_uptrend(df, p1.index)
            if not trend_ok:
                out.append(self._rejected("HEAD_SHOULDERS_TOP", symbol, p1, p3, "no_prior_uptrend"))
                continue

            max_confirmed = max(p1.confirmed_at_index, t1.confirmed_at_index, p2.confirmed_at_index,
                                 t2.confirmed_at_index, p3.confirmed_at_index)
            _assert_no_lookahead([p1.index, t1.index, p2.index, t2.index, p3.index],
                                  max_confirmed, "H&S Top pre-breakout pivot check")

            # Neckline: horizontal support at the LOWER of the two troughs
            # (mirror of IHS's neckline_horizontal = max of the two peaks).
            neckline_horizontal = min(t1.price, t2.price)

            breakout = self._scan_breakout(df, lambda i, _n=neckline_horizontal: _n, max_confirmed,
                                            direction="below", vol_mult_override=cfg.hst_breakout_vol_mult)
            if breakout is None:
                out.append(self._expired("HEAD_SHOULDERS_TOP", symbol, p1, t1, p2, t2, p3, max_confirmed))
                continue

            _assert_no_lookahead([p1.index, t1.index, p2.index, t2.index, p3.index, breakout["breakout_index"]],
                                  breakout["breakout_index"], "H&S Top breakout emission")

            sig = self._build_hst_signal(symbol, df, p1, t1, p2, t2, p3, breakout, neckline_horizontal,
                                          shoulder_symmetry_pct, rise_pct_actual, rise_sessions)
            out.append(sig)
        return out

    def _build_hst_signal(self, symbol, df, p1, t1, p2, t2, p3, breakout, neckline_horizontal,
                           shoulder_symmetry_pct, rise_pct_actual, rise_sessions) -> dict:
        cfg = self.config
        k = cfg.k
        # Volume staircase: LS highest, Head lower, RS lowest -- the exact
        # same direction/ordering as IHS's own tier test (vol_rs < vol_head
        # < vol_ls), reused verbatim since both patterns describe the same
        # "volume diminishes through the pattern" classical staircase.
        vol_ls = float(df["volume"].iloc[max(0, p1.index - k):p1.index + k + 1].mean())
        vol_head = float(df["volume"].iloc[max(0, p2.index - k):p2.index + k + 1].mean())
        vol_rs = float(df["volume"].iloc[max(0, p3.index - k):p3.index + k + 1].mean())
        if vol_rs < vol_head < vol_ls:
            tier = "full"
        elif vol_rs < vol_ls:
            tier = "partial"
        else:
            tier = "none"

        time_symmetry_ratio = ((p2.index - p1.index) / (p3.index - p2.index)
                                if (p3.index - p2.index) != 0 else np.nan)

        bi = breakout["breakout_index"]
        entry_price = float(df["close"].iat[bi])
        atr14 = float(df["atr14"].iat[bi]) if pd.notna(df["atr14"].iat[bi]) else 0.0
        # Structural ceiling: if price reclaims the head, the pattern
        # thesis (a failed high) is invalid -- mirror of IHS's pattern_low
        # floor at the head, just the other side of the trade.
        pattern_high = p2.price

        # Bounded-ATR stop -- IDENTICAL formula to IHS/Double Bottom,
        # added to the RIGHT SHOULDER HIGH instead of subtracted from
        # entry_price, per exact spec ("stop_loss: Right Shoulder High
        # (P3) + bounded-ATR component").
        atr_ratio = (atr14 / entry_price) if entry_price else 0.0
        atr_ratio_bounded = min(max(atr_ratio, cfg.min_atr_ratio), cfg.max_atr_ratio)
        stop_loss_atr_component = atr_ratio_bounded * entry_price * cfg.atr_stop_mult
        stop_loss_final = min(p3.price + stop_loss_atr_component, pattern_high)
        stop_loss_pct_from_entry = (stop_loss_final - entry_price) / entry_price if entry_price else 0.0

        pattern_height = pattern_high - neckline_horizontal  # Head High - Neckline, per exact spec
        target_partial = neckline_horizontal - 0.5 * pattern_height   # target_1
        target_measured = neckline_horizontal - 1.0 * pattern_height  # target_2 -- full measured move, per spec
        risk = stop_loss_final - entry_price
        target_breakeven = entry_price - risk if risk > 0 else np.nan
        rr_partial = (entry_price - target_partial) / risk if risk > 0 else np.nan
        rr_measured = (entry_price - target_measured) / risk if risk > 0 else np.nan

        if pd.isna(rr_measured) or rr_measured < cfg.min_risk_reward_measured:
            return self._rejected("HEAD_SHOULDERS_TOP", symbol, p1, p3, "risk_reward_measured_below_minimum")

        avg_vol20_bo = float(df["avg_volume_20"].iat[bi]) if pd.notna(df["avg_volume_20"].iat[bi]) else np.nan
        breakout_volume = float(df["volume"].iat[bi])
        breakout_vol_ratio = breakout_volume / avg_vol20_bo if avg_vol20_bo else np.nan

        # score_ihs_confidence's formula is direction-agnostic (every
        # component is a pure function of magnitudes/ratios, not raw
        # above/below comparisons) -- reused verbatim, not reimplemented.
        confidence_score, confidence_components = score_ihs_confidence(
            shoulder_symmetry_pct, head_discount_pct=(p2.price / max(p1.price, p3.price) - 1) * 100.0,
            volume_staircase_tier=tier, breakout_vol_ratio=breakout_vol_ratio,
            prior_decline_pct_actual=rise_pct_actual, time_symmetry_ratio=time_symmetry_ratio)

        throwback_risk = bool(entry_price < neckline_horizontal * (1 - cfg.throwback_risk_pct / 100.0))

        pivots_out = [self._pivot_dict(p) for p in (p1, t1, p2, t2, p3)]
        dedup_key = (symbol, "HEAD_SHOULDERS_TOP", p1.date, p2.date, p3.date)

        return {
            "_status": "signal", "_dedup_key": dedup_key,
            "symbol": symbol, "pattern_type": "HEAD_SHOULDERS_TOP", "pattern_subtype": "HEAD_SHOULDERS_TOP",
            "signal_date": breakout["breakout_date"], "signal_index": bi,
            "pivots": pivots_out,
            "neckline_price": neckline_horizontal, "neckline_mode": "horizontal_min",
            "neckline_horizontal": neckline_horizontal, "neckline_sloped": neckline_horizontal,
            "prior_rise_pct_actual": rise_pct_actual, "prior_rise_sessions": rise_sessions,
            "pattern_span_sessions": p3.index - p1.index,
            "vol_ls": vol_ls, "vol_head": vol_head, "vol_rs": vol_rs,
            "breakout_volume": breakout_volume, "avg_volume_20": avg_vol20_bo,
            "breakout_volume_ratio": breakout_vol_ratio,
            "atr14": atr14, "entry_price": entry_price,
            "stop_loss": stop_loss_final,
            "stop_loss_atr_component": stop_loss_atr_component,
            "stop_loss_pct_from_entry": stop_loss_pct_from_entry,
            "target_breakeven": target_breakeven, "target_partial": target_partial,
            "target_measured": target_measured,
            "risk_reward_partial": rr_partial, "risk_reward_measured": rr_measured,
            "throwback_risk": throwback_risk,
            "confidence_score": confidence_score, "confidence_components": confidence_components,
            "params_used": cfg.as_dict(), "engine_version": cfg.engine_version,
        }

    # =========================================== §5 Eve & Eve Double Bottom
    def _scan_double_bottom(self, symbol: str, df: pd.DataFrame, pivots: list[Pivot]) -> list[dict]:
        cfg = self.config
        out = []
        for j in range(len(pivots) - 2):
            triple = pivots[j:j + 3]
            if triple[0].kind != "low":
                continue
            b1, pk, b2 = triple

            spacing = b2.index - b1.index
            if not (cfg.db_min_spacing <= spacing <= cfg.db_max_spacing):
                out.append(self._rejected("DOUBLE_BOTTOM", symbol, b1, b2, "spacing_out_of_range"))
                continue

            alignment_pct = abs(b2.price - b1.price) / b1.price * 100.0 if b1.price else np.inf
            if alignment_pct > cfg.bottom_tolerance_pct:
                out.append(self._rejected("DOUBLE_BOTTOM", symbol, b1, b2, "bottoms_not_aligned"))
                continue

            peak_rise_pct = (pk.price - max(b1.price, b2.price)) / pk.price * 100.0 if pk.price else 0.0
            if peak_rise_pct < cfg.min_peak_rise_pct:
                out.append(self._rejected("DOUBLE_BOTTOM", symbol, b1, b2, "peak_not_prominent"))
                continue

            trend_ok, decline_pct_actual, decline_sessions = self._prior_trend(df, b1.index)
            if not trend_ok:
                out.append(self._rejected("DOUBLE_BOTTOM", symbol, b1, b2, "no_prior_downtrend"))
                continue

            max_confirmed = max(b1.confirmed_at_index, pk.confirmed_at_index, b2.confirmed_at_index)
            _assert_no_lookahead([b1.index, pk.index, b2.index], max_confirmed,
                                  "Double bottom pre-breakout pivot check")

            shape_b1 = self._eve_or_adam(df, b1, pivots)
            shape_b2 = self._eve_or_adam(df, b2, pivots)
            subtype = f"{shape_b1}_{shape_b2}".upper()

            breakout = self._scan_breakout(df, lambda i, _pk=pk: _pk.price, max_confirmed)
            if breakout is None:
                out.append(self._expired("DOUBLE_BOTTOM", symbol, b1, pk, b2, max_confirmed, subtype))
                continue

            _assert_no_lookahead([b1.index, pk.index, b2.index, breakout["breakout_index"]],
                                  breakout["breakout_index"], "Double bottom breakout emission")

            sig = self._build_db_signal(symbol, df, b1, pk, b2, breakout, alignment_pct, peak_rise_pct,
                                         decline_pct_actual, decline_sessions, subtype, shape_b1, shape_b2)
            out.append(sig)
        return out

    def _eve_or_adam(self, df: pd.DataFrame, trough: Pivot, pivots: list[Pivot]) -> str:
        """§5.3 -- three quantitative components, all required for "Eve"."""
        cfg = self.config
        k = cfg.k
        lo = max(0, trough.index - k)
        hi = min(len(df) - 1, trough.index + k)
        window_low = df["low"].iloc[lo:hi + 1]
        flat_band = trough.price * (1 + cfg.flat_band_pct / 100.0)
        flat_bars = int((window_low <= flat_band).sum())
        flatness_ok = flat_bars >= cfg.min_flat_bars

        bracketing_highs = [p for p in pivots if p.kind == "high"]
        before = [p for p in bracketing_highs if p.index < trough.index]
        after = [p for p in bracketing_highs if p.index > trough.index]
        if before and after:
            width = after[0].index - before[-1].index
        else:
            width = hi - lo
        width_ok = width >= cfg.min_trough_width

        depth_pct = (flat_band - trough.price) / trough.price * 100.0 if trough.price else 0.0
        # Use the bracketing highs (if available) for depth, matching the
        # spec's V-ness ratio intent (depth relative to the swing, not the
        # arbitrary flat_band reference) -- fall back to flat_band-derived
        # depth only when no bracketing highs exist yet.
        if before and after:
            bracket_high = max(before[-1].price, after[0].price)
            depth_pct = (bracket_high - trough.price) / bracket_high * 100.0 if bracket_high else 0.0
        vness = depth_pct / width if width else np.inf
        vness_ok = vness <= cfg.max_vness

        return "eve" if (flatness_ok and width_ok and vness_ok) else "adam"

    def _build_db_signal(self, symbol, df, b1, pk, b2, breakout, alignment_pct, peak_rise_pct,
                          decline_pct_actual, decline_sessions, subtype, shape_b1, shape_b2) -> dict:
        cfg = self.config
        undercut_pct = (b2.price - b1.price) / b1.price * 100.0 if b1.price else 0.0

        bi = breakout["breakout_index"]
        entry_price = float(df["close"].iat[bi])
        atr14 = float(df["atr14"].iat[bi]) if pd.notna(df["atr14"].iat[bi]) else 0.0
        pattern_low = min(b1.price, b2.price)
        neckline_at_breakout = pk.price

        # STOP FORMULA ITERATION 3: same ATR-ratio-bounded formula as IHS,
        # see the config-level comment on min_atr_ratio/max_atr_ratio.
        atr_ratio = (atr14 / entry_price) if entry_price else 0.0
        atr_ratio_bounded = min(max(atr_ratio, cfg.min_atr_ratio), cfg.max_atr_ratio)
        stop_loss_atr_component = atr_ratio_bounded * entry_price * cfg.atr_stop_mult
        stop_loss_final = max(entry_price - stop_loss_atr_component, pattern_low)
        stop_loss_pct_from_entry = (entry_price - stop_loss_final) / entry_price if entry_price else 0.0
        pattern_height = neckline_at_breakout - pattern_low
        target_partial = neckline_at_breakout + 0.5 * pattern_height       # target_1 -- unchanged
        target_measured = neckline_at_breakout + 0.75 * pattern_height     # target_2 -- Fix 1
        target_full_measured = neckline_at_breakout + pattern_height       # target_3, reference only
        risk = entry_price - stop_loss_final
        target_breakeven = entry_price + risk if risk > 0 else np.nan
        rr_partial = (target_partial - entry_price) / risk if risk > 0 else np.nan
        rr_measured = (target_measured - entry_price) / risk if risk > 0 else np.nan

        if pd.isna(rr_measured) or rr_measured < cfg.min_risk_reward_measured:
            return self._rejected("DOUBLE_BOTTOM", symbol, b1, b2, "risk_reward_measured_below_minimum")

        avg_vol20_bo = float(df["avg_volume_20"].iat[bi]) if pd.notna(df["avg_volume_20"].iat[bi]) else np.nan
        breakout_volume = float(df["volume"].iat[bi])
        breakout_vol_ratio = breakout_volume / avg_vol20_bo if avg_vol20_bo else np.nan

        eve_count = int(shape_b1 == "eve") + int(shape_b2 == "eve")
        confidence_score, confidence_components = score_double_bottom_confidence(
            alignment_pct, eve_count, undercut_pct, breakout_vol_ratio, decline_pct_actual, peak_rise_pct)

        throwback_risk = bool(entry_price > neckline_at_breakout * (1 + cfg.throwback_risk_pct / 100.0))

        pivots_out = [self._pivot_dict(p) for p in (b1, pk, b2)]
        dedup_key = (symbol, "DOUBLE_BOTTOM", b1.date, b2.date)

        return {
            "_status": "signal", "_dedup_key": dedup_key,
            "symbol": symbol, "pattern_type": "DOUBLE_BOTTOM", "pattern_subtype": subtype,
            "signal_date": breakout["breakout_date"], "signal_index": bi,
            "pivots": pivots_out,
            "neckline_price": neckline_at_breakout, "neckline_mode": "peak_high",
            "neckline_horizontal": neckline_at_breakout, "neckline_sloped": neckline_at_breakout,
            "prior_decline_pct_actual": decline_pct_actual, "prior_decline_sessions": decline_sessions,
            "pattern_span_sessions": b2.index - b1.index,
            "vol_ls": np.nan, "vol_head": np.nan, "vol_rs": np.nan,
            "breakout_volume": breakout_volume, "avg_volume_20": avg_vol20_bo,
            "breakout_volume_ratio": breakout_vol_ratio,
            "atr14": atr14, "entry_price": entry_price,
            "stop_loss": stop_loss_final,
            "stop_loss_atr_component": stop_loss_atr_component,
            "stop_loss_pct_from_entry": stop_loss_pct_from_entry,
            "target_breakeven": target_breakeven, "target_partial": target_partial,
            "target_measured": target_measured, "target_full_measured": target_full_measured,
            "risk_reward_partial": rr_partial, "risk_reward_measured": rr_measured,
            "throwback_risk": throwback_risk,
            "confidence_score": confidence_score, "confidence_components": confidence_components,
            "undercut_pct": round(undercut_pct, 2),
            "params_used": cfg.as_dict(), "engine_version": cfg.engine_version,
        }

    # --------------------------------------------------------- utilities --
    @staticmethod
    def _pivot_dict(p: Pivot) -> dict:
        return {"kind": p.kind, "date": p.date, "index": p.index, "price": p.price,
                "confirmed_at_date": p.confirmed_at_date}

    @staticmethod
    def _rejected(pattern_type: str, symbol: str, p_first: Pivot, p_last: Pivot, reason: str) -> dict:
        return {"_status": "rejected", "symbol": symbol, "pattern_type": pattern_type,
                "first_pivot_date": p_first.date, "last_pivot_date": p_last.date, "reason": reason}

    @staticmethod
    def _expired(pattern_type: str, symbol: str, *pivots_and_index, subtype: Optional[str] = None) -> dict:
        pivots = [p for p in pivots_and_index if isinstance(p, Pivot)]
        max_confirmed = [p for p in pivots_and_index if isinstance(p, int)][0]
        return {"_status": "expired", "symbol": symbol, "pattern_type": pattern_type,
                "pattern_subtype": subtype,
                "pivot_dates": [p.date for p in pivots], "confirmed_from_index": max_confirmed}


@dataclass
class ScanResult:
    signals_df: pd.DataFrame
    signals: list
    expired: list
    rejected: list
    all_signal_keys: set


_OUTPUT_COLUMNS = [
    "symbol", "pattern_type", "pattern_subtype", "signal_date", "signal_index", "pivots",
    "neckline_price", "neckline_mode", "neckline_horizontal", "neckline_sloped",
    "prior_decline_pct_actual", "prior_decline_sessions", "pattern_span_sessions",
    "vol_ls", "vol_head", "vol_rs", "breakout_volume", "avg_volume_20", "breakout_volume_ratio",
    "atr14", "entry_price", "stop_loss", "stop_loss_atr_component", "stop_loss_pct_from_entry",
    "target_breakeven", "target_partial", "target_measured", "target_full_measured",
    "risk_reward_partial", "risk_reward_measured", "throwback_risk",
    "confidence_score", "confidence_components", "params_used", "engine_version",
]

_HST_OUTPUT_COLUMNS = [
    "symbol", "pattern_type", "pattern_subtype", "signal_date", "signal_index", "pivots",
    "neckline_price", "neckline_mode", "neckline_horizontal", "neckline_sloped",
    "prior_rise_pct_actual", "prior_rise_sessions", "pattern_span_sessions",
    "vol_ls", "vol_head", "vol_rs", "breakout_volume", "avg_volume_20", "breakout_volume_ratio",
    "atr14", "entry_price", "stop_loss", "stop_loss_atr_component", "stop_loss_pct_from_entry",
    "target_breakeven", "target_partial", "target_measured",
    "risk_reward_partial", "risk_reward_measured", "throwback_risk",
    "confidence_score", "confidence_components", "params_used", "engine_version",
]
