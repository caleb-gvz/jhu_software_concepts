"""Regression guards for the SQL-injection defenses (Module 5).

Two kinds of check, so the rules cannot quietly erode:

* a static scan of ``src/`` that fails if any ``execute()`` / ``executemany()`` call is
  handed SQL built with an f-string, ``+`` / ``%`` concatenation or ``str.format``;
* a runtime recorder that captures every statement the application really sends to
  PostgreSQL (raw psycopg and SQLAlchemy ORM) and fails if a ``SELECT`` has no ``LIMIT``.
"""

import ast
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import load_data
import orm_queries
import pull_data
import query_data
from db_config import connect
from load_data import COLUMNS, load_records
from models import make_engine
from tests.test_query_data import SEED

pytestmark = pytest.mark.db

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
EXECUTE_METHODS = {"execute", "executemany"}


def _builds_sql_from_text(node: ast.AST) -> bool:
    """True for an f-string, ``a + b`` / ``a % b``, a str literal, or ``"...".format(...)``."""
    if isinstance(node, (ast.JoinedStr, ast.BinOp)):
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and isinstance(node.func.value, ast.Constant)
    )


def _execute_calls(path: Path):
    """Yield ``(line, first_argument)`` for every ``.execute()`` / ``.executemany()`` call."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in EXECUTE_METHODS
            and node.args
        ):
            yield node.lineno, node.args[0]


def test_the_scanner_itself_flags_the_unsafe_patterns():
    unsafe = [
        'cur.execute(f"SELECT * FROM t WHERE a = {x}")',
        'cur.execute("SELECT * FROM t WHERE a = " + x)',
        'cur.execute("SELECT * FROM t WHERE a = %s" % x)',
        'cur.execute("SELECT * FROM t WHERE a = {}".format(x))',
        'cur.execute("SELECT 1")',
    ]
    for source in unsafe:
        call = ast.parse(source).body[0].value
        assert _builds_sql_from_text(call.args[0]), source

    safe = ["cur.execute(statement, params)", "cur.execute(limited(statement), params)"]
    for source in safe:
        call = ast.parse(source).body[0].value
        assert not _builds_sql_from_text(call.args[0]), source


def test_no_query_in_src_is_built_from_strings():
    offenders = [
        f"{path.relative_to(SRC_DIR)}:{line}"
        for path in sorted(SRC_DIR.rglob("*.py"))
        for line, first_argument in _execute_calls(path)
        if _builds_sql_from_text(first_argument)
    ]
    assert offenders == []


def test_the_upsert_is_composed_from_identifiers_and_named_placeholders():
    text = load_data.UPSERT_STATEMENT.as_string()

    assert text.startswith('INSERT INTO "applicants" (')
    for column in COLUMNS:
        assert f'"{column}"' in text            # every column is a quoted identifier
        assert f"%({column})s" in text          # every value is a named placeholder
    assert "ON CONFLICT" in text and "EXCLUDED" in text


# ---- runtime recording ----------------------------------------------------------------

class RecordingCursor(psycopg.Cursor):
    """A cursor that remembers the text of every statement it is asked to run."""

    executed = []

    def execute(self, query, params=None, **kwargs):
        text = query.as_string(self) if hasattr(query, "as_string") else str(query)
        RecordingCursor.executed.append(text)
        return super().execute(query, params, **kwargs)

    def executemany(self, query, params_seq, **kwargs):
        text = query.as_string(self) if hasattr(query, "as_string") else str(query)
        RecordingCursor.executed.append(text)
        return super().executemany(query, params_seq, **kwargs)


def _selects(statements):
    return [text for text in statements if text.lstrip().upper().startswith("SELECT")]


@pytest.fixture
def recording_conn(db_url):
    """A connection to the scratch database that records every statement it executes."""
    RecordingCursor.executed = []
    conn = connect(db_url, cursor_factory=RecordingCursor)
    with conn.cursor() as cur:
        psycopg.Cursor.execute(cur, "TRUNCATE applicants")
    conn.commit()
    yield conn
    conn.close()


def test_every_select_the_raw_sql_layer_sends_carries_a_limit(recording_conn):
    load_records(recording_conn, SEED)
    RecordingCursor.executed = []

    query_data.run_all(recording_conn)
    query_data.fetch_applicants(recording_conn)
    query_data.search_applicants(recording_conn, term="fall 2026", status="accepted")
    pull_data._known_ids(recording_conn)           # pylint: disable=protected-access
    load_data._count_rows(recording_conn)          # pylint: disable=protected-access

    selects = _selects(RecordingCursor.executed)
    assert len(selects) >= 11 + 3                  # the 11 questions plus the look-ups above
    assert [text for text in selects if "LIMIT" not in text] == []


def test_every_select_the_orm_layer_sends_carries_a_limit(db_url, test_conn):
    load_records(test_conn, SEED)
    statements = []
    engine = make_engine(db_url)

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        statements.append(statement)

    with Session(engine) as session:
        orm_queries.run_all(session)
        orm_queries.get_analysis(session)
    engine.dispose()

    selects = _selects(statements)
    assert len(selects) >= 12                      # 11 questions plus the total-entries count
    assert [text for text in selects if "LIMIT" not in text.upper()] == []
