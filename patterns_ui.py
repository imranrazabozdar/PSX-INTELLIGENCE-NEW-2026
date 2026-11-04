"""patterns_ui.py — shared, presentation-only components for the Patterns tab.

Everything here formats and lays out rows the existing modules already
produce. Nothing computes a score, rank, signal or probability, nothing
merges module results, and nothing talks to the backend: every value is
displayed exactly as the module supplied it (only number/date formatting,
the same formats the old tables used).

Colour system (badges only, always with a text label -- never colour alone):
  bull     green   bullish direction only
  bear     red     bearish direction only
  fire     orange  FIRE status
  caution  amber   caution / PRE-FIRE / stale
  info     blue    information, strength labels (EXTREME / READY / WATCH ...)
  research purple  Research / Experimental
  neutral  grey    everything else
"""
import html
import math
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

PAGE_CARDS = 10
PAGE_TABLE = 25
LAYOUT_KEY = "pui_layout"          # "Cards" | "Table", shared by every module
VIEW_KEY = "pui_view"

CSS = """
<style>
.pui-badge{display:inline-block;padding:1px 8px;margin:0 4px 4px 0;border-radius:999px;font-size:.74rem;
 font-weight:700;line-height:1.5;border:1px solid transparent;white-space:normal;word-break:break-word}
.pui-bull{color:#4ade80;background:rgba(34,197,94,.12);border-color:rgba(34,197,94,.45)}
.pui-bear{color:#f87171;background:rgba(239,68,68,.12);border-color:rgba(239,68,68,.45)}
.pui-fire{color:#fb923c;background:rgba(249,115,22,.14);border-color:rgba(249,115,22,.5)}
.pui-caution{color:#facc15;background:rgba(234,179,8,.13);border-color:rgba(234,179,8,.5)}
.pui-info{color:#93c5fd;background:rgba(59,130,246,.14);border-color:rgba(59,130,246,.45)}
.pui-research{color:#d8b4fe;background:rgba(168,85,247,.14);border-color:rgba(168,85,247,.45)}
.pui-neutral{color:#cbd5e1;background:rgba(148,163,184,.14);border-color:rgba(148,163,184,.45)}
.pui-eyebrow{font-size:.7rem;font-weight:800;letter-spacing:.08em;opacity:.7;text-transform:uppercase}
.pui-title{font-size:1.08rem;font-weight:800;margin:0 0 2px;line-height:1.3}
.pui-meta{font-size:.8rem;opacity:.75;margin-bottom:4px}
.pui-card{border:1px solid rgba(148,163,184,.35);border-radius:10px;padding:10px 12px;margin:0 0 8px}
.pui-card-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px;margin-bottom:4px}
.pui-sym{font-weight:800;font-size:1rem}
.pui-co{font-size:.8rem;opacity:.75;flex-basis:100%}
.pui-kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:2px 12px;font-size:.84rem}
.pui-kv div span{opacity:.65;font-size:.74rem;display:block}
.pui-note{font-size:.78rem;opacity:.8;margin-top:4px}
.pui-bar{margin:3px 0}.pui-bar-l{font-size:.74rem;opacity:.75;display:flex;justify-content:space-between}
.pui-bar-t{height:7px;border-radius:4px;background:rgba(148,163,184,.25);overflow:hidden}
.pui-bar-f{height:100%;background:#64748b}
.pui-bar-f.bull{background:#22c55e}.pui-bar-f.bear{background:#ef4444}.pui-bar-f.info{background:#3b82f6}
.pui-sum{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:8px}
@media (min-width:700px){.pui-sum{grid-template-columns:repeat(4,1fr)}}
.pui-sum div{border:1px solid rgba(148,163,184,.35);border-radius:10px;padding:8px 10px}
.st-key-pui_view,.st-key-vol_subview{width:100%!important;max-width:100%!important}
.st-key-pui_view [role=radiogroup],.st-key-vol_subview [role=radiogroup]{flex-wrap:wrap!important;overflow:visible!important;
 row-gap:6px}
.pui-sum b{display:block;font-size:1.3rem}.pui-sum span{font-size:.75rem;opacity:.75}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------- text --
def esc(x):
    return html.escape(str(x))


def badge(text, variant="neutral"):
    return f'<span class="pui-badge pui-{variant}">{esc(text)}</span>'


def badges(items):
    return "".join(badge(t, v) for t, v in items if t not in (None, ""))


def is_blank(v):
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and v.strip() in ("", "None", "nan", "—")


def friendly_age(seconds=None, iso=None):
    """'Updated 5h ago' from a cache age in seconds or an ISO timestamp."""
    if seconds is None and iso:
        try:
            t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            seconds = (datetime.now(timezone.utc) - t).total_seconds()
        except ValueError:
            return "Update time unknown"
    if not isinstance(seconds, (int, float)):
        return "Update time unknown"
    s = max(0, int(seconds))
    if s < 90:
        return "Updated just now"
    if s < 3600:
        return f"Updated {s // 60} min ago"
    if s < 86400 * 2:
        return f"Updated {s // 3600}h ago"
    return f"Updated {s // 86400}d ago"


def fmt(v, f=None, kind="text"):
    """Value as text, with the same format string the old table used."""
    if is_blank(v):
        return None
    if kind == "date":
        try:
            return pd.to_datetime(v).strftime("%b %d, %Y")
        except (ValueError, TypeError):
            return str(v)
    if kind == "bool":
        return "Yes" if bool(v) else "No"
    if f and isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return f % v
        except (TypeError, ValueError):
            return str(v)
    return str(v)


# --------------------------------------------------------------- fields --
def F(col, label, fmt_=None, kind="text", help=None, primary=True, card=True, bar=None):
    """One displayed field. bar = progress-bar variant ('bull'/'bear'/'info')."""
    return {"col": col, "label": label, "fmt": fmt_, "kind": kind, "help": help, "primary": primary,
            "card": card, "bar": bar}


def _column_config(fields, symbol_col):
    cfg = {}
    for f in fields:
        c, lab, h = f["col"], f["label"], f["help"]
        pinned = True if c == symbol_col else None
        if f["bar"]:
            cfg[c] = st.column_config.ProgressColumn(lab, help=h, min_value=0, max_value=100, format="%d",
                                                     pinned=pinned)
        elif f["kind"] == "date":
            cfg[c] = st.column_config.DateColumn(lab, help=h, format="MMM DD, YYYY", pinned=pinned)
        elif f["kind"] == "num" and f["fmt"]:
            cfg[c] = st.column_config.NumberColumn(lab, help=h, format=f["fmt"], pinned=pinned)
        elif f["kind"] == "bool":
            cfg[c] = st.column_config.CheckboxColumn(lab, help=h, pinned=pinned)
        else:
            cfg[c] = st.column_config.TextColumn(lab, help=h, pinned=pinned)
    return cfg


def _bar(label, v, variant):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    w = max(0.0, min(100.0, x))
    return (f'<div class="pui-bar"><div class="pui-bar-l"><span>{esc(label)}</span><span>{esc(fmt(v, "%g"))}</span></div>'
            f'<div class="pui-bar-t"><div class="pui-bar-f {variant}" style="width:{w:.0f}%"></div></div></div>')


def card_html(row, fields, symbol_col, company_col, badge_fn=None, note_cols=()):
    head = f'<span class="pui-sym">{esc(row.get(symbol_col))}</span>'
    if badge_fn:
        head += badges(badge_fn(row))
    co = row.get(company_col) if company_col else None
    if not is_blank(co):
        head += f'<span class="pui-co">{esc(co)}</span>'
    bars, kv = [], []
    for f in fields:
        if not f["card"] or not f["primary"] or f["col"] in (symbol_col, company_col) or f["col"] in note_cols:
            continue
        v = row.get(f["col"])
        if f["bar"]:
            b = _bar(f["label"], v, f["bar"])
            if b:
                bars.append(b)
            continue
        s = fmt(v, f["fmt"], f["kind"])
        if s is None:
            continue
        kv.append(f"<div><span>{esc(f['label'])}</span>{esc(s)}</div>")
    notes = "".join(f'<div class="pui-note">{esc(lab)}: {esc(row.get(c))}</div>'
                    for c, lab in note_cols_labels(note_cols, fields) if not is_blank(row.get(c)))
    return (f'<div class="pui-card"><div class="pui-card-head">{head}</div>{"".join(bars)}'
            f'<div class="pui-kv">{"".join(kv)}</div>{notes}</div>')


def note_cols_labels(note_cols, fields):
    labels = {f["col"]: f["label"] for f in fields}
    return [(c, labels.get(c, c)) for c in note_cols]


def results(df, key, fields, symbol_col="symbol", company_col="company", badge_fn=None, note_cols=(),
            on_open=None, empty_msg="No rows.", open_label="🎯 Open {sym} in Stock Research"):
    """Cards (default) or Table for a module's full row set, with Show more.

    The row ORDER of `df` is kept exactly (it is the module's own order).
    on_open(symbol) is called when a row/card is selected -- the existing
    "open in Stock Research" path."""
    if df is None or len(df) == 0:
        st.info(empty_msg)
        return
    total = len(df)
    layout = st.session_state.get(LAYOUT_KEY, "Cards")
    page = PAGE_CARDS if layout == "Cards" else PAGE_TABLE
    nkey = f"{key}__shown"
    shown = min(total, st.session_state.get(nkey, page))
    view = df.iloc[:shown]
    if layout == "Cards":
        for i, (_, row) in enumerate(view.iterrows()):
            r = row.to_dict()
            st.markdown(card_html(r, fields, symbol_col, company_col, badge_fn, note_cols), unsafe_allow_html=True)
            if on_open and st.button(open_label.format(sym=r[symbol_col]), key=f"{key}__open_{i}",
                                     type="tertiary"):
                st.session_state[f"{key}__card_open"] = r[symbol_col]   # keeps an in-page detail open
                on_open(r[symbol_col])
    else:
        nonempty = [f for f in fields if f["col"] in df.columns
                    and not df[f["col"]].map(lambda v: is_blank(v) and v != "—").all()]
        show_all = st.toggle("Show all columns", key=f"{key}__allcols")
        cols = [f["col"] for f in (fields if show_all else [f for f in nonempty if f["primary"]])
                if f["col"] in df.columns]
        if symbol_col in cols:
            cols = [symbol_col] + [c for c in cols if c != symbol_col]
        sel = st.dataframe(view, hide_index=True, use_container_width=True, key=key, column_order=cols,
                           column_config=_column_config(fields, symbol_col), on_select="rerun",
                           selection_mode="single-row", height=min(38 + 35 * len(view), 38 + 35 * PAGE_TABLE))
        rows = sel.selection.rows if sel and getattr(sel, "selection", None) else []
        if rows and on_open:
            on_open(view.iloc[rows[0]][symbol_col])
        st.caption("Tap a row to open it. Turn on “Show all columns” for every field.")
    if shown < total:
        c1, c2 = st.columns([1, 1])
        c1.caption(f"{shown} of {total} shown")
        if c2.button(f"Show {min(page, total - shown)} more", key=f"{key}__more", use_container_width=True):
            st.session_state[nkey] = shown + page
            st.rerun()
    elif total > page:
        st.caption(f"All {total} shown")


# -------------------------------------------------------------- modules --
def module_header(m):
    """m: dict(category, name, timeframe, status, status_variant, count, age, count_label)."""
    title = m["name"] + (f" — {m['timeframe']}" if m.get("timeframe") else "")
    tags = []
    if m.get("status"):
        tags.append((m["status"], m.get("status_variant") or "neutral"))
    if m.get("count") is not None:
        tags.append((f"{m['count']} {m.get('count_label', 'signal' if m['count'] == 1 else 'signals')}", "info"))
    st.markdown(f'<div class="pui-eyebrow">{esc(m.get("category", ""))}</div>'
                f'<div class="pui-title">{esc(title)}</div>'
                f'<div class="pui-meta">{badges(tags)} {esc(m.get("updated") or friendly_age(m.get("age")))}</div>',
                unsafe_allow_html=True)


def render_module(m):
    """Header, always-visible notes/warnings, results, one collapsed Details."""
    with st.container(border=True):
        module_header(m)
        if m.get("state_msg"):
            kind, msg = m["state_msg"]
            getattr(st, kind)(msg)
        for kind, msg in m.get("warnings", []):
            getattr(st, kind)(msg)
        if m.get("body"):
            m["body"]()
        if m.get("details"):
            with st.expander("Details"):
                m["details"]()


def render_view(mods, empty_title="No signal today"):
    """Modules with signals in their original order, then a compact group of
    the zero-signal ones (name + update time, Details still available)."""
    live = [m for m in mods if (m.get("count") or 0) > 0 or m.get("always_show")]
    quiet = [m for m in mods if m not in live]
    for m in live:
        render_module(m)
    if quiet:
        st.markdown(f'<div class="pui-eyebrow" style="margin-top:8px">{esc(empty_title)} · {len(quiet)} '
                    f'module{"s" if len(quiet) != 1 else ""}</div>', unsafe_allow_html=True)
        for m in quiet:
            if m.get("short_warning"):
                st.warning(m["short_warning"])
            label = (f"{m['name']}" + (f" — {m['timeframe']}" if m.get("timeframe") else "")
                     + f" · {m.get('updated') or friendly_age(m.get('age'))}")
            if m.get("state_msg"):
                label += " · unavailable"
            with st.expander(label):
                if m.get("status"):
                    st.markdown(badge(m["status"], m.get("status_variant") or "neutral"), unsafe_allow_html=True)
                if m.get("state_msg"):
                    kind, msg = m["state_msg"]
                    getattr(st, kind)(msg)
                for kind, msg in m.get("warnings", []):
                    getattr(st, kind)(msg)
                if m.get("empty_msg"):
                    st.caption(m["empty_msg"])
                if m.get("details"):
                    st.markdown("**Details**")
                    m["details"]()


def summary_tiles(items):
    st.markdown('<div class="pui-sum">' + "".join(
        f"<div><b>{esc(v)}</b><span>{esc(k)}</span></div>" for k, v in items) + "</div>", unsafe_allow_html=True)
