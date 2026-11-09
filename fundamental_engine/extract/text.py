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


def item_text_basis(title, permitted_excerpt, retention_mode, acquired_text=None):
    """(text, basis). Full text is used ONLY when it was acquired through sources.acquire (hash-verified) and the registry permits it;
    otherwise the basis is 'headline' (title only) or 'excerpt' (title + permitted excerpt). Never relabelled."""
    if acquired_text and retention_mode == "full_text_permitted":
        return re.sub(r"[ \t]+", " ", acquired_text).strip(), "full_text"
    base = item_text(title, permitted_excerpt, retention_mode)
    has_excerpt = retention_mode in ("excerpt", "full_text_permitted") and bool(permitted_excerpt)
    return base, ("excerpt" if has_excerpt else "headline")
