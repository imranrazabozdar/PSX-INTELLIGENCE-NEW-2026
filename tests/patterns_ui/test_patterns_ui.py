"""Patterns tab (presentation-only redesign) — rendering and interaction tests
against the fixture backend, via Streamlit's AppTest. No database involved."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import capture  # noqa: E402
import fixtures  # noqa: E402

VIEWS = ["Overview", "Market Behaviour", "Long", "Short", "Structural", "Volatility", "Wyckoff 2.0"]


@pytest.fixture(scope="module")
def fx():
    return json.loads(json.dumps(fixtures.build(), default=str))


def _texts(at):
    return " \n".join(t for _, t in capture.dump(at)["text"])


@pytest.mark.parametrize("layout", ["Cards", "Table"])
@pytest.mark.parametrize("view", VIEWS)
def test_every_view_renders(fx, view, layout):
    at = capture.run(fx, {"pui_view": view, "pui_layout": layout})
    assert not at.exception, [e.value for e in at.exception]
    txt = _texts(at)
    assert "BEAR" in txt and "KSE-100 below 200-day MA" in txt          # regime banner kept on every view
    if view == "Short":
        assert "Everything in this tab expects price to FALL" in txt
    if view == "Market Behaviour":
        assert "PSX FIRE Engine — Priority Setups" in txt
        assert "A strength score, not a probability or profitability claim" in txt
        assert "Not a buy signal, and not a prediction." in txt
    if view == "Wyckoff 2.0":
        assert "EXPERIMENTAL / NOT PRODUCTION" in txt
    if view == "Volatility":
        assert "not probabilities" in txt and "scored independently" in txt


def test_overview_counts_and_open_navigates(fx):
    at = capture.run(fx, {"pui_view": "Overview"})
    txt = _texts(at)
    assert "Signal modules active" in txt and "Stocks flagged" in txt
    btn = next(b for b in at.button if b.key == "pui_open_triangle_regression")
    btn.click().run()
    assert at.session_state["pui_view"] == "Short"
    assert "Regression-Channel Triangle Squeeze" in _texts(at)


def test_overview_by_stock_mixed_and_alphabetical(fx):
    at = capture.run(fx, {"pui_view": "Overview", "pui_ov_mode": "By stock", "pui_layout": "Table",
                          "pui_overview_stocks__shown": 100000})
    t = capture.dump(at)["tables"]["pui_overview_stocks"][0]
    syms = [r[0] for r in t["rows"]]
    assert syms == sorted(syms)
    d = t["columns"].index("direction")
    assert {r[d] for r in t["rows"]} <= {"Mixed", "Bullish", "Bearish", ""}


def test_show_more_reaches_every_row(fx):
    hits = fx["/patterns/triangle-regression-scan"]["hits"]
    at = capture.run(fx, {"pui_view": "Short", "pui_layout": "Table", "triangle_reg_hist_checkbox": True})
    for _ in range(10):
        more = [b for b in at.button if b.key == "triangle_regression_scan_table__more"]
        if not more:
            break
        more[0].click().run()
    t = capture.dump(at)["tables"]["triangle_regression_scan_table"][0]
    assert len(t["rows"]) == len(hits)


def test_card_open_sets_research_symbol(fx):
    at = capture.run(fx, {"pui_view": "Market Behaviour", "pui_layout": "Cards"})
    b = next(b for b in at.button if b.key and b.key.startswith("fire_scan_table_FIRE__open_0"))
    b.click().run()
    assert at.session_state["research_symbol"] == fx["/patterns/fire-scan"]["hits"][0]["symbol"]


def test_historical_checkbox_in_details_changes_rows(fx):
    at = capture.run(fx, {"pui_view": "Short", "pui_layout": "Table", "bearish_engulfing_scan_table__shown": 1000})
    n0 = len(capture.dump(at)["tables"]["bearish_engulfing_scan_table"][0]["rows"])
    cb = next(c for c in at.checkbox if c.key == "be_bear_hist_checkbox")
    cb.check().run()
    n1 = len(capture.dump(at)["tables"]["bearish_engulfing_scan_table"][0]["rows"])
    assert n1 == len(fx["/patterns/bearish-engulfing-scan"]["hits"]) and n1 > n0


def test_fire_filters_and_sections(fx):
    hits = fx["/patterns/fire-scan"]["hits"]
    at = capture.run(fx, {"pui_view": "Market Behaviour", "pui_layout": "Table",
                          "fire_scan_table_FIRE__shown": 999, "fire_scan_table_PRE-FIRE__shown": 999})
    t = capture.dump(at)["tables"]
    fire = [r for r in hits if r["classification"] == "FIRE"]
    assert [r[1] for r in t["fire_scan_table_FIRE"][0]["rows"]] == [h["symbol"] for h in fire]
    at.selectbox(key="fire_f_status").select("PRE-FIRE").run()
    t = capture.dump(at)["tables"]
    assert "fire_scan_table_FIRE" not in t and len(t["fire_scan_table_PRE-FIRE"][0]["rows"]) == len(hits) - len(fire)
    at.selectbox(key="fire_f_sort").select("MFI").run()
    mfi = [r[t["fire_scan_table_PRE-FIRE"][0]["columns"].index("mfi")] for r in capture.dump(at)["tables"]["fire_scan_table_PRE-FIRE"][0]["rows"]]
    assert mfi == sorted(mfi, reverse=True)


def test_volatility_filters_shared_across_subviews(fx):
    at = capture.run(fx, {"pui_view": "Volatility", "vol_subview": "⚠️ Early Warning"})
    at.multiselect(key="vol_f_liq").set_value(["Highly Liquid"]).run()
    at.session_state["vol_subview"] = "🟢 Bullish Expansion"
    at.run()
    assert at.multiselect(key="vol_f_liq").value == ["Highly Liquid"]
    assert "Liquidity: Highly Liquid" in _texts(at)


def test_no_full_row_fills_and_no_none_in_cards(fx):
    for v in VIEWS:
        at = capture.run(fx, {"pui_view": v, "pui_layout": "Cards"})
        for m in at.markdown:
            if 'class="pui-card"' in str(m.value):
                assert ">None<" not in m.value and "background-color" not in m.value


def test_volatility_and_w2_detail_paths_still_open(fx):
    at = capture.run(fx, {"pui_view": "Volatility", "pui_layout": "Cards"})
    next(b for b in at.button if b.key == "vol_ew__open_0").click().run()
    assert "What supports the bullish case" in _texts(at)
    at = capture.run(fx, {"pui_view": "Wyckoff 2.0", "pui_layout": "Cards"})
    next(b for b in at.button if b.key == "w2_table__open_0").click().run()
    assert "Why it is classified this way" in _texts(at)


# ---------------------------------------------------------------- Overview == module outputs --
# Module (Overview name) -> the table key(s) its own view renders. Ground truth is
# what each module view actually shows (Table layout, every row expanded).
MODULE_TABLES = {
    "PSX FIRE Engine — Priority Setups": ["fire_scan_table_FIRE", "fire_scan_table_PRE-FIRE"],
    "Wyckoff Institutional Accumulation": ["wyckoff_scan_table"],
    "OBV+MFI Setup with ATR Contraction": ["obv_mfi_scan_table"],
    "Bullish Engulfing": ["patterns_scan_table"],
    "Morning Star": ["morning_star_scan_table"],
    "Bullish Three-Line Strike": ["three_line_strike_scan_table"],
    "MHarris 5-Bar Reversal (Bullish)": ["mharris_bull_scan_table"],
    "Engulfing + Star Confirmed Reversal (Bullish)": ["engulfing_star_bull_scan_table"],
    "MACD+EMA200 Trend Resumption (Bullish)": ["macdema_bull_scan_table"],
    "Level Break Out (Resistance Breakout)": ["level_breakout_bull_scan_table"],
    "GP-Evolved Formula (Long Bias)": ["gp_evolved_bull_scan_table"],
    "Bearish Engulfing": ["bearish_engulfing_scan_table"],
    "Evening Star": ["evening_star_scan_table"],
    "MHarris 5-Bar Reversal (Bearish)": ["mharris_bear_scan_table"],
    "Engulfing + Star Confirmed Reversal (Bearish)": ["engulfing_star_bear_scan_table"],
    "MACD+EMA200 Trend Resumption (Bearish)": ["macdema_bear_scan_table"],
    "Regression-Channel Triangle Squeeze": ["triangle_regression_scan_table"],
    "Level Break Out (Support Breakdown)": ["level_breakout_bear_scan_table"],
    "GP-Evolved Formula (Short Bias)": ["gp_evolved_bear_scan_table"],
    "Chart Patterns (IHS, Double Bottom & Head/Shoulders)": ["advanced_pattern_scan_table"],
    "Early Warning": ["vol_ew"], "Bullish Expansion": ["vol_bull"], "Bearish Expansion": ["vol_bear"],
    "Wyckoff × Volatility": ["vw_table"], "Alerts": ["vol_alerts"],
}
W2_NAME = "Wyckoff Institutional Accumulation 2.0"
W2_FLAG = {"STRONG ACCUMULATION", "ADVANCED ACCUMULATION", "POTENTIAL BREAKOUT"}
TRADE_ACTION = {"bull": ("BUY",), "bear": ("SHORT", "SELL")}


@pytest.fixture(scope="module")
def module_tables(fx):
    import capture_views
    shown = {f"{k}__shown": 100000 for k in capture_views.KEYS}
    out = {}
    for v in ["Market Behaviour", "Long", "Short", "Structural", "Wyckoff 2.0"]:
        out.update({k: t[0] for k, t in capture.dump(capture.run(fx, dict(shown, pui_view=v, pui_layout="Table")))["tables"].items()})
    for sub in capture_views.VOL_SUBS[:5]:
        out.update({k: t[0] for k, t in capture.dump(capture.run(
            fx, dict(shown, pui_view="Volatility", vol_subview=sub, pui_layout="Table")))["tables"].items()})
    return out


def _rows(t):
    return [dict(zip(t["columns"], r)) for r in t["rows"]]


def _expected(module_tables):
    """{module name: [(symbol, direction or None)]} from the modules' own rendered rows."""
    exp = {}
    for name, keys in MODULE_TABLES.items():
        rows = [r for k in keys if k in module_tables for r in _rows(module_tables[k])]
        out = []
        for r in rows:
            sym = r.get("symbol") or r.get("Symbol")
            act = str(r.get("action") or r.get("Action") or "").upper()
            d = ("bull" if any(w in act for w in TRADE_ACTION["bull"]) else
                 "bear" if any(w in act for w in TRADE_ACTION["bear"]) else None)
            if name == "OBV+MFI Setup with ATR Contraction" or name == "Bullish Expansion":
                d = "bull"
            if name == "Bearish Expansion":
                d = "bear"
            out.append((sym, d))
        exp[name] = out
    w2 = _rows(module_tables["w2_table"])
    exp[W2_NAME] = [(r["symbol"], None) for r in w2 if r["enh_class"] in W2_FLAG]
    return exp


