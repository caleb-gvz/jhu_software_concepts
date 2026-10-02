import pytest
from load_data import load_records
from pull_data import pull_new_data
from scrape import ScrapeError, _parse_record
from tests.test_scrape import _record

pytestmark = pytest.mark.db


def _parsed(record_id, **overrides):
    parsed = _parse_record(_record(record_id))
    parsed.update(overrides)
    return parsed


def _ids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT p_id FROM applicants ORDER BY p_id")
        return [row[0] for row in cur.fetchall()]


def test_only_entries_missing_from_the_database_are_added(test_conn):
    load_records(test_conn, [_parsed(1)])
    seen_by_scraper = {}

    def fake_scrape(known_ids, max_pages):
        seen_by_scraper["known_ids"] = set(known_ids)
        return [_parsed(3), _parsed(2)]

    result = pull_new_data(test_conn, scrape_fn=fake_scrape)

    assert seen_by_scraper["known_ids"] == {1}      # the scraper is told what we already have
    assert result.added == 2 and result.error is None
    assert _ids(test_conn) == [1, 2, 3]


def test_existing_rows_are_never_overwritten_by_a_pull(test_conn):
    load_records(test_conn, [_parsed(1, applicant_status="Accepted")])

    pull_new_data(test_conn, scrape_fn=lambda known, pages: [_parsed(1, applicant_status="Rejected")])

    with test_conn.cursor() as cur:
        cur.execute("SELECT status FROM applicants WHERE p_id = 1")
        assert cur.fetchone()[0] == "Accepted"


def test_pulled_records_are_cleaned_like_module_2_data(test_conn):
    messy = _parsed(7, comments="  lots   of   space  ", gpa="3.9")

    pull_new_data(test_conn, scrape_fn=lambda known, pages: [messy])

    with test_conn.cursor() as cur:
        cur.execute("SELECT comments, gpa FROM applicants WHERE p_id = 7")
        assert cur.fetchone() == ("lots of space", 3.9)


def test_a_blocked_scrape_reports_the_error_and_keeps_partial_records(test_conn):
    def blocked(known_ids, max_pages):
        raise ScrapeError("Grad Cafe blocked or rejected the request (HTTP 403).", [_parsed(9)])

    result = pull_new_data(test_conn, scrape_fn=blocked)

    assert result.added == 1
    assert "HTTP 403" in result.error
    assert _ids(test_conn) == [9]


def test_nothing_new_is_a_success_with_zero_added(test_conn):
    result = pull_new_data(test_conn, scrape_fn=lambda known, pages: [])
    assert result.added == 0 and result.error is None


def test_summary_message_is_user_friendly(test_conn):
    ok = pull_new_data(test_conn, scrape_fn=lambda known, pages: [_parsed(4), _parsed(5)])
    assert ok.summary() == "Added 2 new records to the database."

    none = pull_new_data(test_conn, scrape_fn=lambda known, pages: [])
    assert none.summary() == "No new entries were available; the database is already up to date."

    def blocked(known_ids, max_pages):
        raise ScrapeError("Grad Cafe blocked or rejected the request (HTTP 403).", [_parsed(6)])

    failed = pull_new_data(test_conn, scrape_fn=blocked)
    assert failed.summary() == (
        "Pull stopped: Grad Cafe blocked or rejected the request (HTTP 403). "
        "1 record was added before it stopped."
    )
