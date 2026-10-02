"""End-to-end flows: pull -> update -> render, and repeated pulls with overlapping data.

Each test drives the real app (real loader, real ORM queries, real template) through
Flask's test client; only the Grad Cafe scraper is replaced by a fake.
"""

import re

import pytest
from bs4 import BeautifulSoup

from query_data import fetch_applicants
from tests.doubles import FakeScraper, make_record

pytestmark = pytest.mark.integration

TWO_DECIMAL_PERCENT = re.compile(r"\d[\d,]*\.\d{2}%")
ANY_PERCENT = re.compile(r"\d[\d,]*(?:\.\d+)?%")


def _answers(client):
    """Every "Answer:" line on the analysis page, without the label."""
    soup = BeautifulSoup(client.get("/analysis").get_data(as_text=True), "html.parser")
    return [
        answer.get_text(" ", strip=True).removeprefix("Answer: ")
        for answer in soup.select('[data-testid="answer"]')
    ], soup


FIRST_BATCH = [
    make_record(1, us_or_international="American", gpa=3.9),
    make_record(2, us_or_international="International", applicant_status="Rejected", gpa=3.5),
    make_record(3, us_or_international="International", gpa=3.7),
]


def test_pull_then_update_then_render_shows_the_new_analysis(make_app, test_conn):
    client = make_app(scraper=FakeScraper(FIRST_BATCH)).test_client()

    # The page before any data: zero entries, still formatted.
    before, _ = _answers(client)
    assert "Fall 2026 applicant count: 0" in before

    # 1. Pull: the fake scraper's records land in PostgreSQL.
    pull = client.post("/pull-data")
    assert pull.status_code == 200 and pull.get_json()["ok"] is True
    assert [row["p_id"] for row in fetch_applicants(test_conn)] == [1, 2, 3]

    # The page still shows the old snapshot until the analysis is updated.
    stale, _ = _answers(client)
    assert "Fall 2026 applicant count: 0" in stale

    # 2. Update Analysis (not busy) succeeds.
    update = client.post("/update-analysis")
    assert update.status_code == 200 and update.get_json()["total_entries"] == 3

    # 3. Render: the new numbers, correctly formatted.
    after, soup = _answers(client)
    assert "Fall 2026 applicant count: 3" in after
    assert "Percent international: 66.67%" in after
    assert "Fall 2026 accepted PhD Computer Science entries (original fields): 2" in after
    assert "Average GPA: 3.70" in after
    assert "International: 50.00% accepted (n = 2)" in after
    assert soup.select_one('[data-testid="total-entries"]').get_text() == "3"
    percentages = ANY_PERCENT.findall(soup.get_text(" "))
    assert percentages and all(TWO_DECIMAL_PERCENT.fullmatch(value) for value in percentages)


def test_two_pulls_with_overlapping_data_keep_one_row_per_entry(make_app, test_conn):
    second_batch = [
        make_record(3, applicant_status="Rejected"),      # overlaps: already stored
        make_record(4, us_or_international="Other"),
        make_record(5),
    ]
    scraper = FakeScraper(FIRST_BATCH, second_batch)
    client = make_app(scraper=scraper).test_client()

    first = client.post("/pull-data").get_json()
    second = client.post("/pull-data").get_json()

    assert (first["added"], second["added"]) == (3, 2)
    assert scraper.calls[1] == {1, 2, 3}               # the second pull knew what was stored
    rows = fetch_applicants(test_conn)
    assert [row["p_id"] for row in rows] == [1, 2, 3, 4, 5]
    assert rows[2]["status"] == "Accepted"               # the overlap did not overwrite id 3

    client.post("/update-analysis")
    answers, _ = _answers(client)
    assert "Fall 2026 applicant count: 5" in answers
