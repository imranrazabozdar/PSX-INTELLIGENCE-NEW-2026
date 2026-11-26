"""Tests for analysis/send_daily_report.py: message builder and env check only.

No network, no SMTP, no database.
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "send_daily_report", os.path.join(ROOT, "analysis", "send_daily_report.py"))
sdr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sdr)

DUMMY_PDF = b"%PDF-1.4\n% dummy bytes for tests\n%%EOF\n"


def test_message_subject_recipient_and_attachment():
    msg = sdr.build_message(DUMMY_PDF, "2026-11-25", "PSX_Daily_Report_2026-11-25.pdf",
                            sender="sender@example.com", recipient="sender@example.com")
    assert msg["Subject"] == "PSX Daily Patterns Report — 2026-11-25"
    assert msg["From"] == msg["To"] == "sender@example.com"
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert body.strip() == ("Your PSX report for 2026-11-25 is attached "
                            "(Breakouts, Patterns, Chart Patterns; FIRE excluded)")
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    part = attachments[0]
    assert part.get_filename() == "PSX_Daily_Report_2026-11-25.pdf"
    assert part.get_content_type() == "application/pdf"
    assert part.get_payload(decode=True) == DUMMY_PDF


def test_missing_env_exits_1_naming_variable_only(monkeypatch, capsys):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "not-a-real-secret-value")
    called = []
    monkeypatch.setattr(sdr, "_build_pdf", lambda *a, **k: called.append(a))
    assert sdr.main(["--session-date", "2026-11-25"]) == 1
    err = capsys.readouterr().err
    assert "GMAIL_USER" in err
    assert "not-a-real-secret-value" not in err
    assert called == []  # nothing built or sent when config is missing


def test_both_env_missing_names_both(monkeypatch, capsys):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert sdr.main([]) == 1
    err = capsys.readouterr().err
    assert "GMAIL_USER" in err and "GMAIL_APP_PASSWORD" in err
