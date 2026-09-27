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


def main():
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

    # Attempt 3: bare request, no special headers at all (sanity check --
    # confirms whether ANY request to this host succeeds right now,
    # independent of header tuning).
    r3 = requests.get("https://dps.psx.com.pk/", timeout=20)
    dump("Attempt 3: bare GET of the site root, default requests UA", r3)


if __name__ == "__main__":
    main()
