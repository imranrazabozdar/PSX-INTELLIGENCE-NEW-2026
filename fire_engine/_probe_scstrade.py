#!/usr/bin/env python3
"""One-off Phase 1 discovery probe, round 2: follow scstrade.com's real
nav links (Market Statistics, Technicals) discovered in round 1, and log
every XHR/fetch/document network request+response made while on those
pages -- this is how a real chart-data endpoint (JSON API, or a
TradingView-style iframe, which would matter a lot given this project's
explicit "don't use TradingView as data source" rule) actually gets
found, instead of guessing more URLs."""
from playwright.sync_api import sync_playwright

HOME = "https://www.scstrade.com/"
NAV_LINK_TEXTS = ["Market Statistics", "Technicals", "Online Trading"]


def log_requests(page, label):
    seen = []

    def on_response(resp):
        req = resp.request
        ct = resp.headers.get("content-type", "")
        if req.resource_type in ("xhr", "fetch") or "json" in ct or "chart" in req.url.lower() or "candle" in req.url.lower():
            seen.append((req.method, resp.status, req.resource_type, ct, req.url))

    page.on("response", on_response)
    return seen


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(HOME, timeout=30000, wait_until="networkidle")

    print("=== Top-level nav hrefs on homepage ===")
    links = page.eval_on_selector_all(
        "a", "els => els.map(e => [e.textContent.trim(), e.href]).filter(x => x[0])"
    )
    seen_texts = set()
    for text, href in links:
        if text and text not in seen_texts and len(text) < 60:
            seen_texts.add(text)
            print(f"  {text!r} -> {href}")
    print("=" * 80)

    # Try to find and visit the real hrefs for our targets of interest
    href_map = {t: h for t, h in links}
    for target in NAV_LINK_TEXTS:
        matches = [(t, h) for t, h in links if target.lower() in (t or "").lower()]
        if not matches:
            print(f"NO MATCH for nav text containing {target!r}")
            continue
        for text, href in matches[:2]:
            print(f"--- Visiting {text!r} -> {href} ---")
            sub_page = browser.new_page()
            captured = log_requests(sub_page, text)
            try:
                resp = sub_page.goto(href, timeout=30000, wait_until="networkidle")
                print(f"  STATUS: {resp.status if resp else None}")
                print(f"  FINAL URL: {sub_page.url}")
                print(f"  TITLE: {sub_page.title()}")
                # iframes?
                iframes = sub_page.eval_on_selector_all("iframe", "els => els.map(e => e.src)")
                if iframes:
                    print(f"  IFRAMES: {iframes}")
                if captured:
                    print("  Interesting network calls seen on this page:")
                    for method, status, rtype, ct, url in captured[:25]:
                        print(f"    {method} {status} [{rtype}] {ct} {url}")
                else:
                    print("  (no xhr/fetch/json/chart-like network calls observed)")
            except Exception as e:
                print(f"  ERROR: {e!r}")
            finally:
                sub_page.close()
            print("-" * 80)

    browser.close()
