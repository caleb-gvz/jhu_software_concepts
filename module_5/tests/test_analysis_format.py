"""Analysis formatting on the rendered page: "Answer:" labels and two-decimal percentages."""

import re

import pytest
from bs4 import BeautifulSoup

from flask_app import create_app
from load_data import load_records
from tests.doubles import NullSession, SpyQuery, fake_analysis
from tests.test_query_data import SEED

pytestmark = pytest.mark.analysis

# Any number immediately followed by "%", e.g. "7%", "39.2%", "39.28%", "1,234.5%".
ANY_PERCENT = re.compile(r"\d[\d,]*(?:\.\d+)?%")
# The only accepted shape: exactly two digits after the decimal point.
TWO_DECIMAL_PERCENT = re.compile(r"\d[\d,]*\.\d{2}%")


def _soup(response):
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


def _fake_page(analysis=None):
    app = create_app({"TESTING": True}, query_fn=SpyQuery(analysis), session_factory=NullSession)
    return _soup(app.test_client().get("/analysis"))


@pytest.fixture
def real_page(make_app, test_conn):
    """The page rendered from real (seeded) rows through the ORM."""
    load_records(test_conn, SEED)
    return _soup(make_app().test_client().get("/analysis"))


def _assert_answer_labels(soup):
    answers = soup.select('[data-testid="answer"]')
    assert answers, "the page shows no analysis answers"
    for answer in answers:
        label = answer.select_one(".answer-label")
        assert label is not None and label.get_text() == "Answer:"
        assert answer.get_text(" ", strip=True).startswith("Answer: ")
    return answers


def _assert_two_decimal_percentages(soup):
    percentages = ANY_PERCENT.findall(soup.get_text(" "))
    for value in percentages:
        assert TWO_DECIMAL_PERCENT.fullmatch(value), f"{value} does not have exactly two decimals"
    return percentages


# ---- labels --------------------------------------------------------------------------------

def test_every_rendered_analysis_line_is_labeled_answer():
    soup = _fake_page()
    answers = _assert_answer_labels(soup)
    assert len(answers) == 4          # 1 + 2 lines in the assigned cards, 1 in the original card


def test_every_card_has_at_least_one_answer():
    for card in _fake_page().select('[data-testid="analysis-card"]'):
        assert card.select('[data-testid="answer"]')


def test_real_analysis_is_labeled_answer_for_all_eleven_questions(real_page):
    cards = real_page.select('[data-testid="analysis-card"]')
    assert len(cards) == 11
    for card in cards:
        assert card.select('[data-testid="answer"]')
    _assert_answer_labels(real_page)


# ---- percentages -----------------------------------------------------------------------------

def test_percentages_on_the_page_have_exactly_two_decimals():
    percentages = _assert_two_decimal_percentages(_fake_page())
    assert percentages == ["39.28%", "50.00%"]


def test_real_analysis_percentages_have_exactly_two_decimals(real_page):
    percentages = _assert_two_decimal_percentages(real_page)
    assert "33.33%" in percentages            # Q2 on the seeded data
    assert "50.00%" in percentages            # whole-number percent still shows .00


def test_the_percentage_checker_rejects_other_precisions():
    for bad in ("39%", "39.2%", "39.283%"):
        page = _fake_page({
            "total_entries": 1, "original": [],
            "assigned": [{"number": "2", "label": "Question 2", "title": "t", "question": "q",
                          "answers": [f"Percent international: {bad}"]}],
        })
        with pytest.raises(AssertionError):
            _assert_two_decimal_percentages(page)


def test_total_entries_is_a_whole_number_with_thousands_separator():
    soup = _fake_page(fake_analysis(total_entries=40123))
    assert soup.select_one('[data-testid="total-entries"]').get_text() == "40,123"
