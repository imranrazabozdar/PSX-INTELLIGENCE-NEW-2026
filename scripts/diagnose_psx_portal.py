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
    except Exception as e:
        print(f"\nAttempt 2 warm-up GET failed: {type(e).__name__}: {e}")
    r2 = session2.post(HISTORICAL_POST, data={"symbol": "OGDC", "date": "2026-09-27"},
                        headers=BROWSER_HEADERS, timeout=20)
    dump("Attempt 2: warm-up GET then POST with session cookies", r2)

    # Attempt 3: bare request, no special headers at all (sanity check --
    # confirms whether ANY request to this host succeeds right now,
    # independent of header tuning).
    r3 = requests.get("https://dps.psx.com.pk/", timeout=20)
    dump("Attempt 3: bare GET of the site root, default requests UA", r3)


if __name__ == "__main__":
    main()
