"""Flask app factory and analysis-page rendering (GET /analysis).

Most tests inject a fake query function, so they check the page itself without a
database. The last group renders the page from real rows through the ORM.
"""

import ast
import html
import threading
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from flask import Flask
from sqlalchemy.exc import OperationalError

import flask_app as app_module
from flask_app import AnalysisCache, create_app
from load_data import load_records
from pull_data import PullResult
from pull_manager import PullManager
from questions import QUESTIONS
from tests.doubles import NullSession, SpyQuery, fake_analysis
from tests.test_query_data import SEED

pytestmark = pytest.mark.web


def _app(**kwargs):
    """An app whose page data comes from a fake query (no database needed)."""
    kwargs.setdefault("query_fn", SpyQuery())
    kwargs.setdefault("session_factory", NullSession)
    return create_app({"TESTING": True}, **kwargs)


def _soup(response):
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


def _text(response):
    """Response body with HTML entities decoded, i.e. what a visitor would read."""
    return html.unescape(response.get_data(as_text=True))


# ---- app factory / configuration -----------------------------------------------------

def test_create_app_returns_a_testable_flask_app_with_every_route():
    app = _app()
    assert isinstance(app, Flask)

    routes = {rule.rule: rule.methods for rule in app.url_map.iter_rules()}
    assert "GET" in routes["/analysis"]
    assert "GET" in routes["/"]
    assert "POST" in routes["/pull-data"]
    assert "POST" in routes["/update-analysis"]
    assert "GET" in routes["/status"]
    assert app.testing is True


def test_create_app_accepts_config_overrides_including_database_url():
    app = create_app({"DATABASE_URL": "postgresql://tester@db.example:5555/other"},
                     session_factory=NullSession, query_fn=SpyQuery())
    assert app.config["DATABASE_URL"] == "postgresql://tester@db.example:5555/other"
    assert app.config["PULL_IN_BACKGROUND"] is True        # production default


def test_create_app_uses_database_url_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://env_user@env-host:5432/env_db")
    app = create_app(session_factory=NullSession, query_fn=SpyQuery())
    assert app.config["DATABASE_URL"] == "postgresql://env_user@env-host:5432/env_db"


def test_each_app_gets_its_own_pull_manager_unless_one_is_injected():
    manager = PullManager()
    assert _app(pull_manager=manager).extensions["gradcafe"]["pull_manager"] is manager
    assert _app().extensions["gradcafe"]["pull_manager"] is not manager


# ---- GET /analysis -----------------------------------------------------------------------

def test_get_analysis_returns_200():
    assert _app().test_client().get("/analysis").status_code == 200


def test_root_url_serves_the_same_analysis_page():
    client = _app().test_client()
    assert client.get("/").get_data() == client.get("/analysis").get_data()


def test_page_has_pull_data_and_update_analysis_buttons_with_stable_selectors():
    soup = _soup(_app().test_client().get("/analysis"))

    pull = soup.select_one('[data-testid="pull-data-btn"]')
    update = soup.select_one('[data-testid="update-analysis-btn"]')
    assert pull is not None and pull.name == "button" and pull.get_text(strip=True) == "Pull Data"
    assert update is not None and update.name == "button" and update.get_text(strip=True) == "Update Analysis"
    # Each button posts to its endpoint.
    assert pull.find_parent("form")["action"] == "/pull-data"
    assert update.find_parent("form")["action"] == "/update-analysis"


def test_page_text_includes_analysis_and_at_least_one_answer_label():
    response = _app().test_client().get("/analysis")
    soup = _soup(response)

    assert "Analysis" in soup.title.get_text()
    assert "Analysis" in soup.select_one('[data-testid="page-title"]').get_text()
    assert "Answer:" in soup.get_text()


def test_page_renders_every_question_card_from_the_query_result():
    soup = _soup(_app().test_client().get("/analysis"))
    cards = soup.select('[data-testid="analysis-card"]')
    assert [card["data-question"] for card in cards] == ["2", "3", "O1"]
    assert soup.select_one('[data-testid="total-entries"]').get_text() == "3"


def test_page_explains_what_pull_data_does_and_links_the_stylesheet():
    page = _text(_app().test_client().get("/analysis"))
    assert "checks Grad Café for newly submitted application results" in page
    assert "/static/style.css" in page


def test_stylesheet_is_served():
    response = _app().test_client().get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.content_type


def test_page_is_computed_once_and_then_served_from_the_snapshot():
    query = SpyQuery()
    client = _app(query_fn=query).test_client()
    client.get("/analysis")
    client.get("/analysis")
    assert query.calls == 1
    assert "Analysis as of" in _text(client.get("/analysis"))


