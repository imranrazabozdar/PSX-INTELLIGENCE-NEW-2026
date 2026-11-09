"""Loads and validates providers_config.json, builds providers + budgets for a task.

Safeguards:
  * the config may never contain secret values (only the NAME of an env var)
  * a provider is usable in production only if enabled AND model_verified AND terms_reviewed_utc is set
    (tests may pass require_review=False)
"""
import json
import re
from pathlib import Path

from llm.budget import Budget
from llm.providers import OpenAICompatProvider

DEFAULT_PATH = Path(__file__).resolve().parent / "providers_config.json"
_SECRET_KEYS = re.compile(r"(api_?key|secret|token|password|bearer)$", re.I)
_SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9]{8,}|gsk_[A-Za-z0-9]{8,}|AIza[0-9A-Za-z_\-]{10,}|Bearer\s+\S{8,})")
REQUIRED = ("name", "base_url", "api_key_env", "model", "enabled", "max_calls_per_day", "max_tokens_per_day")


class ConfigError(Exception):
    pass


def _scan(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _SECRET_KEYS.search(k) and k != "api_key_env":
                raise ConfigError(f"{path}.{k}: secret-like field names are not allowed in the config")
            _scan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan(v, f"{path}[{i}]")
    elif isinstance(obj, str) and _SECRET_VALUE.search(obj):
        raise ConfigError(f"{path}: looks like a secret value; keep keys in the environment")


def load_config(path=DEFAULT_PATH):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    _scan(cfg)
    names = set()
    for p in cfg.get("providers", []):
        miss = [k for k in REQUIRED if k not in p]
        if miss:
            raise ConfigError(f"provider {p.get('name')!r}: missing {miss}")
        if p["name"] in names:
            raise ConfigError(f"duplicate provider {p['name']!r}")
        names.add(p["name"])
        if not p["base_url"].startswith("https://"):
            raise ConfigError(f"{p['name']}: base_url must be https")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", p["api_key_env"]):
            raise ConfigError(f"{p['name']}: api_key_env must be an UPPER_SNAKE env var name")
    for task, order in cfg.get("tasks", {}).items():
        for n in order:
            if n not in names:
                raise ConfigError(f"task {task!r} references unknown provider {n!r}")
    return cfg


def usable(p, require_review=True):
    if not p["enabled"]:
        return False
    return (not require_review) or bool(p.get("model_verified") and p.get("terms_reviewed_utc"))


def build(task="extraction", path=DEFAULT_PATH, require_review=True, session=None):
    """-> (providers in routing order, {name: Budget}). Providers that are not usable are skipped."""
    cfg = load_config(path)
    by = {p["name"]: p for p in cfg["providers"]}
    providers, budgets = [], {}
    for name in cfg.get("tasks", {}).get(task, []):
        p = by[name]
        if not usable(p, require_review):
            continue
        providers.append(OpenAICompatProvider(
            p["name"], p["base_url"], p["model"], p["api_key_env"], p.get("max_output_tokens", 800),
            p.get("timeout_s", 60), p.get("json_mode", False), p.get("extra_headers"), session))
        budgets[p["name"]] = Budget(p["max_calls_per_day"], p["max_tokens_per_day"], p.get("max_attempts_per_item", 2))
    return providers, budgets


def status(path=DEFAULT_PATH, environ=None):
    """Per-provider readiness summary (never prints keys)."""
    import os
    env = os.environ if environ is None else environ
    out = []
    for p in load_config(path)["providers"]:
        out.append({"name": p["name"], "enabled": p["enabled"], "model_verified": bool(p.get("model_verified")),
                    "terms_reviewed": bool(p.get("terms_reviewed_utc")), "key_present": bool(env.get(p["api_key_env"])),
                    "usable_in_production": usable(p) and bool(env.get(p["api_key_env"]))})
    return out
