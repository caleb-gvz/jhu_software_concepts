# Module 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load Grad Café data into PostgreSQL, answer 11 questions in raw SQL and 6 in SQLAlchemy, and serve them on a Flask page with Pull Data / Update Analysis.

**Architecture:** Small single-purpose modules share `db_config.py` (connections) and `formatting.py` (output rules). Query definitions are data (`QUERIES`) reused by the console, the PDF and Flask. The ORM layer mirrors a subset of them and is parity-tested against raw SQL.

**Tech Stack:** Python 3.14 venv (`module_3/.venv`), psycopg 3, SQLAlchemy 2.x, Flask 3, reportlab, pytest, llama-cpp-python (LLM step only).

**Spec:** `docs/superpowers/specs/2026-09-20-module3-database-flask-design.md`

## Global Constraints

- Table `applicants`: `p_id integer PK, program text, comments text, date_added date, url text, status text, term text, us_or_international text, gpa float, gre float, gre_v float, gre_aw float, degree text, llm_generated_program text, llm_generated_university text`.
- Credentials only via `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`; never committed.
- Counts whole numbers; percentages `NN.NN%`; averages 2 decimals (`formatting.py` only).
- `orm_queries.py`: no `text()`, no raw cursor. Flask reads use `Applicant`.
- Run tests with `.venv\Scripts\python.exe -m pytest` from `module_3/`.
- Stage explicit paths only. Never stage `module 3 instructions.pdf`, `.venv`, caches, `CLAUDE.md`, `.env`, `*.jsonl`, `llm_hosting/models/`.
- After each task: commit, then `git push origin main`.

---

### Task 1: Prioritised, resumable LLM standardization

**Files:**
- Modify: `run_llm_standardization.py` (replace subsample flow)
- Modify: `tests/test_run_llm_standardization.py`
- Modify: `.gitignore` (add `llm_shard_*.json`)

**Interfaces:**
- Produces: `is_priority_record(record: dict) -> bool`; `find_completed_ids(paths: list[Path]) -> set[int]`; `plan_shards(records: list[dict], done_ids: set[int], shards: int) -> list[list[dict]]` (priority rows first, round-robin); `merge_outputs(records, enriched_paths, output_path) -> int`.

- [ ] **Step 1: Write failing tests**

```python
from run_llm_standardization import is_priority_record, plan_shards, find_completed_ids

def _rec(i, term="Fall 2026", status="Accepted", degree="PhD"):
    return {"id": i, "term": term, "applicant_status": status, "degree": degree}

def test_priority_is_fall_2026_accepted_phd():
    assert is_priority_record(_rec(1))
    assert not is_priority_record(_rec(2, term="Fall 2025"))
    assert not is_priority_record(_rec(3, status="Rejected"))
    assert not is_priority_record(_rec(4, degree="Masters"))

def test_plan_shards_puts_priority_first_and_skips_done():
    records = [_rec(1, degree="Masters"), _rec(2), _rec(3), _rec(4)]
    shards = plan_shards(records, done_ids={3}, shards=2)
    flat_order = [r["id"] for pair in zip(*shards) for r in pair]
    assert flat_order[0] == 2                    # priority row leads
    assert {r["id"] for s in shards for r in s} == {1, 2, 4}   # 3 already done

def test_find_completed_ids_ignores_truncated_last_line(tmp_path):
    p = tmp_path / "shard.jsonl"
    p.write_text('{"id": 7}\n{"id": 8}\n{"id": 9', encoding="utf-8")
    assert find_completed_ids([p]) == {7, 8}
```

- [ ] **Step 2: Run** `pytest tests/test_run_llm_standardization.py -v` → FAIL (`ImportError`).
- [ ] **Step 3: Implement** the four functions plus `main()` that: loads `applicant_data.json`, computes `done_ids` from `llm_extend_applicant_data.json` + `llm_shard_*.jsonl`, writes shard inputs `llm_shard_N.json`, launches one `app.py --file … --out llm_shard_N.jsonl --append` subprocess per shard with `N_THREADS=3` env in `llm_hosting/`, waits, then calls `merge_outputs`. `find_completed_ids` reads line-by-line, skipping lines that fail `json.loads`.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Launch** `.venv\Scripts\python.exe run_llm_standardization.py` in the background; confirm `llm_shard_0.jsonl` starts growing.
- [ ] **Step 6: Commit + push** `feat: prioritised resumable LLM standardization`.

