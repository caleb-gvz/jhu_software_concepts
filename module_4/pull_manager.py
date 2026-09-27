"""Run the "Pull Data" scrape as a subprocess, allowing only one at a time.

The Flask app owns a single PullManager. Its rules:

* ``start()`` launches the command only if no earlier launch is still running;
  otherwise it returns False and leaves the running process untouched. A lock makes
  the check-then-launch atomic, so two quick button clicks cannot start two scrapes.
* Output is read on a background thread. The most recent non-blank line is exposed as
  ``last_message`` so the page can show live progress and, afterwards, the outcome.
* Nothing here talks to the database or the scraper directly; the command it runs
  (``pull_data.py``) does that, which keeps the web process responsive.
"""

from __future__ import annotations

import subprocess
import threading
from typing import List, Optional


class PullManager:
    def __init__(self, command: List[str], cwd: Optional[str] = None) -> None:
        self._command = command
        self._cwd = cwd
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._last_message = ""
        self._last_succeeded: Optional[bool] = None

    # ----- state -------------------------------------------------------------

    @property
    def last_message(self) -> str:
        """Latest output line (live progress while running, the outcome afterwards)."""
        with self._lock:
            return self._last_message

    @property
    def last_succeeded(self) -> Optional[bool]:
        """True/False for the most recent finished pull; None if none has finished."""
        with self._lock:
            return self._last_succeeded

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running_locked()

    def _is_running_locked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # ----- control -----------------------------------------------------------

    def start(self) -> bool:
        """Launch the pull. Returns False if one is already running or cannot launch."""
        with self._lock:
            if self._is_running_locked():
                return False
            try:
                self._process = subprocess.Popen(
                    self._command,
                    cwd=self._cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                self._process = None
                self._last_message = f"The pull could not be started: {exc}"
                self._last_succeeded = False
                return False
            self._last_message = ""
            self._last_succeeded = None
            self._reader = threading.Thread(
                target=self._read_output, args=(self._process,), daemon=True
            )
            self._reader.start()
            return True

    def wait(self, timeout: Optional[float] = None) -> None:
        """Block until the current pull (if any) has finished and its output is read."""
        process, reader = self._process, self._reader
        if process is not None:
            process.wait(timeout=timeout)
        if reader is not None:
            reader.join(timeout=timeout)

    # ----- internals ---------------------------------------------------------

    def _read_output(self, process: subprocess.Popen) -> None:
        """Track the latest non-blank output line, then record the final outcome."""
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if line:
                with self._lock:
                    self._last_message = line
        exit_code = process.wait()
        with self._lock:
            self._last_succeeded = exit_code == 0
            if exit_code != 0 and not self._last_message:
                self._last_message = f"The pull failed (exit code {exit_code})."
