"""Database connection settings, read from environment variables only.

Credentials never live in the repository: no host, user or password appears in the code.
The connection is configured by five variables:

    DB_HOST      (default: localhost)
    DB_PORT      (default: 5432)
    DB_NAME      (default: gradcafe)
    DB_USER
    DB_PASSWORD

Each one is read from the process environment first and from the git-ignored ``.env``
file second (copy ``.env.example`` to ``.env``). One optional variable overrides all five
at once, which is how CI and the tests point at a scratch database:

    DATABASE_URL   e.g. postgresql://gradcafe_app:<password>@localhost:5432/gradcafe

The old libpq variables (``PGHOST``, ``PGPASSWORD`` ...) are deliberately *not* read: a
superuser password left in someone's shell must never become the application's login.

``connect()`` serves the raw-SQL code (psycopg 3) and ``sqlalchemy_url()`` serves the
ORM code, so both always talk to the same database with the same settings. Both accept
an explicit URL, which is how the Flask app factory and the tests override the default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import psycopg
from sqlalchemy.engine import URL, make_url

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "gradcafe"

# Optional git-ignored file of KEY=VALUE lines in the module_5 folder (one level above
# src/). Real environment variables always win; the file only supplies missing values.
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _read_env_file() -> Dict[str, str]:
    """Parse KEY=VALUE lines from ENV_FILE (comments and blank lines ignored)."""
    if not ENV_FILE.exists():
        return {}
    values: Dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _setting(name: str, file_values: Dict[str, str], default: Any = None) -> Any:
    """Environment first, then the .env file, then the default."""
    return os.environ.get(name, file_values.get(name, default))


def setting(name: str, default: Any = None) -> Any:
    """Any configuration value by name: environment, then ``.env``, then ``default``."""
    return _setting(name, _read_env_file(), default)


def connection_settings() -> Dict[str, Any]:
    """DB_* settings used when DATABASE_URL is absent; user/password are None when unset."""
    file_values = _read_env_file()
    try:
        port = int(_setting("DB_PORT", file_values, DEFAULT_PORT))
    except ValueError as exc:
        raise ValueError("DB_PORT must be a whole number") from exc
    return {
        "host": _setting("DB_HOST", file_values, DEFAULT_HOST),
        "port": port,
        "dbname": _setting("DB_NAME", file_values, DEFAULT_DATABASE),
        "user": _setting("DB_USER", file_values),
        "password": _setting("DB_PASSWORD", file_values),
    }


def database_url() -> str:
    """The PostgreSQL URL: ``DATABASE_URL`` if set, otherwise built from the DB_* settings."""
    explicit = _setting("DATABASE_URL", _read_env_file())
    if explicit:
        return explicit
    settings = connection_settings()
    return URL.create(
        drivername="postgresql",
        username=settings["user"],
        password=settings["password"],
        host=settings["host"],
        port=settings["port"],
        database=settings["dbname"],
    ).render_as_string(hide_password=False)


def with_database(url: str, database: str) -> str:
    """The same server and credentials as ``url`` but a different database name."""
    return make_url(url).set(database=database).render_as_string(hide_password=False)


def _libpq_url(url: str) -> str:
    """Strip a SQLAlchemy driver suffix (``postgresql+psycopg``) so libpq accepts the URL."""
    parsed = make_url(url)
    if "+" not in parsed.drivername:
        return url
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


CONNECTION_HELP = (
    "Could not connect to PostgreSQL. Check that the server is running and that "
    "DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD (or DATABASE_URL) are set "
    "in your environment or in .env."
)


def report_connection_error(details: object) -> None:
    """Print the standard 'cannot reach PostgreSQL' message, with the driver's details."""
    print(f"{CONNECTION_HELP}\nDetails: {details}", file=sys.stderr)


def connect(url: Optional[str] = None, **kwargs: Any) -> psycopg.Connection:
    """Open a psycopg 3 connection to ``url`` (default: ``database_url()``)."""
    return psycopg.connect(_libpq_url(url or database_url()), **kwargs)


def sqlalchemy_url(url: Optional[str] = None) -> URL:
    """SQLAlchemy URL for the same database, always using the psycopg 3 driver."""
    return make_url(url or database_url()).set(drivername="postgresql+psycopg")
