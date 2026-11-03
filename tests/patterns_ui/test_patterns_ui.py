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
    assert "Active modules" in txt and "Stocks flagged" in txt
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
