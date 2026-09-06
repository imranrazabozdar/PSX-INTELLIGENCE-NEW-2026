"""config.py — loads fire_config/fire_config.yaml into a plain dict, with
light validation. Every threshold used elsewhere in fire_engine is read
from this config, not hard-coded, per the project's own "make all
thresholds configurable" requirement.
"""
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config" / "fire_config.yaml"

_REQUIRED_TOP_LEVEL_KEYS = [
    "database", "mfi", "volume", "compression", "absorption",
    "support_resistance", "pre_fire", "fire", "fire_scoring", "session",
    "stocks", "exclusion", "data_source", "scheduling", "dashboard", "wyckoff",
]


def load_config(path=None) -> dict:
    """Load and lightly validate the YAML config. Raises ValueError if a
    required top-level section is missing (fail loud, not with a silently
    half-configured system) or if fire_scoring weights don't sum to 100."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path) as f:
        cfg = yaml.safe_load(f)

    missing = [k for k in _REQUIRED_TOP_LEVEL_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"fire_config.yaml missing required section(s): {missing}")

    weights = cfg["fire_scoring"]["weights"]
    total = sum(weights.values())
    if total != 100:
        raise ValueError(f"fire_scoring.weights must sum to 100, got {total}: {weights}")

    wcfg = cfg["wyckoff"]
    wyckoff_points = (
        wcfg["bb_width_points"] + wcfg["supply_exhaustion_points"]
        + wcfg["absorption_points"] + wcfg["obv_divergence_points"]
    )
    if wyckoff_points != 100:
        raise ValueError(f"wyckoff's *_points must sum to 100, got {wyckoff_points}")

    return cfg
