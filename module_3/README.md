Name: Caleb Gevertz (JHED: cgevert1)
Module Info: Module 3 — Database Queries, SQLAlchemy, and Dynamic Webpages
(Modern Software Concepts in Python, Johns Hopkins University)

Repository: private GitHub repo `jhu_software_concepts`, folder `module_3/`
(SSH URL is in `github.txt`).

---

## 1. What this module does

The Module 2 Grad Café data (40,000 scraped entries plus LLM-standardized program /
university fields) is loaded into PostgreSQL, analysed with **raw SQL (psycopg 3)** and
again with **SQLAlchemy 2.x**, and displayed on a **dynamic Flask page** whose
**Pull Data** button re-runs the Module 2 scraper to add newly posted entries.

| File | Purpose |
|---|---|
| `load_data.py` | Creates the `applicants` table and loads the cleaned data (idempotent upsert) |
| `query_data.py` | Questions 1–9 + two original questions, in SQL (psycopg) |
| `models.py` | SQLAlchemy 2.x `Applicant` model, Engine and Session factory |
| `orm_queries.py` | The same questions with SQLAlchemy (no raw SQL, no cursor) |
| `questions.py` | Question wording + result formatting shared by SQL and ORM code |
| `formatting.py` | Count / percent / average formatting rules from the assignment |
| `db_config.py` | Connection settings from environment variables (never from code) |
| `app.py`, `templates/`, `static/` | Flask app, HTML template, CSS |
| `pull_data.py`, `pull_manager.py` | Pull Data: the subprocess command and the one-at-a-time runner |
| `scrape.py`, `clean.py` | Module 2 scraper and cleaner (reused; `scrape_new_records` added) |
| `run_llm_standardization.py`, `llm_hosting/` | Module 2 LLM standardizer, now prioritised/sharded/resumable |
| `make_pdfs.py`, `make_zip.py` | Build `query_results.pdf`, `limitations.pdf` and `module_3.zip` |
| `query_results.pdf`, `limitations.pdf` | Analysis PDF and written reflection |
| `screenshots/` | Raw-SQL output, ORM output, running Flask page |
| `tests/` | pytest suite (unit tests + database-backed tests) |
| `docs/superpowers/` | Design spec and implementation plan for this module |

## 2. Setup and how to run

Developed and tested on Windows 11, Python 3.14, PostgreSQL 18. Python 3.10+ is required.

```bash
# 1. Environment
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. PostgreSQL: install it, then create the role and databases ONCE.
#    (Windows: double-click setup_db.bat; Git Bash: bash setup_db.sh; any OS: see db_setup.sql)
#    You will be asked for the postgres superuser password. Nothing is stored in the repo.

# 3. Connection settings: copy .env.example to .env (git-ignored) and fill in the password,
#    or export the same variables in your shell. Real environment variables take priority.
#    PGHOST=localhost  PGPORT=5432  PGDATABASE=gradcafe  PGUSER=gradcafe_app  PGPASSWORD=...

# 4. Load the data (safe to re-run; --reset empties the table first)
python load_data.py

# 5. Raw SQL answers, ORM answers (identical output), PDFs
python query_data.py
python orm_queries.py
python make_pdfs.py

# 6. Web app  ->  http://127.0.0.1:5000
python app.py

# 7. Tests (a scratch database named gradcafe_test is used; DB tests skip if unreachable)
python -m pytest
```

Optional, slow: `python run_llm_standardization.py` runs the local LLM over the entries
that do not have `llm_generated_*` values yet (see section 3.5). It needs
`pip install -r llm_hosting/requirements.txt` and the GGUF model in
`llm_hosting/models/` (about 670 MB; not included in the ZIP or in Git).

No credentials, API keys or paid services are required. Pull Data needs internet access.

## 3. Approach

### 3.1 Loading (`load_data.py`)
* `record_to_row()` maps one Module 2 record to the 14 columns of `applicants`
  (`id`→`p_id`, `gre_score`→`gre`, `applicant_status`→`status`, `date_added_raw`→`date_added`,
  `llm-generated-*`→`llm_generated_*`). Blank text becomes NULL; dates are parsed from ISO
  strings and become NULL if unparseable.
