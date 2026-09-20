"""The SQLAlchemy model and ORM queries must agree with the raw SQL versions."""

import ast
from pathlib import Path

import pytest
from sqlalchemy import Date, Float, Integer, Text
from sqlalchemy.orm import Session

import orm_queries
from db_config import sqlalchemy_url
from load_data import COLUMNS, load_records
from models import Applicant, make_engine
from query_data import QUERIES, run_query
from questions import QUESTIONS
from tests.test_query_data import SEED

ORM_SOURCE = Path(orm_queries.__file__)


@pytest.fixture
def sql_conn_and_orm_session(test_conn):
    """The same seeded scratch database seen through psycopg and through SQLAlchemy."""
    load_records(test_conn, SEED)
    engine = make_engine(sqlalchemy_url().set(database="gradcafe_test"))
    with Session(engine) as session:
        yield test_conn, session
    engine.dispose()


# ---- the model -----------------------------------------------------------------------

def test_applicant_maps_the_existing_applicants_table_with_p_id_as_primary_key():
    table = Applicant.__table__
    assert table.name == "applicants"
    assert [column.name for column in table.columns] == list(COLUMNS)
    assert [column.name for column in table.primary_key.columns] == ["p_id"]


def test_applicant_column_types_match_the_assignment_schema():
    columns = Applicant.__table__.columns
    assert isinstance(columns["p_id"].type, Integer)
    assert isinstance(columns["date_added"].type, Date)
    for name in ("gpa", "gre", "gre_v", "gre_aw"):
        assert isinstance(columns[name].type, Float)
    for name in ("program", "comments", "url", "status", "term", "us_or_international",
                 "degree", "llm_generated_program", "llm_generated_university"):
        assert isinstance(columns[name].type, Text)


def test_model_does_not_create_a_second_copy_of_the_data():
    # mapping only: importing models must not define any table other than applicants
    from models import Base
    assert list(Base.metadata.tables) == ["applicants"]


# ---- parity with raw SQL ---------------------------------------------------------------

@pytest.mark.parametrize("query", QUERIES, ids=[q.number for q in QUERIES])
def test_orm_answer_equals_raw_sql_answer(sql_conn_and_orm_session, query):
    conn, session = sql_conn_and_orm_session
    assert orm_queries.run_query(session, query.number) == run_query(conn, query)


def test_orm_reads_the_rows_through_the_model(sql_conn_and_orm_session):
    _, session = sql_conn_and_orm_session
    applicant = session.get(Applicant, 1)
    assert applicant.program == "Computer Science, Stanford University"
    assert applicant.gpa == 3.8


def test_run_all_covers_every_question_in_order(sql_conn_and_orm_session):
    _, session = sql_conn_and_orm_session
    results = orm_queries.run_all(session)
    assert [question.number for question, _ in results] == [q.number for q in QUESTIONS]
    assert all(lines for _, lines in results)


def test_orm_queries_on_an_empty_table_do_not_crash(test_conn):
    engine = make_engine(sqlalchemy_url().set(database="gradcafe_test"))
    with Session(engine) as session:
        assert all(lines for _, lines in orm_queries.run_all(session))
    engine.dispose()


# ---- no bypassing the ORM ---------------------------------------------------------------

def test_orm_queries_never_use_raw_sql_or_a_psycopg_cursor():
    tree = ast.parse(ORM_SOURCE.read_text(encoding="utf-8"))
    imported_modules, imported_names, called_attributes = set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module or "")
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            called_attributes.add(node.attr)

    assert not any(module.split(".")[0] == "psycopg" for module in imported_modules)
    assert "text" not in imported_names
    assert not {"cursor", "exec_driver_sql"} & called_attributes
    assert "query_data" not in imported_modules   # no borrowing the raw SQL module either
