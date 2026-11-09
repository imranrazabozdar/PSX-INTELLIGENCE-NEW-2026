import os
import sqlite3
import pytest
import manual_pdf_ingester as m

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def db(access="verified_permitted"):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    for f in ("market_bars_schema.sql", "source_items_schema.sql"):
        c.executescript(open(os.path.join(FX, f)).read())
    c.execute("INSERT INTO sources(source_id,name,source_type,access_status,created_at_utc,updated_at_utc) "
              "VALUES('psx','x','exchange',?, 't','t')", (access,))
    return c


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "Board Meeting (OGDC).pdf"
    p.write_bytes(b"%PDF-1.4 test body")
    return p


def test_env_required():
    with pytest.raises(m.IngestError):
        m.vault_root({})


def test_ingest_ok(tmp_path, pdf):
    c, root = db(), tmp_path / "vault"
    root.mkdir()
    r = m.ingest(c, pdf, "psx", root, published_date="2026-11-06", title="T")
    assert r["status"] == "inserted"
    rel = r["content_location"]
    assert rel.startswith("announcements/2026/11/") and rel.endswith("_Board_Meeting_OGDC.pdf")
    assert (root / rel).read_bytes() == pdf.read_bytes()
    row = c.execute("select * from source_items").fetchone()
    assert (row["document_type"], row["retrieval_method"], row["access_status"]) == ("pdf", "manual", "permitted")
    assert row["content_location"] == rel and row["content_sha256"] == m.sha256_file(pdf)
    assert row["event_date"] == "2026-11-06" and row["publication_time_status"] == "date_only"
    assert c.execute("select count(*) from collector_runs where job='manual_pdf_ingest'").fetchone()[0] == 1


def test_duplicate_skipped(tmp_path, pdf):
    c, root = db(), tmp_path
    m.ingest(c, pdf, "psx", root)
    assert m.ingest(c, pdf, "psx", root)["status"] == "duplicate"
    assert c.execute("select count(*) from source_items").fetchone()[0] == 1


def test_rejects_non_pdf_unknown_source_and_dates(tmp_path):
    c = db()
    bad = tmp_path / "x.pdf"; bad.write_bytes(b"hello")
    with pytest.raises(m.IngestError): m.ingest(c, bad, "psx", tmp_path)
    ok = tmp_path / "y.pdf"; ok.write_bytes(b"%PDF-1")
    with pytest.raises(m.IngestError): m.ingest(c, ok, "nope", tmp_path)
    with pytest.raises(m.IngestError): m.ingest(c, ok, "psx", tmp_path, published_date="06/11/2026")


def test_restricted_source_needs_ack(tmp_path, pdf):
    c = db("restricted")
    with pytest.raises(m.IngestError): m.ingest(c, pdf, "psx", tmp_path)
    assert m.ingest(c, pdf, "psx", tmp_path, ack_terms=True)["status"] == "inserted"


def test_dry_run_writes_nothing(tmp_path, pdf):
    c = db(); root = tmp_path / "v"; root.mkdir()
    assert m.ingest(c, pdf, "psx", root, dry_run=True)["status"] == "dry_run"
    assert not any(root.rglob("*.pdf")) and c.execute("select count(*) from source_items").fetchone()[0] == 0


def test_db_failure_removes_copied_file(tmp_path, pdf):
    c = db(); c.execute("drop table collector_runs"); root = tmp_path / "v"; root.mkdir()
    with pytest.raises(Exception): m.ingest(c, pdf, "psx", root)
    assert not any(root.rglob("*.pdf"))
