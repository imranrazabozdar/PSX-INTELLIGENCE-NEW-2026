"""Strict validation of model output. The model is untrusted: nothing it returns is used until these checks pass.

Rules enforced in Python:
  * output must be a JSON object that matches the schema exactly (no extra keys; the model cannot set claim types)
  * "quote" claims must be verbatim substrings of the source text (grounded)
  * "inference" claims may not contain digits, percentages, currency amounts or number words (models never produce numbers)
  * tickers must resolve against company_identifiers; unknown ones are dropped and flagged, never created
"""
import json
import re

NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
                "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "billion",
                "trillion", "lakh", "crore", "percent", "percentage", "half", "double", "triple", "dozen"}
_WORD_RE = re.compile(r"[a-z]+")


class ValidationError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse_json_object(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t).strip()
    try:
        obj = json.loads(t)
    except ValueError as e:
        raise ValidationError(f"not valid JSON: {e}")
    if not isinstance(obj, dict):
        raise ValidationError("top-level JSON must be an object")
    return obj


def check_schema(value, schema, path="$"):
    """Minimal JSON-Schema subset: type, enum, required, properties, additionalProperties=false, items, maxItems, maxLength."""
    if "enum" in schema:
        if value not in schema["enum"]:
            raise ValidationError(f"{path}: {value!r} not in enum")
        return
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            raise ValidationError(f"{path}: expected object")
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                raise ValidationError(f"{path}: missing key {k!r}")
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise ValidationError(f"{path}: unexpected keys {sorted(extra)}")
        for k, v in value.items():
            if k in props:
                check_schema(v, props[k], f"{path}.{k}")
    elif t == "array":
        if not isinstance(value, list):
            raise ValidationError(f"{path}: expected array")
        if len(value) > schema.get("maxItems", 10 ** 9):
            raise ValidationError(f"{path}: too many items")
        for i, v in enumerate(value):
            check_schema(v, schema.get("items", {}), f"{path}[{i}]")
    elif t == "string":
        if not isinstance(value, str):
            raise ValidationError(f"{path}: expected string")
        if len(value) > schema.get("maxLength", 10 ** 9):
            raise ValidationError(f"{path}: string too long")
    elif t in ("number", "integer", "boolean"):
        raise ValidationError(f"{path}: numeric/boolean fields are not allowed in model output")


def has_number(text):
    if re.search(r"\d|%|[$€£¥₨]|\brs\.?\b", text, re.I):
        return True
    return any(w in NUMBER_WORDS for w in _WORD_RE.findall(text.lower()))


def validate_candidate(obj, schema, source_text, resolve_ticker):
    """Returns a normalised candidate dict plus review flags. Raises ValidationError on any hard violation.
    resolve_ticker(ticker) -> company_id or None."""
    check_schema(obj, schema)
    src = norm_ws(source_text)
    claims, flags = [], []
    for i, c in enumerate(obj["claims"]):
        text = norm_ws(c["text"])
        if not text:
            raise ValidationError(f"claims[{i}]: empty text")
        if c["kind"] == "quote":
            if text not in src:
                raise ValidationError(f"claims[{i}]: quote is not verbatim in the source text")
            claims.append({"kind": "quote", "text": text, "grounded": True})
        else:
            if has_number(text):
                raise ValidationError(f"claims[{i}]: inference contains a number (models must not produce numbers)")
            claims.append({"kind": "inference", "text": text, "grounded": False})
    resolved, unresolved = [], []
    for t in obj["tickers"]:
        t = t.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{1,16}", t):
            unresolved.append(t)
            continue
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])", source_text):
            unresolved.append(t)  # not literally present in the document: possible hallucination
            flags.append(f"ticker {t} not found in source text")
            continue
        cid = resolve_ticker(t)
        (resolved if cid else unresolved).append({"ticker": t, "company_id": cid} if cid else t)
    if unresolved:
        flags.append(f"unresolved tickers dropped: {unresolved}")
    return {"event_type": obj["event_type"], "claims": claims, "tickers": resolved, "unresolved_tickers": unresolved,
            "confidence_band": obj["confidence_band"]}, flags
