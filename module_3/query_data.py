"""Answer the Module 3 analysis questions with raw SQL (psycopg 3).

Each question is a ``Query``: its plain-English text, the exact SQL, a short
explanation, and a ``render`` function that turns the result rows into the formatted
lines the assignment asks for. Keeping them as data lets the console output
(``python query_data.py``), ``query_results.pdf``, and the tests all use one source
of truth, so the SQL shown in the PDF is exactly the SQL that ran.

Matching rules used throughout (all case-insensitive):
* term:   ``LOWER(TRIM(term)) = 'fall 2026'``
* accept: ``status ILIKE 'accept%'``
* averages skip NULLs automatically, so each average uses only the applicants who
  supplied that metric.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, List, Sequence, Tuple

import psycopg

from db_config import connect
from formatting import (
    fmt_average,
    fmt_count,
    fmt_percent,
    fmt_signed_difference,
)

Rows = Sequence[Tuple[Any, ...]]
NO_ROWS_MESSAGE = "No matching entries."


@dataclass(frozen=True)
class Query:
    number: str          # "1".."9" for the assigned questions, "O1"/"O2" for my own
    title: str
    question: str
    sql: str
    explanation: str
    render: Callable[[Rows], List[str]]


def _first_value(rows: Rows) -> Any:
    return rows[0][0] if rows else None


# ---- SQL fragments shared verbatim by Questions 8 and 9 (kept as literals so the PDF
# ---- shows exactly what ran) ------------------------------------------------------

Q1_SQL = """\
SELECT COUNT(*)
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026';"""

Q2_SQL = """\
SELECT 100.0 * COUNT(*) FILTER (WHERE LOWER(us_or_international) = 'international')
       / NULLIF(COUNT(*) FILTER (WHERE NULLIF(TRIM(us_or_international), '') IS NOT NULL), 0)
FROM applicants;"""

Q3_SQL = """\
SELECT AVG(gpa), AVG(gre), AVG(gre_v), AVG(gre_aw)
FROM applicants;"""

Q4_SQL = """\
SELECT AVG(gpa)
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026'
  AND LOWER(TRIM(us_or_international)) = 'american'
  AND gpa IS NOT NULL;"""

Q5_SQL = """\
SELECT 100.0 * COUNT(*) FILTER (WHERE status ILIKE 'accept%') / NULLIF(COUNT(*), 0)
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2025';"""

Q6_SQL = """\
SELECT AVG(gpa)
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026'
  AND status ILIKE 'accept%'
  AND gpa IS NOT NULL;"""

Q7_SQL = r"""SELECT COUNT(*)
FROM applicants
WHERE (program ILIKE '%john% hopkins%' OR program ~* '\yjhu\y')
  AND program ILIKE '%computer science%'
  AND degree ILIKE 'master%';"""

Q8_SQL = r"""SELECT COUNT(*)
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026'
  AND status ILIKE 'accept%'
  AND degree ILIKE 'phd'
  AND program ILIKE '%computer science%'
  AND (program ILIKE '%georgetown%'
       OR program ILIKE '%massachusetts institute of technology%'
       OR program ~* '\ymit\y'
       OR program ILIKE '%stanford%'
       OR program ILIKE '%carnegie mellon%');"""

Q9_SQL = r"""SELECT
    COUNT(*) FILTER (WHERE program ILIKE '%computer science%'
        AND (program ILIKE '%georgetown%'
             OR program ILIKE '%massachusetts institute of technology%'
             OR program ~* '\ymit\y'
             OR program ILIKE '%stanford%'
             OR program ILIKE '%carnegie mellon%')) AS original_field_count,
    COUNT(*) FILTER (WHERE llm_generated_program ILIKE '%computer science%'
        AND (llm_generated_university ILIKE '%georgetown%'
             OR llm_generated_university ILIKE '%massachusetts institute of technology%'
             OR llm_generated_university ~* '\ymit\y'
             OR llm_generated_university ILIKE '%stanford%'
             OR llm_generated_university ILIKE '%carnegie mellon%')) AS llm_field_count
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026'
  AND status ILIKE 'accept%'
  AND degree ILIKE 'phd';"""

O1_SQL = """\
SELECT COALESCE(NULLIF(TRIM(us_or_international), ''), 'Unknown') AS nationality_group,
       COUNT(*) AS entries,
       100.0 * COUNT(*) FILTER (WHERE status ILIKE 'accept%') / COUNT(*) AS acceptance_percent
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026'
GROUP BY nationality_group
ORDER BY entries DESC, nationality_group;"""

