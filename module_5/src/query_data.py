"""Answer the analysis questions and look up applicants with composed, parameterized SQL.

Every statement here is built from ``psycopg.sql`` objects and executed separately, with
its values supplied as bound parameters::

    statement = limited(query.statement)                 # construction (a composed object)
    cursor.execute(statement, limit_params(limit, query.params))   # execution + parameters

* Table and column names that vary are quoted with ``sql.Identifier``.
* Every value -- terms, status patterns, the LIKE/regex patterns, the row limit -- is a
  named placeholder (``%(name)s``) filled from a parameter dict. No value is ever spliced
  into the SQL text, and nothing here uses f-strings, ``+`` or ``.format()`` on raw SQL.
* Every ``SELECT`` goes through ``sql_safety.limited``, so it ends in ``LIMIT %(limit)s``,
  and the bound limit is clamped to 1..100 by ``sql_safety.clamp_limit``.

Each analysis question is a ``Query``: the shared question text and result formatting
from ``questions.py`` plus its composed statement, its parameters and a short
explanation. Keeping them as data lets the console output (``python query_data.py``) and
the tests use one source of truth.

Matching rules used throughout (all case-insensitive):

* term:   ``LOWER(TRIM(term)) = %(term)s``  with ``term = 'fall 2026'``
* accept: ``status ILIKE %(accepted)s``     with ``accepted = 'accept%'``
* averages skip NULLs automatically, so each average uses only the applicants who
  supplied that metric.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from db_config import connect, report_connection_error
from load_data import APPLICANTS_TABLE, COLUMNS
from questions import QUESTIONS, Rows, display_label, print_answer
from sql_safety import limit_params, limited

# ---- values bound into the statements -------------------------------------------------

TERM_FALL_2026 = "fall 2026"
TERM_FALL_2025 = "fall 2025"
ACCEPTED_PATTERN = "accept%"
REJECTED_PATTERN = "reject%"
COMPUTER_SCIENCE_PATTERN = "%computer science%"

# The four target universities: (placeholder name, SQL operator, pattern). MIT is matched
# by its full name and by the standalone word (a regex, so "admit" does not match).
UNIVERSITY_TESTS: Tuple[Tuple[str, str, str], ...] = (
    ("georgetown", "ILIKE", "%georgetown%"),
    ("mit_name", "ILIKE", "%massachusetts institute of technology%"),
    ("mit_word", "~*", r"\ymit\y"),
    ("stanford", "ILIKE", "%stanford%"),
    ("carnegie_mellon", "ILIKE", "%carnegie mellon%"),
)
UNIVERSITY_PARAMS: Dict[str, str] = {name: pattern for name, _, pattern in UNIVERSITY_TESTS}


def _compose(template: str, **parts: sql.Composable) -> sql.Composed:
    """Build a SELECT from a template whose ``{table}`` (and other slots) are composed.

    The template holds only fixed SQL and ``%(name)s`` placeholders; the table name is
    filled in as a quoted identifier, never as text.
    """
    return sql.SQL(template).format(table=APPLICANTS_TABLE, **parts)


def _mentions_one_of_the_four_universities(column: str) -> sql.Composed:
    """``(col ILIKE %(georgetown)s OR col ILIKE ... )`` for the named column."""
    tests = [
        sql.SQL("{column} {operator} {value}").format(
            column=sql.Identifier(column),
            operator=sql.SQL(operator),
            value=sql.Placeholder(name),
        )
        for name, operator, _ in UNIVERSITY_TESTS
    ]
    return sql.SQL("({})").format(sql.SQL(" OR ").join(tests))


# ---- the eleven analysis questions: statement (no LIMIT yet) + bound values ---------------

Q1_STATEMENT = _compose(
    """SELECT COUNT(*)
FROM {table}
WHERE LOWER(TRIM(term)) = %(term)s"""
)
Q1_PARAMS = {"term": TERM_FALL_2026}

Q2_STATEMENT = _compose(
    """SELECT 100.0 * COUNT(*) FILTER (WHERE LOWER(us_or_international) = %(international)s)
       / NULLIF(COUNT(*) FILTER (WHERE NULLIF(TRIM(us_or_international), '') IS NOT NULL), 0)
