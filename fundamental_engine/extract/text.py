"""Builds the ONLY text that may be sent to a model for a stored item, honouring the source's retention_mode:
    metadata_only      -> the headline (title) only: nothing else is retained or permitted
    excerpt            -> title + permitted_excerpt (<=1000 chars)
    full_text_permitted-> title + permitted_excerpt here (full text must be supplied by an approved fetch path, not built here)
"""
import re


def item_text(title, permitted_excerpt, retention_mode):
    parts = [re.sub(r"\s+", " ", title or "").strip()]
    if retention_mode in ("excerpt", "full_text_permitted") and permitted_excerpt:
        parts.append(re.sub(r"\s+", " ", permitted_excerpt).strip())
    return "\n".join(p for p in parts if p)
