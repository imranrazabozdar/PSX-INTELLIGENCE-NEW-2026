# PSX Intelligence V2.8 — Announcements Intelligence + AI Synthesis

The official PSX company pages expose announcement groups including Financial Results, Board Meetings
and Others, and the central Announcements portal exposes Company Announcements, CBS, CDC, SECP, NCCPL,
AGM/EOGM and Payouts.

## Added
- `/announcement-intelligence/{symbol}`
- conservative headline direction/materiality classification
- `/ai-brief/{symbol}`
- bull case / bear case / confirmation / invalidation
- market regime + relative strength + unified conviction context
- latest official-disclosure titles in the evidence packet

## Grounding rule
The classifier only labels visible announcement titles. It does not pretend to read a PDF it has not
actually fetched and parsed. A future LLM may rewrite/explain the grounded evidence, but may not invent
prices, indicators, filings, document contents or profit probabilities.

## Next build
Consolidated Android release: connect native screens to the deployed backend, add configuration for the
backend URL, polish loading/error states, and produce the install candidate.
