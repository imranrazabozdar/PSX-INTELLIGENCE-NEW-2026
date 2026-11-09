# LLM providers (free-first)

Status: **no provider is connected yet.** The router, budgets and validation are built and tested with a scripted provider.

## Policy
- One account and one API key per provider, owned by the project owner. No account/key rotation to get around quotas.
- Keys only in environment/host secret stores (e.g. `GROQ_API_KEY`), entered via the secure credential form or repo secrets; never in git or chat.
- Honour 429/`Retry-After`; fall back to the next provider only on error, timeout, invalid output or a refused budget.
- Free tiers may log prompts or train on them: send only public text from `verified_permitted` sources; never secrets or personal data.
- Free-tier limits and terms change: read the provider's current terms when wiring it, then record here (date, limits, data-use terms).
- Daily caps are set per provider in calls and tokens (`llm.budget.Budget`); the global kill switch is `LLM_KILL_SWITCH=1`.

## Wiring a provider (OpenAI-compatible endpoint)
`OpenAICompatProvider(name, base_url, model, api_key_env)`; add it to the router's ordered list and give it a `Budget`.

| Provider | Base URL | Model | Key env var | Terms/limits reviewed (date) | Status |
|---|---|---|---|---|---|
| _(none yet)_ | | | | | |

## Evaluation
Before a model or prompt replaces another, run it on a small frozen, labelled set (to be built in Phase 2) and compare
schema-valid rate, grounded-quote rate and ticker precision.
