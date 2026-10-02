"""The LIMIT guard every query in the application goes through.

Rules (Module 5, "Enforce LIMIT for every query"):

* Every ``SELECT`` is built as a composed ``psycopg.sql`` object and then passed through
  ``limited()``, which appends ``LIMIT %(limit)s``. The limit is therefore always part of
  the statement and is always a *bound parameter*, never text pasted into the SQL.
* The value bound to it comes from ``clamp_limit()`` (via ``limit_params()``), which keeps
  any request inside ``MIN_LIMIT``..``MAX_LIMIT`` so an oversized request such as
  ``limit=10000000`` can never turn a query into a full-table dump.
* Something that is not a whole number (``"abc"``, ``"1; DROP TABLE applicants"``) is
  rejected with ``ValueError`` instead of being guessed at, so the caller can answer
  "bad request" rather than run a query on a value it does not understand.

Statement construction and execution stay separate, as the assignment requires::

    statement = limited(sql.SQL("SELECT {c} FROM {t}").format(c=..., t=...))
    cursor.execute(statement, limit_params(requested_limit, {"term": term}))
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

from psycopg import sql

MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_LIMIT = 100

# Optional sign then ASCII digits only: rejects "", "1e3", "0x10", "1 OR 1=1", "2.5", ...
_WHOLE_NUMBER = re.compile(r"[+-]?[0-9]+")


def clamp_limit(requested: Any = None, default: int = DEFAULT_LIMIT) -> int:
    """Return ``requested`` as an int inside ``MIN_LIMIT``..``MAX_LIMIT``.

    ``None`` means "no preference" and gives ``default`` (itself clamped). Integers and
    whole-number strings (query-string values arrive as text) are clamped into range.
    Anything else -- floats, booleans, bytes, lists, or text that is not a whole number --
    raises ``ValueError``.
    """
    if requested is None:
        requested = default
    if isinstance(requested, bool) or not isinstance(requested, (int, str)):
        raise ValueError("limit must be a whole number")
    if isinstance(requested, str):
        text = requested.strip()
        if not _WHOLE_NUMBER.fullmatch(text):
            raise ValueError("limit must be a whole number")
        requested = int(text)
    return max(MIN_LIMIT, min(MAX_LIMIT, requested))


def limited(statement: sql.Composable) -> sql.Composed:
    """``statement`` followed by ``LIMIT %(limit)s`` (bind it with ``limit_params``)."""
    return sql.SQL("{} LIMIT {}").format(statement, sql.Placeholder("limit"))


def limit_params(
    requested: Any = None, params: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """The parameters for a ``limited()`` statement: ``params`` plus the clamped limit.

    A new dict is returned and ``params`` is left untouched. The ``limit`` entry is set
    last, so a caller-supplied ``"limit"`` key can never override the clamp.
    """
    bound: Dict[str, Any] = dict(params or {})
    bound["limit"] = clamp_limit(requested)
    return bound