O2_SQL = """\
SELECT CASE WHEN status ILIKE 'accept%' THEN 'Accepted' ELSE 'Rejected' END AS outcome,
       COUNT(*) AS entries,
       AVG(gpa) AS average_gpa,
       AVG(gre) AS average_gre_quantitative
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026'
  AND (status ILIKE 'accept%' OR status ILIKE 'reject%')
GROUP BY outcome
ORDER BY outcome;"""


# ---- renderers: result rows -> formatted output lines ---------------------------------

def _render_q1(rows: Rows) -> List[str]:
    return [f"Fall 2026 applicant count: {fmt_count(_first_value(rows))}"]


def _render_q2(rows: Rows) -> List[str]:
    return [f"Percent international: {fmt_percent(_first_value(rows))}"]


def _render_q3(rows: Rows) -> List[str]:
    gpa, gre_q, gre_v, gre_aw = rows[0]
    return [
        f"Average GPA: {fmt_average(gpa)}",
        f"Average GRE Quantitative: {fmt_average(gre_q)}",
        f"Average GRE Verbal: {fmt_average(gre_v)}",
        f"Average GRE Analytical Writing: {fmt_average(gre_aw)}",
    ]


def _render_q4(rows: Rows) -> List[str]:
    return [f"Average GPA of American Fall 2026 applicants: {fmt_average(_first_value(rows))}"]


def _render_q5(rows: Rows) -> List[str]:
    return [f"Fall 2025 acceptance percentage: {fmt_percent(_first_value(rows))}"]


def _render_q6(rows: Rows) -> List[str]:
    return [f"Average GPA of accepted Fall 2026 applicants: {fmt_average(_first_value(rows))}"]


def _render_q7(rows: Rows) -> List[str]:
    return [f"Johns Hopkins University Computer Science master's entries: {fmt_count(_first_value(rows))}"]


def _render_q8(rows: Rows) -> List[str]:
    return [
        "Fall 2026 accepted PhD Computer Science entries (original fields): "
        f"{fmt_count(_first_value(rows))}"
    ]


def _render_q9(rows: Rows) -> List[str]:
    original_count, llm_count = rows[0]
    return [
        f"Original-field count: {fmt_count(original_count)}",
        f"LLM-field count: {fmt_count(llm_count)}",
        f"Difference: {fmt_signed_difference(llm_count - original_count)}",
    ]


def _render_o1(rows: Rows) -> List[str]:
    if not rows:
        return [NO_ROWS_MESSAGE]
    return [
        f"{group}: {fmt_percent(percent)} accepted (n = {fmt_count(entries)})"
        for group, entries, percent in rows
    ]


def _render_o2(rows: Rows) -> List[str]:
    if not rows:
        return [NO_ROWS_MESSAGE]
    return [
        f"{outcome} (n = {fmt_count(entries)}): average GPA {fmt_average(gpa)}, "
        f"average GRE Quantitative {fmt_average(gre_q)}"
        for outcome, entries, gpa, gre_q in rows
    ]