* **Data-quality rules found by inspecting the data** (all documented in code and tests):
  Grad Café's API reports **0.0 for "not provided"** — 35,263 of the 40,000 entries have a GRE
  writing score of exactly 0 — so zero is treated as missing for GPA and every GRE score (the
  Quant/Verbal range is 130–170, writing is (0, 6], GPA is (0, 4.33]); out-of-range values
  become NULL. A nationality other than American / International / Other (847 entries hold a
  literal `"0"`) becomes NULL and is excluded from Question 2's denominator. Without these
  rules the average GRE writing score would have been about 0.25 instead of 4.32.
* **Idempotence:** rows are written with `INSERT … ON CONFLICT (p_id) DO UPDATE`. The only
  thing a conflict may change is an *empty* LLM column (`COALESCE`), so re-running never
  duplicates rows and never overwrites an existing row's original data. `--reset` truncates
  the table for a clean rebuild. Connection errors print a readable message.
* Table: `p_id integer PRIMARY KEY`; `date_added date`; `gpa/gre/gre_v/gre_aw float`;
  every other column `text`.

### 3.2 Raw SQL (`query_data.py`)
Each question is a `Query` object: its wording, the exact SQL, an explanation and a renderer.
`run_query()` executes the SQL through a psycopg cursor and the renderer formats the rows, so
the SQL printed in `query_results.pdf` is exactly the SQL that ran. Matching is
case-insensitive (`LOWER(TRIM(term))`, `ILIKE`); averages use only non-NULL values because
`AVG` ignores NULL (an applicant with a GPA but no GRE still counts toward the GPA average);
percentages guard against division by zero with `NULLIF`. Q7 matches "Johns Hopkins" (also
the "John Hopkins" misspelling) or the standalone word JHU with `program ~* '\yjhu\y'`; Q8/Q9
restrict by term, acceptance, PhD, Computer Science and one of Georgetown / MIT / Stanford /
Carnegie Mellon simultaneously (MIT is matched by full name and by the word `\ymit\y`, so
"Smith" cannot match). Q9 returns both counts from one query using `COUNT(*) FILTER`.

Two original questions: **(1)** Fall 2026 acceptance rate by nationality group, and
**(2)** average GPA and GRE Quantitative of accepted vs rejected Fall 2026 applicants.

### 3.3 SQLAlchemy (`models.py`, `orm_queries.py`)
`Applicant` uses `DeclarativeBase`, `Mapped[...]` and `mapped_column(...)` and only *maps* the
existing table (no `create_all`, no second copy of the data). The Engine is created lazily
from `db_config` with `pool_pre_ping=True`; `SessionLocal = sessionmaker(engine)`.
`orm_queries.py` implements **all eleven** questions (the assignment requires 1, 4, 5, 8, 9 and
one original question; the Flask page must read through the ORM and show every result) using
`select()`, `func.count/avg`, `and_`, `or_`, `case`, `.filter()` and `.ilike()`. It never imports
`text` or `psycopg`; a test parses the module's AST to enforce that. Both implementations
return rows of the same shape and pass them to the same `render` functions in
`questions.py`, and a parametrised test checks that **every ORM answer equals its raw-SQL
answer** on a seeded database (and I diffed the two console outputs on the real data: identical).

### 3.4 Flask app (`app.py`) and Pull Data
* `GET /` runs `orm_queries.run_all()` and renders `templates/analysis.html` (styled by
  `static/style.css`, responsive, light/dark aware). A database outage shows an explanatory
  message with HTTP 503 instead of a stack trace.
* **Pull Data** (`POST /pull-data`) starts `pull_data.py` in a **subprocess** managed by
  `PullManager`. A `threading.Lock` makes check-then-launch atomic, so a second click (or a
  second browser tab) cannot start a second scrape; the user is told one is already running.
  A reader thread keeps the most recent output line as live progress.
