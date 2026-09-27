# Module 4: Pytest and Sphinx (Grad Café Analytics)

**Name:** Caleb Gevertz (JHED: cgevert1)
**Course:** Modern Software Concepts in Python, Johns Hopkins University
**Assignment:** Module 4, Testing and Documentation

| | |
|---|---|
| Repository (SSH) | `git@github.com:caleb-gvz/jhu_software_concepts.git` (also in `github.txt`) |
| Documentation (Read the Docs) | <https://jhu-software-concepts.readthedocs.io/en/latest/> |
| Documentation (built HTML in this folder) | [`docs/_build/html/index.html`](docs/_build/html/index.html) |
| CI workflow | [`../.github/workflows/tests.yml`](../.github/workflows/tests.yml), green run in `actions_success.png` |
| Coverage proof | [`coverage_summary.txt`](coverage_summary.txt) (100% of `src/`) |

Module 4 takes the Module 3 Grad Café app (a Flask analysis page, the ETL pipeline and
PostgreSQL) and adds:

* an automated **pytest** suite with **100% coverage** of `src/`;
* a **GitHub Actions** pipeline that starts PostgreSQL and runs that suite;
* **Sphinx** documentation, published on Read the Docs.

## Layout

```
module_4/
  src/            application code: flask_app.py, scrape.py, clean.py, load_data.py,
                  query_data.py, orm_queries.py, models.py, db_config.py, pull_data.py,
                  pull_manager.py, templates/, static/, llm_hosting/, data files
  tests/          every test (+ conftest.py fixtures, doubles.py test doubles, fixtures/)
  docs/           Sphinx project: source/ (conf.py + pages) and _build/html/ (built site)
  pytest.ini      markers + coverage gate      .coveragerc   coverage settings
  requirements.txt  README.md  coverage_summary.txt  actions_success.png  github.txt
```

## Setup

Requires Python 3.10+ and PostgreSQL 14+. It was developed on Windows 11 with Python 3.14
and PostgreSQL 18; CI uses Ubuntu with Python 3.12 and PostgreSQL 16.

```bash
cd module_4
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt        # app + tests + coverage + Sphinx

cp .env.example .env                   # git-ignored; set DATABASE_URL and GRADCAFE_APP_PASSWORD
```

**Configure PostgreSQL.** Do this once. It creates the `gradcafe_app` role and the
`gradcafe` and `gradcafe_test` databases. You will be asked for the postgres superuser
password, and no secret is stored:

```bash
bash src/setup_db.sh                   # Windows: double-click src\setup_db.bat
# or: psql -U postgres -f src/db_setup.sql  (with GRADCAFE_APP_PASSWORD exported)
```

**Environment variables:**

- `DATABASE_URL` (required), e.g. `postgresql://gradcafe_app:<password>@localhost:5432/gradcafe`.
- `TEST_DATABASE_URL` (optional): the scratch database the tests empty and refill. It
  defaults to `DATABASE_URL` with the database name replaced by `gradcafe_test`.
- The Module 3 `PG*` variables still work as a fallback when `DATABASE_URL` is unset.

**Load the data.** This is safe to re-run; `--reset` rebuilds the table:

```bash
python src/load_data.py
```

## Run the Flask app

```bash
cd src
python flask_app.py                    # or: flask --app flask_app run
# http://127.0.0.1:5000/analysis
```

- **Pull Data** fetches new Grad Café entries in the background. This needs internet
  access, and only one pull can run at a time.
- **Update Analysis** re-runs the queries. While a pull is running, both buttons answer
  `409 {"busy": true}` and do nothing.

## Run the tests

```bash
cd module_4
pytest -m "web or buttons or analysis or db or integration"
```

This runs the entire suite: 247 tests in about 20 seconds, with no network access and
no `sleep()`. It fails if coverage of `src/` drops below 100%. Run it from `module_4`,
because `--cov=src` and `pythonpath = src` are relative to that folder. The database
tests use `gradcafe_test` (or `TEST_DATABASE_URL`).

## View or rebuild the documentation

- Online: the Read the Docs link above.
- Offline: open `docs/_build/html/index.html`.
- Rebuild: `sphinx-build -b html docs/source docs/_build/html`.

The docs cover setup, architecture (web / ETL / DB), an API reference (autodoc for
`scrape`, `clean`, `load_data`, `query_data`, `flask_app` and more), a testing guide
(markers, selectors, fixtures, test doubles), and operational notes with a
troubleshooting section.

## Approach

### Restructuring for testability (`src/`)
- **App factory.** `create_app(config, *, scraper, loader, query_fn, session_factory,
  pull_manager)` builds the app. Every collaborator can be injected, so tests pass a
  `FakeScraper`, a `SpyLoader` / `FailingLoader`, or a fake query without touching the
  network. `config` can override `DATABASE_URL` and `PULL_IN_BACKGROUND`.
- **Routes.** `GET /analysis` renders an analysis snapshot. `POST /pull-data` and
  `POST /update-analysis` return JSON, and the page's buttons call them with `fetch()`
  and show the reply.
  - `POST /pull-data`: `202 {"ok": true}` in the background, `200` with the result when
    synchronous, `409 {"busy": true}` while busy, `500 {"ok": false}` on failure.
  - `POST /update-analysis`: `200 {"ok": true}` after re-querying, `409 {"busy": true}`
    with no update while a pull runs.
