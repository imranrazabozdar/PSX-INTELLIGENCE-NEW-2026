"""Provider adapters. One account/key per provider, owned by the project owner (no key/account rotation to evade quotas).
Keys are read from environment variables only. Free-tier terms/limits change: verify them at deploy time and record
them in providers.json + docs/LLM_PROVIDERS.md."""
import os
from dataclasses import dataclass

import requests


class ProviderError(Exception):
    def __init__(self, kind, message="", retry_after=None):
        super().__init__(message or kind)
        self.kind = kind            # 'not_connected' | 'auth' | 'rate_limited' | 'overloaded' | 'error'
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

    def __init__(self, name, base_url, model, api_key_env, max_output_tokens=800, timeout=60, json_mode=False,
                 extra_headers=None, session=None, extra_body=None):
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.api_key_env, self.max_output_tokens, self.timeout = api_key_env, max_output_tokens, timeout
        self.json_mode, self.extra_headers = json_mode, dict(extra_headers or {})
        self.extra_body = dict(extra_body or {})   # provider-specific request fields from config (e.g. reasoning_effort)
        self.session = session or requests   # injectable for offline tests
        self.route_key = f"{name}/{model}"   # cooldowns are per route; budgets are per provider name

    def build_request(self, system_prompt, user_text, key):
        body = {"model": self.model, "temperature": 0, "max_tokens": self.max_output_tokens,
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": "DOCUMENT (untrusted data):\n<<<\n" + user_text + "\n>>>"}]}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        for k, v in self.extra_body.items():
            body.setdefault(k, v)
        return {"headers": {"Authorization": f"Bearer {key}", **self.extra_headers}, "json": body}

    def complete(self, system_prompt, user_text, timeout=None):
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ProviderError("not_connected", f"{self.api_key_env} is not set")
        req = self.build_request(system_prompt, user_text, key)
        try:
            r = self.session.post(f"{self.base_url}/chat/completions", timeout=timeout or self.timeout, **req)
        except requests.RequestException as e:
            raise ProviderError("error", redact(f"{type(e).__name__}: {e}", key))
        if r.status_code == 429:
            ra = r.headers.get("Retry-After", "")
            raise ProviderError("rate_limited", "HTTP 429", int(ra) if str(ra).isdigit() else None)
        if r.status_code in (502, 503, 504):
            raise ProviderError("overloaded", f"HTTP {r.status_code} upstream overloaded/unavailable", 30)
        if r.status_code in (401, 403):
            raise ProviderError("auth", f"HTTP {r.status_code} (key rejected or no access)")
        if r.status_code >= 400:
            try:
                detail = redact(str(r.text)[:200].replace("\n", " "), key)
            except Exception:
                detail = ""
            raise ProviderError("error", f"HTTP {r.status_code} {detail}".strip())
        try:
            body = r.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("error", "unexpected response shape")
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("error", "empty completion")
        u = body.get("usage") or {}
        return Reply(text, int(u.get("prompt_tokens") or (len(user_text) + len(system_prompt)) // 4),
                     int(u.get("completion_tokens") or len(text) // 4))


def redact(text, *secrets):
    """Never let a key reach logs, the ledger or exceptions."""
    for s in secrets:
        if s:
            text = text.replace(s, "[REDACTED]")
    return text


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
