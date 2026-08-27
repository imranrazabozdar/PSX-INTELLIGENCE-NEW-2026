"""orchestrator.py — THE INTEGRATION LAYER.

The V1 engine was a pipeline: each analyzer produced a section score, a blender
combined them, a risk layer vetoed, and a signal layer decided. That pipeline
was driven by `main.py`, which did not survive the port to the FastAPI service
(fundamentals_fetcher.py still references `python main.py fundamentals`). The
analyzers all survived; the conductor did not — which is why, until now, nothing
in backend/ talked to anything else.

This module rebuilds that conductor as an importable function so the API can
serve a single integrated view per symbol:

    technical_analyzer.analyze()   ─┐
    fundamentals_analyzer.analyze()─┼→ scoring_engine.compute() → score+confidence
    sentiment/news (news_feed)     ─┤                                    │
    macro context                  ─┘                                    ▼
                        risk_manager.assess()  → vetoes → signal_generator.generate()
                        shariah_checker.check() ──────────┘        │
                        market_regime.assess_regime() ─────────────┘
                                                                   ▼
                     Strong Buy / Buy / Watch / Hold / Avoid / Exit + reasons

HONESTY CONTRACT (inherited from every module it calls):
  * Any engine that cannot run is reported as unavailable WITH the reason. Its
    section falls back to a NEUTRAL 50 flagged low_confidence — which
    scoring_engine already handles by docking confidence in proportion to that
    section's weight. A missing input never becomes a bullish input.
  * Nothing here invents a number. Every value is traceable to a named engine.
  * The output is evidence ranking, not a prediction or a probability of profit.
"""

import logging
from datetime import datetime, timezone

log = logging.getLogger("orchestrator")

NEUTRAL = {"score": 50.0, "low_confidence": True}


def _safe(fn, *a, **k):
    """Run an engine; return (result, error_string_or_None). Never raises."""
    try:
        return fn(*a, **k), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _neutral_section(name, reason):
    return dict(NEUTRAL, section=name, unavailable=reason,
                notes=[f"{name} unavailable ({reason}) — neutral 50, "
                       f"confidence reduced. No value fabricated."])


