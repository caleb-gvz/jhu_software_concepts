"""Load the cleaned Module 2 Grad Cafe data into the PostgreSQL ``applicants`` table.

Usage (after setting the PG* environment variables, see db_config.py):

    python load_data.py
    python load_data.py --data applicant_data.json --llm-data llm_extend_applicant_data.json

Design notes
------------
* ``record_to_row`` maps one Module 2 record to the 14 table columns. Blank text and
  missing values become NULL; scores outside a plausible range become NULL so a typo
  such as a GPA of 40 cannot distort an average.
* ``upsert_rows`` uses ``INSERT ... ON CONFLICT (p_id) DO UPDATE``. Running the loader
  again never creates duplicates, and it never overwrites an existing row's original
  fields. The only thing a conflict may change is an *empty* LLM column, which is what
  lets the slow LLM step finish later and be loaded on a second run.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg

from db_config import connect

Record = Dict[str, Any]

# The 14 columns of the required ``applicants`` table, in table order.
COLUMNS = (
    "p_id", "program", "comments", "date_added", "url", "status", "term",
    "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
    "llm_generated_program", "llm_generated_university",
)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS applicants (
    p_id                     INTEGER PRIMARY KEY,
    program                  TEXT,
    comments                 TEXT,
    date_added               DATE,
    url                      TEXT,
    status                   TEXT,
    term                     TEXT,
    us_or_international      TEXT,
    gpa                      FLOAT,
    gre                      FLOAT,
    gre_v                    FLOAT,
    gre_aw                   FLOAT,
    degree                   TEXT,
    llm_generated_program    TEXT,
    llm_generated_university TEXT
)
"""

UPSERT_SQL = f"""
INSERT INTO applicants ({", ".join(COLUMNS)})
VALUES ({", ".join(f"%({column})s" for column in COLUMNS)})
ON CONFLICT (p_id) DO UPDATE SET
    llm_generated_program    = COALESCE(applicants.llm_generated_program,
                                        EXCLUDED.llm_generated_program),
    llm_generated_university = COALESCE(applicants.llm_generated_university,
                                        EXCLUDED.llm_generated_university)
"""

# Plausible score ranges. Values outside them are treated as missing.
# Grad Cafe's API reports 0.0 for "not provided" (e.g. 35,263 of the 40,000 records
# have a GRE writing score of exactly 0), so a zero is a placeholder, never a score:
# GPA and GRE writing use an exclusive lower bound of 0, and the GRE Quantitative /
# Verbal range starts at 130, which also excludes zero.
GPA_MAX = 4.33
GRE_SECTION_RANGE = (130.0, 170.0)   # Quantitative and Verbal
GRE_WRITING_MAX = 6.0                # Analytical Writing, in (0, 6]

# The only nationality classifications the analysis recognises. Anything else in the
# raw data (a literal "0" appears in 847 records) is a placeholder and becomes NULL.
NATIONALITY_CLASSES = {"american": "American", "international": "International", "other": "Other"}


def _text(value: Any) -> Optional[str]:
    """Collapse whitespace; blank or non-string values become None."""
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.split())
    return collapsed or None


def _number_in_range(value: Any, low: float, high: float, *, low_inclusive: bool = True) -> Optional[float]:
    """Return value as a float if it lies within [low, high]; otherwise None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    above_low = number >= low if low_inclusive else number > low
    return number if above_low and number <= high else None


def _nationality(value: Any) -> Optional[str]:
    """Canonical American / International / Other, or None for anything else."""
    text = _text(value)
    return NATIONALITY_CLASSES.get(text.lower()) if text else None


def _parse_date(value: Any) -> Optional[datetime.date]:
    """Parse an ISO ``YYYY-MM-DD`` string; anything unparseable becomes None."""
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def record_to_row(record: Record) -> Record:
    """Map one Module 2 record to a dict keyed by the ``applicants`` column names."""
    return {
        "p_id": record["id"],
        "program": _text(record.get("program")),
        "comments": _text(record.get("comments")),
        "date_added": _parse_date(record.get("date_added_raw")),
        "url": _text(record.get("url")),
        "status": _text(record.get("applicant_status")),
        "term": _text(record.get("term")),
        "us_or_international": _nationality(record.get("us_or_international")),
        "gpa": _number_in_range(record.get("gpa"), 0.0, GPA_MAX, low_inclusive=False),
        "gre": _number_in_range(record.get("gre_score"), *GRE_SECTION_RANGE),
        "gre_v": _number_in_range(record.get("gre_v"), *GRE_SECTION_RANGE),
        "gre_aw": _number_in_range(
            record.get("gre_aw"), 0.0, GRE_WRITING_MAX, low_inclusive=False
        ),
        "degree": _text(record.get("degree")),
        "llm_generated_program": _text(record.get("llm-generated-program")),
        "llm_generated_university": _text(record.get("llm-generated-university")),
    }


def merge_llm_fields(base_records: List[Record], llm_records: List[Record]) -> List[Record]:
    """Return copies of base_records with LLM fields overlaid from llm_records (by id)."""
    llm_by_id = {record["id"]: record for record in llm_records}
    merged: List[Record] = []
    for record in base_records:
        combined = dict(record)
        llm = llm_by_id.get(record["id"])
        if llm is not None:
            for key in ("llm-generated-program", "llm-generated-university"):
                if key in llm:
                    combined[key] = llm[key]
        merged.append(combined)
    return merged


def create_table(conn: psycopg.Connection) -> None:
    """Create the ``applicants`` table if it does not exist yet."""
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def reset_table(conn: psycopg.Connection) -> None:
    """Delete every row so a reload applies the current cleaning rules to all data.

    The normal upsert deliberately never rewrites existing rows; use this (via
    ``--reset``) after the cleaning rules change or to rebuild from the JSON files.
    """
    with conn.cursor() as cur:
        cur.execute("TRUNCATE applicants")
    conn.commit()


def _count_rows(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM applicants")
        return cur.fetchone()[0]


def upsert_rows(conn: psycopg.Connection, rows: List[Record]) -> None:
    """Insert rows; on a p_id conflict only fill empty LLM columns."""
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
    conn.commit()


def load_records(conn: psycopg.Connection, records: List[Record]) -> int:
    """Map and upsert records. Returns how many *new* rows were added."""
    rows = [record_to_row(record) for record in records]
    before = _count_rows(conn)
    upsert_rows(conn, rows)
    return _count_rows(conn) - before


def _read_json_list(path: Path) -> List[Record]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv: Optional[List[str]] = None) -> int:
    module_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Load Grad Cafe data into PostgreSQL.")
    parser.add_argument("--data", type=Path, default=module_dir / "applicant_data.json")
    parser.add_argument(
        "--llm-data",
        type=Path,
        default=module_dir / "llm_extend_applicant_data.json",
        help="LLM-standardized records; merged in by id when the file exists.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Empty the applicants table first, then reload everything.",
    )
    args = parser.parse_args(argv)

    records = _read_json_list(args.data)
    if args.llm_data.exists():
        records = merge_llm_fields(records, _read_json_list(args.llm_data))

    try:
        with connect() as conn:
            create_table(conn)
            if args.reset:
                reset_table(conn)
            added = load_records(conn, records)
            total = _count_rows(conn)
    except psycopg.OperationalError as exc:
        print(
            "Could not connect to PostgreSQL. Check that the server is running and that "
            "PGHOST, PGPORT, PGDATABASE, PGUSER and PGPASSWORD are set.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"Read {len(records)} records; added {added} new rows; table now has {total} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
