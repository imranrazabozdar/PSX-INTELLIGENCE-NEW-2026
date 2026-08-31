"""advanced_pattern_adapter.py — thin adapter between AdvancedPatternEngine
(backend/advanced_pattern_engine.py) and the existing scan-wrapper calling
convention used by patterns_engine.py and morning_star_detector.py.

Does NOT modify AdvancedPatternEngine.scan() in any way. Its only jobs:
  1. Accept the same single-symbol `ohlc_rows` shape (list of dicts keyed
     "trade_date", straight from backend.app.ohlc_rows()) the other two
     scan wrappers already receive.
  2. Rename trade_date -> date going in, and never leak a "date"/
     "trade_date" key back out (output uses "signal_date" only) --
     this rename happens HERE and nowhere else.
  3. Flatten the engine's richer signal dict (nested `pivots` list,
     `confidence_components` dict, both stop-loss/target variants, etc.)
     down to the flat key set the dashboard's hits[] convention expects.
  4. Never raise -- any engine exception or per-symbol rejection is logged
     at DEBUG and returns [], exactly like the other two wrappers'
     informal "skip on failure" behavior (see app.py's `except Exception:
     continue` around each existing scan call).
"""

import logging
import os
import sys

# advanced_pattern_engine.py lives in backend/, one level up from this
# backend/patterns/ package -- added dynamically (not hardcoded) so this
# import resolves whether the module is loaded normally by app.py (which
# already has backend/ on sys.path) or run/imported any other way.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pandas as pd

from advanced_pattern_engine import AdvancedPatternEngine

logger = logging.getLogger(__name__)

_engine = AdvancedPatternEngine()

# Thresholds for _strength_rating()'s confidence_score -> label mapping.
# Starting guesses, not researched constants -- see backend/patterns/README.md.
STRENGTH_STRONG_THRESHOLD = 0.80
STRENGTH_MODERATE_THRESHOLD = 0.60

# Role labels by position, matching the pivot ORDER AdvancedPatternEngine
# always emits them in (see advanced_pattern_engine.py's _pivot_dict calls):
# Inverse H&S -> (t1, p1, t2, p2, t3); Double Bottom -> (b1, pk, b2).
_PIVOT_LABELS = {
    "INVERSE_HS": ["T1", "P1", "T2", "P2", "T3"],
    "DOUBLE_BOTTOM": ["B1", "PK", "B2"],
}

# CALIBRATION ROUND 4, Change 3: static underperformance note, IHS only.
# Investigation 2 (Round 3) found IHS underperformance is structural
# (identical win rate/avg pnl in 2022 vs non-2022 PSX data), not a regime
# artifact. Three consecutive backtest runs have now shown the same
# structural underperformance -- upgraded from a caution note to a size-
# reduction/skip recommendation with the concrete numbers attached. This
# is a plain finding-of-fact label, not a live-computed metric.
_IHS_PERFORMANCE_NOTE = (
    "⚠️ CAUTION: IHS pattern shows consistent underperformance on PSX "
    "across 84 signals (5-year backtest). Win rate 45.2%, median P&L -4.58%. "
    "Trade with significantly reduced size or consider skipping until win "
    "rate exceeds 50% over 20+ consecutive signals."
)


def _get_market_regime(signal_date) -> str | None:
    """CALIBRATION ROUND 3, Change 4: KSE-100 regime lookup (e.g. index
    above/below its 200-day MA). Defensive by design -- as of this
    engine's current data, backend/psx_v2.db has no KSE-100 index-level
    OHLC series (confirmed: no daily_ohlc symbol matches KSE-100/INDEX),
    so this always returns None today. Kept as a real function, not a
    hardcoded None, so wiring in an index feed later only requires
    filling in the body -- no caller changes."""
    return None


def _pivot_summary(pattern_type: str, pivots: list) -> str:
    """Compact string form of a signal's pivots, e.g.
    "T1=2024-01-05,P1=2024-02-01,T2=2024-02-20,P2=2024-03-15,T3=2024-04-01".
    Falls back to positional P0/P1/... labels for an unrecognized pattern
    type or a pivot count that doesn't match the expected role sequence,
    rather than raising or silently truncating."""
    labels = _PIVOT_LABELS.get(pattern_type)
    if not labels or len(labels) != len(pivots):
        labels = [f"P{i}" for i in range(len(pivots))]
    parts = []
    for label, p in zip(labels, pivots):
        date = p.get("date")
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
        parts.append(f"{label}={date_str}")
    return ",".join(parts)


