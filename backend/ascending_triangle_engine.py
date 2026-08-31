"""ascending_triangle_engine.py — deterministic, auditable Ascending
Triangle detector for PSX daily OHLCV data, built on the exact same
architecture as advanced_pattern_engine.py and cup_handle_engine.py (§0
no-lookahead contract, §1 pre-flight, shared breakout scan, bounded-ATR
stop formula, same 16-key adapter schema).

================================================================================
§0. NO-LOOKAHEAD -- SAME CONTRACT AS advanced_pattern_engine.py
================================================================================
Identical guarantee, identical mechanism, reused rather than reimplemented:
  - Pivots come from pivots.find_pivots() and carry confirmed_at_index.
  - A breakout is only ever searched for on bars at or after
    max(confirmed_at_index) across T1/P1/T2/P2/T3/P3 -- via the SAME
    AdvancedPatternEngine._scan_breakout function.
  - signal_date/signal_index are always the breakout bar.
  - _assert_no_lookahead (imported, not reimplemented) is called
    immediately before every signal is emitted.

DIRECTION NOTE: like Cup & Handle, Ascending Triangle is a continuation
pattern requiring a prior UPTREND (not a decline) -- reuses
CupHandleEngine._prior_rise directly rather than duplicating it.

PIVOT WINDOW CONVENTION: T1-first (IHS convention), NOT high-first (Cup &
Handle convention) -- T1(low) -> P1(high) -> T2(low) -> P2(high) ->
T3(low) -> P3(high). Confirmed explicitly with the user; Cup & Handle's
high-first window was a design choice for that module specifically, not
a project-wide rule.

§11 DOCUMENTATION HONESTY: Bulkowski reports a ~76% breakout-direction
rate for symmetrical triangles in US equities (ascending triangles are
reported separately and likely higher, per the spec this was built
against, but that figure has NOT been validated on PSX). Nothing in this
file has been backtested yet. Treat any confidence_score this emits as a
geometric/volume quality score only, not a predictor of outcome.

All non-Bulkowski numerical thresholds below are STARTING GUESSES
requiring PSX calibration, not researched constants -- every one is a
named, documented constructor parameter for exactly this reason.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

from pivots import Pivot, find_pivots
from advanced_pattern_engine import (
    AdvancedPatternEngine,
    _assert_no_lookahead,
    _linear_ramp,
    _plateau_score,
)
from cup_handle_engine import CupHandleEngine

ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class AscendingTriangleConfig:
    """Every tunable threshold, named and defaulted in one place -- same
    discipline as AdvancedPatternConfig/CupHandleConfig. Defaults are
    starting guesses, not researched PSX constants."""

    # Pivot detection (pivots.py) -- same defaults as every other module.
    k: int = 5
    min_swing_pct: float = 3.0
    atr_multiplier: float = 1.5

    # Pre-flight validation -- same field names as AdvancedPatternConfig
    # on purpose: _preflight below calls AdvancedPatternEngine._preflight
    # directly (not reimplemented).
    min_history_sessions: int = 200
    min_traded_sessions_ratio: float = 0.90
    min_turnover_pkr: float = 5_000_000.0
    unadjusted_gap_pct: float = 15.0

    # Prior trend prerequisite -- RISE, not decline (continuation pattern,
    # same as Cup & Handle). Same field names as CupHandleConfig on
    # purpose: _prior_rise below calls CupHandleEngine._prior_rise
    # directly (not reimplemented).
    prior_rise_pct: float = 10.0
    prior_rise_min_sessions: int = 20
    prior_rise_max_sessions: int = 40

    # Triangle geometry
    # Starting guesses set from a structural pre-check on the PSX universe
    # (74 of 111 pre-flight-passing symbols showed the precursor geometry,
    # median span 37 sessions, min 19, max 59) -- NOT a backtest-derived
    # calibration, just the search range the pre-check itself used, widened
    # slightly past the observed max to avoid immediately rejecting
    # boundary cases.
    triangle_min_span: int = 15
    triangle_max_span: int = 75
    # "3+ swing highs within X% of each other" -- same tightness formula
    # as ihs_shoulder_symmetry_max_pct/rim_symmetry_max_pct.
    flat_top_max_pct: float = 3.0
    # Minimum % increment REQUIRED between each consecutive swing low --
    # deliberately not a bare strict inequality (T1<T2<T3). A 0.01% step
    # is not a meaningful rising support line; this is a genuinely new
    # kind of constraint (no existing pattern in this codebase has an
    # equivalent "minimum step between N consecutive points" filter to
    # copy from), confirmed explicitly with the user before building.
    ascending_low_min_step_pct: float = 1.0

    # Breakout (shared mechanism, reused from advanced_pattern_engine.py)
    breakout_vol_mult: float = 1.5
    confirmation_window: int = 30

    # Risk/reward
    min_risk_reward_measured: float = 1.0
    # Bounded-ATR stop formula -- IDENTICAL to AdvancedPatternConfig's/
    # CupHandleConfig's locked Round-4 formula, same field names, same
    # defaults, so all three engines' stops are directly comparable.
    atr_stop_mult: float = 2.0
    min_atr_ratio: float = 0.015
    max_atr_ratio: float = 0.035
    throwback_risk_pct: float = 5.0

    engine_version: str = ENGINE_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


# ============================================================== scoring ==
def score_ascending_triangle_confidence(flat_top_pct: float, low_steps_pct: list,
                                         breakout_vol_ratio: float, prior_rise_pct_actual: float,
                                         triangle_span: int, has_extra_ascending_low: bool,
                                         flat_top_max_pct: float, triangle_min_span: int,
                                         triangle_max_span: int) -> tuple[float, dict]:
    """Deterministic, weighted, auditable -- same structure as the other
    three scoring functions in this codebase. Weights sum to 1.0.

    ascending_low_consistency uses a coefficient of variation
    (stdev/mean of the consecutive-low % steps) -- standard, interpretable,
    no novel statistics, per explicit instruction. UNVALIDATED ON PSX:
    nothing about this formula's relationship to real outcome has been
    tested; it is a geometric-consistency measure only."""
    steps = np.asarray(low_steps_pct, dtype=float)
    mean_step = float(steps.mean()) if len(steps) else 0.0
    if mean_step == 0.0:
        consistency = 0.0
    else:
        cv = float(steps.std()) / mean_step
        consistency = 1.0 - float(np.clip(cv, 0.0, 1.0))

    components = {
        "flat_top_tightness": 0.20 * _linear_ramp(flat_top_pct, zero_at=flat_top_max_pct, full_at=1.0),
        "ascending_low_consistency": 0.20 * consistency,
        "breakout_volume": 0.20 * _linear_ramp(breakout_vol_ratio, zero_at=1.5, full_at=2.0),
        "prior_rise": 0.15 * _linear_ramp(prior_rise_pct_actual, zero_at=10.0, full_at=20.0),
        "triangle_span": 0.15 * _plateau_score(triangle_span, triangle_min_span, 25, 50, triangle_max_span),
        "low_count_bonus": 0.10 * (1.0 if has_extra_ascending_low else 0.0),
    }
    return round(sum(components.values()), 4), {k: round(v, 4) for k, v in components.items()}


# ============================================================= engine ====
class AscendingTriangleEngine:
    """Detects Ascending Triangle patterns across many PSX symbols. See
    module docstring §0 for the no-lookahead contract (identical to
    AdvancedPatternEngine's/CupHandleEngine's) and §11 for the
    Bulkowski-figures disclaimer.

    Usage:
        engine = AscendingTriangleEngine()
        result = engine.scan(df_long, known_signal_keys=previously_seen_keys)
    """

    # COUPLING NOTE: _preflight, _enrich, _scan_breakout, _assert_no_lookahead
    # and related helpers are called directly off AdvancedPatternEngine to
    # avoid duplication; _prior_rise is called directly off CupHandleEngine
    # for the same reason. AscendingTriangleConfig mirrors the field names
    # those methods read. If AdvancedPatternEngine or CupHandleEngine
    # refactor any of those methods to depend on fields not present in
    # AscendingTriangleConfig, these calls will break at runtime. Update
    # all three configs together.
    def __init__(self, config: Optional[AscendingTriangleConfig] = None) -> None:
        self.config = config or AscendingTriangleConfig()

    # ------------------------------------------------------------ public --
    def scan(self, df_long: pd.DataFrame, known_signal_keys: Optional[set] = None) -> "AscendingTriangleScanResult":
        known_signal_keys = set(known_signal_keys or set())
        signals: list[dict] = []
        expired: list[dict] = []
        rejected: list[dict] = []
        new_keys: set = set()

        if df_long is None or len(df_long) == 0:
            return AscendingTriangleScanResult(pd.DataFrame(), [], [], [], known_signal_keys)

        required_cols = {"symbol", "date", "open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df_long.columns):
            return AscendingTriangleScanResult(pd.DataFrame(), [], [], [], known_signal_keys)

        for symbol, raw in df_long.groupby("symbol", sort=False):
            df = raw.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

            ok, reason = self._preflight(df)
            if not ok:
                rejected.append({"symbol": symbol, "pattern_type": None, "reason": reason})
                continue

            enriched = self._enrich(df)
            pivots = find_pivots(enriched, k=self.config.k, min_swing_pct=self.config.min_swing_pct,
                                  atr_multiplier=self.config.atr_multiplier)
            if len(pivots) < 6:
                continue

            for sig in self._find_triangle_candidates(symbol, enriched, pivots):
                self._route(sig, known_signal_keys, new_keys, signals, expired, rejected)

        signals_df = pd.DataFrame(signals) if signals else pd.DataFrame(columns=_OUTPUT_COLUMNS)
        return AscendingTriangleScanResult(signals_df, signals, expired, rejected, known_signal_keys | new_keys)

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
            return
        new_keys.add(key)
        signals.append({k: v for k, v in sig.items() if not k.startswith("_")})

    # --------------------------------------------------- §1 pre-flight ----
    def _preflight(self, df: pd.DataFrame) -> tuple[bool, Optional[str]]:
        """Calls AdvancedPatternEngine._preflight DIRECTLY (unbound-method
        call against this engine's own `self`) -- see the COUPLING NOTE."""
        return AdvancedPatternEngine._preflight(self, df)

    def _enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """Same reuse technique as _preflight."""
        return AdvancedPatternEngine._enrich(self, df)

    def _prior_rise(self, df: pd.DataFrame, t1_index: int) -> tuple[bool, float, int]:
        """Calls CupHandleEngine._prior_rise DIRECTLY -- does not
        reimplement it. Both are continuation patterns requiring a prior
        rise, and this engine's config mirrors the exact field names that
        method reads (prior_rise_pct/prior_rise_min_sessions/
        prior_rise_max_sessions)."""
        return CupHandleEngine._prior_rise(self, df, t1_index)

    def _scan_breakout(self, df: pd.DataFrame, level_at_bar, confirmed_from_index: int) -> Optional[dict]:
        """Calls AdvancedPatternEngine._scan_breakout DIRECTLY -- see the
        COUPLING NOTE."""
        return AdvancedPatternEngine._scan_breakout(self, df, level_at_bar, confirmed_from_index)

    # =============================================== Ascending Triangle ===
    def _find_triangle_candidates(self, symbol: str, df: pd.DataFrame, pivots: list[Pivot]) -> list[dict]:
        """Assembles T1(low)/P1(high)/T2(low)/P2(high)/T3(low)/P3(high)
        pivot windows (T1-first, IHS convention) and applies every
        geometric filter in order, logging a rejection reason for each
        failure. Gate order follows IHS's convention explicitly:
        span_out_of_range -> flat_top_not_tight -> lows_not_ascending ->
        no_prior_uptrend -> [breakout] -> risk_reward_measured_below_minimum."""
        cfg = self.config
        out = []
        for j in range(len(pivots) - 5):
            window = pivots[j:j + 6]
            if window[0].kind != "low":
                continue
            t1, p1, t2, p2, t3, p3 = window

            span = p3.index - t1.index
            if not (cfg.triangle_min_span <= span <= cfg.triangle_max_span):
                out.append(AdvancedPatternEngine._rejected("ASCENDING_TRIANGLE", symbol, t1, p3, "span_out_of_range"))
                continue

            highs = (p1, p2, p3)
            high_prices = [h.price for h in highs]
            flat_top_pct = (max(high_prices) - min(high_prices)) / min(high_prices) * 100.0 if min(high_prices) else np.inf
            if flat_top_pct > cfg.flat_top_max_pct:
                out.append(AdvancedPatternEngine._rejected("ASCENDING_TRIANGLE", symbol, t1, p3, "flat_top_not_tight"))
                continue

            lows = (t1, t2, t3)
            low_steps_pct = [(lows[i + 1].price - lows[i].price) / lows[i].price * 100.0 if lows[i].price else -np.inf
                              for i in range(len(lows) - 1)]
            lows_ascending = all(step >= cfg.ascending_low_min_step_pct for step in low_steps_pct)
            if not lows_ascending:
                out.append(AdvancedPatternEngine._rejected("ASCENDING_TRIANGLE", symbol, t1, p3, "lows_not_ascending"))
                continue

            rise_ok, rise_pct_actual, rise_sessions = self._prior_rise(df, t1.index)
            if not rise_ok:
                out.append(AdvancedPatternEngine._rejected("ASCENDING_TRIANGLE", symbol, t1, p3, "no_prior_uptrend"))
                continue

            max_confirmed = max(t1.confirmed_at_index, p1.confirmed_at_index, t2.confirmed_at_index,
                                 p2.confirmed_at_index, t3.confirmed_at_index, p3.confirmed_at_index)
            _assert_no_lookahead([t1.index, p1.index, t2.index, p2.index, t3.index, p3.index],
                                  max_confirmed, "Ascending Triangle pre-breakout pivot check")

            # Resistance = max of all three highs, not just P3's level --
            # prevents a lower P3 from setting a resistance below P1/P2
            # (confirmed explicitly with the user).
            resistance_level = max(high_prices)
            breakout = self._scan_breakout(df, lambda i, _r=resistance_level: _r, max_confirmed)
            if breakout is None:
                out.append(AdvancedPatternEngine._expired(
                    "ASCENDING_TRIANGLE", symbol, t1, p1, t2, p2, t3, p3, max_confirmed))
                continue

            _assert_no_lookahead([t1.index, p1.index, t2.index, p2.index, t3.index, p3.index,
                                   breakout["breakout_index"]],
                                  breakout["breakout_index"], "Ascending Triangle breakout emission")

            # Does a 4th+ ascending low exist beyond T1/T2/T3 (peek at the
            # next pivot after P3, if any) -- confidence bonus only, never
            # a gate.
            idx_next_low = j + 6
            has_extra_low = (idx_next_low < len(pivots) and pivots[idx_next_low].kind == "low"
                              and t3.price > 0
                              and (pivots[idx_next_low].price - t3.price) / t3.price * 100.0
                              >= cfg.ascending_low_min_step_pct)

            sig = self._build_signal(symbol, df, t1, p1, t2, p2, t3, p3, breakout, resistance_level,
                                      flat_top_pct, low_steps_pct, rise_pct_actual, rise_sessions,
                                      span, has_extra_low)
            out.append(sig)
        return out

    def _build_signal(self, symbol, df, t1, p1, t2, p2, t3, p3, breakout, resistance_level,
                       flat_top_pct, low_steps_pct, rise_pct_actual, rise_sessions,
                       span, has_extra_low) -> dict:
        cfg = self.config
        bi = breakout["breakout_index"]
        entry_price = float(df["close"].iat[bi])
        atr14 = float(df["atr14"].iat[bi]) if pd.notna(df["atr14"].iat[bi]) else 0.0
        # Stop at T3 (most recent, highest low) -- the tightest structural
        # floor. The pattern thesis is "the rising support line is
        # holding"; if T3 breaks, that thesis has failed, regardless of
        # where T1 (the pattern's lowest, oldest low) sits. Confirmed
        # explicitly with the user.
        pattern_low = t3.price

        # Bounded-ATR stop -- IDENTICAL formula/defaults to
        # AdvancedPatternEngine's/CupHandleEngine's locked Round-4 stop.
        atr_ratio = (atr14 / entry_price) if entry_price else 0.0
        atr_ratio_bounded = min(max(atr_ratio, cfg.min_atr_ratio), cfg.max_atr_ratio)
        stop_loss_atr_component = atr_ratio_bounded * entry_price * cfg.atr_stop_mult
        stop_loss_final = max(entry_price - stop_loss_atr_component, pattern_low)
        stop_loss_pct_from_entry = (entry_price - stop_loss_final) / entry_price if entry_price else 0.0

        # Measured move: triangle height at its WIDEST point (P1 to T1,
        # the leftmost/earliest high-low pair -- widest because the lows
        # rise toward the flat top) added to the breakout level, per
        # Bulkowski. Kept as target_full_measured (reference only); the
        # 0.5x/0.75x working-target convention is reused from every other
        # module (confirmed explicitly with the user -- consistency over
        # literal single-target adherence).
        triangle_height = p1.price - t1.price
        target_partial = resistance_level + 0.5 * triangle_height
        target_measured = resistance_level + 0.75 * triangle_height
        target_full_measured = resistance_level + triangle_height
        risk = entry_price - stop_loss_final
        target_breakeven = entry_price + risk if risk > 0 else np.nan
        rr_partial = (target_partial - entry_price) / risk if risk > 0 else np.nan
        rr_measured = (target_measured - entry_price) / risk if risk > 0 else np.nan

        if pd.isna(rr_measured) or rr_measured < cfg.min_risk_reward_measured:
            return AdvancedPatternEngine._rejected("ASCENDING_TRIANGLE", symbol, t1, p3,
                                                     "risk_reward_measured_below_minimum")

        avg_vol20_bo = float(df["avg_volume_20"].iat[bi]) if pd.notna(df["avg_volume_20"].iat[bi]) else np.nan
        breakout_volume = float(df["volume"].iat[bi])
        breakout_vol_ratio = breakout_volume / avg_vol20_bo if avg_vol20_bo else np.nan

        confidence_score, confidence_components = score_ascending_triangle_confidence(
            flat_top_pct, low_steps_pct, breakout_vol_ratio, rise_pct_actual, span, has_extra_low,
            cfg.flat_top_max_pct, cfg.triangle_min_span, cfg.triangle_max_span)

        throwback_risk = bool(entry_price > resistance_level * (1 + cfg.throwback_risk_pct / 100.0))

        pivots_out = [AdvancedPatternEngine._pivot_dict(p) for p in (t1, p1, t2, p2, t3, p3)]
        dedup_key = (symbol, "ASCENDING_TRIANGLE", t1.date, p1.date, t2.date, p2.date, t3.date, p3.date)

        return {
            "_status": "signal", "_dedup_key": dedup_key,
            "symbol": symbol, "pattern_type": "ASCENDING_TRIANGLE", "pattern_subtype": "STANDARD",
            "signal_date": breakout["breakout_date"], "signal_index": bi,
            "pivots": pivots_out,
            "neckline_price": resistance_level, "neckline_mode": "max_of_three_highs",
            "neckline_horizontal": resistance_level, "neckline_sloped": resistance_level,
            "prior_decline_pct_actual": rise_pct_actual, "prior_decline_sessions": rise_sessions,
            "pattern_span_sessions": span,
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
            "flat_top_pct": round(flat_top_pct, 2), "low_steps_pct": [round(s, 2) for s in low_steps_pct],
            "params_used": cfg.as_dict(), "engine_version": cfg.engine_version,
        }


@dataclass
class AscendingTriangleScanResult:
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
    "confidence_score", "confidence_components",
    "flat_top_pct", "low_steps_pct",
    "params_used", "engine_version",
]
