"""Synthetic-series tests for pattern_scanner.bulkowski_detector."""
from datetime import date, timedelta

import pandas as pd

from pattern_scanner.bulkowski_detector import scan_symbol, CONFIRMED, FORMING

START = date(2024, 1, 1)


def _day(i):
    return str(START + timedelta(days=i))


def _frame(rows):
    """rows: list of (close, high, low, volume). Consecutive calendar dates from START."""
    recs = []
    prev = rows[0][0]
    for i, (c, h, l, v) in enumerate(rows):
        recs.append({"date": START + timedelta(days=i), "open": prev, "high": h, "low": l,
                     "close": c, "volume": v})
        prev = c
    return pd.DataFrame(recs)


def _pipe_rows(vol=100_000):
    rows = []
    for i in range(40):                          # base: range 2 around 100, lows 98.5..99.5
        c = 100.0 + (0.5 if i % 2 else -0.5)
        rows.append((c, c + 1.0, c - 1.0, vol))
    rows.append((95.0, 100.0, 90.5, vol))        # pipe bar 1: range 9.5
    rows.append((100.5, 101.0, 90.0, vol))       # pipe bar 2: lowest of 20, close in top 40%
    rows.append((103.0, 104.0, 102.0, vol))      # breakout: close > 101
    return rows


def _cup_rows(bottom, vol=100_000, breakout_vol=300_000):
    """0..14 decline from lip 100 to bottom, 15..34 flat at bottom, 35..49 rise to right lip 99."""
    closes = [100.0 - (100.0 - bottom) * i / 14.0 for i in range(15)]
    closes += [bottom] * 20
    closes += [bottom + (99.0 - bottom) * (i - 34) / 15.0 for i in range(35, 50)]
    rows = [(c, c + 0.5, c - 0.5, vol) for c in closes]
    rows += [(97.0, 98.0, 96.0, 50_000)] * 8    # handle: 8 bars, light volume, lows high in cup
    rows.append((100.0, 100.5, 99.5, breakout_vol))
    return rows


def _flag_rows(vol=100_000, pole_vol=300_000):
    rows = []
    for i in range(30):                          # base around 99
        c = 99.0 + (0.5 if i % 2 else -0.5)
        rows.append((c, c + 1.0, c - 1.0, vol))
    rows.append((98.0, 98.5, 97.0, pole_vol))    # pole base: unique lowest low 97
    for c in [105, 115, 125, 135, 145, 155, 160]:  # pole; top high 160.5 on the 160 bar
        rows.append((c - 0.5, c + 0.5, c - 1.5, pole_vol))
    rows[-1] = (159.5, 160.5, 158.5, pole_vol)
    rows += [(156.0, 158.0, 153.0, 100_000)] * 8  # flag: highs <= 158, lows >= 153
    rows.append((162.0, 163.0, 158.5, 150_000))  # breakout: close > 158
    return rows


def test_clean_pipe_bottom_confirmed():
    sigs = scan_symbol("TEST", _frame(_pipe_rows()))
    pipes = [s for s in sigs if s["pattern"] == "PIPE_BOTTOM_1D"]
    assert len(pipes) == 1, pipes
    s = pipes[0]
    assert s["state"] == CONFIRMED
    assert s["signal_date"] == _day(42)
    assert s["pattern_floor"] == 90.0
    assert s["median20_pkr"] >= 5_000_000
    assert s["stop_basis"] == "max(pattern_floor, EMA20)"


def test_high_tight_flag_confirmed():
    sigs = scan_symbol("TEST", _frame(_flag_rows()))
    flags = [s for s in sigs if s["pattern"] == "HIGH_TIGHT_FLAG_PSX" and s["state"] == CONFIRMED]
    assert len(flags) == 1, flags
    assert flags[0]["formation_high"] == 158.0
    assert flags[0]["pattern_floor"] == 97.0


def test_cup_with_handle_confirmed_at_25_percent_depth():
    sigs = scan_symbol("TEST", _frame(_cup_rows(bottom=75.0)))
    cups = [s for s in sigs if s["pattern"] == "CUP_WITH_HANDLE" and s["state"] == CONFIRMED]
    assert len(cups) == 1, cups
    assert cups[0]["signal_date"] == _day(58)
    assert cups[0]["rvol"] >= 1.5


def test_cup_rejected_when_depth_below_15_percent():
    sigs = scan_symbol("TEST", _frame(_cup_rows(bottom=86.0)))   # depth ~13.6%
    assert [s for s in sigs if s["pattern"] == "CUP_WITH_HANDLE"] == []


def test_liquidity_gate_rejects_low_median20():
    sigs = scan_symbol("TEST", _frame(_pipe_rows(vol=1_000)))    # median20 ~0.1M PKR
    assert sigs == []


def test_causality_future_bars_do_not_change_earlier_signals():
    for rows in (_cup_rows(bottom=75.0), _pipe_rows()):
        cut = len(rows) - 1
        future = [(101.0, 102.0, 80.0, 100_000)] * 10    # would change any non-causal rule
        prefix = scan_symbol("TEST", _frame(rows))
        full = scan_symbol("TEST", _frame(rows + future))

        def confirmed_upto(sigs):
            return sorted((s["pattern"], s["signal_date"], s["pattern_floor"], s["formation_high"])
                          for s in sigs
                          if s["state"] == CONFIRMED and s["signal_date"] <= _day(cut))

        assert confirmed_upto(prefix), "check must not be vacuous"
        assert confirmed_upto(full) == confirmed_upto(prefix)
