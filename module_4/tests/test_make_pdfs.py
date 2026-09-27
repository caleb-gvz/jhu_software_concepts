import pytest
from pypdf import PdfReader

from make_pdfs import build_limitations_pdf, build_query_results_pdf, limitations_paragraphs
from query_data import QUERIES

STATS = {
    "total_entries": 40000,
    "gre_q_reporters": 1176,
    "gre_q_average": 165.68,
    "gpa_reporters": 23929,
    "gpa_average": 3.76,
    "fall_2025_acceptance_percent": 39.03,
    "accepted_average_gpa": 3.76,
    "rejected_average_gpa": 3.78,
    "accepted_average_gre_q": 165.61,
    "rejected_average_gre_q": 165.59,
    "unknown_nationality_entries": 847,
    "llm_standardized_entries": 5000,
}


def _pdf_text(path):
    return "\n".join(page.extract_text() for page in PdfReader(str(path)).pages)


def test_limitations_has_exactly_two_substantive_paragraphs():
    paragraphs = limitations_paragraphs(STATS)
    assert len(paragraphs) == 2
    assert all(len(p.split()) >= 150 for p in paragraphs)


def test_limitations_connects_to_the_databases_own_results_and_covers_required_topics():
    text = " ".join(limitations_paragraphs(STATS)).lower()
    assert "165.68" in text and "1,176" in text                       # Q3 GRE Quantitative result
    assert "39.03%" in text                                            # Q5 acceptance percentage
    for topic in ("selection bias", "self-report", "missing", "representative"):
        assert topic in text
    assert "157" in text                                               # the assignment's reference-population example


def test_limitations_pdf_is_written_and_readable(tmp_path):
    path = tmp_path / "limitations.pdf"
    build_limitations_pdf(STATS, path)
    text = _pdf_text(path)
    assert "Limitations" in text and "165.68" in text
    assert "Caleb Gevertz" in text


def test_query_results_pdf_includes_all_eleven_questions_with_sql_and_explanations(tmp_path):
    results = [(query, [f"result line for {query.number}"]) for query in QUERIES]
    path = tmp_path / "query_results.pdf"

    build_query_results_pdf(results, path, total_entries=40000, generated_on="2026-09-20")

    text = _pdf_text(path)
    assert len(QUERIES) == 11
    for query in QUERIES:
        assert f"result line for {query.number}" in text
        assert query.explanation.split(".")[0][:40] in text.replace("\n", " ")
    assert "SELECT COUNT(*)" in text
    assert "Caleb Gevertz" in text and "cgevert1" in text
    assert "Original question 1" in text and "Question 9" in text


# ---- Question 9 written explanation and LLM-coverage note --------------------------------

from make_pdfs import llm_coverage_note, q9_discussion  # noqa: E402


def test_q9_discussion_explains_a_zero_difference_using_the_actual_counts():
    text = q9_discussion(original_count=30, llm_count=30)
    assert "30" in text and "identical" in text.lower()
    assert "separate" in text.lower()           # the source already gives program and university separately
    assert "does not mean" in text.lower()      # zero difference is not proof the LLM is useless


def test_q9_discussion_explains_a_nonzero_difference_in_both_directions():
    higher = q9_discussion(original_count=14, llm_count=17)
    assert "+3" in higher and "17" in higher and "14" in higher
    lower = q9_discussion(original_count=17, llm_count=14)
    assert "-3" in lower


def test_llm_coverage_note_reports_the_real_numbers():
    stats = dict(STATS, llm_standardized_entries=10442, q9_candidates_missing_llm=0)
    note = llm_coverage_note(stats)
    assert "10,442" in note and "40,000" in note
    assert "every" in note.lower() or "all" in note.lower()

    partial = llm_coverage_note(dict(stats, q9_candidates_missing_llm=12))
    assert "12" in partial