### Task 2: Shared formatting and DB config

**Files:** Create `formatting.py`, `db_config.py`, `.env.example`; Test `tests/test_formatting.py`, `tests/test_db_config.py`.

**Interfaces:** Produces `fmt_count(n)->str` (`19,290`), `fmt_percent(x)->str` (`50.09%`), `fmt_average(x)->str` (`3.79`), `fmt_signed_difference(n)->str` (`+3`), each returning `"N/A"` for `None`; `connect() -> psycopg.Connection`; `sqlalchemy_url() -> sqlalchemy.engine.URL`.

- [ ] **Step 1: Tests**

```python
from formatting import fmt_count, fmt_percent, fmt_average, fmt_signed_difference

def test_formats():
    assert fmt_count(19290) == "19,290"
    assert fmt_percent(50.0876) == "50.09%"
    assert fmt_average(3.7872697) == "3.79"
    assert fmt_average(164.87784679) == "164.88"
    assert fmt_signed_difference(3) == "+3" and fmt_signed_difference(-2) == "-2"
    assert fmt_signed_difference(0) == "0"
    assert fmt_average(None) == "N/A"

def test_sqlalchemy_url_reads_env_and_hides_nothing_hardcoded(monkeypatch):
    from db_config import sqlalchemy_url
    monkeypatch.setenv("PGUSER", "u"); monkeypatch.setenv("PGPASSWORD", "p")
    monkeypatch.setenv("PGDATABASE", "d"); monkeypatch.setenv("PGHOST", "h"); monkeypatch.setenv("PGPORT", "5433")
    url = sqlalchemy_url()
    assert (url.host, url.port, url.database, url.username) == ("h", 5433, "d", "u")
    assert url.drivername == "postgresql+psycopg"
```

- [ ] **Step 2:** run → FAIL. **Step 3:** implement (defaults: host `localhost`, port `5432`, db `gradcafe`; `connect()` uses `psycopg.connect(host=…, port=…, dbname=…, user=…, password=…)`). **Step 4:** run → PASS. **Step 5:** commit + push.

### Task 3: PostgreSQL set-up and `load_data.py`

**Files:** Create `load_data.py`, `tests/test_load_data.py`, `tests/conftest.py` (fixture `test_conn`: connects to `gradcafe_test`, skips if unreachable; truncates `applicants`).

**Interfaces:** Consumes `db_config.connect`. Produces `record_to_row(record: dict) -> dict` (keys = the 14 column names), `create_table(conn) -> None`, `upsert_rows(conn, rows: list[dict]) -> int`, `load_records(conn, records) -> int`, CLI `python load_data.py [--data applicant_data.json] [--llm-data llm_extend_applicant_data.json]`.

- [ ] **Step 1: Tests (pure)**

```python
from load_data import record_to_row

BASE = {"id": 5, "url": "u", "program": "CS, MIT", "degree": "PhD", "applicant_status": "Accepted",
        "term": "Fall 2026", "us_or_international": "American", "gpa": 3.9, "gre_score": 168.0,
        "gre_v": 160.0, "gre_aw": 4.5, "comments": "  ", "date_added_raw": "2026-09-12"}

def test_maps_columns_and_types():
    row = record_to_row(BASE)
    assert row["p_id"] == 5 and row["status"] == "Accepted" and row["gre"] == 168.0
    assert str(row["date_added"]) == "2026-09-12" and row["comments"] is None

def test_out_of_range_scores_become_none():
    row = record_to_row({**BASE, "gpa": 40.0, "gre_score": 900.0, "gre_aw": 9.0})
    assert row["gpa"] is None and row["gre"] is None and row["gre_aw"] is None
    assert row["gre_v"] == 160.0

def test_missing_optional_values_do_not_fail():
    row = record_to_row({"id": 6, "url": "u"})
    assert row["p_id"] == 6 and row["gpa"] is None and row["date_added"] is None

def test_llm_fields_map_from_hyphenated_keys():
    row = record_to_row({**BASE, "llm-generated-program": "Computer Science", "llm-generated-university": "MIT"})
    assert row["llm_generated_program"] == "Computer Science"
```

- [ ] **Step 2 (DB test):** loading the same records twice leaves `COUNT(*)` unchanged, and a second load with LLM fields fills NULL LLM columns without touching `status`.
- [ ] **Step 3:** implement. Upsert SQL:

