"""news_pipeline.py — Produces news_signals.json, the file news_feed.py reads.

WHY THIS EXISTS
The V1 news design was a three-stage pipeline:
    news_fetcher.py  -> news_raw_24h.json   (raw headlines, no judgment)
    [manual LLM routine per news_routine.md] -> news_signals.json  (verdicts)
    news_feed.py     -> per-symbol verdict consumed by the engine
The middle stage was a human-in-the-loop Claude session. news_routine.md is not
in this repo, so news_signals.json was never produced and the news layer has
always scored a flat neutral 50.

WHAT THIS DOES INSTEAD
Runs stages 1 and 3 automatically with a DETERMINISTIC finance-keyword scorer in
between. That is deliberately weaker than LLM judgment, and it says so:

  * confidence is capped at "medium" and is "low" on thin coverage. It is NEVER
    "high" — only a real reading of the article can justify that.
  * materiality only escalates on explicit high-impact terms (default, results,
    dividend, merger, suspension...), never on tone alone.
  * every verdict carries the real source URLs, so any claim is checkable.
  * a symbol with no matching headline gets NO entry at all — news_feed then
    returns None and the engine treats news as neutral. Silence is never scored
    as good news.

RELEVANCE GATE
PSX market-watch gives ticker + sector code, not company names, so the query is
"<SYMBOL> PSX Pakistan" and a headline must actually contain the ticker to be
attributed to it. That favours precision over recall: fewer headlines, but a
"National Foods" story can never be attributed to National Refinery.

    python news_pipeline.py            # refresh from the live market
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import requests

log = logging.getLogger("news_pipeline")

UA = {"User-Agent": "Mozilla/5.0 (psx-intelligence news-pipeline)"}
TIMEOUT = 15
GOOGLE_NEWS_RSS = ("https://news.google.com/rss/search?q={query}"
                   "&hl=en-PK&gl=PK&ceid=PK:en")

MACRO_FEEDS = [
    ("Business Recorder", "https://www.brecorder.com/feeds/latest-news"),
    ("Dawn Business", "https://www.dawn.com/feeds/business"),
]

# Publishers whose reporting we are willing to attribute a verdict to.
CREDIBLE = ["brecorder", "business recorder", "dawn", "profit", "pakistan today",
            "mettis", "tribune", "the news", "arab news", "bloomberg", "reuters",
            "geo", "dunya", "nation", "ary"]

# --- deterministic finance lexicon. Weights are intentionally modest; this is a
# keyword heuristic, not a language model, and the score reflects that.
POS = {"profit": 2.0, "record profit": 3.0, "growth": 1.5, "surge": 2.0,
       "rally": 1.8, "upgrade": 2.0, "dividend": 1.5, "bonus": 1.5,
       "expansion": 1.5, "contract": 1.2, "award": 1.5, "approval": 1.5,
       "acquisition": 1.0, "buyback": 1.8, "high": 0.8, "rise": 1.0,
       "increase": 1.0, "gain": 1.2, "beat": 1.5, "recovery": 1.2}
NEG = {"loss": -2.0, "default": -3.0, "crash": -3.0, "plunge": -2.2,
       "decline": -1.5, "downgrade": -2.0, "suspension": -2.5, "penalty": -2.0,
       "probe": -1.5, "investigation": -1.5, "fraud": -3.0, "adverse": -1.8,
       "termination": -2.0, "shutdown": -2.2, "fall": -1.2, "drop": -1.2,
       "decrease": -1.2, "cut": -1.0, "delay": -1.0, "strike": -1.5}
HIGH_MATERIALITY = ["material information", "financial results", "dividend",
                    "merger", "acquisition", "right issue", "bonus", "default",
                    "suspension", "delisting", "profit after tax", "earnings"]


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _pub_dt(s):
    try:
        dt = parsedate_to_datetime(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _publisher(title, fallback=""):
    return title.rsplit(" - ", 1)[1].strip() if " - " in title else (fallback or "source")


def _clean_title(title):
    return title.rsplit(" - ", 1)[0].strip() if " - " in title else title


# ---------------------------------------------------------------------------
# Alias lookup, borrowed from the sibling Engine Fundamentals project's
# psxwatch.universe (37 hand-verified company profiles with real names and
# aliases). This is why per-symbol coverage used to be so thin: the query and
# the relevance gate were both `f"{symbol} PSX Pakistan"` / `\b{symbol}\b`, but
# Google News headlines almost always use the company's NAME ("Oil & Gas
# Development Company"), not the bare ticker ("OGDC") — so real, on-topic
# articles were being fetched and then thrown away by the gate that was
# supposed to confirm relevance. Querying and matching on the real name (when
# known) fixes both ends at once. Falls back to the original ticker-only
# behaviour, unchanged, for any symbol outside that 37-company universe or if
# the sibling project isn't present at all — never crashes either way.
_UNIVERSE = None


def _load_universe():
    global _UNIVERSE
    if _UNIVERSE is not None:
        return _UNIVERSE
    _UNIVERSE = {}
    try:
        import sys as _sys
        sib = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..",
            "Engine Fundamentals"))
        if sib not in _sys.path:
            _sys.path.insert(0, sib)
        from psxwatch.universe import BY_TICKER, match_tokens
        for ticker, company in BY_TICKER.items():
            _UNIVERSE[ticker] = {"name": company.name,
                                 "tokens": match_tokens(company)}
    except Exception as e:
        log.info("psxwatch.universe not available for alias lookup: %s", e)
    return _UNIVERSE


def _when_clause(cutoff):
    """Google News RSS ranks search results by RELEVANCE, not recency — a plain
    text query returns whatever it considers most on-topic across the feed's
    entire history (observed directly: months-old articles ranked above recent
    ones for the same company). Client-side filtering on pubDate>=cutoff was
    then discarding nearly everything, which is why per-symbol coverage looked
    broken even for companies with real recent news. Google's `when:Nd` search
    operator scopes the ranking server-side to an actual recency window instead
    — verified to surface real articles a plain query missed entirely."""
    days = max(1, int((datetime.now(timezone.utc) - cutoff).total_seconds() // 86400) + 1)
    return f"when:{days}d"


def _query_and_pattern(symbol, cutoff):
    """Return (search_query, relevance_regex) for one symbol."""
    when = _when_clause(cutoff)
    u = _load_universe().get(symbol.upper())
    if not u:
        return (f"{symbol} PSX Pakistan {when}",
                re.compile(rf"\b{re.escape(symbol)}\b", re.I))
    query = f"{u['name']} PSX Pakistan {when}"
    pattern = "|".join(re.escape(t) for t in u["tokens"])
    return query, re.compile(rf"\b(?:{pattern})\b", re.I)


def _fetch_rss(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return ET.fromstring(r.content)


def _items(root, cutoff):
    for it in root.iter("item"):
        title = _strip_html(it.findtext("title", ""))
        link = (it.findtext("link", "") or "").strip()
        pub = _pub_dt(it.findtext("pubDate", ""))
        if not title or not link or not pub or pub < cutoff:
            continue
        yield {"title": title, "url": link, "published": pub.isoformat(),
               "summary": _strip_html(it.findtext("description", ""))[:400]}


def fetch_symbol(symbol, cutoff):
    """Headlines that ACTUALLY name this company. Precision over recall.

    Queries and matches on the real company name + aliases when the sibling
    psxwatch universe has an entry for this ticker; otherwise falls back to
    the original ticker-only query/gate."""
    query, pat = _query_and_pattern(symbol, cutoff)
    url = GOOGLE_NEWS_RSS.format(query=quote_plus(query))
    out = []
    try:
        root = _fetch_rss(url)
    except Exception as e:
        log.warning("%s: RSS failed: %s", symbol, e)
        return out
    for it in _items(root, cutoff):
        blob = f"{it['title']} {it['summary']}"
        if not pat.search(blob):
            continue                      # relevance gate: ticker must appear
        pub = _publisher(it["title"])
        if CREDIBLE and not any(c in pub.lower() for c in CREDIBLE):
            continue                      # attribution gate: credible desks only
        it = dict(it, publisher=pub, title=_clean_title(it["title"]),
                  symbol=symbol)
        out.append(it)
    return out


def score_items(items):
    """Deterministic verdict from a symbol's headlines. Never returns 'high'
    confidence — a keyword scorer has not read the articles."""
    if not items:
        return None
    total, hits = 0.0, []
    material_pos = material_neg = False
    for it in items:
        low = f"{it['title']} {it.get('summary','')}".lower()
        s = 0.0
        for w, v in POS.items():
            if w in low:
                s += v; hits.append(w)
        for w, v in NEG.items():
            if w in low:
                s += v; hits.append(w)
        if any(h in low for h in HIGH_MATERIALITY):
            if s > 0: material_pos = True
            elif s < 0: material_neg = True
        total += max(-4.0, min(4.0, s))
    n = len(items)
    avg = total / n
    # map roughly [-4,4] -> [0,100], then shrink toward neutral on thin coverage
    raw = 50 + avg * 11
    weight = min(1.0, n / 4.0)
    score = round(50 + (raw - 50) * weight, 1)
    score = max(0.0, min(100.0, score))
    direction = "positive" if score > 56 else "negative" if score < 44 else "neutral"
    materiality = ("material_negative" if material_neg and direction == "negative"
                   else "material_positive" if material_pos and direction == "positive"
                   else "normal")
    # Keyword scoring earns "medium" at best, and only with real coverage.
    confidence = "medium" if n >= 3 and abs(score - 50) >= 6 else "low"
    uniq = sorted(set(hits))[:6]
    summary = (f"{n} headline(s) from credible desks; keyword read is {direction}"
               + (f" (terms: {', '.join(uniq)})" if uniq else "")
               + ". Keyword-derived, not article-level judgment.")
    return {"score": score, "direction": direction, "materiality": materiality,
            "confidence": confidence, "summary": summary,
            "headlines": [i["title"] for i in items][:6],
            "sources": [i["url"] for i in items][:6],
            "publishers": sorted({i["publisher"] for i in items})[:6],
            "method": "deterministic_keyword_v1",
            "caveat": "Scored by finance keyword lexicon, NOT by reading the "
                      "articles. Confidence is capped at medium by design. "
                      "Open the source URLs before acting."}


def fetch_macro(cutoff, limit=25):
    out = []
    for name, url in MACRO_FEEDS:
        try:
            root = _fetch_rss(url)
        except Exception as e:
            log.warning("macro feed %s failed: %s", name, e)
            continue
        for it in _items(root, cutoff):
            out.append(dict(it, publisher=name, title=_clean_title(it["title"])))
    out.sort(key=lambda x: x["published"], reverse=True)
    return out[:limit]


def run(symbols, window_hours=48, out_path=None, pause=0.4, with_macro=True):
    """Fetch, score, and write news_signals.json. Returns the payload."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    signals, raw, skipped = {}, [], []
    for s in symbols:
        items = fetch_symbol(s, cutoff)
        if not items:
            skipped.append(s)            # NO entry — silence is not a verdict
            continue
        v = score_items(items)
        if v:
            signals[s.upper()] = v
            raw.extend(items)
        time.sleep(pause)
    macro = fetch_macro(cutoff) if with_macro else []
    # Aggregate "market mood": the SAME deterministic keyword scorer used for
    # every per-symbol verdict above, just run over the whole macro-feed
    # headline set instead of one symbol's headlines -- reuses score_items()'s
    # existing honesty rules (confidence capped at medium, thin-coverage
    # shrinkage toward neutral, source URLs kept) rather than a separate,
    # weaker aggregate sentiment implementation.
    macro_verdict = score_items(macro) if macro else None
    payload = {"as_of": now.isoformat(), "window_hours": window_hours,
               "source": "Google News RSS (credible-desk filtered) + macro feeds",
               "method": "deterministic_keyword_v1",
               "signals": signals,
               "symbols_with_no_news": skipped,
               "macro_headlines": [{"title": m["title"], "url": m["url"],
                                    "publisher": m["publisher"],
                                    "published": m["published"]} for m in macro],
               "macro_verdict": macro_verdict,
               "note": "Verdicts are keyword-derived, never article-level "
                       "judgment; confidence is capped at medium. Symbols with "
                       "no matching headline are omitted entirely so the engine "
                       "treats them as neutral rather than positive."}
    path = out_path or _default_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return payload


def _default_path():
    """Write where news_feed.py will look for it."""
    try:
        import config
        p = getattr(config, "NEWS_SIGNALS_PATH", None)
        if p:
            return p
        base = getattr(config, "BASE_DIR", None)
        if base:
            return os.path.join(base, "news_signals.json")
    except Exception:
        pass
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "news_signals.json")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        import config
        syms = list(getattr(config, "STOCKS", []) or [])
    except Exception:
        syms = []
    if not syms:
        syms = ["OGDC", "PPL", "MARI", "HBL", "UBL", "MCB", "LUCK", "FFC",
                "ENGRO", "PSO", "HUBC", "SYS", "TRG", "BOP", "MLCF"]
    p = run(syms)
    print(f"\nWrote {_default_path()}: {len(p['signals'])}/{len(syms)} symbols "
          f"have a verdict, {len(p['symbols_with_no_news'])} had no matching "
          f"headline, {len(p['macro_headlines'])} macro headlines, "
          f"as_of {p['as_of']}")
