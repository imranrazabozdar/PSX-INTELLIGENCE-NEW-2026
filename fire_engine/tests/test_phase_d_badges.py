"""Phase D pre-ignition badges and setup grade (fire_engine/phase_d_badges.py): synthetic bars only."""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fire_engine import phase_d_badges as B  # noqa: E402

END = date(2026, 11, 24)


def _weekdays(n, end=END):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def _bars(closes, ranges, vols):
    dates = _weekdays(len(closes))
    return [{"date": d, "open": c, "high": c + r / 2, "low": c - r / 2, "close": c, "volume": v}
            for d, c, r, v in zip(dates, closes, ranges, vols)]


def coil_bars(rally=False):
    """Flat base at ~10. Wide ranges up to bar 92, then narrow (ATR contracts). Last three bars before
    the ignition (bar 105) trade on a fifth of the normal volume. Optionally a 15% rally over the 10 bars
    before the ignition, which makes the setup exhausted."""
    closes = [10 + (0.05 if k % 2 else -0.05) for k in range(106)]
    if rally:
        for k in range(94, 105):
            closes[k] = 10 + 1.5 * (k - 94) / 10
    ranges = [1.0 if k < 93 else 0.2 for k in range(106)]
    vols = [1_000_000.0] * 106
    for k in (102, 103, 104):
        vols[k] = 200_000.0
    return _bars(closes, ranges, vols)


IGN_COIL = _weekdays(106)[105]


def trend_closes(scale=1.0):
    """20 -> 40 over 188 bars, a 25% rally over the 8 bars before bar 196, then flat."""
    c = []
    for k in range(200):
        if k < 188:
            v = 20 + 20 * k / 187
        elif k <= 195:
            v = 40 + 10 * (k - 187) / 8
        else:
            v = 50.0
        c.append(v * scale)
    return c


def trend_bars(scale=1.0):
    closes = trend_closes(scale)
    return _bars(closes, [0.5 * scale] * 200, [1_000_000.0] * 200)


IGN_TREND = _weekdays(200)[196]


def test_coil_dryup_gives_a_plus_prime():
    bars = coil_bars()
    g = B.compute_badges(bars, IGN_COIL, bars[-1]["date"])
    assert g["coil_dryup"] is True and g["exhausted_pre_ign"] is False
    assert g["w1_leader"] is False                      # only 22 weeks of history: no weekly leader
    assert g["setup_grade"] == "A+ PRIME"
    assert g["price_tier"] == "SWEET_SPOT"
    assert g["atr_ratio_pre_ign"] <= 0.95 and g["dryup_pre_ign"] <= 0.35
    assert g["mfi_pre_ign"] is not None and g["ret10_pre_ign"] is not None


def test_leader_with_exhaustion_is_standard():
    bars = trend_bars()
    g = B.compute_badges(bars, IGN_TREND, bars[-1]["date"])
    assert g["w1_leader"] is True
    assert g["exhausted_pre_ign"] is True               # 25% rally over the 10 bars before ignition
    assert g["coil_dryup"] is False
    assert g["setup_grade"] == "STANDARD"
    assert g["price_tier"] == "MID_CAP"


def test_price_above_100_is_watch_only_heavy_cap():
    bars = trend_bars(scale=2.6)                        # same shape, last close 130
    g = B.compute_badges(bars, IGN_TREND, bars[-1]["date"])
    assert g["w1_leader"] is True                       # the leader is computed, but the price cap wins
    assert g["setup_grade"] == "WATCH_ONLY"
    assert g["price_tier"] == "HEAVY_CAP_CAUTION"


def test_exhaustion_blocks_a_plus_even_with_coil():
    bars = coil_bars(rally=True)
    g = B.compute_badges(bars, IGN_COIL, bars[-1]["date"])
    assert g["coil_dryup"] is True and g["exhausted_pre_ign"] is True
    assert g["setup_grade"] != "A+ PRIME"
    assert g["setup_grade"] == "WATCH_ONLY"             # no weekly leader, so not STANDARD either


def test_missing_ignition_date_does_not_raise():
    bars = coil_bars()
    g = B.compute_badges(bars, "2001-01-02", bars[-1]["date"])
    assert g["coil_dryup"] is False and g["exhausted_pre_ign"] is False
    assert g["atr_ratio_pre_ign"] is None and g["dryup_pre_ign"] is None
    assert g["setup_grade"] in ("A+ PRIME", "STANDARD", "WATCH_ONLY")
    g = B.compute_badges(bars, None, bars[-1]["date"])
    assert g["coil_dryup"] is False and g["price_tier"] == "SWEET_SPOT"


def test_bad_input_returns_watch_only_and_never_raises():
    g = B.compute_badges(None, IGN_COIL, "2026-11-24")
    assert g == {"coil_dryup": False, "w1_leader": False, "exhausted_pre_ign": False, "price_tier": None,
                 "setup_grade": "WATCH_ONLY", "atr_ratio_pre_ign": None, "dryup_pre_ign": None,
                 "mfi_pre_ign": None, "ret10_pre_ign": None}
    g = B.compute_badges([{"date": "2026-11-24", "close": "x"}], "2026-11-24", "2026-11-24")
    assert g["setup_grade"] == "WATCH_ONLY" and g["coil_dryup"] is False


def test_price_tier_thresholds():
    assert B._tier(25) == "SWEET_SPOT" and B._tier(25.01) == "MID_CAP"
    assert B._tier(100) == "MID_CAP" and B._tier(100.01) == "HEAVY_CAP_CAUTION"
