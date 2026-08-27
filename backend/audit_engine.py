"""audit_engine.py — daily update mode, signal state machine, alerts, audit
trail, and failure analysis (STEPS 67-71 of the source framework).

Every /dss/{symbol} call saves a snapshot (STEP 70: date, score, grade,
action, Wyckoff phase/events, entry/stop/target, and the full raw result for
later inspection). The next call for the same symbol diffs against the prior
snapshot (STEP 67: "what changed?") and maps the Wyckoff event sequence onto
a lifecycle stage (STEP 68) so the system doesn't re-announce "BUY" at every
step of one unfolding setup.

Failure analysis (STEP 71) is retroactive and evidence-based: once enough
real trading days have passed after a BUY-leaning snapshot, it checks what
actually happened in the stored true-OHLC (target hit / stop hit / neither)
and, for losses, cites the recorded conditions at signal time (thin R:R, no
confirmed Wyckoff event, high event risk, weak grade) — never a guess dressed
up as certainty.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

DB = os.getenv("PSX_DB", "psx_v2.db")

BUY_LIKE = {"STRONG BUY", "BUY", "ACCUMULATE", "WATCH FOR BUY"}
SELL_LIKE = {"STRONG SELL / AVOID", "SELL / REDUCE", "WATCH FOR SELL"}


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_tables():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS dss_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, saved_at TEXT, evidence_score REAL, confidence_grade TEXT,
            final_action TEXT, wyckoff_phase TEXT, wyckoff_events TEXT,
            price REAL, invalidation REAL, target_1 REAL, reward_risk REAL,
            raw_json TEXT);
        CREATE INDEX IF NOT EXISTS ix_dss_history_symbol ON dss_history(symbol, saved_at);
        """)
        c.commit()


def latest_snapshot(symbol):
    ensure_tables()
    with _conn() as c:
        row = c.execute("SELECT * FROM dss_history WHERE symbol=? ORDER BY id DESC LIMIT 1",
                         (symbol.upper(),)).fetchone()
    return dict(row) if row else None


def get_history(symbol, limit=30):
    ensure_tables()
    with _conn() as c:
        rows = c.execute("""SELECT symbol, saved_at, evidence_score, confidence_grade, final_action,
                            wyckoff_phase, price, invalidation, target_1, reward_risk
                            FROM dss_history WHERE symbol=? ORDER BY id DESC LIMIT ?""",
                          (symbol.upper(), limit)).fetchall()
    return [dict(r) for r in rows]


