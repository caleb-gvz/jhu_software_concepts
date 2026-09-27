"""Answer the Module 3 analysis questions with raw SQL (psycopg 3).

Each question is a ``Query``: the shared question text and result formatting from
``questions.py`` plus the exact SQL and a short explanation of it. Keeping them as
data lets the console output (``python query_data.py``), ``query_results.pdf`` and the
tests all use one source of truth, so the SQL shown in the PDF is exactly the SQL that
ran.

Matching rules used throughout (all case-insensitive):

* term:   ``LOWER(TRIM(term)) = 'fall 2026'``
* accept: ``status ILIKE 'accept%'``
* averages skip NULLs automatically, so each average uses only the applicants who
  supplied that metric.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from db_config import connect
from load_data import COLUMNS
from questions import QUESTIONS, Rows, display_label

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

SQL_BY_NUMBER: Dict[str, str] = {
    "1": Q1_SQL, "2": Q2_SQL, "3": Q3_SQL, "4": Q4_SQL, "5": Q5_SQL, "6": Q6_SQL,
    "7": Q7_SQL, "8": Q8_SQL, "9": Q9_SQL, "O1": O1_SQL, "O2": O2_SQL,
}

EXPLANATION_BY_NUMBER: Dict[str, str] = {
    "1": "Counts the rows whose term is Fall 2026. The term is trimmed and lower-cased first "
         "so 'Fall 2026', 'fall 2026' and ' Fall 2026 ' all match.",
    "2": "The numerator counts International entries. The denominator counts every entry with a "
         "non-blank classification (American, International or Other), so blank values are left "
         "out and American and Other count as not international. NULLIF guards against dividing "
         "by zero.",
    "3": "AVG ignores NULLs, so each of the four averages is computed only over applicants who "
         "supplied that particular metric. An applicant with a GPA but no GRE still counts toward "
         "the GPA average.",
    "4": "Filters to Fall 2026 entries classified as American that actually report a GPA, then "
         "averages the GPA.",
    "5": "Among all Fall 2025 entries, COUNT(*) FILTER counts those whose status starts with "
         "'accept' (case-insensitive) and divides by the total number of Fall 2025 entries.",
    "6": "Filters to Fall 2026 entries with an acceptance status that report a GPA, then "
         "averages the GPA.",
    "7": "Uses the original downloaded program and degree fields. The program text must mention "
         "Johns Hopkins (including the 'John Hopkins' misspelling) or the standalone word JHU, "
         "and contain 'computer science', and the degree must start with 'master'.",
    "8": "Applies all five restrictions at once (term, acceptance, PhD, Computer Science, one of "
         "the four universities) using the original downloaded program text. MIT is matched both "
         "by its full name and by the standalone word 'MIT'.",
    "9": "Term, degree and status still come from the original fields; only the program and "
         "university tests switch to the LLM-generated columns. One query returns both counts "
         "(the original-field count equals Question 8) and the difference is LLM minus original.",
    "O1": "Groups Fall 2026 entries by nationality classification (blank shown as Unknown) and "
          "reports how many entries each group has and what percentage of them were acceptances.",
    "O2": "Groups Fall 2026 accepted and rejected entries and averages GPA and GRE Quantitative "
          "within each group, ignoring missing values. It shows how self-reported scores differ "
          "by outcome.",
}


@dataclass(frozen=True)
class Query:
    number: str
    title: str
    question: str
    sql: str
    explanation: str
    render: Callable[[Rows], List[str]]


QUERIES: Tuple[Query, ...] = tuple(
    Query(
        number=q.number,
        title=q.title,
        question=q.question,
        sql=SQL_BY_NUMBER[q.number],
        explanation=EXPLANATION_BY_NUMBER[q.number],
        render=q.render,
    )
    for q in QUESTIONS
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


FETCH_APPLICANTS_SQL = sql.SQL("SELECT {columns} FROM applicants ORDER BY p_id").format(
    columns=sql.SQL(", ").join(sql.Identifier(column) for column in COLUMNS)
)


def fetch_applicants(
    conn: psycopg.Connection, limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Return stored applicants as dicts keyed by the Module 3 column names.

    Every dict has exactly the keys in ``load_data.COLUMNS`` (``p_id``, ``program``,
    ... ``llm_generated_university``), ordered by ``p_id``. ``limit`` caps how many
    rows are returned.
    """
    statement = FETCH_APPLICANTS_SQL
    params: Tuple[Any, ...] = ()
    if limit is not None:
        statement = sql.SQL("{} LIMIT %s").format(FETCH_APPLICANTS_SQL)
        params = (limit,)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(statement, params)
        return cur.fetchall()


def main() -> int:
    try:
        with connect() as conn:
            results = run_all(conn)
    except psycopg.OperationalError as exc:
        print(
            "Could not connect to PostgreSQL. Check that the server is running and that "
            "DATABASE_URL (or PGHOST, PGPORT, PGDATABASE, PGUSER and PGPASSWORD) is set.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1

    for query, lines in results:
        print(f"{display_label(query.number)}: {query.question}")
        for line in lines:
            print(f"  {line}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
