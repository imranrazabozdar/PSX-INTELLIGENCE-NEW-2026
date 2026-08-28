"""streamlit_app.py — PSX Intelligence, Streamlit front end.

Replaces the Android client. The architecture underneath is unchanged: this
talks to backend/app.py over plain HTTP, exactly like MainActivity.java did
(BACKEND="http://host:8000" -> GET /market, etc.) — same server, same
endpoints, same truth rule (nothing here invents a number the backend didn't
return). Set PSX_BACKEND to point at a non-local backend; defaults to the
usual `uvicorn app:app --port 8000` on localhost.

Run:
    cd backend && uvicorn app:app --reload
    streamlit run streamlit_app.py
"""

import os
import sys
import threading

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import time
import streamlit as st

BACKEND = os.getenv("PSX_BACKEND", "http://localhost:8000")
TIMEOUT = 45  # generous margin for cross-region latency to Turso (Streamlit
              # Cloud's runtime and this database aren't in the same region)

# Streamlit Community Cloud only runs one process per app, so there's no
# separate host for backend/app.py the way local dev (two terminals: uvicorn
# + streamlit run) or a split Render+Streamlit deploy has. PSX_EMBED_BACKEND=1
# makes this script start the FastAPI app itself, in a background thread
# inside the same process, before rendering anything. Local dev is unaffected
# unless this env var is explicitly set.
_EMBED_BACKEND = os.getenv("PSX_EMBED_BACKEND", "").lower() in ("1", "true", "yes")
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")


@st.cache_resource
def _ensure_embedded_backend():
    """Starts backend/app.py in a daemon thread exactly once per container
    process. @st.cache_resource (not a module-level flag) guarantees the
    once-per-process part — Streamlit reruns this script on every interaction
    and a plain global can't be trusted to survive that the same way."""
    if not _EMBED_BACKEND:
        return False
    # backend/app.py and its siblings resolve PSX_DB relative to the process
    # CWD at import time, which is the project root under `streamlit run`, not
    # backend/ — set it to an absolute path first so they agree with BACKEND's
    # "http://127.0.0.1:8000" pointing at this same embedded instance.
    os.environ.setdefault("PSX_DB", os.path.join(_BACKEND_DIR, "psx_v2.db"))
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
    import uvicorn
    import app as _backend_app  # backend/app.py; its own bare imports (psx_report,
                                 # scan_cache_engine, ...) resolve now that
                                 # _BACKEND_DIR is on sys.path

    threading.Thread(
        target=uvicorn.run,
        kwargs={"app": _backend_app.app, "host": "127.0.0.1", "port": 8000, "log_level": "warning"},
        daemon=True,
    ).start()
    for _ in range(30):
        try:
            if requests.get("http://127.0.0.1:8000/health", timeout=1).ok:
                break
        except Exception:
            pass
        time.sleep(1)
    return True


_ensure_embedded_backend()

st.set_page_config(page_title="PSX Intelligence", layout="wide",
                    initial_sidebar_state="collapsed",
                    page_icon="📈")

st.markdown("""
<style>
:root {
    --teal: #14D9B0; --teal-dark: #0FBF9A; --teal-light: rgba(20,217,176,0.12);
    --gold: #F0B429; --gold-dark: #D69E1F;
    --ink: #EDF1F4; --sub: #8B96A3; --line: rgba(255,255,255,0.08);
    --up: #22C55E; --up-bg: rgba(34,197,94,0.14); --down: #F0475B; --down-bg: rgba(240,71,91,0.14);
    --alert: #F0B429; --alert-bg: rgba(240,180,41,0.14);
    --info: #3B82F6; --info-bg: rgba(59,130,246,0.14);
    --bg: #0A0D11; --card-bg: rgba(255,255,255,0.045); --card-bg-solid: #12161C;
}
#MainMenu, footer, header {visibility: hidden;}
.stApp {background: radial-gradient(circle at 15% 0%, #101720 0%, #0A0D11 45%);}
.block-container {padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1240px;}
html, body, [class*="css"] {font-family: -apple-system, "Segoe UI", Inter, Roboto, sans-serif; color: var(--ink);}

/* ---- top brand bar ---- */
.psx-topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 2px 4px 18px; border-bottom: 1px solid var(--line); margin-bottom: 18px;
}
.psx-brand {display: flex; align-items: center; gap: 10px;}
.psx-brand .mark {
    width: 38px; height: 38px; border-radius: 10px;
    background: linear-gradient(135deg, var(--teal) 0%, #0B7A70 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; box-shadow: 0 4px 14px rgba(20,217,176,0.3);
}
.psx-brand .name {font-size: 1.32rem; font-weight: 800; color: var(--ink); letter-spacing: -0.02em;}
.psx-brand .tagline {font-size: 0.82rem; color: var(--sub); margin-top: -2px;}
.psx-live-badge {
    display: inline-flex; align-items: center; gap: 6px; font-size: 0.78rem;
    font-weight: 700; padding: 5px 12px; border-radius: 999px;
}
.psx-live-badge.on {background: var(--up-bg); color: var(--up);}
.psx-live-badge.off {background: var(--down-bg); color: var(--down);}
.psx-live-badge .dot {width: 7px; height: 7px; border-radius: 50%; background: currentColor;}

/* ---- glass card base (used by every card-like block below) ---- */
.psx-glass {
    background: var(--card-bg); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    border: 1px solid var(--line); border-radius: 16px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
}

/* ---- index pill strip ---- */
.psx-idx-row {display: flex; gap: 10px; overflow-x: auto; padding: 2px 2px 6px; margin-bottom: 18px;}
.psx-idx-pill {
    flex: 0 0 auto; min-width: 148px; padding: 12px 16px;
    background: var(--card-bg); backdrop-filter: blur(14px); border: 1px solid var(--line);
    border-radius: 14px; box-shadow: 0 4px 20px rgba(0,0,0,0.25);
}
.psx-idx-pill .lbl {font-size: 0.74rem; font-weight: 700; color: var(--sub); letter-spacing: 0.03em;}
.psx-idx-pill .val {font-size: 1.12rem; font-weight: 800; color: var(--ink); margin-top: 2px;}
.psx-idx-pill .chg {font-size: 0.8rem; font-weight: 700; margin-top: 2px;}
.psx-idx-pill .chg.up {color: var(--up);} .psx-idx-pill .chg.down {color: var(--down);}

/* ---- section headers ---- */
.psx-section-eyebrow {font-size: 0.74rem; font-weight: 800; color: var(--teal); letter-spacing: 0.08em; margin-bottom: 2px;}
.psx-section-title {font-size: 1.32rem; font-weight: 800; color: var(--ink); margin: 0 0 12px; letter-spacing: -0.01em;}

/* ---- generic card ---- */
.psx-card {
    padding: 16px 18px; margin-bottom: 10px;
    background: var(--card-bg); backdrop-filter: blur(14px); border: 1px solid var(--line);
    border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.25);
}

/* ---- mover row (gainers/losers/most active) ---- */
.psx-mover {
    display: flex; align-items: center; gap: 10px; padding: 9px 4px;
    border-bottom: 1px solid var(--line);
}
.psx-mover:last-child {border-bottom: none;}
.psx-avatar {
    width: 30px; height: 30px; border-radius: 50%; flex: 0 0 auto;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.72rem; font-weight: 800; color: #06231C; background: var(--teal);
}
.psx-mover .sym {font-weight: 700; color: var(--ink); font-size: 0.9rem;}
.psx-mover .co {font-size: 0.74rem; color: var(--sub);}
.psx-mover .right {margin-left: auto; text-align: right;}
.psx-mover .price {font-weight: 700; color: var(--ink); font-size: 0.88rem;}
.psx-mover .chg {font-size: 0.78rem; font-weight: 700;}
.psx-mover .chg.up {color: var(--up);} .psx-mover .chg.down {color: var(--down);}

/* ---- sector chip grid ---- */
.psx-chip-grid {display: flex; flex-wrap: wrap; gap: 8px;}
.psx-chip {
    border: 1px solid var(--line); background: var(--card-bg); border-radius: 10px;
    padding: 8px 12px; min-width: 150px; flex: 1 1 150px;
}
.psx-chip .name {font-size: 0.8rem; font-weight: 700; color: var(--ink);}
.psx-chip .stat {font-size: 0.74rem; color: var(--sub); margin-top: 2px;}
.psx-chip .stat b {font-weight: 700;}
.psx-chip .stat .up {color: var(--up);} .psx-chip .stat .down {color: var(--down);}

div[data-testid="stMetric"] {
    background: var(--card-bg); backdrop-filter: blur(14px); border: 1px solid var(--line);
    border-radius: 12px; padding: 14px 16px 10px;
}
div[data-testid="stMetricLabel"] {font-weight: 600; color: var(--sub);}
div[data-testid="stMetricValue"] {color: var(--ink);}

.stTabs [data-baseweb="tab-list"] {gap: 4px; border-bottom: 1px solid var(--line);}
.stTabs [data-baseweb="tab"] {
    height: 42px; border-radius: 10px 10px 0 0; padding: 0 18px;
    font-weight: 600; color: var(--sub);
}
.stTabs [aria-selected="true"] {color: var(--teal) !important; background: var(--teal-light);}

div[data-testid="stExpander"] {
    border: 1px solid var(--line); border-radius: 10px; box-shadow: none; background: var(--card-bg);
}
.stAlert {border-radius: 10px;}
[data-testid="stDataFrame"] {border-radius: 10px; overflow: hidden;}
div.stButton > button {
    border-radius: 10px; font-weight: 700; border: 1px solid var(--line);
    background: var(--card-bg); color: var(--ink);
}
div.stButton > button[kind="primary"] {background: var(--teal); border-color: var(--teal); color: #06231C;}

/* ---- real bordered cards (st.container(border=True)) ---- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 16px !important; border-color: var(--line) !important;
    background: var(--card-bg) !important; backdrop-filter: blur(14px);
    box-shadow: 0 4px 20px rgba(0,0,0,0.2);
}
.psx-panel-title {font-weight: 800; color: var(--ink); font-size: 0.98rem; margin-bottom: 8px;}

/* ---- stock hero (Stock Research tab) ---- */
.psx-stock-hero {
    display: flex; align-items: center; gap: 14px; padding: 16px 20px; margin-bottom: 14px;
    background: var(--card-bg); backdrop-filter: blur(14px); border: 1px solid var(--line);
    border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.25);
}
.psx-stock-hero .psx-avatar {width: 46px; height: 46px; font-size: 1rem;}
.psx-stock-hero .sym {font-size: 1.3rem; font-weight: 800; color: var(--ink);}
.psx-stock-hero .co {font-size: 0.86rem; color: var(--sub);}
.psx-stock-hero .right {margin-left: auto; text-align: right;}
.psx-stock-hero .price {font-size: 1.35rem; font-weight: 800; color: var(--ink);}
.psx-stock-hero .chg {font-size: 0.9rem; font-weight: 700;}
.psx-stock-hero .chg.up {color: var(--up);} .psx-stock-hero .chg.down {color: var(--down);}

/* ---- signal badge ---- */
.psx-badge {
    display: inline-block; font-size: 0.78rem; font-weight: 800; padding: 4px 12px;
    border-radius: 999px; letter-spacing: 0.02em;
}
.psx-badge.buy {background: var(--up-bg); color: var(--up);}
.psx-badge.sell {background: var(--down-bg); color: var(--down);}
.psx-badge.watch {background: var(--alert-bg); color: var(--alert);}
.psx-badge.neutral {background: rgba(255,255,255,0.06); color: var(--sub);}
.psx-badge.pending {background: rgba(255,255,255,0.04); color: #5B6673; font-style: italic;}
.psx-badge.grade-strong {background: var(--up-bg); color: var(--up); font-size: 1rem; padding: 6px 16px;}
.psx-badge.grade-weak {background: var(--down-bg); color: var(--down); font-size: 1rem; padding: 6px 16px;}
.psx-badge.grade-mid {background: var(--alert-bg); color: var(--alert); font-size: 1rem; padding: 6px 16px;}

/* ---- quick-pick symbol chips ---- */
div[data-testid="column"] div.stButton > button {padding: 4px 14px; height: 34px;}

/* ---- DSS evidence score gauge + confluence rows ---- */
.psx-score-hero {display: flex; align-items: center; gap: 24px; flex-wrap: wrap;}
.psx-score-num {font-size: 2.6rem; font-weight: 800; color: var(--ink); line-height: 1;}
.psx-score-sub {font-size: 0.8rem; color: var(--sub); margin-top: 4px;}
.psx-conf-row {
    display: flex; align-items: center; gap: 10px; padding: 8px 4px;
    border-bottom: 1px solid var(--line); font-size: 0.85rem;
}
.psx-conf-row:last-child {border-bottom: none;}
.psx-conf-row .bar-track {flex: 0 0 90px; height: 8px; border-radius: 4px; background: rgba(255,255,255,0.08); position: relative; overflow: hidden;}
.psx-conf-row .bar-fill {position: absolute; top: 0; bottom: 0; border-radius: 4px;}
.psx-conf-row .bar-fill.bullish {background: var(--up); left: 50%;}
.psx-conf-row .bar-fill.bearish {background: var(--down); right: 50%;}
.psx-conf-row .comp-name {flex: 1 1 auto; color: var(--ink); font-weight: 600;}
.psx-conf-row .comp-pts {flex: 0 0 56px; text-align: right; font-weight: 700;}
.psx-conf-row .comp-pts.up {color: var(--up);} .psx-conf-row .comp-pts.down {color: var(--down);}
.psx-conf-row .comp-detail {flex: 0 0 100%; font-size: 0.74rem; color: var(--sub); padding-left: 100px; margin-top: -2px;}
.psx-scenario-card {border-left: 4px solid var(--line); padding: 8px 0 8px 12px; margin-bottom: 8px;}
.psx-scenario-card.bullish {border-left-color: var(--up);}
.psx-scenario-card.bearish {border-left-color: var(--down);}
.psx-scenario-card.base {border-left-color: var(--sub);}

/* ---- range gauge (Day's Range / 52W / Invalidation-Target style slider) ---- */
.psx-gauge {position: relative; margin: 26px 0 10px;}
.psx-gauge .end-lbl {position: absolute; top: -24px; font-size: 0.7rem; font-weight: 700; color: var(--sub); line-height: 1.35;}
.psx-gauge .end-lbl b {display: block; font-size: 0.86rem;}
.psx-gauge .end-lbl.lo {left: 0;} .psx-gauge .end-lbl.lo b {color: var(--down);}
.psx-gauge .end-lbl.hi {right: 0; text-align: right;} .psx-gauge .end-lbl.hi b {color: var(--up);}
.psx-gauge .track {position: relative; height: 6px; border-radius: 3px;
    background: linear-gradient(90deg, var(--down) 0%, rgba(255,255,255,0.12) 50%, var(--up) 100%);}
.psx-gauge .dot {position: absolute; top: 50%; width: 14px; height: 14px; border-radius: 50%;
    background: var(--card-bg-solid); border: 3px solid var(--ink); transform: translate(-50%, -50%);
    box-shadow: 0 1px 4px rgba(0,0,0,0.5); z-index: 2;}
.psx-gauge .val-tag {position: absolute; bottom: 14px; transform: translateX(-50%);
    font-size: 0.74rem; font-weight: 800; color: var(--ink); background: var(--card-bg-solid);
    padding: 1px 7px; border-radius: 6px; border: 1px solid var(--line); white-space: nowrap; z-index: 3;}

/* ---- indicator verdict pill (RSI/MACD/Stoch-style colored badges) ---- */
.psx-ind-grid {display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0;}
.psx-ind-pill {display: flex; align-items: center; gap: 8px; padding: 7px 12px;
    border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid var(--line); flex: 1 1 140px;}
.psx-ind-pill .lbl {font-size: 0.7rem; color: var(--sub); font-weight: 700;}
.psx-ind-pill .val {font-size: 0.88rem; font-weight: 800; color: var(--ink); margin-left: auto;}
.psx-ind-pill .tag {font-size: 0.66rem; font-weight: 800; padding: 2px 8px; border-radius: 999px;}
.psx-ind-pill .tag.buy {background: var(--up-bg); color: var(--up);}
.psx-ind-pill .tag.sell {background: var(--down-bg); color: var(--down);}
.psx-ind-pill .tag.neutral {background: rgba(255,255,255,0.06); color: var(--sub);}

/* ---- circular progress ring gauge (Market Health / Evidence Score) ---- */
.psx-ring-wrap {display: flex; align-items: center; gap: 20px; flex-wrap: wrap;}
.psx-ring {
    position: relative; width: 108px; height: 108px; border-radius: 50%; flex: 0 0 auto;
    display: flex; align-items: center; justify-content: center;
}
.psx-ring::before {
    content: ""; position: absolute; inset: 0; border-radius: 50%;
    background: conic-gradient(var(--ring-color, var(--teal)) calc(var(--ring-pct, 50) * 1%), rgba(255,255,255,0.08) 0);
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 12px), #000 calc(100% - 11px));
    mask: radial-gradient(farthest-side, transparent calc(100% - 12px), #000 calc(100% - 11px));
}
.psx-ring .ring-num {font-size: 1.7rem; font-weight: 800; color: var(--ink); z-index: 1; line-height: 1;}
.psx-ring .ring-sub {position: absolute; bottom: -20px; font-size: 0.68rem; color: var(--sub); font-weight: 700; white-space: nowrap;}
.psx-ring-stats {display: flex; flex-direction: column; gap: 10px;}
.psx-ring-stat {display: flex; align-items: center; gap: 10px;}
.psx-ring-stat .k {font-size: 0.76rem; color: var(--sub); font-weight: 700; min-width: 70px;}
.psx-ring-stat .v {font-size: 0.92rem; font-weight: 800;}
.psx-ring-stat .v.up {color: var(--up);} .psx-ring-stat .v.down {color: var(--down);}
.psx-ring-stat .v.alert {color: var(--alert);} .psx-ring-stat .v.info {color: var(--info);}

/* ---- rich stock card (screener/watchlist-style, Investify layout) ---- */
.psx-scard {
    padding: 14px 16px; margin-bottom: 10px;
    background: var(--card-bg); backdrop-filter: blur(14px); border: 1px solid var(--line);
    border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    transition: transform 0.15s ease, border-color 0.15s ease;
}
.psx-scard:hover {border-color: rgba(20,217,176,0.35); transform: translateY(-1px);}
.psx-scard .row1 {display: flex; align-items: center; gap: 12px;}
.psx-scard .psx-avatar {width: 40px; height: 40px; font-size: 0.86rem;}
.psx-scard .mid {flex: 1 1 auto; min-width: 0;}
.psx-scard .sym {font-weight: 800; color: var(--ink); font-size: 1rem;}
.psx-scard .co {font-size: 0.76rem; color: var(--sub); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.psx-scard .right {text-align: right; flex: 0 0 auto;}
.psx-scard .price {font-weight: 800; color: var(--ink); font-size: 1.02rem;}
.psx-scard .chg {font-size: 0.82rem; font-weight: 700; margin-top: 2px;}
.psx-scard .chg.up {color: var(--up);} .psx-scard .chg.down {color: var(--down);}
.psx-scard .row2 {display: flex; gap: 18px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line);}
.psx-scard .stat {font-size: 0.72rem; color: var(--sub);}
.psx-scard .stat b {display: block; font-size: 0.82rem; color: var(--ink); font-weight: 700; margin-top: 1px;}
.psx-scard .score-block {margin-left: auto; text-align: right;}
.psx-scard .score-block .sk {font-size: 0.68rem; color: var(--sub); font-weight: 700; letter-spacing: 0.04em;}
.psx-scard .score-block .sv {font-size: 1.15rem; font-weight: 800; color: var(--ink);}
</style>
""", unsafe_allow_html=True)


