#!/usr/bin/env python3
"""One-off Phase 1 discovery probe, round 3: visit the real charting pages
found in round 2 (TA_RealTimeCharting.aspx / TA_BasicCharting.aspx /
MS_HistoricalPrices.aspx), capture every network response (not just
xhr/fetch -- AnyChart's own data loader may use plain GETs), and print
truncated bodies for anything JSON/candle-shaped so the real 1-minute
OHLCV endpoint (query params, auth requirement, response shape) can be
confirmed before any production scraper is written."""
import re
from playwright.sync_api import sync_playwright

PAGES = [
    "https://www.scstrade.com/TechnicalAnalysis/TA_RealTimeCharting.aspx",
    "https://www.scstrade.com/TechnicalAnalysis/TA_BasicCharting.aspx",
    "https://www.scstrade.com/MarketStatistics/MS_HistoricalPrices.aspx",
    "https://www.scstrade.com/stockscreening/SS_CompanySnapShot.aspx?symbol=AICL",
]


def probe(page, url):
    captured = []

    def on_response(resp):
        req = resp.request
        if req.resource_type in ("stylesheet", "font", "image"):
            return
        try:
            ct = resp.headers.get("content-type", "")
        except Exception:
            ct = ""
        body_snippet = None
        looks_interesting = (
            "json" in ct or req.resource_type in ("xhr", "fetch", "document")
            or re.search(r"chart|candle|ohlc|history|intraday|data", req.url, re.I)
        )
        if looks_interesting:
            try:
                if "json" in ct or (req.resource_type in ("xhr", "fetch") and resp.status == 200):
                    text = resp.text()
                    body_snippet = text[:500]
            except Exception as e:
                body_snippet = f"<could not read body: {e!r}>"
        captured.append((req.method, resp.status, req.resource_type, ct, req.url, body_snippet))

    page.on("response", on_response)
    try:
        resp = page.goto(url, timeout=30000, wait_until="networkidle")
        print(f"URL: {url}")
        print(f"  STATUS: {resp.status if resp else None}")
        print(f"  FINAL URL: {page.url}")
        print(f"  TITLE: {page.title()}")
        # Look for login redirect / auth wall
        body_text = page.inner_text("body")[:800]
        print("  --- body text (first 800 chars) ---")
        print(body_text)
        # Any select/input for symbol?
        selects = page.eval_on_selector_all(
            "select", "els => els.map(e => ({id: e.id, name: e.name, options: [...e.options].slice(0,5).map(o=>o.value)}))"
        )
        if selects:
            print(f"  <select> elements: {selects}")
        print("  --- captured network activity ---")
        for method, status, rtype, ct, u, body in captured:
            print(f"    {method} {status} [{rtype}] {ct} {u}")
            if body:
                print(f"      BODY[:500]: {body!r}")
    except Exception as e:
        print(f"URL: {url}\n  ERROR: {e!r}")
    print("=" * 80)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for url in PAGES:
        pg = browser.new_page()
        probe(pg, url)
        pg.close()
    browser.close()
