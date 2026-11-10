"""Fail-closed guard: this engine must never use the PSX-NEWS-INTELLIGENCE database.

That database is exclusive to the news project (ADR-0001 and the news repository's database ownership rules).
The check refuses at configuration time, before any network call, and never falls back silently to another
database. Refused: the owned host, any host that names the news project, and URLs carrying credentials.
"""

NEWS_OWNED_HOST = "psx-news-intelligence-imranrazabozdar.aws-us-east-1.turso.io"
NEWS_HOST_MARKER = "psx-news-intelligence"


class SharedDatabaseRefused(RuntimeError):
    """The configured database belongs to another project."""


def remote_host(url: str) -> str:
    rest = url.split("://", 1)[-1]
    if "@" in rest.split("/", 1)[0] or "?" in rest or "#" in rest:
        raise SharedDatabaseRefused("database URL must not carry credentials, a query or a fragment")
    return rest.split("/", 1)[0].split(":", 1)[0].lower().rstrip(".")


def refuse_news_database(url: str) -> None:
    """Raise unless the URL is not the news project's database. Empty URLs are the caller's concern."""
    if not url:
        return
    host = remote_host(url)
    if host == NEWS_OWNED_HOST or NEWS_HOST_MARKER in host:
        raise SharedDatabaseRefused(
            "refusing: LIBSQL_URL points at the PSX-NEWS-INTELLIGENCE database. The technical engine must use "
            "its own separate database; see docs/DATABASE_OWNERSHIP.md")
