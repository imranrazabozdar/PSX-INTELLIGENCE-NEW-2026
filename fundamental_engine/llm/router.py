"""LLM router: eligibility gate -> cache -> kill switch/budget -> provider (with ordered fallback) -> strict validation
-> idempotent write of a CANDIDATE into event_extractions. Models never write to the database and never produce numbers.
"""
import hashlib
import json
import time
from datetime import datetime, timezone

from core.config import LLM_ELIGIBLE_ACCESS_STATUS
from extract import registry
from extract.claims import BAND_TO_CONFIDENCE, classify_claims
from llm import budget as bud
from llm.providers import ProviderError
from llm.validate import ValidationError, parse_json_object, validate_candidate

SCHEMA_VERSION_TAG = lambda spec: f"{spec['schema_id']}/{spec['schema_version']}"
PROMPT_VERSION_TAG = lambda spec: f"{spec['prompt_id']}@{spec['prompt_version']}"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Router:
    def __init__(self, db, providers, budgets=None, spec=registry.EVENT_CANDIDATE, now=_now, mono=time.monotonic):
        """providers: ordered list (primary first). budgets: {provider_name: Budget}."""
        self.db, self.providers, self.spec, self.now, self.mono = db, providers, spec, now, mono
        self.cooldown_until = {}   # provider name -> monotonic time; set after a rate limit, never hammer a limited provider
        self.budgets = budgets or {}
        self.prompt, self.prompt_sha = registry.load_prompt(spec["prompt_id"], spec["prompt_version"])
        self.schema = registry.load_schema(spec["schema_id"], spec["schema_version"])

    @classmethod
    def from_config(cls, db, task="extraction", path=None, require_review=True, **kw):
        from llm import config as cfg
        providers, budgets = cfg.build(task, path or cfg.DEFAULT_PATH, require_review)
        return cls(db, providers, budgets, **kw)

    # ------------------------------------------------------------ ledger
    def _log(self, provider, model, input_sha, outcome, in_tok=0, out_tok=0, attempts=1, error=None):
        return self.db.execute(
            "INSERT INTO llm_calls(called_at_utc,provider,model,prompt_id,prompt_version,prompt_sha256,input_sha256,"
            "input_tokens,output_tokens,cost_usd,attempts,outcome,error) VALUES(?,?,?,?,?,?,?,?,?,0,?,?,?)",
            (self.now(), provider, model, self.spec["prompt_id"], self.spec["prompt_version"], self.prompt_sha,
             input_sha, in_tok, out_tok, attempts, outcome, error)).lastrowid

    def _resolve_ticker(self, t):
        r = self.db.execute("SELECT company_id FROM company_identifiers WHERE id_type='psx_ticker' AND value=? "
                            "AND valid_to IS NULL", (t,)).one()
        return r["company_id"] if r else None

    # ------------------------------------------------------------ main entry
    def extract(self, source_item_id, text):
        item = self.db.execute(
            "SELECT s.source_item_id, s.source_id, src.access_status, src.source_type FROM source_items s "
            "JOIN sources src USING(source_id) WHERE s.source_item_id=?", (source_item_id,)).one()
        if item is None:
            return {"outcome": "error", "detail": "unknown source_item_id"}
        in_sha = sha(text)
        sv, pv = SCHEMA_VERSION_TAG(self.spec), PROMPT_VERSION_TAG(self.spec)

        # 1. eligibility: restricted/blocked/unreviewed content never leaves the project
        if item["access_status"] not in LLM_ELIGIBLE_ACCESS_STATUS:
            return {"outcome": "refused_source", "detail": f"source access_status={item['access_status']!r}"}

        # 2. cache (content-hash + versions): a hit costs nothing and is logged
        hit = self.db.execute(
            "SELECT extraction_id, model FROM event_extractions WHERE source_item_id=? AND schema_version=? AND prompt_version=?",
            (source_item_id, sv, pv)).one()
        if hit:
            self._log("cache", hit["model"], in_sha, "cached")
            return {"outcome": "cached", "extraction_id": hit["extraction_id"]}

        # 3-5. providers in order
        last = {"outcome": "not_connected", "detail": "no provider available"}
        for prov in self.providers:
            if self.cooldown_until.get(prov.name, 0) > self.mono():
                last = {"outcome": "rate_limited", "provider": prov.name, "detail": "cooling down"}
                continue
            b = self.budgets.get(prov.name, bud.Budget())
            ok, why = bud.allowed(self.db, prov.name, b, est_tokens=(len(text) + len(self.prompt)) // 4, now=None)
            if not ok:
                self._log(prov.name, prov.model, in_sha, why)
                last = {"outcome": why, "provider": prov.name}
                if why == "refused_kill_switch":
                    return last
                continue
            for attempt in range(1, b.max_attempts_per_item + 1):
                try:
                    reply = prov.complete(self.prompt, text)
                except ProviderError as e:
                    outcome = "not_connected" if e.kind in ("not_connected", "auth") else "error"
                    if e.kind == "rate_limited":
                        self.cooldown_until[prov.name] = self.mono() + (e.retry_after or 60)
                    self._log(prov.name, prov.model, in_sha, outcome, attempts=attempt, error=f"{e.kind}: {e}"[:300])
                    last = {"outcome": outcome, "provider": prov.name, "detail": str(e)}
                    break  # next provider (never hammer a provider that is rate limiting or down)
                try:
                    cand, flags = validate_candidate(parse_json_object(reply.text), self.schema, text, self._resolve_ticker)
                except ValidationError as e:
                    self._log(prov.name, prov.model, in_sha, "invalid_output", reply.input_tokens, reply.output_tokens,
                              attempt, error=e.reason[:300])
                    last = {"outcome": "invalid_output", "provider": prov.name, "detail": e.reason}
                    continue
                call_id = self._log(prov.name, prov.model, in_sha, "ok", reply.input_tokens, reply.output_tokens, attempt)
                return self._store(item, source_item_id, text, in_sha, call_id, prov, cand, flags, sv, pv)
        return last

    # ------------------------------------------------------------ candidate write (idempotent)
    def _store(self, item, source_item_id, text, in_sha, call_id, prov, cand, flags, sv, pv):
        claims = classify_claims(cand["claims"], item["source_type"])
        extracted = {"event_type": cand["event_type"], "claims": claims, "tickers": cand["tickers"],
                     "unresolved_tickers": cand["unresolved_tickers"], "confidence_band": cand["confidence_band"],
                     "record_kind": "model_candidate"}
        band = cand["confidence_band"]
        self.db.execute(
            "INSERT OR IGNORE INTO event_extractions(source_item_id,event_id,call_id,schema_version,prompt_version,model,"
            "extracted_json,confidence,confidence_explanation,needs_human_review,review_reasons_json,provenance_json,created_at_utc) "
            "VALUES(?,NULL,?,?,?,?,?,?,?,1,?,?,?)",
            (source_item_id, call_id, sv, pv, prov.model, json.dumps(extracted, sort_keys=True),
             BAND_TO_CONFIDENCE[band],
             f"model band {band!r} mapped to {BAND_TO_CONFIDENCE[band]} by a fixed Python table; not a model-supplied number",
             json.dumps(["phase1_all_candidates_need_human_review"] + flags),
             json.dumps({"provider": prov.name, "model": prov.model, "prompt_sha256": self.prompt_sha,
                         "input_sha256": in_sha, "source_item_id": source_item_id, "call_id": call_id}, sort_keys=True),
             self.now()))
        self.db.commit()
        row = self.db.execute("SELECT extraction_id FROM event_extractions WHERE source_item_id=? AND schema_version=? "
                              "AND prompt_version=? AND model=?", (source_item_id, sv, pv, prov.model)).one()
        return {"outcome": "ok", "extraction_id": row["extraction_id"], "call_id": call_id, "flags": flags,
                "claim_types": [c["claim_type"] for c in claims]}
