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
| groq | https://api.groq.com/openai/v1 | llama-3.3-70b-versatile | `GROQ_API_KEY` | not yet | disabled |
| gemini | https://generativelanguage.googleapis.com/v1beta/openai | gemini-2.0-flash | `GEMINI_API_KEY` | not yet | disabled |
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
