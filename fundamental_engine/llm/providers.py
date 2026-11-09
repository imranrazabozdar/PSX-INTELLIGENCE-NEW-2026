"""Provider adapters. One account/key per provider, owned by the project owner (no key/account rotation to evade quotas).
Keys are read from environment variables only. Free-tier terms/limits change: verify them at deploy time and record
them in providers.json + docs/LLM_PROVIDERS.md."""
import os
from dataclasses import dataclass

import requests


class ProviderError(Exception):
    def __init__(self, kind, message="", retry_after=None):
        super().__init__(message or kind)
        self.kind = kind            # 'not_connected' | 'rate_limited' | 'error'
        self.retry_after = retry_after


@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class Provider:
    name = "base"
    model = "base"

    def complete(self, system_prompt, user_text, timeout=60):  # pragma: no cover - interface
        raise NotImplementedError


class OpenAICompatProvider(Provider):
    """Any OpenAI-compatible /chat/completions endpoint (many free tiers expose one)."""

    def __init__(self, name, base_url, model, api_key_env, max_output_tokens=800):
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.api_key_env, self.max_output_tokens = api_key_env, max_output_tokens

    def complete(self, system_prompt, user_text, timeout=60):
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ProviderError("not_connected", f"{self.api_key_env} is not set")
        try:
            r = requests.post(f"{self.base_url}/chat/completions", timeout=timeout,
                              headers={"Authorization": f"Bearer {key}"},
                              json={"model": self.model, "temperature": 0, "max_tokens": self.max_output_tokens,
                                    "messages": [{"role": "system", "content": system_prompt},
                                                 {"role": "user", "content": "DOCUMENT (untrusted data):\n<<<\n" + user_text + "\n>>>"}]})
        except requests.RequestException as e:
            raise ProviderError("error", f"{type(e).__name__}: {e}")
        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            raise ProviderError("rate_limited", "HTTP 429", int(ra) if ra and ra.isdigit() else None)
        if r.status_code >= 400:
            raise ProviderError("error", f"HTTP {r.status_code}")
        body = r.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("error", "unexpected response shape")
        u = body.get("usage") or {}
        return Reply(text, int(u.get("prompt_tokens") or len(user_text + system_prompt) // 4),
                     int(u.get("completion_tokens") or len(text) // 4))


class ScriptedProvider(Provider):
    """Deterministic provider for tests/offline runs: replays queued replies or raises queued ProviderErrors."""

    def __init__(self, name="scripted", model="scripted-1", replies=()):
        self.name, self.model, self.queue, self.calls = name, model, list(replies), 0

    def complete(self, system_prompt, user_text, timeout=60):
        self.calls += 1
        if not self.queue:
            raise ProviderError("error", "no scripted reply")
        r = self.queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, Reply) else Reply(r, 100, 50)
