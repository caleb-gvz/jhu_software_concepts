# Module 5 — Software Assurance + Secure SQL (SQLi Defense)

**Name:** Caleb Gevertz  **JHED:** cgevert1
**Course:** Modern Software Concepts in Python, Johns Hopkins University
**Assignment:** Module 5 — Software Assurance + Secure SQL (SQLi Defense)

Module 5 hardens the Module 4 Flask + PostgreSQL Grad Cafe analysis app: lint-clean code
(Pylint 10/10), SQL injection defenses (psycopg SQL composition, parameter binding and an
enforced `LIMIT` on every query), environment-based credentials with a least-privilege
database user, a dependency graph, a reproducible pip/uv install, Snyk scans and a
GitHub Actions pipeline that enforces all of it.

> Work in progress: this README is extended step by step as each requirement lands.

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
