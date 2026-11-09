import pytest
import investify_pilot as ip

HTML = """<html><body><nav><a>Home navigation link here</a></nav>
<h2>OGDC announces board meeting for quarterly results</h2>
<article><a href="/n/1">Engro Corporation announces cash dividend of Rs 5</a></article></body></html>"""


class Resp:
    def __init__(self, status=200, text=HTML, url="https://investify.pk/", headers=None):
        self.status_code, self.text, self.url = status, text, url
        self.headers, self.content = headers or {"content-type": "text/html"}, text.encode()


class Sess:
    def __init__(self, pages): self.pages, self.calls = pages, []
    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.pages.get(url) or self.pages["*"]


NOJ = dict(sleep=lambda s: None)


def test_only_honest_ua_header():
    assert ip.HEADERS == {"User-Agent": ip.USER_AGENT}
    s = Sess({"https://investify.pk/robots.txt": Resp(404, ""), "*": Resp()})
    ip.run(session=s, out=lambda *_: None, **NOJ)
    assert all(kw["headers"] == {"User-Agent": ip.USER_AGENT} for _, kw in s.calls)


def test_jitter_range_applied_before_every_request():
    waits = []
    s = Sess({"https://investify.pk/robots.txt": Resp(404, ""), "*": Resp()})
    ip.run(session=s, sleep=waits.append, out=lambda *_: None)
    assert len(waits) == 2 and all(4.5 <= w <= 9.5 for w in waits)


def test_extracts_text_and_exit_ok():
    lines = []
    s = Sess({"https://investify.pk/robots.txt": Resp(404, ""), "*": Resp()})
    assert ip.run(session=s, out=lines.append, **NOJ) == 0
    joined = "\n".join(lines)
    assert "OGDC announces board meeting" in joined and "Engro Corporation announces cash dividend" in joined
    assert "Home navigation" not in joined


@pytest.mark.parametrize("resp", [Resp(403, "forbidden"), Resp(429, ""), Resp(200, "<html>Please complete the reCAPTCHA</html>"),
                                  Resp(200, "<title>Just a moment...</title>")])
def test_block_exits_gracefully_without_retry(resp):
    lines = []
    s = Sess({"https://investify.pk/robots.txt": Resp(404, ""), "*": resp})
    assert ip.run(session=s, out=lines.append, **NOJ) == 3
    assert len(s.calls) == 2 and any("BLOCKED" in l for l in lines)


def test_robots_disallow_stops_before_fetch():
    s = Sess({"https://investify.pk/robots.txt": Resp(200, "User-agent: *\nDisallow: /"), "*": Resp()})
    assert ip.run(session=s, out=lambda *_: None, **NOJ) == 2
    assert len(s.calls) == 1


def test_robots_block_is_block():
    s = Sess({"https://investify.pk/robots.txt": Resp(403, ""), "*": Resp()})
    assert ip.run(session=s, out=lambda *_: None, **NOJ) == 3


def test_cap_and_bad_url():
    b = ip.Budget(1); b.take()
    with pytest.raises(RuntimeError): b.take()
    assert ip.run("ftp://x", out=lambda *_: None) == 2


def test_no_db_imports():
    src = open(ip.__file__).read()
    assert "turso" not in src.lower() and "sqlite" not in src.lower()


HOME = """<html><body><section><h2>Company Announcements</h2>
<ul><li class="ann"><a href="/announcements/123"><span class="sym">OGDC</span><span class="t">Briefing</span><time datetime="2026-11-09T10:00">10:00</time></a></li>
<li class="ann"><a href="/announcements/124"><span class="sym">SSGC</span><span class="t">Annual Report</span></a></li>
<li class="ann"><a href="/announcements/125"><span class="sym">EFU</span><span class="t">Allotment</span></a></li></ul>
<a href="/announcements">View all</a></section></body></html>"""


def test_probe_follows_link_and_prints_raw_html():
    lines = []
    s = Sess({"https://investify.pk/robots.txt": Resp(404, ""), "https://investify.pk/": Resp(200, HOME),
              "https://investify.pk/announcements": Resp(200, HOME, url="https://investify.pk/announcements")})
    assert ip.probe(session=s, out=lines.append, **NOJ) == 0
    text = "\n".join(lines)
    assert "https://investify.pk/announcements" in text and '<span class="sym">OGDC</span>' in text
    assert len(s.calls) <= ip.REQUEST_CAP


def test_probe_block_exit():
    s = Sess({"https://investify.pk/robots.txt": Resp(404, ""), "*": Resp(403, "no")})
    assert ip.probe(session=s, out=lambda *_: None, **NOJ) == 3


def test_probe_direct_page_uses_deep_link_items():
    lines = []
    s = Sess({"https://www.investify.pk/robots.txt": Resp(404, ""),
              "https://www.investify.pk/announcements": Resp(200, HOME.replace("Company Announcements", "Filings"), url="https://www.investify.pk/announcements")})
    assert ip.probe("https://www.investify.pk/announcements", session=s, out=lines.append, **NOJ) == 0
    assert len(s.calls) == 2 and '<span class="sym">OGDC</span>' in "\n".join(lines)