* `pull_data.py` asks the database for the ids it already has, then calls
  `scrape.scrape_new_records()` — the Module 2 scraper's URL builder, `robots.txt` check,
  page parser and record parser — which reads the newest survey pages until it reaches a page
  with nothing new (at most 20 pages ≈ 400 entries per click, ~0.75 s apart). New records go
  through Module 2's `clean_data()` and the same upsert as `load_data.py`, so **new rows are
  added without overwriting existing data**. Blocks/timeouts (`ScrapeError`) are reported in
  plain language and any records fetched before the failure are still kept.
* **Update Analysis** (`POST /update-analysis`, top right) only re-reads the database. If a pull
  is running it says "New data is currently being retrieved" and leaves the pull alone;
  otherwise it confirms the analysis was refreshed. `GET /status` is polled by a small script
  so the page shows progress, disables Pull Data during a pull, and reloads when it finishes.

### 3.5 LLM standardization (Module 2 carry-over)
Only 5,000 of the 40,000 entries came with LLM-generated program/university fields from
Module 2 (a full run takes ~7–9 h on CPU). Question 9 selects rows by the **original** term,
status and degree, so only **Fall 2026 + accepted + PhD** entries (6,051) can change its answer.
`run_llm_standardization.py` was rewritten to (a) standardize those rows first, (b) run four
parallel shards with per-record flushed output, (c) skip ids already done so it can be
interrupted and resumed, and (d) merge everything into `llm_extend_applicant_data.json`.
Entries outside that group may have empty `llm_generated_*` columns; that cannot change
Q8 or Q9. Rows added by Pull Data also have NULL LLM columns (the model is too slow to run
inside a button click).

## 4. SQL versus SQLAlchemy — Question 5 (Fall 2025 acceptance percentage)

**Raw SQL**
```sql
SELECT 100.0 * COUNT(*) FILTER (WHERE status ILIKE 'accept%') / NULLIF(COUNT(*), 0)
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2025';
```

**SQLAlchemy**
```python
def _term_is(term):
    return func.lower(func.trim(Applicant.term)) == term

def _is_accepted():
    return Applicant.status.ilike("accept%")

def _percent_of_total(matching_count, total_count):
    return literal(Decimal("100.0"), Numeric) * matching_count / total_count

def q5(session):
    accepted = func.count().filter(_is_accepted())
    return session.execute(
        select(_percent_of_total(accepted, func.nullif(func.count(), 0))).where(_term_is("fall 2025"))
    ).all()
```

**Comparison.** The ORM version is built from small named, reusable pieces (`_term_is`,
`_is_accepted`), so the same "Fall 2026" or "accepted" rule is written once and used in eight
queries, and a misspelled column name (`Applicant.statuss`) fails immediately as an
`AttributeError` instead of at run time inside a SQL string. Writing SQL directly is shorter and reads
exactly as PostgreSQL executes it, which made it far easier to debug and to paste into `psql`;
the ORM hides that behind function calls, and I had to learn that `literal(Decimal("100.0"), Numeric)`
was needed so the ORM's arithmetic stayed exact NUMERIC like the SQL version rather than
becoming floating point. Raw SQL also gives direct control over PostgreSQL features
(`FILTER`, `ILIKE`, regex operators), whereas the ORM's portability advantage matters only if
the database were ever swapped out. For a one-off analysis I found SQL clearer; for the web
app, where queries are composed and reused, the ORM was the better fit.

## 5. Results (final data: 40,000 entries)

| Question | Result |
|---|---|
| 1. Fall 2026 applicant count | 33,207 |
| 2. Percent international | 47.14% |
| 3. Average GPA / GRE Quant / GRE Verbal / GRE Writing | 3.76 / 165.68 / 160.35 / 4.32 |
| 4. Average GPA, American Fall 2026 applicants | 3.79 |
| 5. Fall 2025 acceptance percentage | 39.03% |
| 6. Average GPA, accepted Fall 2026 applicants | 3.76 |
| 7. Johns Hopkins master's Computer Science entries | 20 |
| 8. Fall 2026 accepted PhD CS at Georgetown / MIT / Stanford / CMU (original fields) | 30 |
| 9. Same, using LLM-generated fields | 30 (difference 0) |
| Original 1. Fall 2026 acceptance rate by nationality | American 36.73% (n = 17,726), International 34.25% (n = 14,791), Unknown 53.32% (n = 572), Other 54.24% (n = 118) |
| Original 2. Accepted vs rejected, Fall 2026 (avg GPA / avg GRE Quant) | Accepted 3.76 / 165.61 (n = 11,945); Rejected 3.78 / 165.59 (n = 15,084) |

I checked these numbers three ways: the raw-SQL answers were recomputed independently in plain
Python from the raw JSON (all matched), the ORM answers equal the SQL answers on the real data,
and hand-built test data with known answers is asserted in `tests/test_query_data.py`.

**Why Questions 8 and 9 agree (Q9 written analysis).** Both searches found the same 30 entries
and the two sets of matching entries are identical. Grad Café's current results already give the
program and the university as separate, cleanly typed fields (Module 2 rebuilt the combined
"Program, University" text only so the LLM had something to split), so on input that tidy the
model mostly copies the names back. That does not make LLM standardization useless: for free-text
or misspelled entries (e.g. "John Hopkins", unusual abbreviations) it can raise a count, and it
can also lower one by mistake — I saw LLM spelling errors such as "Fayeletteville" and
"Ellectrical". A difference of zero only shows that, for these four universities, the original
fields were already good enough.

**Final LLM coverage:** 10,442 of the 40,000 entries have `llm_generated_*` values, including
**all 6,051** Fall 2026 accepted PhD entries (the only ones Q8/Q9 can select; none are missing).
The remaining ~29,600 entries were not standardized because the full run would have taken
several more hours. Interesting data-quality note: 847 entries have no usable nationality
(shown as "Unknown" in original question 1, and excluded from Question 2).

## 6. Screenshots (`screenshots/`)
* `sql_output.png` — output of `python query_data.py`
* `orm_output.png` — output of `python orm_queries.py`
* `flask_page.png` — the running Flask page
* `flask_pull_running.png`, `flask_pull_finished.png` — Pull Data in progress (with Update
  Analysis reporting "currently being retrieved", and the Pull Data button disabled) and after
  it finished ("Added 400 new records"). These two were captured against a scratch database
  (`gradcafe_test`) so the real data was not changed by the demonstration.

## 7. Known bugs and limitations
* **LLM coverage:** see sections 3.5 and 5. `llm_generated_*` is empty for about 29,600 entries
  outside Fall 2026 accepted PhD (which cannot change Q8/Q9) and for rows added by Pull Data.
  The LLM also makes occasional spelling mistakes (e.g. "Fayeletteville"), so LLM-based counts
  are approximate.
* **Pull Data** reads at most the 20 newest survey pages per click; if more than ~400 new
  entries have appeared, click again. It stops (and says so) if Grad Café blocks or rejects a
  request; Cloudflare interference was reported earlier in the semester but a live pull worked
  when tested (20 pages / 400 entries in ~34 s). Like Module 2, it never tries to bypass a block.
* `PullManager` lives in the web process, so it assumes a single Flask process (the built-in
  server, as used here). Several worker processes would each have their own manager.
* The Module 2 note that only ~8 records had 0 GRE scores understated the placeholder problem
  (it is 0.0 for "not provided" across most entries); Module 3 treats those zeros as missing.
* Console-output screenshots are renderings of the captured program output, not photos of a
  terminal window.
* Tested on Windows only.
* The 40,000 records are a snapshot; the numbers in this README, the PDFs and the screenshots
  describe that snapshot. Live Grad Café keeps receiving entries, so a fresh Pull Data changes them.

## 8. Module 2 background (scraper reuse)
`scrape.py` uses `urllib` and BeautifulSoup only: Grad Café's survey page embeds all results
as JSON in a `data-page` attribute, which `_extract_page_records()` reads; `robots.txt` was
checked manually (`screenshot.jpg`, `robots.txt`) and is checked in code before every request
(`_check_robots_allowed`); requests are throttled (~0.75 s) and stop on any HTTP failure.
`scrape_data()` is checkpointed and resumable (cursor + seen ids) and produced
`applicant_data.json`; `scrape_new_records()` is the Module 3 addition for incremental pulls.
