#!/usr/bin/env python3
"""diagnose_psx_portal.py — one-off diagnostic for the 2026-09-27 incident
where dps.psx.com.pk started returning 403 Forbidden for every request from
GitHub Actions runners, with no code change on our side (this exact scraper
worked fine through 2026-09-25). dps_scraper.py's normal error path only
logs the exception message, not the actual response -- this script captures
full status/headers/body so we can tell whether this is:
  (a) a WAF/Cloudflare challenge (body contains "cloudflare"/"attention
      required"/a cf-ray header),
  (b) a plain deny-list block (no distinctive challenge markup), or
  (c) something that a session/cookie warm-up (GET the page first, then
      POST with those cookies) gets past.
Prints everything; does not touch Turso or any other part of the app.
"""
import requests

HISTORICAL_PAGE = "https://dps.psx.com.pk/historical"
HISTORICAL_POST = "https://dps.psx.com.pk/historical"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://dps.psx.com.pk/historical",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
}


def dump(label, resp):
    print(f"\n===== {label} =====")
    print(f"status: {resp.status_code}")
    print(f"final url: {resp.url}")
    for k in ("server", "cf-ray", "cf-mitigated", "cf-cache-status", "content-type",
              "retry-after", "x-sucuri-id", "set-cookie"):
        if k in resp.headers:
            print(f"header[{k}]: {resp.headers[k]}")
    body = resp.text
    print(f"body length: {len(body)}")
    lowered = body.lower()
    for marker in ("cloudflare", "attention required", "sucuri", "captcha",
                   "access denied", "forbidden", "rate limit"):
        if marker in lowered:
            print(f"  body contains marker: {marker!r}")
    print("body[:600]:")
    print(body[:600])


def find_csrf_markers(html):
    """Looks for the common places a site embeds a CSRF/session token that a
    plain requests.Session() (no JS execution) would never pick up on its
    own: a <meta name="csrf-token"> tag, a hidden <input> field, or an
    inline JS variable assignment. Returns a list of (kind, snippet)."""
    import re
    found = []
    for m in re.finditer(r'<meta[^>]+name=["\'](csrf-token|_token|xsrf-token)["\'][^>]*>', html, re.I):
        found.append(("meta tag", m.group(0)))
    for m in re.finditer(r'<input[^>]+name=["\'](csrf_token|_token|authenticity_token)["\'][^>]*>', html, re.I):
        found.append(("hidden input", m.group(0)))
    for m in re.finditer(r'(csrfToken|CSRF_TOKEN|_token)\s*[=:]\s*["\'][^"\']{8,80}["\']', html):
        found.append(("inline JS var", m.group(0)))
    return found


def probe_scs_daily():
    """Can SCS (chart.scstrade.com) -- the UDF feed fire_engine already uses
    for 1-min and 4h bars -- serve DAILY bars over a multi-year range? If so
    it can replace the now-403'd PSX /historical endpoint for daily_ohlc."""
    import time as _time
    from datetime import datetime, timezone
    base = "https://chart.scstrade.com"
    hdr = {
        "User-Agent": BROWSER_HEADERS["User-Agent"],
        "Referer": "https://www.scstrade.com/TechnicalAnalysis/TA_RealTimeCharting.aspx",
        "Accept": "application/json",
    }
    print("\n===== SCS probe: /config =====")
    cfg = requests.get(f"{base}/config", headers=hdr, timeout=20)
    print(f"status: {cfg.status_code}")
    try:
        print(f"supported_resolutions: {cfg.json().get('supported_resolutions')}")
    except Exception as e:
        print(f"could not parse /config JSON: {e}; body[:300]={cfg.text[:300]}")

    now = int(_time.time())
    five_years_ago = now - 5 * 366 * 86400
    for res in ("D", "1D"):
        print(f"\n===== SCS probe: /history symbol=OGDC resolution={res} (5y) =====")
        r = requests.get(f"{base}/history",
                         params={"symbol": "OGDC", "resolution": res, "from": five_years_ago, "to": now},
                         headers=hdr, timeout=30)
        print(f"status: {r.status_code}")
        try:
            data = r.json()
        except Exception as e:
            print(f"not JSON: {e}; body[:300]={r.text[:300]}")
            continue
        print(f"s: {data.get('s')}")
        t = data.get("t") or []
        if not t:
            print(f"no bars; keys={list(data.keys())}")
            continue
        o, h, l, c, v = (data.get(k) or [] for k in ("o", "h", "l", "c", "v"))
        fmt = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print(f"bars: {len(t)}  first: {fmt(t[0])}  last: {fmt(t[-1])}")
        bad = sum(1 for i in range(len(t)) if not (l[i] <= min(o[i], c[i]) <= max(o[i], c[i]) <= h[i]))
        print(f"OHLC-inconsistent bars: {bad}")
        for i in range(max(0, len(t) - 5), len(t)):
            print(f"  {fmt(t[i])}  O={o[i]} H={h[i]} L={l[i]} C={c[i]} V={v[i]}")


