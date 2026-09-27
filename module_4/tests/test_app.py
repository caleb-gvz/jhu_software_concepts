import ast
import html
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app as app_module
from app import create_app
from db_config import sqlalchemy_url
from load_data import load_records
from models import make_engine
from questions import QUESTIONS
from tests.test_query_data import SEED


class FakeManager:
    """Stands in for PullManager so no real scrape is ever started by these tests."""

    def __init__(self, running=False, message="", succeeded=None, can_start=True):
        self.running = running
        self.last_message = message
        self.last_succeeded = succeeded
        self.can_start = can_start
        self.start_calls = 0

    def is_running(self):
        return self.running

    def start(self):
        if self.running or not self.can_start:
            return False
        self.start_calls += 1
        self.running = True
        return True


@pytest.fixture
def session_factory(test_conn):
    load_records(test_conn, SEED)
    engine = make_engine(sqlalchemy_url().set(database="gradcafe_test"))
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def _client(manager, session_factory):
    application = create_app(manager=manager, session_factory=session_factory)
    application.config["TESTING"] = True
    return application.test_client()


def _text(response):
    """Response body with HTML entities decoded, i.e. what a visitor would read."""
    return html.unescape(response.get_data(as_text=True))


# ---- the analysis page ------------------------------------------------------------------

def test_page_shows_every_question_with_results_from_the_database(session_factory):
    page = _text(_client(FakeManager(), session_factory).get("/"))

    for question in QUESTIONS:
        assert question.question in page
    assert "Fall 2026 applicant count: 7" in page               # Q1 on the seeded data
    assert "Percent international: 33.33%" in page             # Q2
    assert "Difference: +1" in page                             # Q9
    assert "American: 50.00% accepted (n = 2)" in page          # original question 1


def test_page_has_both_buttons_an_explanation_and_a_stylesheet(session_factory):
    page = _text(_client(FakeManager(), session_factory).get("/"))

    assert "Pull Data" in page and "Update Analysis" in page
    assert "checks Grad Cafe for newly submitted application results" in page.lower() or \
           "checks grad caf" in page.lower()
    assert "/static/style.css" in page


def test_stylesheet_is_served(session_factory):
    response = _client(FakeManager(), session_factory).get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.content_type


def test_page_warns_that_data_is_being_retrieved_while_a_pull_runs(session_factory):
    page = _text(_client(FakeManager(running=True, message="Checking Grad Cafe"), session_factory).get("/"))
    assert "currently being retrieved" in page


def test_database_outage_shows_a_friendly_message_instead_of_crashing():
    def broken_factory():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    response = _client(FakeManager(), broken_factory).get("/")

    assert response.status_code == 503
    assert "could not connect to the database" in _text(response).lower()


# ---- Pull Data ----------------------------------------------------------------------------

def test_pull_data_starts_a_pull_and_says_so(session_factory):
    manager = FakeManager()
    client = _client(manager, session_factory)

    response = client.post("/pull-data", follow_redirects=True)

    assert manager.start_calls == 1
    assert "started" in _text(response).lower()


def test_pull_data_refuses_a_second_scrape_while_one_is_running(session_factory):
    manager = FakeManager(running=True)
    client = _client(manager, session_factory)

    response = client.post("/pull-data", follow_redirects=True)

    assert manager.start_calls == 0
    assert "already running" in _text(response).lower()


def test_pull_data_reports_when_the_pull_could_not_be_started(session_factory):
    manager = FakeManager(can_start=False, message="The pull could not be started: no such file")
    response = _client(manager, session_factory).post("/pull-data", follow_redirects=True)
    assert "could not be started" in _text(response).lower()


# ---- Update Analysis ---------------------------------------------------------------------

def test_update_analysis_never_starts_a_scrape(session_factory):
    manager = FakeManager()
    _client(manager, session_factory).post("/update-analysis", follow_redirects=True)
    assert manager.start_calls == 0


def test_update_analysis_while_pulling_says_new_data_is_being_retrieved(session_factory):
    manager = FakeManager(running=True)
    response = _client(manager, session_factory).post("/update-analysis", follow_redirects=True)

    assert "currently being retrieved" in _text(response)
    assert manager.start_calls == 0 and manager.running       # the pull was left alone


def test_update_analysis_when_idle_refreshes_from_the_database(session_factory):
    response = _client(FakeManager(), session_factory).post("/update-analysis", follow_redirects=True)
    page = _text(response)

    assert "up to date" in page.lower() or "updated" in page.lower()
    assert "Fall 2026 applicant count: 7" in page


# ---- status endpoint ------------------------------------------------------------------------

def test_status_endpoint_reports_running_state_and_message(session_factory):
    running = _client(FakeManager(running=True, message="Fetching page 3"), session_factory)
    assert running.get("/status").get_json() == {
        "running": True, "message": "Fetching page 3", "succeeded": None,
    }

    finished = _client(FakeManager(message="Added 5 new records to the database.", succeeded=True), session_factory)
    assert finished.get("/status").get_json() == {
        "running": False, "message": "Added 5 new records to the database.", "succeeded": True,
    }


# ---- ORM only ------------------------------------------------------------------------------

def test_app_reads_the_database_only_through_the_orm():
    tree = ast.parse(Path(app_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])

    assert "psycopg" not in imported
    assert "query_data" not in imported
    assert "orm_queries" in imported
