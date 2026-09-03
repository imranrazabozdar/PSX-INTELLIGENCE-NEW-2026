"""catalyst_exposure.py — generalizes the refinery study's manual method
(fundamentals_analyzer.py's 5-ratio scorer + sourced, dated qualitative
reasoning about a specific catalyst's differential impact) into a
repeatable comparison across any ticker list and any described catalyst.

This does NOT invent domain classifications. Which companies are net
beneficiaries vs exposed to a given catalyst is business-model/sector
knowledge that has to come from the caller, sourced and dated -- exactly
like "PRL is a hydro-skimming, import-competing local producer" was
sourced research in the refinery study, not something derivable from the
5 generic ratios alone. What this module DOES do automatically, from the
existing engine:
  - Pull each ticker's fundamentals_analyzer.py output (now staleness-
    flagged per Fix 2: data_as_of, age_days, stale).
  - Turn a caller-supplied per-ticker sign classification + optional
    "currently loss-making" fact into a THEORETICAL MAGNITUDE read
    (bigger swing potential for a currently underperforming beneficiary).
  - Turn the ratio engine's D/E (or a caller-supplied, sourced override
    when D/E is missing or the cached value is flagged stale) into an
    EXECUTION CAPACITY read (self-funded vs external-financing-dependent).
  - Suppress -- never default -- any ticker missing what it needs to be
    classified on either axis, exactly like the refinery study's own
    "missing inputs suppress the score" principle.

No forensic models, no new ratio computation: this reuses
fundamentals_analyzer.analyze() as its only fundamentals source, per the
project's "reuse, don't reimplement" rule and its own explicit scope
boundary (not the 53-ratio/Sloan/Beneish/Altman/Piotroski engine
described in this project's notes, which does not exist in this repo).
"""

import fundamentals_analyzer as fa

VALID_SIGNS = ("beneficiary", "exposed")


def _require(d, keys, ctx):
    missing = [k for k in keys if k not in d or d[k] is None]
    if missing:
        raise ValueError(f"{ctx} missing required field(s): {missing}")


def _execution_capacity(ticker, ratios, extra):
    """Returns (label, basis_text, sourced) from D/E, preferring a
    caller-supplied sourced override when the cached D/E is missing or
    stale, and otherwise refusing to trust a stale cached D/E at face
    value (flagging it as unverified rather than silently using it)."""
    override = (extra or {}).get("execution_override")
    de = fa.raw_ratios(ticker).get("de")
    have_de = any(h.startswith("D/E") for h in ratios.get("have", []))

    if override:
        _require(override, ("de", "source", "date"), f"{ticker} execution_override")
        de_val = override["de"]
        label = "strong (low leverage)" if de_val < 0.6 else (
            "moderate leverage" if de_val < 1.0 else "weak (high leverage)")
        basis = (f"D/E={de_val} — sourced override ({override['source']}, "
                 f"{override['date']}), used because {'the cached ratio was stale' if ratios.get('stale') else 'D/E was missing from the cached ratio engine'}.")
        return label, basis, True

    if ratios.get("stale"):
        return ("UNVERIFIED — cached D/E is stale",
                f"D/E={de} in cache but data_as_of={ratios.get('data_as_of')} "
                f"({ratios.get('age_days')} days old) exceeds the staleness threshold; "
                f"not used at face value without a sourced override.", False)

    if de is None or not have_de:
        return (None, "D/E not present in the cached ratio engine and no sourced "
                       "override was supplied.", False)

    label = "strong (low leverage)" if de < 0.6 else (
        "moderate leverage" if de < 1.0 else "weak (high leverage)")
    return label, f"D/E={de} (cached, data_as_of={ratios.get('data_as_of')}, not stale).", True


def _theoretical_magnitude(ticker, ratios, classification):
    """Returns (label, basis_text) — 'high' for a sourced currently-loss-
    making beneficiary (largest swing potential), else derived from ROE
    if present, else unavailable (never guessed)."""
    loss_making = classification.get("loss_making")
    loss_src = classification.get("loss_making_source")
    loss_date = classification.get("loss_making_date")
    if loss_making is True:
        _require(classification, ("loss_making_source", "loss_making_date"),
                  f"{ticker} loss_making=True")
        return ("high", f"Currently loss-making per {loss_src} ({loss_date}) — a "
                        f"margin-supportive catalyst has the largest theoretical swing "
                        f"potential here (loss toward breakeven/positive), before any "
                        f"volume growth is assumed.")
    if loss_making is False:
        roe = fa.raw_ratios(ticker).get("roe")
        if roe is not None:
            return ("lower", f"Already profitable per {loss_src} ({loss_date}), ROE={roe}% "
                             f"cached — the catalyst is additive to an already-positive "
                             f"base rather than a swing from loss to profit.")
        return ("lower", f"Already profitable per {loss_src} ({loss_date}) — additive to "
                         f"an already-positive base.")
    return (None, "No sourced loss_making classification supplied for this ticker; "
                  "theoretical magnitude cannot be assessed without guessing.")


