"""Tests for the pure confluence join (pattern_scanner.confluence)."""
from pattern_scanner.confluence import build_badges, obv_symbols_from_result


def _sig(sym, date="2025-01-10"):
    return {"symbol": sym, "pattern": "PIPE_BOTTOM_1D", "state": "CONFIRMED", "signal_date": date}


def test_phase_d_on_signal_date_tags_phase_d():
    rows = [{"symbol": "ABC", "scan_date": "2025-01-10", "signal_type": "SHELF_BREAKOUT"}]
    out = build_badges([_sig("ABC")], rows, set())
    assert out[0]["confluence"] == "PHASE_D"


def test_phase_d_on_latest_session_tags_phase_d_even_if_other_date():
    rows = [{"symbol": "ABC", "scan_date": "2025-01-14", "signal_type": "SOS_IGNITION"}]
    out = build_badges([_sig("ABC")], rows, set(), latest_session="2025-01-14")
    assert out[0]["confluence"] == "PHASE_D"


def test_phase_d_other_type_or_old_date_gives_no_badge():
    rows = [{"symbol": "ABC", "scan_date": "2025-01-10", "signal_type": "SOMETHING_ELSE"},
            {"symbol": "ABC", "scan_date": "2024-12-01", "signal_type": "ACTIVE_SHELF"}]
    out = build_badges([_sig("ABC")], rows, set(), latest_session="2025-01-14")
    assert out[0]["confluence"] == ""


def test_obv_membership_tags_obv_mfi_and_both_combine():
    rows = [{"symbol": "XYZ", "scan_date": "2025-01-10", "signal_type": "ACTIVE_SHELF"}]
    sigs = [_sig("XYZ"), _sig("ABC")]
    out = build_badges(sigs, rows, {"xyz"}, latest_session="2025-01-14")
    assert out[0]["confluence"] == "PHASE_D+OBV_MFI"
    assert out[1]["confluence"] == ""


def test_input_signals_not_mutated():
    s = _sig("ABC")
    build_badges([s], [], {"ABC"})
    assert "confluence" not in s


def test_obv_symbols_from_cache_payload():
    payload = {"status": "ok", "hits": [{"symbol": "abc"}, {"symbol": None}, {"symbol": "DEF"}]}
    assert obv_symbols_from_result(payload) == {"ABC", "DEF"}
    assert obv_symbols_from_result(None) == set()
