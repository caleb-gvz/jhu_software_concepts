"""Tests for query_data.py against a small hand-built dataset with known answers.

Every row below exists to exercise one rule from the assignment; the expected values
in the tests were worked out by hand from this table.
"""

import pytest

from load_data import load_records
from query_data import QUERIES, get_query, run_all, run_query

pytestmark = pytest.mark.db


def _rec(record_id, term="Fall 2026", status="Accepted", degree="PhD", program="Biology, X University",
         nationality=None, gpa=None, gre=None, gre_v=None, gre_aw=None, llm_program=None, llm_university=None):
    record = {
        "id": record_id, "url": f"u{record_id}", "term": term, "applicant_status": status,
        "degree": degree, "program": program, "us_or_international": nationality,
        "gpa": gpa, "gre_score": gre, "gre_v": gre_v, "gre_aw": gre_aw,
    }
    if llm_program:
        record["llm-generated-program"] = llm_program
        record["llm-generated-university"] = llm_university
    return record


SEED = [
    # --- Fall 2026 ---------------------------------------------------------------
    _rec(1, nationality="American", gpa=3.8, gre=160, gre_v=150, gre_aw=4.0,
         program="Computer Science, Stanford University",
         llm_program="Computer Science", llm_university="Stanford University"),
    _rec(2, status="Rejected", degree="Masters", nationality="American", gre_v=155,
         program="Computer Science, Johns Hopkins University"),
    # lower-case term/status; original text hides "Computer Science", only the LLM fields reveal it
    _rec(3, term="fall 2026", status="accepted", nationality="International", gpa=3.4, gre=170, gre_aw=5.0,
         program="Comp Sci, MIT",
         llm_program="Computer Science", llm_university="Massachusetts Institute of Technology"),
    _rec(4, status="Rejected", degree="Masters", nationality="International", gpa=3.6, gre_aw=4.5,
         program="Computer Science, JHU"),
    _rec(5, nationality="Other", gpa=3.2, program="Computer Science, Carnegie Mellon University",
         llm_program="Computer Science", llm_university="Carnegie Mellon University"),
    _rec(14, degree="Masters", program="Computer Science, Stanford University",           # wrong degree
         llm_program="Computer Science", llm_university="Stanford University"),
    _rec(15, program="Computer Science, University of Washington",                        # wrong university
         llm_program="Computer Science", llm_university="University of Washington"),
    # --- Fall 2025 ---------------------------------------------------------------
    _rec(6, term="Fall 2025", degree="Masters", nationality="American", gpa=3.5),
    _rec(7, term="Fall 2025", status="Rejected", nationality="International", gpa=3.0),
    _rec(8, term="Fall 2025", status="Rejected", nationality="American"),
    _rec(9, term="Fall 2025"),                                                            # blank nationality
    _rec(10, term="Fall 2025", status="Wait listed", nationality="American"),
    # --- other terms (must not leak into Fall 2026 / Fall 2025 answers) -----------
    _rec(11, term="Spring 2026"),
    _rec(12, term="Spring 2027", program="Computer Science, Johns Hopkins University"),   # JHU CS but PhD
    _rec(13, term="Spring 2027", degree="Masters", program="Music, Johns Hopkins University"),  # JHU master's, not CS
]


@pytest.fixture
def seeded_conn(test_conn):
    load_records(test_conn, SEED)
    return test_conn


def _lines(conn, number):
    return run_query(conn, get_query(number))


def test_q1_counts_fall_2026_entries_case_insensitively(seeded_conn):
    assert _lines(seeded_conn, "1") == ["Fall 2026 applicant count: 7"]


def test_q2_excludes_blank_nationality_and_counts_other_as_not_international(seeded_conn):
    # 9 entries have a nationality; 3 are International
    assert _lines(seeded_conn, "2") == ["Percent international: 33.33%"]


def test_q3_each_average_uses_only_applicants_who_provide_that_metric(seeded_conn):
    assert _lines(seeded_conn, "3") == [
        "Average GPA: 3.42",
        "Average GRE Quantitative: 165.00",
        "Average GRE Verbal: 152.50",
        "Average GRE Analytical Writing: 4.50",
    ]


def test_q4_averages_only_american_fall_2026_applicants_with_a_gpa(seeded_conn):
    # row 2 is American Fall 2026 but has no GPA, so only row 1 counts
    assert _lines(seeded_conn, "4") == ["Average GPA of American Fall 2026 applicants: 3.80"]


def test_q5_fall_2025_acceptance_percentage(seeded_conn):
    # 2 of 5 Fall 2025 entries are acceptances
    assert _lines(seeded_conn, "5") == ["Fall 2025 acceptance percentage: 40.00%"]


def test_q6_average_gpa_of_accepted_fall_2026_applicants(seeded_conn):
    # rows 1, 3, 5 -> (3.8 + 3.4 + 3.2) / 3
    assert _lines(seeded_conn, "6") == ["Average GPA of accepted Fall 2026 applicants: 3.47"]


def test_q7_matches_johns_hopkins_and_jhu_computer_science_masters_only(seeded_conn):
    # rows 2 (Johns Hopkins) and 4 (JHU); row 12 is a PhD, row 13 is not Computer Science
    assert _lines(seeded_conn, "7") == ["Johns Hopkins University Computer Science master's entries: 2"]


def test_q8_uses_original_fields_and_all_four_restrictions(seeded_conn):
    # row 1 (Stanford) and row 5 (CMU). Row 3's original text says "Comp Sci, MIT";
    # row 14 is a master's and row 15 is a different university.
    assert _lines(seeded_conn, "8") == ["Fall 2026 accepted PhD Computer Science entries (original fields): 2"]


def test_q9_reports_both_counts_and_the_signed_difference(seeded_conn):
    # LLM fields also recognise row 3 (MIT), so 3 vs 2
    assert _lines(seeded_conn, "9") == [
        "Original-field count: 2",
        "LLM-field count: 3",
        "Difference: +1",
    ]


def test_original_question_1_acceptance_rate_by_nationality_group(seeded_conn):
    assert _lines(seeded_conn, "O1") == [
        "American: 50.00% accepted (n = 2)",
        "International: 50.00% accepted (n = 2)",
        "Unknown: 100.00% accepted (n = 2)",
        "Other: 100.00% accepted (n = 1)",
    ]


def test_original_question_2_accepted_versus_rejected_averages(seeded_conn):
    assert _lines(seeded_conn, "O2") == [
        "Accepted (n = 5): average GPA 3.47, average GRE Quantitative 165.00",
        "Rejected (n = 2): average GPA 3.60, average GRE Quantitative N/A",
    ]


def test_every_query_carries_the_text_the_pdf_needs():
    numbers = [query.number for query in QUERIES]
    assert numbers == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "O1", "O2"]
    for query in QUERIES:
        assert query.question.endswith("?")
        assert query.sql.strip().upper().startswith("SELECT")
        assert "SELECT *" not in query.sql.upper()
        assert len(query.explanation) > 40


def test_run_all_returns_every_query_with_its_result_lines(seeded_conn):
    results = run_all(seeded_conn)
    assert [query.number for query, _ in results] == [q.number for q in QUERIES]
    assert all(lines for _, lines in results)


def test_queries_on_an_empty_table_do_not_crash(test_conn):
    for query in QUERIES:
        assert run_query(test_conn, query)   # renders N/A / 0 instead of raising