- **Busy state is observable.** `PullManager` now runs the pull job on a thread instead of
  a subprocess. It keeps a lock-protected busy flag (`is_running()`) and offers `start()`
  (background) and `run()` (synchronous, used by the tests). Tests hold a pull open on a
  `threading.Event`, never with `sleep()`.
- **Selectors and labels.** The template has stable `data-testid` selectors
  (`pull-data-btn`, `update-analysis-btn`, `analysis-card`, `answer`, ...) and prefixes
  every result line with an `Answer:` label.
- **Configuration.** `db_config.database_url()` reads `DATABASE_URL`, then `.env`, then
  the `PG*` fallback. `connect(url)` and `sqlalchemy_url(url)` accept an explicit URL,
  which is how the app factory and the tests override it.
- **Query functions.** `orm_queries.get_analysis(session)` returns the exact dictionary
  the template renders (`total_entries`, `assigned`, `original`; each card has `number`,
  `label`, `title`, `question`, `answers`). `query_data.fetch_applicants(conn)` returns
  rows as dicts keyed by the Module 3 columns.
- **Unchanged schema.** The Module 3 schema and the formatting rules are unchanged:
  counts are whole numbers, and percentages and averages have two decimals.

### Fix from the Module 3 review
The review found that the loader's JSON/LLM merge path crashed with an uncaught
`TypeError` when it met a `null` record. The fix has four parts:

- `load_data.validate_record()` checks every record: it must be a JSON object with a
  positive integer `id` that fits the INTEGER key.
- `load_records()` skips unusable records and returns a `LoadResult` whose `rejected`
  list gives each one's position and reason (`record #2: record is null`). All valid
  records are still loaded.
- `merge_llm_fields()` and `clean_data()` pass invalid records through instead of
  raising. `load_data.py` prints the skipped rows and exits 0 after loading the rest.
  Missing, invalid or non-list JSON files produce a readable error instead of a traceback.
- Each batch is written in **one transaction**. If the database rejects a row, the whole
  batch rolls back, so there are no partial writes. A failed pull returns 500.

Tests: `test_db_insert.py::test_a_null_record_is_reported_and_the_valid_ones_still_load`,
`..._in_the_llm_merge_path_do_not_raise`, and `..._command_line_load_reports_the_bad_row...`.

### Test suite design
- **Required files.** `test_flask_page.py`, `test_buttons.py`, `test_analysis_format.py`,
  `test_db_insert.py` and `test_integration_end_to_end.py`. The Module 3 tests were kept
  and extended.
- **Markers.** Every test has a marker (`web`, `buttons`, `analysis`, `db` or
  `integration`). `conftest.py` stops the run if a collected test has none, so
  `pytest -m "web or buttons or analysis or db or integration"` always runs everything.
- **HTML assertions** use BeautifulSoup and the `data-testid` selectors. Percentages are
  checked with the regex `\d[\d,]*\.\d{2}%` against every `...%` token on the page.
- **Database tests** run against a real PostgreSQL scratch database. Fixtures empty it
  before each test, and they check the schema, inserts, idempotency, and dictionary keys.
- **Hard-to-reach code** such as the scraper's network helpers, every command-line
  `main()`, and the instructor's LLM host is covered with fakes: a fake `urlopen`, fake
  `llama_cpp` / `huggingface_hub` modules, and a patched `subprocess.Popen`. No live
  network, model or subprocess is involved.
- **Coverage exclusion.** The only line excluded from coverage is the
  `if __name__ == "__main__":` guard, which only calls `main()`. `main()` itself is
  tested directly (see `.coveragerc`).

### CI
`.github/workflows/tests.yml` is at the repository root. It:

1. starts a `postgres:16` service with a health check;
2. sets `DATABASE_URL` / `TEST_DATABASE_URL`;
3. installs `module_4/requirements.txt` on Python 3.12;
4. runs the marked pytest command with the 100% gate from `module_4`.

## Packaging for Canvas
`python src/make_zip.py` writes `module_4.zip`. It contains the `module_4` folder and the
repository's `.github/workflows/tests.yml`, and leaves out virtual environments, caches
(`__pycache__`, `.pytest_cache`, `.coverage`, `htmlcov`), `.env`, the instructions PDF,
the LLM model, and LLM work files.

## Known bugs and limitations
- **Single process only.** Pulls run on a thread inside the web process, so the busy flag
  assumes one Flask process (the built-in server). With several worker processes, each
  would have its own flag. A restart stops a running pull; committed batches are kept.
- **No LLM fields for pulled rows.** Rows added by Pull Data have empty `llm_generated_*`
  columns, because the local LLM is too slow for a button click. Running
  `src/run_llm_standardization.py` and then `src/load_data.py` fills them.
- **Pull size limit.** Pull Data reads at most the 20 newest survey pages (~400 entries)
  per click, and stops (keeping what it fetched) if Grad Café blocks the request.
- **Run location.** `pytest` must be run from `module_4`. The assignment's example
  `pytest.ini` uses `--cov=module_4/src`, which only works from the repository root. I
  used `--cov=src` so the documented `cd module_4 && pytest ...` command, the CI workflow
  and the docs all agree.
- **Platform testing.** Tested locally on Windows and in CI on Ubuntu.
