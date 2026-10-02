"""Flask front end for the Grad Cafe analysis.

Routes
------

``GET /analysis``
    The analysis page (``/`` serves the same page).
``POST /pull-data``
    Start a pull of new Grad Cafe entries: ``202 {"ok": true}`` when it starts in the
    background, or ``200`` with the outcome when the app is configured to pull
    synchronously. ``409 {"busy": true}`` while a pull is already running.
``POST /update-analysis``
    Re-run the analysis queries: ``200 {"ok": true}``, or ``409 {"busy": true}`` (and no
    update) while a pull is running. Never scrapes.
``GET /applicants``
    JSON list of stored applicants. Query string: ``term`` and ``status`` (exact,
    case-insensitive filters), ``sort`` (a stored column name, default ``p_id``),
    ``direction`` (``asc``/``desc``) and ``limit`` (clamped to 1..100, default 100). Every
    value is validated or bound as a parameter; bad input gives ``400``, an unreachable
    database ``503``. Read-only.
``GET /status``
    JSON the page polls to show pull progress.

``create_app`` is a factory, and every collaborator can be replaced. This is how the
tests run the whole app without the network and against a scratch database:

* ``config``: overrides such as ``DATABASE_URL`` or ``PULL_IN_BACKGROUND``.
* ``scraper``: ``scraper(known_ids, max_pages) -> records`` (default: the Module 2
  scraper against Grad Cafe).
* ``loader``: ``loader(conn, records) -> LoadResult`` (default:
  ``load_data.load_records``).
* ``query_fn``: ``query_fn(session) -> dict`` (default: ``orm_queries.get_analysis``).
* ``session_factory``: SQLAlchemy session factory (default: built from ``DATABASE_URL``).
* ``pull_manager``: the busy-state owner (default: a new ``PullManager``).

All database reads for the page go through ``orm_queries`` (the ``Applicant`` model);
this module contains no SQL.

Run it with ``python flask_app.py`` or ``flask --app flask_app run`` from ``src/``, after
setting ``DATABASE_URL`` (see ``db_config.py``).
"""

from __future__ import annotations

import datetime
import os
import secrets
import threading
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import psycopg
from flask import Flask, jsonify, render_template, request
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import orm_queries
import pull_data
from db_config import connect, database_url
from load_data import load_records
from models import make_session_factory
from pull_manager import PullManager
from query_data import search_applicants
from sql_safety import clamp_limit

BUSY_MESSAGE = (
    "New data is currently being retrieved from Grad Café. Please wait for the pull to "
    "finish, then click Update Analysis to include the new records."
)
DB_ERROR_MESSAGE = (
    "The page could not connect to the database. Check that PostgreSQL is running and "
    "that DATABASE_URL is set."
)


class AnalysisCache:
    """The most recent analysis snapshot shown on the page (thread-safe).

    ``GET /analysis`` renders the snapshot; ``POST /update-analysis`` replaces it. The
    snapshot is computed on first use, so a fresh server shows current data.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        query_fn: Callable[[Session], Dict[str, Any]],
    ) -> None:
        self._session_factory = session_factory
        self._query_fn = query_fn
        self._lock = threading.Lock()
        self.analysis: Optional[Dict[str, Any]] = None
        self.updated_at: Optional[datetime.datetime] = None

    def refresh(self) -> Dict[str, Any]:
        """Run the queries now and store the result as the current snapshot."""
        with self._session_factory() as session:
            analysis = self._query_fn(session)
        with self._lock:
            self.analysis = analysis
            self.updated_at = datetime.datetime.now()
        return analysis

    def current(self) -> Dict[str, Any]:
        """The stored snapshot, computing it first if there is none yet."""
        with self._lock:
            analysis = self.analysis
        return analysis if analysis is not None else self.refresh()


def _busy_response() -> Tuple[Any, int]:
    """The JSON body and status used whenever a pull is already in progress."""
    return jsonify(ok=False, busy=True, message=BUSY_MESSAGE), 409


def _json_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One applicant row made JSON-friendly (dates become ISO ``YYYY-MM-DD`` strings)."""
    return {
        column: value.isoformat() if isinstance(value, datetime.date) else value
        for column, value in row.items()
    }


def _applicants_response(db_url: str, args: Mapping[str, str]) -> Tuple[Any, int]:
    """Answer ``GET /applicants`` from the query-string ``args``.

    Every value is validated before it can reach SQL: ``limit`` must be a whole number
    (then it is clamped to 1..100), ``sort`` must name a stored column, ``direction`` must
    be ``asc`` or ``desc``, and ``term`` / ``status`` are bound parameters. A rejected value
    gives ``400`` with a fixed message that never repeats the input.
    """
    direction = args.get("direction", "asc").strip().lower()
    if direction not in ("asc", "desc"):
        return jsonify(ok=False, error="direction must be 'asc' or 'desc'"), 400
    try:
        limit = clamp_limit(args.get("limit"))
        with connect(db_url) as conn:
            rows = search_applicants(
                conn,
                term=args.get("term"),
                status=args.get("status"),
                sort=args.get("sort", "p_id"),
                descending=direction == "desc",
                limit=limit,
            )
    except ValueError as exc:          # bad limit or sort: the message is fixed text
        return jsonify(ok=False, error=str(exc)), 400
    except psycopg.OperationalError:
        return jsonify(ok=False, error=DB_ERROR_MESSAGE), 503
    return jsonify(count=len(rows), limit=limit, applicants=[_json_row(r) for r in rows]), 200


