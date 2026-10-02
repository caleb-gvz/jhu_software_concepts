"""Log in as the real least-privilege role and prove what it can and cannot do.

These tests need the roles created by ``src/db_setup.sql`` and the environment variable
``TEST_APP_DATABASE_URL`` (the application role's URL for the scratch database; set it
in ``.env`` or the shell -- CI sets it). Without it they are skipped, with the reason.
"""

import psycopg
import pytest

from db_config import connect, setting
from load_data import COLUMNS, load_records
from pull_data import _known_ids
from query_data import fetch_applicants, run_all, search_applicants
from tests.doubles import FakeScraper, make_record
from tests.test_query_data import SEED, _rec

APP_URL = setting("TEST_APP_DATABASE_URL")

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not APP_URL, reason="TEST_APP_DATABASE_URL is not set (least-privilege role not provisioned)"
    ),
]

LLM_COLUMNS = ("llm_generated_program", "llm_generated_university")


@pytest.fixture
def app_conn(test_conn):
    """A connection as the application role to the (already emptied) scratch database."""
    conn = connect(APP_URL)
    yield conn
    conn.close()


def _one(conn, query):
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchone()


def test_the_application_role_is_not_a_superuser_and_cannot_create_roles_or_databases(app_conn):
    attributes = _one(
        app_conn,
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user",
    )

    assert attributes == (False, False, False, False, False)


def test_the_application_role_owns_nothing(app_conn):
    owned_objects = _one(
        app_conn,
        "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
        "WHERE r.rolname = current_user",
    )[0]
    owns_database = _one(
        app_conn,
        "SELECT r.rolname = current_user FROM pg_database d "
        "JOIN pg_roles r ON r.oid = d.datdba WHERE d.datname = current_database()",
    )[0]

    assert owned_objects == 0
    assert owns_database is False


def test_the_application_code_works_with_only_the_granted_privileges(app_conn):
    load_records(app_conn, SEED)                                   # INSERT
    assert len(fetch_applicants(app_conn)) == 15                   # SELECT
    assert len(search_applicants(app_conn, term="fall 2026", status="accepted")) == 5
    assert len(run_all(app_conn)) == 11                            # every analysis query
    assert _known_ids(app_conn) == set(range(1, 16))

    # The upsert's conflict branch needs UPDATE on the two llm_* columns.
    load_records(app_conn, [_rec(2, llm_program="Computer Science", llm_university="Stanford")])
    row = [r for r in fetch_applicants(app_conn) if r["p_id"] == 2][0]
    assert row["llm_generated_program"] == "Computer Science"


@pytest.mark.parametrize(
    "statement",
    [
        "DROP TABLE applicants",
        "ALTER TABLE applicants ADD COLUMN extra TEXT",
        "ALTER TABLE applicants DROP COLUMN status",
        "TRUNCATE applicants",
        "DELETE FROM applicants",
        "UPDATE applicants SET status = 'hacked'",
        "UPDATE applicants SET p_id = p_id + 1000",
        "CREATE TABLE evil (id INT)",
        "CREATE INDEX evil_index ON applicants (status)",
        "CREATE ROLE evil LOGIN",
        "COMMENT ON TABLE applicants IS 'changed'",
    ],
)
def test_destructive_and_owner_only_statements_are_refused_and_the_data_survives(
    app_conn, test_conn, statement
):
    load_records(test_conn, [_rec(1), _rec(2)])

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(statement)
    app_conn.rollback()

    assert [row["p_id"] for row in fetch_applicants(app_conn)] == [1, 2]


def test_the_application_role_cannot_hand_out_privileges(app_conn, test_conn):
    # PostgreSQL does not raise for a non-owner's GRANT; it warns and grants nothing.
    app_conn.execute("GRANT ALL ON applicants TO PUBLIC")
    app_conn.commit()

    public_grants = _one(
        test_conn,
        "SELECT count(*) FROM information_schema.role_table_grants "
        "WHERE table_name = 'applicants' AND grantee = 'PUBLIC'",
    )[0]
    app_can_delete = _one(
        test_conn, "SELECT has_table_privilege('gradcafe_m5_app', 'applicants', 'DELETE')"
    )[0]
    assert public_grants == 0
    assert app_can_delete is False


@pytest.mark.parametrize("column", [c for c in COLUMNS if c not in LLM_COLUMNS])
def test_every_column_except_the_two_llm_ones_is_read_only_for_the_application_role(
    app_conn, test_conn, column
):
    load_records(test_conn, [_rec(1)])
    assignment = f'"{column}" = "{column}"'

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(f"UPDATE applicants SET {assignment}")
    app_conn.rollback()


def test_the_two_llm_columns_are_updatable(app_conn, test_conn):
    load_records(test_conn, [_rec(1)])

    for column in LLM_COLUMNS:
        app_conn.execute(f"UPDATE applicants SET {column} = 'filled' WHERE p_id = 1")
    app_conn.commit()

    row = fetch_applicants(app_conn)[0]
    assert (row["llm_generated_program"], row["llm_generated_university"]) == ("filled", "filled")


def test_the_whole_web_app_runs_as_the_least_privilege_role(make_app, test_conn):
    load_records(test_conn, SEED)
    scraper = FakeScraper([make_record(100)])
    client = make_app({"DATABASE_URL": APP_URL}, scraper=scraper).test_client()

    assert client.get("/analysis").status_code == 200                  # ORM reads
    assert client.get("/applicants?limit=3").get_json()["count"] == 3  # composed-SQL search
    assert client.post("/update-analysis").status_code == 200
    pulled = client.post("/pull-data")                                  # SELECT + INSERT only
    assert pulled.status_code == 200 and pulled.get_json()["added"] == 1
    assert client.get("/applicants?limit=100").get_json()["count"] == 16
