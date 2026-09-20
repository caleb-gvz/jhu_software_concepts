import datetime

from load_data import COLUMNS, merge_llm_fields, record_to_row

BASE = {
    "id": 5,
    "url": "https://www.thegradcafe.com/result/5",
    "program": "Computer Science, MIT",
    "degree": "PhD",
    "applicant_status": "Accepted",
    "term": "Fall 2026",
    "us_or_international": "American",
    "gpa": 3.9,
    "gre_score": 168.0,
    "gre_v": 160.0,
    "gre_aw": 4.5,
    "comments": "Happy!",
    "date_added_raw": "2026-09-12",
}


def test_row_has_exactly_the_assignment_columns():
    assert set(record_to_row(BASE)) == set(COLUMNS)
    assert COLUMNS == (
        "p_id", "program", "comments", "date_added", "url", "status", "term",
        "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
        "llm_generated_program", "llm_generated_university",
    )


def test_maps_renamed_fields_and_parses_date():
    row = record_to_row(BASE)
    assert row["p_id"] == 5
    assert row["status"] == "Accepted"
    assert row["gre"] == 168.0
    assert row["date_added"] == datetime.date(2026, 9, 12)


def test_blank_text_becomes_none():
    row = record_to_row({**BASE, "comments": "   ", "us_or_international": ""})
    assert row["comments"] is None
    assert row["us_or_international"] is None


def test_out_of_range_scores_become_none_but_valid_ones_survive():
    row = record_to_row({**BASE, "gpa": 40.0, "gre_score": 900.0, "gre_aw": 9.0})
    assert row["gpa"] is None
    assert row["gre"] is None
    assert row["gre_aw"] is None
    assert row["gre_v"] == 160.0


def test_boundary_scores_are_kept():
    row = record_to_row({**BASE, "gpa": 4.33, "gre_score": 130, "gre_v": 170, "gre_aw": 0})
    assert (row["gpa"], row["gre"], row["gre_v"], row["gre_aw"]) == (4.33, 130.0, 170.0, 0.0)


def test_zero_gpa_is_treated_as_missing():
    assert record_to_row({**BASE, "gpa": 0})["gpa"] is None


def test_missing_optional_values_do_not_fail():
    row = record_to_row({"id": 6})
    assert row["p_id"] == 6
    assert row["gpa"] is None and row["gre"] is None and row["comments"] is None
    assert row["date_added"] is None


def test_bad_date_becomes_none_instead_of_crashing():
    assert record_to_row({**BASE, "date_added_raw": "not a date"})["date_added"] is None


def test_llm_fields_come_from_hyphenated_keys():
    row = record_to_row(
        {**BASE, "llm-generated-program": "Computer Science",
         "llm-generated-university": "Massachusetts Institute of Technology"}
    )
    assert row["llm_generated_program"] == "Computer Science"
    assert row["llm_generated_university"] == "Massachusetts Institute of Technology"


def test_merge_llm_fields_overlays_by_id_without_mutating_input():
    base = [{"id": 1, "program": "A"}, {"id": 2, "program": "B"}]
    llm = [{"id": 2, "llm-generated-program": "B2", "llm-generated-university": "U2"}]

    merged = merge_llm_fields(base, llm)

    assert merged[0] == {"id": 1, "program": "A"}
    assert merged[1]["llm-generated-program"] == "B2"
    assert merged[1]["llm-generated-university"] == "U2"
    assert "llm-generated-program" not in base[1]


# ---------------------------------------------------------------------------
# Database-backed tests (skipped automatically when PostgreSQL is unreachable)
# ---------------------------------------------------------------------------
from load_data import create_table, load_records  # noqa: E402


def _count(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM applicants")
        return cur.fetchone()[0]


def test_table_has_the_required_columns_and_primary_key(test_conn):
    with test_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'applicants' ORDER BY ordinal_position"
        )
        columns = cur.fetchall()
        cur.execute(
            "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
            "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'applicants'::regclass AND i.indisprimary"
        )
        primary_key = [row[0] for row in cur.fetchall()]

    assert [name for name, _ in columns] == list(COLUMNS)
    types = dict(columns)
    assert types["p_id"] == "integer"
    assert types["date_added"] == "date"
    assert types["gpa"] == "double precision"
    assert types["program"] == "text"
    assert primary_key == ["p_id"]


def test_create_table_twice_is_harmless(test_conn):
    create_table(test_conn)
    create_table(test_conn)


def test_loading_twice_does_not_duplicate_rows(test_conn):
    records = [dict(BASE, id=1), dict(BASE, id=2)]

    assert load_records(test_conn, records) == 2
    assert load_records(test_conn, records) == 0
    assert _count(test_conn) == 2


def test_reload_fills_empty_llm_columns_but_never_changes_original_fields(test_conn):
    load_records(test_conn, [dict(BASE, id=1)])

    changed = dict(
        BASE, id=1, applicant_status="Rejected",
        **{"llm-generated-program": "Computer Science",
           "llm-generated-university": "Massachusetts Institute of Technology"},
    )
    assert load_records(test_conn, [changed]) == 0

    with test_conn.cursor() as cur:
        cur.execute("SELECT status, llm_generated_program, llm_generated_university FROM applicants")
        assert cur.fetchone() == (
            "Accepted", "Computer Science", "Massachusetts Institute of Technology"
        )


def test_existing_llm_values_are_not_overwritten_by_later_loads(test_conn):
    first = dict(BASE, id=1, **{"llm-generated-program": "First",
                                "llm-generated-university": "First U"})
    second = dict(BASE, id=1, **{"llm-generated-program": "Second"})
    load_records(test_conn, [first])
    load_records(test_conn, [second])

    with test_conn.cursor() as cur:
        cur.execute("SELECT llm_generated_program FROM applicants")
        assert cur.fetchone()[0] == "First"


def test_rows_with_missing_optional_values_load_as_nulls(test_conn):
    load_records(test_conn, [{"id": 9, "url": "u"}])
    with test_conn.cursor() as cur:
        cur.execute("SELECT gpa, gre, comments, date_added FROM applicants WHERE p_id = 9")
        assert cur.fetchone() == (None, None, None, None)
