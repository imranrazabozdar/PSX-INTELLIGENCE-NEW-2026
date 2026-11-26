"""Build the daily PSX patterns PDF with analysis/daily_report_pdf.py and email it.

Read-only with respect to the database: the builder runs its SELECT/PRAGMA-only
connection. The builder module is not modified; this script only imports it.

Usage:
    python3 analysis/send_daily_report.py                       # latest session
    python3 analysis/send_daily_report.py --session-date 2026-11-25
    python3 analysis/send_daily_report.py --dry-run             # build only, no email

Required environment (send mode only): GMAIL_USER, GMAIL_APP_PASSWORD.
Mail goes via smtp.gmail.com:587 (STARTTLS); sender and recipient are GMAIL_USER.
Secrets and the address are never printed.
"""
import argparse
import os
import smtplib
import sys
import tempfile
from email.message import EmailMessage

ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
REQUIRED_ENV = ("GMAIL_USER", "GMAIL_APP_PASSWORD")


def build_message(pdf_bytes, session_date, filename, sender, recipient):
    msg = EmailMessage()
    msg["Subject"] = f"PSX Daily Patterns Report — {session_date}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(
        f"Your PSX report for {session_date} is attached "
        "(Breakouts, Patterns, Chart Patterns; FIRE excluded)"
    )
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
    return msg


def send_message(msg, user, password):
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)


def _build_pdf(session_date, out_dir):
    sys.path.insert(0, ANALYSIS_DIR)
    import daily_report_pdf as rpt  # existing builder, imported only

    conn = rpt.ReadOnlyConnection(rpt._open_connection(None))
    session, sections, path, pages, size = rpt.build_report(conn, out_dir, session_date=session_date)
    with open(path, "rb") as f:
        data = f.read()
    return session, os.path.basename(path), data, pages, size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-date", metavar="YYYY-MM-DD",
                    help="report this session date instead of the latest one")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the PDF and print name, size and page count; do not send")
    args = ap.parse_args(argv)

    if not args.dry_run:
        missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            for name in missing:
                print(f"missing environment variable: {name}", file=sys.stderr)
            return 1

    with tempfile.TemporaryDirectory() as out_dir:
        session, filename, data, pages, size = _build_pdf(args.session_date, out_dir)

        if args.dry_run:
            print(f"report: {filename}")
            print(f"pages: {pages}  size: {size // 1024} KB")
            print("dry-run: no email sent")
            return 0

        user = os.environ["GMAIL_USER"]
        password = os.environ["GMAIL_APP_PASSWORD"]
        msg = build_message(data, session, filename, sender=user, recipient=user)
        send_message(msg, user, password)
        print(f"email sent: session {session}, {filename}, pages: {pages}, size: {size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