def scan_symbol(symbol: str, ohlc_rows: list, min_rows: int = 200) -> list:
    """Runs AdvancedPatternEngine for ONE symbol's daily OHLCV and returns
    a flat list of hit dicts, exactly matching the calling shape of
    _run_bullish_engulfing_scan/_run_morning_star_scan's per-symbol call
    (see app.py). Returns [] on any rejection, error, or insufficient
    history -- never raises.
    """
    n_rows = len(ohlc_rows) if ohlc_rows else 0
    if n_rows < min_rows:
        logger.debug("advanced_pattern_adapter: skipping %s, %d rows < min_rows=%d",
                      symbol, n_rows, min_rows)
        return []

    try:
        df = pd.DataFrame(ohlc_rows)
        if "trade_date" not in df.columns:
            logger.debug("advanced_pattern_adapter: %s missing 'trade_date' column, columns=%s",
                          symbol, list(df.columns))
            return []
        # Rename happens HERE ONLY -- the engine never sees "trade_date",
        # and nothing downstream of this adapter ever sees "date" again.
        df = df.rename(columns={"trade_date": "date"})
        df["symbol"] = symbol
        result = _engine.scan(df)
    except Exception:
        logger.debug("advanced_pattern_adapter: engine raised scanning %s", symbol, exc_info=True)
        return []

    if not result.signals:
        if result.rejected:
            logger.debug("advanced_pattern_adapter: %s produced no signals, rejected=%s",
                          symbol, result.rejected)
        return []

    hits = []
    for sig in result.signals:
        try:
            signal_date = sig["signal_date"]
            signal_date_str = signal_date.strftime("%Y-%m-%d") if hasattr(signal_date, "strftime") \
                else str(signal_date)
            hits.append({
                "symbol": symbol,
                "pattern_type": sig["pattern_type"],
                "pattern_subtype": sig["pattern_subtype"],
                "signal_date": signal_date_str,
                "strength_rating": _strength_rating(sig),
                "entry_price": sig["entry_price"],
                "stop_loss": sig["stop_loss"],
                "target_1": sig["target_partial"],
                "target_2": sig["target_measured"],
                "risk_reward_measured": sig["risk_reward_measured"],
                "confidence_score": sig["confidence_score"],
                "neckline_price": sig["neckline_price"],
                "prior_decline_pct_actual": sig["prior_decline_pct_actual"],
                "pivot_summary": _pivot_summary(sig["pattern_type"], sig.get("pivots") or []),
                "performance_note": _IHS_PERFORMANCE_NOTE if sig["pattern_type"] == "INVERSE_HS" else None,
                "regime": _get_market_regime(sig["signal_date"]),
            })
        except Exception:
            logger.debug("advanced_pattern_adapter: failed to flatten a signal for %s", symbol, exc_info=True)
            continue

    return hits


def _strength_rating(sig: dict) -> str:
    """AdvancedPatternEngine has no explicit STRONG/MODERATE tier the way
    MorningStarDetector does -- it emits a continuous confidence_score
    instead. Derives a comparable three-tier label purely from that score
    so the dashboard's Strength column has something consistent to show
    across all three pattern modules, without inventing a new scoring
    rule: >=0.8 STRONG (matches this engine's own "confidence > 0.8"
    textbook-fixture bar from its test suite), >=0.6 MODERATE, else WEAK."""
    score = sig.get("confidence_score") or 0.0
    if score >= STRENGTH_STRONG_THRESHOLD:
        return "STRONG"
    if score >= STRENGTH_MODERATE_THRESHOLD:
        return "MODERATE"
    return "WEAK"


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    from test_advanced_patterns import build_ihs_fixture  # noqa: E402

    fixture_df = build_ihs_fixture()
    rows = fixture_df.rename(columns={"date": "trade_date"}).to_dict("records")
    hits = scan_symbol("IHSTEST", rows, min_rows=200)
    print(f"hits: {len(hits)}")
    for h in hits:
        print(h)
        assert all(not isinstance(v, (dict, list)) for v in h.values()), "found a nested value in a hit dict"
