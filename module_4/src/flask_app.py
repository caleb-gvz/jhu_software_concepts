"""Flask front end for the Grad Cafe analysis.

Routes
------
GET  /                 Run every analysis question through the SQLAlchemy ORM and show the results.
POST /pull-data        Start ``pull_data.py`` in a background subprocess (never two at once).
POST /update-analysis  Re-read the database. Never starts a scrape and never disturbs a running one.
GET  /status           JSON the page polls to show pull progress and disable the Pull Data button.

All database reads go through ``orm_queries`` (the ``Applicant`` model); this module
contains no SQL. The scrape itself runs in a separate process managed by
``PullManager`` so the web page stays responsive during a long pull.

Run it with ``python app.py`` (or ``flask --app app run``) after setting the PG*
environment variables described in ``db_config.py``.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from flask import Flask, flash, jsonify, redirect, render_template, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import orm_queries
from models import Applicant, SessionLocal
from pull_manager import PullManager
from questions import display_label

MODULE_DIR = Path(__file__).resolve().parent


def _default_manager() -> PullManager:
    """A manager that runs pull_data.py with the same Python that runs the web app."""
    return PullManager(
        [sys.executable, str(MODULE_DIR / "pull_data.py")], cwd=str(MODULE_DIR)
    )


def _result_cards(session: Session) -> Dict[str, List[Dict[str, Any]]]:
    """Run all questions via the ORM and split them into assigned vs. original questions."""
    cards: Dict[str, List[Dict[str, Any]]] = {"assigned": [], "original": []}
    for question, lines in orm_queries.run_all(session):
        group = "original" if question.number.startswith("O") else "assigned"
        cards[group].append(
            {
                "label": display_label(question.number),
                "title": question.title,
                "question": question.question,
                "lines": lines,
            }
        )
    return cards


def create_app(
    manager: Optional[PullManager] = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> Flask:
    """Build the Flask app. Both collaborators can be replaced for testing."""
    app = Flask(__name__)
    # Only signs the flash-message cookie; a fresh random key per process is fine.
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(16)
    pull_manager = manager or _default_manager()

    @app.get("/")
    def analysis():
        page: Dict[str, Any] = {
            "pulling": pull_manager.is_running(),
            "last_pull_message": pull_manager.last_message,
            "last_pull_succeeded": pull_manager.last_succeeded,
            # Safe defaults so the template still renders if the database is unreachable.
            "cards": None,
            "total_entries": None,
        }
        try:
            with session_factory() as session:
                page["cards"] = _result_cards(session)
                page["total_entries"] = session.scalar(
                    select(func.count()).select_from(Applicant)
                )
        except OperationalError:
            return render_template("analysis.html", db_error=True, **page), 503
        return render_template("analysis.html", db_error=False, **page)

    @app.post("/pull-data")
    def pull_data():
        if pull_manager.is_running():
            flash(
                "A data pull is already running, so a second one was not started. "
                "Please wait for it to finish.",
                "warning",
            )
        elif pull_manager.start():
            flash(
                "Pull Data started. Grad Café is being checked for new results in the "
                "background; this may take a little while. This page will tell you when "
                "it finishes.",
                "info",
            )
        else:
            flash(
                pull_manager.last_message or "A data pull is already running.", "error"
            )
        return redirect(url_for("analysis"))

    @app.post("/update-analysis")
    def update_analysis():
        if pull_manager.is_running():
            flash(
                "New data is currently being retrieved. The analysis below shows what is "
                "in the database right now; click Update Analysis again once the pull "
                "has finished to include the new records.",
                "warning",
            )
        else:
            flash("Analysis updated using the latest data in the database.", "success")
        return redirect(url_for("analysis"))

    @app.get("/status")
    def status():
        return jsonify(
            running=pull_manager.is_running(),
            message=pull_manager.last_message,
            succeeded=pull_manager.last_succeeded,
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=False)
