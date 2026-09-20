# Module 3 — Database Queries, SQLAlchemy, Flask: Design

Student: Caleb Gevertz (JHED: cgevert1). Source of requirements: `module 3 instructions.pdf`
(local only, never pushed). Baseline: Module 2 code and data copied into `module_3/`.

## Goal

Load the Module 2 Grad Café data into PostgreSQL, answer 9 assigned + 2 original
questions in raw SQL (psycopg 3), repeat 6 of them with SQLAlchemy 2.x, and serve the
results on a Flask page with **Pull Data** and **Update Analysis** buttons.

## Global constraints

- Python 3.10+ (developed on 3.14). Own `.venv` and `requirements.txt` for this module.
- Single table `applicants` with exactly the 14 columns in the assignment
  (`p_id integer PK`, text/date/float types as specified).
- No credentials in the repo: connection settings come from `PGHOST`, `PGPORT`,
  `PGDATABASE`, `PGUSER`, `PGPASSWORD` (defaults: localhost / 5432 / gradcafe).
  Only a secret-free `.env.example` is committed.
- Output formatting everywhere (console, PDF, Flask): counts are whole numbers,
  percentages `NN.NN%`, averages 2 decimals. One shared module (`formatting.py`).
- `orm_queries.py` must not use `text()` or a raw cursor.
- Flask reads use the SQLAlchemy `Applicant` model.
- `CLAUDE.md` files are not tracked. The instructions PDF is never pushed.
- Commit small and push to `origin/main` after each milestone.

## Data mapping (Module 2 JSON → `applicants`)

| JSON field | Column |
|---|---|
| `id` | `p_id` (PK; Grad Café result id) |
| `program` ("Program, University") | `program` |
| `comments` | `comments` |
| `date_added_raw` (ISO) | `date_added` |
| `url` | `url` |
| `applicant_status` | `status` |
| `term` | `term` |
| `us_or_international` | `us_or_international` |
| `gpa` / `gre_score` / `gre_v` / `gre_aw` | `gpa` / `gre` / `gre_v` / `gre_aw` |
| `degree` | `degree` |
| `llm-generated-program` / `-university` | `llm_generated_program` / `_university` |

Blank strings become NULL. Out-of-range scores become NULL so bad entries cannot
distort averages: GPA outside (0, 4.33], GRE Quant/Verbal outside 130–170, GRE AW
outside (0, 6]. Grad Café reports 0.0 for "not provided" (35,263 of 40,000 rows have a writing score of 0), so zeros are missing. Nationality other than American/International/Other (847 rows hold a literal "0") becomes NULL. The loader is idempotent: `INSERT … ON CONFLICT (p_id) DO UPDATE` only
fills empty LLM columns (`COALESCE`); every other column of an existing row is left
untouched, so reloading or pulling never overwrites usable data.

## LLM standardization scope

40,000 records; 5,000 already have LLM fields. Q9 filters on original term, status and
degree, so only rows with **Fall 2026 + accepted + PhD** (6,051 rows, 5,398 not yet
enriched) can change Q8/Q9. Those run **first** (~1.2 h), then the remaining rows
continue in background shards (4 processes × 3 threads) and the loader is re-run as
they finish. The driver is resumable: it skips ids already present in any output.
Rows Pull Data adds later have NULL LLM fields (known limitation, documented).

## Components

| File | Responsibility |
|---|---|
| `run_llm_standardization.py` | Prioritised, resumable, sharded LLM run; merges into `llm_extend_applicant_data.json` |
| `db_config.py` | Env-based `connect()` (psycopg) and `sqlalchemy_url()` |
| `formatting.py` | `fmt_count`, `fmt_percent`, `fmt_average`, `fmt_signed_difference` |
| `load_data.py` | Create table, map/sanitise records, idempotent upsert, CLI |
| `query_data.py` | Q1–Q9 + 2 original questions as data (`QUERIES`) + `run_all()` + console output |
| `models.py` | `Applicant` (SQLAlchemy 2.x `Mapped`), engine, `SessionLocal` |
| `orm_queries.py` | ORM versions of Q1, 4, 5, 8, 9 and original Q1; console output |
| `scrape.py` (+`scrape_new_records`) | Module 2 scraper, extended to fetch newest pages until known ids |
| `pull_data.py` | CLI run in a subprocess: known ids from DB → scrape new → clean → upsert |
| `pull_manager.py` | `PullManager`: at most one running subprocess, status text |
| `app.py`, `templates/analysis.html`, `static/style.css` | Flask page, `/pull-data`, `/update-analysis`, `/status` |
| `make_pdfs.py` | Build `query_results.pdf` from live results; `limitations.pdf` |
| `README.md`, `requirements.txt`, `github.txt`, screenshots, `module_3.zip` | Submission |

## Query semantics

- Term match: `LOWER(TRIM(term)) = 'fall 2026'`. Acceptance: `status ILIKE 'accept%'`.
- Q2 denominator: rows whose `us_or_international` is non-blank (American, International,
  Other); numerator: `international` only.
- Q3/Q4/Q6 averages use only rows where that metric is not NULL (`AVG` ignores NULL).
- Q7/Q8: original `program` (contains "Program, University") and `degree`
  (`Masters`, `PhD`). Q9: `llm_generated_program/university` + original term/degree/status.
- Q9 also reports the Q8 count and the signed difference (`+3`).
- Original questions: (1) Fall 2026 acceptance rate by nationality group;
  (2) average GPA / GRE Quant of accepted vs rejected Fall 2026 applicants (feeds the
  limitations essay).

## Flask behaviour

`GET /` renders all results via ORM functions. `POST /pull-data` starts `pull_data.py` in a
subprocess unless one is running (then flashes "already running"). `POST /update-analysis`
only re-queries; if a pull is running it flashes "New data is currently being retrieved"
and does not touch the subprocess. `GET /status` returns JSON the page polls to disable
Pull Data and show progress. Scraper errors (e.g. Cloudflare 403) are surfaced as
user-facing messages.

## Testing

pytest, TDD. Pure logic (formatting, record mapping, sanitising, shard planning,
pull manager) is unit-tested with no database. DB-backed tests (loader idempotency,
raw-SQL vs ORM parity, Flask routes) run against a scratch `gradcafe_test` database and
skip cleanly when PostgreSQL is unreachable.

## Known risks

Cloudflare may block Pull Data (handled with a clear message); PostgreSQL must be installed
by the user; the full LLM pass may not finish before the deadline (reported in the README).
