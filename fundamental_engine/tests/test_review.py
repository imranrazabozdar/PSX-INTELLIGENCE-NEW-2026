import json
import sqlite3

import pytest

from core import migrate
from core.db import SqliteClient, sqlite_connect
from llm.providers import ScriptedProvider
from llm.router import Router
from review import accept, queue
from tests.conftest import add_company, add_item, add_source

HEAD = "OGDC announces final cash dividend for FY2026"
CAND = json.dumps({"event_type": "dividend", "tickers": ["OGDC"], "confidence_band": "medium",
                   "claims": [{"kind": "quote", "text": "OGDC announces final cash dividend for FY2026"},
                              {"kind": "inference", "text": "Shareholders may expect a payout"}]})
NO_QUOTE = json.dumps({"event_type": "other", "tickers": [], "confidence_band": "low", "claims": []})


def mark_baseline(d):
    """Make a baseline-schema DB look like the live one: schema_migrations already at version 10."""
    d.execute("INSERT INTO schema_migrations(version,name,checksum,applied_at_utc,result) VALUES(10,'market_ohlcv',?,'t','applied')", ("e" * 64,))


@pytest.fixture
def rv(db):
    mark_baseline(db)
    migrate.apply(db)                                    # baseline already recorded: runner must add only 0011
    add_source(db, "news", stype="news_media"); add_company(db, "OGDC")
    return db


def candidate(db, reply=CAND, title=HEAD, ext="a"):
    item = db.execute("INSERT INTO source_items(source_id,external_id,title,collected_at_utc,content_sha256) VALUES('news',?,?,'2026-11-09T00:00:00Z',?)",
                      (ext, title, "a" * 64)).lastrowid
    Router(db, [ScriptedProvider("groq", "m", [reply])]).extract(item, title)
    return db.execute("select extraction_id from event_extractions where source_item_id=?", (item,)).one()["extraction_id"]


# ------------------------------------------------------------------ migration 0011
def test_baseline_db_gets_only_0011_and_it_is_idempotent(db):
    mark_baseline(db)
    assert migrate.apply(db, dry_run=True) == [(11, "extraction_reviews")]
    migrate.apply(db)
    assert db.execute("select version from schema_migrations order by version desc limit 1").one()["version"] == 11
    assert migrate.apply(db, dry_run=True) == []


def test_marker_split_path_used_for_turso_style_clients():
    class NoScript(SqliteClient):                           # a client without .script(), like TursoClient
        script = property(lambda self: (_ for _ in ()).throw(AttributeError()))
    d = NoScript()
    SqliteClient.script(d, (migrate.MIG_DIR / "0010_baseline_snapshot.sql").read_text())
    mark_baseline(d)
    assert not hasattr(d, "script")
    migrate.apply(d)
    assert d.execute("select count(*) n from sqlite_master where name in ('extraction_reviews','v_review_queue','trg_extraction_reviews_no_update')").one()["n"] == 3


