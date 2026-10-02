import json as json_module
import urllib.error
import urllib.robotparser
from pathlib import Path
from unittest.mock import patch

import pytest

from scrape import (
    BASE_URL,
    _build_survey_url,
    _check_robots_allowed,
    _coerce_float,
    _extract_page_records,
    _fetch_page,
    _merge_robots_groups,
    _parse_record,
    load_data,
    save_data,
    scrape_data,
)

pytestmark = pytest.mark.db

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "survey_page_sample.html"

# Real robots.txt fetched from https://www.thegradcafe.com/robots.txt on 2026-09-13
ROBOTS_TXT_FIXTURE = """\
User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /

User-agent: ClaudeBot
Disallow: /

User-agent: *
Disallow: /signin
Disallow: /register
Disallow: /forgot-password
Disallow: /reset-password
Disallow: /confirm-password
Disallow: /verify-email
Disallow: /profile
Sitemap: https://www.thegradcafe.com/sitemap.xml
"""


def _make_parser() -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(_merge_robots_groups(ROBOTS_TXT_FIXTURE).splitlines())
    return rp


def test_merge_robots_groups_combines_duplicate_wildcard_blocks():
    merged = _merge_robots_groups(ROBOTS_TXT_FIXTURE)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(merged.splitlines())
    # Both the first "*" block's Allow: / and the second "*" block's
    # Disallow: /signin must survive the merge.
    assert rp.can_fetch("*", f"{BASE_URL}/survey") is True
    assert rp.can_fetch("*", f"{BASE_URL}/signin") is False


def test_build_survey_url_no_cursor():
    assert _build_survey_url() == f"{BASE_URL}/survey"


def test_build_survey_url_with_cursor():
    url = _build_survey_url("abc123")
    assert url == f"{BASE_URL}/survey?cursor=abc123"


def test_robots_allows_survey_path():
    parser = _make_parser()
    assert _check_robots_allowed(f"{BASE_URL}/survey?cursor=abc", parser) is True


def test_robots_disallows_signin():
    parser = _make_parser()
    assert _check_robots_allowed(f"{BASE_URL}/signin", parser) is False


def test_extract_page_records_returns_records_and_cursor():
    html_text = FIXTURE_PATH.read_text(encoding="utf-8")
    records, next_cursor = _extract_page_records(html_text)
    assert len(records) == 2
    assert records[0]["id"] == 1020482
    assert records[0]["school"] == "Bennington College"
    assert records[1]["decision"] == "Interview"
    assert next_cursor == (
        "eyJjcmVhdGVkX2F0IjoiMjAyNi0wOC0yOCAxNzo1MToxMCIsImFkbWl0aWQiOjEwMjA0"
        "NjMsIl9wb2ludHNUb05leHRJdGVtcyI6dHJ1ZX0"
    )


def test_extract_page_records_raises_on_missing_payload():
    with pytest.raises(ValueError):
        _extract_page_records("<html><body>no data-page here</body></html>")


def test_fetch_page_raises_on_http_error():
    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://www.thegradcafe.com/survey", 403, "Forbidden", {}, None
        )

    with patch("urllib.request.urlopen", side_effect=_raise):
        with pytest.raises(urllib.error.HTTPError):
            _fetch_page("https://www.thegradcafe.com/survey")


# Real records captured from https://www.thegradcafe.com/survey on 2026-09-13
ACCEPTED_RECORD = {
    "id": 1020482,
    "school": "Bennington College",
    "program": "Creative Writing Poetry",
    "level": "MFA",
    "decision": "Accepted",
    "decision_label": "Accepted on Sep 11",
    "acceptedDate": "2026-09-11",
    "rejectedDate": None,
    "waitlistedDate": None,
    "interviewDate": None,
    "season": "Spring 2027",
    "status": "American",
    "ugpa": None,
    "greq": None,
    "grev": None,
    "grew": None,
    "gres": None,
    "notes": "Have no idea if I will attend.",
    "created_at": "2026-09-12",
    "added_on_label": "Sep 12, 2026",
}

WAITLISTED_RECORD_WITH_GRE = {
    "id": 1020479,
    "school": "Bangladesh University of Engineering and Technology (BUET)",
    "program": "Electrical Engineering and Computer Science",
    "level": "PhD",
    "decision": "Wait listed",
    "decision_label": "Wait listed on Sep 10",
    "acceptedDate": None,
    "rejectedDate": None,
    "waitlistedDate": "2026-09-10",
    "interviewDate": None,
    "season": "Spring 2027",
    "status": "International",
    "ugpa": "3.57",
    "greq": 163,
    "grev": 158,
    "grew": "4.00",
    "gres": None,
    "notes": None,
    "created_at": "2026-09-10",
    "added_on_label": "Sep 10, 2026",
}


def test_coerce_float_handles_none_str_int():
    assert _coerce_float(None) is None
    assert _coerce_float("3.57") == 3.57
    assert _coerce_float(163) == 163.0
    assert _coerce_float("not a number") is None