def _signal_kind(text):
    t = (text or "").upper()
    if any(k in t for k in ("BUY", "BULL", "POSITIVE", "ACCUM")):
        return "buy"
    if any(k in t for k in ("SELL", "BEAR", "NEGATIVE", "DISTRIB")):
        return "sell"
    if any(k in t for k in ("WATCH", "TRIGGER", "NEUTRAL MIXED")):
        return "watch"
    return "neutral"


def _badge(text):
    if not text:
        return ""
    return f'<span class="psx-badge {_signal_kind(text)}">{text}</span>'


_DSS_BULLISH_BUCKETS = ("top_10_strongest_buy_setups", "top_10_accumulation_setups",
                        "top_10_reaccumulation_setups", "top_10_breakout_setups")
_DSS_BEARISH_BUCKETS = ("top_10_distribution_warnings", "top_10_markdown_avoid")


def _compute_consensus(sr, br):
    """Cross-reference DSS's named buckets against psx_brain's independent
    verdicts to find symbols BOTH engines read the same way (higher-conviction
    agreement) and symbols where they actively disagree (worth investigating,
    not a bug to hide). Deliberately does NOT blend their scores into one
    number — that would fabricate a combined metric neither engine's own
    methodology supports. Returns None if either scan isn't loaded yet."""
    if not (isinstance(sr, dict) and "top_10_strongest_buy_setups" in sr):
        return None
    if not (isinstance(br, dict) and isinstance(br.get("ranked"), list)):
        return None

    dss_bull, dss_bear = {}, {}
    for key in _DSS_BULLISH_BUCKETS:
        for item in sr.get(key, []):
            dss_bull[item["symbol"]] = item
    for key in _DSS_BEARISH_BUCKETS:
        for item in sr.get(key, []):
            dss_bear[item["symbol"]] = item

    brain_bull, brain_bear = {}, {}
    for item in br.get("ranked", []):
        sym = item.get("symbol")
        if not sym:
            continue
        cls = (item.get("class") or item.get("verdict") or "").lower()
        if "buy" in cls:
            brain_bull[sym] = item
        elif "sell" in cls or "avoid" in cls:
            brain_bear[sym] = item

    agree_buy = [(s, dss_bull[s], brain_bull[s]) for s in dss_bull if s in brain_bull]
    agree_avoid = [(s, dss_bear[s], brain_bear[s]) for s in dss_bear if s in brain_bear]
    disagree = ([(s, dss_bull[s], brain_bear[s], "DSS bullish · psx_brain bearish") for s in dss_bull if s in brain_bear]
                + [(s, dss_bear[s], brain_bull[s], "DSS bearish · psx_brain bullish") for s in dss_bear if s in brain_bull])
    return {"agree_buy": agree_buy, "agree_avoid": agree_avoid, "disagree": disagree}


def _initials(symbol):
    s = "".join(ch for ch in (symbol or "") if ch.isalpha())
    return (s[:2] or "??").upper()


def _fmt_vol(v):
    try:
        v = float(v)
    except Exception:
        return "—"
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:.0f}"


def _mover_html(rows, price_key="price", pct_key="pct", vol_key="volume", names=None):
    names = names or {}
    out = []
    for r in rows:
        sym = r.get("symbol", "")
        pct = r.get(pct_key)
        up = (pct or 0) >= 0
        cls = "up" if up else "down"
        arrow = "▲" if up else "▼"
        co = names.get(sym.upper(), "") if isinstance(sym, str) else ""
        out.append(
            f'<div class="psx-mover"><div class="psx-avatar">{_initials(sym)}</div>'
            f'<div><div class="sym">{sym}</div><div class="co">{co}</div></div>'
            f'<div class="right"><div class="price">{r.get(price_key, "—")}</div>'
            f'<div class="chg {cls}">{arrow} {abs(pct):.2f}%</div></div></div>'
            if pct is not None else
            f'<div class="psx-mover"><div class="psx-avatar">{_initials(sym)}</div>'
            f'<div><div class="sym">{sym}</div><div class="co">{co}</div></div></div>'
        )
    return "".join(out)


def _range_gauge_html(lo, hi, val, lo_label="Low", hi_label="High", fmt=None):
    """Visual range slider — Investify-style Day's Range/52-Week Range gauge:
    colored low/high endpoints, a dot at the current value's position, and a
    floating label showing the exact value above the dot. Returns "" (renders
    nothing) if any input isn't a real number, rather than a broken gauge."""
    try:
        lo_f, hi_f, val_f = float(lo), float(hi), float(val)
    except (TypeError, ValueError):
        return ""
    pct = 50.0 if hi_f == lo_f else max(2.0, min(98.0, (val_f - lo_f) / (hi_f - lo_f) * 100))
    fmt = fmt or (lambda x: f"{x:,.2f}")
    return (f'<div class="psx-gauge">'
            f'<div class="end-lbl lo">{lo_label}<b>{fmt(lo_f)}</b></div>'
            f'<div class="end-lbl hi">{hi_label}<b>{fmt(hi_f)}</b></div>'
            f'<div class="val-tag" style="left:{pct}%;">{fmt(val_f)}</div>'
            f'<div class="track"><div class="dot" style="left:{pct}%;"></div></div>'
            f'</div>')


def _rsi_verdict(rsi):
    if rsi is None: return "neutral", "—"
    if rsi >= 70: return "sell", "OVERBOUGHT"
    if rsi <= 30: return "buy", "OVERSOLD"
    return "neutral", "NEUTRAL"


def _macd_verdict(hist):
    if hist is None: return "neutral", "—"
    return ("buy", "BULLISH") if hist > 0 else ("sell", "BEARISH") if hist < 0 else ("neutral", "FLAT")


def _adx_verdict(adx):
    if adx is None: return "neutral", "—"
    return ("buy", "TRENDING") if adx >= 25 else ("neutral", "RANGE-BOUND")


def _ind_pill_html(label, value, kind, tag):
    val_str = f"{value:.1f}" if isinstance(value, (int, float)) else (value if value is not None else "—")
    return (f'<div class="psx-ind-pill"><span class="lbl">{label}</span>'
            f'<span class="val">{val_str}</span><span class="tag {kind}">{tag}</span></div>')


_RING_COLORS = {"up": "var(--up)", "down": "var(--down)", "alert": "var(--alert)",
                "info": "var(--info)", "teal": "var(--teal)"}


def _ring_html(value, max_value=100, sub_label="", color="teal", size=108):
    """Circular progress-ring gauge (Market Health / Evidence Score style) —
    pure CSS conic-gradient, no chart library needed. `value`/`max_value`
    drive the fill percentage; the number shown is `value` itself, not a
    rescaled percentage, so a caller passing an already-meaningful 0-100
    score (e.g. breadth_pct, evidence_score) shows that real number."""
    try:
        pct = max(0.0, min(100.0, float(value) / float(max_value) * 100))
        num_str = f"{value:.0f}" if isinstance(value, (int, float)) else str(value)
    except (TypeError, ValueError, ZeroDivisionError):
        pct, num_str = 0.0, "—"
    ring_color = _RING_COLORS.get(color, color)
    style = f"--ring-pct:{pct};--ring-color:{ring_color};width:{size}px;height:{size}px;"
    return (f'<div class="psx-ring" style="{style}"><span class="ring-num">{num_str}</span>'
            + (f'<span class="ring-sub">{sub_label}</span>' if sub_label else "") + '</div>')


def _scard_html(symbol, company, price, pct, hi=None, lo=None, volume=None,
                 score=None, score_label="SCORE", badge_text=None):
    """Rich Investify-style stock card: avatar, symbol/company, price/change,
    a High/Low/Volume stat row, and a score block with an optional signal
    badge — used for short, curated lists where the visual card treatment
    earns its keep (longer lists stay as st.dataframe for sort/search/scale,
    see the Screener tab's own comment on that tradeoff)."""
    cls = "up" if (pct or 0) >= 0 else "down"
    arrow = "▲" if (pct or 0) >= 0 else "▼"
    price_str = f"{price:,.2f}" if isinstance(price, (int, float)) else (price or "—")
    stats = []
    if hi is not None or lo is not None:
        hi_s = f"{hi:,.2f}" if isinstance(hi, (int, float)) else (hi or "—")
        lo_s = f"{lo:,.2f}" if isinstance(lo, (int, float)) else (lo or "—")
        stats.append(f'<div class="stat">High<b>{hi_s}</b></div>')
        stats.append(f'<div class="stat">Low<b>{lo_s}</b></div>')
    if volume is not None:
        stats.append(f'<div class="stat">Volume<b>{_fmt_vol(volume)}</b></div>')
    score_html = ""
    if score is not None:
        badge_html = f'<span class="psx-badge {_signal_kind(badge_text)}" style="margin-top:4px;display:inline-block;">{badge_text}</span>' if badge_text else ""
        score_html = (f'<div class="score-block"><div class="sk">{score_label}</div>'
                      f'<div class="sv">{score:.0f}</div>{badge_html}</div>')
    return (
        f'<div class="psx-scard"><div class="row1">'
        f'<div class="psx-avatar">{_initials(symbol)}</div>'
        f'<div class="mid"><div class="sym">{symbol}</div><div class="co">{company or ""}</div></div>'
        f'<div class="right"><div class="price">{price_str}</div>'
        f'<div class="chg {cls}">{arrow} {abs(pct or 0):.2f}%</div></div></div>'
        f'<div class="row2">{"".join(stats)}{score_html}</div></div>'
    )


_EVENT_MARKER_STYLE = {
    # accumulation — below the bar, teal/up-colored
    "PS": ("triangle-up", "#0D9488", "below"), "SC": ("triangle-up", "#0D9F6E", "below"),
    "AR": ("circle", "#64748B", "above"), "ST": ("circle", "#64748B", "below"),
    "SPRING": ("star", "#0D9F6E", "below"), "TEST": ("diamond", "#0D9F6E", "below"),
    "SOS": ("triangle-up", "#0D9F6E", "below"), "LPS": ("triangle-up", "#0D9488", "below"),
    # distribution — above the bar, red/down-colored
    "PSY": ("triangle-down", "#DC2626", "above"), "BC": ("triangle-down", "#B91C1C", "above"),
    "UT": ("star", "#DC2626", "above"), "SOW": ("triangle-down", "#B91C1C", "above"),
    "LPSY": ("triangle-down", "#DC2626", "above"),
}


