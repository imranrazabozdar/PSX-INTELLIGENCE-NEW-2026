"""PILOT-2026-11-09-04 (OWNER OVERRIDE, see docs/SOURCE_PERMISSION_LOG.md).

Read-only console test: fetch ONE public Investify page and print text-based
headlines/announcement snippets. No database, no files, no login.

Honest client: project User-Agent only (no browser-mimicking headers).
Polite: 4.5-9.5 s random delay before every request, robots.txt checked first and
respected, at most 3 requests per run. On a WAF block / CAPTCHA / challenge it stops,
reports, and exits with code 3 -- it never tries to get around it.

    python backend/investify_pilot.py [URL]        # default https://investify.pk/
Exit codes: 0 ok, 2 refused by robots.txt / bad URL, 3 blocked (WAF/CAPTCHA/rate limit), 4 network/other error.
"""
import random
import re
import sys
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

APPROVAL_ID = "PILOT-2026-11-09-04"
DEFAULT_URL = "https://investify.pk/"
USER_AGENT = "Mozilla/5.0 (compatible; PSX-NEWS-INTELLIGENCE research bot, contact owner)"
HEADERS = {"User-Agent": USER_AGENT}  # deliberately nothing else: no Referer, no Sec-Fetch-*
JITTER_MIN, JITTER_MAX = 4.5, 9.5
REQUEST_CAP = 3
BLOCK_STATUSES = {401, 403, 407, 429, 451, 503}
BLOCK_MARKERS = ("captcha", "recaptcha", "hcaptcha", "cf-chl", "cf-challenge", "just a moment",
                 "attention required", "access denied", "request blocked", "are you a robot",
                 "unusual traffic", "ddos protection")


class Blocked(Exception):
    pass


class Budget:
    def __init__(self, cap=REQUEST_CAP):
        self.cap, self.used = cap, 0

    def take(self):
        if self.used >= self.cap:
            raise RuntimeError(f"request cap {self.cap} reached")
        self.used += 1


def polite_get(url, budget, session=None, sleep=time.sleep, rng=random.uniform, timeout=25):
    """Jitter first, then one honest GET. Raises Blocked on WAF/CAPTCHA signals."""
    budget.take()
    sleep(rng(JITTER_MIN, JITTER_MAX))
    resp = (session or requests).get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    check_block(resp)
    return resp


def check_block(resp):
    if resp.status_code in BLOCK_STATUSES:
        raise Blocked(f"HTTP {resp.status_code} from {urlparse(resp.url).netloc}")
    head = (resp.text or "")[:20000].lower()
    server_hdr = " ".join(f"{k}:{v}" for k, v in resp.headers.items()).lower()
    for m in BLOCK_MARKERS:
        if m in head or (m.startswith("cf-") and m in server_hdr):
            raise Blocked(f"challenge/CAPTCHA marker {m!r} on page (HTTP {resp.status_code})")


def allowed_by_robots(url, budget, session=None, sleep=time.sleep, rng=random.uniform):
    """Fetch robots.txt (counts toward the cap, jittered). 404/no robots = allowed."""
    p = urlparse(url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    budget.take()
    sleep(rng(JITTER_MIN, JITTER_MAX))
    resp = (session or requests).get(robots_url, headers=HEADERS, timeout=25)
    if resp.status_code in BLOCK_STATUSES:
        raise Blocked(f"robots.txt: HTTP {resp.status_code}")
    if resp.status_code >= 400:
        return True
    rp = robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp.can_fetch(USER_AGENT, url) and rp.can_fetch("*", url)


def extract_items(html, limit=25):
    """Headline-ish text from a public page: headings and links inside article-like blocks."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "nav", "footer"]):
        t.decompose()
    seen, out = set(), []
    for el in soup.select("h1,h2,h3,h4,article a,.news a,.announcement a,[class*=announce] a,[class*=news] a"):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if 15 <= len(text) <= 240 and text.lower() not in seen:
            seen.add(text.lower())
            href = el.get("href") if el.name == "a" else None
            out.append((text, href))
        if len(out) >= limit:
            break
    return out


def run(url=DEFAULT_URL, session=None, sleep=time.sleep, rng=random.uniform, out=print):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        out(f"bad URL: {url}")
        return 2
    budget = Budget()
    out(f"{APPROVAL_ID} (owner override) read-only test -> {url}")
    out(f"UA: {USER_AGENT} | jitter {JITTER_MIN}-{JITTER_MAX}s | cap {REQUEST_CAP} requests | no DB writes")
    try:
        if not allowed_by_robots(url, budget, session, sleep, rng):
            out("robots.txt disallows this URL for our agent: stopping, nothing fetched.")
            return 2
        resp = polite_get(url, budget, session, sleep, rng)
    except Blocked as e:
        out(f"BLOCKED: {e}. Not retrying and not attempting any bypass. Requests used: {budget.used}.")
        return 3
    except requests.RequestException as e:
        out(f"network error: {type(e).__name__}: {e}")
        return 4
    out(f"HTTP {resp.status_code}, {len(resp.content)} bytes, content-type {resp.headers.get('content-type')}")
    items = extract_items(resp.text)
    if not items:
        out("no headline-like text found (page may be rendered by JavaScript; not worked around).")
    for i, (text, href) in enumerate(items, 1):
        out(f"{i:2d}. {text}" + (f"  [{href}]" if href else ""))
    out(f"done. requests used: {budget.used}/{REQUEST_CAP}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
