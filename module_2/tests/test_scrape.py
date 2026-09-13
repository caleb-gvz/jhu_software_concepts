import urllib.error
import urllib.robotparser
from pathlib import Path
from unittest.mock import patch

import pytest

from scrape import (
    BASE_URL,
    _build_survey_url,
    _check_robots_allowed,
    _extract_page_records,
    _fetch_page,
    _merge_robots_groups,
)

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
