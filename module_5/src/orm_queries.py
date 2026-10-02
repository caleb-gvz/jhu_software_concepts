"""Answer the analysis questions with SQLAlchemy 2.x instead of handwritten SQL.

Every function builds a statement from the ``Applicant`` model with ``select()``,
``func``, ``and_``/``or_`` and executes it through a ``Session``. Nothing here submits
raw SQL strings or uses a database cursor.

The assignment asks for Questions 1, 4, 5, 8, 9 and one original question here. The
Flask page must also read through the ORM and show every result, so all eleven are
implemented; the required ones are marked ``REQUIRED_BY_ASSIGNMENT``.

Each function returns rows shaped exactly like the raw-SQL version, and both are
worded and formatted by the same ``render`` functions in ``questions.py``, so the two
approaches produce identical output.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from typing import Any, Callable, Dict, List, Tuple

from sqlalchemy import Numeric, and_, case, func, literal, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from db_config import report_connection_error
from models import Applicant, make_session_factory
from questions import QUESTIONS, Question, Rows, display_label, get_question, print_answer

# Pylint cannot see through SQLAlchemy's dynamic ``func`` namespace, so it reports every
# ``func.count(...)`` call as "not callable". That is a known false positive.
# pylint: disable=not-callable

REQUIRED_BY_ASSIGNMENT = ("1", "4", "5", "8", "9", "O1")


# ---- reusable conditions -------------------------------------------------------------

def _term_is(term: str):
    """Case- and whitespace-insensitive match on the term column."""
    return func.lower(func.trim(Applicant.term)) == term


def _is_accepted():
    return Applicant.status.ilike("accept%")


def _percent_of_total(matching_count, total_count):
    """100 * matching / total, in exact NUMERIC arithmetic like the SQL version."""
    return literal(Decimal("100.0"), Numeric) * matching_count / total_count


def _mentions_one_of_the_four_universities(column):
    """Georgetown, MIT (full name or the standalone word), Stanford, Carnegie Mellon."""
    return or_(
        column.ilike("%georgetown%"),
        column.ilike("%massachusetts institute of technology%"),
        column.regexp_match(r"\ymit\y", flags="i"),
        column.ilike("%stanford%"),
        column.ilike("%carnegie mellon%"),
    )


def _fall_2026_accepted_phd():
    return and_(
        _term_is("fall 2026"),
        _is_accepted(),
        Applicant.degree.ilike("phd"),
    )


# ---- the questions -------------------------------------------------------------------

def q1(session: Session) -> Rows:
    """Q1: number of Fall 2026 entries."""
    return session.execute(
        select(func.count()).select_from(Applicant).where(_term_is("fall 2026"))
    ).all()


def q2(session: Session) -> Rows:
    """Q2: percent international among entries with a non-blank nationality."""
    international = func.count().filter(
        func.lower(Applicant.us_or_international) == "international"
    )
    classified = func.count().filter(
        func.nullif(func.trim(Applicant.us_or_international), "").is_not(None)
    )
    return session.execute(
        select(_percent_of_total(international, func.nullif(classified, 0)))
    ).all()


def q3(session: Session) -> Rows:
    """Q3: each average over only the applicants who supplied that metric (AVG skips NULL)."""
    return session.execute(
        select(
            func.avg(Applicant.gpa),
            func.avg(Applicant.gre),
            func.avg(Applicant.gre_v),
            func.avg(Applicant.gre_aw),
        )
    ).all()


def q4(session: Session) -> Rows:
    """Q4: average GPA of American Fall 2026 applicants who report a GPA."""
    return session.execute(
        select(func.avg(Applicant.gpa)).where(
            _term_is("fall 2026"),
            func.lower(func.trim(Applicant.us_or_international)) == "american",
            Applicant.gpa.is_not(None),
        )
    ).all()


def q5(session: Session) -> Rows:
    """Q5: percentage of Fall 2025 entries that are acceptances."""
    accepted = func.count().filter(_is_accepted())
    return session.execute(
        select(_percent_of_total(accepted, func.nullif(func.count(), 0))).where(
            _term_is("fall 2025")
        )
    ).all()


def q6(session: Session) -> Rows:
    """Q6: average GPA of accepted Fall 2026 applicants who report a GPA."""
    return session.execute(
        select(func.avg(Applicant.gpa)).where(
            _term_is("fall 2026"), _is_accepted(), Applicant.gpa.is_not(None)
        )
    ).all()


def q7(session: Session) -> Rows:
    """Q7: Johns Hopkins / JHU Computer Science master's entries (original fields)."""
    return session.execute(
        select(func.count()).select_from(Applicant).where(
            or_(
                Applicant.program.ilike("%john% hopkins%"),
                Applicant.program.regexp_match(r"\yjhu\y", flags="i"),
            ),
            Applicant.program.ilike("%computer science%"),
            Applicant.degree.ilike("master%"),
        )
    ).all()


