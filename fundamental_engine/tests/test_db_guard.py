"""Fail-closed database ownership for the technical engine. No network: refusals happen before any call."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.db_guard import NEWS_OWNED_HOST, SharedDatabaseRefused, refuse_news_database
from core.db import TursoClient

ROOT = Path(__file__).resolve().parents[2]
NEWS = f"libsql://{NEWS_OWNED_HOST}"


@pytest.mark.parametrize("url", [
    NEWS,
    f"libsql://{NEWS_OWNED_HOST.upper()}.",
    f"https://{NEWS_OWNED_HOST}/v2/pipeline",
    "libsql://psx-news-intelligence-anything.example.turso.io",
    f"libsql://user@{NEWS_OWNED_HOST}",
    f"libsql://{NEWS_OWNED_HOST}?tls=1",
])
def test_the_news_database_is_refused_in_every_spelling(url):
    with pytest.raises(SharedDatabaseRefused):
        refuse_news_database(url)


def test_a_separate_technical_database_is_accepted():
    refuse_news_database("libsql://psx-intelligence-technical.example.turso.io")
    refuse_news_database("")          # empty is the caller's concern, not a shared database


def test_the_turso_client_refuses_before_any_network_call():
    with pytest.raises(SharedDatabaseRefused):
        TursoClient(NEWS, "token")


def test_the_backend_refuses_the_news_database_at_import():
    env = {**os.environ, "LIBSQL_URL": NEWS, "LIBSQL_AUTH_TOKEN": "token"}
    proc = subprocess.run([sys.executable, "-c", "import backend.turso_db"], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0
    assert "PSX-NEWS-INTELLIGENCE database" in proc.stderr
