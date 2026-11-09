"""Safe source-content acquisition (acquire@v1).

Fetches article / disclosure text ONLY where the registry permits it. Defaults refuse:
  * source gate   : access_status=verified_permitted AND enabled AND terms_status=approved AND retention_mode in
                    ('excerpt','full_text_permitted'). 'metadata_only' (every source today) => NO fetch, ever.
  * robots.txt    : checked first per host; disallow, 401/403, or unreachable => no fetch
  * paywall/CAPTCHA/WAF: detected (HTTP 401/402/403/429/503, body markers, teaser-length text) => stop, record, never bypass
  * rate limits   : honest UA, 4.5-9.5 s jitter before every request (robots included), per-run request budget
  * provenance    : text + manifest (url, hash, status, robots result, UA, timestamps, retention mode, text_basis='full_text') written to
                    the document vault; the database is READ-ONLY here (original source_items are never modified)
Headline-only text is never relabelled as full text: only text acquired through this module carries text_basis='full_text'.
"""
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from core.config import USER_AGENT

VERSION = "acquire@v1"
RETENTION_TO_MODE = {"full_text_permitted": "full_text", "excerpt": "excerpt"}
JITTER = (4.5, 9.5)
MIN_ARTICLE_CHARS = 600
MAX_BYTES = 2_000_000
PAYWALL_MARKERS = ("subscribe to continue", "subscribe to read", "subscribers only", "this content is for subscribers", "for subscribers only",
                   "log in to continue reading", "login to continue reading", "premium content", "paywall", "register to read",
                   "sign in to read", "become a member to read")
BLOCK_MARKERS = ("captcha", "recaptcha", "hcaptcha", "cf-chl", "just a moment", "attention required", "access denied", "request blocked",
                 "are you a robot", "unusual traffic", "ddos protection")
BOILERPLATE = re.compile(r"^(advertisement|follow us|share this|read more|also read|related|click here|subscribe|newsletter|copyright)\b", re.I)


class AcquireError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ permission gate (read-only DB)
def eligibility(db):
    out = []
    for s in db.execute("SELECT source_id, source_type, enabled, access_status, terms_status, retention_mode FROM sources "
                        "WHERE access_status='verified_permitted' ORDER BY source_id").rows:
        mode = RETENTION_TO_MODE.get(s["retention_mode"])
        if not s["enabled"]:
            why = "source is disabled"
        elif s["terms_status"] != "approved":
            why = f"terms_status={s['terms_status']!r} (not approved)"
        elif mode is None:
            why = f"retention_mode={s['retention_mode']!r}: registry permits metadata only (headline, link, publisher, timestamp)"
        else:
            why = "ok"
        out.append({"source_id": s["source_id"], "source_type": s["source_type"], "retention_mode": s["retention_mode"],
                    "eligible": why == "ok", "mode": mode if why == "ok" else None, "reason": why})
    return out


# ------------------------------------------------------------------ text extraction
def extract_article_text(html):
    soup = BeautifulSoup(html or "", "lxml")
    for t in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe", "figure"]):
        t.decompose()
    arts = soup.find_all("article")
    root = max(arts, key=lambda a: len(a.get_text(" ", strip=True))) if arts else (soup.find("main") or soup.body or soup)
    paras = []
    for p in root.find_all("p"):
        t = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        if len(t) >= 40 and not BOILERPLATE.match(t):
            paras.append(t)
    return "\n\n".join(paras)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ polite fetcher
class PoliteFetcher:
    def __init__(self, session=None, sleep=time.sleep, rng=random.uniform, jitter=JITTER, max_requests=20,
                 max_bytes=MAX_BYTES, timeout=25, user_agent=USER_AGENT):
        self.session, self.sleep, self.rng, self.jitter = session or requests, sleep, rng, jitter
        self.max_requests, self.max_bytes, self.timeout, self.ua = max_requests, max_bytes, timeout, user_agent
        self.requests_made, self._robots = 0, {}
        self.headers = {"User-Agent": user_agent}          # nothing else: no Referer, no browser-mimicking headers

    def _get(self, url):
        if self.requests_made >= self.max_requests:
            return None
        self.requests_made += 1
        self.sleep(self.rng(*self.jitter))
        return self.session.get(url, headers=self.headers, timeout=self.timeout, allow_redirects=True)

    def robots(self, url):
        p = urlparse(url)
        host = f"{p.scheme}://{p.netloc}"
        if host not in self._robots:
            try:
                r = self._get(f"{host}/robots.txt")
            except requests.RequestException:
                r = False
            if r is None:
                return "budget_exhausted"
            if r is False:
                self._robots[host] = ("unavailable", None)
            elif r.status_code == 404:
                self._robots[host] = ("none", None)             # no robots.txt: nothing disallowed
            elif r.status_code in (401, 403, 407, 429, 451, 503) or r.status_code >= 400:
                self._robots[host] = ("unavailable", None)      # conservative: a refused robots.txt is not permission
            else:
                rp = robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
                self._robots[host] = ("rules", rp)
        kind, rp = self._robots[host]
        if kind == "unavailable":
            return "robots_unavailable"
        if kind == "rules" and not (rp.can_fetch(self.ua, url) and rp.can_fetch("*", url)):
            return "robots_disallowed"
        return "ok"

    def fetch(self, url):
        base = {"url": url, "status": None, "http_status": None, "content_type": None, "text": None}
        verdict = self.robots(url)
        if verdict != "ok":
            return {**base, "status": verdict}
        try:
            r = self._get(url)
        except requests.RequestException as e:
            return {**base, "status": "error", "detail": type(e).__name__}
        if r is None:
            return {**base, "status": "budget_exhausted"}
        base.update(http_status=r.status_code, content_type=(r.headers.get("content-type") or "").split(";")[0].strip().lower())
        if r.status_code in (401, 402):
            return {**base, "status": "paywalled"}
        if r.status_code in (403, 407, 429, 451, 503):
            return {**base, "status": "blocked"}
        if r.status_code >= 400:
            return {**base, "status": "error"}
        if base["content_type"] not in ("text/html", "application/xhtml+xml"):
            return {**base, "status": "not_html"}
        body = r.text or ""
        if len(body.encode("utf-8", "ignore")) > self.max_bytes:
            return {**base, "status": "too_large"}
        low = body[:60000].lower()
        if any(m in low for m in BLOCK_MARKERS):
            return {**base, "status": "captcha"}
        text = extract_article_text(body)
        if any(m in low for m in PAYWALL_MARKERS) and len(text) < MIN_ARTICLE_CHARS * 3:
            return {**base, "status": "paywalled"}
        if len(text) < MIN_ARTICLE_CHARS:
            return {**base, "status": "too_short"}           # a teaser or an empty shell is not an article
        return {**base, "status": "fetched_ok", "text": text}


