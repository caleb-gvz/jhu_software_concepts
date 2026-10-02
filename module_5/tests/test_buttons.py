"""The "Pull Data" and "Update Analysis" endpoints and the busy-state rules.

Busy state is made observable, never timed: a ``BlockingScraper`` (or a job waiting on
a ``threading.Event``) holds a pull open while the test checks the 409 responses, and
the test then releases it. No test calls ``sleep()``.
"""

import threading

import pytest

from pull_data import PullResult
from pull_manager import PullManager, PullOutcome
from tests.doubles import (
    BlockingScraper,
    FailingLoader,
    FakeScraper,
    NullSession,
    SpyLoader,
    SpyQuery,
    make_record,
)

pytestmark = pytest.mark.buttons


def _count_rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM applicants")
        return cur.fetchone()[0]


# ---- POST /pull-data ---------------------------------------------------------------------

def test_pull_data_returns_200_with_ok_true_and_loads_the_scraped_rows(make_app):
    scraper = FakeScraper([make_record(1), make_record(2), make_record(3)])
    loader = SpyLoader()
    client = make_app(scraper=scraper, loader=loader).test_client()

    response = client.post("/pull-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True and body["busy"] is False
    assert body["added"] == 3
    assert "Added 3 new records" in body["message"]
    # The loader was triggered exactly once, with the scraper's rows (after cleaning).
    assert len(scraper.calls) == 1
    assert [[record["id"] for record in batch] for batch in loader.batches] == [[1, 2, 3]]


def test_pull_data_in_background_returns_202_with_ok_true(make_app, test_conn):
    scraper = FakeScraper([make_record(10), make_record(11)])
    app = make_app({"PULL_IN_BACKGROUND": True}, scraper=scraper)

    response = app.test_client().post("/pull-data")

    assert response.status_code == 202
    assert response.get_json()["ok"] is True
    app.extensions["gradcafe"]["pull_manager"].wait(timeout=30)
    assert _count_rows(test_conn) == 2


def test_pull_data_tells_the_scraper_which_ids_are_already_stored(make_app):
    scraper = FakeScraper([make_record(1)], [make_record(2)])
    client = make_app(scraper=scraper).test_client()

    client.post("/pull-data")
    client.post("/pull-data")

    assert scraper.calls == [set(), {1}]


# ---- POST /update-analysis ---------------------------------------------------------------

def test_update_analysis_returns_200_when_not_busy_and_reruns_the_queries():
    from flask_app import create_app

    query = SpyQuery()
    client = create_app({"TESTING": True}, query_fn=query, session_factory=NullSession).test_client()
    client.get("/analysis")

    response = client.post("/update-analysis")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True and body["busy"] is False
    assert body["total_entries"] == 3
    assert query.calls == 2          # page load + the update


def test_update_analysis_never_starts_a_scrape(make_app):
    scraper = FakeScraper([make_record(1)])
    make_app(scraper=scraper).test_client().post("/update-analysis")
    assert scraper.calls == []


# ---- busy gating -------------------------------------------------------------------------

@pytest.fixture
def busy_app(make_app):
    """An app whose background pull is held "in progress" until the test releases it."""
    scraper = BlockingScraper([make_record(1)])
    query = SpyQuery()
    app = make_app({"PULL_IN_BACKGROUND": True}, scraper=scraper, query_fn=query)
    client = app.test_client()
    assert client.post("/pull-data").status_code == 202
    assert scraper.started.wait(timeout=30)          # the pull is now mid-scrape
    yield app, client, scraper, query
    scraper.release.set()
    app.extensions["gradcafe"]["pull_manager"].wait(timeout=30)


def test_update_analysis_returns_409_busy_and_performs_no_update_during_a_pull(busy_app):
    app, client, scraper, query = busy_app

    response = client.post("/update-analysis")

    assert response.status_code == 409
    assert response.get_json()["busy"] is True
    assert response.get_json()["ok"] is False
    assert query.calls == 0                           # no re-query happened
    assert app.extensions["gradcafe"]["analysis_cache"].analysis is None


def test_pull_data_returns_409_busy_while_a_pull_is_running(busy_app):
    app, client, scraper, query = busy_app

    response = client.post("/pull-data")

    assert response.status_code == 409
    assert response.get_json()["busy"] is True
    assert len(scraper.calls) == 0 and scraper.started.is_set()   # only the first pull ran


def test_busy_state_clears_when_the_pull_finishes(busy_app, test_conn):
    app, client, scraper, query = busy_app
    manager = app.extensions["gradcafe"]["pull_manager"]
    assert manager.is_running()

    scraper.release.set()
    manager.wait(timeout=30)

    assert not manager.is_running()
    assert client.post("/update-analysis").status_code == 200
    assert _count_rows(test_conn) == 1


def test_synchronous_pull_is_also_gated_while_another_pull_runs():
    from flask_app import create_app

    manager, release, started = PullManager(), threading.Event(), threading.Event()

    def held_job(report):
        started.set()
        release.wait(timeout=30)
        return PullResult(added=0)

    manager.start(held_job)
    started.wait(timeout=30)
    app = create_app({"TESTING": True, "PULL_IN_BACKGROUND": False},
                     pull_manager=manager, query_fn=SpyQuery(), session_factory=NullSession)
    try:
        response = app.test_client().post("/pull-data")
        assert response.status_code == 409
        assert response.get_json()["busy"] is True
    finally:
        release.set()
        manager.wait()


# ---- error paths ---------------------------------------------------------------------------

def test_loader_failure_returns_500_and_leaves_no_partial_writes(make_app, test_conn):
    scraper = FakeScraper([make_record(1), make_record(2)])
    client = make_app(scraper=scraper, loader=FailingLoader("disk full")).test_client()

    response = client.post("/pull-data")

    assert response.status_code == 500
    body = response.get_json()
    assert body["ok"] is False
    assert "disk full" in body["error"]
    assert _count_rows(test_conn) == 0       # the half-written row was rolled back


def test_blocked_scrape_returns_500_but_keeps_the_records_fetched_before_it(make_app, test_conn):
    from scrape import ScrapeError

    def blocked(known_ids, max_pages):
        raise ScrapeError("Grad Cafe blocked or rejected the request (HTTP 403).", [make_record(7)])

    response = make_app(scraper=blocked).test_client().post("/pull-data")

    assert response.status_code == 500
    assert "HTTP 403" in response.get_json()["error"]
    assert _count_rows(test_conn) == 1


def test_unreachable_database_during_a_pull_is_reported_not_raised():
    from flask_app import create_app

    app = create_app(
        {"TESTING": True, "PULL_IN_BACKGROUND": False,
         "DATABASE_URL": "postgresql://nobody@127.0.0.1:1/nowhere?connect_timeout=2"},
        scraper=FakeScraper([make_record(1)]), query_fn=SpyQuery(), session_factory=NullSession,
    )
    response = app.test_client().post("/pull-data")

    assert response.status_code == 500
    assert "The data pull failed" in response.get_json()["error"]
    assert app.extensions["gradcafe"]["pull_manager"].is_running() is False


def test_update_analysis_reports_a_database_outage_with_503():
    from flask_app import create_app
    from sqlalchemy.exc import OperationalError

    def broken_factory():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    app = create_app({"TESTING": True}, session_factory=broken_factory, query_fn=SpyQuery())
    response = app.test_client().post("/update-analysis")

    assert response.status_code == 503
    assert response.get_json()["ok"] is False


# ---- PullManager on its own ------------------------------------------------------------------

def test_idle_manager_has_no_message_and_no_result_yet():
    manager = PullManager()
    assert manager.last_message == ""
    assert manager.last_succeeded is None
    assert not manager.is_running()
    manager.wait()                         # nothing to wait for; returns immediately


def test_run_returns_the_outcome_of_a_successful_job():
    manager = PullManager()
    outcome = manager.run(lambda report: PullResult(added=2))
    assert outcome == PullOutcome(succeeded=True, message="Added 2 new records to the database.", added=2)
    assert manager.last_succeeded is True and not manager.is_running()


def test_job_exceptions_become_a_failed_outcome_with_a_readable_message():
    def exploding(report):
        raise ValueError("bad page")

    manager = PullManager()
    outcome = manager.run(exploding)
    assert outcome.succeeded is False
    assert outcome.message == "The data pull failed: bad page"
    assert manager.last_message == outcome.message


def test_start_refuses_a_second_job_and_run_returns_none_while_busy():
    manager, release, started = PullManager(), threading.Event(), threading.Event()

    def held_job(report):
        report("Fetching page 1")
        started.set()
        release.wait(timeout=30)
        return PullResult(added=1)

    assert manager.start(held_job) is True
    started.wait(timeout=30)
    assert manager.is_running()
    assert manager.last_message == "Fetching page 1"
    assert manager.start(held_job) is False
    assert manager.run(held_job) is None

    release.set()
    manager.wait()
    assert not manager.is_running()
    assert manager.last_message == "Added 1 new record to the database."
    assert manager.start(lambda report: PullResult(added=0)) is True    # free again
    manager.wait()
