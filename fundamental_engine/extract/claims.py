"""Separation of verified facts from AI interpretation. The MODEL never chooses a claim type; Python assigns it.

  grounded verbatim quote from an official source (exchange/regulator/government) -> 'official_statement'
  grounded verbatim quote from any other permitted source                          -> 'news_report'
  anything the model authored itself (inference)                                   -> 'model_inference'

(A quote establishes only that the SOURCE said it; 'verified_fact' is reserved for human-reviewed evidence.)
"""
from core.config import OFFICIAL_SOURCE_TYPES

BAND_TO_CONFIDENCE = {"low": 0.3, "medium": 0.6, "high": 0.85}  # fixed Python mapping, not a model-supplied number


def claim_type(kind, grounded, source_type):
    if kind == "quote" and grounded:
        return "official_statement" if source_type in OFFICIAL_SOURCE_TYPES else "news_report"
    return "model_inference"


def classify_claims(claims, source_type):
    return [{**c, "claim_type": claim_type(c["kind"], c["grounded"], source_type)} for c in claims]
