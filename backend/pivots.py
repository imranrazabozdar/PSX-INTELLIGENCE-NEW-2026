"""pivots.py — swing-pivot (fractal) detection, separately testable from
advanced_pattern_engine.py's pattern-assembly logic.

NO-LOOKAHEAD CONTRACT (see advanced_pattern_engine.py §0 for the full
rationale): a swing low/high at bar i cannot be known until k bars to its
RIGHT have printed. Every Pivot this module returns therefore carries both
its own index/date AND confirmed_at_index/confirmed_at_date = index + k --
callers must never act on a pivot before its confirmation bar.

This module is PSX-agnostic and pure-geometric: it does not know about
circuit-breaker locks or PSX-specific data-quality rules. Callers (see
advanced_pattern_engine.py's pre-flight validation) are responsible for
excluding locked bars before computing the `atr14` column this module
expects as an input -- _find_pivots never recomputes ATR itself, so a
caller's locked-bar exclusion is never silently bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Pivot:
    kind: str                      # "low" or "high"
    index: int                     # positional index into the symbol's own df (0-based, reset)
    date: pd.Timestamp
    price: float
    confirmed_at_index: int        # index + k -- the earliest bar this pivot may be used on
    confirmed_at_date: pd.Timestamp


def _rolling_extreme_candidates(series: pd.Series, k: int, mode: str) -> pd.Series:
    """Bar i is a window-extreme candidate if series[i] equals the min/max
    of series[i-k : i+k+1] (a centered window of 2k+1 bars) AND no earlier
    bar within that same k-bar lookback also ties it (ties broken by
    earliest index, per spec §2.1) -- so a flat run of identical prices
    produces exactly one candidate, not one per bar. Edge bars (the first/
    last k rows, where the centered window is incomplete) never qualify --
    consistent with the no-lookahead contract: there's nothing to confirm
    a pivot within k bars of either end of the available series anyway.
    """
    window = 2 * k + 1
    extreme = series.rolling(window, center=True, min_periods=window).min() if mode == "min" \
        else series.rolling(window, center=True, min_periods=window).max()
    is_candidate = series == extreme

    tie_with_earlier = pd.Series(False, index=series.index)
    for offset in range(1, k + 1):
        shifted_value = series.shift(offset)
        shifted_is_candidate = is_candidate.shift(offset).fillna(False)
        tie_with_earlier = tie_with_earlier | ((shifted_value == series) & shifted_is_candidate)

    return is_candidate & ~tie_with_earlier


def _amplitude_ok(price: float, prev_opposite_price: float | None, atr_pct: float,
                   min_swing_pct: float) -> bool:
    """Spec §2.2: discard a pivot whose move from the preceding OPPOSITE
    pivot is smaller than max(min_swing_pct, 1.5*ATR14/close), expressed
    as a percentage move. The very first pivot in a series has no
    preceding opposite pivot to measure against -- always accepted (there
    is nothing yet to filter it against)."""
    if prev_opposite_price is None or prev_opposite_price == 0:
        return True
    threshold_pct = max(min_swing_pct, atr_pct)
    move_pct = abs(price - prev_opposite_price) / prev_opposite_price * 100.0
    return move_pct >= threshold_pct


def find_pivots(df: pd.DataFrame, k: int = 5, min_swing_pct: float = 3.0,
                 atr_multiplier: float = 1.5) -> list[Pivot]:
    """Detects alternating swing low/high pivots on one symbol's OHLC
    series (already sorted ascending, reset to a 0-based positional
    index). Implements spec §2 exactly:

    1. Fractal test (k bars either side, ties broken by earliest index).
    2. Amplitude filter: a candidate's move from the preceding OPPOSITE
       pivot must be >= max(min_swing_pct, 1.5*ATR14/close*100) -- this is
       what stops the engine matching noise on thin small-caps. `df` must
       already carry an `atr14` column (computed by the caller with
       locked bars excluded -- see module docstring); rows with a missing/
       NaN atr14 fall back to min_swing_pct alone for that comparison.
    3. Alternation: the final sequence must strictly alternate low/high/
       low/high -- where two consecutive same-type candidates survive
       filtering, keep the more extreme one (lower low / higher high).

    Returns pivots in ascending index order. Never raises on malformed
    input -- returns [] if required columns are missing or there's too
    little history for even one k-bar window.
    """
    required = {"date", "high", "low", "close", "atr14"}
    if df is None or not required.issubset(df.columns) or len(df) < 2 * k + 1:
        return []

    work = df.reset_index(drop=True)
    low_candidates = _rolling_extreme_candidates(work["low"], k, "min")
    high_candidates = _rolling_extreme_candidates(work["high"], k, "max")

    atr_pct = (work["atr14"] / work["close"] * atr_multiplier * 100.0).fillna(0.0)

    raw: list[tuple[int, str, float]] = []
    for i in range(len(work)):
        if low_candidates.iat[i]:
            raw.append((i, "low", float(work["low"].iat[i])))
        if high_candidates.iat[i]:
            raw.append((i, "high", float(work["high"].iat[i])))
    raw.sort(key=lambda r: r[0])

    # Amplitude filter, applied in index order so "preceding opposite
    # pivot" always refers to the nearest surviving pivot of the other
    # kind seen so far.
    amplitude_passed: list[tuple[int, str, float]] = []
    last_opposite_price = {"low": None, "high": None}
    for i, kind, price in raw:
        opposite = "high" if kind == "low" else "low"
        threshold = max(min_swing_pct, float(atr_pct.iat[i]))
        if _amplitude_ok(price, last_opposite_price[opposite], threshold, min_swing_pct):
            amplitude_passed.append((i, kind, price))
        # Track the most recent surviving pivot of each kind, regardless of
        # whether THIS candidate itself survived, so a later pivot is still
        # measured against the last genuinely confirmed opposite extreme.
        last_opposite_price[kind] = price

    # Alternation: where consecutive survivors share a kind, keep the more
    # extreme (lowest low / highest high) and drop the other.
    alternated: list[tuple[int, str, float]] = []
    for i, kind, price in amplitude_passed:
        if alternated and alternated[-1][1] == kind:
            prev_i, prev_kind, prev_price = alternated[-1]
            more_extreme = (price < prev_price) if kind == "low" else (price > prev_price)
            if more_extreme:
                alternated[-1] = (i, kind, price)
            # else: drop the new one, keep the existing more-extreme pivot
        else:
            alternated.append((i, kind, price))

    pivots = []
    for i, kind, price in alternated:
        confirmed_at = i + k
        confirmed_date = work["date"].iat[confirmed_at] if confirmed_at < len(work) else pd.NaT
        pivots.append(Pivot(kind=kind, index=i, date=work["date"].iat[i], price=price,
                             confirmed_at_index=confirmed_at, confirmed_at_date=confirmed_date))
    return pivots
