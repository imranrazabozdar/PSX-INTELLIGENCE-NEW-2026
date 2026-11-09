"""Central configuration. Secrets come ONLY from the environment (or the host's secret store), never from files in git."""
import os

APPROVED_TOS_SOURCE_STATUSES = ("verified_permitted",)
# Sources whose content may be sent to a third-party LLM. Restricted/blocked/licence-required/unreviewed content
# must never leave the project (forwarding it would spread restricted material further).
LLM_ELIGIBLE_ACCESS_STATUS = ("verified_permitted",)
OFFICIAL_SOURCE_TYPES = ("exchange", "official_regulator", "government")


def env(name, default=None):
    return os.environ.get(name, default)


def kill_switch_on():
    return env("LLM_KILL_SWITCH", "").strip().lower() in ("1", "true", "yes", "on")
