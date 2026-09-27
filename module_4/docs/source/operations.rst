Operational notes
=================

Busy-state policy
-----------------

* At most one pull runs at a time. :meth:`pull_manager.PullManager.start` claims the
  busy flag under a lock before launching the job, so two quick clicks cannot start two
  scrapes. The second click gets ``409 {"busy": true}``.
* While a pull is running, **Update Analysis** also returns ``409 {"busy": true}`` and
  does not re-query, so the page never shows a half-loaded dataset. Once the pull
  finishes, the page says so and asks the user to click Update Analysis.
* A pull that raises (network, database, loader) is recorded as a failed outcome with a
  readable message, shown on the page and in ``GET /status``. The busy flag is always
  released.
* Pulls run on a daemon thread in the web process. If the server restarts, the pull
  stops. Rows are committed per batch, so a stopped pull never leaves a partial batch.

Idempotency strategy
--------------------

* Loading is an upsert: ``INSERT ... ON CONFLICT (p_id) DO UPDATE``. Re-running the
  loader, pulling the same page twice, or overlapping two pulls never duplicates a row.
* A conflict never overwrites an existing row's original fields. It may only fill LLM
  columns that are still empty (``COALESCE``), which lets the slow LLM step finish later.
* Each batch is loaded in one transaction. If the database rejects any row, the whole
  batch is rolled back.
* Invalid source records (null, not an object, missing or non-integer ``id``) are
  skipped. Each one is reported with its 1-based position, for example
  ``record #2: record is null``, and every usable record is still loaded.

Uniqueness keys
---------------

``p_id``, the Grad Café result id (``/result/<id>``), is the primary key and the only
uniqueness key. Before scraping, the pull asks the database for all known ids, so the
scraper stops at the first page that has nothing new.

Troubleshooting
---------------

``Could not connect to PostgreSQL`` / page shows "could not connect to the database"
   PostgreSQL is not running, or ``DATABASE_URL`` is wrong. Check it with
   ``psql "$DATABASE_URL" -c "select 1"``. On Windows, start the ``postgresql-x64-NN``
   service.

Database tests are skipped and coverage fails
   The scratch database is missing. Run ``src/setup_db.sh`` (or ``.bat``) once, or set
   ``TEST_DATABASE_URL`` to a database the tests may empty and refill.

``password authentication failed for user "gradcafe_app"``
   The role's password differs from the one in ``DATABASE_URL``. Re-run the setup
   script with ``GRADCAFE_APP_PASSWORD`` set to the password you want. The script is
   safe to re-run and resets the password.

Coverage reports ``No data to report`` or measures nothing
   pytest was started from a folder other than ``module_4`` or the repository root, so
   neither ``--cov`` path exists. Run ``pytest -m "..."`` from ``module_4`` or
   ``pytest module_4 -m "..."`` from the repository root.

``CoverageWarning: Module src was never imported`` (or ``module_4/src``)
   This is expected and harmless. ``pytest.ini`` lists both coverage paths so either
   run location works, and the path that does not exist from where you ran pytest
   triggers the warning.

``ModuleNotFoundError: flask_app`` (or another app module)
   pytest did not load ``module_4/pytest.ini``, whose ``pythonpath = src`` makes the
   app modules importable. Use one of the two commands above. To run a script by hand,
   ``cd src`` first or call ``python src/<script>.py``.

``psql`` not found by ``setup_db.*``
   Add PostgreSQL's ``bin`` folder to ``PATH``, or set ``PSQL`` to the full path of
   ``psql``.

CI: ``connection refused`` on port 5432
   The Postgres service container was not healthy yet. The workflow's
   ``--health-cmd pg_isready`` check normally prevents this, so re-run the job.

Pull Data reports "blocked or rejected the request (HTTP 403)"
   Grad Café refused the request, or ``robots.txt`` disallows the page. Whatever was
   fetched before the error is kept. Try again later. The analysis still works on the
   existing data.

Rows added by Pull Data have empty ``llm_generated_*`` columns
   This is expected. The local LLM is too slow to run inside a button click. Run
   ``python src/run_llm_standardization.py`` and then ``python src/load_data.py`` to
   fill them. The upsert only fills empty LLM columns.
