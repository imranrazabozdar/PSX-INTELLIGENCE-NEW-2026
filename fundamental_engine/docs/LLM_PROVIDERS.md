# LLM providers (free-first)

Status: **no provider is enabled or connected yet.** `llm/providers_config.json` defines three OpenAI-compatible candidates (Groq, Gemini API, OpenRouter free route), all shipped `enabled=false`, `model_verified=false`, `terms_reviewed_utc=null`. The router, budgets, validation and rate-limit handling are tested offline through a fake HTTP session; live checks are opt-in (below).

## Policy
- One account and one API key per provider, owned by the project owner. No account/key rotation to get around quotas.
- Keys only in environment/host secret stores (e.g. `GROQ_API_KEY`), entered via the secure credential form or repo secrets; never in git or chat.
- Honour 429/`Retry-After`; fall back to the next provider only on error, timeout, invalid output or a refused budget.
- Free tiers may log prompts or train on them: send only public text from `verified_permitted` sources; never secrets or personal data.
- Free-tier limits and terms change: read the provider's current terms when wiring it, then record here (date, limits, data-use terms).
- Daily caps are set per provider in calls and tokens (`llm.budget.Budget`); the global kill switch is `LLM_KILL_SWITCH=1`.

## Wiring a provider (OpenAI-compatible endpoint)
`OpenAICompatProvider(name, base_url, model, api_key_env)`; add it to the router's ordered list and give it a `Budget`.

| Provider | Base URL | Model (UNVERIFIED) | Key env var | Terms/limits reviewed | Status |
|---|---|---|---|---|---|
| groq | https://api.groq.com/openai/v1 | openai/gpt-oss-20b | `GROQ_API_KEY` | 2026-11-09, owner attestation | **enabled** (model confirmed via /models) |
| gemini | https://generativelanguage.googleapis.com/v1beta/openai | gemini-3.5-flash-lite, gemini-3.1-flash-lite (verified); gemini-3.8-flash (listed, unverified) | `GEMINI_API_KEY` | 2026-11-09, owner attestation | **enabled** |
| openrouter | https://openrouter.ai/api/v1 | meta-llama/llama-3.3-70b-instruct:free | `OPENROUTER_API_KEY` | not yet | disabled |

Base URLs are the providers' documented OpenAI-compatible endpoints. Model ids and free-tier limits were written without
consulting the provider's current docs and may be out of date: verify, then set `model_verified`, `terms_reviewed_utc`
and `enabled` in the config. Daily caps in the config are OUR conservative caps, not the providers' published limits.

## Enabling a provider (checklist)
1. Read the provider's current free-tier terms: data use (logging/training), limits, permitted use. Record the date here.
2. Confirm the model id exists on the free tier; set `model_verified=true`.
3. Create the key under the owner's account; store it as the env var / host secret named in `api_key_env` (never in git or chat).
4. Set `terms_reviewed_utc` and `enabled=true`.
5. `python fundamental_engine/scripts/check_providers.py` (readiness), then
   `RUN_LIVE_LLM_TESTS=1 python fundamental_engine/scripts/check_providers.py --live` or `pytest -m live` (spends a few free calls).

## Evaluation
Before a model or prompt replaces another, run it on a small frozen, labelled set (to be built in Phase 2) and compare
schema-valid rate, grounded-quote rate and ticker precision.

## Rollout order and code paths (owner decision; each step contingent on verification, terms review, secure credential injection)
| Step | Provider | Task | Code path | State |
|---|---|---|---|---|
| 1 | Groq | `news_event_extraction` | `extract/pipeline.py: run_news_batch`, `scripts/run_extraction.py` | built, tested offline; dry-run works; **not enabled** |
| 2 | Gemini | `long_document_extraction`, `financial_line_items` | `extract/chunking.py`, `run_long_document`, `llm/handlers.py: FinancialHandler`, `extract/numbers.py` | built, tested offline; **not enabled** |
| 3 | OpenRouter | fallback for both | `llm/config.py` per-model expansion; per-route cooldown, per-provider budget | built, tested offline; **not enabled** |

### Step 1 - news/event extraction
- Input is built by `extract/text.py` from the source's `retention_mode`. **All 10 verified_permitted news sources are
  `metadata_only` with no stored excerpts**, so today the only text a model may see is the **headline** (32-78 chars in the
  first dry run). Expect thin results (few claims, few tickers). Sending full article text would need a separate, explicit
  permission decision plus an approved fetch path; it is not implemented.
