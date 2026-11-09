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
from urllib.parse import urljoin, urlparse

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


# ---------------------------------------------------------------- structure probe
def find_announcements_link(html, base_url):
    """Index-page href for the 'Company Announcements' section on the homepage.
    Preference: the heading itself is a link > a 'view all / see all / more' link in the
    same section > the shortest announcement-like path (never an individual item deep link
    unless nothing else exists)."""
    soup = BeautifulSoup(html, "lxml")
    head = soup.find(string=re.compile(r"company\s+announcements", re.I))
    if not head:
        return None, None
    anc = head.find_parent("a", href=True)
    if anc is not None:
        return urljoin(base_url, anc["href"]), anc
    section = head.parent
    for _ in range(4):
        if len(section.find_all("a", href=True)) >= 3:
            break
        section = section.parent
    links = section.find_all("a", href=True)
    for a in links:
        if re.search(r"view\s+all|see\s+all|all\s+announcements|^more\b|show\s+all", a.get_text(" ", strip=True), re.I):
            return urljoin(base_url, a["href"]), a
    cands = [a for a in links if re.search(r"announce|disclos|notice|filing", a["href"], re.I)]
    if cands:
        best = min(cands, key=lambda a: len(urlparse(urljoin(base_url, a["href"])).path.strip("/").split("/")))
        return urljoin(base_url, best["href"]), best
    return None, None


def announcement_block(html, limit=3):
    """Raw HTML of the first `limit` announcement-like items after the 'Company Announcements' heading."""
    soup = BeautifulSoup(html, "lxml")
    head = soup.find(string=re.compile(r"company\s+announcements", re.I))
    if not head:
        return None, []
    container = head.parent
    for _ in range(4):  # climb until the container holds several links
        if len(container.find_all("a", href=True)) >= 3:
            break
        container = container.parent
    items = []
    for a in container.find_all("a", href=True):
        node = a
        while node.parent is not container and node.parent is not None and len(node.parent.find_all("a", href=True)) == 1:
            node = node.parent  # smallest wrapper holding exactly this item's link
        if node not in items:
            items.append(node)
        if len(items) >= limit:
            break
    return container, items


def deep_link_items(html, limit=3):
    """Smallest wrapper around links that point to individual announcements (/announcements/<something>)."""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/announcements?/[^/?#]+", re.I)):
        node = a
        for _ in range(4):
            par = node.parent
            if par is None or len(par.find_all("a", href=re.compile(r"/announcements?/[^/?#]+", re.I))) != 1:
                break
            node = par
        if id(node) not in seen:
            seen.add(id(node)); out.append(node)
        if len(out) >= limit:
            break
    return out


def probe(url=DEFAULT_URL, session=None, sleep=time.sleep, rng=random.uniform, out=print):
    out(f"{APPROVAL_ID} STRUCTURE PROBE (owner override, read-only) -> {url}")
    out(f"UA: {USER_AGENT} | jitter {JITTER_MIN}-{JITTER_MAX}s | cap {REQUEST_CAP} requests | no DB writes")
    budget = Budget()
    try:
        if not allowed_by_robots(url, budget, session, sleep, rng):
            out("robots.txt disallows this URL: stopping.")
            return 2
        home = polite_get(url, budget, session, sleep, rng)
        target_html, target_url = home.text, home.url
        if urlparse(url).path.strip("/"):  # a specific page was given: analyse it directly
            out(f"page HTTP {home.status_code}, {len(home.content)} bytes ({home.url})")
        else:
            link, a = find_announcements_link(home.text, home.url)
            out(f"homepage HTTP {home.status_code}; announcements link found: {link}")
            if a is not None:
                out("link element: " + str(a)[:400])
            if link and urlparse(link).netloc == urlparse(home.url).netloc and link.rstrip("/") != home.url.rstrip("/"):
                page = polite_get(link, budget, session, sleep, rng)
                out(f"announcements page {page.url} HTTP {page.status_code}, {len(page.content)} bytes")
                target_html, target_url = page.text, page.url
            else:
                out("no separate same-site announcements URL found; analysing the homepage block instead.")
        _, items = announcement_block(target_html) if "company announcements" in target_html.lower() else (None, [])
        if not items:
            items = deep_link_items(target_html)
        if not items:
            soup = BeautifulSoup(target_html, "lxml")
            items = soup.select("article, li, tr")[:3]
            out("heading not on this page; showing first generic list items instead.")
        for i, node in enumerate(items[:3], 1):
            out(f"\n--- raw HTML of item {i} (from {target_url}) ---\n" + str(node)[:1800])
    except Blocked as e:
        out(f"BLOCKED: {e}. Not retrying and not attempting any bypass. Requests used: {budget.used}.")
        return 3
    except requests.RequestException as e:
        out(f"network error: {type(e).__name__}: {e}")
        return 4
    out(f"\ndone. requests used: {budget.used}/{REQUEST_CAP}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = args[0] if args else DEFAULT_URL
    sys.exit(probe(url) if "--probe" in sys.argv else run(url))
