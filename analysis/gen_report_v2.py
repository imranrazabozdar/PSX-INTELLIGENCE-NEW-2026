#!/usr/bin/env python3
"""Generates the finer-grained per-day markdown tables, "what fired"
narrative sections, and the cross-stock first-occurrence comparison
table straight from premove_analysis.json / premove_data_raw.json --
no hand-typed numbers (the lesson from the first pass of this study:
hand-typed tables produced real transcription errors, caught only by
cross-checking against the raw JSON).

As of the indicator-expansion round, each stock gets TWO linked tables
(same date key): a CORE table (OHLC/candle/trend, same 18 columns as
before) and a VOLUME & FLOW table (MFI, OBV, A/D Line, ATR, VWAP,
Ichimoku cloud position, flow-divergence note) -- kept separate rather
than one very wide row, per this round's explicit instruction.

Prints each stock's section to stdout, in order, so it can be piped
straight into the report file's replacement/append points.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta

ANALYSIS_PATH = str(Path(__file__).parent / "premove_analysis.json")
RAW_PATH = str(Path(__file__).parent / "premove_data_raw.json")

analysis = json.load(open(ANALYSIS_PATH))
raw = json.load(open(RAW_PATH))
MOVE_START = analysis["move_start"]
SYMBOLS = ["AICL", "SHFA", "THCCL", "FNEL", "MDTL", "FPJM", "BNL", "DSIL", "SYM", "PREMA", "JSBL", "ILP"]

CORE_COLS = ["date", "open", "high", "low", "close", "volume", "vol_20d_avg", "vol_ratio",
             "candle_pattern", "pattern_criteria_met", "price_vs_ma20", "price_vs_ma50",
             "bb_position", "macd_hist", "macd_hist_direction", "ema20_vs_ema50", "rsi_14",
             "support_resistance_note"]
CORE_HEADERS = ["Date", "Open", "High", "Low", "Close", "Volume", "Vol 20d avg", "Vol ratio",
                "Candle pattern", "Pattern criteria met", "Price vs MA20", "Price vs MA50",
                "BB position", "MACD hist", "MACD dir", "EMA20 vs EMA50", "RSI(14)",
                "Support/resistance note"]

FLOW_COLS = ["date", "mfi_14", "obv", "ad_line", "atr_14", "vwap", "price_vs_vwap",
             "tenkan_sen", "kijun_sen", "ichimoku_note", "flow_divergence"]
FLOW_HEADERS = ["Date", "MFI(14)", "OBV", "A/D Line", "ATR(14)", "VWAP (window-anchored)",
                 "Price vs VWAP", "Tenkan-sen", "Kijun-sen", "Ichimoku cloud", "Flow divergence"]


INT_COLS = {"volume", "vol_20d_avg", "obv", "ad_line"}
RATIO_COLS = {"vol_ratio", "rsi_14", "mfi_14"}


def fmt(v, col=None):
    if v is None or v == "":
        return "—"
    if col in INT_COLS and isinstance(v, (int, float)):
        return f"{int(round(v)):,}"
    if col in RATIO_COLS and isinstance(v, (int, float)):
        return f"{v:.2f}"
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) >= 1 else f"{v:.4f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def day_offsets(dates, move_start):
    if move_start in dates:
        zero_idx = dates.index(move_start)
    else:
        later = [d for d in dates if d > move_start]
        zero_idx = dates.index(later[0]) if later else len(dates) - 1
    return {d: i - zero_idx for i, d in enumerate(dates)}


def weekday_gap_rows(rows, report_start, report_end):
    """Fill in any weekday (Mon-Fri) within [report_start, report_end]
    that has no trading-day row, as an explicit gap row (holiday/no
    trade), per the requirement that missing days appear, not get
    silently skipped. Weekends are not listed as gap rows since PSX
    never trades them."""
    present = {r["date"] for r in rows}
    start = datetime.strptime(report_start, "%Y-%m-%d")
    end = datetime.strptime(report_end, "%Y-%m-%d")
    gaps = []
    d = start
    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and ds not in present:
            gaps.append(ds)
        d += timedelta(days=1)
    return gaps


def _build_table(sym, cols, headers):
    rows = analysis["rows"][sym]
    report_start = analysis["crosses"][sym]["report_start"]
    report_end = analysis["crosses"][sym]["report_end"]
    gaps = weekday_gap_rows(rows, report_start, report_end)

    merged = [(r["date"], r) for r in rows] + [(g, None) for g in gaps]
    merged.sort(key=lambda x: x[0])

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "---|" * len(headers))
    for date, r in merged:
        if r is None:
            cells = [date] + ["—"] * (len(headers) - 2) + ["No PSX trading data (weekday, no trade recorded / holiday)"]
        else:
            cells = [fmt(r[c], c) for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_core_table(sym):
    return _build_table(sym, CORE_COLS, CORE_HEADERS)


def build_flow_table(sym):
    return _build_table(sym, FLOW_COLS, FLOW_HEADERS)


def what_fired(sym):
    rows = analysis["rows"][sym]
    dates = [r["date"] for r in rows]
    offs = day_offsets(dates, MOVE_START[sym])
    lines = []
    for r in rows:
        d = r["date"]
        off = offs[d]
        label = f"Day {off:+d}" if off != 0 else "Day 0"
        parts = []
        vr = r["vol_ratio"]
        parts.append(f"Volume {vr:.1f}x avg" if vr is not None else "Volume ratio n/a (insufficient history)")
        if r["candle_pattern"]:
            parts.append(f"{r['candle_pattern']} formed ({r['pattern_criteria_met']})")
        else:
            parts.append("no pattern")
        parts.append(f"BB {r['bb_position']}")
        parts.append(f"MACD hist {r['macd_hist']:.4f} ({r['macd_hist_direction']})" if r["macd_hist"] is not None else "MACD hist n/a")
        parts.append(r["ema20_vs_ema50"])
        if r["mfi_14"] is not None:
            parts.append(f"MFI {r['mfi_14']:.1f}")
        if r["price_vs_vwap"] and r["price_vs_vwap"] != "n/a":
            parts.append(f"price {r['price_vs_vwap']} VWAP")
        if r["ichimoku_note"] and "not yet formed" not in r["ichimoku_note"]:
            parts.append(r["ichimoku_note"])
        if r["flow_divergence"]:
            parts.append(r["flow_divergence"])
        if r["support_resistance_note"]:
            parts.append(r["support_resistance_note"])
        lines.append(f"{label} ({d}): " + ", ".join(parts))
    return "\n".join(lines)


def flow_divergence_days(sym):
    """All days in this stock's report window where OBV/A-D Line/price
    disagreed -- pulled out separately since this is exactly the "quiet
    accumulation/distribution" signal the richer indicator set was added
    to hunt for."""
    return [(r["date"], r["flow_divergence"]) for r in analysis["rows"][sym] if r["flow_divergence"]]


def cross_stock_table():
    occ = analysis["first_occurrences"]
    fields = [
        ("first_vol_2x", "First volume >2x avg"),
        ("first_pattern", "First candlestick pattern"),
        ("first_bb_oversold", "First BB oversold (<=-1.5 sigma)"),
        ("first_macd_sign_change", "First MACD hist sign change (neg->pos)"),
        ("first_ema_golden_cross", "First EMA20/50 golden cross"),
        ("breakout_day", "Breakout day (vol>=2.5x + up day)"),
    ]
    lines = ["| Signal | " + " | ".join(SYMBOLS) + " |", "|" + "---|" * (len(SYMBOLS) + 1)]
    for key, label in fields:
        cells = [label]
        for sym in SYMBOLS:
            v = occ[sym].get(key)
            if v is None:
                cells.append("not observed in window")
            else:
                off = v["day_offset"]
                cells.append(f"Day {off:+d} ({v['date']})" if off != 0 else f"Day 0 ({v['date']})")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    for sym in SYMBOLS:
        print(f"\n\n===== {sym} CORE TABLE =====\n")
        print(build_core_table(sym))
        print(f"\n\n===== {sym} FLOW TABLE =====\n")
        print(build_flow_table(sym))
        print(f"\n\n===== {sym} WHAT FIRED =====\n")
        print(what_fired(sym))
        print(f"\n\n===== {sym} FLOW DIVERGENCE DAYS =====\n")
        print(flow_divergence_days(sym))
    print("\n\n===== CROSS-STOCK TABLE =====\n")
    print(cross_stock_table())
