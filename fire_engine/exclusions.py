"""exclusions.py — Phase 6: filter out low-volume/low-volatility sector
stocks unsuitable for FIRE pattern analysis. Loads the flat symbol list
from fire_engine.excluded_sectors_config -- see that module's own
docstring for a reported discrepancy (the source material's own claimed
"519 total" vs. the 244 symbols it actually supplied).
"""
from fire_engine.excluded_sectors_config import EXCLUDED_SYMBOLS_FLAT


def load_exclusions_from_config(config_path: str = None) -> list:
    """`config_path` is accepted for interface parity with the spec but
    unused: the exclusion list is a Python module
    (fire_engine.excluded_sectors_config), not YAML, since that's the
    literal format it was supplied in. Returns the flat sorted symbol
    list."""
    return list(EXCLUDED_SYMBOLS_FLAT)


def is_stock_excluded(symbol: str, excluded_list: list) -> bool:
    return symbol.upper() in {s.upper() for s in excluded_list}


def filter_excluded_stocks(all_symbols: list, excluded_list: list) -> list:
    excluded_upper = {s.upper() for s in excluded_list}
    return [s for s in all_symbols if s.upper() not in excluded_upper]
