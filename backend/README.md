# PSX Intelligence V2 API (Alpha)

Private-research backend. It polls the PSX public market-watch page conservatively (default 120 seconds), caches one full-market snapshot, serves REST endpoints, and pushes change notifications to clients over `/ws/market`.

Run:
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Endpoints: `/api/health`, `/api/market`, `/api/opportunities`, `/api/sectors`, `/api/stocks/{symbol}`, `/api/export.xlsx`, WebSocket `/ws/market`.

The first Wyckoff output is explicitly heuristic. A statistically validated V2 classifier should be trained and walk-forward tested before using phase probabilities for investment decisions.
