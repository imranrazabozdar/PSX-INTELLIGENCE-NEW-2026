"""cup_handle_engine.py — deterministic, auditable Cup & Handle detector
for PSX daily OHLCV data, built on the exact same architecture as
advanced_pattern_engine.py (§0 no-lookahead contract, §1 pre-flight,
shared breakout scan, bounded-ATR stop formula, same 16-key adapter
schema).

================================================================================
§0. NO-LOOKAHEAD -- SAME CONTRACT AS advanced_pattern_engine.py
================================================================================
Identical guarantee, identical mechanism, reused rather than reimplemented:
  - Pivots come from pivots.find_pivots() and carry confirmed_at_index.
  - A breakout is only ever searched for on bars at or after
    max(confirmed_at_index) across P1/T1/P2/T2 -- via the SAME
    AdvancedPatternEngine._scan_breakout function (see _scan_breakout
    below, which calls it directly rather than duplicating it).
  - signal_date/signal_index are always the breakout bar.
  - _assert_no_lookahead (imported, not reimplemented) is called
    immediately before every signal is emitted.

DIRECTION NOTE: unlike Inverse H&S and Eve & Eve Double Bottom (both
reversal patterns requiring a prior DECLINE), Cup & Handle is a
continuation pattern -- the cup forms during an established UPTREND, and
the handle is a shallow pullback before the breakout continuation. Every
prior-trend check in this file therefore measures a RISE, not a decline
(_prior_rise mirrors AdvancedPatternEngine._prior_trend's exact
look-back/argmax-vs-argmin structure, direction inverted).

§11 DOCUMENTATION HONESTY: Bulkowski reports a ~95% breakout-direction
rate for Cup & Handle in US equities. That figure has NOT been validated
on PSX -- nothing in this file has been backtested yet. Treat any
confidence_score this emits as a geometric/volume quality score only,
not a predictor of outcome (the advanced engine's own confidence score
was found to have zero such predictive power on PSX after backtesting;
no stronger claim is made here pre-backtest).

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

ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class CupHandleConfig:
    """Every tunable threshold, named and defaulted in one place -- same
    discipline as AdvancedPatternConfig. Defaults are starting guesses,
    not researched PSX constants."""

    # Pivot detection (pivots.py) -- same defaults as the advanced engine,
    # by explicit instruction, so pivot geometry stays directly comparable
    # across pattern modules.
    k: int = 5
    min_swing_pct: float = 3.0
    atr_multiplier: float = 1.5

    # Pre-flight validation -- same field names as AdvancedPatternConfig
    # on purpose: _preflight below calls AdvancedPatternEngine._preflight
    # directly (not reimplemented), and that method only ever reads these
    # four fields off self.config, so matching names is what makes the
    # reuse work, not just convention.
    min_history_sessions: int = 200
    min_traded_sessions_ratio: float = 0.90
    min_turnover_pkr: float = 5_000_000.0
    unadjusted_gap_pct: float = 15.0

    # Prior trend prerequisite -- RISE, not decline (see module docstring).
    prior_rise_pct: float = 10.0
    prior_rise_min_sessions: int = 20
    prior_rise_max_sessions: int = 40

    # Cup geometry
    cup_min_span: int = 25
    # PARAMETER RECALIBRATION, 2026-08-29 (first PSX calibration; see
    # CALIBRATION_LOG.md "CUP & HANDLE BUILD NOTES"): 150 -> 250. A
    # full-universe rejection-funnel diagnostic found 69.4% of assembled
    # P1/T1/P2 triples (4,489 of 6,467) died at this single gate, the
    # single largest rejection stage by far -- cup_min_span=25 had zero
    # rejections, so only the ceiling was binding. PSX cups form over
    # longer periods than the US-equity-derived 150-session default
    # (thinner liquidity, slower institutional accumulation); 250 sessions
    # (~1 calendar year) was chosen as the new ceiling. Recalibrated from
    # US-equity default to PSX on 2026-08-29 -- see CALIBRATION_LOG.md.
    cup_max_span: int = 250
    rim_symmetry_max_pct: float = 5.0
    # Bulkowski quality cutoff: a cup that retraces more than ~1/3 of the
    # prior rise is lower-quality. Expressed as cup depth (% of the left
    # rim price) relative to the prior rise magnitude (also a %), i.e.
    # "the cup gave back more than cup_max_depth_pct of the preceding
    # advance" -- not an absolute price-depth percentage.
    # PARAMETER RECALIBRATION, 2026-08-29 (first PSX calibration): 33.0 ->
    # 65.0. Of the 461 triples that reached this check after passing
    # span+rim_symmetry+prior_rise, median cup_depth_pct_of_rise was
    # 56.1% -- almost twice Bulkowski/O'Neil's 33% US-equity benchmark.
    # PSX stocks have structurally deeper corrections (thinner liquidity,
    # higher volatility); 65% admits the typical PSX cup while still
    # excluding >65% collapses that look more like pattern failure than
    # accumulation. Recalibrated from US-equity default to PSX on
    # 2026-08-29 -- see CALIBRATION_LOG.md.
    cup_max_depth_pct: float = 65.0
    # Reused from the Eve/Adam roundness test (same name, same default) as
    # the ceiling for the cup_roundness confidence component below --
    # APPROXIMATION of Bulkowski's visual "rounded, not V-shaped" criterion
    # via depth/width, the same simplification already used for Eve vs
    # Adam troughs, not a new geometric model.
    max_vness: float = 1.2

    # Breakout (shared mechanism, reused from advanced_pattern_engine.py)
    breakout_vol_mult: float = 1.5
    confirmation_window: int = 30

    # Handle geometry -- shallower and shorter than the cup, by spec.
    # PARAMETER RECALIBRATION, 2026-08-29 (first PSX calibration): 15.0 ->
    # 30.0. Of the 35 triples that cleared every cup-stage filter (after
    # Change 1/Change 2 above), 100% died at this single gate -- zero
    # signals were possible at 15% on PSX data. Same underlying cause as
    # the cup-depth recalibration (PSX volatility/liquidity structure);
    # 30% of cup height is the new ceiling, still tight enough to exclude
    # a handle that retraces the full cup. Recalibrated from US-equity
    # default to PSX on 2026-08-29 -- see CALIBRATION_LOG.md.
    handle_max_depth_pct: float = 30.0
    handle_max_span: int = 25

    # Risk/reward
    min_risk_reward_measured: float = 1.0
    # Bounded-ATR stop formula -- IDENTICAL to AdvancedPatternConfig's
    # locked Round-4 formula, same field names, same defaults, so the two
    # engines' stops are directly comparable and nothing was re-derived.
    atr_stop_mult: float = 2.0
    min_atr_ratio: float = 0.015
    max_atr_ratio: float = 0.035
    throwback_risk_pct: float = 5.0

    engine_version: str = ENGINE_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


# ============================================================== scoring ==
def score_cup_handle_confidence(rim_symmetry_pct: float, cup_vness: float,
                                 handle_depth_pct: float, breakout_vol_ratio: float,
                                 prior_rise_pct_actual: float, cup_depth_pct_of_rise: float,
                                 max_vness: float) -> tuple[float, dict]:
    """Deterministic, weighted, auditable -- same structure as
    score_ihs_confidence/score_double_bottom_confidence. Weights sum to
    1.0. cup_roundness is an explicit APPROXIMATION of Bulkowski's visual
    roundness criteria (depth/width ratio, the same mechanism already used
    for the Eve/Adam trough test), not a researched formula."""
    components = {
        "rim_symmetry": 0.20 * _linear_ramp(rim_symmetry_pct, zero_at=5.0, full_at=2.0),
        "cup_roundness": 0.20 * _linear_ramp(cup_vness, zero_at=max_vness, full_at=0.8),
        "handle_tightness": 0.15 * _linear_ramp(handle_depth_pct, zero_at=15.0, full_at=8.0),
        "breakout_volume": 0.20 * _linear_ramp(breakout_vol_ratio, zero_at=1.5, full_at=2.0),
        "prior_rise": 0.15 * _linear_ramp(prior_rise_pct_actual, zero_at=10.0, full_at=20.0),
        # Plateau: full credit on [20, 33] (the Bulkowski-quality band),
        # ramping to 0 below 20 and above 33. Values >33 are already hard-
        # rejected before a signal ever reaches this function (see
        # "cup_too_deep" in _find_cup_handle_candidates) -- the high-side
        # ramp here is a defensive default for this function in isolation,
        # not a path reachable in practice through the engine.
        "cup_depth": 0.10 * _plateau_score(cup_depth_pct_of_rise, 0.0, 20.0, 33.0, 40.0),
    }
    return round(sum(components.values()), 4), {k: round(v, 4) for k, v in components.items()}


# ============================================================= engine ====
class CupHandleEngine:
    """Detects Cup & Handle patterns across many PSX symbols. See module
    docstring §0 for the no-lookahead contract (identical to
    AdvancedPatternEngine's) and §11 for the Bulkowski-figures disclaimer.

    Usage:
        engine = CupHandleEngine()
        result = engine.scan(df_long, known_signal_keys=previously_seen_keys)
    """

    # COUPLING NOTE: _preflight, _enrich, _scan_breakout, _assert_no_lookahead
    # and related helpers are called directly off AdvancedPatternEngine to
    # avoid duplication. CupHandleConfig mirrors the field names those
    # methods read. If AdvancedPatternEngine refactors any of those methods
    # to depend on APE-specific config fields not present in
    # CupHandleConfig, these calls will break at runtime. Update both
    # configs together.
    def __init__(self, config: Optional[CupHandleConfig] = None) -> None:
        self.config = config or CupHandleConfig()

    # ------------------------------------------------------------ public --
    def scan(self, df_long: pd.DataFrame, known_signal_keys: Optional[set] = None) -> "CupHandleScanResult":
        known_signal_keys = set(known_signal_keys or set())
        signals: list[dict] = []
        expired: list[dict] = []
        rejected: list[dict] = []
        new_keys: set = set()

        if df_long is None or len(df_long) == 0:
            return CupHandleScanResult(pd.DataFrame(), [], [], [], known_signal_keys)

        required_cols = {"symbol", "date", "open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df_long.columns):
            return CupHandleScanResult(pd.DataFrame(), [], [], [], known_signal_keys)

        for symbol, raw in df_long.groupby("symbol", sort=False):
            df = raw.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

            ok, reason = self._preflight(df)
            if not ok:
                rejected.append({"symbol": symbol, "pattern_type": None, "reason": reason})
                continue

            enriched = self._enrich(df)
            pivots = find_pivots(enriched, k=self.config.k, min_swing_pct=self.config.min_swing_pct,
                                  atr_multiplier=self.config.atr_multiplier)
            if len(pivots) < 4:
                continue

            for sig in self._find_cup_handle_candidates(symbol, enriched, pivots):
                self._route(sig, known_signal_keys, new_keys, signals, expired, rejected)

        signals_df = pd.DataFrame(signals) if signals else pd.DataFrame(columns=_OUTPUT_COLUMNS)
        return CupHandleScanResult(signals_df, signals, expired, rejected, known_signal_keys | new_keys)

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
        """Calls AdvancedPatternEngine._preflight DIRECTLY (an unbound
        method call against this engine's own `self`) rather than
        reimplementing its five checks -- it only ever reads
        self.config.min_history_sessions/min_traded_sessions_ratio/
        min_turnover_pkr/unadjusted_gap_pct, all of which CupHandleConfig
        defines with identical names and defaults, so this is a genuine
        shared implementation, not a parallel copy that could drift."""
        return AdvancedPatternEngine._preflight(self, df)

    def _enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """Same reuse technique as _preflight -- AdvancedPatternEngine._enrich
        only reads df and returns is_locked/atr14/avg_volume_20 columns; no
        IHS/Double-Bottom-specific state involved."""
        return AdvancedPatternEngine._enrich(self, df)

    # -------------------------------------------------- prior rise check --
    def _prior_rise(self, df: pd.DataFrame, p1_index: int) -> tuple[bool, float, int]:
        """Mirrors AdvancedPatternEngine._prior_trend exactly (same
        look-back-window structure), direction inverted: looks back over
        the min..max session window immediately before the left rim (P1),
        finds the actual LOWEST low in that window, and measures the RISE
        from that low to P1's high. Returns
        (ok, prior_rise_pct_actual, prior_rise_sessions)."""
        cfg = self.config
        lookback_start = max(0, p1_index - cfg.prior_rise_max_sessions)
        if lookback_start >= p1_index:
            return False, 0.0, 0
        window = df["low"].iloc[lookback_start:p1_index]
        if window.empty:
            return False, 0.0, 0
        pre_low = float(window.min())
        pre_low_index = lookback_start + int(window.values.argmin())
        sessions = p1_index - pre_low_index
        rim_high = float(df["high"].iloc[p1_index])
        rise_pct = (rim_high - pre_low) / pre_low * 100.0 if pre_low else 0.0
        ok = (rise_pct >= cfg.prior_rise_pct
              and cfg.prior_rise_min_sessions <= sessions <= cfg.prior_rise_max_sessions)
        return ok, round(rise_pct, 2), sessions

    # --------------------------------------------------- shared breakout --
    def _scan_breakout(self, df: pd.DataFrame, level_at_bar, confirmed_from_index: int) -> Optional[dict]:
        """Calls AdvancedPatternEngine._scan_breakout DIRECTLY -- does not
        reimplement it. That method only reads self.config.confirmation_window
        and self.config.breakout_vol_mult (both defined identically here)
        plus its explicit df/level_at_bar/confirmed_from_index arguments,
        so this unbound-method call is the same function running, not a
        parallel copy."""
        return AdvancedPatternEngine._scan_breakout(self, df, level_at_bar, confirmed_from_index)

    # =============================================== Cup & Handle =========
    def _find_cup_handle_candidates(self, symbol: str, df: pd.DataFrame, pivots: list[Pivot]) -> list[dict]:
        """Assembles P1(high)/T1(low)/P2(high)/T2(low) pivot windows and
        applies every geometric filter in order, logging a rejection
        reason for each failure rather than silently dropping candidates."""
        cfg = self.config
        out = []
        for j in range(len(pivots) - 3):
            window = pivots[j:j + 4]
            if window[0].kind != "high":
                continue
            p1, t1, p2, t2 = window

            cup_span = p2.index - p1.index
            if not (cfg.cup_min_span <= cup_span <= cfg.cup_max_span):
                out.append(AdvancedPatternEngine._rejected("CUP_HANDLE", symbol, p1, p2, "cup_span_out_of_range"))
                continue

            rim_symmetry_pct = abs(p1.price - p2.price) / min(p1.price, p2.price) * 100.0 if p1.price and p2.price else np.inf
            if rim_symmetry_pct > cfg.rim_symmetry_max_pct:
                out.append(AdvancedPatternEngine._rejected("CUP_HANDLE", symbol, p1, p2, "rims_not_symmetric"))
                continue

            rise_ok, rise_pct_actual, rise_sessions = self._prior_rise(df, p1.index)
            if not rise_ok:
                out.append(AdvancedPatternEngine._rejected("CUP_HANDLE", symbol, p1, p2, "no_prior_uptrend"))
                continue

            cup_depth_pct_of_rim = (p1.price - t1.price) / p1.price * 100.0 if p1.price else 0.0
            cup_depth_pct_of_rise = (cup_depth_pct_of_rim / rise_pct_actual * 100.0) if rise_pct_actual else np.inf
            if cup_depth_pct_of_rise > cfg.cup_max_depth_pct:
                out.append(AdvancedPatternEngine._rejected("CUP_HANDLE", symbol, p1, p2, "cup_too_deep"))
                continue

            cup_height = p2.price - t1.price
            handle_depth_pct = (p2.price - t2.price) / cup_height * 100.0 if cup_height else np.inf
            if handle_depth_pct > cfg.handle_max_depth_pct:
                out.append(AdvancedPatternEngine._rejected("CUP_HANDLE", symbol, p1, t2, "handle_too_deep"))
                continue

            handle_span = t2.index - p2.index
            if handle_span > cfg.handle_max_span:
                out.append(AdvancedPatternEngine._rejected("CUP_HANDLE", symbol, p1, t2, "handle_span_out_of_range"))
                continue

            max_confirmed = max(p1.confirmed_at_index, t1.confirmed_at_index,
                                 p2.confirmed_at_index, t2.confirmed_at_index)
            _assert_no_lookahead([p1.index, t1.index, p2.index, t2.index],
                                  max_confirmed, "Cup & Handle pre-breakout pivot check")

            breakout = self._scan_breakout(df, lambda i, _p2=p2: _p2.price, max_confirmed)
            if breakout is None:
                out.append(AdvancedPatternEngine._expired(
                    "CUP_HANDLE", symbol, p1, t1, p2, t2, max_confirmed))
                continue

            _assert_no_lookahead([p1.index, t1.index, p2.index, t2.index, breakout["breakout_index"]],
                                  breakout["breakout_index"], "Cup & Handle breakout emission")

            sig = self._build_signal(symbol, df, p1, t1, p2, t2, breakout, rim_symmetry_pct,
                                      rise_pct_actual, rise_sessions, cup_span, cup_depth_pct_of_rim,
                                      cup_depth_pct_of_rise, handle_depth_pct)
            out.append(sig)
        return out

    def _build_signal(self, symbol, df, p1, t1, p2, t2, breakout, rim_symmetry_pct,
                       rise_pct_actual, rise_sessions, cup_span, cup_depth_pct_of_rim,
                       cup_depth_pct_of_rise, handle_depth_pct) -> dict:
        cfg = self.config
        bi = breakout["breakout_index"]
        entry_price = float(df["close"].iat[bi])
        atr14 = float(df["atr14"].iat[bi]) if pd.notna(df["atr14"].iat[bi]) else 0.0
        pattern_low = t1.price  # cup bottom -- if price returns here the pattern thesis is invalid
        rim_price = p2.price    # right rim -- the breakout level, reused under "neckline_price" for
                                 # adapter-schema consistency across pattern modules (see _OUTPUT_COLUMNS)

        # Bounded-ATR stop -- IDENTICAL formula/defaults to
        # AdvancedPatternEngine's locked Round-4 stop. See CupHandleConfig's
        # atr_stop_mult/min_atr_ratio/max_atr_ratio for the rationale.
        atr_ratio = (atr14 / entry_price) if entry_price else 0.0
        atr_ratio_bounded = min(max(atr_ratio, cfg.min_atr_ratio), cfg.max_atr_ratio)
        stop_loss_atr_component = atr_ratio_bounded * entry_price * cfg.atr_stop_mult
        stop_loss_final = max(entry_price - stop_loss_atr_component, pattern_low)
        stop_loss_pct_from_entry = (entry_price - stop_loss_final) / entry_price if entry_price else 0.0

        pattern_height = rim_price - pattern_low
        target_partial = rim_price + 0.5 * pattern_height
        target_measured = rim_price + 0.75 * pattern_height
        target_full_measured = rim_price + pattern_height
        risk = entry_price - stop_loss_final
        target_breakeven = entry_price + risk if risk > 0 else np.nan
        rr_partial = (target_partial - entry_price) / risk if risk > 0 else np.nan
        rr_measured = (target_measured - entry_price) / risk if risk > 0 else np.nan

        if pd.isna(rr_measured) or rr_measured < cfg.min_risk_reward_measured:
            return AdvancedPatternEngine._rejected("CUP_HANDLE", symbol, p1, t2, "risk_reward_measured_below_minimum")

        avg_vol20_bo = float(df["avg_volume_20"].iat[bi]) if pd.notna(df["avg_volume_20"].iat[bi]) else np.nan
        breakout_volume = float(df["volume"].iat[bi])
        breakout_vol_ratio = breakout_volume / avg_vol20_bo if avg_vol20_bo else np.nan

        cup_vness = cup_depth_pct_of_rim / cup_span if cup_span else np.inf
        confidence_score, confidence_components = score_cup_handle_confidence(
            rim_symmetry_pct, cup_vness, handle_depth_pct, breakout_vol_ratio,
            rise_pct_actual, cup_depth_pct_of_rise, cfg.max_vness)

        throwback_risk = bool(entry_price > rim_price * (1 + cfg.throwback_risk_pct / 100.0))
        pattern_subtype = "TIGHT_HANDLE" if handle_depth_pct <= 0.5 * cfg.handle_max_depth_pct else "LOOSE_HANDLE"

        pivots_out = [AdvancedPatternEngine._pivot_dict(p) for p in (p1, t1, p2, t2)]
        dedup_key = (symbol, "CUP_HANDLE", p1.date, t1.date, p2.date, t2.date)

        return {
            "_status": "signal", "_dedup_key": dedup_key,
            "symbol": symbol, "pattern_type": "CUP_HANDLE", "pattern_subtype": pattern_subtype,
            "signal_date": breakout["breakout_date"], "signal_index": bi,
            "pivots": pivots_out,
            "neckline_price": rim_price, "neckline_mode": "rim_high",
            "neckline_horizontal": rim_price, "neckline_sloped": rim_price,
            "prior_decline_pct_actual": rise_pct_actual, "prior_decline_sessions": rise_sessions,
            "pattern_span_sessions": t2.index - p1.index,
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
            "cup_span_sessions": cup_span, "cup_depth_pct_of_rim": round(cup_depth_pct_of_rim, 2),
            "handle_depth_pct": round(handle_depth_pct, 2),
            "params_used": cfg.as_dict(), "engine_version": cfg.engine_version,
        }


@dataclass
class CupHandleScanResult:
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
    "cup_span_sessions", "cup_depth_pct_of_rim", "handle_depth_pct",
    "params_used", "engine_version",
]
