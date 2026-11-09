"""Call/token budget gates and kill switch. Free tiers cost $0, so caps are in calls and tokens per UTC day per provider,
counted from the llm_calls ledger (cache hits and refusals do not count)."""
from dataclasses import dataclass
from datetime import datetime, timezone

from core.config import kill_switch_on

COUNTED = ("ok", "invalid_output", "error")


@dataclass
class Budget:
    max_calls_per_day: int = 50
    max_tokens_per_day: int = 100_000
    max_attempts_per_item: int = 2  # per provider, only for invalid output


def today_start(now=None):
    n = now or datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT00:00:00Z")


def usage_today(db, provider, now=None):
    r = db.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens+output_tokens),0) AS tokens FROM llm_calls "
        "WHERE provider=? AND called_at_utc>=? AND outcome IN ('ok','invalid_output','error')",
        (provider, today_start(now))).one()
    return r["calls"], r["tokens"]


def allowed(db, provider, budget, est_tokens=0, now=None):
    if kill_switch_on():
        return False, "refused_kill_switch"
    calls, tokens = usage_today(db, provider, now)
    if calls + 1 > budget.max_calls_per_day or tokens + est_tokens > budget.max_tokens_per_day:
        return False, "refused_budget"
    return True, "ok"
