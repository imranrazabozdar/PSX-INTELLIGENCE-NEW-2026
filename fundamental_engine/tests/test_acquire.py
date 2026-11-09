import json

import pytest
import requests

from sources import acquire
from sources.acquire import PoliteFetcher, acquire_items, eligibility, extract_article_text, load_acquired, load_manifest, store_result
from tests.conftest import add_item, add_source

PARA = "The finance ministry said on Monday that the revised budget estimates reflect a lower primary deficit than projected earlier this year. "
ARTICLE = "<html><body><nav>menu menu menu</nav><article>" + "".join(f"<p>{PARA}Paragraph {i}.</p>" for i in range(1, 8)) + \
          "<p>Advertisement</p><p>Follow us on social media for the latest updates</p></article><footer>copyright</footer></body></html>"


class Resp:
    def __init__(self, status=200, text=ARTICLE, ctype="text/html; charset=utf-8", headers=None):
        self.status_code, self.text = status, text
        self.headers = {"content-type": ctype, **(headers or {})}


class Net:
    """URL-dispatching fake session. pages: {url_suffix: Resp | Exception}"""
    def __init__(self, pages=None, robots="User-agent: *\nAllow: /"):
        self.pages, self.robots, self.calls = pages or {}, robots, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if url.endswith("/robots.txt"):
            r = self.robots
            if isinstance(r, Exception):
                raise r
            return r if isinstance(r, Resp) else Resp(200, r, "text/plain")
        r = next((v for k, v in self.pages.items() if url.endswith(k)), Resp())
        if isinstance(r, Exception):
            raise r
        return r


def fetcher(net, **kw):
    sl = []
    f = PoliteFetcher(net, sleep=sl.append, rng=lambda a, b: 5.0, **kw)
    f.slept = sl
    return f


def setup_source(db, retention="metadata_only", terms="approved", enabled=1, sid="news"):
    add_source(db, sid, stype="news_media")
    db.execute("UPDATE sources SET retention_mode=?, terms_status=?, enabled=? WHERE source_id=?", (retention, terms, enabled, sid))
    return sid


def add_url(db, sid, ext, path="/a1"):
    # canonical_url is immutable by trigger: set it at insert time
    return db.execute("INSERT INTO source_items(source_id,external_id,canonical_url,title,collected_at_utc,content_sha256) VALUES(?,?,?,?,'2026-11-09T00:00:00Z',?)",
                      (sid, ext, f"https://news.example{path}", "t", "a" * 64)).lastrowid


# ------------------------------------------------------------------ permission gate
@pytest.mark.parametrize("retention,terms,enabled,ok,why", [
    ("metadata_only", "approved", 1, False, "metadata only"),
    ("excerpt", "approved", 1, True, "ok"), ("full_text_permitted", "approved", 1, True, "ok"),
    ("full_text_permitted", "not_reviewed", 1, False, "not approved"), ("full_text_permitted", "approved", 0, False, "disabled")])
def test_eligibility_matrix(db, retention, terms, enabled, ok, why):
    sid = setup_source(db, retention, terms, enabled)
    e = {x["source_id"]: x for x in eligibility(db)}[sid]
    assert e["eligible"] is ok and why in e["reason"]


def test_only_verified_permitted_sources_are_considered(db):
    add_source(db, "r", "restricted", "news_media")
    assert eligibility(db) == []


def test_metadata_only_sources_are_never_fetched_even_when_asked(db, tmp_path):
    sid = setup_source(db)                                 # metadata_only: the state of every source today
    add_url(db, sid, "e1")
    net = Net()
    res = acquire_items(db, tmp_path, fetcher(net), sid, dry_run=False)
    assert res["refused"] and "metadata only" in res["reason"] and net.calls == []
    res2 = acquire_items(db, tmp_path, fetcher(net), None, dry_run=False)               # no source named: still nothing eligible
    assert res2["refused"] and net.calls == [] and sid in res2["ineligible"]


# ------------------------------------------------------------------ fetcher safeguards
def test_honest_headers_only_and_jitter_before_every_request():
    net = Net()
    f = fetcher(net)
    out = f.fetch("https://news.example/a1")
    assert out["status"] == "fetched_ok" and len(f.slept) == 2                          # robots.txt + page, each preceded by jitter
    for _, kw in net.calls:
        assert kw["headers"] == {"User-Agent": acquire.USER_AGENT}                      # no Referer, no Sec-Fetch-*, no spoofing
    assert all(4.5 <= s <= 9.5 for s in [5.0]) and acquire.JITTER == (4.5, 9.5)


def test_extracts_article_text_and_drops_boilerplate():
    t = extract_article_text(ARTICLE)
    assert "revised budget estimates" in t and "Advertisement" not in t and "Follow us" not in t and "menu" not in t and "copyright" not in t
    assert t.count("\n\n") == 6


@pytest.mark.parametrize("robots,status", [
    ("User-agent: *\nDisallow: /", "robots_disallowed"),
    (Resp(403, "forbidden"), "robots_unavailable"), (Resp(503, ""), "robots_unavailable"),
    (requests.ConnectionError("down"), "robots_unavailable")])
def test_robots_refusals_prevent_any_page_request(robots, status):
    net = Net(robots=robots)
    out = fetcher(net).fetch("https://news.example/a1")
    assert out["status"] == status and [u for u, _ in net.calls] == ["https://news.example/robots.txt"]