def main():
    probe_scs_daily()
    session = requests.Session()

    # Attempt 1: exactly what dps_scraper.py does today -- cold POST, no
    # prior GET, static headers, no cookies.
    r1 = session.post(HISTORICAL_POST, data={"symbol": "OGDC", "date": "2026-09-27"},
                       headers=BROWSER_HEADERS, timeout=20)
    dump("Attempt 1: cold POST (current dps_scraper.py behavior)", r1)

    # Attempt 2: GET the historical page first (like a real browser would
    # before firing its XHR), carry whatever cookies that sets, THEN POST.
    session2 = requests.Session()
    try:
        rg = session2.get(HISTORICAL_PAGE, headers={"User-Agent": BROWSER_HEADERS["User-Agent"]}, timeout=20)
        print(f"\n===== Attempt 2 warm-up GET status: {rg.status_code}, cookies: {dict(session2.cookies)} =====")
        print(f"warm-up GET body length: {len(rg.text)}")
        markers = find_csrf_markers(rg.text)
        if markers:
            print(f"Found {len(markers)} possible CSRF/token marker(s) in the page HTML:")
            for kind, snippet in markers:
                print(f"  [{kind}] {snippet[:200]}")
        else:
            print("No csrf-token/xsrf-token/_token meta tag, hidden input, or inline JS var found "
                  "in the raw HTML -- if this page sets a token, it's likely injected client-side "
                  "by JS after page load, which a plain GET here would never see.")
        # Response headers on the GET itself -- a Set-Cookie here wouldn't
        # show in session2.cookies if it was rejected (e.g. bad domain/path).
        if "set-cookie" in rg.headers:
            print(f"warm-up GET response header[set-cookie]: {rg.headers['set-cookie']}")
    except Exception as e:
        print(f"\nAttempt 2 warm-up GET failed: {type(e).__name__}: {e}")
    r2 = session2.post(HISTORICAL_POST, data={"symbol": "OGDC", "date": "2026-09-27"},
                        headers=BROWSER_HEADERS, timeout=20)
    dump("Attempt 2: warm-up POST with session cookies", r2)

    # Attempt 4: a REAL Chromium session (Playwright), navigate to the
    # actual page, then fire the identical POST from WITHIN the page's own
    # JS context via fetch() -- this carries the browser's genuine TLS/HTTP
    # fingerprint, cookies, and Origin/Referer exactly as a real user's
    # browser would, without us having to guess what a bot-check wants.
    print("\n===== Attempt 4: real Chromium session, fetch() from within the page =====")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=BROWSER_HEADERS["User-Agent"])
            nav = page.goto(HISTORICAL_PAGE, wait_until="networkidle", timeout=30000)
            print(f"page navigation status: {nav.status if nav else 'None'}")
            result = page.evaluate(
                """async () => {
                    const resp = await fetch('/historical', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                            'X-Requested-With': 'XMLHttpRequest',
                            'Accept': 'text/html, */*; q=0.01',
                        },
                        body: 'symbol=OGDC&date=2026-09-27',
                    });
                    const text = await resp.text();
                    return {status: resp.status, length: text.length, snippet: text.slice(0, 600)};
                }"""
            )
            print(f"fetch() status: {result['status']}")
            print(f"fetch() body length: {result['length']}")
            print("fetch() body[:600]:")
            print(result["snippet"])
            browser.close()
    except ImportError:
        print("playwright not installed in this environment -- skipping attempt 4")
    except Exception as e:
        print(f"Attempt 4 failed: {type(e).__name__}: {e}")

    # Attempt 5: the OTHER real endpoints this codebase depends on, all
    # under the same dps.psx.com.pk host -- to establish whether today's
    # block is narrow (just POST /historical) or hits the whole domain.
    # Uses the exact same headers backend/app.py's market_watch()/eod() use.
    APP_HEAD = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://dps.psx.com.pk/",
        "Connection": "keep-alive",
    }
    for label, url in [
        ("GET /market-watch (live quotes -- app.py's market_watch())", "https://dps.psx.com.pk/market-watch"),
        ("GET /timeseries/eod/OGDC (app.py's eod())", "https://dps.psx.com.pk/timeseries/eod/OGDC"),
        ("GET /company/OGDC (fundamentals page)", "https://dps.psx.com.pk/company/OGDC"),
    ]:
        try:
            r = requests.get(url, headers=APP_HEAD, timeout=20)
            dump(f"Attempt 5: {label}", r)
        except Exception as e:
            print(f"\n===== Attempt 5: {label} =====\nrequest failed: {type(e).__name__}: {e}")

    # Attempt 3: bare request, no special headers at all (sanity check --
    # confirms whether ANY request to this host succeeds right now,
    # independent of header tuning).
    r3 = requests.get("https://dps.psx.com.pk/", timeout=20)
    dump("Attempt 3: bare GET of the site root, default requests UA", r3)

    # Attempt 6: /market-watch and /timeseries/eod/{symbol} came back 404 in
    # a prior round (not 403 -- a real "doesn't exist", not a block). Search
    # the homepage we already fetched for its actual nav links to find
    # where PSX moved these, if they moved rather than disappeared.
    print("\n===== Attempt 6: nav links on the homepage mentioning market/watch/historical/eod/timeseries =====")
    import re
    hrefs = set(re.findall(r'href=["\']([^"\']+)["\']', r3.text))
    keywords = ("market", "watch", "historical", "eod", "timeseries", "quote", "price")
    matches = sorted(h for h in hrefs if any(k in h.lower() for k in keywords))
    if matches:
        for h in matches:
            print(f"  {h}")
    else:
        print("  No matching nav links found in the homepage HTML.")


if __name__ == "__main__":
    main()
