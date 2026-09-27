Testing guide
=============

How to run the tests
--------------------

From the ``module_4`` folder:

.. code-block:: bash

   pytest -m "web or buttons or analysis or db or integration"   # the full suite
   pytest -m web                     # only page-rendering tests
   pytest -m "buttons or integration"
   pytest tests/test_buttons.py -k busy --no-cov   # one area, without the coverage gate

``pytest.ini`` adds ``--cov=module_4/src --cov=src --cov-report=term-missing
--cov-fail-under=100``, so a full run fails unless every line under ``src/`` is covered.
Both coverage paths are listed so the same command works from ``module_4`` and, as
``pytest module_4 -m "..."``, from the repository root. Coverage prints a harmless
"never imported" warning for whichever path does not exist from where you ran it. The
only lines excluded from coverage are the ``if __name__ == "__main__":`` guards
(``# pragma: no cover``), which only call a ``main()`` that is tested directly. The suite takes
about 20 seconds. It never contacts Grad Café and never calls ``sleep()``.

Database-backed tests use a scratch database: ``TEST_DATABASE_URL``, or else
``DATABASE_URL`` with the database name replaced by ``gradcafe_test``. The tests
empty that database and refill it. If it cannot be reached, those tests are skipped
and the coverage gate then fails, so a green run always includes them.

Markers
-------

Every test has at least one marker. ``tests/conftest.py`` enforces this at collection
time and stops the run with an error if any test is unmarked.

.. list-table::
   :header-rows: 1
   :widths: 16 34 50

   * - Marker
     - Meaning
     - Files
   * - ``web``
     - page load / HTML structure
     - ``test_flask_page.py``
   * - ``buttons``
     - Pull Data / Update Analysis endpoints and busy state
     - ``test_buttons.py``
   * - ``analysis``
     - "Answer:" labels and two-decimal percentages
     - ``test_analysis_format.py``, ``test_formatting.py``, ``test_make_pdfs.py``
   * - ``db``
     - schema, inserts, selects, and the ETL that feeds them
     - ``test_db_insert.py``, ``test_load_data.py``, ``test_query_data.py``,
       ``test_orm_parity.py``, ``test_pull_data.py``, ``test_db_config.py``,
       ``test_scrape*.py``, ``test_clean.py``, ``test_command_line.py``,
       ``test_llm_hosting.py``, ``test_run_llm_standardization.py``
   * - ``integration``
     - end-to-end flows
     - ``test_integration_end_to_end.py``, ``test_make_zip.py``

What the required test files check
----------------------------------

``test_flask_page.py``
   ``create_app`` returns a Flask app with every route. ``GET /analysis`` returns 200.
   The page has both buttons, the text "Analysis", and at least one "Answer:". It also
   shows the busy banner, the last pull's outcome, and a 503 page when the database is
   down.
``test_buttons.py``
   ``POST /pull-data`` returns 200/202 with ``{"ok": true}`` and passes the scraper's rows
   to the loader. ``POST /update-analysis`` returns 200 and re-queries. While a pull is
   in progress, both POSTs return ``409 {"busy": true}`` and do nothing. Error paths:
   when the loader fails, the response is 500 and nothing is written; a blocked scrape
   and an unreachable database are reported rather than raised.
``test_analysis_format.py``
   Every rendered result line is labelled "Answer:". Every percentage on the page
   matches ``\d[\d,]*\.\d{2}%``, on both fake and real data. A companion test shows the
   checker rejects ``39%``, ``39.2%`` and ``39.283%``.
``test_db_insert.py``
   The table is empty before ``POST /pull-data``; afterwards the rows exist with the
   Module 3 schema and non-null required fields. Pulling or loading the same data twice
   adds no rows. ``fetch_applicants`` and ``get_analysis`` return dicts with the expected
   keys. A null record is reported and the valid records still load (the fix for the
   Module 3 review).
``test_integration_end_to_end.py``
   With a fake scraper returning several records: pull, then update, then render. The
   page shows the new numbers, correctly formatted. Two pulls with overlapping records
   keep exactly one row per ``p_id``.

Stable selectors
----------------

UI tests find elements by ``data-testid`` with BeautifulSoup, never by position or
styling:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Selector
     - Element
   * - ``[data-testid="pull-data-btn"]``
     - the Pull Data ``<button>`` (inside a form posting to ``/pull-data``)
   * - ``[data-testid="update-analysis-btn"]``
     - the Update Analysis ``<button>`` (form posting to ``/update-analysis``)
   * - ``[data-testid="page-title"]``
     - the page heading (contains "Analysis")
   * - ``[data-testid="analysis-card"]``
     - one question; ``data-question`` holds its number (``1``..``9``, ``O1``, ``O2``)
   * - ``[data-testid="answer"]``
     - one result line; its ``.answer-label`` child reads ``Answer:``
   * - ``[data-testid="total-entries"]``
     - the entry count in the header
   * - ``[data-testid="pull-banner"]``
     - "new data is being retrieved" banner (``hidden`` when idle)
   * - ``[data-testid="last-pull"]``
     - outcome of the most recent pull
   * - ``[data-testid="db-error"]``
     - shown instead of the analysis when the database is unreachable

Fixtures (``tests/conftest.py``)
--------------------------------

``db_url`` (session)
   URL of the scratch database; skips database tests if it is unreachable.
``test_conn``
   A psycopg connection to the scratch database with an empty ``applicants`` table.
``make_app``
   Factory: ``make_app(config=None, **create_app_kwargs)``. It builds a test app bound
   to the scratch database with ``PULL_IN_BACKGROUND=False``, so ``POST /pull-data``
   finishes before the response returns. At teardown it waits for any background pull.

Test doubles (``tests/doubles.py``)
-----------------------------------

``make_record(id, **overrides)``
   A record shaped exactly like the scraper's output.
``FakeScraper(*batches)``
   Replaces the Grad Café scraper. Call *n* returns batch *n*, and the ``known_ids`` of
   every call is recorded.
``BlockingScraper``
   A FakeScraper that waits on ``threading.Event`` objects (``started`` /
   ``release``). It keeps a background pull "in progress" while a test checks the 409
   behaviour, which is deterministic and needs no ``sleep()``.
``SpyLoader``
   Wraps the real loader and records every batch it receives.
``FailingLoader``
   Writes one row without committing, then raises. Used to show that a failed pull
   leaves no partial writes.
``SpyQuery`` / ``fake_analysis()`` / ``NullSession``
   Replace ``orm_queries.get_analysis`` and the database session, so page tests need no
   database.

The local LLM (``src/llm_hosting``) is tested with fake ``llama_cpp`` and
``huggingface_hub`` modules installed into ``sys.modules``. No model is downloaded.

Continuous integration
----------------------

``.github/workflows/tests.yml`` (at the repository root) starts a ``postgres:16``
service container, installs ``module_4/requirements.txt`` on Python 3.12, sets
``DATABASE_URL`` / ``TEST_DATABASE_URL`` to the container, and runs the same marked
pytest command with the coverage gate.