FROM {table}"""
)
Q2_PARAMS = {"international": "international"}

Q3_STATEMENT = _compose(
    """SELECT AVG(gpa), AVG(gre), AVG(gre_v), AVG(gre_aw)
FROM {table}"""
)
Q3_PARAMS: Dict[str, Any] = {}

Q4_STATEMENT = _compose(
    """SELECT AVG(gpa)
FROM {table}
WHERE LOWER(TRIM(term)) = %(term)s
  AND LOWER(TRIM(us_or_international)) = %(nationality)s
  AND gpa IS NOT NULL"""
)
Q4_PARAMS = {"term": TERM_FALL_2026, "nationality": "american"}

Q5_STATEMENT = _compose(
    """SELECT 100.0 * COUNT(*) FILTER (WHERE status ILIKE %(accepted)s) / NULLIF(COUNT(*), 0)
FROM {table}
WHERE LOWER(TRIM(term)) = %(term)s"""
)
Q5_PARAMS = {"term": TERM_FALL_2025, "accepted": ACCEPTED_PATTERN}

Q6_STATEMENT = _compose(
    """SELECT AVG(gpa)
FROM {table}
WHERE LOWER(TRIM(term)) = %(term)s
  AND status ILIKE %(accepted)s
  AND gpa IS NOT NULL"""
)
Q6_PARAMS = {"term": TERM_FALL_2026, "accepted": ACCEPTED_PATTERN}

Q7_STATEMENT = _compose(
    """SELECT COUNT(*)
FROM {table}
WHERE (program ILIKE %(johns_hopkins)s OR program ~* %(jhu_word)s)
  AND program ILIKE %(computer_science)s
  AND degree ILIKE %(masters)s"""
)
Q7_PARAMS = {
    "johns_hopkins": "%john% hopkins%",
    "jhu_word": r"\yjhu\y",
    "computer_science": COMPUTER_SCIENCE_PATTERN,
    "masters": "master%",
}

Q8_STATEMENT = _compose(
    """SELECT COUNT(*)
FROM {table}
WHERE LOWER(TRIM(term)) = %(term)s
  AND status ILIKE %(accepted)s
  AND degree ILIKE %(degree)s
  AND program ILIKE %(computer_science)s
  AND {at_one_of_the_four}""",
    at_one_of_the_four=_mentions_one_of_the_four_universities("program"),
)
Q8_PARAMS = {
    "term": TERM_FALL_2026,
    "accepted": ACCEPTED_PATTERN,
    "degree": "phd",
    "computer_science": COMPUTER_SCIENCE_PATTERN,
    **UNIVERSITY_PARAMS,
}

Q9_STATEMENT = _compose(
    """SELECT
    COUNT(*) FILTER (WHERE program ILIKE %(computer_science)s
        AND {original_university}) AS original_field_count,
    COUNT(*) FILTER (WHERE llm_generated_program ILIKE %(computer_science)s
        AND {llm_university}) AS llm_field_count
FROM {table}
WHERE LOWER(TRIM(term)) = %(term)s
  AND status ILIKE %(accepted)s
  AND degree ILIKE %(degree)s""",
    original_university=_mentions_one_of_the_four_universities("program"),
    llm_university=_mentions_one_of_the_four_universities("llm_generated_university"),
)
Q9_PARAMS = Q8_PARAMS

O1_STATEMENT = _compose(
    """SELECT COALESCE(NULLIF(TRIM(us_or_international), ''), 'Unknown') AS nationality_group,
       COUNT(*) AS entries,
       100.0 * COUNT(*) FILTER (WHERE status ILIKE %(accepted)s) / COUNT(*) AS acceptance_percent
FROM {table}
WHERE LOWER(TRIM(term)) = %(term)s
GROUP BY nationality_group
ORDER BY entries DESC, nationality_group"""
)
O1_PARAMS = {"term": TERM_FALL_2026, "accepted": ACCEPTED_PATTERN}

O2_STATEMENT = _compose(
    """SELECT CASE WHEN status ILIKE %(accepted)s THEN 'Accepted' ELSE 'Rejected' END AS outcome,
       COUNT(*) AS entries,
       AVG(gpa) AS average_gpa,
       AVG(gre) AS average_gre_quantitative