def build_wyckoff_chart(ohlc, wyckoff_events=None, support=None, resistance=None, title=""):
    """Candlesticks + volume, with real Wyckoff event markers (from
    /wyckoff-events — SC/AR/ST/Spring/Test/SOS/LPS and PSY/BC/UT/SOW/LPSY)
    and the current support/resistance band overlaid. Dashboard Page 3 of
    the source framework — was entirely missing from the app before this."""
    df = pd.DataFrame(ohlc)
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["trade_date"])

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
                        vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df["date"], open=df["open"], high=df["high"],
                                  low=df["low"], close=df["close"], name="Price",
                                  increasing_line_color="#0D9F6E", decreasing_line_color="#DC2626"),
                  row=1, col=1)
    vol_colors = ["#0D9F6E" if c >= o else "#DC2626" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"], name="Volume", marker_color=vol_colors,
                         opacity=0.5), row=2, col=1)

    if support:
        fig.add_hline(y=support, line_dash="dot", line_color="#0D9F6E", opacity=0.6,
                      annotation_text=f"Support {support}", annotation_position="right", row=1, col=1)
    if resistance:
        fig.add_hline(y=resistance, line_dash="dot", line_color="#DC2626", opacity=0.6,
                      annotation_text=f"Resistance {resistance}", annotation_position="right", row=1, col=1)

    if wyckoff_events:
        for seq_key in ("accumulation", "distribution"):
            for ev in (wyckoff_events.get(seq_key, {}) or {}).get("events", []):
                code = ev.get("event")
                style = _EVENT_MARKER_STYLE.get(code)
                if not style or not ev.get("date"):
                    continue
                symbol, color, pos = style
                try:
                    ev_date = pd.to_datetime(ev["date"])
                    row = df[df["date"] == ev_date]
                    y = (row["low"].iloc[0] * 0.985 if pos == "below" else row["high"].iloc[0] * 1.015) \
                        if not row.empty else ev.get("price")
                except Exception:
                    y = ev.get("price")
                fig.add_trace(go.Scatter(x=[ev.get("date")], y=[y], mode="markers+text",
                                         marker=dict(symbol=symbol, size=13, color=color,
                                                     line=dict(width=1, color="white")),
                                         text=[code], textposition="top center" if pos == "above" else "bottom center",
                                         textfont=dict(size=10, color=color), name=ev.get("name", code),
                                         showlegend=False, hovertext=f"{ev.get('name')} — {ev.get('date')}"),
                              row=1, col=1)

    fig.update_layout(title=title, height=520, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis_rangeslider_visible=False, showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(size=11))
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    return fig


