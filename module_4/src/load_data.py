"""Load the cleaned Module 2 Grad Cafe data into the PostgreSQL ``applicants`` table.

Usage (after setting DATABASE_URL or the PG* variables, see db_config.py):

    python load_data.py
    python load_data.py --data applicant_data.json --llm-data llm_extend_applicant_data.json

Design notes
------------
* ``record_to_row`` maps one Module 2 record to the table's columns. Blank text and
  missing values become NULL; scores outside a plausible range become NULL so a typo
  such as a GPA of 40 cannot distort an average.
* ``upsert_rows`` uses ``INSERT ... ON CONFLICT (p_id) DO UPDATE``. Running the loader
  again never creates duplicates, and it never overwrites an existing row's original
  fields. The only thing a conflict may change is an *empty* LLM column, which is what
  lets the slow LLM step finish later and be loaded on a second run.
* Every input record is validated first (``validate_record``). A record that is null,
  not a JSON object, or lacks a usable integer ``id`` is set aside and reported by its
  position in the file; all usable records are still loaded. One bad row can never
  stop a load or make it crash.
* ``load_records`` writes a batch in a single transaction: either every usable row of
  the batch is stored or, if the database write fails, none of it is.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg

from db_config import connect

Record = Dict[str, Any]

# The columns of the required ``applicants`` table, in table order.
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

# p_id is a PostgreSQL INTEGER, so ids must fit in a signed 32-bit integer.
MAX_P_ID = 2**31 - 1

# How many rejected records ``main`` lists individually before summarising the rest.
MAX_REJECTIONS_SHOWN = 20


@dataclass(frozen=True)
class RejectedRecord:
    """A record that could not be loaded, identified by its position in the input list."""

    index: int      # 0-based position in the input list
    reason: str

    def describe(self) -> str:
        """Human-readable form with a 1-based record number, e.g. ``record #3: ...``."""
        return f"record #{self.index + 1}: {self.reason}"


@dataclass
class LoadResult:
    """Outcome of ``load_records``: new rows added and the records that were set aside."""

    added: int
    rejected: List[RejectedRecord] = field(default_factory=list)


class DataFileError(Exception):
    """A data file is missing, is not valid JSON, or does not hold a JSON list."""


# ---- record validation ---------------------------------------------------------------

def _record_id(record: Record) -> Optional[int]:
    """The record's id as an int, or None when it is missing or not a whole number."""
    value = record.get("id")
    if isinstance(value, bool):          # bool is an int subclass, but True is not an id
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def validate_record(record: Any) -> Optional[str]:
    """Return why ``record`` cannot be loaded, or None if it is usable.

    A usable record is a JSON object (dict) whose ``id`` is a positive whole number
    that fits the INTEGER primary key. Every other field is optional and is cleaned by
    ``record_to_row``.
    """
    if record is None:
        return "record is null"
    if not isinstance(record, dict):
        return f"record is a {type(record).__name__}, not a JSON object"
    if "id" not in record:
        return "record has no 'id' field"
    record_id = _record_id(record)
    if record_id is None:
        return f"record id {record['id']!r} is not a whole number"
    if not 0 < record_id <= MAX_P_ID:
        return f"record id {record_id} is outside the valid range 1..{MAX_P_ID}"
    return None


def partition_records(
    records: Sequence[Any],
) -> Tuple[List[Record], List[RejectedRecord]]:
    """Split records into (usable records, rejected records with their positions)."""
    usable: List[Record] = []
    rejected: List[RejectedRecord] = []
    for index, record in enumerate(records):
        reason = validate_record(record)
        if reason is None:
            usable.append(record)
        else:
            rejected.append(RejectedRecord(index, reason))
    return usable, rejected


