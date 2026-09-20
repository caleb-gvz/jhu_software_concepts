"""Fetch newly posted Grad Cafe entries and add them to the database.

This is the command the web app's **Pull Data** button runs in a subprocess:

    python pull_data.py

Flow: ask the database which ids it already has -> scrape the newest Grad Cafe pages
until reaching entries we already have (``scrape.scrape_new_records``, the Module 2
scraper) -> clean them with Module 2's ``clean.clean_data`` -> upsert with
``load_data.load_records``. Because loading is an upsert that never rewrites existing
rows, a pull can only *add* usable data, never overwrite or corrupt it.

Every message printed is a complete, user-friendly line; the web app shows the most
recent one as live progress and, when the process ends, as the outcome. The exit code
is 0 on success and 2 if the pull could not finish (blocked, offline, ...).

Records added by a pull have no LLM-standardized program/university (the local model
is far too slow to run inside a button click); those two columns stay NULL for them.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

import psycopg

from clean import clean_data
from db_config import connect
from load_data import create_table, load_records
from scrape import ScrapeError, scrape_new_records

# How many of the newest survey pages (~20 entries each) one pull may read.
DEFAULT_MAX_PAGES = 20

ScrapeFunction = Callable[[Set[int], int], List[Dict[str, Any]]]


@dataclass
class PullResult:
    added: int
    error: Optional[str] = None

    def summary(self) -> str:
        """One sentence describing the outcome, suitable for showing to the user."""
        if self.error is None:
            if self.added == 0:
                return "No new entries were available; the database is already up to date."
            return f"Added {self.added} new records to the database."
        if self.added == 0:
            return f"Pull stopped: {self.error} No new records were added."
        noun = "record was" if self.added == 1 else "records were"
        return f"Pull stopped: {self.error} {self.added} {noun} added before it stopped."


def _known_ids(conn: psycopg.Connection) -> Set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT p_id FROM applicants")
        return {row[0] for row in cur.fetchall()}


def pull_new_data(
    conn: psycopg.Connection,
    scrape_fn: ScrapeFunction = lambda known_ids, max_pages: scrape_new_records(
        known_ids, max_pages=max_pages
    ),
    max_pages: int = DEFAULT_MAX_PAGES,
) -> PullResult:
    """Scrape entries the database lacks, clean them, and add them.

    ``scrape_fn`` is injectable so tests can run without the network. If the scrape
    fails part-way, the records fetched so far are still saved and the error is
    reported in the result.
    """
    known_ids = _known_ids(conn)
    error: Optional[str] = None
    try:
        new_records = scrape_fn(known_ids, max_pages)
    except ScrapeError as exc:
        new_records = exc.partial_records
        error = str(exc)

    added = load_records(conn, clean_data(new_records)) if new_records else 0
    return PullResult(added=added, error=error)


def main() -> int:
    print("Checking Grad Cafe for new entries...", flush=True)
    try:
        with connect() as conn:
            create_table(conn)
            result = pull_new_data(conn)
    except psycopg.OperationalError as exc:
        print(f"Pull stopped: could not connect to the database ({exc}).", flush=True)
        return 2
    print(result.summary(), flush=True)
    return 2 if result.error else 0


if __name__ == "__main__":
    sys.exit(main())
