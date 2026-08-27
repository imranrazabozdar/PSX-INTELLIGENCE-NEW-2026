"""psxwatch_bridge.py — read-only bridge into the Engine Fundamentals project's
psxwatch.db (news impact scores, computed ratios, driver-exposure priors,
verified exposure evidence).

Deliberately READ-ONLY and separate from this backend's own psx_v2.db: the two
projects have their own writers, their own schemas, and their own test suites
(psxwatch's `./run_tests.sh`, 195 assertions). Merging schemas would couple two
independently-tested systems for no benefit. This module only SELECTs.

Every function fails soft — missing DB file, missing table (psxwatch.db is
created lazily by whichever psxwatch module runs first, so a fresh checkout may
be missing tables this bridge expects), or no row for a symbol all return None
or [], never a fabricated value. Per HANDOFF.md, psxwatch has never seen real
data in its own sandbox, so on a fresh setup every one of these will legitimately
return "not available" until psxwatch actually gets run against real filings —
that is the honest state, not a bug in the bridge.
"""

import json
import os
import sqlite3

DB = os.getenv(
    "PSXWATCH_DB",
    os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "Engine Fundamentals", "psxwatch.db")),
)


def _conn():
    if not os.path.exists(DB):
        return None
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _table_exists(c, name):
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def news_impact(ticker, limit=20):
    """Recent evidence-quoted news impact scores for one ticker (analyze.py)."""
    c = _conn()
    if c is None:
        return {"status": "unavailable", "reason": f"psxwatch.db not found at {DB}"}
    try:
        if not _table_exists(c, "scores"):
            return {"status": "unavailable", "reason": "scores table not created yet — run psxwatch.ingest/.analyze"}
        rows = c.execute(
            """SELECT s.*, a.title, a.url, a.published, a.source_name
               FROM scores s JOIN articles a ON a.id = s.article_id
               WHERE s.ticker=? AND (a.dup_of IS NULL OR a.dup_of='')
               ORDER BY s.scored_at DESC LIMIT ?""",
            (ticker.upper(), limit),
        ).fetchall()
        return {"status": "ok", "ticker": ticker.upper(),
                "items": [dict(r) for r in rows]}
    except sqlite3.Error as e:
        return {"status": "error", "reason": str(e)}
    finally:
        c.close()


def fundamentals_deep(ticker):
    """Most recent computed ratio set for one ticker (ratios.py, via context.py's
    ratio_history table) — the deterministic 53-metric engine's output."""
    c = _conn()
    if c is None:
        return {"status": "unavailable", "reason": f"psxwatch.db not found at {DB}"}
    try:
        if not _table_exists(c, "ratio_history"):
            return {"status": "unavailable", "reason": "ratio_history table not created yet — run psxwatch.report"}
        row = c.execute(
            """SELECT * FROM ratio_history WHERE ticker=?
               ORDER BY period_end DESC LIMIT 1""",
            (ticker.upper(),),
        ).fetchone()
        if not row:
            return {"status": "not_found", "ticker": ticker.upper(),
                    "reason": "no stored ratio history for this ticker"}
        out = dict(row)
        try:
            out["ratios"] = json.loads(out.pop("ratios_json"))
        except Exception:
            pass
        out["status"] = "ok"
        return out
    except sqlite3.Error as e:
        return {"status": "error", "reason": str(e)}
    finally:
        c.close()


def exposure(ticker):
    """Driver-exposure priors for one ticker (exposure.py's seeded matrix).
    Every row is a PRIOR — confidence <=0.6 by construction, not a measurement."""
    c = _conn()
    if c is None:
        return {"status": "unavailable", "reason": f"psxwatch.db not found at {DB}"}
    try:
        if not _table_exists(c, "exposures"):
            return {"status": "unavailable", "reason": "exposures table not created yet — run exposure.seed()"}
        rows = c.execute(
            "SELECT * FROM exposures WHERE ticker=? ORDER BY driver_id",
            (ticker.upper(),),
        ).fetchall()
        return {"status": "ok", "ticker": ticker.upper(),
                "exposures": [dict(r) for r in rows],
                "note": "Every exposure is a PRIOR, not a measurement — see "
                        "exposure_evidence for anything verify.py has checked "
                        "against a real annual report."}
    except sqlite3.Error as e:
        return {"status": "error", "reason": str(e)}
    finally:
        c.close()


def exposure_evidence(ticker):
    """verify.py's grounded reconciliation output: derived vs prior, per driver."""
    c = _conn()
    if c is None:
        return {"status": "unavailable", "reason": f"psxwatch.db not found at {DB}"}
    try:
        if not _table_exists(c, "exposure_evidence"):
            return {"status": "unavailable", "reason": "exposure_evidence table not created yet — run psxwatch.verify"}
        rows = c.execute(
            "SELECT * FROM exposure_evidence WHERE ticker=? ORDER BY created_at DESC",
            (ticker.upper(),),
        ).fetchall()
        return {"status": "ok", "ticker": ticker.upper(),
                "evidence": [dict(r) for r in rows]}
    except sqlite3.Error as e:
        return {"status": "error", "reason": str(e)}
    finally:
        c.close()