# ---- field cleaning ------------------------------------------------------------------

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
    """Map one (validated) Module 2 record to a dict keyed by the ``applicants`` columns."""
    return {
        "p_id": _record_id(record),
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


def merge_llm_fields(base_records: Sequence[Any], llm_records: Sequence[Any]) -> List[Any]:
    """Return copies of base_records with LLM fields overlaid from llm_records (by id).

    Invalid records never raise here. An invalid LLM record is ignored (it has no id to
    match on), and an invalid base record is passed through unchanged, in its original
    position, so ``load_records`` can report it with the right record number.
    """
    usable_llm, _ = partition_records(llm_records)
    llm_by_id = {_record_id(record): record for record in usable_llm}
    merged: List[Any] = []
    for record in base_records:
        if validate_record(record) is not None:
            merged.append(record)
            continue
        combined = dict(record)
        llm = llm_by_id.get(_record_id(record))
        if llm is not None:
            for key in ("llm-generated-program", "llm-generated-university"):
                if key in llm:
                    combined[key] = llm[key]
        merged.append(combined)
    return merged


# ---- database writes -----------------------------------------------------------------

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
    """Number of rows currently in ``applicants``."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM applicants")
        return cur.fetchone()[0]


def upsert_rows(conn: psycopg.Connection, rows: List[Record]) -> None:
    """Insert rows; on a p_id conflict only fill empty LLM columns.

    Does not commit: the caller decides whether the batch is kept (see ``load_records``).
    """
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)


def load_records(conn: psycopg.Connection, records: Sequence[Any]) -> LoadResult:
    """Validate, map and upsert records in one transaction.

    Unusable records are skipped and listed in the result instead of stopping the load.
    If the database write itself fails, the whole batch is rolled back (no partial
    writes) and the error is re-raised.
    """
    usable, rejected = partition_records(records)
    rows = [record_to_row(record) for record in usable]
    try:
        before = _count_rows(conn)
        upsert_rows(conn, rows)
        added = _count_rows(conn) - before
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return LoadResult(added=added, rejected=rejected)


# ---- command line --------------------------------------------------------------------

def _read_json_list(path: Path) -> List[Any]:
    """Read a JSON array from ``path``; raise DataFileError with a readable message."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        raise DataFileError(f"{path} does not exist.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DataFileError(f"{path} is not valid JSON ({exc}).") from exc
    if not isinstance(data, list):
        raise DataFileError(
            f"{path} must contain a JSON list of records, not a {type(data).__name__}."
        )
    return data


def _report_rejections(label: str, rejected: Sequence[RejectedRecord]) -> None:
    """Print skipped records to stderr, listing at most MAX_REJECTIONS_SHOWN of them."""
    if not rejected:
        return
    print(f"Skipped {len(rejected)} unusable {label}:", file=sys.stderr)
    for rejection in rejected[:MAX_REJECTIONS_SHOWN]:
        print(f"  {rejection.describe()}", file=sys.stderr)
    hidden = len(rejected) - MAX_REJECTIONS_SHOWN
    if hidden > 0:
        print(f"  ... and {hidden} more", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point; returns the process exit code."""
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

    try:
        records = _read_json_list(args.data)
    except DataFileError as exc:
        print(f"Cannot load data: {exc}", file=sys.stderr)
        return 1

    if args.llm_data.exists():
        try:
            llm_records = _read_json_list(args.llm_data)
        except DataFileError as exc:
            print(f"Warning: ignoring LLM data: {exc}", file=sys.stderr)
        else:
            _report_rejections("LLM records", partition_records(llm_records)[1])
            records = merge_llm_fields(records, llm_records)

    try:
        with connect() as conn:
            create_table(conn)
            if args.reset:
                reset_table(conn)
            result = load_records(conn, records)
            total = _count_rows(conn)
    except psycopg.OperationalError as exc:
        print(
            "Could not connect to PostgreSQL. Check that the server is running and that "
            "DATABASE_URL (or PGHOST, PGPORT, PGDATABASE, PGUSER and PGPASSWORD) is set.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1

    _report_rejections("records", result.rejected)
    print(
        f"Read {len(records)} records; added {result.added} new rows; "
        f"skipped {len(result.rejected)} unusable records; table now has {total} rows."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