def test_missing_robots_txt_means_allowed():
    assert fetcher(Net(robots=Resp(404, "nope"))).fetch("https://news.example/a1")["status"] == "fetched_ok"


@pytest.mark.parametrize("page,status", [
    (Resp(402, ""), "paywalled"), (Resp(401, ""), "paywalled"),
    (Resp(403, "no"), "blocked"), (Resp(429, ""), "blocked"), (Resp(503, ""), "blocked"),
    (Resp(200, "<html><body><h1>Just a moment...</h1><div>reCAPTCHA</div></body></html>"), "captcha"),
    (Resp(200, "<html><body><article><p>" + "Intro paragraph about the economy and markets today. " * 3 + "</p></article><div>Subscribe to continue reading</div></body></html>"), "paywalled"),
    (Resp(200, "<html><body><article><p>Short teaser sentence that is clearly not a full article body at all.</p></article></body></html>"), "too_short"),
    (Resp(200, "%PDF-1.4", "application/pdf"), "not_html"),
    (Resp(404, ""), "error"), (requests.Timeout("slow"), "error")])
def test_blocks_paywalls_captchas_teasers_and_non_html_are_recorded_not_bypassed(page, status):
    net = Net({"/a1": page})
    out = fetcher(net).fetch("https://news.example/a1")
    assert out["status"] == status and out["text"] is None
    assert len(net.calls) == 2                                                          # robots + exactly one page request: no retry, no second try


def test_oversized_page_rejected():
    out = fetcher(Net({"/a1": Resp(200, "x" * 5000)}), max_bytes=1000).fetch("https://news.example/a1")
    assert out["status"] == "too_large"


def test_request_budget_enforced():
    net = Net()
    f = fetcher(net, max_requests=2)
    assert f.fetch("https://news.example/a1")["status"] == "fetched_ok"                  # robots + page = 2
    assert f.fetch("https://news.example/a2")["status"] == "budget_exhausted" and len(net.calls) == 2


# ------------------------------------------------------------------ vault storage and verification
def test_store_load_roundtrip_and_tamper_detection(tmp_path):
    res = fetcher(Net()).fetch("https://news.example/a1")
    man = store_result(tmp_path, {"source_item_id": 7, "source_id": "news"}, res, "full_text", now="2026-11-09T12:00:00Z")
    assert man["status"] == "fetched_ok" and man["text_basis"] == "full_text" and man["robots"] == "ok" and man["user_agent"] == acquire.USER_AGENT
    assert man["text_path"].startswith("articles/2026/11/7_") and len(man["content_sha256"]) == 64 and man["chars"] == len(res["text"])
    got = load_acquired(tmp_path, 7)
    assert got["text"] == res["text"] and got["sha256"] == man["content_sha256"]
    (tmp_path / man["text_path"]).write_text("tampered", encoding="utf-8")
    assert load_acquired(tmp_path, 7) is None                                           # hash no longer matches
    assert load_acquired(tmp_path, 999) is None


def test_refusals_are_remembered_without_text(tmp_path):
    res = fetcher(Net(robots="User-agent: *\nDisallow: /")).fetch("https://news.example/a1")
    man = store_result(tmp_path, {"source_item_id": 8, "source_id": "news"}, res, "full_text", robots_note="robots_disallowed")
    assert man["status"] == "robots_disallowed" and man["text_path"] is None and man["text_basis"] is None and load_acquired(tmp_path, 8) is None
    assert load_manifest(tmp_path, 8)["robots"] == "robots_disallowed"


# ------------------------------------------------------------------ batch
def test_eligible_source_dry_run_then_live_stores_text_and_leaves_db_untouched(db, tmp_path):
    sid = setup_source(db, "full_text_permitted")
    a, b = add_url(db, sid, "e1", "/a1"), add_url(db, sid, "e2", "/a2")
    before = db.execute("select source_item_id,title,content_sha256,permitted_excerpt,content_location from source_items order by 1").rows
    net = Net()
    dry = acquire_items(db, tmp_path, fetcher(net), sid, limit=5, dry_run=True)
    assert [p["source_item_id"] for p in dry["planned"]] == [b, a] and net.calls == [] and not (tmp_path / "articles").exists()
    live = acquire_items(db, tmp_path, fetcher(net), sid, limit=5, dry_run=False, now="2026-11-09T12:00:00Z")
    assert [s for _, s in live["outcomes"]] == ["fetched_ok", "fetched_ok"]
    assert load_acquired(tmp_path, a)["manifest"]["retention_mode_applied"] == "full_text"
    assert db.execute("select source_item_id,title,content_sha256,permitted_excerpt,content_location from source_items order by 1").rows == before
    again = acquire_items(db, tmp_path, fetcher(Net()), sid, dry_run=True)
    assert again["planned"] == []                                                       # already acquired: not fetched twice


def test_a_block_stops_that_source_for_the_run(db, tmp_path):
    sid = setup_source(db, "full_text_permitted")
    for i in range(3):
        add_url(db, sid, f"e{i}", f"/p{i}")
    net = Net({"/p2": Resp(403, "no")})                                                 # newest item is blocked first
    res = acquire_items(db, tmp_path, fetcher(net), sid, limit=3, dry_run=False)
    assert [s for _, s in res["outcomes"]] == ["blocked"]
    assert sum(1 for u, _ in net.calls if not u.endswith("robots.txt")) == 1            # the other two were never requested
