import urllib.error
import urllib.robotparser

import pytest

from scrape import ScrapeError, scrape_new_records
from tests.test_scrape import _allow_all_robots_parser, _page_html, _record


def _fetcher(pages):
    """Fake fetch function that serves the given pages in order and counts calls."""
    calls = []
    iterator = iter(pages)

    def fetch(url):
        calls.append(url)
        return next(iterator)

    fetch.calls = calls
    return fetch


def _pull(fetch, known_ids=frozenset(), **kwargs):
    return scrape_new_records(
        known_ids=set(known_ids),
        delay_seconds=0,
        fetch_fn=fetch,
        robots_parser=_allow_all_robots_parser(),
        **kwargs,
    )


def test_returns_only_records_not_already_known_and_parses_them():
    fetch = _fetcher([_page_html([_record(10), _record(9), _record(8)], None)])

    records = _pull(fetch, known_ids={8})

    assert [r["id"] for r in records] == [10, 9]
    assert records[0]["url"].endswith("/result/10")
    assert records[0]["applicant_status"] == "Accepted"   # parsed into the Module 2 schema


def test_stops_at_first_page_containing_only_known_ids():
    fetch = _fetcher([
        _page_html([_record(12), _record(11)], "c2"),
        _page_html([_record(10), _record(9)], "c3"),     # all known -> boundary reached
        _page_html([_record(8)], None),                  # must never be requested
    ])

    records = _pull(fetch, known_ids={10, 9, 8})

    assert [r["id"] for r in records] == [12, 11]
    assert len(fetch.calls) == 2


def test_continues_through_a_page_that_mixes_new_and_known_ids():
    fetch = _fetcher([
        _page_html([_record(12), _record(5)], "c2"),
        _page_html([_record(11)], None),
    ])

    records = _pull(fetch, known_ids={5})

    assert [r["id"] for r in records] == [12, 11]


def test_max_pages_limits_how_many_pages_are_fetched():
    fetch = _fetcher([
        _page_html([_record(30)], "c2"),
        _page_html([_record(29)], "c3"),
        _page_html([_record(28)], "c4"),
    ])

    records = _pull(fetch, max_pages=2)

    assert [r["id"] for r in records] == [30, 29]
    assert len(fetch.calls) == 2


def test_stops_when_there_is_no_next_page():
    fetch = _fetcher([_page_html([_record(1)], None)])
    assert [r["id"] for r in _pull(fetch)] == [1]
    assert len(fetch.calls) == 1


def test_duplicate_ids_across_pages_are_returned_once():
    fetch = _fetcher([
        _page_html([_record(7), _record(6)], "c2"),
        _page_html([_record(6), _record(5)], None),
    ])
    assert [r["id"] for r in _pull(fetch)] == [7, 6, 5]


def test_http_403_raises_scrape_error_with_readable_message():
    def blocked(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    with pytest.raises(ScrapeError) as excinfo:
        _pull(blocked)

    assert "403" in str(excinfo.value)
    assert excinfo.value.partial_records == []


def test_error_after_some_pages_keeps_the_partial_records():
    def second_page_fails(url, _state={"n": 0}):
        _state["n"] += 1
        if _state["n"] == 1:
            return _page_html([_record(20)], "c2")
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    with pytest.raises(ScrapeError) as excinfo:
        _pull(second_page_fails)

    assert [r["id"] for r in excinfo.value.partial_records] == [20]


def test_unreachable_network_raises_scrape_error():
    def offline(url):
        raise urllib.error.URLError("no route to host")

    with pytest.raises(ScrapeError, match="Could not reach"):
        _pull(offline)


def test_unparseable_page_raises_scrape_error():
    with pytest.raises(ScrapeError, match="Could not read"):
        _pull(_fetcher(["<html>no payload here</html>"]))


def test_robots_disallow_raises_scrape_error_without_fetching():
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    fetch = _fetcher([_page_html([_record(1)], None)])

    with pytest.raises(ScrapeError, match="robots.txt"):
        scrape_new_records(set(), delay_seconds=0, fetch_fn=fetch, robots_parser=parser)

    assert fetch.calls == []
