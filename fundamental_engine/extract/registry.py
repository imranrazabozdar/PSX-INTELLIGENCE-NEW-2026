"""Versioned prompt + schema registry. Every LLM call records the prompt's SHA-256."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load_prompt(prompt_id, version):
    text = (BASE / "prompts" / f"{prompt_id}_{version}.txt").read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_schema(schema_id, version):
    return json.loads((BASE / "schemas" / f"{schema_id}_{version}.json").read_text(encoding="utf-8"))


EVENT_CANDIDATE = {"prompt_id": "event_candidate", "prompt_version": "v1", "schema_id": "event_candidate",
                   "schema_version": "1"}
