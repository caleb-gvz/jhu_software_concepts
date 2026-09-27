"""Database connection settings, read from environment variables only.

Credentials never live in the repository. The connection is configured by one variable:

    DATABASE_URL   e.g. postgresql://gradcafe_app:<password>@localhost:5432/gradcafe

When ``DATABASE_URL`` is not set, the URL is assembled from the standard libpq
variables instead, so Module 3 setups keep working unchanged:

    PGHOST      (default: localhost)
    PGPORT      (default: 5432)
    PGDATABASE  (default: gradcafe)
    PGUSER
    PGPASSWORD

``connect()`` serves the raw-SQL code (psycopg 3) and ``sqlalchemy_url()`` serves the
ORM code, so both always talk to the same database with the same settings. Both accept
an explicit URL, which is how the Flask app factory and the tests override the default.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import psycopg
from sqlalchemy.engine import URL, make_url

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "gradcafe"

# Optional git-ignored file of KEY=VALUE lines in the module_4 folder (one level above
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


def connection_settings() -> Dict[str, Any]:
    """PG* settings used when DATABASE_URL is absent; user/password are None when unset."""
    file_values = _read_env_file()
    return {
        "host": _setting("PGHOST", file_values, DEFAULT_HOST),
        "port": int(_setting("PGPORT", file_values, DEFAULT_PORT)),
        "dbname": _setting("PGDATABASE", file_values, DEFAULT_DATABASE),
        "user": _setting("PGUSER", file_values),
        "password": _setting("PGPASSWORD", file_values),
    }


def database_url() -> str:
    """The PostgreSQL URL: ``DATABASE_URL`` if set, otherwise built from the PG* settings."""
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


def connect(url: Optional[str] = None, **kwargs: Any) -> psycopg.Connection:
    """Open a psycopg 3 connection to ``url`` (default: ``database_url()``)."""
    return psycopg.connect(_libpq_url(url or database_url()), **kwargs)


def sqlalchemy_url(url: Optional[str] = None) -> URL:
    """SQLAlchemy URL for the same database, always using the psycopg 3 driver."""
    return make_url(url or database_url()).set(drivername="postgresql+psycopg")