# The factory takes one injectable collaborator per seam (scraper, loader, query function,
# session factory, pull manager) so tests can run the whole app offline, and it defines the
# routes as closures over them. That is why it has more arguments and locals than the
# default limits allow.
def create_app(  # pylint: disable=too-many-arguments,too-many-locals
    config: Optional[Mapping[str, Any]] = None,
    *,
    scraper: Optional[pull_data.ScrapeFunction] = None,
    loader: Optional[pull_data.LoadFunction] = None,
    query_fn: Optional[Callable[[Session], Dict[str, Any]]] = None,
    session_factory: Optional[Callable[[], Session]] = None,
    pull_manager: Optional[PullManager] = None,
) -> Flask:
    """Build the Flask app; every collaborator can be replaced (see the module docstring)."""
    # The assets live in the ``web_assets`` package so they ship inside a built wheel.
    app = Flask(
        __name__,
        template_folder="web_assets/templates",
        static_folder="web_assets/static",
    )
    app.config.update(
        # Only signs the session cookie; a fresh random key per process is fine.
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(16),
        DATABASE_URL=database_url(),
        PULL_IN_BACKGROUND=True,
        PULL_MAX_PAGES=pull_data.DEFAULT_MAX_PAGES,
    )
    app.config.update(config or {})

    manager = pull_manager or PullManager()
    sessions = session_factory or make_session_factory(app.config["DATABASE_URL"])
    cache = AnalysisCache(sessions, query_fn or orm_queries.get_analysis)
    scrape_fn = scraper or pull_data.default_scraper
    load_fn = loader or load_records
    # Exposed so tests and tooling can observe the app's state.
    app.extensions["gradcafe"] = {
        "pull_manager": manager,
        "analysis_cache": cache,
        "session_factory": sessions,
    }

    def pull_job(report: Callable[[str], None]) -> pull_data.PullResult:
        """One pull against this app's database with this app's scraper and loader."""
        return pull_data.run_pull(
            app.config["DATABASE_URL"],
            scrape_fn=scrape_fn,
            loader=load_fn,
            report=report,
            max_pages=app.config["PULL_MAX_PAGES"],
        )

    @app.get("/")
    @app.get("/analysis")
    def analysis():
        """Render the analysis page from the current snapshot."""
        page: Dict[str, Any] = {
            "pulling": manager.is_running(),
            "last_pull_message": manager.last_message,
            "last_pull_succeeded": manager.last_succeeded,
        }
        try:
            data = cache.current()
        except OperationalError:
            return render_template("analysis.html", analysis=None, db_error=True, **page), 503
        return render_template(
            "analysis.html",
            analysis=data,
            updated_at=cache.updated_at,
            db_error=False,
            **page,
        )

    @app.post("/pull-data", endpoint="pull_data")
    def pull_data_route():
        """Start a pull, or refuse with 409 while one is running."""
        if app.config["PULL_IN_BACKGROUND"]:
            if not manager.start(pull_job):
                return _busy_response()
            return jsonify(
                ok=True,
                busy=False,
                message=(
                    "Pull Data started. Grad Café is being checked for new results in the "
                    "background; this may take a little while."
                ),
            ), 202

        outcome = manager.run(pull_job)
        if outcome is None:
            return _busy_response()
        if not outcome.succeeded:
            return jsonify(ok=False, busy=False, error=outcome.message), 500
        return jsonify(ok=True, busy=False, added=outcome.added, message=outcome.message), 200

    @app.post("/update-analysis")
    def update_analysis():
        """Re-query the database, unless a pull is in progress (then do nothing)."""
        if manager.is_running():
            return _busy_response()
        try:
            data = cache.refresh()
        except OperationalError:
            return jsonify(ok=False, busy=False, error=DB_ERROR_MESSAGE), 503
        return jsonify(
            ok=True,
            busy=False,
            total_entries=data["total_entries"],
            message="Analysis updated using the latest data in the database.",
        ), 200

    @app.get("/applicants")
    def applicants():
        """JSON list of applicants, filtered and sorted by validated query-string values."""
        return _applicants_response(app.config["DATABASE_URL"], request.args)

    @app.get("/status")
    def status():
        """Current pull state for the page's progress banner."""
        return jsonify(
            running=manager.is_running(),
            message=manager.last_message,
            succeeded=manager.last_succeeded,
        )

    return app


if __name__ == "__main__":  # pragma: no cover  (only starts the dev server)
    create_app().run(debug=False)