@st.cache_data(ttl=60)
def _get(path, **params):
    try:
        r = requests.get(f"{BACKEND}{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "reason": f"{type(e).__name__}: {e}"}


def _post(path, **params):
    try:
        r = requests.post(f"{BACKEND}{path}", params=params, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "reason": f"{type(e).__name__}: {e}"}


def _backend_up():
    try:
        r = requests.get(f"{BACKEND}/health", timeout=5)
        return r.ok
    except Exception:
        return False


@st.cache_data(ttl=6 * 3600)
def _company_names():
    """{SYMBOL: official name} from PSX's own directory, via the backend."""
    r = _get("/company-names")
    return {k: (v or {}).get("name") for k, v in r.get("names", {}).items()}


def _with_company(df, symbol_col="symbol"):
    """Insert a 'company' column right after the symbol column, using PSX's
    official name directory. Symbols with no match keep their bare ticker
    rather than a blank cell — never fabricates a name."""
    if symbol_col not in df.columns:
        return df
    names = _company_names()
    df = df.copy()
    company = df[symbol_col].map(lambda s: names.get(str(s).upper()) or "")
    pos = df.columns.get_loc(symbol_col) + 1
    df.insert(pos, "company", company)
    return df


_backend_ok = _backend_up()
st.markdown(
    '<div class="psx-topbar"><div class="psx-brand">'
    '<div class="mark">📈</div><div><div class="name">PSX Intelligence</div>'
    '<div class="tagline">Live technicals, fundamentals, driver-exposure & news for the Pakistan Stock Exchange</div>'
    '</div></div>'
    + (f'<div class="psx-live-badge on"><span class="dot"></span>LIVE · {BACKEND}</div>'
       if _backend_ok else
       f'<div class="psx-live-badge off"><span class="dot"></span>BACKEND UNREACHABLE</div>')
    + '</div>',
    unsafe_allow_html=True,
)

if not _backend_ok:
    st.error(
        f"Cannot reach the backend at {BACKEND}. Start it first:\n\n"
        "```bash\ncd backend && uvicorn app:app --reload\n```\n\n"
        "Or set PSX_BACKEND to point at a running instance."
    )
    st.stop()

# Filter widgets that mirror each other across tabs (min volume, scan limit,
# admin token) share one value each. Streamlit only honors a widget's `value=`
# argument the FIRST time its key is created — every rerun after that, the
# widget's own persisted state wins over `value=`, so a plain "read shared,
# write shared" pattern silently stops syncing after the first edit. The fix:
# on_change callbacks that, the instant one widget changes, overwrite every
# sibling widget's session_state entry directly — so next render each sibling
# reads its own now-updated key, no `value=` override needed.
_SYNC_GROUPS = {
    "min_volume": ["home_min_vol", "op_vol", "al_vol"],
    "limit": ["op_limit", "al_limit", "bf_limit"],
    "admin_token": ["scan_token", "al_token", "dssscan_token", "more_admin_token"],
}
_SYNC_DEFAULTS = {"home_min_vol": 50_000, "op_vol": 50_000, "al_vol": 50_000,
                  "op_limit": 50, "al_limit": 50, "bf_limit": 50,
                  "scan_token": "", "al_token": "", "dssscan_token": "", "more_admin_token": ""}
for _k, _v in _SYNC_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _sync_cb(group, source_key):
    def _cb():
        val = st.session_state[source_key]
        for k in _SYNC_GROUPS[group]:
            st.session_state[k] = val
    return _cb


def _admin_token_input(key):
    """Admin token field synced across every tab that needs one (Screener scan,
    Pulse alerts, More backfill-bulk) — enter it once, it's filled in everywhere,
    since PSX_ADMIN_TOKEN is one value per backend, not per-panel."""
    return st.text_input("Admin token (if set on backend)", type="password", key=key,
                          on_change=_sync_cb("admin_token", key))


tab_home, tab_screener, tab_pulse, tab_dss, tab_more = st.tabs(
    ["🏠 Home", "🔍 Screener", "📰 Pulse", "🎯 Stock Research", "⚙️ More"]
)

# ---------------------------------------------------------------- Home ----
with tab_home:
    lm = _get("/live-market")
    idx = (lm.get("indices") or {}) if isinstance(lm, dict) else {}
    if idx:
        pills = []
        for name, d in idx.items():
            chg = d.get("chg_pct")
            close_v = d.get("close")
            close_str = f"{close_v:,.2f}" if isinstance(close_v, (int, float)) else "—"
            pts = None
            if isinstance(close_v, (int, float)) and chg is not None:
                pts = close_v - close_v / (1 + chg / 100)
            cls = "up" if (chg or 0) >= 0 else "down"
            arrow = "▲" if (chg or 0) >= 0 else "▼"
            pts_str = f"{pts:+,.1f} " if pts is not None else ""
            pills.append(
                f'<div class="psx-idx-pill"><div class="lbl">{name}</div>'
                f'<div class="val">{close_str}</div>'
                f'<div class="chg {cls}">{arrow} {pts_str}({abs(chg):.2f}%)</div></div>'
                if chg is not None else
                f'<div class="psx-idx-pill"><div class="lbl">{name}</div>'
                f'<div class="val">{close_str}</div></div>'
            )
        st.markdown(f'<div class="psx-idx-row">{"".join(pills)}</div>', unsafe_allow_html=True)

    st.markdown('<div class="psx-section-eyebrow">MARKET COMMAND CENTER</div>'
                '<div class="psx-section-title">Regime, Momentum, Volatility & Sector Leadership</div>',
                unsafe_allow_html=True)
    with st.container(border=True):
        mcc = _get("/market-command-center")
        if mcc.get("status") == "ok":
            mr = mcc.get("market_regime") or {}
            vol = mcc.get("kse100_volatility_regime") or {}
            regime_label = mr.get("label", "—")
            trend_word = ("Bullish" if "RISK-ON" in regime_label.upper() else
                          "Bearish" if "RISK-OFF" in regime_label.upper() else "Mixed")
            trend_color = "up" if trend_word == "Bullish" else "down" if trend_word == "Bearish" else "alert"
            risk_word = vol.get("regime", "—") if vol.get("status") == "ok" else "—"
            risk_color = ("down" if risk_word in ("High", "Very High") else
                          "alert" if risk_word == "Medium" else "up" if risk_word in ("Low", "Very Low") else "info")
            breadth = mr.get("breadth_pct")
            ring_color = "up" if (breadth or 0) >= 55 else "down" if (breadth or 0) <= 45 else "alert"
            st.markdown(
                '<div class="psx-ring-wrap">'
                + _ring_html(breadth, max_value=100, sub_label="MARKET BREADTH", color=ring_color, size=116)
                + '<div class="psx-ring-stats">'
                + f'<div class="psx-ring-stat"><span class="k">Trend</span><span class="v {trend_color}">{trend_word} ({regime_label})</span></div>'
                + f'<div class="psx-ring-stat"><span class="k">Risk</span><span class="v {risk_color}">{risk_word} volatility</span></div>'
                + f'<div class="psx-ring-stat"><span class="k">Momentum</span><span class="v {"up" if (mr.get("avg_change_pct") or 0) >= 0 else "down"}">{mr.get("avg_change_pct", "—")}% avg chg</span></div>'
                + '</div></div>',
                unsafe_allow_html=True)
            st.caption("Market Breadth Score = % of eligible stocks advancing today — a real, direct measure "
                       "of participation, not a fabricated composite. Trend/Risk are the same regime and "
                       "KSE-100 volatility classification used everywhere else in this app.")
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown("**🟢 Strongest sectors**")
                for s in mcc.get("top_sectors", []):
                    st.caption(f"{s['sector']} — strength {s['strength']}, breadth {s['breadth_pct']}%, "
                               f"avg chg {s['avg_change_pct']:+.2f}%")
            with sc2:
                st.markdown("**🔴 Weakest sectors**")
                for s in mcc.get("bottom_sectors", []):
                    st.caption(f"{s['sector']} — strength {s['strength']}, breadth {s['breadth_pct']}%, "
                               f"avg chg {s['avg_change_pct']:+.2f}%")
        else:
            st.caption("Market command center unavailable.")

    names = _company_names()

    st.markdown('<div class="psx-section-eyebrow">MARKET SNAPSHOT</div>'
                '<div class="psx-section-title">PSX Market Overview</div>', unsafe_allow_html=True)
    f1, f2 = st.columns([1, 2])
    with f1:
        min_vol = st.number_input("Min volume", step=10_000, key="home_min_vol",
                                   on_change=_sync_cb("min_volume", "home_min_vol"))
    with f2:
        search = st.text_input("🔍 Search symbol or company", placeholder="e.g. OGDC, Oil & Gas...")
    rows = _get("/market", min_volume=min_vol)

    if isinstance(rows, list) and rows:
        df = pd.DataFrame(rows)

        b = _get("/breadth")
        if isinstance(b, dict) and "advancing" in b:
            m1, m2, m3 = st.columns(3)
            m1.metric("Advancing", b["advancing"])
            m2.metric("Declining", b["declining"])
            m3.metric("Breadth %", f"{b['breadth_pct']}%")

        gc, lc, ac = st.columns(3)
        by_pct = df.dropna(subset=["pct"]).sort_values("pct", ascending=False) if "pct" in df.columns else df
        with gc:
            st.markdown('<div class="psx-card"><b>⚡ Gainers</b>' +
                        _mover_html(by_pct.head(6).to_dict("records"), names=names) +
                        '</div>', unsafe_allow_html=True)
        with lc:
            st.markdown('<div class="psx-card"><b>📉 Losers</b>' +
                        _mover_html(by_pct.tail(6).sort_values("pct").to_dict("records"), names=names) +
                        '</div>', unsafe_allow_html=True)
        with ac:
            by_vol = df.sort_values("volume", ascending=False) if "volume" in df.columns else df
            st.markdown('<div class="psx-card"><b>🔥 Most Active</b>' +
                        _mover_html(by_vol.head(6).to_dict("records"), names=names) +
                        '</div>', unsafe_allow_html=True)

        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        view = df.copy()
        if search:
            s = search.strip().lower()
            nm = view["symbol"].map(lambda x: names.get(str(x).upper(), ""))
            view = view[view["symbol"].str.lower().str.contains(s, na=False) |
                        nm.str.lower().str.contains(s, na=False)]
        cols = ["symbol", "name", "sector", "price", "pct", "volume", "score", "setup"]
        home_df = (view[[c for c in cols if c in view.columns]]
                   .rename(columns={"name": "company", "pct": "chg %"})
                   .sort_values("chg %", ascending=False))
        home_col_cfg = {"score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
                        "price": st.column_config.NumberColumn("Price", format="%.2f"),
                        "chg %": st.column_config.NumberColumn("Chg %", format="%.2f%%"),
                        "volume": st.column_config.NumberColumn("Volume", format="compact")}
        st.dataframe(
            home_df, use_container_width=True, height=420, hide_index=True,
            column_config={k: v for k, v in home_col_cfg.items() if k in home_df.columns},
        )
    else:
        # rows can be a non-list error dict OR a genuinely empty list (e.g. a
        # min-volume filter with no matches) — only dicts have .get().
        reason = rows.get("reason") if isinstance(rows, dict) else None
        st.warning(reason or "No market data returned. Is the backend reachable and PSX portal up?")

    st.markdown('<div class="psx-section-eyebrow">PSX SECTORS</div>'
                '<div class="psx-section-title">Sector Performance</div>', unsafe_allow_html=True)
    sec = _get("/sectors")
    if isinstance(sec, list) and sec:
        chips = []
        for s in sorted(sec, key=lambda x: -(x.get("avg_pct") or 0)):
            pct = s.get("avg_pct")
            cls = "up" if (pct or 0) >= 0 else "down"
            chips.append(
                f'<div class="psx-chip"><div class="name">{s.get("sector", "—")}</div>'
                f'<div class="stat">{s.get("n", 0)} stocks · vol {_fmt_vol(s.get("volume"))} · '
                f'<b class="{cls}">{pct:+.2f}%</b></div></div>'
            )
        st.markdown(f'<div class="psx-chip-grid">{"".join(chips)}</div>', unsafe_allow_html=True)

# ----------------------------------------------------------- Screener ----
with tab_screener:
    st.markdown('<div class="psx-section-eyebrow">SCREENER</div>'
                '<div class="psx-section-title">Whole-Market Rankings</div>', unsafe_allow_html=True)
    st.caption("Three independent engines rank the whole market differently — shown here in order of rigor, "
                "not just personal preference. The **Decision Support Scan** is the primary/default ranking "
                "(same confluence-matrix + backtested-stats engine as a stock's own Stock Research page). "
                "The other two are genuinely different methodologies, useful as a cross-check, not near-duplicates "
                "of each other or of the primary ranking. Click any row to open that symbol in the Stock Research "
                "tab. (The Home tab's table uses a much simpler price/volume heuristic — not a fourth ranking, "
                "just a quick-glance tag.)")

    op_min_vol = st.number_input("Min volume (applies to all three below)", step=10_000, key="op_vol",
                                  on_change=_sync_cb("min_volume", "op_vol"))

    # Pre-fetch both scans (cheap — cached client- and server-side) so the
    # consensus section below can cross-reference them before either
    # section's own detailed UI renders further down this tab.
    if "dss_scan_result" not in st.session_state:
        st.session_state["dss_scan_result"] = _get("/dss-scan")
    if "brain_scan_result" not in st.session_state:
        st.session_state["brain_scan_result"] = _get("/scan")
    _sr_pre = st.session_state.get("dss_scan_result")
    _br_pre = st.session_state.get("brain_scan_result")

    consensus = _compute_consensus(_sr_pre, _br_pre)
    st.markdown('<div class="psx-section-eyebrow">CONSENSUS</div>'
                '<div class="psx-section-title">🤝 Where The Two Independent Engines Agree</div>',
                unsafe_allow_html=True)
    with st.container(border=True):
        st.caption("DSS (Wyckoff + regime + backtested stats) and psx_brain (trend/momentum trade-plan "
                   "verdicts) are built independently and can legitimately disagree — this cross-references "
                   "their named buy/avoid buckets rather than blending scores into one fabricated number. "
                   "Agreement here is a stronger signal than either engine alone; disagreement is worth "
                   "investigating, not a bug.")
        if consensus is None:
            st.info("Waiting on both scans below to finish loading — consensus appears once the Primary "
                    "Ranking and Whole-Book Scan sections have real data.")
        else:
            if consensus["agree_buy"]:
                st.markdown(f"**✅ Both engines bullish on these ({len(consensus['agree_buy'])})**")
                rows = [{"symbol": s, "DSS action": d.get("action"), "DSS score": d.get("score"),
                        "psx_brain verdict": b.get("verdict"), "psx_brain confidence": b.get("confidence")}
                        for s, d, b in consensus["agree_buy"]]
                cdf = pd.DataFrame(rows)
                csel = st.dataframe(cdf, use_container_width=True, hide_index=True,
                                    on_select="rerun", selection_mode="single-row", key="consensus_buy_table",
                                    column_config={
                                        "DSS score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                                        "psx_brain confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f")})
                crows = csel.selection.rows if csel and csel.selection else []
                if crows:
                    st.session_state.research_symbol = cdf.iloc[crows[0]]["symbol"]
                    st.toast(f"Opened {st.session_state.research_symbol} in Stock Research →", icon="🎯")
            else:
                st.info("No symbols right now where both engines are independently bullish — an honest "
                        "result, not a bug. Check back after the next auto-refresh.")

            if consensus["agree_avoid"]:
                st.markdown(f"**🔴 Both engines bearish on these ({len(consensus['agree_avoid'])})**")
                rows = [{"symbol": s, "DSS action": d.get("action"), "DSS score": d.get("score"),
                        "psx_brain verdict": b.get("verdict")} for s, d, b in consensus["agree_avoid"]]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            if consensus["disagree"]:
                with st.expander(f"⚠️ Where they disagree ({len(consensus['disagree'])}) — shown, not hidden"):
                    rows = [{"symbol": s, "DSS reads": f"{d.get('action')} (score {d.get('score')})",
                            "psx_brain reads": f"{b.get('verdict')} (confidence {b.get('confidence')})",
                            "note": note} for s, d, b, note in consensus["disagree"]]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown('<div class="psx-section-eyebrow">PRIMARY RANKING</div>'
                '<div class="psx-section-title">🎯 Decision Support Market Scanner</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.caption("Runs the full Decision Support System (confluence matrix, evidence score, Wyckoff, "
                   "candlesticks, real backtest stats) over every symbol with stored true-OHLC, then ranks "
                   "into named buckets. Same engine each stock's own Stock Research page uses. The backend "
                   "auto-refreshes this in the background, so loading this tab is instant — prices are "
                   "patched live on top of the cached analysis.")
        status = _get("/dss-scan/status")
        if status.get("status") == "ok":
            age_min = round(status["age_seconds"] / 60, 1)
            running_note = " · a background refresh is running right now" if status.get("job_running") else ""
            st.caption(f"📦 Cached scan: {status['scanned']} symbols · last full analysis {age_min} min ago "
                       f"(auto-refreshes every {round(status['max_age_seconds']/60)} min) · "
                       f"prices refreshed live{running_note}.")
        elif status.get("status") == "never_run":
            st.info("No scan cached yet — the backend runs one automatically shortly after startup "
                    "(can take a few minutes for the full backfilled universe), or force one now below.")
        scan_token = _admin_token_input("dssscan_token")
        force_col1, force_col2 = st.columns([1, 3])
        with force_col1:
            force_rescan = st.button("Refresh in background", type="secondary")
        # The backend ALWAYS returns real data instantly if any exists — a full
        # universe scan can take several minutes, so this never blocks the page
        # on it. force just kicks off a background recompute; the response you
        # get back right after clicking is still last known good data, and the
        # fresh result shows up next time this section reloads once it lands.
        params = {}
        if force_rescan:
            params["force"] = "true"
            if scan_token:
                params["token"] = scan_token
            kickoff = requests.get(f"{BACKEND}/dss-scan", params=params, timeout=30).json()
            if kickoff.get("status") == "forbidden":
                st.error(kickoff.get("reason"))
            else:
                st.session_state["dss_scan_result"] = kickoff
                if kickoff.get("_background_refresh_running"):
                    st.toast("Full recompute started in the background — showing last known data below; "
                             "reload this section in a few minutes for the fresh scan.", icon="🔄")
        elif "dss_scan_result" not in st.session_state:
            st.session_state["dss_scan_result"] = _get("/dss-scan")
        sr = st.session_state.get("dss_scan_result")
        if sr and "top_10_strongest_buy_setups" in sr:
            if sr.get("_background_refresh_running"):
                st.caption("🔄 A background refresh is in progress — the data below is the last completed scan.")
            st.caption(f"Scanned {sr.get('scanned')} symbols · market regime "
                       f"{(sr.get('market_regime') or {}).get('label','—')}")
            buckets = [
                ("🟢 Top 10 Strongest Buy Setups", "top_10_strongest_buy_setups"),
                ("🔵 Top 10 Accumulation Setups", "top_10_accumulation_setups"),
                ("🔷 Top 10 Reaccumulation Setups", "top_10_reaccumulation_setups"),
                ("🚀 Top 10 Breakout Setups", "top_10_breakout_setups"),
                ("👀 Top 10 Early Reversal Watchlist", "top_10_early_reversal_watchlist"),
                ("💪 Top 10 Strongest Relative-Strength Stocks", "top_10_strongest_relative_strength"),
                ("🟠 Top 10 Distribution Warnings", "top_10_distribution_warnings"),
                ("🔴 Top 10 Markdown / Avoid Stocks", "top_10_markdown_avoid"),
            ]
            cols_per_row = ["symbol", "name", "sector", "price", "pct", "phase", "signal_stage", "score",
                            "grade", "action", "rs_vs_index", "rs_class", "entry", "stop", "target", "rr"]
            for label, key in buckets:
                items = sr.get(key, [])
                if not items:
                    continue
                st.markdown(f"**{label}** ({len(items)})")
                df_ = pd.DataFrame(items)
                shown_cols = [c for c in cols_per_row if c in df_.columns]
                col_cfg = {"score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
                           "price": st.column_config.NumberColumn("Price", format="%.2f"),
                           "pct": st.column_config.NumberColumn("Chg %", format="%.2f%%")}
                dsel = st.dataframe(df_[shown_cols],
                            use_container_width=True, hide_index=True, height=min(38 * (len(items) + 1) + 3, 420),
                            on_select="rerun", selection_mode="single-row", key=f"dss_bucket_{key}",
                            column_config={k: v for k, v in col_cfg.items() if k in shown_cols})
                drows = dsel.selection.rows if dsel and dsel.selection else []
                if drows:
                    st.session_state.research_symbol = df_.iloc[drows[0]]["symbol"]
                    st.toast(f"Opened {st.session_state.research_symbol} in Stock Research →", icon="🎯")

    st.markdown('<div class="psx-section-eyebrow">SECOND OPINION</div>'
                '<div class="psx-section-title">🧠 Conviction Ranking</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.caption("A different methodology: liquidity/momentum/trend/structure/Wyckoff/fundamentals blend "
                   "over every liquid symbol in the live market (not just the backfilled-history subset the "
                   "primary ranking above uses). Worth checking when it agrees or disagrees with the primary "
                   "ranking — it isn't a subset or a looser version of it.")
        ranked = _get("/ranked-opportunities", limit=40)
        if isinstance(ranked, list) and ranked:
            names_ = _company_names()
            rdf = pd.DataFrame(ranked)
            rdf.insert(1, "company", rdf["symbol"].map(lambda s: names_.get(str(s).upper(), "")))
            display_cols = [c for c in ["symbol", "company", "sector", "price", "pct", "score", "label"]
                            if c in rdf.columns]
            conv_col_cfg = {"score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
                            "price": st.column_config.NumberColumn("Price", format="%.2f"),
                            "pct": st.column_config.NumberColumn("Chg %", format="%.2f%%")}
            sel = st.dataframe(rdf[display_cols], use_container_width=True, hide_index=True, height=380,
                               on_select="rerun", selection_mode="single-row", key="conviction_rank_table",
                               column_config={k: v for k, v in conv_col_cfg.items() if k in display_cols})
            rows_sel = sel.selection.rows if sel and sel.selection else []
            if rows_sel:
                st.session_state.research_symbol = rdf.iloc[rows_sel[0]]["symbol"]
                st.toast(f"Opened {st.session_state.research_symbol} in Stock Research →", icon="🎯")
        else:
            st.info("Conviction ranking unavailable.")

    st.markdown('<div class="psx-section-eyebrow">SECOND OPINION</div>'
                '<div class="psx-section-title">📈 Whole-Book Scan (psx_brain)</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.caption("A third, independent methodology: full-indicator trade-plan verdicts (BUY/WAIT/SELL with "
                   "entry/stop/target) over the most liquid names. Expensive — fetches OHLCV + runs the full "
                   "indicator engine per symbol. Requires PSX_ADMIN_TOKEN on the backend unless called from "
                   "localhost.")
        admin_token = _admin_token_input("scan_token")
        is_default_scan = op_min_vol == _SYNC_DEFAULTS.get("home_min_vol", 50_000)
        if st.button("Run scan", type="primary"):
            params = {"min_volume": op_min_vol, "limit": 40, "top": 20}
            if admin_token:
                params["token"] = admin_token
            # With min_volume/limit/top at their defaults this returns real
            # cached data instantly (and refreshes in the background if
            # stale) — never blocks the page. A non-default min_volume runs
            # synchronously and can take a little while, hence the spinner.
            with st.spinner("Scanning..."):
                r = requests.get(f"{BACKEND}/scan", params=params, timeout=180).json()
            if is_default_scan and r.get("ranked"):
                st.session_state["brain_scan_result"] = r
        else:
            # No click this run — show whatever was already pre-fetched at
            # the top of this tab (for the consensus section) rather than an
            # empty panel until someone clicks. Non-default min_volume still
            # needs an explicit click since it's not the pre-fetched default.
            r = _br_pre if is_default_scan else None
        if r is None:
            st.caption("Adjust the min-volume filter above, then click **Run scan** for this custom view.")
        elif r.get("status") == "forbidden":
            st.error(r.get("reason"))
        elif r.get("status") == "running":
            st.info(r.get("reason", "First scan is running in the background — check back shortly."))
        elif r.get("ranked"):
            if r.get("_background_refresh_running"):
                st.caption("🔄 A background refresh is in progress — showing the last completed scan.")
            st.text(r.get("commentary", ""))
            bdf = _with_company(pd.DataFrame(r["ranked"]))
            brain_col_cfg = {"confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100, format="%.0f"),
                             "price": st.column_config.NumberColumn("Price", format="%.2f")}
            bsel = st.dataframe(bdf, use_container_width=True, hide_index=True, height=420,
                                on_select="rerun", selection_mode="single-row", key="brain_scan_table",
                                column_config={k: v for k, v in brain_col_cfg.items() if k in bdf.columns})
            brows = bsel.selection.rows if bsel and bsel.selection else []
            if brows and "symbol" in bdf.columns:
                st.session_state.research_symbol = bdf.iloc[brows[0]]["symbol"]
                st.toast(f"Opened {st.session_state.research_symbol} in Stock Research →", icon="🎯")
            if r.get("skipped"):
                with st.expander(f"Skipped ({len(r['skipped'])})"):
                    st.json(r["skipped"])
        else:
            st.warning(r.get("reason", "Scan returned nothing."))

# --------------------------------------------------------------- Pulse ----
with tab_pulse:
    st.markdown('<div class="psx-section-eyebrow">MARKET PULSE</div>'
                '<div class="psx-section-title">News, Sector Impact & Alerts</div>', unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown('<div class="psx-panel-title">📰 News Feed</div>', unsafe_allow_html=True)
        feed = _get("/news-feed")
        if feed.get("status") == "ok":
            st.caption(f"As of {feed.get('as_of')} · age {feed.get('age_minutes')} min · "
                       f"{feed.get('symbols_with_news')} symbols with news")
            if feed.get("stocks"):
                st.dataframe(
                    pd.DataFrame(feed["stocks"])[
                        ["symbol", "sector", "price", "observed_move_pct", "direction",
                         "materiality", "confidence", "agreement", "summary"]
                    ],
                    use_container_width=True, height=420,
                )
            if feed.get("macro_headlines"):
                with st.expander(f"All macro headlines ({len(feed['macro_headlines'])})"):
                    for m in feed["macro_headlines"]:
                        themes = ", ".join(t["theme"] for t in m.get("themes", []))
                        st.markdown(f"**{m.get('title')}**" + (f"  \n_{themes}_" if themes else ""))
        else:
            st.warning(feed.get("reason") or feed.get("note") or "News feed unavailable.")

    themed = [m for m in (feed.get("macro_headlines", []) if isinstance(feed, dict) else []) if m.get("themes")]
    if themed:
        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">📊 Sector Impact</div>'
                        '<div style="font-size:0.82rem;color:var(--sub);margin-bottom:10px;">'
                        'Macro headlines mapped to sectors conventionally sensitive to them — '
                        'conventional analyst relationships (e.g. oil up → cement/transport cost '
                        'pressure), NOT measured against PSX history. Directional guidance for '
                        'where to look, never a score.</div>', unsafe_allow_html=True)
            for m in themed:
                for t in m["themes"]:
                    chips = "".join(f'<span class="psx-badge watch" style="margin:2px 4px 2px 0">→ {s}</span>'
                                     for s in t.get("sectors_conventionally_sensitive", []))
                    st.markdown(f'<div style="margin-bottom:10px;"><b>{m.get("title")}</b><br>{chips}</div>',
                                unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown('<div class="psx-panel-title">🔔 Volume & Accumulation/Distribution Alerts</div>',
                    unsafe_allow_html=True)
        st.caption("Rebuilt on data this app already owns (PSX portal + technical "
                   "engine's CMF/OBV/avg-volume) — no longer depends on the now-gated "
                   "psxterminal.com feed. ~5min delayed, not tick-level. Auto-refreshes in the "
                   "background every 30 min for the default thresholds below — no click needed.")

        _ALERT_LABEL = {"ACCUMULATION": "POSITIVE MONEY-FLOW PRESSURE", "DISTRIBUTION": "NEGATIVE MONEY-FLOW PRESSURE",
                        "VOLUME_SURGE": "VOLUME SURGE"}

        def _render_alerts(r):
            if r.get("alerts"):
                st.caption(f"Scanned {r['scanned']} · flagged {r['flagged']} · "
                           f"{r['skipped_no_data']} skipped (no backfilled OHLC)"
                           + (f" · cached {r['_cache_age_seconds']}s ago" if "_cache_age_seconds" in r else ""))
                st.caption("Labeled by what they actually measure — CMF/OBV money-flow proxies, not "
                           "confirmed Wyckoff accumulation/distribution. See a stock's Decision Support "
                           "tab for whether Wyckoff structure independently agrees.")
                rows_html = []
                for a in r["alerts"]:
                    cls = "up" if (a["pct"] or 0) >= 0 else "down"
                    arrow = "▲" if (a["pct"] or 0) >= 0 else "▼"
                    badges = " ".join(_badge(_ALERT_LABEL.get(x["type"], x["type"])) for x in a["alerts"])
                    cmf_val = a.get("cmf")
                    cmf_str = f"{cmf_val:+.2f}" if isinstance(cmf_val, (int, float)) else "—"
                    rows_html.append(
                        f'<div class="psx-mover"><div class="psx-avatar">{_initials(a["symbol"])}</div>'
                        f'<div><div class="sym">{a["symbol"]} &nbsp;{badges}</div>'
                        f'<div class="co">{a.get("name") or ""} · {a["vol_x_avg"]}x avg vol · CMF {cmf_str}</div></div>'
                        f'<div class="right"><div class="price">{a["price"]}</div>'
                        f'<div class="chg {cls}">{arrow} {abs(a["pct"]):.2f}%</div></div></div>'
                    )
                st.markdown(f'<div class="psx-card">{"".join(rows_html)}</div>', unsafe_allow_html=True)
                st.caption(r.get("note", ""))
            else:
                st.info(f"Scanned {r.get('scanned', 0)} symbols — nothing crossed "
                        "the surge/accumulation thresholds right now.")

        if "alerts_result" not in st.session_state:
            st.session_state["alerts_result"] = _get("/alerts")
        _render_alerts(st.session_state["alerts_result"])

        with st.expander("Custom thresholds (runs live, not cached)"):
            a1, a2, a3 = st.columns(3)
            with a1:
                al_min_vol = st.number_input("Min volume", step=50_000, key="al_vol",
                                              on_change=_sync_cb("min_volume", "al_vol"))
            with a2:
                al_surge_x = st.number_input("Surge threshold (x avg)", value=2.0, step=0.5, key="al_surge")
            with a3:
                al_limit = st.number_input("Scan top-N liquid", step=10, key="al_limit",
                                            on_change=_sync_cb("limit", "al_limit"))
            al_token = _admin_token_input("al_token")
            if st.button("Run custom alert scan", type="primary"):
                params = {"min_volume": al_min_vol, "volume_surge_x": al_surge_x, "limit": al_limit}
                if al_token:
                    params["token"] = al_token
                with st.spinner("Scanning for volume surges and accumulation/distribution..."):
                    r = requests.get(f"{BACKEND}/alerts", params=params, timeout=180).json()
                if r.get("status") == "forbidden":
                    st.error(r.get("reason"))
                else:
                    _render_alerts(r)

    with st.container(border=True):
        st.markdown('<div class="psx-panel-title">📡 Live Tape (psxterminal.com, supplementary)</div>',
                    unsafe_allow_html=True)
        tape = _get("/live-tape")
        if tape.get("status") == "ok":
            st.text(tape.get("summary", ""))
            if tape.get("alerts"):
                st.dataframe(pd.DataFrame(tape["alerts"]), use_container_width=True)
        else:
            st.info("Not available — psxterminal.com stopped publishing per-stock "
                    "live data (the endpoint now returns 403/404, confirmed by "
                    "direct testing, not a bug here). See the Live indices section "
                    "on the More tab for what's still genuinely live from that "
                    "source (KSE100/KMI30/KSE30/ALLSHR).")

# --------------------------------------------------------- Stock Research ----
with tab_dss:
    st.markdown('<div class="psx-section-eyebrow">STOCK RESEARCH</div>'
                '<div class="psx-section-title">Everything About One Stock, In One Place</div>',
                unsafe_allow_html=True)
    st.caption("Every engine's read on a single symbol — psx_brain's Verdict, the blended Decision, and the "
               "full Decision Support System (confluence matrix, Wyckoff, candlesticks, price action, "
               "backtested stats) — used to be split across two tabs; it's all here now. Hierarchy of "
               "evidence for the DSS score: Market Regime → Sector Regime → Stock Structure → Wyckoff → "
               "Supply/Demand → Candlesticks → Price Action → Relative Strength → Risk/Reward → Final "
               "Decision. Historical pattern statistics and quant baseline validation are explicitly marked "
               "PENDING where they don't apply — no win-rate is fabricated. This is analysis, not certainty: "
               "read every action as a hypothesis, not a promise.")

    st.caption("Whole-market rankings (including this same DSS scan, as the primary ranking) live on the "
               "**Screener** tab. This tab is for researching one stock at a time — pick it below, or click "
               "a row on the Screener tab to land here with it preselected.")

    if "research_symbol" not in st.session_state:
        st.session_state.research_symbol = "OGDC"
    dss_picks = ["OGDC", "PPL", "HBL", "UBL", "LUCK", "FFC", "ENGRO", "MCB", "SYS", "MARI"]
    dss_cols = st.columns(len(dss_picks) + 2)
    for i, p in enumerate(dss_picks):
        if dss_cols[i].button(p, key=f"dsspick_{p}",
                               type="primary" if st.session_state.research_symbol == p else "secondary"):
            st.session_state.research_symbol = p
    dss_typed = dss_cols[-2].text_input("Or type a symbol", value="", key="dss_typed",
                                         label_visibility="collapsed", placeholder="Type symbol...")
    if dss_typed.strip():
        st.session_state.research_symbol = dss_typed.strip().upper()
    dss_symbol = st.session_state.research_symbol

    if dss_symbol:
        d = _get(f"/dss/{dss_symbol}")
        if d.get("status") != "ok":
            st.warning(d.get("reason") or "Decision Support unavailable for this symbol.")
        else:
            q = d.get("quote") or {}
            names_dss = _company_names()
            cname = names_dss.get(dss_symbol)
            cls = "up" if (q.get("pct") or 0) >= 0 else "down"
            arrow = "▲" if (q.get("pct") or 0) >= 0 else "▼"
            st.markdown(
                f'<div class="psx-stock-hero"><div class="psx-avatar">{_initials(dss_symbol)}</div>'
                f'<div><div class="sym">{dss_symbol}</div>'
                f'<div class="co">{cname or "—"}{" · " + q.get("sector","") if q.get("sector") else ""}</div></div>'
                f'<div class="right"><div class="price">{q.get("price","—")}</div>'
                f'<div class="chg {cls}">{arrow} {abs(q.get("pct") or 0):.2f}%</div></div></div>',
                unsafe_allow_html=True)

            event_risk = d.get("event_risk") or {}
            if event_risk.get("level") == "HIGH":
                st.warning(f"⚠️ EVENT RISK: HIGH — {event_risk.get('reason','')} "
                           f"Score capped at {event_risk.get('score_cap')}/100 as a result.")
                for it in event_risk.get("items", [])[:2]:
                    st.caption(f"• {it.get('date','')}: {it.get('title','')}")

            sstate = d.get("signal_state") or {}
            slc = d.get("since_last_check")
            st.markdown(f'<span class="psx-badge watch">📍 {sstate.get("stage","NO STRUCTURE DETECTED")}</span>',
                        unsafe_allow_html=True)
            if slc is None:
                st.caption("First time this symbol has been checked — nothing to compare against yet.")
            elif slc.get("meaningful_change"):
                delta = slc.get("score_delta", 0)
                delta_str = f"{delta:+.1f}"
                bits = []
                if slc.get("action_changed"):
                    bits.append(f"action changed from **{slc.get('prior_action')}**")
                if slc.get("grade_changed"):
                    bits.append(f"grade changed from **{slc.get('prior_grade')}**")
                if slc.get("new_events"):
                    bits.append(f"new Wyckoff event(s): **{', '.join(slc['new_events'])}**")
                st.info(f"🔔 Since last check ({slc.get('prior_checked_at','')[:16].replace('T',' ')}): "
                        f"score {delta_str} — " + "; ".join(bits))
            else:
                st.caption(f"No meaningful change since last check "
                           f"({slc.get('prior_checked_at','')[:16].replace('T',' ')}).")

            wev = _get(f"/wyckoff-events/{dss_symbol}")  # needed by both the LIVE tab's chart and the TECHNICALS tab's event timeline

            st.markdown('<div class="psx-section-eyebrow">DEEP DIVE</div>'
                        '<div class="psx-section-title">Live · Verdict · Fundamentals · Technicals · Announcements · Profile · Competitors</div>',
                        unsafe_allow_html=True)
            subtab_live, subtab_verdict, subtab_fund, subtab_tech, subtab_ann, subtab_profile, subtab_comp = st.tabs(
                ["🔴 LIVE", "📊 VERDICT", "💰 FUNDAMENTALS", "📈 TECHNICALS",
                 "📢 ANNOUNCEMENTS", "🏢 PROFILE", "⚖️ COMPETITORS"]
            )
            with subtab_live:
                st.markdown('<div class="psx-section-eyebrow">INTERACTIVE CHART</div>'
                            '<div class="psx-section-title">Price, Volume & Wyckoff Events</div>',
                            unsafe_allow_html=True)
                with st.container(border=True):
                    ohlc = _get(f"/ohlc/{dss_symbol}", limit=260)
                    if isinstance(ohlc, list) and ohlc:
                        tr = (d.get("wyckoff") or {}).get("trading_range") or {}
                        fig = build_wyckoff_chart(ohlc, wev if wev.get("status") == "ok" else None,
                                                  support=tr.get("support"), resistance=tr.get("resistance"),
                                                  title=f"{dss_symbol} — daily")
                        if fig:
                            st.plotly_chart(fig, use_container_width=True)
                            st.caption("Markers: SC/AR/ST/Spring/Test/SOS/LPS (accumulation, teal) · "
                                       "PSY/BC/UT/SOW/LPSY (distribution, red) — from the same event scan "
                                       "shown in the timeline below. Dotted lines mark the current trading range.")
                    else:
                        st.caption("No stored true-OHLC for this symbol yet — backfill it from the More tab.")

                st.markdown('<div class="psx-section-eyebrow">DAY\'S RANGE</div>'
                            '<div class="psx-section-title">Price Stats</div>', unsafe_allow_html=True)
                with st.container(border=True):
                    day_gauge = _range_gauge_html(q.get("low"), q.get("high"), q.get("price"),
                                                  lo_label="Day Low", hi_label="Day High")
                    if day_gauge:
                        st.markdown(day_gauge, unsafe_allow_html=True)
                    lv1, lv2, lv3, lv4 = st.columns(4)
                    lv1.metric("Volume", _fmt_vol(q.get("volume")))
                    lv2.metric("Open", q.get("open") if q.get("open") is not None else "—")
                    lv3.metric("LDCP", q.get("ldcp") if q.get("ldcp") is not None else "—")
                    chg = q.get("change")
                    lv4.metric("Change", f"{chg:+.2f}" if isinstance(chg, (int, float)) else "—")
                    st.caption("52-week range isn't tracked by this backend yet — showing today's real "
                               "day range only rather than a guessed figure.")

            with subtab_verdict:
                st.markdown('<div class="psx-section-eyebrow">OTHER ENGINES\' OPINIONS</div>'
                            '<div class="psx-section-title">Cross-Check: psx_brain Verdict & Blended Decision</div>',
                            unsafe_allow_html=True)
                st.caption("Two independent, differently-built engines' read on this same stock — worth "
                           "noticing when they agree with the Evidence Score below, and worth investigating "
                           "when they don't. Neither is a subset or a looser version of the DSS score.")
                colA, colB = st.columns(2)
                with colA, st.container(border=True):
                    st.markdown('<div class="psx-panel-title">🧭 Verdict (psx_brain)</div>', unsafe_allow_html=True)
                    v = _get(f"/verdict/{dss_symbol}")
                    if v.get("status") == "ok":
                        st.markdown(_badge(v["verdict"]) +
                                    f'&nbsp;&nbsp;score **{v["score"]}** · confidence **{v["confidence"]}/100**',
                                    unsafe_allow_html=True)
                        st.caption(f"history: {v.get('history_source')}")
                        l = v.get("levels", {})
                        st.write(f"Trigger {l.get('trigger')} · Stop {l.get('stop')} · "
                                 f"T1 {l.get('t1')} · T2 {l.get('t2')} · T3 {l.get('t3')} · "
                                 f"R:R {l.get('rr')} · size {l.get('size_pct')}%")
                        if v.get("bull"):
                            st.success("\n".join("• " + x for x in v["bull"]))
                        if v.get("bear"):
                            st.error("\n".join("• " + x for x in v["bear"]))
                        if v.get("flags"):
                            st.warning("\n".join("• " + x for x in v["flags"]))
                    else:
                        st.info(v.get("reason", "Verdict unavailable."))
                with colB, st.container(border=True):
                    st.markdown('<div class="psx-panel-title">⚖️ Decision (technical + fundamentals + news + risk)</div>',
                                unsafe_allow_html=True)
                    dres = _get(f"/decision/{dss_symbol}", record=False)
                    if dres.get("status") == "unavailable":
                        st.info(dres.get("reason"))
                    elif "decision" in dres:
                        dec = dres["decision"]
                        st.markdown(_badge(dec.get("signal")) +
                                    f'&nbsp;&nbsp;confidence **{dec.get("confidence")}**', unsafe_allow_html=True)
                        if dec.get("reasons"):
                            st.write("　·　".join(dec["reasons"]))
                        bz1, bz2 = dec.get("buy_zone_low"), dec.get("buy_zone_high")
                        if bz1 is not None:
                            st.caption(f"Buy zone: {bz1} – {bz2}  ·  confluence "
                                       f"{dec.get('confluence')} ({', '.join(dec.get('confluence_dims', []))})")
                    if isinstance(dres.get("engines"), dict):
                        with st.expander("Engine breakdown (technical / fundamentals / regime / shariah / risk)"):
                            for ename, block in dres["engines"].items():
                                st.markdown(f"*{ename}*")
                                st.table(pd.DataFrame(
                                    [(k, bv) for k, bv in block.items() if not isinstance(bv, (dict, list))],
                                    columns=["field", "value"]))

                grade = d.get("confidence_grade", "F")
                grade_cls = "grade-strong" if grade in ("A+", "A") else "grade-weak" if grade in ("D", "F") else "grade-mid"
                action = d.get("final_action", "NEUTRAL")
                with st.container(border=True):
                    sc1, sc2 = st.columns([1, 2])
                    with sc1:
                        st.markdown(
                            f'<div class="psx-score-hero">'
                            f'<div><div class="psx-score-num">{d.get("evidence_score")}<span style="font-size:1.1rem;color:var(--sub);">/100</span></div>'
                            f'<div class="psx-score-sub">Evidence Score · {d.get("score_basis","")}</div></div>'
                            f'</div>', unsafe_allow_html=True)
                        st.markdown(f'<span class="psx-badge {grade_cls}">Grade {grade}</span>&nbsp;&nbsp;'
                                    f'{_badge(action)}', unsafe_allow_html=True)
                        st.caption(f"{d.get('bullish_components')} bullish vs {d.get('bearish_components')} "
                                   "bearish components (of those with real data).")
                    with sc2:
                        r = d.get("risk", {})
                        gauge = _range_gauge_html(r.get("invalidation"), r.get("target_1"), q.get("price"),
                                                  lo_label="Invalidation", hi_label="Target 1")
                        if gauge:
                            st.markdown(gauge, unsafe_allow_html=True)
                            rm3, rm4 = st.columns(2)
                            rm3.metric("Target 2", r.get("target_2") or "—")
                            rm4.metric("R : R", r.get("reward_risk") or "—")
                        else:
                            rm1, rm2, rm3, rm4 = st.columns(4)
                            rm1.metric("Invalidation", r.get("invalidation") or "—")
                            rm2.metric("Target 1", r.get("target_1") or "—")
                            rm3.metric("Target 2", r.get("target_2") or "—")
                            rm4.metric("R : R", r.get("reward_risk") or "—")
                        if not r.get("liquidity_ok"):
                            st.warning("Below the liquidity gate — confidence in every signal here is reduced.")
                        vr = d.get("volatility_regime") or {}
                        if vr.get("status") == "ok":
                            st.caption(f"📊 Volatility regime: **{vr.get('regime')}** "
                                       f"(ATR {vr.get('atr_pct_of_price')}% of price, "
                                       f"{vr.get('percentile_vs_own_history')}th percentile of its own history) "
                                       "— adjust stop distance accordingly, never a fixed -2%/-5%.")

                dq = d.get("data_quality") or {}
                liq = d.get("liquidity") or {}
                ss = d.get("stop_loss_sanity") or {}
                pq = d.get("position_quality") or {}
                with st.container(border=True):
                    st.markdown('<div class="psx-panel-title">🧪 Data Quality, Liquidity & Trade Structure</div>',
                                unsafe_allow_html=True)
                    qc1, qc2, qc3, qc4 = st.columns(4)
                    qc1.metric("Data quality", f"{dq.get('score','—')}/100" if dq.get("score") is not None else "—")
                    qc2.metric("Liquidity tier", liq.get("tier", "—"))
                    qc3.metric("Stop sanity", f"{ss.get('atr_multiple','—')}× ATR" if ss.get("atr_multiple") else "—")
                    qc4.metric("Position quality", f"{pq.get('score','—')}/100" if pq.get("score") is not None else "—")
                    if dq.get("score") is not None and dq["score"] < 90:
                        st.caption(f"⚠️ Data quality {dq['score']}/100 — {dq.get('issues')}")
                    if liq.get("confidence_multiplier", 1.0) < 1.0:
                        st.caption(f"⚠️ {liq.get('tier')} — confidence multiplier {liq.get('confidence_multiplier')}× "
                                   "applied to the evidence score.")
                    if ss.get("status") == "ok":
                        st.caption(f"🛑 {ss.get('verdict')}")
                    if pq.get("breakdown"):
                        bd = pq["breakdown"]
                        st.caption(f"Position quality breakdown — setup {bd.get('setup_quality')}, "
                                   f"stop {bd.get('stop_quality')}, liquidity {bd.get('liquidity_quality')}, "
                                   f"R:R {bd.get('reward_risk_quality')}, market alignment {bd.get('market_alignment_quality')}")

                st.markdown('<div class="psx-section-eyebrow">THREE DIFFERENT NUMBERS</div>'
                            '<div class="psx-section-title">Evidence · Historical Edge · Calibrated Frequency</div>',
                            unsafe_allow_html=True)
                with st.container(border=True):
                    st.caption("These measure three different things — never collapsed into one 'confidence'.")
                    tn1, tn2, tn3 = st.columns(3)
                    with tn1:
                        st.metric("Evidence Score", f"{d.get('evidence_score')}/100")
                        st.caption("How strongly current analytical engines agree — not a probability.")
                    he = d.get("historical_edge")
                    with tn2:
                        st.metric("Historical OOS Edge", f"{he['oos_expectancy_pct']:+.2f}%" if he else "—")
                        st.caption(f"n={he['n']} in held-out test data" if he else
                                   "No matching pattern in the walk-forward cache yet.")
                    cw = d.get("calibrated_win_frequency")
                    with tn3:
                        st.metric("Calibrated Win Frequency", f"{cw['actual_in_test_pct']}%" if cw else "—")
                        st.caption(f"vs {cw['predicted_from_train_pct']}% predicted from train (n={cw['n']})" if cw else
                                   "No calibration bin match yet.")

                    gates = d.get("gates") or {}
                    fired = [k for k in ("structural_veto", "rr_below_1_5", "oos_negative")
                            if gates.get(k)] + (["liquidity_tier:" + gates["liquidity_tier"]]
                                                if gates.get("liquidity_tier") in ("Illiquid", "Very Illiquid") else [])
                    if fired:
                        reasons = []
                        if gates.get("structural_veto"):
                            reasons.append("Wyckoff structure reads distribution/markdown-like, or an Upthrust is "
                                           "confirmed/candidate")
                        if gates.get("rr_below_1_5"):
                            reasons.append("Reward/risk is below 1.5")
                        if gates.get("oos_negative"):
                            reasons.append("This pattern's out-of-sample expectancy is negative in the walk-forward cache")
                        if gates.get("liquidity_tier") in ("Illiquid", "Very Illiquid"):
                            reasons.append(f"Liquidity tier is {gates['liquidity_tier']}")
                        st.warning("**Why not a stronger BUY?** The additive evidence score alone would have "
                                  "claimed more — capped because: " + "; ".join(reasons) + ".")
                    else:
                        st.caption("No gate capped this action — the final action reflects the additive score directly.")

                st.markdown('<div class="psx-section-eyebrow">CONFLUENCE MATRIX</div>'
                            '<div class="psx-section-title">Signal Confluence</div>', unsafe_allow_html=True)
                with st.container(border=True):
                    rows_html = []
                    for c in d.get("confluence_matrix", []):
                        stance = c["stance"]
                        pts = c["signed_points"]
                        if stance == "pending":
                            fill = ""
                            pts_html = '<span style="color:var(--sub);font-style:italic;">pending</span>'
                        else:
                            width = min(50, abs(pts) / max(1, c["weight"]) * 50)
                            fillcls = "bullish" if stance == "bullish" else "bearish" if stance == "bearish" else ""
                            fill = f'<div class="bar-fill {fillcls}" style="width:{width}%"></div>' if fillcls else ""
                            pts_cls = "up" if pts > 0 else "down" if pts < 0 else ""
                            pts_html = f'<span class="comp-pts {pts_cls}">{pts:+.1f}</span>'
                        rows_html.append(
                            f'<div class="psx-conf-row"><div class="bar-track">{fill}</div>'
                            f'<div class="comp-name">{c["component"]} <span style="color:var(--sub);font-weight:400;">'
                            f'(w={c["weight"]})</span></div>{pts_html}'
                            f'<div class="comp-detail">{c["detail"]}</div></div>'
                        )
                    st.markdown("".join(rows_html), unsafe_allow_html=True)

                st.markdown('<div class="psx-section-eyebrow">SCENARIOS</div>'
                            '<div class="psx-section-title">Three-Scenario Analysis</div>', unsafe_allow_html=True)
                with st.container(border=True):
                    ts = d.get("three_scenarios", {})
                    for kind, label in (("bullish", "🟢 Bullish Case"), ("base", "⚪ Base Case"), ("bearish", "🔴 Bearish Case")):
                        sc = ts.get(kind, {})
                        st.markdown(
                            f'<div class="psx-scenario-card {kind}"><b>{label}</b><br>'
                            f'<b>What must happen:</b> {sc.get("what_must_happen","—")}<br>'
                            f'<b>Then:</b> {sc.get("then","—")}</div>', unsafe_allow_html=True)

                ec1, ec2 = st.columns(2)
                with ec1, st.container(border=True):
                    st.markdown('<div class="psx-panel-title">🎯 Entry Engine</div>', unsafe_allow_html=True)
                    ee = d.get("entry_engine", {})
                    for k, label in (("aggressive", "Aggressive"), ("standard", "Standard"), ("conservative", "Conservative")):
                        e = ee.get(k, {})
                        st.markdown(f"**{label}: {e.get('price') or '—'}**  \n{e.get('reason','')}")
                with ec2, st.container(border=True):
                    st.markdown('<div class="psx-panel-title">🧭 Market & Sector Regime</div>', unsafe_allow_html=True)
                    mr = d.get("market_regime") or {}
                    sr = d.get("sector_regime") or {}
                    st.markdown(f"**KSE-100:** {mr.get('label','—')} (breadth {mr.get('breadth_pct','—')}%, "
                                f"avg chg {mr.get('avg_change_pct','—')}%)")
                    if sr:
                        st.markdown(f"**Sector ({sr.get('sector','—')}):** breadth {sr.get('breadth_pct','—')}%, "
                                    f"avg chg {sr.get('avg_change_pct','—')}%, strength {sr.get('strength','—')}")
                    else:
                        st.caption("Sector rotation data unavailable.")

                ws = d.get("weekly_structure") or {}
                if ws.get("status") == "ok":
                    st.caption(f"📅 **Weekly structure** (strategic timeframe, {ws.get('bars')} weeks): "
                               f"{(ws.get('structure') or {}).get('trend','—')}")

            with subtab_tech:
                st.markdown('<div class="psx-section-eyebrow">SUPPORTING DETAIL</div>'
                            '<div class="psx-section-title">Technical Stack & Candlestick Structure</div>',
                            unsafe_allow_html=True)
                tcol1, tcol2, tcol3 = st.columns(3)
                with tcol1, st.container(border=True):
                    st.markdown('<div class="psx-panel-title">📐 Wyckoff (quick read)</div>', unsafe_allow_html=True)
                    w = _get(f"/wyckoff-pro/{dss_symbol}")
                    if w.get("phase"):
                        st.markdown(_badge(w["phase"]), unsafe_allow_html=True)
                        tr_w = w.get("trading_range", {})
                        if tr_w:
                            st.caption(f"Range: {tr_w.get('support')} – {tr_w.get('resistance')} "
                                       f"({tr_w.get('width_pct')}% wide, {tr_w.get('bars')} bars)")
                        st.write(f"Spring: {w.get('spring', {}).get('status', '—')}  ·  "
                                 f"Upthrust: {w.get('upthrust', {}).get('status', '—')}")
                    else:
                        st.info(w.get("reason") or "Needs ≥50 true-OHLC sessions — backfill from More tab.")
                with tcol2, st.container(border=True):
                    st.markdown('<div class="psx-panel-title">📊 Technical (full V1 stack)</div>', unsafe_allow_html=True)
                    t = _get(f"/technical-pro/{dss_symbol}")
                    if t.get("status") == "ok":
                        tech = t["technical"]
                        st.markdown(_badge(tech.get("classification")) +
                                    f'&nbsp;&nbsp;score **{tech.get("score")}**', unsafe_allow_html=True)
                        rsi_kind, rsi_tag = _rsi_verdict(tech.get("rsi"))
                        adx_kind, adx_tag = _adx_verdict(tech.get("adx_proxy"))
                        st.markdown(
                            '<div class="psx-ind-grid">'
                            + _ind_pill_html("RSI", tech.get("rsi"), rsi_kind, rsi_tag)
                            + _ind_pill_html("ATR%", tech.get("atr_pct"), "neutral", "VOLATILITY")
                            + _ind_pill_html("ADX", tech.get("adx_proxy"), adx_kind, adx_tag)
                            + '</div>', unsafe_allow_html=True)
                        if tech.get("notes"):
                            st.write("\n".join("• " + n for n in tech["notes"]))
                        st.caption(f"Stop {tech.get('stop_loss')} · Target1 {tech.get('target1')} · "
                                   f"Target2 {tech.get('target2')} · R:R {tech.get('risk_reward')} · "
                                   f"source: {tech.get('history_source')}")
                    else:
                        st.info(t.get("reason", "Technical-pro unavailable."))
                with tcol3, st.container(border=True):
                    st.markdown('<div class="psx-panel-title">🕯️ Candlestick patterns</div>', unsafe_allow_html=True)
                    it = _get(f"/intelligence/{dss_symbol}")
                    if it.get("status") == "awaiting_true_ohlcv" or "sessions" not in it:
                        st.info(it.get("message") or
                                "No true OHLC stored for this symbol yet. Backfill it "
                                "from More → Backfill true OHLC.")
                    else:
                        st.caption(f"{it['sessions']} true-OHLC sessions · ATR14 "
                                   f"{it.get('atr14') and round(it['atr14'], 2)}")
                        if it.get("candles"):
                            st.success(", ".join(it["candles"]))
                        else:
                            st.caption("No candlestick pattern on the most recent bar "
                                       "(doji/hammer/engulfing etc. don't fire every day — "
                                       "this is a normal, non-error result).")
                        st.write(f"Structure: {it.get('structure', {}).get('trend', '—')}, "
                                 f"BOS {it.get('structure', {}).get('bos') or 'none'}")

                st.markdown('<div class="psx-section-eyebrow">RELATIVE STRENGTH</div>'
                            '<div class="psx-section-title">Stock vs KSE-100 vs Sector</div>', unsafe_allow_html=True)
                with st.container(border=True):
                    rss = _get(f"/relative-strength-series/{dss_symbol}", lookback=252)
                    if rss.get("status") == "ok" and rss.get("dates"):
                        rsdf = pd.DataFrame({"date": pd.to_datetime(rss["dates"]), dss_symbol: rss["stock"],
                                             "KSE-100": rss["index"], "Sector avg": rss["sector"]})
                        rsfig = go.Figure()
                        rsfig.add_trace(go.Scatter(x=rsdf["date"], y=rsdf[dss_symbol], name=dss_symbol,
                                                   line=dict(color="#0D9488", width=2)))
                        if rsdf["KSE-100"].notna().any():
                            rsfig.add_trace(go.Scatter(x=rsdf["date"], y=rsdf["KSE-100"], name="KSE-100",
                                                       line=dict(color="#64748B", width=1.5, dash="dot")))
                        if rsdf["Sector avg"].notna().any():
                            rsfig.add_trace(go.Scatter(x=rsdf["date"], y=rsdf["Sector avg"], name="Sector avg",
                                                       line=dict(color="#F59E0B", width=1.5, dash="dash")))
                        rsfig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10),
                                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                            legend=dict(orientation="h", y=1.1), font=dict(size=11),
                                            yaxis_title="Rebased to 100")
                        st.plotly_chart(rsfig, use_container_width=True)
                        st.caption(rss.get("note", ""))
                    else:
                        st.caption("Not enough stored true-OHLC to plot relative strength yet.")

            with subtab_tech:
                st.markdown('<div class="psx-section-eyebrow">WYCKOFF DETAIL</div>'
                            '<div class="psx-section-title">Event Timeline & 9 Buying/Selling Tests</div>',
                            unsafe_allow_html=True)
                if wev.get("status") == "ok":
                    wc1, wc2 = st.columns(2)
                    with wc1, st.container(border=True):
                        st.markdown('<div class="psx-panel-title">📈 Accumulation Sequence</div>', unsafe_allow_html=True)
                        accum = wev.get("accumulation", {})
                        if accum.get("events"):
                            st.dataframe(pd.DataFrame(accum["events"]), use_container_width=True, hide_index=True)
                        else:
                            st.caption("No accumulation events detected in the scanned window.")
                        bt = wev.get("buying_tests", {})
                        st.markdown(f"**Buying Tests: {bt.get('passed')}/9 passed**")
                        st.dataframe(pd.DataFrame(bt.get("tests", [])), use_container_width=True, hide_index=True, height=250)
                    with wc2, st.container(border=True):
                        st.markdown('<div class="psx-panel-title">📉 Distribution Sequence</div>', unsafe_allow_html=True)
                        distrib = wev.get("distribution", {})
                        if distrib.get("events"):
                            st.dataframe(pd.DataFrame(distrib["events"]), use_container_width=True, hide_index=True)
                        else:
                            st.caption("No distribution events detected in the scanned window.")
                        st_ = wev.get("selling_tests", {})
                        st.markdown(f"**Selling Tests: {st_.get('passed')}/9 passed**")
                        st.dataframe(pd.DataFrame(st_.get("tests", [])), use_container_width=True, hide_index=True, height=250)
                else:
                    st.caption(wev.get("reason") or "Wyckoff event detail unavailable — needs true-OHLC history.")

                with st.container(border=True):
                    st.markdown('<div class="psx-panel-title">📊 Al Brooks Price Action</div>', unsafe_allow_html=True)
                    pa = _get(f"/price-action/{dss_symbol}")
                    if pa.get("status") == "ok":
                        ts_ = pa.get("trend_strength", {})
                        if ts_.get("status") == "ok":
                            st.markdown(f"**Trend strength score: {ts_.get('score')}/100** "
                                        f"(closes near extreme {ts_.get('closes_near_extreme')}, "
                                        f"follow-through: {ts_.get('follow_through')})")
                        bq = pa.get("breakout_quality", {})
                        if bq.get("status") == "ok":
                            st.markdown(f"**Breakout: {bq.get('grade')} (score {bq.get('score')})** — "
                                        f"vol×avg {bq.get('volume_ratio')}, close position {bq.get('close_position')}, "
                                        f"follow-through confirmed: {bq.get('follow_through_confirmed')}")
                        else:
                            st.caption(bq.get("status", "No breakout in the recent window."))
                        with st.expander("Last 10 bars, Al Brooks classification"):
                            st.dataframe(pd.DataFrame(pa.get("recent_bars", [])), use_container_width=True, hide_index=True)
                    else:
                        st.caption(pa.get("reason") or "Price action detail unavailable.")

            with subtab_fund:
                st.markdown('<div class="psx-section-eyebrow">FUNDAMENTALS</div>'
                            '<div class="psx-section-title">Earnings, Profitability & Valuation</div>',
                            unsafe_allow_html=True)
                with st.container(border=True):
                    st.markdown('<div class="psx-panel-title">💰 Fundamentals — free (PSX company page + sector blend)</div>',
                                unsafe_allow_html=True)
                    fund_engine = (dres.get("engines", {}) or {}).get("fundamentals") if isinstance(dres, dict) else None
                    if fund_engine and fund_engine.get("have"):
                        st.metric("Fundamentals score", fund_engine.get("score"))
                        st.write("\n".join("• " + h for h in fund_engine["have"]))
                        st.caption(f"As of {fund_engine.get('as_of')} — sector-relative blend "
                                   "(fundamentals_analyzer.py, scraped free, no LLM).")
                    else:
                        st.info("No sector-relative blend cached for this symbol yet — "
                                "run Backfill fundamentals (More tab) or POST /backfill-fundamentals.")
                    with st.expander("psxwatch deep engine (53-metric ratios) — needs ANTHROPIC_API_KEY"):
                        fd = _get(f"/fundamentals-deep/{dss_symbol}")
                        if fd.get("status") == "ok":
                            ratios = fd.get("ratios", {})
                            st.caption(f"{fd.get('ticker')} · period ending {fd.get('period_end')} "
                                       f"({fd.get('months')} months) · sector {fd.get('sector')}")
                            st.dataframe(pd.DataFrame(sorted(ratios.items()), columns=["metric", "value"]),
                                        use_container_width=True, height=300)
                        else:
                            st.info(fd.get("reason", "Not available."))
            with subtab_profile:
                st.markdown('<div class="psx-section-eyebrow">COMPANY SNAPSHOT</div>'
                            '<div class="psx-section-title">Profile</div>', unsafe_allow_html=True)
                with st.container(border=True):
                    pv1, pv2, pv3 = st.columns(3)
                    pv1.metric("Sector", q.get("sector") or "—")
                    pv2.metric("Shariah", "Compliant" if q.get("shariah") else "Not verified compliant")
                    pv3.metric("Index membership", (q.get("listed") or "—").split(",")[0])
                    if q.get("shariah_status"):
                        st.caption(q["shariah_status"])
                    fpv = _get(f"/fundamentals/{dss_symbol}")
                    if fpv.get("raw_available"):
                        st.markdown("**Latest scraped financials (PSX company page)**")
                        fp_rows = [(k, v) for k, v in fpv.items() if k not in ("symbol", "source", "raw_available")]
                        st.table(pd.DataFrame(fp_rows, columns=["field", "value"]))
                        st.caption(f"Source: {fpv.get('source')}")
                st.markdown('<div class="psx-section-eyebrow">NEWS & EXPOSURE</div>'
                            '<div class="psx-section-title">News Sentiment & Driver Exposure</div>',
                            unsafe_allow_html=True)
                with st.container(border=True):
                    st.markdown('<div class="psx-panel-title">📰 News — free (deterministic keyword scorer)</div>',
                                unsafe_allow_html=True)
                    nv = _get(f"/news-verdict/{dss_symbol}")
                    if nv.get("status") == "ok":
                        nvv = nv["verdict"]
                        st.markdown(_badge(nvv.get("direction")) +
                                    f'&nbsp;&nbsp;materiality **{nvv.get("materiality")}** · '
                                    f'confidence **{nvv.get("confidence")}**', unsafe_allow_html=True)
                        if nvv.get("headlines"):
                            st.write("\n".join("• " + h for h in nvv["headlines"]))
                        if nvv.get("sources"):
                            st.caption(" · ".join(nvv["sources"][:3]))
                    else:
                        st.info(nv.get("note", "No fresh headline matched this ticker this run."))
                    with st.expander("Driver exposure (psxwatch priors) + evidence-quoted news scores"):
                        ex = _get(f"/exposure/{dss_symbol}")
                        if ex.get("status") == "ok" and ex.get("exposures"):
                            st.dataframe(pd.DataFrame(ex["exposures"]), use_container_width=True)
                            st.caption(ex.get("note", ""))
                        else:
                            st.info(ex.get("reason", "No stored exposure priors."))
                        ni = _get(f"/news-impact/{dss_symbol}")
                        if ni.get("status") == "ok" and ni.get("items"):
                            st.dataframe(pd.DataFrame(ni["items"]), use_container_width=True)
                        else:
                            st.info(ni.get("reason", "No stored news impact scores (needs ANTHROPIC_API_KEY)."))
            with subtab_verdict:
                with st.expander("📜 Audit trail — past snapshots for this symbol"):
                    hist = _get(f"/dss/{dss_symbol}/history")
                    snaps = hist.get("snapshots", [])
                    if snaps:
                        hdf = pd.DataFrame(snaps)
                        st.dataframe(hdf[["saved_at", "evidence_score", "confidence_grade", "final_action",
                                         "wyckoff_phase", "price", "invalidation", "target_1", "reward_risk"]],
                                    use_container_width=True, hide_index=True)
                    else:
                        st.caption("No prior snapshots yet.")

                with st.expander("📄 Formal 16-part stock report (STEP 61)"):
                    rep = _get(f"/dss/{dss_symbol}/report")
                    if rep.get("status") == "ok":
                        st.markdown(rep.get("report_markdown", ""))
                    else:
                        st.caption(rep.get("reason", "Report unavailable."))

                with st.expander("Full raw evidence (Wyckoff / verdict / decision engine outputs)"):
                    st.json({"wyckoff": d.get("wyckoff"), "verdict": d.get("verdict"), "decision": d.get("decision")})

                st.caption(d.get("note", ""))
            with subtab_ann:
                st.markdown('<div class="psx-section-eyebrow">OFFICIAL FILINGS</div>'
                            '<div class="psx-section-title">Announcements</div>', unsafe_allow_html=True)
                ann = _get(f"/announcement-intelligence/{dss_symbol}")
                items = ann.get("items") if isinstance(ann, dict) else None
                if items:
                    st.caption(ann.get("warning", ""))
                    for it in items[:20]:
                        materiality = (it.get("materiality") or "").upper()
                        mcls = "sell" if materiality == "HIGH" else "watch" if materiality == "MEDIUM" else "neutral"
                        st.markdown(
                            f'<div class="psx-card"><div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                            f'<div><b>{it.get("title","")}</b><br>'
                            f'<span style="color:var(--sub);font-size:0.8rem;">{it.get("date","")}</span></div>'
                            f'<span class="psx-badge {mcls}">{materiality or "—"}</span></div>'
                            f'<div style="margin-top:8px;font-size:0.82rem;color:var(--sub);">Assessment: {it.get("direction","")}</div>'
                            f'</div>', unsafe_allow_html=True)
                else:
                    st.info((ann.get("reason") if isinstance(ann, dict) else None) or "No announcement data available for this symbol.")

            with subtab_comp:
                st.markdown('<div class="psx-section-eyebrow">PEER COMPARISON</div>'
                            f'<div class="psx-section-title">{dss_symbol} vs Sector Peers</div>', unsafe_allow_html=True)
                sector_ = q.get("sector")
                if sector_:
                    all_rows = _get("/market", min_volume=0)
                    all_rows = all_rows if isinstance(all_rows, list) else []
                    peers = [r for r in all_rows if isinstance(r, dict) and r.get("sector") == sector_
                             and r.get("symbol") != dss_symbol]
                    peers = sorted(peers, key=lambda r: -(r.get("volume") or 0))[:5]
                    if peers:
                        comp_rows = [{"symbol": dss_symbol, "price": q.get("price"), "chg %": q.get("pct"),
                                      "score": q.get("score"), "setup": q.get("setup")}]
                        for p in peers:
                            comp_rows.append({"symbol": p["symbol"], "price": p.get("price"),
                                              "chg %": p.get("pct"), "score": p.get("score"), "setup": p.get("setup")})
                        cdf = pd.DataFrame(comp_rows)
                        st.dataframe(cdf, use_container_width=True, hide_index=True,
                                    column_config={
                                        "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
                                        "chg %": st.column_config.NumberColumn(format="%.2f%%"),
                                        "price": st.column_config.NumberColumn(format="%.2f")})
                        st.caption(f"Same-sector peers ({sector_}) by traded volume — 'score' here is the same "
                                   "quick price/volume heuristic shown on the Home tab, not the Evidence Score. "
                                   "Type a peer's symbol into the picker above for its full DSS breakdown.")
                    else:
                        st.info("No other symbols found in this sector in today's market data.")
                else:
                    st.info("Sector unavailable for this symbol — can't find peers.")

# ---------------------------------------------------------------- More ----
with tab_more:
    st.markdown('<div class="psx-section-eyebrow">TOOLS & STATUS</div>'
                '<div class="psx-section-title">More</div>', unsafe_allow_html=True)
    st.caption("Data backfill, the quantitative validation lab (does any pattern actually beat a coin "
               "flip, and does it hold on data it never saw), and system status \u2014 grouped so you "
               "don't have to scroll past everything to find one thing.")

    more_token = _admin_token_input("more_admin_token")
    st.caption("One admin token, reused by every force-run/backfill action below \u2014 enter it once here "
               "(only needed if PSX_ADMIN_TOKEN is set on the backend; on localhost it's optional).")

    subtab_data, subtab_quant, subtab_status = st.tabs(
        ["\U0001F5C4\uFE0F DATA & BACKFILL", "\U0001F9EA QUANT VALIDATION LAB", "\u2699\uFE0F SYSTEM STATUS"]
    )

    with subtab_data:
        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">🗄️ Backfill True OHLC</div>', unsafe_allow_html=True)
            st.caption("Candlestick patterns, real ATR/ADX, CMF and Wyckoff all need true "
                       "open/high/low/close — PSX's EOD feed is close-only, so this pulls "
                       "genuine OHLCV from Yahoo Finance and stores it. Use this to backfill a **new** "
                       "symbol's full history. Everything **already** backfilled gets its latest daily bar "
                       "appended automatically once a day in the background — no manual re-run needed.")
            bf1, bf2 = st.columns(2)
            with bf1:
                bf_symbol = st.text_input("Symbol to backfill", value="OGDC", key="bf_sym").strip().upper()
                if st.button("Backfill this symbol", type="primary"):
                    with st.spinner(f"Backfilling {bf_symbol}..."):
                        r = _post(f"/backfill-ohlc/{bf_symbol}")
                    st.json(r)
            with bf2:
                bf_limit = st.number_input("Bulk: top-N most liquid", step=5, key="bf_limit",
                                            on_change=_sync_cb("limit", "bf_limit"))
                if st.button("Backfill bulk"):
                    params = {"limit": bf_limit}
                    if more_token:
                        params["token"] = more_token
                    with st.spinner("Backfilling bulk (this can take a minute)..."):
                        r = requests.post(f"{BACKEND}/backfill-ohlc-bulk", params=params, timeout=180).json()
                    st.json(r)

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">⬇️ Export</div>', unsafe_allow_html=True)
            st.markdown(f"[Download full market export (.xlsx)]({BACKEND}/export.xlsx)")

    with subtab_quant:
        st.caption("Five tools, one question each: does a pattern beat random chance, does "
                   "its edge survive data it never trained on, does it hold across bull/bear "
                   "regimes, is there a genuine PSX-specific combination worth tracking, and "
                   "are past BUY signals grading out as real wins or losses in hindsight?")

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">🧪 Pattern Backtest Lab</div>', unsafe_allow_html=True)
            st.caption("Real walk-forward backtest over every symbol with stored true-OHLC (daily_ohlc) — "
                       "candlesticks, Spring/Upthrust, breakouts, plus Spring+candlestick combos. Feeds the "
                       "Decision Support tab's Historical Stats and Quant Validation components with genuine "
                       "numbers instead of PENDING. No win-rate is fabricated; sample sizes are always shown. "
                       "Auto-refreshes once a day in the background (pattern stats come from daily bars that "
                       "don't shift within a day) — no click needed for routine use.")
            bt_status = _get("/backtest/status")
            if bt_status.get("status") == "ok":
                run = bt_status["run"]
                st.caption(f"Last run: {run.get('run_at')} · {run.get('universe_symbols')} symbols · "
                           f"{run.get('universe_bars')} bars · horizon {bt_status.get('horizon')}d")
                bdf = pd.DataFrame(bt_status["patterns"]).sort_values("expectancy", ascending=False)
                st.dataframe(bdf[["pattern", "n", "win_rate", "avg_return", "median_return", "expectancy", "low_sample"]],
                            use_container_width=True, hide_index=True, height=300)
                st.markdown("**Baselines (Grimes-style — does any pattern above actually beat these?)**")
                base_df = pd.DataFrame(bt_status["baselines"])
                st.dataframe(base_df[["baseline", "n", "win_rate", "avg_return", "expectancy"]],
                            use_container_width=True, hide_index=True)
            else:
                st.info(bt_status.get("reason", "No backtest run yet — the background scheduler runs one "
                                                "automatically within its first cycle after startup."))
            if st.button("Force re-run now", type="secondary"):
                params = {"force": "true"}
                if more_token:
                    params["token"] = more_token
                # Backend always returns the last cached result instantly (even
                # while a force-triggered recompute runs in the background) — no
                # blocking wait here.
                r = requests.post(f"{BACKEND}/backtest/run", params=params, timeout=30).json()
                if r.get("status") == "ok":
                    note = " (refresh running in background — reload shortly for the new result)" \
                        if r.get("_background_refresh_running") else ""
                    st.success(f"Backtest: {r['universe_symbols']} symbols, {r['universe_bars']} bars, "
                               f"{len(r['patterns_found'])} patterns detected.{note}")
                    st.rerun()
                else:
                    st.error(r.get("reason", "Backtest failed."))

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">🔍 Failure Analysis — Audit Trail</div>', unsafe_allow_html=True)
            st.caption("Retroactively grades every past BUY-leaning Decision Support snapshot at least N days "
                       "old against what the stored true-OHLC actually did next — target hit first (win), "
                       "invalidation hit first (loss), or still pending. Losses are cited with the exact "
                       "recorded conditions at signal time (weak R:R, weak grade, unresolved Wyckoff phase, "
                       "high event risk), never a guess. Auto-refreshes daily for the default 20-day window.")

            def _render_failure_analysis(fa):
                if fa.get("status") == "ok":
                    if "_cache_age_seconds" in fa:
                        st.caption(f"Cached {fa['_cache_age_seconds']}s ago")
                    st.metric("Win rate", f"{fa['win_rate']}%" if fa.get("win_rate") is not None else "—")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Wins", fa.get("wins", 0))
                    m2.metric("Losses", fa.get("losses", 0))
                    m3.metric("Pending", fa.get("pending", 0))
                    if fa.get("graded"):
                        gdf = pd.DataFrame(fa["graded"])
                        st.dataframe(gdf, use_container_width=True, hide_index=True)
                    else:
                        st.info("No snapshots old enough yet to grade — the audit trail needs time to accumulate. "
                                "Every /dss/{symbol} call saves a snapshot automatically.")
                    st.caption(fa.get("note", ""))
                else:
                    st.error(fa.get("reason", "Failure analysis unavailable."))

            if "failure_analysis_result" not in st.session_state:
                st.session_state["failure_analysis_result"] = _get("/audit/failure-analysis")
            _render_failure_analysis(st.session_state["failure_analysis_result"])

            with st.expander("Custom window (runs live, not cached)"):
                fa1, fa2 = st.columns(2)
                with fa1:
                    fa_min_age = st.number_input("Min snapshot age (days)", value=20, step=5, key="fa_min_age")
                with fa2:
                    fa_horizon = st.number_input("Outcome horizon (trading days)", value=20, step=5, key="fa_horizon")
                if st.button("Run custom failure analysis"):
                    with st.spinner("Grading past snapshots against real subsequent price action..."):
                        fa = requests.get(f"{BACKEND}/audit/failure-analysis",
                                          params={"min_age_days": fa_min_age, "horizon_days": fa_horizon, "force": "true"},
                                          timeout=60).json()
                    _render_failure_analysis(fa)

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">🔬 Walk-Forward Validation Lab</div>', unsafe_allow_html=True)
            st.caption("Chronological train (60%) / validation (20%) / test (20%) split per symbol — never "
                       "shuffled, so 'test' is genuinely unseen future data. Shows whether a pattern's train-set "
                       "edge actually holds out-of-sample, net-of-transaction-cost expectancy, correlation-based "
                       "feature importance, and empirical calibration. Auto-refreshes daily for the default "
                       "parameters — no click needed for routine use.")
            if st.button("Force re-run walk-forward now", type="secondary"):
                params = {"force": "true"}
                if more_token:
                    params["token"] = more_token
                # Instant — backend serves the last cached result while the force
                # recompute runs in the background.
                wf = requests.post(f"{BACKEND}/backtest/walkforward", params=params, timeout=30).json()
                if wf.get("status") == "ok":
                    st.session_state["wf_result"] = wf
                    if wf.get("_background_refresh_running"):
                        st.toast("Recompute running in the background — showing last known result; "
                                 "re-run this in a bit for the fresh one.", icon="🔄")
                else:
                    st.error(wf.get("reason", "Walk-forward validation failed."))
            if "wf_result" not in st.session_state:
                # POST-only route (it also accepts non-default params), but with no
                # `force` it checks the cache first and returns instantly if fresh —
                # cheap, not a live recompute, UNLESS the background scheduler hasn't
                # completed its first pass yet (e.g. right after a backend restart),
                # in which case this can briefly block — caught below, not crashed.
                try:
                    cached_wf = requests.post(f"{BACKEND}/backtest/walkforward", timeout=15).json()
                    if cached_wf.get("status") == "ok":
                        st.session_state["wf_result"] = cached_wf
                except requests.exceptions.Timeout:
                    st.session_state["wf_result"] = None
                    st.caption("⏳ Still computing in the background (first run after startup) — check back shortly.")
            wf = st.session_state.get("wf_result")
            if wf:
                if "_cache_age_seconds" in wf:
                    st.caption(f"Cached {wf['_cache_age_seconds']}s ago")
                st.caption(f"{wf['universe_symbols']} symbols · train {wf['counts']['train']} signals · "
                           f"validation {wf['counts']['validation']} · test {wf['counts']['test']} · "
                           f"cost {wf['cost_pct_per_round_trip']}% round-trip · horizon {wf['horizon']}d")

                st.markdown("**Out-of-sample check — does the train-set edge survive on unseen test data?**")
                oos = wf.get("out_of_sample_check", [])
                if oos:
                    odf = pd.DataFrame(oos)
                    odf["direction_holds_out_of_sample"] = odf["direction_holds_out_of_sample"].map(
                        {True: "✅ holds", False: "❌ reverses"})
                    st.dataframe(odf, use_container_width=True, hide_index=True, height=320)
                    reversed_n = sum(1 for r in oos if not r["direction_holds_out_of_sample"])
                    st.caption(f"{reversed_n}/{len(oos)} patterns reverse direction out-of-sample — "
                               "the honest reason not to trust a single train-only backtest.")
                else:
                    st.info("No patterns had enough sample in both train and test to compare.")

                st.markdown("**Calibration — TRAIN-predicted win rate vs ACTUAL win rate in held-out TEST**")
                calib = wf.get("calibration", [])
                if calib:
                    cdf = pd.DataFrame(calib)
                    st.dataframe(cdf[["bin", "predicted_win_rate_from_train", "actual_win_rate_in_test",
                                      "calibration_gap", "test_n", "patterns"]],
                                use_container_width=True, hide_index=True)
                    st.caption("A well-calibrated system has actual ≈ predicted with small gaps. Large gaps "
                               "(especially in the highest-predicted bin) mean the score should NOT be read "
                               "as a literal probability yet.")
                else:
                    st.caption("Not enough patterns with both train and test samples to build calibration bins.")

                st.markdown("**Feature importance — correlation with forward-win outcome (TRAIN only)**")
                fi = wf.get("feature_importance", {})
                if fi.get("status") == "ok":
                    fidf = pd.DataFrame(fi["ranked"])
                    st.dataframe(fidf, use_container_width=True, hide_index=True)
                    st.caption(fi.get("note", ""))
                else:
                    st.caption(fi.get("status", "Feature importance unavailable."))

                st.caption(wf.get("note", ""))

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">🌦️ Regime-Split Backtest</div>', unsafe_allow_html=True)
            st.caption("Splits every real detected signal by KSE-100-derived market regime (Bull/Bear/Range) "
                       "and by each stock's own trailing volatility regime — does a pattern's edge actually "
                       "hold across regimes, or does the pooled number hide that it only works in bull markets? "
                       "Auto-refreshes daily — no click needed for routine use.")
            if st.button("Force re-run regime-split now", type="secondary"):
                params = {"force": "true"}
                if more_token:
                    params["token"] = more_token
                rg = requests.post(f"{BACKEND}/backtest/regime-split", params=params, timeout=30).json()
                if rg.get("status") == "ok":
                    st.session_state["regime_result"] = rg
                    if rg.get("_background_refresh_running"):
                        st.toast("Recompute running in the background — showing last known result.", icon="🔄")
                else:
                    st.error(rg.get("reason", "Regime-split backtest failed."))
            if "regime_result" not in st.session_state:
                try:
                    cached_rg = requests.post(f"{BACKEND}/backtest/regime-split", timeout=15).json()
                    if cached_rg.get("status") == "ok":
                        st.session_state["regime_result"] = cached_rg
                except requests.exceptions.Timeout:
                    st.session_state["regime_result"] = None
                    st.caption("⏳ Still computing in the background (first run after startup) — check back shortly.")
            rg = st.session_state.get("regime_result")
            if rg:
                if "_cache_age_seconds" in rg:
                    st.caption(f"Cached {rg['_cache_age_seconds']}s ago")
                st.caption(f"{rg['universe_symbols']} symbols · signal counts by market regime: "
                           f"{rg['counts']['market_regime']}")
                st.markdown("**Pattern performance shift across market regimes** (only patterns with a real "
                            "sample in 2+ regimes)")
                shift_rows = []
                for pat, regs in rg.get("pattern_regime_shift", {}).items():
                    row = {"pattern": pat}
                    for reg_name in ("Bull", "Bear", "Range"):
                        v = regs.get(reg_name)
                        row[f"{reg_name}_n"] = v["n"] if v else None
                        row[f"{reg_name}_win%"] = v["win_rate"] if v else None
                        row[f"{reg_name}_exp%"] = v["expectancy"] if v else None
                    shift_rows.append(row)
                if shift_rows:
                    st.dataframe(pd.DataFrame(shift_rows), use_container_width=True, hide_index=True, height=350)
                st.caption(rg.get("note", ""))

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">🧭 PSX-Specific Edge Discovery</div>', unsafe_allow_html=True)
            st.caption("Tests combinations beyond the fixed textbook pattern library — RVOL>90th-percentile "
                       "breakout + successful 3-day retest, and a low-volume Spring test — with the identical "
                       "walk-forward machinery every other pattern is held to, so any 'edge' claim is honest. "
                       "Auto-refreshes daily — no click needed for routine use.")
            if st.button("Force re-run edge discovery now", type="secondary"):
                params = {"force": "true"}
                if more_token:
                    params["token"] = more_token
                ed = requests.post(f"{BACKEND}/backtest/discover-edges", params=params, timeout=30).json()
                if ed.get("status") == "ok":
                    st.session_state["edge_result"] = ed
                    if ed.get("_background_refresh_running"):
                        st.toast("Recompute running in the background — showing last known result.", icon="🔄")
                else:
                    st.error(ed.get("reason", "Edge discovery failed."))
            if "edge_result" not in st.session_state:
                try:
                    cached_ed = requests.post(f"{BACKEND}/backtest/discover-edges", timeout=15).json()
                    if cached_ed.get("status") == "ok":
                        st.session_state["edge_result"] = cached_ed
                except requests.exceptions.Timeout:
                    st.session_state["edge_result"] = None
                    st.caption("⏳ Still computing in the background (first run after startup) — check back shortly.")
            ed = st.session_state.get("edge_result")
            if ed:
                if "_cache_age_seconds" in ed:
                    st.caption(f"Cached {ed['_cache_age_seconds']}s ago")
                for key in ("edge_a", "edge_b"):
                    e = ed.get(key, {})
                    st.markdown(f"**{e.get('name')}** — {e.get('n_signals')} signals")
                    st20 = (e.get("stats_by_horizon") or {}).get("20") or (e.get("stats_by_horizon") or {}).get(20)
                    if st20:
                        st.dataframe(pd.DataFrame([st20]), use_container_width=True, hide_index=True)
                st.caption(ed.get("note", ""))
                st.info("Compare the expectancy above against /backtest/status's textbook patterns and the "
                        "random_entry baseline (Backtest Lab panel above) to judge honestly whether either "
                        "combination is worth tracking as a real PSX-specific edge.")

    with subtab_status:
        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">🌐 Live Indices (psxterminal.com)</div>', unsafe_allow_html=True)
            st.caption("Per-stock live data is gated (403) on psxterminal.com's current "
                       "API — see backend/psx_live.py. Index-level data below is real "
                       "and confirmed working.")
            lm = _get("/live-market")
            if lm.get("status") == "ok":
                if lm.get("index_report"):
                    st.text(lm["index_report"])
                if lm.get("indices"):
                    st.dataframe(pd.DataFrame(lm["indices"]).T, use_container_width=True)
            else:
                st.info(lm.get("reason", "Live market unavailable."))

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">🎓 Learning Status</div>', unsafe_allow_html=True)
            ls = _get("/learning-status")
            if "runs_stored" in ls:
                m1, m2, m3 = st.columns(3)
                m1.metric("Runs stored", ls.get("runs_stored"))
                m2.metric("Strictly graded", ls.get("strictly_graded"))
                m3.metric("Win rate", f"{ls['win_rate']}%" if ls.get("win_rate") is not None else "—")
                st.caption(ls.get("confidence_effect", ""))
                st.caption(ls.get("note", ""))
            else:
                st.info(ls.get("reason", "Learning status unavailable."))

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">📋 PSX Announcements</div>', unsafe_allow_html=True)
            st.markdown("[Open PSX announcements portal](https://dps.psx.com.pk/announcements/companies)")

        with st.container(border=True):
            st.markdown('<div class="psx-panel-title">💓 Backend Health</div>', unsafe_allow_html=True)
            h = _get("/health")
            if h.get("ok"):
                st.success(f"Backend OK · {h.get('market_data')} · {h.get('freshness')}")
                st.caption(f"Checked {h.get('time')}")
                st.caption(h.get("policy", ""))
            else:
                st.error(h.get("reason", "Backend unreachable."))
