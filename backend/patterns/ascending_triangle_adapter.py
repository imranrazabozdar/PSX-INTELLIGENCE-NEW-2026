"""ascending_triangle_adapter.py — thin adapter between
AscendingTriangleEngine (backend/ascending_triangle_engine.py) and the
existing scan-wrapper calling convention used by patterns_engine.py,
morning_star_detector.py, advanced_pattern_adapter.py, and
cup_handle_adapter.py. Mirrors cup_handle_adapter.py exactly.

Does NOT modify AscendingTriangleEngine.scan() in any way. Its only jobs:
  1. Accept the same single-symbol `ohlc_rows` shape (list of dicts keyed
     "trade_date", straight from backend.app.ohlc_rows()) the other scan
     wrappers already receive.
  2. Rename trade_date -> date going in, and never leak a "date"/
     "trade_date" key back out (output uses "signal_date" only) --
     this rename happens HERE and nowhere else.
  3. Flatten the engine's richer signal dict down to the same flat
     16-key set every other pattern adapter uses.
  4. Never raise -- any engine exception or per-symbol rejection is logged
     at DEBUG and returns [], exactly like the other wrappers' informal
     "skip on failure" behavior.
"""

import logging
import os
import sys

# ascending_triangle_engine.py lives in backend/, one level up from this
# backend/patterns/ package -- added dynamically (not hardcoded) so this
# import resolves whether the module is loaded normally by app.py (which
# already has backend/ on sys.path) or run/imported any other way.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pandas as pd

from ascending_triangle_engine import AscendingTriangleEngine

logger = logging.getLogger(__name__)

_engine = AscendingTriangleEngine()

# Thresholds for _strength_rating()'s confidence_score -> label mapping.
# Same values as every other pattern adapter -- starting guesses, not
# researched constants -- see backend/patterns/README.md.
STRENGTH_STRONG_THRESHOLD = 0.80
STRENGTH_MODERATE_THRESHOLD = 0.60

# Role labels by position, matching the pivot ORDER AscendingTriangleEngine
# always emits them in (see ascending_triangle_engine.py's _pivot_dict
# calls, T1-first / IHS convention): T1, P1, T2, P2, T3, P3.
_PIVOT_LABELS = {
    "ASCENDING_TRIANGLE": ["T1", "P1", "T2", "P2", "T3", "P3"],
}

# Ascending Triangle has not been backtested on PSX yet -- same posture
# as Cup & Handle's performance_note when it was first built.
_ASCENDING_TRIANGLE_PERFORMANCE_NOTE = (
    "Not yet backtested on PSX. Bulkowski reports 76% breakout-direction "
    "rate in US equities (symmetrical triangles; ascending likely higher). "
    "PSX performance unknown. Trade with caution until local backtest is "
    "complete."
)


def _get_market_regime(signal_date) -> str | None:
    """Same defensive stub as every other pattern adapter's
    _get_market_regime -- backend/psx_v2.db has no KSE-100 index-level
    OHLC series, so this always returns None today."""
    return None


def _pivot_summary(pattern_type: str, pivots: list) -> str:
    """Compact string form of a signal's pivots, e.g.
    "T1=2023-07-..,P1=2023-08-..,T2=..,P2=..,T3=..,P3=..". Falls back to
    positional P0/P1/... labels for an unrecognized pattern type or a
    pivot count that doesn't match the expected role sequence, rather
    than raising or silently truncating."""
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
    """Runs AscendingTriangleEngine for ONE symbol's daily OHLCV and
    returns a flat list of hit dicts, exactly matching the calling shape
    of the other pattern adapters' per-symbol call (see app.py). Returns
    [] on any rejection, error, or insufficient history -- never raises.
    """
    n_rows = len(ohlc_rows) if ohlc_rows else 0
    if n_rows < min_rows:
        logger.debug("ascending_triangle_adapter: skipping %s, %d rows < min_rows=%d",
                      symbol, n_rows, min_rows)
        return []

    try:
        df = pd.DataFrame(ohlc_rows)
        if "trade_date" not in df.columns:
            logger.debug("ascending_triangle_adapter: %s missing 'trade_date' column, columns=%s",
                          symbol, list(df.columns))
            return []
        # Rename happens HERE ONLY -- the engine never sees "trade_date",
        # and nothing downstream of this adapter ever sees "date" again.
        df = df.rename(columns={"trade_date": "date"})
        df["symbol"] = symbol
        result = _engine.scan(df)
    except Exception:
        logger.debug("ascending_triangle_adapter: engine raised scanning %s", symbol, exc_info=True)
        return []

    if not result.signals:
        if result.rejected:
            logger.debug("ascending_triangle_adapter: %s produced no signals, rejected=%s",
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
                "performance_note": _ASCENDING_TRIANGLE_PERFORMANCE_NOTE,
                "regime": _get_market_regime(sig["signal_date"]),
            })
        except Exception:
            logger.debug("ascending_triangle_adapter: failed to flatten a signal for %s", symbol, exc_info=True)
            continue

    return hits


def _strength_rating(sig: dict) -> str:
    """Same three-tier mapping as every other pattern adapter's
    _strength_rating: >=0.8 STRONG, >=0.6 MODERATE, else WEAK."""
    score = sig.get("confidence_score") or 0.0
    if score >= STRENGTH_STRONG_THRESHOLD:
        return "STRONG"
    if score >= STRENGTH_MODERATE_THRESHOLD:
        return "MODERATE"
    return "WEAK"


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    from test_ascending_triangle import build_ascending_triangle_fixture  # noqa: E402

    fixture_df = build_ascending_triangle_fixture()
    rows = fixture_df.rename(columns={"date": "trade_date"}).to_dict("records")
    hits = scan_symbol("TRITEST", rows, min_rows=200)
    print(f"hits: {len(hits)}")
    for h in hits:
        print(h)
        assert all(not isinstance(v, (dict, list)) for v in h.values()), "found a nested value in a hit dict"
