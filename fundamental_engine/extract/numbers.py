"""Deterministic number parsing. Models never produce numbers: they point at text (a verbatim quote) and PYTHON parses it."""
import re
from decimal import Decimal, InvalidOperation

_PLAIN = re.compile(r"^\d+(\.\d+)?$")
_GROUPED = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")


def parse_number(text):
    """'1,234,567' -> Decimal; '(1,234)' -> Decimal(-1234); '-5.5' -> Decimal('-5.5'); anything ambiguous -> None.
    Accepts Pakistani/international digit grouping with commas; rejects mixed separators, text, percentages, dashes (nil)."""
    t = (text or "").strip()
    t = re.sub(r"^(rs\.?|pkr|usd|\$)\s*", "", t, flags=re.I).strip()
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1].strip()
    if t.startswith("-"):
        neg, t = (not neg), t[1:].strip()
    if not (_PLAIN.match(t) or _GROUPED.match(t)):
        return None
    try:
        v = Decimal(t.replace(",", ""))
    except InvalidOperation:
        return None
    return -v if neg else v