def test_parse_record_accepted_no_scores():
    parsed = _parse_record(ACCEPTED_RECORD)
    assert parsed["id"] == 1020482
    assert parsed["url"] == "https://www.thegradcafe.com/result/1020482"
    assert parsed["program_raw"] == "Creative Writing Poetry"
    assert parsed["university_raw"] == "Bennington College"
    assert parsed["program"] == "Creative Writing Poetry, Bennington College"
    assert parsed["degree"] == "MFA"
    assert parsed["applicant_status"] == "Accepted"
    assert parsed["status_date"] == "2026-09-11"
    assert parsed["term"] == "Spring 2027"
    assert parsed["us_or_international"] == "American"
    assert parsed["gpa"] is None
    assert parsed["gre_score"] is None
    assert parsed["comments"] == "Have no idea if I will attend."
    assert parsed["date_added"] == "Sep 12, 2026"


def test_parse_record_waitlisted_with_mixed_type_scores():
    parsed = _parse_record(WAITLISTED_RECORD_WITH_GRE)
    assert parsed["applicant_status"] == "Wait listed"
    assert parsed["status_date"] == "2026-09-10"
    assert parsed["gpa"] == 3.57
    assert parsed["gre_score"] == 163.0
    assert parsed["gre_v"] == 158.0
    assert parsed["gre_aw"] == 4.0


def _allow_all_robots_parser():
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(["User-agent: *", "Allow: /"])
    return rp


def _page_html(records, next_cursor):
    payload = {
        "props": {"results": {"data": records, "meta": {"next_cursor": next_cursor}}}
    }
    escaped = json_module.dumps(payload).replace('"', "&quot;")
    return f'<div id="app" data-page="{escaped}"></div>'


def _record(rid):
    return {
        "id": rid,
        "school": f"School {rid}",
        "program": f"Program {rid}",
        "level": "Masters",
        "decision": "Accepted",
        "decision_label": "Accepted",
        "acceptedDate": "2026-01-01",
        "rejectedDate": None,
        "waitlistedDate": None,
        "interviewDate": None,
        "season": "Fall 2026",
        "status": "American",
        "ugpa": None,
        "greq": None,
        "grev": None,
        "grew": None,
        "gres": None,
        "notes": None,
        "created_at": "2026-01-01",
        "added_on_label": "Jan 1, 2026",
    }


def test_save_and_load_data_round_trip(tmp_path):
    path = tmp_path / "out.json"
    records = [{"id": 1, "program": "X"}]
    save_data(records, str(path))
    assert load_data(str(path)) == records


def test_load_data_missing_file_returns_empty_list(tmp_path):
    assert load_data(str(tmp_path / "missing.json")) == []


def test_scrape_data_paginates_until_target_reached(tmp_path):
    output_path = tmp_path / "applicant_data.json"
    checkpoint_path = tmp_path / "checkpoint.json"

    page1 = _page_html([_record(1), _record(2)], "cursor-2")
    page2 = _page_html([_record(3), _record(4)], None)
    pages = iter([page1, page2])

    def fake_fetch(url):
        return next(pages)

    records = scrape_data(
        target_count=3,
        output_path=str(output_path),
        checkpoint_path=str(checkpoint_path),
        delay_seconds=0,
        fetch_fn=fake_fetch,
        robots_parser=_allow_all_robots_parser(),
    )

    assert len(records) == 4  # page granularity: stops after the page that reaches target
    assert [r["id"] for r in records] == [1, 2, 3, 4]
    assert load_data(str(output_path)) == records


def test_scrape_data_resumes_from_checkpoint(tmp_path):
    from scrape import _parse_record as parse_record

    output_path = tmp_path / "applicant_data.json"
    checkpoint_path = tmp_path / "checkpoint.json"

    # Simulate a prior run that already scraped id 1 and checkpointed cursor-2.
    save_data([parse_record(_record(1))], str(output_path))
    checkpoint_path.write_text(
        json_module.dumps({"next_cursor": "cursor-2", "seen_ids": [1]}),
        encoding="utf-8",
    )

    page2 = _page_html([_record(2), _record(3)], None)
    resumed = scrape_data(
        target_count=3,
        output_path=str(output_path),
        checkpoint_path=str(checkpoint_path),
        delay_seconds=0,
        fetch_fn=lambda url: page2,
        robots_parser=_allow_all_robots_parser(),
    )
    ids = sorted(r["id"] for r in resumed)
    assert ids == [1, 2, 3]  # no duplicate of id 1, continued from checkpoint


def test_scrape_data_stops_on_http_error(tmp_path):
    output_path = tmp_path / "applicant_data.json"
    checkpoint_path = tmp_path / "checkpoint.json"

    def failing_fetch(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    records = scrape_data(
        target_count=100,
        output_path=str(output_path),
        checkpoint_path=str(checkpoint_path),
        delay_seconds=0,
        fetch_fn=failing_fetch,
        robots_parser=_allow_all_robots_parser(),
    )
    assert records == []  # stopped immediately, no partial/garbage data
