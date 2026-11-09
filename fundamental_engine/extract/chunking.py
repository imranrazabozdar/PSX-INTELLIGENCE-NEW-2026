"""Long-document handling: split on paragraph boundaries into overlapping chunks with stable ids/hashes, so every chunk is
cached by content hash and every quote is grounded against its own chunk only."""
import hashlib
import re


def chunk_text(text, max_chars=20000, overlap_chars=500):
    paras = [p for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        p = p.strip()
        while len(p) > max_chars:                    # a single huge paragraph: hard split
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(p[:max_chars]); p = p[max_chars - overlap_chars:]
        if cur and len(cur) + len(p) + 2 > max_chars:
            chunks.append(cur)
            tail = cur[-overlap_chars:] if overlap_chars else ""
            cur = (tail + "\n\n" + p) if tail else p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    n = len(chunks)
    return [{"index": i + 1, "of": n, "sha256": hashlib.sha256(c.encode("utf-8")).hexdigest(), "text": c}
            for i, c in enumerate(chunks)]


def variant_tag(chunk):
    """Folded into schema_version so the existing UNIQUE(source_item_id, schema_version, prompt_version, model) key caches per chunk."""
    return f"#c{chunk['index']}of{chunk['of']}:{chunk['sha256'][:10]}"


def est_tokens(text):
    return max(1, len(text) // 4)
