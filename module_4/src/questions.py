"""The analysis questions and how their results are worded, independent of how they
are computed.

Both implementations -- raw SQL (``query_data.py``) and SQLAlchemy
(``orm_queries.py``) -- return result *rows* in the same shape and hand them to the
``render`` function here. That guarantees the two produce identical, identically
formatted answers, and it keeps the wording and formatting rules
(see ``formatting.py``) in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Sequence, Tuple

from formatting import (
    fmt_average,
    fmt_count,
    fmt_percent,
    fmt_signed_difference,
)

Rows = Sequence[Tuple[Any, ...]]
NO_ROWS_MESSAGE = "No matching entries."


@dataclass(frozen=True)
class Question:
    number: str          # "1".."9" for the assigned questions, "O1"/"O2" for my own
    title: str
    question: str
    render: Callable[[Rows], List[str]]


def _first_value(rows: Rows) -> Any:
    return rows[0][0] if rows else None


def render_q1(rows: Rows) -> List[str]:
    return [f"Fall 2026 applicant count: {fmt_count(_first_value(rows))}"]


def render_q2(rows: Rows) -> List[str]:
    return [f"Percent international: {fmt_percent(_first_value(rows))}"]


def render_q3(rows: Rows) -> List[str]:
    gpa, gre_q, gre_v, gre_aw = rows[0]
    return [
        f"Average GPA: {fmt_average(gpa)}",
        f"Average GRE Quantitative: {fmt_average(gre_q)}",
        f"Average GRE Verbal: {fmt_average(gre_v)}",
        f"Average GRE Analytical Writing: {fmt_average(gre_aw)}",
    ]


def render_q4(rows: Rows) -> List[str]:
    return [f"Average GPA of American Fall 2026 applicants: {fmt_average(_first_value(rows))}"]


def render_q5(rows: Rows) -> List[str]:
    return [f"Fall 2025 acceptance percentage: {fmt_percent(_first_value(rows))}"]


def render_q6(rows: Rows) -> List[str]:
    return [f"Average GPA of accepted Fall 2026 applicants: {fmt_average(_first_value(rows))}"]


def render_q7(rows: Rows) -> List[str]:
    return [f"Johns Hopkins University Computer Science master's entries: {fmt_count(_first_value(rows))}"]


def render_q8(rows: Rows) -> List[str]:
    return [
        "Fall 2026 accepted PhD Computer Science entries (original fields): "
        f"{fmt_count(_first_value(rows))}"
    ]


def render_q9(rows: Rows) -> List[str]:
    original_count, llm_count = rows[0]
    return [
        f"Original-field count: {fmt_count(original_count)}",
        f"LLM-field count: {fmt_count(llm_count)}",
        f"Difference: {fmt_signed_difference(llm_count - original_count)}",
    ]


def render_o1(rows: Rows) -> List[str]:
    if not rows:
        return [NO_ROWS_MESSAGE]
    return [
        f"{group}: {fmt_percent(percent)} accepted (n = {fmt_count(entries)})"
        for group, entries, percent in rows
    ]


def render_o2(rows: Rows) -> List[str]:
    if not rows:
        return [NO_ROWS_MESSAGE]
    return [
        f"{outcome} (n = {fmt_count(entries)}): average GPA {fmt_average(gpa)}, "
        f"average GRE Quantitative {fmt_average(gre_q)}"
        for outcome, entries, gpa, gre_q in rows
    ]


QUESTIONS: Tuple[Question, ...] = (
    Question(
        "1", "Fall 2026 applicants",
        "How many entries in the database are from applicants who applied for Fall 2026?",
        render_q1,
    ),
    Question(
        "2", "Percent international",
        "Among entries that provide a nationality classification, what percentage are "
        "international students?",
        render_q2,
    ),
    Question(
        "3", "Average GPA and GRE scores",
        "What are the average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical Writing "
        "scores of applicants who provide each metric?",
        render_q3,
    ),
    Question(
        "4", "Average GPA of American Fall 2026 applicants",
        "What is the average GPA of American applicants who applied for Fall 2026?",
        render_q4,
    ),
    Question(
        "5", "Fall 2025 acceptance percentage",
        "What percentage of Fall 2025 entries are acceptances?",
        render_q5,
    ),
    Question(
        "6", "Average GPA of accepted Fall 2026 applicants",
        "What is the average GPA of accepted applicants who applied for Fall 2026?",
        render_q6,
    ),
    Question(
        "7", "Johns Hopkins Computer Science master's entries",
        "How many entries are from applicants who applied to Johns Hopkins University for a "
        "master's degree in Computer Science?",
        render_q7,
    ),
    Question(
        "8", "Fall 2026 CS PhD acceptances at four universities (original fields)",
        "How many Fall 2026 entries are acceptances from applicants applying for a PhD in "
        "Computer Science at Georgetown, MIT, Stanford or Carnegie Mellon?",
        render_q8,
    ),
    Question(
        "9", "Same question using the LLM-generated fields",
        "Repeating Question 8 but identifying the program and university with "
        "llm_generated_program and llm_generated_university, how do the counts compare?",
        render_q9,
    ),
    Question(
        "O1", "Fall 2026 acceptance rate by nationality group",
        "For Fall 2026, how does the acceptance rate differ between American, International "
        "and Other applicants?",
        render_o1,
    ),
    Question(
        "O2", "Accepted versus rejected applicants' GPA and GRE",
        "Among Fall 2026 applicants who were accepted or rejected, how do average GPA and GRE "
        "Quantitative scores compare, and how many applicants report them?",
        render_o2,
    ),
)


def get_question(number: str) -> Question:
    """Look up a question by its number ("1".."9", "O1", "O2")."""
    for question in QUESTIONS:
        if question.number == number:
            return question
    raise KeyError(number)


def display_label(number: str) -> str:
    """'Question 3' for assigned questions, 'Original question 1' for my own."""
    if number.startswith("O"):
        return f"Original question {number[1:]}"
    return f"Question {number}"
