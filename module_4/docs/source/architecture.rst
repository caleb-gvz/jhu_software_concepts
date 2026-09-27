Architecture
============

The service has three layers. Each has one job, and the layers talk only through the
small interfaces described here, so each one can be tested on its own.

.. code-block:: text

   Browser ──HTTP──▶ Web layer (flask_app.py, templates/, static/)
                        │  create_app(config, scraper=, loader=, query_fn=, ...)
                        │
            ┌───────────┴─────────────┐
            ▼                         ▼
   PullManager (pull_manager.py)   AnalysisCache ──▶ orm_queries.get_analysis()
   one pull at a time, busy flag        │                (SQLAlchemy, models.py)
            │                           │
            ▼                           ▼
   ETL layer: pull_data.run_pull()    DB layer: PostgreSQL "applicants" table
     scrape.scrape_new_records()  ──▶   load_data.load_records()  (psycopg 3)
     clean.clean_data()                 query_data.py             (raw SQL)

Web layer
---------

``flask_app.py`` exposes the ``create_app(...)`` factory. The factory owns two objects:

* a :class:`pull_manager.PullManager`, which runs at most one pull at a time and keeps
  the busy state that decides whether a request gets a 409;
* an :class:`flask_app.AnalysisCache`, the analysis snapshot the page renders.
  ``POST /update-analysis`` replaces the snapshot.

Routes:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Route
     - Behaviour
   * - ``GET /analysis`` (and ``/``)
     - Renders ``templates/analysis.html`` from the current snapshot, computing it on
       first use. Returns 503 with a friendly message if the database is unreachable.
   * - ``POST /pull-data``
     - When idle: starts a pull and returns ``202 {"ok": true}`` (background, the
       production default), or ``200 {"ok": true, "added": n}`` when
       ``PULL_IN_BACKGROUND`` is ``False``, as it is in the tests. While busy: ``409
       {"busy": true}``. If the pull fails: ``500 {"ok": false, "error": ...}``.
   * - ``POST /update-analysis``
     - When idle: re-runs the queries and returns ``200 {"ok": true}``. While a pull is
       running: ``409 {"busy": true}``, and the snapshot is left unchanged.
   * - ``GET /status``
     - JSON ``{"running", "message", "succeeded"}``. The page polls it to show pull
       progress.

The page's buttons submit with ``fetch()``, read the JSON reply, and show a message.
The page runs no SQL; every read goes through the ORM.

ETL layer
---------

* **Extract**: :func:`scrape.scrape_new_records` reads the newest Grad Café survey
  pages. It stops at the first page with nothing new, checks ``robots.txt``, and raises
  :class:`scrape.ScrapeError` with any partial results when it is blocked or offline.
  The Module 2 full scrape (:func:`scrape.scrape_data`) is still available.
* **Transform**: :func:`clean.clean_data` collapses whitespace and coerces numbers.
  :func:`load_data.record_to_row` maps a record to the table columns and treats
  impossible scores and Grad Café's ``0.0`` placeholders as missing.
* **Load**: :func:`load_data.load_records` validates every record first
  (:func:`load_data.validate_record`). Null or malformed records are skipped and
  reported by position. The usable rows are upserted in **one transaction**.

:func:`pull_data.run_pull` ties the steps together for the Pull Data button. Its
scraper and loader are parameters, so the app factory and the tests can inject fakes.

Database layer
--------------

One table, ``applicants``, with the Module 3 schema. It is unchanged in Module 4:

.. code-block:: sql

   p_id INTEGER PRIMARY KEY, program TEXT, comments TEXT, date_added DATE, url TEXT,
   status TEXT, term TEXT, us_or_international TEXT, gpa FLOAT, gre FLOAT, gre_v FLOAT,
   gre_aw FLOAT, degree TEXT, llm_generated_program TEXT, llm_generated_university TEXT

* ``db_config.py`` turns ``DATABASE_URL`` into a psycopg connection
  (:func:`db_config.connect`) or a SQLAlchemy URL (:func:`db_config.sqlalchemy_url`),
  so the raw-SQL and ORM code always use the same database.
* ``models.py`` maps the table as the SQLAlchemy ``Applicant`` model.
* ``query_data.py`` answers the questions in raw SQL and ``orm_queries.py`` answers them
  through the ORM. Both hand their rows to the same ``questions.py`` renderers and the
  same ``formatting.py`` rules, so the two produce identical output.
