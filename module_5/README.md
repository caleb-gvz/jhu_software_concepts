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