def test_reviews_are_append_only_and_accept_requires_event(rv):
    ex = candidate(rv)
    ins = "INSERT INTO extraction_reviews(extraction_id,decision,reviewer,notes,event_id,decided_at_utc) VALUES(?,?,?,?,?,'2026-11-09T12:00:00Z')"
    with pytest.raises(sqlite3.IntegrityError):
        rv.execute(ins, (ex, "accept", "Imran", "ok", None))              # accept without an event
    with pytest.raises(sqlite3.IntegrityError):
        rv.execute(ins, (ex, "reject", "I", "ok", None))                  # reviewer too short
    with pytest.raises(sqlite3.IntegrityError):
        rv.execute(ins, (ex, "reject", "Imran", "  ", None))              # blank notes
    rv.execute(ins, (ex, "reject", "Imran", "not relevant", None))
    for sql in ("UPDATE extraction_reviews SET notes='x'", "DELETE FROM extraction_reviews"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            rv.execute(sql)


# ------------------------------------------------------------------ queue
def test_queue_lists_pending_and_summarises(rv):
    ex = candidate(rv)
    rows = queue.pending(rv)
    s = queue.summarise(rows[0])
    assert [r["extraction_id"] for r in rows] == [ex] and s["reviewable"] and s["tickers"] == ["OGDC"]
    assert s["quotes"] == [("news_report", HEAD)] and s["inferences"] == ["Shareholders may expect a payout"]


def test_queue_hides_decided_but_keeps_needs_more_evidence(rv):
    a, b, c = candidate(rv, ext="a"), candidate(rv, title=HEAD + " today", ext="b"), candidate(rv, title=HEAD + " again", ext="c")
    for ex, dec in ((a, "reject"), (b, "needs_more_evidence")):
        accept.apply_plan(rv, accept.build_plan(queue.show(rv, ex), dec, "Imran", "checked"))
    assert [r["extraction_id"] for r in queue.pending(rv)] == [b, c]       # rejected one is gone, needs_more_evidence stays
    assert [r["extraction_id"] for r in rv.execute("select extraction_id from v_review_queue order by 1").rows] == [b, c]   # the view agrees


def test_queue_works_before_migration_treating_all_as_pending(db):
    add_source(db, "news", stype="news_media"); add_company(db, "OGDC")
    ex = candidate(db)
    assert [r["extraction_id"] for r in queue.pending(db)] == [ex]


# ------------------------------------------------------------------ accept / reject
def test_accept_creates_event_revision_evidence_and_decision(rv):
    ex = candidate(rv)
    plan = accept.build_plan(queue.show(rv, ex), "accept", "Imran", "headline matches the filing", status_stage="notification")
    assert plan["summary"] == {"decision": "accept", "extraction_id": ex, "evidence": 1, "company_links": 0}
    accept.apply_plan(rv, plan)
    ev = rv.execute("select * from events").one()
    assert ev["headline"] == HEAD and ev["summary"] is None and ev["verification_state"] == "single_source" and ev["confidence"] is None
    assert ev["status_stage"] == "notification" and ev["event_type"] == "dividend"
    assert rv.execute("select revision_no,changed_by,model_version from event_revisions").one() == {"revision_no": 1, "changed_by": "Imran", "model_version": "m"}
    evid = rv.execute("select * from event_evidence").rows
    assert len(evid) == 1 and evid[0]["claim"] == HEAD and evid[0]["claim_type"] == "news_report" and evid[0]["verification_state"] == "unverified"
    assert "payout" not in json.dumps([dict(x) for x in evid]) and "payout" not in ev["headline"]       # inference never becomes evidence
    rev = rv.execute("select decision,event_id from extraction_reviews").one()
    assert rev == {"decision": "accept", "event_id": ev["event_id"]}
    assert queue.pending(rv) == []


def test_accept_rejects_missing_reviewer_notes_stage_and_unquotable(rv):
    ex = candidate(rv)
    row = queue.show(rv, ex)
    for kw in ({"reviewer": "", "notes": "x"}, {"reviewer": "Imran", "notes": " "}):
        with pytest.raises(accept.ReviewError):
            accept.build_plan(row, "accept", **kw)
    with pytest.raises(accept.ReviewError, match="status_stage"):
        accept.build_plan(row, "accept", "Imran", "ok", status_stage="bogus")
    with pytest.raises(accept.ReviewError, match="decision"):
        accept.build_plan(row, "maybe", "Imran", "ok")
    ex2 = candidate(rv, NO_QUOTE, title="Pindi courts acquit most accused", ext="z")
    with pytest.raises(accept.ReviewError, match="no grounded quote"):
        accept.build_plan(queue.show(rv, ex2), "accept", "Imran", "ok")
    assert rv.execute("select count(*) n from events").one()["n"] == 0


def test_company_link_needs_reviewer_rationale_and_stays_pending(rv):
    ex = candidate(rv)
    row = queue.show(rv, ex)
    assert accept.build_plan(row, "accept", "Imran", "ok")["summary"]["company_links"] == 0
    plan = accept.build_plan(row, "accept", "Imran", "ok", company_rationales={"OGDC": "OGDC is the company named in the dividend headline"})
    accept.apply_plan(rv, plan)
    link = rv.execute("select * from event_companies").one()
    assert link["reviewer_status"] == "pending" and link["exposure_type"] == "uncertain" and link["company_id"] == "cmp-ogdc"
    with pytest.raises(sqlite3.IntegrityError, match="confirmed exposure"):     # the schema itself forbids accepting it from here
        rv.execute("UPDATE event_companies SET reviewer_status='accepted'")


def test_apply_is_atomic(rv):
    ex = candidate(rv)
    row = queue.show(rv, ex)
    plan = accept.build_plan(row, "accept", "Imran", "ok")
    plan["statements"].insert(-1, plan["statements"][-2])                       # duplicate evidence row -> UNIQUE violation mid-plan
    with pytest.raises(sqlite3.IntegrityError):
        accept.apply_plan(rv, plan)
    assert [rv.execute(f"select count(*) n from {t}").one()["n"] for t in ("events", "event_revisions", "event_evidence", "extraction_reviews")] == [0, 0, 0, 0]


def test_reject_and_needs_more_evidence_write_only_a_decision(rv):
    ex = candidate(rv)
    accept.apply_plan(rv, accept.build_plan(queue.show(rv, ex), "reject", "Imran", "irrelevant to listed companies"))
    assert rv.execute("select decision,event_id from extraction_reviews").one() == {"decision": "reject", "event_id": None}
    assert rv.execute("select count(*) n from events").one()["n"] == 0


# ------------------------------------------------------------------ runner (apply with --confirm)
from review import runner


def test_default_reviewer_is_imran_raza():
    assert runner.DEFAULT_REVIEWER == "Imran Raza"


def test_nothing_written_without_confirm(rv):
    ex = candidate(rv)
    r = runner.decide(rv, ex, "accept", "headline matches the source")
    assert r["applied"] is False and "plan only" in r["message"]
    assert [rv.execute(f"select count(*) n from {t}").one()["n"] for t in ("events", "event_evidence", "extraction_reviews")] == [0, 0, 0]


def test_confirm_applies_atomically_with_default_reviewer(rv):
    ex = candidate(rv)
    assert runner.decide(rv, ex, "accept", "headline matches the source", confirm=True)["applied"] is True
    assert rv.execute("select reviewer from extraction_reviews").one()["reviewer"] == "Imran Raza"
    assert rv.execute("select recorded_by from event_evidence").one()["recorded_by"] == "Imran Raza"
    assert rv.execute("select changed_by from event_revisions").one()["changed_by"] == "Imran Raza"


def test_cannot_decide_twice_or_on_unknown_candidate(rv):
    ex = candidate(rv)
    runner.decide(rv, ex, "reject", "not relevant", confirm=True)
    with pytest.raises(runner.RunnerError, match="not awaiting review"):
        runner.decide(rv, ex, "accept", "changed my mind", confirm=True)
    with pytest.raises(runner.RunnerError, match="not awaiting review"):
        runner.decide(rv, 9999, "reject", "x", confirm=True)
    assert rv.execute("select count(*) n from events").one()["n"] == 0


def test_needs_more_evidence_can_be_decided_again(rv):
    ex = candidate(rv)
    runner.decide(rv, ex, "needs_more_evidence", "check the filing", confirm=True)
    runner.decide(rv, ex, "accept", "filing confirms", confirm=True)
    assert rv.execute("select count(*) n from extraction_reviews").one()["n"] == 2 and rv.execute("select count(*) n from events").one()["n"] == 1


def test_refuses_without_migration(db):
    add_source(db, "news", stype="news_media"); add_company(db, "OGDC")
    ex = candidate(db)
    with pytest.raises(runner.RunnerError, match="migration 0011"):
        runner.decide(db, ex, "reject", "x", confirm=True)


def test_runner_still_enforces_grounded_quote_and_notes(rv):
    ex = candidate(rv, NO_QUOTE, title="Pindi courts acquit most accused", ext="z")
    with pytest.raises(accept.ReviewError, match="no grounded quote"):
        runner.decide(rv, ex, "accept", "ok", confirm=True)
    with pytest.raises(accept.ReviewError, match="notes"):
        runner.decide(rv, candidate(rv), "reject", "  ", confirm=True)


def test_cli_writes_only_through_confirmed_runner():
    src = open(__import__("pathlib").Path(__file__).resolve().parent.parent / "scripts" / "review_queue.py").read()
    assert "apply_plan" not in src and "INSERT" not in src and 'confirm="--confirm" in a' in src
