"""Per-task handlers: validate model output, build the stored candidate, and map confidence. Python decides everything
that is stored; the model's output is only ever proposed content."""
import re

from extract.claims import BAND_TO_CONFIDENCE, claim_type, classify_claims
from extract.numbers import parse_number
from llm.validate import ValidationError, check_schema, norm_ws, validate_candidate


class EventHandler:
    name = "event_candidate"

    def validate(self, obj, schema, text, resolve):
        return validate_candidate(obj, schema, text, resolve)

    def extracted(self, cand, source_type):
        claims = classify_claims(cand["claims"], source_type)
        return {"event_type": cand["event_type"], "claims": claims, "tickers": cand["tickers"],
                "unresolved_tickers": cand["unresolved_tickers"], "confidence_band": cand["confidence_band"],
                "record_kind": "model_candidate"}

    def claim_types(self, extracted):
        return [c["claim_type"] for c in extracted["claims"]]


class FinancialHandler:
    """Model points at table text (verbatim quotes); PYTHON parses the numbers. No scaling by unit (calc layer's job)."""
    name = "financial_line_items"

    def validate(self, obj, schema, text, resolve):
        check_schema(obj, schema)
        src, flags, items, seen = norm_ws(text), [], [], set()
        unit = norm_ws(obj["unit_text"])
        if unit and unit not in src:
            raise ValidationError("unit_text is not verbatim in the source text")
        if not unit:
            flags.append("unit_missing: values are unscaled and need a unit before any calculation")
        for i, it in enumerate(obj["items"]):
            label, period, value = norm_ws(it["label"]), norm_ws(it["period"]), norm_ws(it["value"])
            for k, q in (("label", label), ("period", period), ("value", value)):
                if not q or q not in src:
                    raise ValidationError(f"items[{i}].{k}: not verbatim in the source text")
            parsed = parse_number(value)
            if parsed is None:
                raise ValidationError(f"items[{i}].value: {value!r} is not a parseable number")
            key = (label, period, value)
            if key in seen:
                continue
            seen.add(key)
            items.append({"label": label, "period": period, "value_text": value, "value_parsed": str(parsed), "grounded": True})
        return {"statement": obj["statement"], "unit_text": unit, "items": items,
                "confidence_band": obj["confidence_band"]}, flags

    def extracted(self, cand, source_type):
        ctype = claim_type("quote", True, source_type)
        return {**cand, "items": [{**i, "claim_type": ctype} for i in cand["items"]], "record_kind": "model_candidate"}

    def claim_types(self, extracted):
        return [i["claim_type"] for i in extracted["items"]]


HANDLERS = {"event_candidate": EventHandler(), "financial_line_items": FinancialHandler()}
