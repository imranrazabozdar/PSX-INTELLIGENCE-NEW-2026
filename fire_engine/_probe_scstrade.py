#!/usr/bin/env python3
"""One-off Phase 1 discovery probe: verify scstrade.com is reachable and
inspect its actual page structure for 1-minute OHLCV data, before writing
any scraper against a guess. Not part of the production scraper -- deleted
or replaced once the real structure is confirmed. Prints findings to the
Actions log (this sandbox can't reach scstrade.com directly, same
constraint already documented in backend/dps_scraper.py for dps.psx.com.pk)."""
import sys
from playwright.sync_api import sync_playwright

CANDIDATE_URLS = [
    "https://www.scstrade.com/",
    "https://www.scstrade.com/MarketStatistics/MS_ChartsData.aspx",
    "https://www.scstrade.com/Charts/",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for url in CANDIDATE_URLS:
        page = browser.new_page()
        try:
            resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
            print(f"URL: {url}")
            print(f"  STATUS: {resp.status if resp else None}")
            print(f"  FINAL URL: {page.url}")
            print(f"  TITLE: {page.title()}")
            html = page.content()
            print(f"  HTML length: {len(html)}")
            # Look for anything chart/table/candle related
            lower = html.lower()
            for kw in ["candle", "ohlc", "1min", "1 min", "intraday", "mfi", "chart", "login", "iframe"]:
                if kw in lower:
                    print(f"    contains keyword: {kw!r}")
            print("  --- first 2000 chars of body text ---")
            body_text = page.inner_text("body")[:2000]
            print(body_text)
            print("=" * 80)
        except Exception as e:
            print(f"URL: {url}")
            print(f"  ERROR: {e!r}")
            print("=" * 80)
        finally:
            page.close()
    browser.close()