QUERIES: Tuple[Query, ...] = (
    Query(
        "1", "Fall 2026 applicants",
        "How many entries in the database are from applicants who applied for Fall 2026?",
        Q1_SQL,
        "Counts the rows whose term is Fall 2026. The term is trimmed and lower-cased first "
        "so 'Fall 2026', 'fall 2026' and ' Fall 2026 ' all match.",
        _render_q1,
    ),
    Query(
        "2", "Percent international",
        "Among entries that provide a nationality classification, what percentage are "
        "international students?",
        Q2_SQL,
        "The numerator counts International entries. The denominator counts every entry with a "
        "non-blank classification (American, International or Other), so blank values are left "
        "out and American and Other count as not international. NULLIF guards against dividing "
        "by zero.",
        _render_q2,
    ),
    Query(
        "3", "Average GPA and GRE scores",
        "What are the average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical Writing "
        "scores of applicants who provide each metric?",
        Q3_SQL,
        "AVG ignores NULLs, so each of the four averages is computed only over applicants who "
        "supplied that particular metric. An applicant with a GPA but no GRE still counts toward "
        "the GPA average.",
        _render_q3,
    ),
    Query(
        "4", "Average GPA of American Fall 2026 applicants",
        "What is the average GPA of American applicants who applied for Fall 2026?",
        Q4_SQL,
        "Filters to Fall 2026 entries classified as American that actually report a GPA, then "
        "averages the GPA.",
        _render_q4,
    ),
    Query(
        "5", "Fall 2025 acceptance percentage",
        "What percentage of Fall 2025 entries are acceptances?",
        Q5_SQL,
        "Among all Fall 2025 entries, COUNT(*) FILTER counts those whose status starts with "
        "'accept' (case-insensitive) and divides by the total number of Fall 2025 entries.",
        _render_q5,
    ),
    Query(
        "6", "Average GPA of accepted Fall 2026 applicants",
        "What is the average GPA of accepted applicants who applied for Fall 2026?",
        Q6_SQL,
        "Filters to Fall 2026 entries with an acceptance status that report a GPA, then "
        "averages the GPA.",
        _render_q6,
    ),
    Query(
        "7", "Johns Hopkins Computer Science master's entries",
        "How many entries are from applicants who applied to Johns Hopkins University for a "
        "master's degree in Computer Science?",
        Q7_SQL,
        "Uses the original downloaded program and degree fields. The program text must mention "
        "Johns Hopkins (including the 'John Hopkins' misspelling) or the standalone word JHU, "
        "and contain 'computer science', and the degree must start with 'master'.",
        _render_q7,
    ),
    Query(
        "8", "Fall 2026 CS PhD acceptances at four universities (original fields)",
        "How many Fall 2026 entries are acceptances from applicants applying for a PhD in "
        "Computer Science at Georgetown, MIT, Stanford or Carnegie Mellon?",
        Q8_SQL,
        "Applies all five restrictions at once (term, acceptance, PhD, Computer Science, one of "
        "the four universities) using the original downloaded program text. MIT is matched both "
        "by its full name and by the standalone word 'MIT'.",
        _render_q8,
    ),
    Query(
        "9", "Same question using the LLM-generated fields",
        "Repeating Question 8 but identifying the program and university with "
        "llm_generated_program and llm_generated_university, how do the counts compare?",
        Q9_SQL,
        "Term, degree and status still come from the original fields; only the program and "
        "university tests switch to the LLM-generated columns. One query returns both counts "
        "(the original-field count equals Question 8) and the difference is LLM minus original.",
        _render_q9,
    ),
    Query(
        "O1", "Fall 2026 acceptance rate by nationality group",
        "For Fall 2026, how does the acceptance rate differ between American, International "
        "and Other applicants?",
        O1_SQL,
        "Groups Fall 2026 entries by nationality classification (blank shown as Unknown) and "
        "reports how many entries each group has and what percentage of them were acceptances.",
        _render_o1,
    ),
    Query(
        "O2", "Accepted versus rejected applicants' GPA and GRE",
        "Among Fall 2026 applicants who were accepted or rejected, how do average GPA and GRE "
        "Quantitative scores compare, and how many applicants report them?",
        O2_SQL,
        "Groups Fall 2026 accepted and rejected entries and averages GPA and GRE Quantitative "
        "within each group, ignoring missing values. It shows how self-reported scores differ "
        "by outcome.",
        _render_o2,
    ),
)


def get_query(number: str) -> Query:
    """Look up a query by its number ("1".."9", "O1", "O2")."""
    for query in QUERIES:
        if query.number == number:
            return query
    raise KeyError(number)


def run_query(conn: psycopg.Connection, query: Query) -> List[str]:
    """Execute one query and return its formatted result lines."""
    with conn.cursor() as cur:
        cur.execute(query.sql)
        return query.render(cur.fetchall())


def run_all(conn: psycopg.Connection) -> List[Tuple[Query, List[str]]]:
    """Run every query in order, pairing each with its formatted result lines."""
    return [(query, run_query(conn, query)) for query in QUERIES]


def main() -> int:
    try:
        with connect() as conn:
            results = run_all(conn)
    except psycopg.OperationalError as exc:
        print(
            "Could not connect to PostgreSQL. Check that the server is running and that "
            "PGHOST, PGPORT, PGDATABASE, PGUSER and PGPASSWORD are set.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1

    for query, lines in results:
        if query.number.startswith("O"):
            label = f"Original question {query.number[1:]}"
        else:
            label = f"Question {query.number}"
        print(f"{label}: {query.question}")
        for line in lines:
            print(f"  {line}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
