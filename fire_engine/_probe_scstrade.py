#!/usr/bin/env python3
"""One-off Phase 1 discovery probe, round 4: TA_RealTimeCharting.aspx uses
TradingView's own Charting Library + UDF datafeed protocol
(charting_library.standalone.js, datafeedsnew/udf/dist/bundle.js) --
confirmed in round 3. The open question this round settles: does the UDF
datafeed's actual data (config/symbols/history calls) get served from
scstrade.com's own domain (SCS's own market data, just rendered through a
licensed TradingView UI -- plausibly fine to use) or from a
tradingview.com/third-party domain (literally the thing this project's
own rules forbid)? Waits longer and lets the widget fully initialize
before inspecting captured requests and their host."""
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

URL = "https://www.scstrade.com/TechnicalAnalysis/TA_RealTimeCharting.aspx"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    all_requests = []

    def on_request(req):
        all_requests.append((req.method, req.resource_type, req.url))

    page.on("request", on_request)
    page.goto(URL, timeout=30000, wait_until="networkidle")
    page.wait_for_timeout(8000)  # let the charting widget finish its own init/datafeed calls

    print(f"Total requests captured: {len(all_requests)}")
    hosts = {}
    for method, rtype, url in all_requests:
        host = urlparse(url).netloc
        hosts.setdefault(host, []).append((method, rtype, url))

    print("=== Distinct hosts contacted ===")
    for host in sorted(hosts):
        print(f"  {host}  ({len(hosts[host])} requests)")

    print()
    print("=== Every request to scstrade.com itself (candidate UDF datafeed calls) ===")
    for method, rtype, url in all_requests:
        if "scstrade.com" in urlparse(url).netloc:
            print(f"  {method} [{rtype}] {url}")

    print()
    print("=== Any request whose path contains udf/config/symbols/history/candle ===")
    import re
    for method, rtype, url in all_requests:
        if re.search(r"udf|/config|/symbols|/history|candle|resolution", url, re.I):
            print(f"  {method} [{rtype}] {url}")

    browser.close()