FROM {table}
WHERE LOWER(TRIM(term)) = %(term)s
  AND (status ILIKE %(accepted)s OR status ILIKE %(rejected)s)
GROUP BY outcome
ORDER BY outcome"""
)
O2_PARAMS = {
    "term": TERM_FALL_2026,
    "accepted": ACCEPTED_PATTERN,
    "rejected": REJECTED_PATTERN,
}

STATEMENT_BY_NUMBER: Dict[str, Tuple[sql.Composable, Mapping[str, Any]]] = {
    "1": (Q1_STATEMENT, Q1_PARAMS), "2": (Q2_STATEMENT, Q2_PARAMS),
    "3": (Q3_STATEMENT, Q3_PARAMS), "4": (Q4_STATEMENT, Q4_PARAMS),
    "5": (Q5_STATEMENT, Q5_PARAMS), "6": (Q6_STATEMENT, Q6_PARAMS),
    "7": (Q7_STATEMENT, Q7_PARAMS), "8": (Q8_STATEMENT, Q8_PARAMS),
    "9": (Q9_STATEMENT, Q9_PARAMS), "O1": (O1_STATEMENT, O1_PARAMS),
    "O2": (O2_STATEMENT, O2_PARAMS),
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
class Query:  # pylint: disable=too-many-instance-attributes
    """One question bound to its composed SQL, parameter values and an explanation."""

    number: str
    title: str
    question: str
    statement: sql.Composable
    params: Mapping[str, Any]
    explanation: str
    render: Callable[[Rows], List[str]]

    @property
    def sql(self) -> str:
        """The statement as it is sent, ``LIMIT %(limit)s`` included (for display and tests)."""
        return limited(self.statement).as_string()


QUERIES: Tuple[Query, ...] = tuple(
    Query(
        number=q.number,
        title=q.title,
        question=q.question,
        statement=STATEMENT_BY_NUMBER[q.number][0],
        params=STATEMENT_BY_NUMBER[q.number][1],
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


def run_query(conn: psycopg.Connection, query: Query, limit: Any = None) -> List[str]:
    """Execute one query with its LIMIT enforced and return its formatted result lines.

    ``limit`` is clamped to 1..100 (``ValueError`` if it is not a whole number); the
    statement is composed first and executed with the bound parameters second.
    """
    statement = limited(query.statement)
    params = limit_params(limit, query.params)
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return query.render(cur.fetchall())


def run_all(conn: psycopg.Connection, limit: Any = None) -> List[Tuple[Query, List[str]]]:
    """Run every query in order, pairing each with its formatted result lines."""
    return [(query, run_query(conn, query, limit)) for query in QUERIES]


# ---- applicant look-ups (the paths that take caller-supplied values) ---------------------

# Any stored column may be used to sort; the allow-list is the only source of sort names.
SORTABLE_COLUMNS: Tuple[str, ...] = COLUMNS
_KEY_COLUMN = "p_id"

# One pre-built, quoted identifier per allowed column. A caller's ``sort`` text is only ever
# used as a dictionary key here: what goes into the SQL is one of these constants, so the
# request text itself never becomes part of the statement.
SORT_IDENTIFIERS: Dict[str, sql.Identifier] = {
    name: sql.Identifier(name) for name in SORTABLE_COLUMNS
}

SELECT_APPLICANTS = sql.SQL("SELECT {columns} FROM {table}").format(
    columns=sql.SQL(", ").join(sql.Identifier(column) for column in COLUMNS),
    table=APPLICANTS_TABLE,
)


def fetch_applicants(conn: psycopg.Connection, limit: Any = None) -> List[Dict[str, Any]]:
    """Return stored applicants as dicts keyed by the Module 3 column names.

    Every dict has exactly the keys in ``load_data.COLUMNS`` (``p_id``, ``program``,
    ... ``llm_generated_university``), ordered by ``p_id``. At most ``limit`` rows come
    back; ``None`` means the default, and the value is always clamped to 1..100.
    """
    statement = limited(
        sql.SQL("{select} ORDER BY {key}").format(
            select=SELECT_APPLICANTS, key=sql.Identifier(_KEY_COLUMN)
        )
    )
    params = limit_params(limit)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(statement, params)
        return cur.fetchall()


def _equals_ignoring_case(column: str) -> sql.Composed:
    """``LOWER(TRIM(col)) = LOWER(TRIM(%(col)s))`` -- the bound value shares the column name."""
    return sql.SQL("LOWER(TRIM({column})) = LOWER(TRIM({value}))").format(
        column=sql.Identifier(column), value=sql.Placeholder(column)
    )


# ASC / DESC as constants chosen by a boolean, never assembled from caller text.
SORT_DIRECTIONS: Dict[bool, sql.SQL] = {False: sql.SQL("ASC"), True: sql.SQL("DESC")}

# The only filters the search accepts, built once from constants: a caller's value can
# select a condition and fill its bound parameter, but never alters the SQL text.
FILTER_CONDITIONS: Dict[str, sql.Composed] = {
    column: _equals_ignoring_case(column) for column in ("term", "status")
}


def _trusted_sort_identifier(sort: Any) -> sql.Identifier:
    """The pre-built identifier whose column name equals ``sort``; ``ValueError`` if none.

    The match is found by *comparing* ``sort`` with each allowed name and returning the
    trusted constant, so the caller's text is never copied into the result (a plain
    ``SORT_IDENTIFIERS[sort]`` lookup would also be safe, but static analyzers treat a
    lookup by tainted key as tainted). Anything that is not exactly an allowed name --
    including non-strings -- is rejected.
    """
    for name, identifier in SORT_IDENTIFIERS.items():
        if name == sort:
            return identifier
    raise ValueError(f"sort must be one of: {', '.join(SORTABLE_COLUMNS)}")


def _where_clause(
    term: Optional[str], status: Optional[str]
) -> Tuple[sql.Composable, Dict[str, Any]]:
    """``WHERE`` for the given filters plus their bound values; blank or ``None`` is skipped."""
    requested = {"term": term, "status": status}
    conditions: List[sql.Composable] = []
    params: Dict[str, Any] = {}
    for column, condition in FILTER_CONDITIONS.items():   # column names are constants
        if requested[column]:
            conditions.append(condition)
            params[column] = str(requested[column])          # request text only ever binds
    if not conditions:
        return sql.SQL(""), params
    return sql.SQL(" WHERE {}").format(sql.SQL(" AND ").join(conditions)), params


def search_applicants(  # pylint: disable=too-many-arguments
    conn: psycopg.Connection,
    *,
    term: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = _KEY_COLUMN,
    descending: bool = False,
    limit: Any = None,
) -> List[Dict[str, Any]]:
    """Applicants filtered by ``term`` and/or ``status`` (exact, case-insensitive).

    * ``term`` / ``status`` are bound parameters; blank or ``None`` means no filter. They
      are compared with ``=`` rather than ``LIKE``, so ``%`` and ``_`` are ordinary
      characters and a value can never widen the match.
    * ``sort`` must be one of ``SORTABLE_COLUMNS``; it selects a pre-built
      ``sql.Identifier`` from ``SORT_IDENTIFIERS`` (its text is never placed in the SQL).
      Anything else raises ``ValueError``.
    * Direction comes from the ``descending`` flag, never from caller text. NULLs sort last.
    * At most ``limit`` rows come back, clamped to 1..100 (``ValueError`` if not a number).
    """
    sort_identifier = _trusted_sort_identifier(sort)

    where, params = _where_clause(term, status)
    statement = limited(
        sql.SQL("{select}{where} ORDER BY {sort} {direction} NULLS LAST, {key}").format(
            select=SELECT_APPLICANTS,
            where=where,
            sort=sort_identifier,
            direction=SORT_DIRECTIONS[bool(descending)],
            key=sql.Identifier(_KEY_COLUMN),
        )
    )
    bound = limit_params(limit, params)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(statement, bound)
        return cur.fetchall()


def main() -> int:
    """Run every query against the configured database and print the answers."""
    try:
        with connect() as conn:
            results = run_all(conn)
    except psycopg.OperationalError as exc:
        report_connection_error(exc)
        return 1

    for query, lines in results:
        print_answer(display_label(query.number), query.question, lines)
    return 0


if __name__ == "__main__":  # pragma: no cover  (only calls main(), which is tested)
    sys.exit(main())
