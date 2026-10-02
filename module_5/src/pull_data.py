"""Fetch newly posted Grad Cafe entries and add them to the database.

This is what the web app's **Pull Data** button runs (in a background thread, see
``pull_manager.py``). It can also be run by hand:

    python pull_data.py

Flow: ask the database which ids it already has -> scrape the newest Grad Cafe pages
until reaching entries we already have (``scrape.scrape_new_records``, the Module 2
scraper) -> clean them with Module 2's ``clean.clean_data`` -> upsert with
``load_data.load_records``. Because loading is an upsert that never rewrites existing
rows, a pull can only *add* usable data, never overwrite or corrupt it.

The scraper and the loader are parameters, so tests (and the Flask app factory) can
inject fakes and never touch the network. If the loader fails, the transaction is
rolled back, so a failed pull leaves no partial writes behind.

Records added by a pull have no LLM-standardized program/university (the local model
is far too slow to run inside a button click); those two columns stay NULL for them.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

import psycopg
from psycopg import sql

from clean import clean_data
from db_config import connect
from load_data import APPLICANTS_TABLE, LoadResult, create_table, load_records
from scrape import ScrapeError, scrape_new_records
from sql_safety import MAX_LIMIT, limit_params, limited

# One page of already-stored ids: keyset pagination ("the next ids after the last one I
# saw"), so no single query ever asks for more than MAX_LIMIT rows.
KNOWN_ID_PAGE_STATEMENT = sql.SQL(
    "SELECT {key} FROM {table} WHERE {key} > %(after)s ORDER BY {key}"
).format(key=sql.Identifier("p_id"), table=APPLICANTS_TABLE)

# Smaller than any possible INTEGER p_id, so the first page starts at the very beginning.
BEFORE_EVERY_ID = -(2**31)

# How many of the newest survey pages (~20 entries each) one pull may read.
DEFAULT_MAX_PAGES = 20

ScrapeFunction = Callable[[Set[int], int], List[Dict[str, Any]]]
LoadFunction = Callable[[psycopg.Connection, Sequence[Any]], LoadResult]
ReportFunction = Callable[[str], None]


@dataclass
class PullResult:
    """How many rows one pull added, how many records it skipped, and any scrape error."""

    added: int
    error: Optional[str] = None
    skipped: int = 0

    def summary(self) -> str:
        """One sentence describing the outcome, suitable for showing to the user."""
        skipped = (
            f" {self.skipped} unusable record{'s were' if self.skipped != 1 else ' was'} skipped."
            if self.skipped else ""
        )
        if self.error is None:
            if self.added == 0:
                return (
                    "No new entries were available; the database is already up to date."
                    + skipped
                )
            noun = "record" if self.added == 1 else "records"
            return f"Added {self.added} new {noun} to the database." + skipped
        if self.added == 0:
            return f"Pull stopped: {self.error} No new records were added." + skipped
        noun = "record was" if self.added == 1 else "records were"
        return (
            f"Pull stopped: {self.error} {self.added} {noun} added before it stopped."
            + skipped
        )


def default_scraper(known_ids: Set[int], max_pages: int) -> List[Dict[str, Any]]:
    """The real Module 2 scraper: fetch the newest Grad Cafe entries not in known_ids."""
    return scrape_new_records(known_ids, max_pages=max_pages)


def _known_ids(conn: psycopg.Connection) -> Set[int]:
    """Every p_id already stored in ``applicants``, read one capped page at a time.

    Each query is ``LIMIT``-ed to ``MAX_LIMIT`` ids; a full page means there may be more,
    so the next query resumes after the last id seen. The loop ends on a short page.
    """
    statement = limited(KNOWN_ID_PAGE_STATEMENT)
    known: Set[int] = set()
    after = BEFORE_EVERY_ID
    while True:
        with conn.cursor() as cur:
            cur.execute(statement, limit_params(MAX_LIMIT, {"after": after}))
            page = [row[0] for row in cur.fetchall()]
        known.update(page)
        if len(page) < MAX_LIMIT:
            return known
        after = page[-1]


def pull_new_data(
    conn: psycopg.Connection,
    scrape_fn: ScrapeFunction = default_scraper,
    max_pages: int = DEFAULT_MAX_PAGES,
    loader: LoadFunction = load_records,
) -> PullResult:
    """Scrape entries the database lacks, clean them, and add them.

    ``scrape_fn`` and ``loader`` are injectable so tests run without the network. If
    the scrape fails part-way, the records fetched so far are still saved and the error
    is reported in the result. If the *loader* fails, its transaction is rolled back
    and the exception propagates, so nothing is half-written.
    """
    known_ids = _known_ids(conn)
    error: Optional[str] = None
    try:
        new_records = scrape_fn(known_ids, max_pages)
    except ScrapeError as exc:
        new_records = exc.partial_records
        error = str(exc)

    if not new_records:
        return PullResult(added=0, error=error)
    try:
        loaded = loader(conn, clean_data(new_records))
    except Exception:
        conn.rollback()
        raise
    return PullResult(added=loaded.added, error=error, skipped=len(loaded.rejected))


def run_pull(
    database_url: Optional[str] = None,
    scrape_fn: ScrapeFunction = default_scraper,
    loader: LoadFunction = load_records,
    report: ReportFunction = lambda message: None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> PullResult:
    """Open a connection, make sure the table exists, and run one pull.

    ``report`` receives short progress messages for the web page. Connection errors
    and loader errors propagate to the caller (the PullManager records them).
    """
    report("Checking Grad Cafe for new entries...")
    with connect(database_url) as conn:
        create_table(conn)
        return pull_new_data(conn, scrape_fn=scrape_fn, max_pages=max_pages, loader=loader)


def main() -> int:
    """Command-line entry point: pull once and print the outcome."""
    try:
        result = run_pull(report=lambda message: print(message, flush=True))
    except psycopg.OperationalError as exc:
        print(f"Pull stopped: could not connect to the database ({exc}).", flush=True)
        return 2
    print(result.summary(), flush=True)
    return 2 if result.error else 0


if __name__ == "__main__":  # pragma: no cover  (only calls main(), which is tested)
    sys.exit(main())