def q8(session: Session) -> Rows:
    """Q8: Fall 2026 accepted PhD Computer Science entries at the four universities."""
    return session.execute(
        select(func.count()).select_from(Applicant).where(
            _fall_2026_accepted_phd(),
            Applicant.program.ilike("%computer science%"),
            _mentions_one_of_the_four_universities(Applicant.program),
        )
    ).all()


def q9(session: Session) -> Rows:
    """Q9: the Q8 count next to the same count using the LLM-generated fields."""
    original_field_count = func.count().filter(
        and_(
            Applicant.program.ilike("%computer science%"),
            _mentions_one_of_the_four_universities(Applicant.program),
        )
    )
    llm_field_count = func.count().filter(
        and_(
            Applicant.llm_generated_program.ilike("%computer science%"),
            _mentions_one_of_the_four_universities(Applicant.llm_generated_university),
        )
    )
    return session.execute(
        select(original_field_count, llm_field_count).where(_fall_2026_accepted_phd())
    ).all()


def o1(session: Session) -> Rows:
    """Original question 1: Fall 2026 acceptance rate by nationality group."""
    nationality_group = func.coalesce(
        func.nullif(func.trim(Applicant.us_or_international), ""), "Unknown"
    ).label("nationality_group")
    entries = func.count().label("entries")
    acceptance_percent = _percent_of_total(
        func.count().filter(_is_accepted()), func.count()
    ).label("acceptance_percent")
    return session.execute(
        select(nationality_group, entries, acceptance_percent)
        .where(_term_is("fall 2026"))
        .group_by(nationality_group)
        .order_by(entries.desc(), nationality_group)
    ).all()


def o2(session: Session) -> Rows:
    """Original question 2: Fall 2026 accepted vs rejected, entries / avg GPA / avg GRE Quant."""
    outcome = case((_is_accepted(), "Accepted"), else_="Rejected").label("outcome")
    return session.execute(
        select(
            outcome,
            func.count().label("entries"),
            func.avg(Applicant.gpa),
            func.avg(Applicant.gre),
        )
        .where(
            _term_is("fall 2026"),
            or_(_is_accepted(), Applicant.status.ilike("reject%")),
        )
        .group_by(outcome)
        .order_by(outcome)
    ).all()


ORM_QUERIES: Dict[str, Callable[[Session], Rows]] = {
    "1": q1, "2": q2, "3": q3, "4": q4, "5": q5, "6": q6, "7": q7, "8": q8, "9": q9,
    "O1": o1, "O2": o2,
}


def run_query(session: Session, number: str) -> List[str]:
    """Run one question through the ORM and return its formatted result lines."""
    return get_question(number).render(ORM_QUERIES[number](session))


def run_all(session: Session) -> List[Tuple[Question, List[str]]]:
    """Run every question in order, pairing each with its formatted result lines."""
    return [(question, run_query(session, question.number)) for question in QUESTIONS]


# Keys of the dictionary the analysis template renders (see ``get_analysis``).
ANALYSIS_KEYS = ("total_entries", "assigned", "original")
CARD_KEYS = ("number", "label", "title", "question", "answers")


def get_analysis(session: Session) -> Dict[str, Any]:
    """Everything the analysis page shows, as one dictionary.

    Keys (``ANALYSIS_KEYS``):

    * ``total_entries`` -- number of rows in ``applicants``.
    * ``assigned`` / ``original`` -- lists of question cards for Questions 1-9 and for
      my own questions. Each card has the ``CARD_KEYS``: ``number``, ``label``,
      ``title``, ``question`` and ``answers`` (the formatted result lines, which the
      page prefixes with "Answer:").
    """
    analysis: Dict[str, Any] = {
        "total_entries": session.scalar(select(func.count()).select_from(Applicant)),
        "assigned": [],
        "original": [],
    }
    for question, lines in run_all(session):
        group = "original" if question.number.startswith("O") else "assigned"
        analysis[group].append(
            {
                "number": question.number,
                "label": display_label(question.number),
                "title": question.title,
                "question": question.question,
                "answers": lines,
            }
        )
    return analysis


def main() -> int:
    """Run every ORM query against the configured database and print the answers."""
    try:
        with make_session_factory()() as session:
            results = run_all(session)
    except OperationalError as exc:
        report_connection_error(exc.orig)
        return 1

    for question, lines in results:
        marker = "  [required ORM question]" if question.number in REQUIRED_BY_ASSIGNMENT else ""
        print_answer(display_label(question.number), question.question, lines, marker)
    return 0


if __name__ == "__main__":  # pragma: no cover  (only calls main(), which is tested)
    sys.exit(main())