# ------------------------------------------------------------------ vault storage (text + manifest); DB untouched
def vault_root_from_env(env=None):
    v = (env or os.environ).get("DOCUMENT_VAULT_PATH", "").strip()
    if not v:
        raise AcquireError("DOCUMENT_VAULT_PATH is not set")
    root = Path(v).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def manifest_path(root, item_id):
    return Path(root) / "articles" / "manifests" / f"{int(item_id):09d}.json"


def store_result(root, item, result, mode, robots_note="ok", now=None):
    """item: {'source_item_id','source_id'}. Writes the manifest always (so refusals are remembered) and the text only on success."""
    now = now or _now()
    man = {"acquire_version": VERSION, "source_item_id": item["source_item_id"], "source_id": item["source_id"], "url": result["url"],
           "fetched_at_utc": now, "status": result["status"], "http_status": result.get("http_status"), "robots": robots_note,
           "user_agent": USER_AGENT, "retention_mode_applied": mode, "text_basis": "full_text" if result["status"] == "fetched_ok" else None,
           "content_sha256": None, "chars": 0, "text_path": None}
    if result["status"] == "fetched_ok":
        text = result["text"]
        sha = sha256_text(text)
        rel = f"articles/{now[:4]}/{now[5:7]}/{item['source_item_id']}_{sha[:12]}.txt"
        _atomic_write(Path(root) / rel, text.encode("utf-8"))
        man.update(content_sha256=sha, chars=len(text), text_path=rel)
    _atomic_write(manifest_path(root, item["source_item_id"]), json.dumps(man, indent=1, sort_keys=True).encode("utf-8"))
    return man


def load_manifest(root, item_id):
    p = manifest_path(root, item_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_acquired(root, item_id):
    """Full text for an item ONLY if its manifest says fetched_ok and the stored text still matches the recorded SHA-256."""
    man = load_manifest(root, item_id)
    if not man or man["status"] != "fetched_ok" or not man.get("text_path"):
        return None
    f = Path(root) / man["text_path"]
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8")
    return {"text": text, "sha256": man["content_sha256"], "manifest": man} if sha256_text(text) == man["content_sha256"] else None


# ------------------------------------------------------------------ batch (dry-run by default)
def acquire_items(db, root, fetcher, source_id=None, limit=5, dry_run=True, now=None):
    elig = {e["source_id"]: e for e in eligibility(db)}
    if source_id and not elig.get(source_id, {}).get("eligible"):
        return {"refused": True, "reason": (elig.get(source_id) or {"reason": "source is not verified_permitted"})["reason"], "fetched": 0}
    allowed = [s for s, e in elig.items() if e["eligible"] and (source_id is None or s == source_id)]
    report = {"refused": False, "eligible_sources": allowed, "ineligible": {s: e["reason"] for s, e in elig.items() if not e["eligible"]},
              "planned": [], "outcomes": [], "dry_run": dry_run}
    if not allowed:
        report["refused"], report["reason"] = True, "no source is eligible for content acquisition under the current registry"
        return report
    ph = ",".join("?" * len(allowed))
    rows = db.execute(f"SELECT source_item_id, source_id, canonical_url FROM source_items WHERE source_id IN ({ph}) AND canonical_url IS NOT NULL "
                      f"ORDER BY collected_at_utc DESC, source_item_id DESC LIMIT ?", (*allowed, limit * 5)).rows
    todo = [r for r in rows if load_manifest(root, r["source_item_id"]) is None][:limit]
    report["planned"] = [{"source_item_id": r["source_item_id"], "source_id": r["source_id"], "url": r["canonical_url"]} for r in todo]
    if dry_run:
        return report
    blocked_sources = set()
    for r in todo:
        if r["source_id"] in blocked_sources:
            continue
        res = fetcher.fetch(r["canonical_url"])
        store_result(root, r, res, elig[r["source_id"]]["mode"], robots_note="ok" if res["status"] not in ("robots_disallowed", "robots_unavailable") else res["status"], now=now)
        report["outcomes"].append((r["source_item_id"], res["status"]))
        if res["status"] in ("blocked", "captcha", "paywalled", "robots_disallowed", "robots_unavailable"):
            blocked_sources.add(r["source_id"])          # a refusal stops that source for this run: never hammer, never bypass
        if res["status"] == "budget_exhausted":
            break
    return report