```sql
INSERT INTO applicants (p_id, program, comments, date_added, url, status, term, us_or_international,
  gpa, gre, gre_v, gre_aw, degree, llm_generated_program, llm_generated_university)
VALUES (%(p_id)s, %(program)s, %(comments)s, %(date_added)s, %(url)s, %(status)s, %(term)s,
  %(us_or_international)s, %(gpa)s, %(gre)s, %(gre_v)s, %(gre_aw)s, %(degree)s,
  %(llm_generated_program)s, %(llm_generated_university)s)
ON CONFLICT (p_id) DO UPDATE SET
  llm_generated_program    = COALESCE(applicants.llm_generated_program, EXCLUDED.llm_generated_program),
  llm_generated_university = COALESCE(applicants.llm_generated_university, EXCLUDED.llm_generated_university)
```

`create_table` uses `CREATE TABLE IF NOT EXISTS` with the schema above (`gpa/gre/gre_v/gre_aw FLOAT`). Wrap DB errors with a readable message naming the env vars.
- [ ] **Step 4:** create `gradcafe` + `gradcafe_test` databases and a `gradcafe_app` role (needs the user's postgres superuser password via `PGPASSWORD`, not stored). Run the loader on all 40,000 records; verify `SELECT COUNT(*)`, run it again, verify the count is unchanged.
- [ ] **Step 5:** commit + push `feat: load Module 2 data into PostgreSQL`.

### Task 4: Raw SQL analysis (`query_data.py`)

**Files:** Create `query_data.py`, `tests/test_query_data.py`.

**Interfaces:** Consumes `db_config.connect`, `formatting.*`. Produces `@dataclass Query(number, title, question, sql, explanation, render)`; `QUERIES: list[Query]` (13 entries: 1–9 and `"O1"`, `"O2"` — Q9 renders three lines); `run_query(conn, query) -> list[str]` (formatted result lines); `run_all(conn) -> list[tuple[Query, list[str]]]`; `main()` prints every result.

- [ ] **Step 1: Tests** against a small fixture set inserted into `gradcafe_test` (rows engineered so each question has a known answer; includes a NULL-GPA American Fall 2026 row, a `jhu` and a `Johns Hopkins University` Masters CS row, a Stanford PhD accepted Fall 2026 CS row whose original `program` is misleading but whose LLM fields are correct).

```python
def test_q1_counts_fall_2026_case_insensitively(seeded_conn):
    assert run_query(seeded_conn, get_query(1)) == ["Fall 2026 applicant count: 4"]

def test_q2_excludes_blank_nationality_from_denominator(seeded_conn):
    assert run_query(seeded_conn, get_query(2)) == ["Percent international: 40.00%"]

def test_q3_averages_use_only_rows_with_each_metric(seeded_conn):
    assert run_query(seeded_conn, get_query(3))[0] == "Average GPA: 3.60"

def test_q9_reports_both_counts_and_difference(seeded_conn):
    assert run_query(seeded_conn, get_query(9)) == [
        "Original-field count: 1", "LLM-field count: 2", "Difference: +1"]
```

- [ ] **Step 2:** run → FAIL. **Step 3:** implement with these SQL bodies (all constants, no parameters):

```sql
-- 1
SELECT COUNT(*) FROM applicants WHERE LOWER(TRIM(term)) = 'fall 2026';
-- 2
SELECT 100.0 * COUNT(*) FILTER (WHERE LOWER(TRIM(us_or_international)) = 'international')
       / NULLIF(COUNT(*) FILTER (WHERE NULLIF(TRIM(us_or_international), '') IS NOT NULL), 0)
FROM applicants;
-- 3
SELECT AVG(gpa), AVG(gre), AVG(gre_v), AVG(gre_aw) FROM applicants;
-- 4
SELECT AVG(gpa) FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026' AND LOWER(TRIM(us_or_international)) = 'american' AND gpa IS NOT NULL;
-- 5
SELECT 100.0 * COUNT(*) FILTER (WHERE status ILIKE 'accept%') / NULLIF(COUNT(*), 0)
FROM applicants WHERE LOWER(TRIM(term)) = 'fall 2025';
-- 6
SELECT AVG(gpa) FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026' AND status ILIKE 'accept%' AND gpa IS NOT NULL;
-- 7
SELECT COUNT(*) FROM applicants
WHERE (program ILIKE '%johns hopkins%' OR program ~* '\yjhu\y')
  AND program ILIKE '%computer science%' AND degree ILIKE 'master%';
-- 8 (original fields)  |  9 swaps program -> llm_generated_program in the program test and
-- program -> llm_generated_university in the university test
SELECT COUNT(*) FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026' AND status ILIKE 'accept%' AND degree ILIKE 'phd'
  AND program ILIKE '%computer science%'
  AND (program ILIKE '%georgetown%' OR program ILIKE '%massachusetts institute of technology%'
       OR program ~* '\ymit\y' OR program ILIKE '%stanford%' OR program ILIKE '%carnegie mellon%');
-- O1: Fall 2026 acceptance rate by nationality group
SELECT COALESCE(NULLIF(TRIM(us_or_international), ''), 'Unknown') AS grp, COUNT(*) AS entries,
       100.0 * COUNT(*) FILTER (WHERE status ILIKE 'accept%') / COUNT(*) AS acceptance_pct
FROM applicants WHERE LOWER(TRIM(term)) = 'fall 2026' GROUP BY grp ORDER BY entries DESC;
-- O2: accepted vs rejected, Fall 2026: entries, avg GPA, avg GRE Quant
SELECT status, COUNT(*), AVG(gpa), AVG(gre) FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2026' AND (status ILIKE 'accept%' OR status ILIKE 'reject%')
GROUP BY status ORDER BY status;
```

- [ ] **Step 4:** run tests → PASS; run `python query_data.py` against the real DB and sanity-check every number by hand with an independent pandas-free Python count over `applicant_data.json`.
- [ ] **Step 5:** commit + push `feat: raw SQL analysis for Questions 1-9 and two original questions`.

### Task 5: SQLAlchemy model and ORM queries

**Files:** Create `models.py`, `orm_queries.py`, `tests/test_orm_parity.py`.

**Interfaces:** Consumes `db_config.sqlalchemy_url`, `formatting.*`. Produces `Base`, `Applicant`, `engine`, `SessionLocal`, `get_session()` in `models.py`; in `orm_queries.py` `q1(session)->int`, `q4(session)->float|None`, `q5(session)->float|None`, `q8(session)->int`, `q9(session)->tuple[int,int,int]` (original, llm, difference), `own_q1(session)->list[tuple[str,int,float]]`, `run_all(session)->list[tuple[str,list[str]]]`, `main()`.

- [ ] **Step 1: Parity test**

```python
def test_orm_answers_match_raw_sql(seeded_conn, orm_session):
    import orm_queries as o, query_data as q
    assert fmt_count(o.q1(orm_session)) in q.run_query(seeded_conn, q.get_query(1))[0]
    assert o.q9(orm_session) == (1, 2, 1)
    # ...same for Q4, Q5, Q8, own Q1

def test_orm_module_never_uses_raw_sql():
    src = Path("orm_queries.py").read_text(encoding="utf-8")
    assert "text(" not in src and ".cursor(" not in src and "psycopg" not in src
```

- [ ] **Step 2:** run → FAIL. **Step 3:** implement with `select`, `func.count`, `func.avg`, `and_`, `or_`, `Applicant.status.ilike("accept%")`, `func.lower(func.trim(Applicant.term)) == "fall 2026"`, `func.count().filter(...)` for percentages, `Applicant.program.regexp_match(r"\ymit\y", flags="i")` for MIT. **Step 4:** tests PASS + `python orm_queries.py` output equals `query_data.py` for the shared questions. **Step 5:** commit + push (model and ORM as two commits).

### Task 6: Scraper support for incremental pulls

**Files:** Modify `scrape.py` (add `scrape_new_records`); Create `pull_data.py`; Test `tests/test_scrape.py`, `tests/test_pull_data.py`.

**Interfaces:** Produces `scrape_new_records(known_ids: set[int], max_pages: int = 20, delay_seconds: float = 0.75, fetch_fn=_fetch_page, robots_parser=None) -> list[dict]` (newest page first; parsed records not in `known_ids`; stops after a page containing only known ids, at `max_pages`, or on any HTTP/robots/parse error which it raises as `ScrapeError(message)`); `pull_data.main() -> int` exit code (0 ok, 2 scrape error), prints one status line per stage.

- [ ] **Step 1: Tests** with a fake `fetch_fn` returning the fixture HTML: new ids returned, known ids skipped, stops at first all-known page, HTTP 403 raises `ScrapeError("Grad Café blocked the request (HTTP 403)")`.
- [ ] **Step 2–4:** implement, PASS. `pull_data.main` = `connect()` → `SELECT p_id` → `scrape_new_records` → `clean.clean_data` → `load_data.load_records`; prints `Added N new records`.
- [ ] **Step 5:** live smoke test of one page (`max_pages=1`) to learn whether Cloudflare blocks; record the outcome in the README either way. Commit + push.

### Task 7: Flask app, Pull Data, Update Analysis

**Files:** Create `pull_manager.py`, `app.py`, `templates/analysis.html`, `static/style.css`, `tests/test_pull_manager.py`, `tests/test_app.py`.

**Interfaces:** Produces `PullManager(command: list[str])` with `start() -> bool`, `is_running() -> bool`, `last_message -> str`; `create_app(manager: PullManager | None = None, session_factory=SessionLocal) -> Flask`. Routes `GET /`, `POST /pull-data`, `POST /update-analysis`, `GET /status` → `{"running": bool, "message": str}`.

- [ ] **Step 1: Tests**

```python
import sys
from pull_manager import PullManager

def test_second_start_is_refused_while_running():
    m = PullManager([sys.executable, "-c", "import time; time.sleep(2)"])
    assert m.start() is True
    assert m.start() is False and m.is_running()
    m.wait()

def test_finished_process_message_uses_last_output_line():
    m = PullManager([sys.executable, "-c", "print('Added 3 new records')"])
    m.start(); m.wait()
    assert not m.is_running() and "Added 3 new records" in m.last_message

def test_update_analysis_reports_busy_and_does_not_start_scrape(client_with_running_manager):
    resp = client_with_running_manager.post("/update-analysis", follow_redirects=True)
    assert b"currently being retrieved" in resp.data
```

- [ ] **Step 2–4:** implement with a `threading.Lock` around start/poll, `subprocess.Popen(command, stdout=PIPE, stderr=STDOUT, text=True)`, and flash messages; Update Analysis button top-right (`.header-actions`), explanatory paragraph beside Pull Data, page reads only through `orm_queries.run_all`, polling script (~15 lines) hitting `/status` every 3 s and disabling **Pull Data** while running. Real routes tested with the Flask test client against `gradcafe_test`.
- [ ] **Step 5:** run `python app.py`, open in browser, click both buttons, confirm behaviour; commit + push.

### Task 8: PDFs, screenshots, README

**Files:** Create `make_pdfs.py`, `README.md`, `screenshots/*.png`; Generate `query_results.pdf`, `limitations.pdf`; Modify `requirements.txt`; Delete stale `readme.txt` (its scraper notes move into README.md).

- [ ] **Step 1:** `make_pdfs.py` builds `query_results.pdf` from `query_data.run_all` (question, result, SQL, explanation for all 11) and `limitations.pdf` from two reviewed paragraphs (text lives in the script; cites the real Q3 GRE Quant average and the O2 accepted-vs-rejected gap).
- [ ] **Step 2:** screenshots: `query_data.py` console, `orm_queries.py` console, running Flask page (Playwright browser tool).
- [ ] **Step 3:** README.md: name + JHED, setup (PostgreSQL, env vars, `load_data.py`, `query_data.py`, `orm_queries.py`, `app.py`), approach, SQL-vs-ORM comparison for Q5 (raw SQL, ORM code, 3–5 sentences), Q8/Q9 LLM-coverage note, known bugs. `pip freeze`-checked `requirements.txt` (psycopg[binary], SQLAlchemy, Flask, reportlab, beautifulsoup4, pytest); LLM deps stay in `llm_hosting/requirements.txt`.
- [ ] **Step 4:** commit + push.

### Task 9: Final load, verification, ZIP

- [ ] **Step 1:** when LLM shards finish (or at the deadline), re-run `run_llm_standardization.py` (merge only) and `load_data.py`; re-run `query_data.py`, `orm_queries.py`, regenerate PDFs and screenshots so all numbers agree.
- [ ] **Step 2:** `pytest` all green; `git status` clean; `git check-ignore` confirms the instructions PDF is ignored; fresh-venv install from `requirements.txt` works.
- [ ] **Step 3:** build `module_3.zip` with a script that includes only tracked-style deliverables (excludes `.venv`, caches, model, `*.jsonl`, `llm_shard_*`, `.env`, the instructions PDF, `CLAUDE.md`); verify the file list.
- [ ] **Step 4:** final commit + push; confirm `git log origin/main` equals local HEAD and `github.txt` holds the SSH URL.
