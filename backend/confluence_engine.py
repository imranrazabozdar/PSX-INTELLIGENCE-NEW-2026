"""confluence_engine.py — aggregates every pattern-family scan's LATEST-BAR
hits into one per-symbol bullish/bearish vote count ("confluence"), so a
dashboard can show ONE bullish list and ONE bearish list ranked by how many
independent indicators agree, instead of forcing a reader to cross-check
8 separate detector tabs each with their own buy/sell list (the confusion
this module exists to fix, per explicit user request).

DESIGN CHOICES (per explicit user direction):
  - No stock is ever excluded for having only 1 agreeing indicator -- a
    symbol appears in the bullish list the moment at least one indicator
    votes BULL on it (and correspondingly for bearish), sorted with the
    most-agreed-upon symbols first, then by fewest opposing votes.
  - "Agreement" is a raw vote COUNT across indicators, not weighted by
    each indicator's own backtested track record -- several of the 8
    families below backtested as net losers at their stated-default
    settings (see each family's own detector module docstring). This
    module reports agreement exactly as asked; each family's own
    historical performance is surfaced alongside the count by the caller
    (see app.py's /patterns/confluence), not folded into the ranking
    itself, so a stock is never silently down-ranked by a judgment call
    this module didn't make.
  - A symbol with an equal bull/bear vote count is a genuine split with
    no principled tie-break -- excluded from BOTH lists rather than
    arbitrarily assigned a lean.

INDICATOR -> VOTE mapping (8 families, all read from the same
analysis_cache rows run_chart_pattern_refresh.py's daily cron already
writes -- this module makes no live detector calls of its own, so it's
only ever as fresh as the last daily refresh):
  bullish_engulfing_scan   -> every hit is BULL (bearish engulfing isn't wired into the daily scan)
  mharris_scan             -> hit['direction']       (BULL or BEAR)
  macdema_scan             -> hit['direction']       (BULL or BEAR)
  triangle_regression_scan -> every hit is BEAR (SHORT-only by design, see triangle_regression_detector.py)
  level_breakout_scan      -> hit['direction']       (BULL or BEAR)
  morning_star_scan        -> every hit is BULL (a bullish reversal pattern by definition)
  advanced_pattern_scan    -> every hit is BULL (only IHS/Double Bottom are wired, both bullish)
  gp_evolved_scan          -> hit['classification']  BUY->BULL, SELL->BEAR
"""

FAMILIES = [
    ("bullish_engulfing_scan", "Bullish Engulfing"),
    ("mharris_scan", "MHarris 5-Bar Reversal"),
    ("macdema_scan", "MACD+EMA200 Trend Resumption"),
    ("triangle_regression_scan", "Triangle Squeeze"),
    ("level_breakout_scan", "Level Break Out"),
    ("morning_star_scan", "Morning Star"),
    ("advanced_pattern_scan", "Advanced (IHS/Double Bottom)"),
    ("gp_evolved_scan", "GP-Evolved Formula"),
]

_ALWAYS_BULL = {"bullish_engulfing_scan", "morning_star_scan", "advanced_pattern_scan"}
_ALWAYS_BEAR = {"triangle_regression_scan"}


def _vote_for_hit(cache_key, hit):
    if cache_key in _ALWAYS_BULL:
        return "BULL"
    if cache_key in _ALWAYS_BEAR:
        return "BEAR"
    if cache_key == "gp_evolved_scan":
        c = hit.get("classification")
        return "BULL" if c == "BUY" else ("BEAR" if c == "SELL" else None)
    d = hit.get("direction")
    return d if d in ("BULL", "BEAR") else None


def build_confluence(scans: dict, symbol_filter=None) -> dict:
    """scans: {cache_key: scan_result_dict} -- pass whatever's available
    from scan_cache_engine.latest_many([k for k, _ in FAMILIES]); a
    missing/None entry for a family is skipped, not treated as an error
    (e.g. gp_evolved_scan before the first offline training run exists).
    symbol_filter: optional iterable of symbols to restrict to (e.g. the
    89-symbol watchlist) -- omit/None for whole-market scope.

    Returns {"bullish": [...], "bearish": [...], "families_available": N,
    "families_total": 8}, each list entry: {"symbol", "agree" (vote count
    on the winning side), "disagree" (vote count on the other side),
    "indicators" (family labels that voted this way), "opposing_indicators"
    (family labels that voted the other way)} -- sorted most-agreed-upon
    first, ties broken by fewest opposing votes, then symbol."""
    symbol_filter = set(symbol_filter) if symbol_filter is not None else None
    votes = {}
    families_available = 0
    for cache_key, family_label in FAMILIES:
        scan = scans.get(cache_key)
        if not scan or scan.get("status") not in ("ok", None):
            continue
        families_available += 1
        for hit in (scan.get("hits") or []):
            sym = hit.get("symbol")
            if not sym:
                continue
            if symbol_filter is not None and sym not in symbol_filter:
                continue
            vote = _vote_for_hit(cache_key, hit)
            if vote not in ("BULL", "BEAR"):
                continue
            entry = votes.setdefault(sym, {"BULL": [], "BEAR": []})
            entry[vote].append(family_label)

    bullish, bearish = [], []
    for sym, v in votes.items():
        n_bull, n_bear = len(v["BULL"]), len(v["BEAR"])
        if n_bull > n_bear:
            bullish.append({"symbol": sym, "agree": n_bull, "disagree": n_bear,
                             "indicators": v["BULL"], "opposing_indicators": v["BEAR"]})
        elif n_bear > n_bull:
            bearish.append({"symbol": sym, "agree": n_bear, "disagree": n_bull,
                             "indicators": v["BEAR"], "opposing_indicators": v["BULL"]})
        # n_bull == n_bear: genuine split, excluded from both lists (see module docstring)

    bullish.sort(key=lambda r: (-r["agree"], r["disagree"], r["symbol"]))
    bearish.sort(key=lambda r: (-r["agree"], r["disagree"], r["symbol"]))
    return {"bullish": bullish, "bearish": bearish,
            "families_available": families_available, "families_total": len(FAMILIES)}
