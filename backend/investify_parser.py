"""Offline parser for Investify's public "Company Announcements" page.

Pure function of an HTML string: NO network, NO database, never follows or fetches any link.
Extracts only public facts (ticker, timestamp, category, title, PSX filing id) and deliberately
ignores Investify's own content (summaries, "Highlights", sentiment chips) and the PDF links.
See docs/INVESTIFY_ANNOUNCEMENT_MAPPING.md and docs/SOURCE_PERMISSION_LOG.md (PILOT-2026-11-09-04).
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE_URL = "https://www.investify.pk/"
SENTIMENT_WORDS = {"neutral", "positive", "negative", "bullish", "bearish", "mixed"}
_TICKER_RE = re.compile(r"^/company/([A-Za-z0-9]{1,16})(?:/|$)")
_DEEP_RE = re.compile(r"^/announcements/([A-Za-z0-9]{1,16})/dps-pdf-([0-9]+(?:-[0-9]+)?)/?$")


def _utc_iso(value):
    """'2026-11-06T12:45:00.000Z' -> '2026-11-06T12:45:00Z'; None if not a valid UTC timestamp."""
    try:
        dt = datetime.strptime(value.strip().replace(".000Z", "Z"), "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, AttributeError):
        return None
    return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _category(card):
    """First pill-shaped span that is not a sentiment chip (category chip is the primary-coloured one)."""
    pills = [s for s in card.find_all("span") if "rounded-full" in (s.get("class") or [])]
    for s in pills:
        text = s.get_text(" ", strip=True)
        if text and text.lower() not in SENTIMENT_WORDS and "text-primary" in (s.get("class") or []):
            return text
    for s in pills:
        text = s.get_text(" ", strip=True)
        if text and text.lower() not in SENTIMENT_WORDS:
            return text
    return None


def parse_announcements(html):
    """Return a list of dicts: ticker, timestamp_utc, category, title, psx_id (+ deep_link).
    Malformed cards (any required field missing/invalid) are skipped, never guessed."""
    soup = BeautifulSoup(html, "lxml")
    items, seen = [], set()
    for card in soup.select('[data-announcement-row="true"]'):
        h3a = card.select_one("h3 a[href]")
        if h3a is None:
            continue
        m = _DEEP_RE.match(h3a["href"])
        if not m:
            continue
        deep_ticker, psx_id = m.group(1).upper(), m.group(2)
        link = card.find("a", href=_TICKER_RE)
        ticker = _TICKER_RE.match(link["href"]).group(1).upper() if link else None
        if ticker is None or ticker != deep_ticker:  # the two ticker sources must agree
            continue
        time_el = card.find("time")
        ts = _utc_iso(time_el.get("datetime")) if time_el else None
        title = re.sub(r"\s+", " ", h3a.get_text(" ", strip=True))
        category = _category(card)
        if not (ts and title and category) or psx_id in seen:
            continue
        seen.add(psx_id)
        items.append({"ticker": ticker, "timestamp_utc": ts, "category": category, "title": title,
                      "psx_id": psx_id, "deep_link": urljoin(BASE_URL, h3a["href"])})
    return items


# ------------------------------------------------------------------ source_items mapping (DESIGN)
SOURCE_ID = "investify"           # honest provenance: we read it from Investify (row stays RESTRICTED)
DOCUMENT_TYPE = "announcement"
RETRIEVAL_METHOD = "html"          # server-rendered HTML page; 'api' would be false
ACCESS_STATUS = "restricted"       # conservative: source is RESTRICTED pending written permission


def facts_sha256(item):
    """content_sha256 over the public facts only, never over Investify's proprietary text."""
    canon = json.dumps([item["ticker"], item["timestamp_utc"], item["category"], item["title"], item["psx_id"]],
                       ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def to_source_item(item, collected_at_utc, collection_run_id=None):
    """Column -> value mapping for one source_items INSERT. Pure; executes nothing."""
    return {
        "source_id": SOURCE_ID,
        "canonical_url": item["deep_link"],
        "external_id": f"psx_filing:{item['psx_id']}",
        "title": item["title"],
        "published_at_utc": item["timestamp_utc"],
        "published_at_raw": item["timestamp_utc"],
        "event_date": item["timestamp_utc"][:10],          # note: UTC date; PKT date may be +1 late evening
        "collected_at_utc": collected_at_utc,
        "content_sha256": facts_sha256(item),
        "permitted_excerpt": None,                          # never store Investify's summary text
        "content_location": None,                           # the PDF is not fetched; manual ingester handles PDFs
        "access_status": ACCESS_STATUS,
        "original_url": item["deep_link"],
        "retrieval_method": RETRIEVAL_METHOD,
        "collection_run_id": collection_run_id,
        "document_type": DOCUMENT_TYPE,
        "publication_time_status": "known",
        "source_metadata_json": json.dumps(
            {"ticker": item["ticker"], "category": item["category"], "psx_filing_id": item["psx_id"],
             "via": "investify.pk/announcements"}, sort_keys=True),
    }
