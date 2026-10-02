"""Shared pytest fixtures.

Database-backed tests use a scratch database, never the real one:

* ``TEST_DATABASE_URL`` (environment or ``.env``; CI sets it) -- an *owner-level*
  connection, because the tests create and empty the table. Otherwise
* the normal ``DB_*`` / ``DATABASE_URL`` settings with the database name replaced by
  ``gradcafe_m5_test``.

``TEST_APP_DATABASE_URL`` is the least-privilege application role's URL for the same
scratch database; ``tests/test_least_privilege.py`` uses it and is skipped without it.

When that database cannot be reached the database tests are skipped with a clear
reason (and the coverage gate then fails, so a green run always includes them).
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import psycopg
import pytest

from db_config import connect, database_url, setting, with_database
from flask_app import create_app
from load_data import create_table

TEST_DATABASE = "gradcafe_m5_test"

# Every test must carry at least one of these (see pytest.ini); enforced below.
REQUIRED_MARKERS = {"web", "buttons", "analysis", "db", "integration"}


def pytest_collection_modifyitems(config, items):
    """Refuse to run if any collected test is missing a required marker."""
    unmarked = [
        item.nodeid
        for item in items
        if not REQUIRED_MARKERS & {marker.name for marker in item.iter_markers()}
    ]
    if unmarked:
        raise pytest.UsageError(
            "Every test needs one of the markers "
            f"{sorted(REQUIRED_MARKERS)}; unmarked: {', '.join(unmarked)}"
        )


def test_database_url() -> str:
    """URL of the scratch database the tests may freely empty and refill."""
    return setting("TEST_DATABASE_URL") or with_database(database_url(), TEST_DATABASE)


# pytest would otherwise try to collect the helper above as a test.
test_database_url.__test__ = False


@pytest.fixture(scope="session")
def db_url() -> str:
    """The scratch database URL, or skip when PostgreSQL is not reachable."""
    url = test_database_url()
    try:
        connect(url, connect_timeout=5).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL test database not reachable: {exc}")
    return url


@pytest.fixture
def test_conn(db_url):
    """A connection to the scratch database with an empty ``applicants`` table."""
    conn = connect(db_url)
    create_table(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE applicants")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def make_app(db_url, test_conn) -> Callable[..., Any]:
    """Factory for a test app bound to the (empty) scratch database.

    Pulls run synchronously by default so a test can assert on the database right after
    ``POST /pull-data`` without waiting; pass ``config={"PULL_IN_BACKGROUND": True}`` to
    exercise the background thread. Any other ``create_app`` keyword (``scraper``,
    ``loader``, ``query_fn``, ``pull_manager``) is passed straight through.
    """
    apps = []

    def factory(config: Dict[str, Any] = None, **kwargs: Any):
        settings = {"TESTING": True, "DATABASE_URL": db_url, "PULL_IN_BACKGROUND": False}
        settings.update(config or {})
        app = create_app(settings, **kwargs)
        apps.append(app)
        return app

    yield factory
    # Wait for any background pull so it cannot outlive its test.
    for app in apps:
        app.extensions["gradcafe"]["pull_manager"].wait(timeout=30)
