API reference
=============

Generated from the docstrings in ``module_4/src``.

Web layer: ``flask_app``
------------------------

.. automodule:: flask_app
   :members: create_app, AnalysisCache

ETL: ``scrape``
---------------

.. automodule:: scrape
   :members: scrape_new_records, scrape_data, ScrapeError, main
   :private-members: _parse_record, _extract_page_records, _merge_robots_groups

ETL: ``clean``
--------------

.. automodule:: clean
   :members:

ETL: ``load_data``
------------------

.. automodule:: load_data
   :members:

Pull Data: ``pull_data`` and ``pull_manager``
---------------------------------------------

.. automodule:: pull_data
   :members:

.. automodule:: pull_manager
   :members:

Queries: ``query_data`` (raw SQL)
---------------------------------

.. automodule:: query_data
   :members: fetch_applicants, run_query, run_all, get_query, Query, main

Queries: ``orm_queries`` (SQLAlchemy)
-------------------------------------

.. automodule:: orm_queries
   :members: get_analysis, run_query, run_all, main, ANALYSIS_KEYS, CARD_KEYS

Database: ``models`` and ``db_config``
--------------------------------------

.. automodule:: models
   :members: Applicant, make_engine, make_session_factory, get_session
   :exclude-members: metadata, registry

.. automodule:: db_config
   :members:

Shared: ``questions`` and ``formatting``
----------------------------------------

.. automodule:: questions
   :members: Question, QUESTIONS, get_question, display_label

.. automodule:: formatting
   :members:
