"""Deterministic cross-source story de-duplication (dedup@v1). Pure functions: no DB writes, original items untouched.

normalize_title(): Unicode NFKC, case-folded, quotes/dashes unified, publisher decorations and wire prefixes stripped,
  punctuation removed, currency/percent/number spellings unified (Rs 6.59 = Rs6.59, 12.31pc = 12.31 percent, 1,500 = 1500),
  leading articles dropped. Numbers are KEPT: two headlines with different figures are different facts.
fingerprint(): SHA-256 of the normalised token sequence. Same fingerprint = EXACT duplicate (safe to skip a model call).
similarity(): token Jaccard + identical numeric tokens => NEAR duplicate: REPORTED only, never skipped automatically.
"""
import hashlib
import re
import unicodedata

VERSION = "dedup@v1"
PUBLISHERS = ["dawn.com", "dawn", "business recorder", "brecorder.com", "brecorder", "the express tribune", "express tribune",
              "tribune.com.pk", "tribune", "reuters", "associated press", "ap", "afp", "bloomberg", "pbs", "pakistan bureau of statistics",
              "app", "the news", "the news international", "geo news", "ary news"]
_PUB = "|".join(sorted((re.escape(p) for p in PUBLISHERS), key=len, reverse=True))
_SUFFIX = re.compile(rf"\s*[\|\-–—:•]\s*(?:{_PUB})(?:\s+(?:news|report|desk))?\s*$", re.I)
_PREFIX_PUB = re.compile(rf"^\s*(?:{_PUB})\s*[:|\-–—]\s+", re.I)
_WIRE = re.compile(r"^\s*(?:update|updated|exclusive|breaking|live|watch|video|analysis|factbox|explainer)\s*\d*\s*[-–—:|]\s*", re.I)
_ARTICLES = {"the", "a", "an"}
NEAR_JACCARD = 0.8
MIN_NEAR_TOKENS = 4


def _canon_chars(s):
    s = unicodedata.normalize("NFKC", s or "")
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("−", "-"), (" ", " ")):
        s = s.replace(a, b)
    return s


def normalize_tokens(title):
    s = _canon_chars(title)
    for _ in range(3):                                   # decorations can stack: "UPDATE 2 - ... | Dawn"
        s2 = _WIRE.sub("", _PREFIX_PUB.sub("", _SUFFIX.sub("", s)))
        if s2 == s:
            break
        s = s2
    s = s.casefold()
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)                            # 1,500 -> 1500
    s = re.sub(r"\b(rs|pkr|usd)\.?\s*(?=\d)", r"\1", s)                   # Rs 6.59 / Rs. 6.59 -> rs6.59
    s = re.sub(r"\$\s*(?=\d)", "usd", s)
    s = re.sub(r"(?<=\d)\s*(?:per\s*cent|percent|pc|%)(?![a-z])", "pc", s)  # 12.31 percent / 12.31% / 12.31pc -> 12.31pc
    s = s.replace("'", "")                                                # hsd's -> hsds, don't -> dont
    s = re.sub(r"(?<![a-z0-9])-|-(?![a-z0-9])", " ", s)                   # keep hyphens only inside words/numbers (4-1/2)
    s = re.sub(r"[^a-z0-9.\-/ ]+", " ", s)
    s = re.sub(r"(?<![0-9])\.|\.(?![0-9])", " ", s)                       # keep dots only inside numbers
    tokens = [t for t in s.split() if t]
    return [t for t in tokens if t not in _ARTICLES]


def normalize_title(title):
    return " ".join(normalize_tokens(title))


def fingerprint(title):
    toks = normalize_tokens(title)
    return hashlib.sha256(" ".join(toks).encode("utf-8")).hexdigest() if toks else None


def _numbers(tokens):
    return {t for t in tokens if re.search(r"\d", t)}


def similarity(a, b):
    ta, tb = normalize_tokens(a), normalize_tokens(b)
    sa, sb = set(ta), set(tb)
    if not sa or not sb:
        return {"jaccard": 0.0, "same_numbers": False, "near_duplicate": False}
    jac = len(sa & sb) / len(sa | sb)
    same_nums = _numbers(ta) == _numbers(tb)
    return {"jaccard": round(jac, 3), "same_numbers": same_nums,
            "near_duplicate": bool(jac >= NEAR_JACCARD and same_nums and min(len(sa), len(sb)) >= MIN_NEAR_TOKENS)}


def group_items(items):
    """items: iterable of {'source_item_id','source_id','title'} in PREFERENCE order (earliest/best first).
    Returns {'exact': [[ids...]], 'near': [(id_a, id_b, similarity)], 'first_of': {fingerprint: id}, 'duplicate_of': {id: first_id}}."""
    first_of, dup_of, groups, rows = {}, {}, {}, []
    for it in items:
        fp = fingerprint(it["title"])
        rows.append((it, fp))
        if fp is None:
            continue
        if fp in first_of:
            dup_of[it["source_item_id"]] = first_of[fp]
            groups[fp].append(it["source_item_id"])
        else:
            first_of[fp] = it["source_item_id"]
            groups[fp] = [it["source_item_id"]]
    near = []
    firsts = [(it, fp) for it, fp in rows if fp and first_of[fp] == it["source_item_id"]]
    for i in range(len(firsts)):                         # near-duplicate scan among distinct stories only (reported, never skipped)
        for j in range(i + 1, len(firsts)):
            s = similarity(firsts[i][0]["title"], firsts[j][0]["title"])
            if s["near_duplicate"]:
                near.append((firsts[i][0]["source_item_id"], firsts[j][0]["source_item_id"], s))
    return {"exact": [g for g in groups.values() if len(g) > 1], "near": near, "first_of": first_of, "duplicate_of": dup_of}


def cluster_plan(group, now):
    """Statements an APPROVED step could use to persist exact groups in the existing story_clusters/story_cluster_members
    tables (no migration needed). NOT executed anywhere by default: the originals stay untouched either way."""
    stmts = []
    for ids in group["exact"]:
        key = "dedup@v1:" + str(min(ids))
        stmts.append(("INSERT OR IGNORE INTO story_clusters(cluster_key,event_id,created_at_utc) VALUES(?,NULL,?)", (key, now)))
        for i in ids:
            stmts.append(("INSERT OR IGNORE INTO story_cluster_members(cluster_id,source_item_id,similarity,is_near_duplicate,added_at_utc) "
                          "VALUES((SELECT cluster_id FROM story_clusters WHERE cluster_key=?),?,1.0,0,?)", (key, i, now)))
    return stmts
