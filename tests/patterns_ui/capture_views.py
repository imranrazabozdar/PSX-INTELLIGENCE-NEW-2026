"""Capture every Patterns view of the redesigned tab (Table layout, all rows
expanded) into one JSON: {view[/subview]: dump}."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture  # noqa: E402

VIEWS = ["Overview", "Market Behaviour", "Long", "Short", "Structural", "Volatility", "Wyckoff 2.0"]
VOL_SUBS = ["⚠️ Early Warning", "🟢 Bullish Expansion", "🔴 Bearish Expansion", "🧩 Wyckoff × Volatility",
            "🔔 Alerts", "🧪 Historical Validation"]
KEYS = ["fire_scan_table_FIRE", "fire_scan_table_PRE-FIRE", "wyckoff_scan_table", "obv_mfi_scan_table",
        "patterns_scan_table", "morning_star_scan_table", "three_line_strike_scan_table", "mharris_bull_scan_table",
        "engulfing_star_bull_scan_table", "macdema_bull_scan_table", "level_breakout_bull_scan_table",
        "gp_evolved_bull_scan_table", "bearish_engulfing_scan_table", "evening_star_scan_table",
        "mharris_bear_scan_table", "engulfing_star_bear_scan_table", "macdema_bear_scan_table",
        "triangle_regression_scan_table", "level_breakout_bear_scan_table", "gp_evolved_bear_scan_table",
        "advanced_pattern_scan_table", "vol_ew", "vol_bull", "vol_bear", "vw_table", "vol_alerts", "w2_table",
        "pui_overview_stocks"]


def main(fx_path, out_path, layout="Table", extra=()):
    fx = json.load(open(fx_path))
    base = {"pui_layout": layout, **{f"{k}__shown": 100000 for k in KEYS}}
    base.update(dict(extra))
    res = {}
    for v in VIEWS:
        subs = VOL_SUBS if v == "Volatility" else [None]
        for sub in subs:
            st_ = dict(base, pui_view=v)
            if sub:
                st_["vol_subview"] = sub
            at = capture.run(fx, st_)
            name = v + (f"/{sub}" if sub else "")
            res[name] = capture.dump(at)
            print(name, len(res[name]["tables"]), "tables", res[name]["exceptions"][:1], flush=True)
    if layout == "Table":
        st_ = dict(base, pui_view="Overview", pui_ov_mode="By stock")
        res["Overview/By stock"] = capture.dump(capture.run(fx, st_))
    Path(out_path).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    extra = [a.split("=", 1) for a in sys.argv[4:]]
    extra = [(k, v == "true" if v in ("true", "false") else v) for k, v in extra]
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "Table", extra)
