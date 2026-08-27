# PSX Intelligence V3.0 — Wyckoff Pro

Adds a conservative, rule-driven Wyckoff engine on genuine OHLCV.

New:
- Trading-range support/resistance detection
- Effort-vs-Result: relative volume, spread, price progress
- Spring quality: penetration, return to range, 1–3 bar recovery, volume, test, SOS confirmation
- Upthrust quality: penetration, prompt rejection, relative volume, SOW confirmation
- Candidate → Tested → Confirmed states
- Phase C/D hypotheses with UNRESOLVED fallback
- Evidence HIGH/MEDIUM/LOW, explicitly not profit probability
- `/wyckoff-pro/{symbol}` endpoint

The engine deliberately does not force PS/SC/AR/ST/BC labels where the available algorithm cannot
support them robustly. Future calibration should be based on stored PSX examples and walk-forward tests.