def analyze_catalyst(tickers, catalyst, classifications, extra_facts=None):
    """
    tickers: list of ticker symbols to consider.
    catalyst: {"name": str, "description": str (transmission mechanism,
        plain text), "sources": [str, ...]} — catalyst-level metadata.
    classifications: {ticker: {
        "sign": "beneficiary" | "exposed",
        "reason": str, "source": str, "date": str,
        "loss_making": bool | None (optional),
        "loss_making_source": str, "loss_making_date": str (required if
            loss_making is not None),
    }}
        A ticker with NO entry here is SUPPRESSED from the whole
        comparison — sign is business/sector knowledge this module will
        not infer.
    extra_facts: optional {ticker: {"execution_override": {"de": float,
        "source": str, "date": str}, "notes": [str, ...]}} — sourced
        supplementary facts (e.g. a cash position not captured by the
        5-ratio engine), used only where documented above.

    Returns {"catalyst": ..., "results": [...], "suppressed": [...]}.
    """
    _require(catalyst, ("name", "description", "sources"), "catalyst")
    extra_facts = extra_facts or {}

    results = []
    suppressed = []

    for t in tickers:
        cls = classifications.get(t)
        if cls is None:
            suppressed.append({"ticker": t, "reason": "No sourced sign classification "
                               "supplied for this ticker — suppressed, not defaulted."})
            continue
        _require(cls, ("sign", "reason", "source", "date"), f"{t} classification")
        if cls["sign"] not in VALID_SIGNS:
            raise ValueError(f"{t}: sign must be one of {VALID_SIGNS}, got {cls['sign']!r}")

        ratios = fa.analyze(t)
        extra = extra_facts.get(t, {})

        if ratios.get("low_confidence") and not ratios.get("have"):
            suppressed.append({"ticker": t, "reason": "No fundamentals data at all in "
                               "the ratio engine for this ticker — suppressed from the "
                               "ranking (sign classification alone is not a score)."})
            continue

        magnitude_label, magnitude_basis = _theoretical_magnitude(t, ratios, cls)
        exec_label, exec_basis, exec_sourced = _execution_capacity(t, ratios, extra)

        results.append({
            "ticker": t,
            "sign": cls["sign"],
            "sign_reason": cls["reason"], "sign_source": cls["source"], "sign_date": cls["date"],
            "ratios_have": ratios.get("have", []),
            "score": ratios.get("score"),
            "data_as_of": ratios.get("data_as_of"), "age_days": ratios.get("age_days"),
            "stale": ratios.get("stale"),
            "theoretical_magnitude": magnitude_label, "magnitude_basis": magnitude_basis,
            "execution_capacity": exec_label, "execution_basis": exec_basis,
            "execution_sourced_override": exec_sourced,
            "notes": extra.get("notes", []),
        })

    return {"catalyst": catalyst, "results": results, "suppressed": suppressed}


def format_report(analysis):
    """Plain-text table for quick inspection / CLI use."""
    lines = [f"Catalyst: {analysis['catalyst']['name']}", ""]
    beneficiaries = [r for r in analysis["results"] if r["sign"] == "beneficiary"]
    exposed = [r for r in analysis["results"] if r["sign"] == "exposed"]

    def fmt(rows):
        out = []
        for r in rows:
            stale_tag = " [STALE]" if r["stale"] else ""
            out.append(f"  {r['ticker']:<8} magnitude={r['theoretical_magnitude'] or '?':<8} "
                       f"execution={r['execution_capacity'] or '?'}{stale_tag}")
        return "\n".join(out) if out else "  (none)"

    lines.append(f"Beneficiaries ({len(beneficiaries)}):")
    lines.append(fmt(beneficiaries))
    lines.append(f"Exposed ({len(exposed)}):")
    lines.append(fmt(exposed))
    lines.append(f"Suppressed ({len(analysis['suppressed'])}):")
    for s in analysis["suppressed"]:
        lines.append(f"  {s['ticker']}: {s['reason']}")
    return "\n".join(lines)
