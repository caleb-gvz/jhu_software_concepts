import pytest

from clean import _clean_text, _normalize_status, clean_data, coerce_float

pytestmark = pytest.mark.db


def test_clean_text_collapses_whitespace():
    assert _clean_text("  Computer   Science \n") == "Computer Science"


def test_clean_text_empty_string_becomes_none():
    assert _clean_text("   ") is None


def test_clean_text_passes_through_non_strings():
    assert _clean_text(None) is None
    assert _clean_text(3.5) == 3.5


def test_normalize_status_collapses_whitespace():
    assert _normalize_status("  Accepted  ") == "Accepted"
    assert _normalize_status(None) is None


def test_coerce_float_from_mixed_types():
    assert coerce_float("3.9") == 3.9
    assert coerce_float("3.57") == 3.57
    assert coerce_float(163) == 163.0
    assert coerce_float(None) is None
    assert coerce_float("N/A") is None


def test_clean_data_normalizes_whitespace_and_preserves_raw_fields():
    records = [
        {
            "id": 1,
            "program_raw": "  Creative Writing Poetry  ",
            "university_raw": "  Bennington College ",
            "program": "  Creative Writing Poetry,  Bennington College ",
            "degree": "MFA",
            "applicant_status": "  Accepted ",
            "status_date": "2026-09-11",
            "gpa": "3.9",
            "gre_score": None,
            "comments": "   ",
        }
    ]
    cleaned = clean_data(records)
    assert cleaned[0]["program_raw"] == "Creative Writing Poetry"
    assert cleaned[0]["university_raw"] == "Bennington College"
    assert cleaned[0]["applicant_status"] == "Accepted"
    assert cleaned[0]["gpa"] == 3.9
    assert cleaned[0]["comments"] is None
    # id untouched (not a text field)
    assert cleaned[0]["id"] == 1


def test_clean_data_does_not_mutate_input():
    records = [{"id": 1, "program_raw": "  X  "}]
    clean_data(records)
    assert records[0]["program_raw"] == "  X  "  # original left untouched
