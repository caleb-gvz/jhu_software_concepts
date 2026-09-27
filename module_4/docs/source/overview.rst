Overview and setup
==================

What the service does
---------------------

* **Pull Data** fetches the newest Grad Café survey entries that are not yet in the
  database, cleans them, and inserts them into the ``applicants`` table in PostgreSQL.
* **Update Analysis** re-runs the eleven analysis questions (nine assigned, two
  original) through SQLAlchemy and refreshes the page.
* The analysis page (``GET /analysis``) shows every answer as an ``Answer:`` line.
  Counts are whole numbers, and every percentage and average has exactly two decimals.

Requirements
------------

* Python 3.10 or newer (developed on 3.14; CI runs 3.12)
* PostgreSQL 14 or newer (developed on 18; CI runs 16)
* Everything else is in ``module_4/requirements.txt``: Flask, psycopg 3, SQLAlchemy 2,
  BeautifulSoup, pytest and pytest-cov, and Sphinx.

Folder layout
-------------

.. code-block:: text

   module_4/
     src/              application code: Flask app, ETL (scrape/clean/load), queries
       templates/  static/  llm_hosting/  applicant_data.json  ...
     tests/            the whole pytest suite (plus doubles.py and fixtures/)
     docs/             this Sphinx project (source/ and the built _build/html/)
     pytest.ini        markers + coverage gate
     .coveragerc       coverage settings
     requirements.txt
     README.md
     coverage_summary.txt

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Variable
     - Meaning
   * - ``DATABASE_URL``
     - **Required.** The PostgreSQL URL used by the web app, the loader and the query
       scripts, e.g. ``postgresql://gradcafe_app:<password>@localhost:5432/gradcafe``.
   * - ``TEST_DATABASE_URL``
     - Optional. The scratch database the tests may empty and refill. Default:
       ``DATABASE_URL`` with the database name replaced by ``gradcafe_test``.
   * - ``FLASK_SECRET_KEY``
     - Optional. Signs Flask's session cookie; a random key is generated if unset.
   * - ``GRADCAFE_APP_PASSWORD``
     - Used only by ``src/setup_db.*`` to create the ``gradcafe_app`` role.
   * - ``PGHOST`` ``PGPORT`` ``PGDATABASE`` ``PGUSER`` ``PGPASSWORD``
     - Legacy fallback from Module 3, used only when ``DATABASE_URL`` is not set.

The variables can be exported in the shell or placed in ``module_4/.env``, which is
git-ignored. Real environment variables always take priority over ``.env``. Copy
``.env.example`` to start.

Setting up
----------

.. code-block:: bash

   cd module_4
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt

   cp .env.example .env               # then edit DATABASE_URL and GRADCAFE_APP_PASSWORD

   # One time: create the gradcafe_app role and the gradcafe + gradcafe_test databases.
   # Prompts for the postgres superuser's password; nothing is stored.
   bash src/setup_db.sh               # Windows: double-click src\setup_db.bat
   # (or: psql -U postgres -f src/db_setup.sql with GRADCAFE_APP_PASSWORD exported)

   # Load the Module 2 data (about 40,000 rows). Safe to re-run; --reset reloads.
   python src/load_data.py

Running the app
---------------

.. code-block:: bash

   cd module_4/src
   python flask_app.py                # or: flask --app flask_app run
   # open http://127.0.0.1:5000/analysis

Pull Data needs internet access because it contacts Grad Café, and it respects
``robots.txt``. Nothing else needs the network.

Other command-line tools (all in ``src/``):

* ``python query_data.py`` prints the answers using raw SQL (psycopg).
* ``python orm_queries.py`` prints the same answers using the SQLAlchemy ORM.
* ``python pull_data.py`` does one pull from the command line.
* ``python make_pdfs.py`` rebuilds the Module 3 PDF reports.
* ``python make_zip.py`` builds ``module_4.zip`` for Canvas, without venvs, caches or
  secrets.

Running the tests
-----------------

.. code-block:: bash

   cd module_4
   pytest -m "web or buttons or analysis or db or integration"

This runs the entire suite (every test carries one of those markers) and enforces 100%
coverage of ``src/``. See :doc:`testing` for details.

Building these docs
-------------------

.. code-block:: bash

   cd module_4
   sphinx-build -b html docs/source docs/_build/html

The published copy is on Read the Docs; the link is in the repository README.
