# PSX Intelligence V2.2 — Fundamentals

Adds a native Fundamentals tab to every stock terminal.

- Fetches the official PSX company page for the selected symbol.
- Shows only values that can be found in the source.
- Supports Sales, Profit after Taxation, EPS, gross/net margin, EPS growth and PEG where available.
- Explicitly handles incomplete company pages rather than treating missing fields as zero.
- Keeps a one-tap official PSX source button.
- Adds `/fundamentals/{symbol}` to the optional FastAPI backend.
- Does not fabricate P/E, ROE, dividend yield or other metrics when PSX does not expose them consistently.

PSX company pages can contain annual and quarterly financials, ratios and company disclosures, but field availability varies by issuer.
