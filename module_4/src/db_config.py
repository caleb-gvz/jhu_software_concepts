"""Database connection settings, read from environment variables only.

Credentials never live in the repository. Set these before running any script:

    PGHOST      (default: localhost)
    PGPORT      (default: 5432)
    PGDATABASE  (default: gradcafe)
    PGUSER
    PGPASSWORD

``connect()`` serves the raw-SQL code (psycopg 3) and ``sqlalchemy_url()`` serves the
ORM code, so both always talk to the same database with the same settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import psycopg
from sqlalchemy.engine import URL

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "gradcafe"

# Optional git-ignored file of KEY=VALUE lines. Real environment variables always win;
# the file only supplies values that are missing from the environment.
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
    """Current connection settings; user/password are None when not set."""
    file_values = _read_env_file()
    return {
        "host": _setting("PGHOST", file_values, DEFAULT_HOST),
        "port": int(_setting("PGPORT", file_values, DEFAULT_PORT)),
        "dbname": _setting("PGDATABASE", file_values, DEFAULT_DATABASE),
        "user": _setting("PGUSER", file_values),
        "password": _setting("PGPASSWORD", file_values),
    }


def connect() -> psycopg.Connection:
    """Open a psycopg 3 connection. Unset user/password fall back to libpq defaults."""
    settings = {k: v for k, v in connection_settings().items() if v is not None}
    return psycopg.connect(**settings)


def sqlalchemy_url() -> URL:
    """SQLAlchemy URL for the same database (psycopg 3 driver)."""
    settings = connection_settings()
    return URL.create(
        drivername="postgresql+psycopg",
        username=settings["user"],
        password=settings["password"],
        host=settings["host"],
        port=settings["port"],
        database=settings["dbname"],
    )
