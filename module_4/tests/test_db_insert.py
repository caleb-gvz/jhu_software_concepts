"""Database writes: inserts on pull, schema, idempotency, and the query functions."""

import json

import pytest

import load_data
from load_data import COLUMNS, load_records, merge_llm_fields
from orm_queries import ANALYSIS_KEYS, CARD_KEYS, get_analysis
from query_data import fetch_applicants
from tests.doubles import FakeScraper, make_record
from tests.test_query_data import SEED

pytestmark = pytest.mark.db

# Fields the fake scraper always supplies, so they must be non-null after a pull.
REQUIRED_NON_NULL = (
    "p_id", "program", "date_added", "url", "status", "term", "us_or_international",
    "gpa", "gre", "gre_v", "gre_aw", "degree",
)


def _count_rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM applicants")
        return cur.fetchone()[0]


# ---- insert on pull --------------------------------------------------------------------

def test_pull_inserts_new_rows_with_the_required_schema_and_non_null_fields(make_app, test_conn):
    assert _count_rows(test_conn) == 0                          # before: target table empty
    scraper = FakeScraper([make_record(101), make_record(102, us_or_international="International")])

    response = make_app(scraper=scraper).test_client().post("/pull-data")

    assert response.status_code == 200
    rows = fetch_applicants(test_conn)
    assert [row["p_id"] for row in rows] == [101, 102]
    for row in rows:
        assert tuple(row) == COLUMNS                             # the Module 3 schema, in order
        for column in REQUIRED_NON_NULL:
            assert row[column] is not None, f"{column} is NULL for p_id {row['p_id']}"
    assert rows[0]["program"] == "Computer Science, Stanford University"
    assert rows[1]["us_or_international"] == "International"
    # Pulled rows have no LLM standardization (documented limitation).
    assert rows[0]["llm_generated_program"] is None


def test_table_has_the_required_columns_types_and_primary_key(test_conn):
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
    assert all(types[name] == "double precision" for name in ("gpa", "gre", "gre_v", "gre_aw"))
    assert types["program"] == "text"
    assert primary_key == ["p_id"]


# ---- idempotency / uniqueness ------------------------------------------------------------

def test_pulling_the_same_data_twice_does_not_duplicate_rows(make_app, test_conn):
    batch = [make_record(1), make_record(2), make_record(3)]
    client = make_app(scraper=FakeScraper(batch, batch)).test_client()

    first = client.post("/pull-data").get_json()
    second = client.post("/pull-data").get_json()

    assert first["added"] == 3
    assert second["added"] == 0
    assert _count_rows(test_conn) == 3
    with test_conn.cursor() as cur:
        cur.execute("SELECT COUNT(DISTINCT p_id) FROM applicants")
        assert cur.fetchone()[0] == 3


def test_loading_twice_does_not_duplicate_rows(test_conn):
    records = [make_record(1), make_record(2)]
    assert load_records(test_conn, records).added == 2
    assert load_records(test_conn, records).added == 0
    assert _count_rows(test_conn) == 2


def test_duplicate_ids_inside_one_batch_are_stored_once(test_conn):
    result = load_records(test_conn, [make_record(5), make_record(5, comments="again")])
    assert result.added == 1
    assert _count_rows(test_conn) == 1


def test_a_duplicate_never_overwrites_the_original_row(test_conn):
    load_records(test_conn, [make_record(1, applicant_status="Accepted")])
    load_records(test_conn, [make_record(1, applicant_status="Rejected")])
    assert fetch_applicants(test_conn)[0]["status"] == "Accepted"


# ---- query functions -----------------------------------------------------------------------

def test_fetch_applicants_returns_dicts_with_the_module_3_keys(test_conn):
    load_records(test_conn, [make_record(3), make_record(1), make_record(2)])

    rows = fetch_applicants(test_conn)

    assert [row["p_id"] for row in rows] == [1, 2, 3]
    assert all(isinstance(row, dict) and set(row) == set(COLUMNS) for row in rows)
    assert len(fetch_applicants(test_conn, limit=2)) == 2


def test_get_analysis_returns_the_keys_the_template_uses(make_app, test_conn):
    load_records(test_conn, SEED)
    app = make_app()
    session_factory = app.extensions["gradcafe"]["session_factory"]

    with session_factory() as session:
        analysis = get_analysis(session)

    assert tuple(analysis) == ANALYSIS_KEYS
    assert analysis["total_entries"] == len(SEED)
    assert len(analysis["assigned"]) == 9 and len(analysis["original"]) == 2
    for card in analysis["assigned"] + analysis["original"]:
        assert tuple(card) == CARD_KEYS
        assert card["answers"] and all(isinstance(line, str) for line in card["answers"])
    assert analysis["assigned"][0]["label"] == "Question 1"
    assert analysis["original"][0]["label"] == "Original question 1"


# ---- invalid source records (Module 3 review) ---------------------------------------------

def test_a_null_record_is_reported_and_the_valid_ones_still_load(test_conn):
    records = [make_record(1), None, make_record(2)]

    result = load_records(test_conn, records)

    assert result.added == 2
    assert [(r.index, r.reason) for r in result.rejected] == [(1, "record is null")]
    assert result.rejected[0].describe() == "record #2: record is null"
    assert [row["p_id"] for row in fetch_applicants(test_conn)] == [1, 2]


def test_null_records_in_the_llm_merge_path_do_not_raise(test_conn):
    base = [make_record(1), None, make_record(2)]
    llm = [{"id": 1, "llm-generated-program": "Computer Science",
            "llm-generated-university": "Stanford University"}, None, {"no": "id"}]

    merged = merge_llm_fields(base, llm)
    result = load_records(test_conn, merged)

    assert merged[1] is None                           # kept in place so its number is right
    assert result.added == 2
    assert [r.describe() for r in result.rejected] == ["record #2: record is null"]
    assert fetch_applicants(test_conn)[0]["llm_generated_program"] == "Computer Science"


def test_command_line_load_reports_the_bad_row_and_loads_the_rest(
    tmp_path, monkeypatch, capsys, db_url, test_conn
):
    data = tmp_path / "data.json"
    data.write_text(json.dumps([make_record(1), None, make_record(2)]), encoding="utf-8")
    llm = tmp_path / "llm.json"
    llm.write_text(json.dumps([None, {"id": 2, "llm-generated-program": "CS"}]), encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", db_url)

    exit_code = load_data.main(["--data", str(data), "--llm-data", str(llm)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "record #2: record is null" in captured.err
    assert "Skipped 1 unusable LLM records" in captured.err
    assert "added 2 new rows; skipped 1 unusable records" in captured.out
    assert _count_rows(test_conn) == 2