def decide(symbol, quote=None, capital=1_000_000, prev_signal=None,
           technical=None, deps=None):
    """Run the full integrated pipeline for one symbol.

    `deps` lets the caller inject already-imported modules (app.py holds them
    behind defensive try/except, so we reuse rather than re-import).
    `technical` lets the caller pass a technical_analyzer result it already
    computed, avoiding a second history fetch.
    """
    deps = deps or {}
    sym = symbol.upper()
    out = {"symbol": sym,
           "as_of": datetime.now(timezone.utc).isoformat(),
           "engines": {}, "unavailable": {}}

    tech_mod = deps.get("technical")
    score_mod = deps.get("scoring")
    signal_mod = deps.get("signal")
    risk_mod = deps.get("risk")
    shariah_mod = deps.get("shariah")
    regime_mod = deps.get("regime")
    fundamentals_fn = deps.get("fundamentals")
    news_fn = deps.get("news")

    # ---------------------------------------------------------- 1. TECHNICAL
    if technical is None and tech_mod is not None:
        technical, err = _safe(tech_mod, sym)
        if err:
            out["unavailable"]["technical"] = err
    if not isinstance(technical, dict) or "score" not in technical:
        reason = out["unavailable"].get("technical", "engine or history unavailable")
        technical = dict(_neutral_section("technical", reason),
                         classification="Unknown", price=(quote or {}).get("price"))
        out["unavailable"].setdefault("technical", reason)
    else:
        out["engines"]["technical"] = {
            "score": technical.get("score"),
            "classification": technical.get("classification"),
            "rsi": technical.get("rsi"), "macd_hist": technical.get("macd_hist"),
            "ema20": technical.get("ema20"), "ema50": technical.get("ema50"),
            "ema200": technical.get("ema200"),
            "support": technical.get("support"), "resistance": technical.get("resistance"),
            "stop_loss": technical.get("stop_loss"), "target1": technical.get("target1"),
            "headroom_rr": technical.get("headroom_rr"),
            "atr": technical.get("atr"), "atr_method": technical.get("atr_method"),
            "cmf": technical.get("cmf"), "obv_up": technical.get("obv_up"),
            "breakout": technical.get("breakout"), "breakdown": technical.get("breakdown"),
            "extended": technical.get("extended"),
            "accumulation_candidate": technical.get("accumulation_candidate"),
            "accumulation_reasons": technical.get("accumulation_reasons"),
            "pullback_ready": technical.get("pullback_ready"),
            "observations": technical.get("observations"),
            "history_source": technical.get("history_source"),
        }

    # ------------------------------------------------------ 2. FUNDAMENTALS
    fundamentals = None
    if fundamentals_fn is not None:
        fundamentals, err = _safe(fundamentals_fn, sym)
        if err:
            out["unavailable"]["fundamentals"] = err
    if not isinstance(fundamentals, dict) or "score" not in fundamentals:
        fundamentals = _neutral_section(
            "fundamentals", out["unavailable"].get("fundamentals", "no ratios available"))
    else:
        out["engines"]["fundamentals"] = {
            "score": fundamentals.get("score"), "as_of": fundamentals.get("as_of"),
            "have": fundamentals.get("have"),
            "low_confidence": fundamentals.get("low_confidence"),
            "notes": fundamentals.get("notes")}

    # ------------------------------------------------- 3. NEWS / SENTIMENT
    # sentiment_analyzer needs the DB-backed news table; the authentic feed
    # (news_signals.json) is the primary path and is read directly here.
    sentiment = None
    if news_fn is not None:
        verdict, err = _safe(news_fn, sym)
        if err:
            out["unavailable"]["news"] = err
        elif verdict and verdict.get("score") is not None:
            sentiment = {"score": float(verdict["score"]),
                         "low_confidence": (verdict.get("confidence") or "").lower() == "low",
                         "flags": [], "verdict": verdict.get("summary"),
                         "direction": verdict.get("direction"),
                         "materiality": verdict.get("materiality"),
                         "sources": verdict.get("sources", [])}
            if verdict.get("materiality") == "material_negative":
                sentiment["flags"].append("MATERIAL NEGATIVE news (authentic source)")
            out["engines"]["news"] = sentiment
    if sentiment is None:
        sentiment = dict(_neutral_section(
            "news", out["unavailable"].get("news", "no fresh authentic verdict")),
            flags=[])

    # macro is not separately wired yet (macro_news_analyzer needs the DB news
    # table populated); it enters as an explicit neutral rather than silently.
    macro = _neutral_section("macro", "macro_news_analyzer not wired to a "
                                      "populated news table yet")
    macro["bad_news_flag"] = False
    macro["bad_news"] = []

    # ------------------------------------------------------------ 4. BLEND
    blended = None
    if score_mod is not None:
        # scoring_engine indexes config.WEIGHTS directly for macro_news /
        # sentiment / technical, and reads "fundamentals" (PLURAL). Two real
        # failure modes seen in the wild:
        #   1. A missing key raises KeyError and loses the tuned blend entirely.
        #   2. A config written as "fundamental" (SINGULAR) never matches, so
        #      that weight is silently ignored and the applied weights no longer
        #      sum to 1.0 — depressing every score and capping the maximum.
        #      (OGDC 2026-08: 0.7*85.6 + 0.1*50 = 64.9 with 0.2 of the weight
        #      unassigned; fundamentals contributed nothing despite being set.)
        # So: map known aliases onto the names scoring_engine actually reads,
        # drop keys that are not scoring sections, fill gaps with 0.0, and
        # renormalize so the weights sum to 1.0. Reported in `notes`.
        try:
            import config as _cfg
            _w = getattr(_cfg, "WEIGHTS", None)
            if isinstance(_w, dict):
                _SECTIONS = ("macro_news", "sentiment", "technical", "fundamentals")
                _ALIAS = {"fundamental": "fundamentals", "fundamentals": "fundamentals",
                          "macro": "macro_news", "macro_news": "macro_news",
                          "news": "macro_news", "sentiment": "sentiment",
                          "technical": "technical", "tech": "technical"}
                _before = dict(_w)
                _merged = {k: 0.0 for k in _SECTIONS}
                _ignored = {}
                for k, v in _before.items():
                    tgt = _ALIAS.get(str(k).strip().lower())
                    if tgt:
                        _merged[tgt] += float(v or 0)
                    else:
                        _ignored[k] = v
                _total = sum(_merged.values())
                if _total > 0 and abs(_total - 1.0) > 1e-6:
                    _merged = {k: round(v / _total, 4) for k, v in _merged.items()}
                _w.clear(); _w.update(_merged)
                _n = out.setdefault("notes", [])
                _n.append("config.WEIGHTS as written: " +
                          ", ".join(f"{k}={v}" for k, v in _before.items()))
                _n.append("weights applied (aliases mapped, renormalized to 1.0): " +
                          ", ".join(f"{k}={v}" for k, v in _merged.items()))
                if _ignored:
                    _n.append("config.WEIGHTS keys IGNORED (not scoring sections): " +
                              ", ".join(f"{k}={v}" for k, v in _ignored.items()))
                if abs(_total - 1.0) > 1e-6:
                    _n.append(f"WARNING: config.WEIGHTS summed to {round(_total,4)}, "
                              "not 1.0 — rescaled. Fix config.py so the intended "
                              "weighting is explicit.")
        except Exception:
            pass
        blended, err = _safe(score_mod.compute, sym, macro, sentiment, technical,
                             fundamentals, technical.get("tech_flags"))
        if err:
            out["unavailable"]["scoring"] = err
    if blended is None:
        # Transparent equal-ish fallback so the endpoint still returns something
        # traceable; clearly labelled as NOT the tuned V1 blend.
        parts = [technical.get("score", 50), fundamentals.get("score", 50)]
        blended = {"final_score": round(sum(parts) / len(parts), 1),
                   "confidence": 40.0, "data_quality": "fallback blend",
                   "weak_sections": ["scoring_engine unavailable"],
                   "history_note": "scoring_engine not available — simple mean of "
                                   "technical and fundamentals, NOT the tuned "
                                   "V1 weighting.",
                   "breakdown": {"technical": technical.get("score"),
                                 "fundamentals": fundamentals.get("score")}}
    out["scoring"] = blended
    final_score = blended.get("final_score", 50.0)
    confidence = blended.get("confidence", 40.0)

    # ----------------------------------------------------------- 5. REGIME
    regime, regime_pct = None, None
    if regime_mod is not None:
        r, err = _safe(regime_mod.assess_regime)
        if err:
            out["unavailable"]["regime"] = err
        elif isinstance(r, dict):
            regime = r.get("regime")
            regime_pct = r.get("pct_above")
            out["engines"]["regime"] = r
    if regime is None:
        out["unavailable"].setdefault("regime", "benchmark index unavailable")
        # market_regime's own contract: unknown regime fails the gate OPEN.

    # ---------------------------------------------------------- 6. SHARIAH
    # The caller (app.py) resolves this using PSX's LIVE index membership, which
    # is stronger and fresher evidence than a hand-maintained list. If it passed
    # a verdict, honour it; otherwise fall back to the config-list checker.
    shariah = deps.get("shariah_verdict")
    if isinstance(shariah, dict) and "eligible_for_ranking" in shariah:
        out["engines"]["shariah"] = shariah
    else:
        shariah = {"eligible_for_ranking": True,
                   "status": "Unverified — shariah_checker unavailable",
                   "source": "none"}
        if shariah_mod is not None:
            s, err = _safe(shariah_mod.check, sym)
            if err:
                out["unavailable"]["shariah"] = err
            elif isinstance(s, dict):
                shariah = s
                out["engines"]["shariah"] = s

    # ------------------------------------------------------------- 7. RISK
    risk = {"risk_level": "Unknown", "warnings": [], "vetoes": [],
            "position_sizing": None}
    if risk_mod is not None:
        r, err = _safe(risk_mod.assess, sym, technical, sentiment, macro,
                       capital_pkr=capital, regime=regime,
                       regime_pct_above=regime_pct)
        if err:
            out["unavailable"]["risk"] = err
        elif isinstance(r, dict):
            risk = r
            out["engines"]["risk"] = r

    # ----------------------------------------------------------- 8. SIGNAL
    # signal_generator binds T = config.SIGNAL_THRESHOLDS at import and indexes
    # T["strong_buy"|"buy"|"watch"|"hold"] directly. A config missing any of
    # those band keys raises KeyError and no decision is produced at all. Fill
    # only the ABSENT keys, using the bands documented in signal_generator's own
    # messages ("Buy band 70-80", "Watch band 60-70", "Hold band 50-60"), and
    # report exactly what was missing so it can be set deliberately in config.py.
    # Mutating in place reaches signal_generator's already-bound reference.
    try:
        import config as _cfg
        _T = getattr(_cfg, "SIGNAL_THRESHOLDS", None)
        if isinstance(_T, dict):
            _defaults = {"strong_buy": 80, "buy": 70, "watch": 60, "hold": 50}
            _added = {k: v for k, v in _defaults.items() if k not in _T}
            if _added:
                _T.update(_added)
                out.setdefault("notes", []).append(
                    "config.SIGNAL_THRESHOLDS was missing " +
                    ", ".join(f"{k}" for k in _added) +
                    " — filled with documented V1 defaults " +
                    ", ".join(f"{k}={v}" for k, v in _added.items()) +
                    ". Set these explicitly in config.py; they decide every signal.")
    except Exception:
        pass

    decision = None
    if signal_mod is not None:
        d, err = _safe(signal_mod.generate, sym, final_score, confidence, risk,
                       shariah, technical, regime=regime,
                       prev_signal=prev_signal, regime_pct_above=regime_pct)
        if err:
            out["unavailable"]["signal"] = err
        elif isinstance(d, dict):
            decision = d
    if decision is None:
        decision = {"signal": "Unavailable",
                    "reasons": ["signal_generator could not run — no decision is "
                                "guessed from the score alone."],
                    "confidence": confidence, "confluence": 0,
                    "confluence_dims": []}
    out["decision"] = decision

    # --------------------------------------------------------- 9. PROVENANCE
    ran = sorted(out["engines"].keys())
    missing = sorted(out["unavailable"].keys())
    out["integration"] = {
        "engines_ran": ran, "engines_unavailable": missing,
        "coverage": f"{len(ran)}/{len(ran) + len(missing)} layers",
        "contract": "Unavailable layers enter as NEUTRAL 50 flagged "
                    "low_confidence, which reduces confidence in proportion to "
                    "that layer's weight. Missing evidence is never treated as "
                    "positive evidence, and no value here is fabricated.",
        "meaning": "Evidence ranking across layers — not a prediction, not a "
                   "probability of profit. Manual confirmation required."}
    return out
