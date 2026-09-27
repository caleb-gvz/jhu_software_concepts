"""Normalize scraped GradCafe applicant data without altering raw fields."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional

_TEXT_FIELDS = (
    "program_raw",
    "university_raw",
    "program",
    "degree",
    "status_label_raw",
    "term",
    "us_or_international",
    "comments",
    "date_added",
    "date_added_raw",
)
_FLOAT_FIELDS = ("gpa", "gre_score", "gre_v", "gre_aw", "gre_subject")


def _clean_text(value: Any) -> Any:
    """Collapse internal whitespace; blank strings become None. Non-strings pass through."""
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return normalized if normalized else None
    return value


def _normalize_status(value: Optional[str]) -> Optional[str]:
    """Whitespace-only normalization of a status string; never changes its meaning."""
    return _clean_text(value)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def clean_data(records: List[Any]) -> List[Any]:
    """Return a new, normalized list of records. Never mutates the input.

    Anything that is not a dict (e.g. a ``null`` entry) is passed through unchanged, in
    place, so the loader can report it by position instead of this step crashing.
    """
    cleaned: List[Any] = []
    for record in records:
        if not isinstance(record, dict):
            cleaned.append(record)
            continue
        new_record = dict(record)
        for field in _TEXT_FIELDS:
            if field in new_record:
                new_record[field] = _clean_text(new_record[field])
        if "applicant_status" in new_record:
            new_record["applicant_status"] = _normalize_status(
                new_record["applicant_status"]
            )
        for field in _FLOAT_FIELDS:
            if field in new_record:
                new_record[field] = _coerce_float(new_record[field])
        cleaned.append(new_record)
    return cleaned


def load_data(path: str) -> List[Dict[str, Any]]:
    """Read a JSON list of records."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(records: List[Dict[str, Any]], path: str) -> None:
    """Write records as an indented JSON list."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def main(argv: Optional[List[str]] = None) -> None:
    """Command-line entry point: clean a JSON file in place or into --output."""
    parser = argparse.ArgumentParser(
        description="Clean scraped GradCafe applicant data."
    )
    parser.add_argument("--input", default="applicant_data.json")
    parser.add_argument(
        "--output", default=None, help="Defaults to overwriting --input."
    )
    args = parser.parse_args(argv)
    output_path = args.output or args.input

    records = load_data(args.input)
    cleaned = clean_data(records)
    save_data(cleaned, output_path)
    print(f"Cleaned {len(cleaned)} records -> {output_path}")


if __name__ == "__main__":
    main()