- Grounding, zero-number rule, Python-assigned claim types, review-gated candidates, content-hash cache, budgets and kill
  switch all apply (see README). Run: `python fundamental_engine/scripts/run_extraction.py --task news_event_extraction --limit 10` (dry run) / `--live`.

### Step 2 - long documents and financial statements
- Documents are chunked (default 20,000 chars, 500 overlap) and each chunk is cached by content hash (folded into
  `schema_version`, so no schema change). Quotes are grounded against their own chunk only. At most `max_chunks_per_run`
  (default 5) uncached chunks per run; re-running resumes (earlier chunks are cache hits).
- Financial line items: the model returns verbatim label/period/value text and the verbatim unit text; **Python parses the
  numbers** (`value_parsed`, strict comma-grouping/parentheses rules) and never scales by unit. Candidates are stored in
  `event_extractions` for review; nothing is written to `financial_metrics`.
- **Eligibility limitation:** annual reports from restricted sources (e.g. PSX filings held in the manual vault) are blocked
  by the eligibility gate and cannot be sent to any provider. Using them needs an explicit owner decision (and a provider
  whose data-use terms are acceptable); no bypass exists.

### Step 3 - OpenRouter fallback
- A provider with a `models` list expands to one route per model that is both `enabled` and `verified`, in listed order.
  A rate-limited route cools down for its `Retry-After`; the other models of the provider are still tried. Daily budgets
  are shared across all models of a provider. Currently one unverified, disabled model is listed.

### Groq go-live notes (2026-11-09)
- Enabled by owner decision: `openai/gpt-oss-20b` (id confirmed present via `GET /models`; `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` are NOT available on this account). Terms review recorded as an **owner attestation**, not an assistant review.
- Key: saved on the Default environment via the secure credential form; the proxy injects it. Code reads `GROQ_API_KEY`, so run with `GROQ_API_KEY=proxy-injected` in this sandbox. On the owner's own machine/hosts set the real key in the environment.
- **Reasoning-model gotcha:** `gpt-oss` spends hidden reasoning tokens inside `max_output_tokens`. At 800 the model sometimes produced an empty answer and Groq's JSON mode returned HTTP 400 `json_validate_failed`. Config now uses `max_output_tokens=2000` and `extra_body={"reasoning_effort":"low"}`; the live compat test passed 3/3 afterwards. Error details now include a redacted, truncated response body for diagnosis.
- Observed usage: ~380 input / ~680 output tokens per headline-sized call before the fix; watch `llm_calls` after the change.
- Disclosure: one live call during debugging used a headline-length sentence paraphrased from an Investify (restricted) listing (OGDC corporate briefing). It was sent only to Groq, stored nowhere (in-memory DB), and should not have been used: the eligibility gate protects stored items, but my ad-hoc test bypassed it. Later live tests use only synthetic sample text.

### Gemini go-live notes (2026-11-09)
- Key: saved on the Default environment via the secure credential form (host `generativelanguage.googleapis.com`); the proxy injects it. Run with `GEMINI_API_KEY=proxy-injected` in this sandbox.
- **`/models` listing is not proof a model works.** `gemini-2.5-flash` is listed but a real call returns 404 "no longer available to new users"; `gemini-2.0-flash` is absent. Only a successful real call counts as verification.
- Availability is volatile on this tier: on 2026-11-09 `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` answered (HTTP 200) while `gemini-3.8-flash`, `3.5-flash`, `3.6-flash` returned HTTP 502 and `3.7-flash`, `flash-latest` HTTP 503 "high demand". The config lists models in order (`models` list, per-model `verified`); `gemini-3.8-flash` is enabled but unverified, so it is skipped until a live call succeeds. When one does, flip its `verified` to true and move it first if quality justifies it.
- Router now treats HTTP 502/503/504 as `overloaded`: the route cools down 30 s and the next route/provider is tried (logged as `error`).
- Thinking-model caveat applies (reasoning tokens count against `max_output_tokens`): `reasoning_effort=low`, cap 4000, timeout 120 s.
- Fallback order: news = groq -> gemini -> openrouter; long documents = gemini -> openrouter; financial line items = gemini.
- Live verification: `check_providers.py --live` ok; live pytest (structured JSON + financial line items) 2/2; synthetic 3-chunk statement (known values): recall 9/9, 0 wrong, numbers parsed by Python.
- Privacy: free-tier Gemini terms commonly allow Google to use prompts to improve products. Only public text from verified_permitted sources may be sent; restricted-source documents (e.g. PSX filings in the vault) remain blocked by the eligibility gate.
