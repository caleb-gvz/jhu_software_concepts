"""Build the two PDF deliverables from the live database.

    python make_pdfs.py

* ``query_results.pdf``  - for each of the 11 questions: the question, the final
  result, the exact SQL that produced it, and a short explanation. The results come
  from running ``query_data.py``'s queries, so the PDF always matches the console.
* ``limitations.pdf``    - a two-paragraph reflection on the limits of analysing
  anonymous, self-reported data. Every figure quoted in it is read from the
  database when the PDF is built, so the essay can never disagree with the results.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

import psycopg
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
)
from sqlalchemy import func, select

import orm_queries
from db_config import connect
from formatting import fmt_average, fmt_count, fmt_percent
from models import Applicant, SessionLocal
from query_data import Query, run_all
from questions import display_label

AUTHOR_LINE = "Caleb Gevertz (JHED: cgevert1) - Modern Software Concepts in Python, Module 3"
MODULE_DIR = Path(__file__).resolve().parent

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle("Title", parent=_styles["Title"], fontSize=20, spaceAfter=4)
BYLINE = ParagraphStyle("Byline", parent=_styles["Normal"], textColor=colors.HexColor("#555555"), spaceAfter=10)
HEADING = ParagraphStyle("Heading", parent=_styles["Heading2"], spaceBefore=14, spaceAfter=4, textColor=colors.HexColor("#1f3a68"))
LABEL = ParagraphStyle("Label", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#555555"), spaceBefore=6)
BODY = ParagraphStyle("Body", parent=_styles["Normal"], fontSize=10, leading=14)
RESULT = ParagraphStyle("Result", parent=BODY, fontName="Helvetica-Bold", textColor=colors.HexColor("#0b5c3b"))
ESSAY = ParagraphStyle("Essay", parent=BODY, fontSize=11, leading=16, alignment=TA_JUSTIFY, spaceAfter=12)
CODE = ParagraphStyle("Code", parent=_styles["Code"], fontSize=7.6, leading=9.6, backColor=colors.HexColor("#f3f5f9"), borderPadding=5, leftIndent=4)


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text), style)


# ---------------------------------------------------------------------------------------
# query_results.pdf
# ---------------------------------------------------------------------------------------

def build_query_results_pdf(
    results: Sequence[Tuple[Query, List[str]]],
    path: Path,
    total_entries: int,
    generated_on: str,
    notes: Optional[Sequence[str]] = None,
) -> None:
    """Write one section per question: question, result, SQL, explanation."""
    story: List[Any] = [
        _para("SQL Query Results", TITLE),
        _para(AUTHOR_LINE, BYLINE),
        _para(
            f"Generated {generated_on} from the PostgreSQL 'applicants' table "
            f"({fmt_count(total_entries)} entries). Counts are whole numbers, percentages "
            "show two decimals, and averages show two decimals.",
            BODY,
        ),
    ]
    for note in notes or []:
        story += [Spacer(1, 4), _para(note, BODY)]

    for query, lines in results:
        section: List[Any] = [
            _para(f"{display_label(query.number)}: {query.title}", HEADING),
            _para("Question", LABEL),
            _para(query.question, BODY),
            _para("Result", LABEL),
            *[_para(line, RESULT) for line in lines],
            _para("SQL query", LABEL),
            Preformatted(query.sql, CODE),
            _para("What the query does and why it answers the question", LABEL),
            _para(query.explanation, BODY),
        ]
        story.append(KeepTogether(section))

    SimpleDocTemplate(
        str(path), pagesize=letter, title="SQL Query Results", author="Caleb Gevertz",
        leftMargin=0.8 * inch, rightMargin=0.8 * inch, topMargin=0.8 * inch, bottomMargin=0.8 * inch,
    ).build(story)


# ---------------------------------------------------------------------------------------
# limitations.pdf
# ---------------------------------------------------------------------------------------

def limitations_paragraphs(stats: Dict[str, Any]) -> List[str]:
    """The two-paragraph reflection, with every figure taken from `stats`."""
    total = fmt_count(stats["total_entries"])
    reporters = fmt_count(stats["gre_q_reporters"])
    reporter_share = fmt_percent(100 * stats["gre_q_reporters"] / stats["total_entries"])
    gre_average = fmt_average(stats["gre_q_average"])

    first = (
        f"Every number in this analysis describes the {total} Grad Café entries in my database, "
        "not graduate applicants in general, and the gap between those two things is where the "
        "limitations lie. Grad Café is anonymous and voluntary, so it suffers from selection bias: "
        "only people who know the site exists, are comfortable posting, and choose to report a "
        "result appear in it, and the people who are absent (applicants who never visit the site, "
        "who come from fields or countries where posting results is uncommon, or who simply prefer "
        "privacy) are not a random slice of the population. The clearest example in my own results "
        f"is Question 3: the average GRE Quantitative score is {gre_average}, but only {reporters} of "
        f"the {total} entries ({reporter_share}) report one. A commonly cited average for all GRE "
        "test takers is roughly 157, so it would be a mistake to conclude that applicants in general "
        f"average {gre_average}. People with strong scores are more likely to volunteer them, many "
        "programs no longer require the GRE so weaker scorers have little reason to post theirs, and "
        "the site's audience may skew toward highly competitive applicants. The missing values are "
        "therefore not missing at random, and averaging only the people who report a metric (as the "
        "assignment requires) describes the reporters, not the applicant pool. Self-reported values "
        "are also unverified and messy: in the raw data the great majority of GRE writing scores were "
        "a 0.0 placeholder for \"not provided\", some GPAs were below 1.0, and "
        f"{fmt_count(stats['unknown_nationality_entries'])} entries had a meaningless nationality "
        "value, all of which I had to convert to missing values before any average was meaningful."
    )

    second = (
        "Outcome reporting adds a second layer of bias. People with especially good news (an "
        "acceptance from a top program) or especially bad or surprising news (a rejection they "
        "consider unfair, a strange timeline) are more motivated to post than people with an "
        "unremarkable result, so the dataset over-represents memorable outcomes. My Fall 2025 "
        f"acceptance percentage in Question 5 is {fmt_percent(stats['fall_2025_acceptance_percent'])}; "
        "that is the share of Grad Café entries that were acceptances, not the acceptance rate of the "
        "programs involved, which are often published as much lower for selective programs. Another "
        "result that needs care is my second original question: among Fall 2026 applicants the "
        f"accepted group has an average GPA of {fmt_average(stats['accepted_average_gpa'])} and GRE "
        f"Quantitative score of {fmt_average(stats['accepted_average_gre_q'])}, compared with "
        f"{fmt_average(stats['rejected_average_gpa'])} and {fmt_average(stats['rejected_average_gre_q'])} "
        "for the rejected group. The groups look almost identical, but that does not show that grades "
        "and test scores are irrelevant to admission: everyone who reports scores here is already "
        "clustered in a narrow, high range, decisions depend on things the database never captures "
        "(letters, research, fit, funding), and reporting habits may differ by outcome. The pipeline "
        f"adds error as well: LLM standardization exists for {fmt_count(stats['llm_standardized_entries'])} "
        "entries and makes occasional mistakes, so the Question 8 and Question 9 counts should be "
        "treated as approximate. What my database mathematically contains is a set of self-selected, "
        "partly missing, unverified reports; the defensible conclusions are descriptive (\"among "
        "people who chose to post, ...\") rather than statements that are representative of all "
        "graduate applicants."
    )
    return [first, second]


def build_limitations_pdf(stats: Dict[str, Any], path: Path) -> None:
    story: List[Any] = [
        _para("Limitations of Analyzing Anonymous, Self-Reported Data", TITLE),
        _para(AUTHOR_LINE, BYLINE),
        Spacer(1, 6),
    ]
    story += [_para(paragraph, ESSAY) for paragraph in limitations_paragraphs(stats)]
    SimpleDocTemplate(
        str(path), pagesize=letter, title="Limitations of Grad Cafe Data", author="Caleb Gevertz",
        leftMargin=1 * inch, rightMargin=1 * inch, topMargin=1 * inch, bottomMargin=1 * inch,
    ).build(story)


# ---------------------------------------------------------------------------------------
# gathering the figures (through the ORM) and the command-line entry point
# ---------------------------------------------------------------------------------------

def collect_stats(session) -> Dict[str, Any]:
    """Figures quoted in the essay, all read from the database."""
    count_rows = lambda *conditions: session.scalar(  # noqa: E731
        select(func.count()).select_from(Applicant).where(*conditions)
    )
    by_outcome = {row[0]: row for row in orm_queries.o2(session)}
    accepted, rejected = by_outcome["Accepted"], by_outcome["Rejected"]
    return {
        "total_entries": count_rows(),
        "gre_q_reporters": session.scalar(select(func.count(Applicant.gre))),
        "gre_q_average": session.scalar(select(func.avg(Applicant.gre))),
        "gpa_reporters": session.scalar(select(func.count(Applicant.gpa))),
        "gpa_average": session.scalar(select(func.avg(Applicant.gpa))),
        "fall_2025_acceptance_percent": float(orm_queries.q5(session)[0][0]),
        "accepted_average_gpa": accepted[2],
        "rejected_average_gpa": rejected[2],
        "accepted_average_gre_q": accepted[3],
        "rejected_average_gre_q": rejected[3],
        "unknown_nationality_entries": count_rows(Applicant.us_or_international.is_(None)),
        "llm_standardized_entries": session.scalar(select(func.count(Applicant.llm_generated_program))),
    }


def main() -> int:
    try:
        with connect() as conn:
            results = run_all(conn)
        with SessionLocal() as session:
            stats = collect_stats(session)
    except psycopg.OperationalError as exc:
        print(f"Could not connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1

    llm_note = (
        f"Note on Questions 8 and 9: llm_generated_program / llm_generated_university are filled "
        f"for {fmt_count(stats['llm_standardized_entries'])} of the {fmt_count(stats['total_entries'])} "
        "entries. Question 9 only examines Fall 2026 accepted PhD entries, and the local LLM was run "
        "on those entries first; other entries may have empty LLM columns, which cannot change Q8 or Q9."
    )
    build_query_results_pdf(
        results, MODULE_DIR / "query_results.pdf", stats["total_entries"],
        datetime.date.today().isoformat(), notes=[llm_note],
    )
    build_limitations_pdf(stats, MODULE_DIR / "limitations.pdf")
    print("Wrote query_results.pdf and limitations.pdf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