def test_overview_by_module_counts_match_module_outputs(fx, module_tables):
    import re
    at = capture.run(fx, {"pui_view": "Overview"})
    md = [str(m.value) for m in at.markdown]
    exp = _expected(module_tables)
    seen = 0
    for name, rows in exp.items():
        line = next(x for x in md if x.startswith(f"**{name}**"))
        n = int(re.search(r">(\d+) (?:signals?|alerts|research flags)<", line).group(1))
        assert n == len(rows), (name, n, len(rows))
        seen += 1
    assert seen == len(MODULE_TABLES) + 1
    hv = next(x for x in md if x.startswith("**Historical Validation**"))
    assert "Information view" in hv
    w2 = next(x for x in md if x.startswith(f"**{W2_NAME}**"))
    assert "include only Strong Accumulation, Advanced Accumulation and Potential Breakout" in w2


def test_overview_by_stock_flags_and_mixed_match_module_outputs(fx, module_tables):
    exp = _expected(module_tables)
    flagging = {k: v for k, v in exp.items() if k not in ("Wyckoff × Volatility", "Alerts")}  # list views, no flags
    want = {}
    for name, rows in flagging.items():
        for sym, d in rows:
            want.setdefault(sym, []).append((name, d))
    at = capture.run(fx, {"pui_view": "Overview", "pui_ov_mode": "By stock", "pui_layout": "Table",
                          "pui_overview_stocks__shown": 100000})
    got = {r["symbol"]: r for r in _rows(capture.dump(at)["tables"]["pui_overview_stocks"][0])}
    assert set(got) == set(want)
    for sym, fl in want.items():
        mods = got[sym]["modules"]
        for name in {n for n, _ in fl}:
            assert mods.count(f"{name}: ") == sum(1 for n, _ in fl if n == name), (sym, name, mods)
        dirs = {d for _, d in fl if d}
        expect_dir = ("Mixed" if dirs == {"bull", "bear"} else "Bullish" if dirs == {"bull"}
                      else "Bearish" if dirs == {"bear"} else "")
        assert got[sym]["direction"] == expect_dir, (sym, fl)
    assert any(r["direction"] == "Mixed" for r in got.values())      # fixture exercises Mixed