def test_database_outage_shows_a_friendly_message_instead_of_crashing():
    def broken_factory():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    response = _app(session_factory=broken_factory).test_client().get("/analysis")

    assert response.status_code == 503
    soup = _soup(response)
    assert soup.select_one('[data-testid="db-error"]') is not None
    # The buttons are still there so the user can retry.
    assert soup.select_one('[data-testid="update-analysis-btn"]') is not None


# ---- pull state shown on the page ----------------------------------------------------

def _busy_manager():
    """A PullManager holding a job open until the returned Event is set."""
    manager, reported, release = PullManager(), threading.Event(), threading.Event()

    def job(report):
        report("Fetching page 3")
        reported.set()
        release.wait(timeout=30)
        return PullResult(added=0)

    manager.start(job)
    reported.wait(timeout=30)      # the job is now mid-pull; no sleep() needed
    return manager, release


def test_page_warns_that_data_is_being_retrieved_while_a_pull_runs():
    manager, release = _busy_manager()
    try:
        soup = _soup(_app(pull_manager=manager).test_client().get("/analysis"))
        banner = soup.select_one('[data-testid="pull-banner"]')
        assert not banner.has_attr("hidden")
        assert "currently being retrieved" in banner.get_text()
        assert soup.select_one('[data-testid="pull-data-btn"]').has_attr("disabled")
    finally:
        release.set()
        manager.wait()


def test_page_shows_the_outcome_of_the_last_pull():
    manager = PullManager()
    manager.run(lambda report: PullResult(added=4))
    soup = _soup(_app(pull_manager=manager).test_client().get("/analysis"))

    last = soup.select_one('[data-testid="last-pull"]')
    assert "Added 4 new records" in last.get_text()
    assert "notice-success" in last["class"]
    assert soup.select_one('[data-testid="pull-banner"]').has_attr("hidden")


def test_page_shows_a_failed_last_pull_as_an_error():
    manager = PullManager()
    manager.run(lambda report: PullResult(added=0, error="HTTP 403."))
    last = _soup(_app(pull_manager=manager).test_client().get("/analysis")).select_one(
        '[data-testid="last-pull"]'
    )
    assert "notice-error" in last["class"]


def test_status_endpoint_reports_running_state_and_message():
    manager, release = _busy_manager()
    try:
        running = _app(pull_manager=manager).test_client().get("/status").get_json()
        assert running == {"running": True, "message": "Fetching page 3", "succeeded": None}
    finally:
        release.set()
        manager.wait()

    finished = _app(pull_manager=manager).test_client().get("/status").get_json()
    assert finished == {
        "running": False,
        "message": "No new entries were available; the database is already up to date.",
        "succeeded": True,
    }


# ---- analysis cache --------------------------------------------------------------------

def test_analysis_cache_computes_on_first_use_and_refresh_replaces_the_snapshot():
    query = SpyQuery(fake_analysis(total_entries=1))
    cache = AnalysisCache(NullSession, query)
    assert cache.analysis is None and cache.updated_at is None

    assert cache.current()["total_entries"] == 1
    assert cache.current()["total_entries"] == 1
    assert query.calls == 1

    query.analysis = fake_analysis(total_entries=2)
    assert cache.refresh()["total_entries"] == 2
    assert cache.current()["total_entries"] == 2
    assert query.calls == 2


# ---- the real page, through the ORM ------------------------------------------------------

def test_page_shows_every_question_with_results_from_the_database(make_app, test_conn):
    load_records(test_conn, SEED)
    response = make_app().test_client().get("/analysis")
    page = _text(response)
    answers = [a.get_text(" ", strip=True) for a in _soup(response).select('[data-testid="answer"]')]

    for question in QUESTIONS:
        assert question.question in page
    assert "Answer: Fall 2026 applicant count: 7" in answers      # Q1 on the seeded data
    assert "Answer: Percent international: 33.33%" in answers    # Q2
    assert "Answer: Difference: +1" in answers                    # Q9
    assert "Answer: American: 50.00% accepted (n = 2)" in answers  # original question 1


def test_the_page_reads_through_the_orm_and_the_app_runs_no_sql_itself():
    tree = ast.parse(Path(app_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    names_from_query_data = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
            if node.module == "query_data":
                names_from_query_data.update(alias.name for alias in node.names)

    # The analysis page's data still comes from the ORM ...
    assert "orm_queries" in imported
    # ... the only raw-SQL function the app uses is the vetted GET /applicants search ...
    assert names_from_query_data == {"search_applicants"}
    # ... and this module never builds or runs a statement itself.
    executed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany"}
    ]
    assert executed == []
