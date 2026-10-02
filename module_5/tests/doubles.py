"""Test doubles shared by the test modules.

None of these touch the network. They stand in for the Grad Cafe scraper, the loader
and the analysis query so each test controls exactly what the app sees.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Sequence, Set

from load_data import LoadResult, load_records, upsert_rows, record_to_row


def make_record(record_id: int, **overrides: Any) -> Dict[str, Any]:
    """A record shaped exactly like ``scrape._parse_record`` output (Module 2 schema)."""
    record = {
        "id": record_id,
        "url": f"https://www.thegradcafe.com/result/{record_id}",
        "program_raw": "Computer Science",
        "university_raw": "Stanford University",
        "program": "Computer Science, Stanford University",
        "degree": "PhD",
        "applicant_status": "Accepted",
        "status_date": "2026-02-01",
        "status_label_raw": "Accepted",
        "term": "Fall 2026",
        "us_or_international": "American",
        "gre_score": 165.0,
        "gre_v": 160.0,
        "gre_aw": 4.5,
        "gre_subject": None,
        "gpa": 3.8,
        "comments": "Great news!",
        "date_added": "February 01, 2026",
        "date_added_raw": "2026-02-01",
    }
    record.update(overrides)
    return record


class FakeScraper:
    """Callable with the scraper signature that returns canned records.

    ``batches`` is a list of record lists; call N returns batch N (the last batch
    repeats). Every call's ``known_ids`` is recorded so tests can check what the app
    told the scraper.
    """

    def __init__(self, *batches: Sequence[Dict[str, Any]]) -> None:
        self.batches: List[List[Dict[str, Any]]] = [list(batch) for batch in batches] or [[]]
        self.calls: List[Set[int]] = []

    def __call__(self, known_ids: Set[int], max_pages: int) -> List[Dict[str, Any]]:
        self.calls.append(set(known_ids))
        index = min(len(self.calls) - 1, len(self.batches) - 1)
        # Copy dicts so a test cannot be affected by the app mutating them; anything
        # else (e.g. a deliberate ``None``) is returned as-is.
        return [dict(r) if isinstance(r, dict) else r for r in self.batches[index]]


class BlockingScraper(FakeScraper):
    """A FakeScraper that waits on an Event, keeping a background pull "in progress".

    Tests use it to hold the busy state open deterministically (no ``sleep()``):
    ``started`` is set once the pull reaches the scraper and ``release`` lets it finish.
    """

    def __init__(self, *batches: Sequence[Dict[str, Any]]) -> None:
        super().__init__(*batches)
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, known_ids: Set[int], max_pages: int) -> List[Dict[str, Any]]:
        self.started.set()
        self.release.wait(timeout=30)
        return super().__call__(known_ids, max_pages)


class SpyLoader:
    """Wraps the real loader and remembers every batch of records it was given."""

    def __init__(self) -> None:
        self.batches: List[List[Dict[str, Any]]] = []

    def __call__(self, conn, records: Sequence[Any]) -> LoadResult:
        self.batches.append(list(records))
        return load_records(conn, records)


class FailingLoader:
    """Writes the first record (uncommitted) and then fails, like a crash mid-load."""

    def __init__(self, message: str = "disk full") -> None:
        self.message = message

    def __call__(self, conn, records: Sequence[Any]) -> LoadResult:
        upsert_rows(conn, [record_to_row(records[0])])
        raise RuntimeError(self.message)


class SpyQuery:
    """Stands in for ``orm_queries.get_analysis`` and counts how often it ran."""

    def __init__(self, analysis: Optional[Dict[str, Any]] = None) -> None:
        self.analysis = analysis or fake_analysis()
        self.calls = 0

    def __call__(self, session) -> Dict[str, Any]:
        self.calls += 1
        return self.analysis


class NullSession:
    """A context-manager session for tests whose query function ignores the session."""

    def __enter__(self) -> "NullSession":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None


def fake_analysis(total_entries: int = 3) -> Dict[str, Any]:
    """A small analysis dictionary in the shape ``orm_queries.get_analysis`` returns."""
    return {
        "total_entries": total_entries,
        "assigned": [
            {
                "number": "2",
                "label": "Question 2",
                "title": "Percent international",
                "question": "What percentage are international students?",
                "answers": ["Percent international: 39.28%"],
            },
            {
                "number": "3",
                "label": "Question 3",
                "title": "Averages",
                "question": "What are the average scores?",
                "answers": ["Average GPA: 3.79", "Average GRE Quantitative: 161.25"],
            },
        ],
        "original": [
            {
                "number": "O1",
                "label": "Original question 1",
                "title": "Acceptance by nationality",
                "question": "How does acceptance differ by nationality?",
                "answers": ["American: 50.00% accepted (n = 2)"],
            },
        ],
    }