def test_overview_tiles_separate_info_views(fx):
    at = capture.run(fx, {"pui_view": "Overview"})
    txt = _texts(at)
    assert "Signal modules active" in txt
    assert "Not counted: 2 information views (Volatility Alerts and Historical Validation)" in txt


# ------------------------------------------------------------- trade fields on cards --
TRADE_LABELS = {"entry": "Entry", "Entry": "Entry", "stop": None, "Stop": "Stop-Loss (Risk)",
                "target 1": None, "Target": "Target (Reward)", "date": "Date", "Date": "Date", "R:R": "R:R"}


def test_cards_show_entry_stop_target_date_rr_wherever_they_exist(fx, module_tables):
    import html as _h
    import patterns_ui as U
    for v in ["Long", "Short", "Structural"]:
        at = capture.run(fx, {"pui_view": v, "pui_layout": "Cards",
                              **{f"{k}__shown": 100000 for k in MODULE_TABLES_KEYS()}})
        cards = [_h.unescape(str(m.value)) for m in at.markdown if 'class="pui-card"' in str(m.value)]
        for key in [k for ks in MODULE_TABLES.values() for k in ks]:
            if key not in module_tables or not key.endswith("scan_table"):
                continue
            for r in _rows(module_tables[key]):
                sym = r.get("symbol") or r.get("Symbol")
                mine = [c for c in cards if f'pui-sym">{sym}<' in c]
                if not mine:
                    continue
                for col in ("entry", "Entry", "stop", "Stop", "target 1", "Target", "date", "Date", "R:R"):
                    if col in r and not U.is_blank(r[col]):
                        lab = {"entry": "Entry", "Entry": "Entry", "stop": ("Stop-Loss (Risk)", "Initial Stop (ATR trail)"),
                               "Stop": "Stop-Loss (Risk)", "target 1": ("Target (Reward)", "Target"),
                               "Target": "Target (Reward)", "date": "Date", "Date": "Date", "R:R": "R:R"}[col]
                        labs = lab if isinstance(lab, tuple) else (lab,)
                        assert any(f"<span>{l}</span>" in c for c in mine for l in labs), (key, sym, col)


def MODULE_TABLES_KEYS():
    import capture_views
    return capture_views.KEYS