def save_snapshot(symbol, dss_result, wyckoff_events=None):
    """Saves the snapshot AFTER the caller has already fetched the prior one
    for diffing — order matters, see app.py's call site."""
    ensure_tables()
    sym = symbol.upper()
    risk = dss_result.get("risk", {})
    events = []
    if wyckoff_events:
        events = (wyckoff_events.get("accumulation", {}).get("sequence_found", []) +
                  wyckoff_events.get("distribution", {}).get("sequence_found", []))
    with _conn() as c:
        c.execute("""INSERT INTO dss_history
            (symbol, saved_at, evidence_score, confidence_grade, final_action, wyckoff_phase,
             wyckoff_events, price, invalidation, target_1, reward_risk, raw_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sym, datetime.now(timezone.utc).isoformat(), dss_result.get("evidence_score"),
             dss_result.get("confidence_grade"), dss_result.get("final_action"),
             (dss_result.get("wyckoff") or {}).get("phase"), json.dumps(events),
             (dss_result.get("quote") or {}).get("price"), risk.get("invalidation"),
             risk.get("target_1"), risk.get("reward_risk"), json.dumps(dss_result)))
        c.commit()


def diff_snapshots(prev, curr_result, wyckoff_events=None):
    """STEP 67: what changed since the last check? None if there's no prior
    snapshot to compare (first time this symbol was ever checked)."""
    if not prev:
        return None
    curr_events = set()
    if wyckoff_events:
        curr_events = set(wyckoff_events.get("accumulation", {}).get("sequence_found", []) +
                          wyckoff_events.get("distribution", {}).get("sequence_found", []))
    prev_events = set(json.loads(prev.get("wyckoff_events") or "[]"))
    new_events = sorted(curr_events - prev_events)

    score_delta = round((curr_result.get("evidence_score") or 0) - (prev.get("evidence_score") or 0), 1)
    action_changed = prev.get("final_action") != curr_result.get("final_action")
    grade_changed = prev.get("confidence_grade") != curr_result.get("confidence_grade")
    meaningful = action_changed or grade_changed or abs(score_delta) >= 8 or bool(new_events)

    return {
        "prior_checked_at": prev.get("saved_at"),
        "prior_action": prev.get("final_action"), "prior_score": prev.get("evidence_score"),
        "prior_grade": prev.get("confidence_grade"),
        "score_delta": score_delta, "action_changed": action_changed, "grade_changed": grade_changed,
        "new_events": new_events, "meaningful_change": meaningful,
    }


# ------------------------------------------------------------- signal state --
_ACCUM_CHAIN = ["SC", "AR", "ST", "SPRING", "TEST", "SOS", "LPS"]
_DISTRIB_CHAIN = ["BC", "PSY", "AR", "ST", "UT", "SOW", "LPSY"]


def signal_state(wyckoff_events, action):
    """STEP 68: map the furthest-reached point in the accumulation or
    distribution event chain onto one lifecycle label, so the UI shows
    'SOS confirmed, LPS forming' instead of re-declaring BUY at every step."""
    if not wyckoff_events:
        return {"stage": "NO STRUCTURE DETECTED", "chain": [], "furthest": None}
    accum = set(wyckoff_events.get("accumulation", {}).get("sequence_found", []))
    distrib = set(wyckoff_events.get("distribution", {}).get("sequence_found", []))

    accum_reached = [e for e in _ACCUM_CHAIN if e in accum]
    distrib_reached = [e for e in _DISTRIB_CHAIN if e in distrib]

    if accum_reached and len(accum_reached) >= len(distrib_reached):
        furthest = accum_reached[-1]
        stage_names = {"SC": "SELLING CLIMAX DETECTED", "AR": "AUTOMATIC RALLY", "ST": "SECONDARY TEST",
                       "SPRING": "SPRING DETECTED", "TEST": "SPRING TEST SUCCESSFUL",
                       "SOS": "SIGN OF STRENGTH CONFIRMED", "LPS": "LAST POINT OF SUPPORT — MARKUP LIKELY NEXT"}
        return {"stage": stage_names.get(furthest, furthest), "chain": accum_reached,
                "furthest": furthest, "sequence": "accumulation"}
    if distrib_reached:
        furthest = distrib_reached[-1]
        stage_names = {"BC": "BUYING CLIMAX DETECTED", "PSY": "PRELIMINARY SUPPLY", "AR": "AUTOMATIC REACTION",
                       "ST": "SECONDARY TEST", "UT": "UPTHRUST DETECTED", "SOW": "SIGN OF WEAKNESS CONFIRMED",
                       "LPSY": "LAST POINT OF SUPPLY — MARKDOWN LIKELY NEXT"}
        return {"stage": stage_names.get(furthest, furthest), "chain": distrib_reached,
                "furthest": furthest, "sequence": "distribution"}
    return {"stage": "NO STRUCTURE DETECTED", "chain": [], "furthest": None}


# ------------------------------------------------------------ failure grading --
def _outcome_for_snapshot(row, subsequent_ohlc, horizon_days=20):
    """Did price hit target_1 or invalidation first within horizon_days of
    real subsequent bars? 'pending' if not enough time has passed yet."""
    if len(subsequent_ohlc) < 1:
        return "pending", None
    target, stop = row.get("target_1"), row.get("invalidation")
    entry = row.get("price")
    if not entry:
        return "unknown", None
    hit_target_at, hit_stop_at = None, None
    for i, b in enumerate(subsequent_ohlc[:horizon_days]):
        if target and hit_target_at is None and b["high"] >= target:
            hit_target_at = i
        if stop and hit_stop_at is None and b["low"] <= stop:
            hit_stop_at = i
        if hit_target_at is not None or hit_stop_at is not None:
            break
    if hit_target_at is not None and (hit_stop_at is None or hit_target_at <= hit_stop_at):
        return "win", hit_target_at
    if hit_stop_at is not None:
        return "loss", hit_stop_at
    if len(subsequent_ohlc) >= horizon_days:
        final = subsequent_ohlc[horizon_days - 1]["close"]
        return ("win" if entry and final > entry else "loss"), horizon_days
    return "pending", None


def _failure_reason(raw):
    """STEP 71: cite what the recorded snapshot actually showed, never guess
    beyond it."""
    reasons = []
    if (raw.get("risk", {}).get("reward_risk") or 99) < 1.5:
        reasons.append("Reward/risk was weak (<1.5) at signal time")
    grade = raw.get("confidence_grade")
    if grade in ("D", "F"):
        reasons.append(f"Confidence grade was already weak ({grade})")
    phase = (raw.get("wyckoff") or {}).get("phase", "")
    if "UNRESOLVED" in phase or not phase:
        reasons.append("Wyckoff phase was unresolved, not confirmed accumulation")
    if (raw.get("event_risk") or {}).get("level") == "HIGH":
        reasons.append("A HIGH-materiality announcement coincided with the signal")
    n_bear = raw.get("bearish_components", 0)
    n_bull = raw.get("bullish_components", 0)
    if n_bear and n_bull and n_bear >= n_bull:
        reasons.append(f"Bearish components ({n_bear}) matched or exceeded bullish ({n_bull}) even at signal time")
    return reasons or ["No obvious contradicting evidence was recorded — genuine statistical variance."]


def grade_outcomes(ohlc_lookup, min_age_days=20, horizon_days=20):
    """ohlc_lookup: callable(symbol) -> ascending true-OHLC rows (so this
    module doesn't need to know how app.py fetches them). Grades every
    BUY-leaning snapshot old enough to have a real subsequent-price verdict."""
    ensure_tables()
    with _conn() as c:
        rows = c.execute("SELECT * FROM dss_history WHERE final_action IN (%s) ORDER BY id" %
                          ",".join("?" * len(BUY_LIKE)), tuple(BUY_LIKE)).fetchall()
    graded = []
    for row in rows:
        row = dict(row)
        saved_at = datetime.fromisoformat(row["saved_at"])
        age_days = (datetime.now(timezone.utc) - saved_at).days
        if age_days < min_age_days:
            continue
        a = ohlc_lookup(row["symbol"])
        if not a:
            continue
        signal_date = saved_at.date().isoformat()
        subsequent = [b for b in a if b["trade_date"] > signal_date]
        outcome, hit_day = _outcome_for_snapshot(row, subsequent, horizon_days)
        raw = json.loads(row["raw_json"] or "{}")
        entry = {"symbol": row["symbol"], "saved_at": row["saved_at"], "action": row["final_action"],
                "score": row["evidence_score"], "grade": row["confidence_grade"],
                "outcome": outcome, "hit_after_days": hit_day}
        if outcome == "loss":
            entry["failure_reasons"] = _failure_reason(raw)
        graded.append(entry)
    wins = sum(1 for g in graded if g["outcome"] == "win")
    losses = sum(1 for g in graded if g["outcome"] == "loss")
    pending = sum(1 for g in graded if g["outcome"] == "pending")
    total_decided = wins + losses
    return {"graded": graded, "wins": wins, "losses": losses, "pending": pending,
            "win_rate": round(wins / total_decided * 100, 1) if total_decided else None,
            "note": f"Target vs invalidation race within {horizon_days} real trading days after each "
                    f"BUY-leaning snapshot at least {min_age_days} days old. 'pending' means not enough "
                    "time has passed yet to know."}
