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
from typing import Any, Dict

import psycopg
from sqlalchemy.engine import URL

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "gradcafe"


def connection_settings() -> Dict[str, Any]:
    """Current connection settings; user/password are None when not set."""
    return {
        "host": os.environ.get("PGHOST", DEFAULT_HOST),
        "port": int(os.environ.get("PGPORT", DEFAULT_PORT)),
        "dbname": os.environ.get("PGDATABASE", DEFAULT_DATABASE),
        "user": os.environ.get("PGUSER"),
        "password": os.environ.get("PGPASSWORD"),
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
