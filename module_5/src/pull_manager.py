"""Run the "Pull Data" job, allowing only one at a time.

The Flask app owns a single PullManager. Its rules:

* A *job* is any callable ``job(report) -> PullResult``. ``report(message)`` lets the
  job publish progress, which the page shows through ``GET /status``.
* ``start(job)`` runs the job on a background thread; ``run(job)`` runs it in the
  calling thread and returns its outcome. Both refuse (``start`` returns False, ``run``
  returns None) while another job is still in progress. A lock makes check-then-start
  atomic, so two quick button clicks can never launch two scrapes.
* The busy state is plain, observable data (``is_running()``), so tests can check the
  409 "busy" behaviour deterministically: they hold a job open on a
  ``threading.Event`` instead of sleeping.
* A job that raises is recorded as a failed pull with a readable message; the
  exception never escapes into the web request that started it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

Report = Callable[[str], None]
Job = Callable[[Report], Any]


@dataclass(frozen=True)
class PullOutcome:
    """The result of one finished job, as shown to the user."""

    succeeded: bool
    message: str
    added: int = 0


class PullManager:
    """Owns the single in-progress pull and remembers the outcome of the last one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_message = ""
        self._last_succeeded: Optional[bool] = None

    # ----- state -------------------------------------------------------------

    @property
    def last_message(self) -> str:
        """Latest progress line while running; the outcome sentence afterwards."""
        with self._lock:
            return self._last_message

    @property
    def last_succeeded(self) -> Optional[bool]:
        """True/False for the most recent finished pull; None if none has finished."""
        with self._lock:
            return self._last_succeeded

    def is_running(self) -> bool:
        """True while a job is in progress."""
        with self._lock:
            return self._running

    # ----- control -----------------------------------------------------------

    def start(self, job: Job) -> bool:
        """Run ``job`` on a background thread. Returns False if one is already running."""
        if not self._begin():
            return False
        self._thread = threading.Thread(target=self._execute, args=(job,), daemon=True)
        self._thread.start()
        return True

    def run(self, job: Job) -> Optional[PullOutcome]:
        """Run ``job`` in this thread and return its outcome (None if already busy)."""
        if not self._begin():
            return None
        return self._execute(job)

    def wait(self, timeout: Optional[float] = None) -> None:
        """Block until the background job started by ``start`` (if any) has finished."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    # ----- internals ---------------------------------------------------------

    def _begin(self) -> bool:
        """Atomically claim the busy flag; False if another job already holds it."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._last_message = "Starting the data pull..."
            self._last_succeeded = None
            return True

    def _report(self, message: str) -> None:
        """Progress callback handed to the job."""
        with self._lock:
            self._last_message = message

    def _execute(self, job: Job) -> PullOutcome:
        """Run the job, turn its result (or exception) into an outcome, release busy."""
        try:
            result = job(self._report)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Deliberately broad: this is the job-runner boundary, and any failure inside
            # a pull must become a readable, failed outcome instead of killing the thread.
            outcome = PullOutcome(
                succeeded=False, message=f"The data pull failed: {exc}"
            )
        else:
            outcome = PullOutcome(
                succeeded=result.error is None,
                message=result.summary(),
                added=result.added,
            )
        with self._lock:
            self._running = False
            self._last_message = outcome.message
            self._last_succeeded = outcome.succeeded
        return outcome
