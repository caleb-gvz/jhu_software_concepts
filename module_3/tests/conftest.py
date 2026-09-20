"""Shared pytest fixtures.

Database-backed tests use a scratch database named ``gradcafe_test`` (never the real
``gradcafe`` database) and skip cleanly when PostgreSQL is not reachable.
"""

import psycopg
import pytest

from db_config import connection_settings
from load_data import create_table

TEST_DATABASE = "gradcafe_test"


def _test_connection_settings():
    settings = {k: v for k, v in connection_settings().items() if v is not None}
    settings["dbname"] = TEST_DATABASE
    return settings


@pytest.fixture
def test_conn():
    """A connection to the scratch database with an empty ``applicants`` table."""
    try:
        conn = psycopg.connect(**_test_connection_settings(), connect_timeout=5)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL test database not reachable: {exc}")
    create_table(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE applicants")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def point_env_at_test_database(monkeypatch):
    """Make db_config (and therefore SQLAlchemy/Flask) use the scratch database."""
    monkeypatch.setenv("PGDATABASE", TEST_DATABASE)
