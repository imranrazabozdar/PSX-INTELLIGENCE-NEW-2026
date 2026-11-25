"""Pure confluence join for chart-pattern signals (no DB access).

Inputs are rows the caller already read with SELECT:
  phase_d_rows: [{"symbol", "scan_date", "signal_type"}] from phase_d_signals
  obv_symbols:  set of symbols present in the latest analysis_cache 'obv_mfi_scan' result
Badges:
  PHASE_D  - symbol has a phase_d_signals row of type SHELF_BREAKOUT / SOS_IGNITION /
             ACTIVE_SHELF dated on the signal's date, or on the latest scanned session.
  OBV_MFI  - symbol is in the latest OBV+MFI scan hits.
"""
from __future__ import annotations

PHASE_D_TYPES = frozenset({"SHELF_BREAKOUT", "SOS_IGNITION", "ACTIVE_SHELF"})


def phase_d_index(phase_d_rows):
    """{symbol: set(scan_date)} for rows of a PHASE_D type (filters by type, normalises date)."""
    idx = {}
    for r in phase_d_rows or []:
        if r.get("signal_type") not in PHASE_D_TYPES:
            continue
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        idx.setdefault(sym, set()).add(str(r.get("scan_date") or "")[:10])
    return idx


def build_badges(signals, phase_d_rows, obv_symbols, latest_session=None):
    """Return a new list of signal dicts, each with a 'confluence' key:
    '' (none), 'PHASE_D', 'OBV_MFI' or 'PHASE_D+OBV_MFI'. Input dicts are not mutated."""
    pd_idx = phase_d_index(phase_d_rows)
    obv = {str(s).upper() for s in (obv_symbols or [])}
    latest = str(latest_session)[:10] if latest_session else None
    out = []
    for s in signals:
        sym = str(s.get("symbol") or "").upper()
        sig_date = str(s.get("signal_date") or "")[:10]
        dates = pd_idx.get(sym, set())
        has_pd = bool(dates) and (sig_date in dates or (latest is not None and latest in dates))
        tags = []
        if has_pd:
            tags.append("PHASE_D")
        if sym in obv:
            tags.append("OBV_MFI")
        row = dict(s)
        row["confluence"] = "+".join(tags)
        out.append(row)
    return out


def obv_symbols_from_result(result):
    """Symbols from an analysis_cache 'obv_mfi_scan' payload ({'hits': [{'symbol': ...}]})."""
    if not isinstance(result, dict):
        return set()
    return {str(h.get("symbol")).upper() for h in result.get("hits") or [] if h.get("symbol")}
