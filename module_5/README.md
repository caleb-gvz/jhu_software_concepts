# Module 5 — Software Assurance + Secure SQL (SQLi Defense)

**Name:** Caleb Gevertz  **JHED:** cgevert1
**Course:** Modern Software Concepts in Python, Johns Hopkins University
**Assignment:** Module 5 — Software Assurance + Secure SQL (SQLi Defense)

Module 5 hardens the Module 4 Flask + PostgreSQL Grad Cafe analysis app: lint-clean code
(Pylint 10/10), SQL injection defenses (psycopg SQL composition, parameter binding and an
enforced `LIMIT` on every query), environment-based credentials with a least-privilege
database user, a dependency graph, a reproducible pip/uv install, Snyk scans and a
GitHub Actions pipeline that enforces all of it.

## Fresh Install

Requirements: Python 3.10+ (3.12 is what CI uses), PostgreSQL 14+, and — only to regenerate the
dependency graph — [Graphviz](https://graphviz.org/download/) so that the `dot` command is on your PATH.
Run everything below from the `module_5/` folder. `requirements.txt` pins **every** package (runtime,
tooling and their transitive dependencies), so either method rebuilds the identical environment.

### Option 1 — pip + venv

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .           # puts src/ on the import path (see setup.py)
```

### Option 2 — uv

```bash
uv venv                              # creates .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
uv pip sync requirements.txt         # installs exactly what is listed -- nothing more, nothing less
uv pip install -e .
```

`uv pip sync` makes the environment match `requirements.txt` exactly (it also removes anything extra),
which is why the file is fully pinned. The short list of direct dependencies lives in
`requirements.in`; regenerate the pinned file after editing it with:

```bash
uv pip compile requirements.in --universal --python-version 3.12 -o requirements.txt
```

Both methods were verified in brand-new environments: the app imports and serves its page from a
different working directory, `pip check` reports no broken requirements, and a non-editable wheel
(`pip wheel . --no-deps`) also carries the templates and CSS.

### Configure the database connection

Credentials are never in the code. Copy the template and fill in real values (`.env` is git-ignored):

```bash
cp .env.example .env
```

| Variable | Used by | Meaning |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME` | app, CLI tools | Server location and database (defaults `localhost`, `5432`, `gradcafe`; this module uses `gradcafe_m5`) |
| `DB_USER`, `DB_PASSWORD` | app, CLI tools | The **least-privilege** role `gradcafe_m5_app` |
| `DB_OWNER_USER`, `DB_OWNER_PASSWORD` | `setup_db.*` only | The owner role that creates the schema |
| `TEST_DATABASE_URL` | tests | Owner-level URL of the scratch database `gradcafe_m5_test` |
| `TEST_APP_DATABASE_URL` | privilege tests | The app role's URL for the same scratch database |
| `DATABASE_URL` | optional | A full URL that replaces the five `DB_*` values (CI uses it) |

Real environment variables always override `.env`. The old `PG*` variables are intentionally ignored.

### Create the database roles (one time)

`src/setup_db.sh` (or double-click `src/setup_db.bat` on Windows) runs `src/db_setup.sql` as the
PostgreSQL superuser and prompts for that password (it is never stored). It reads the two role
passwords from `.env`. See *Least-privilege database* below for exactly what it creates.

## Running

```bash
# load the scraped data (schema must exist: see "Create the database roles")
python src/load_data.py                  # add --reset to empty the table first (needs the owner role)
python src/query_data.py                 # print the analysis answers using the composed-SQL layer
python src/orm_queries.py                # the same answers through SQLAlchemy

# the Flask app
cd src && flask --app flask_app run      # http://127.0.0.1:5000/analysis
```

Routes: `GET /analysis`, `POST /pull-data`, `POST /update-analysis`, `GET /status`, and the new read-only
`GET /applicants?term=&status=&sort=&direction=&limit=` (see *SQL injection defenses*).
Example: `curl "http://127.0.0.1:5000/applicants?term=fall%202026&status=accepted&sort=gpa&direction=desc&limit=5"`.

## Tests

```bash
pytest -m "web or buttons or analysis or db or integration"
```

`pytest.ini` enforces 100% coverage of `src/` (`--cov-fail-under=100`); the same command works from the
repository root as `pytest module_5 -m "..."`. The final summary is saved in `coverage_summary.txt`.
Tests that need the least-privilege role are skipped, with a stated reason, unless
`TEST_APP_DATABASE_URL` is set.

## SQL injection defenses

**Rule: SQL text is composed with `psycopg.sql`; values only ever travel as bound parameters.**

| Module 4 (before) | Module 5 (after) |
|---|---|
| `load_data.UPSERT_SQL` built with an f-string and `", ".join(COLUMNS)` | `UPSERT_STATEMENT` composed from `sql.SQL`, `sql.Identifier` (every column) and `sql.Placeholder` (every value) |
| Eleven analysis queries as raw strings with the filter values written into the text (`... = 'fall 2026'`, `ILIKE 'accept%'`) | `query_data.py` composes each from `sql.SQL`; table is `sql.Identifier("applicants")`; every filter value is a named placeholder (`%(term)s`, `%(accepted)s`, ...) bound from a dict |
| `SELECT p_id FROM applicants` read the whole table | Keyset-paginated, `LIMIT`-ed pages (`pull_data._known_ids`) |
| `fetch_applicants(limit=None)` returned every row | Always capped; the default is the maximum (100) |
| No endpoint accepted user input | New read-only `GET /applicants?term&status&sort&direction&limit`, built on `query_data.search_applicants` |

**Construction is separate from execution.** Every query follows the same two steps:

```python
statement = limited(query.statement)                  # build: a composed SQL object + "LIMIT %(limit)s"
cursor.execute(statement, limit_params(limit, query.params))   # run: statement and parameters apart
```

**What each kind of variable part does**

* *Values* (term, status, LIKE and regex patterns, the `LIMIT`): `sql.Placeholder` / `%(name)s`,
  filled from a parameter dict. `term` and `status` are compared with `=`, not `LIKE`, so a user's
  `%` or `_` is an ordinary character and cannot widen the match.
* *Identifiers* (table and column names): `sql.Identifier`. The only user-influenced identifier is the
  `sort` column, and it must first be an exact member of the `SORTABLE_COLUMNS` allow-list.
* *Direction* (`ASC`/`DESC`) is chosen from a boolean in code, never from request text.

**LIMIT on every query** (`src/sql_safety.py`)

* `limited(stmt)` appends `LIMIT %(limit)s` to every `SELECT`; the ORM path calls `.limit()` on every
  select. A test records every statement sent to PostgreSQL (raw psycopg *and* SQLAlchemy) and fails
  if any `SELECT` lacks a `LIMIT`.
* `clamp_limit()` keeps the value in **1..100** (`MIN_LIMIT`..`MAX_LIMIT`): `limit=99999999` becomes
  100, `0` and negatives become 1, and no limit means the default of 100. Something that is not a
  whole number (`abc`, `1; DROP TABLE applicants`, `2.5`, `1e3`) raises `ValueError`, which the endpoint
  turns into `400 Bad Request` with a fixed message that never echoes the input.
* Write statements (`INSERT ... ON CONFLICT`, `TRUNCATE`, `CREATE TABLE`) return no rows, so `LIMIT`
  does not apply to them; they carry only bound values (the upsert) or no values at all.

**Hostile input is tested, not assumed.** `tests/test_applicants_endpoint.py`,
`tests/test_query_data.py` and `tests/test_sql_safety.py` send payloads such as
`' OR '1'='1`, `'; DROP TABLE applicants; --`, `%`, `p_id; DROP TABLE applicants --` and `pg_sleep(5)` as
values, sort columns, directions and limits, and check there is no crash, no extra rows, no leaked data
and that the table is still intact. `tests/test_sql_composition_guard.py` parses every file in `src/`
and fails if any `execute()` / `executemany()` is ever given an f-string, `+`/`%` concatenation,
`.format()` or string literal.

## Dependency graph

`dependency.svg` is generated with pydeps and Graphviz. From `module_5/`, with `dot` on your PATH:

```bash
pydeps src/flask_app.py --noshow -T svg -o dependency.svg --max-module-depth=1
```

`--max-module-depth=1` collapses each third-party package (Flask, psycopg, SQLAlchemy) into a single node
so the picture shows how *this project's* modules relate instead of hundreds of Flask internals. pydeps
draws each arrow from a dependency to the module that imports it. CI regenerates the file on every push
and fails if it is missing or empty.

**Key dependencies, in 7 sentences.** `flask_app.py` is the entry point and sits at the bottom of the graph
because nearly everything flows into it. Flask and its helpers (Werkzeug for requests and routing, Jinja2
for the page template, plus click, itsdangerous, markupsafe and blinker) form the web layer. Data access has
two parallel paths: psycopg (with its compiled `psycopg_binary` driver) serves the raw-SQL modules
`query_data`, `load_data` and `pull_data`, while SQLAlchemy serves `models` and `orm_queries`, which feed the
analysis page. `db_config` is the single place both paths read the `DB_*` connection settings from the
environment, so five modules import it and no credentials appear anywhere else. The new `sql_safety` module
(built on `psycopg.sql`) is imported by `query_data`, `load_data`, `pull_data` and `orm_queries`, which is
how one clamp-and-bind `LIMIT` rule covers every query. `questions` holds the shared wording and formatting
so the SQL and ORM versions give identical answers, while `clean` and `scrape` feed `pull_data` (the Pull
Data button) under the supervision of `pull_manager`. Underneath it all, `typing_extensions` is a shared
low-level dependency of SQLAlchemy, psycopg and Flask's helpers, and there are no cycles: dependencies flow
in one direction toward the app.

## Static analysis: Pylint (10/10)

Pylint runs on every Python file under `src/` and nothing outside it. From `module_5/`
with the virtual environment active:

```bash
pylint src
```

Expected final line: `Your code has been rated at 10.00/10`. The saved output is in
`pylint_report.txt`. CI runs `pylint src --fail-under=10`, so any score below 10 fails the build.

Fixes were made in the code wherever possible (docstrings, shared helpers instead of
duplicated blocks, `functools.lru_cache` instead of a global, a context manager instead of
a bare `open`). The few remaining inline `# pylint: disable=...` comments each carry a
one-line justification: SQLAlchemy's dynamic `func` namespace (a known `not-callable`
false positive), the job-runner boundary that must catch every exception, declarative
models with no methods, the dependency-injection `create_app` factory, and two optional
LLM packages that are intentionally not installed.
