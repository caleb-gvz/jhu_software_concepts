# Module 2 — GradCafe Scraper & Cleaning Pipeline — Design

Date: 2026-09-13
Status: Approved by user in chat 2026-09-13

## Context

Module 2 requires a programmatic scraper that pulls ≥30,000 graduate
applicant entries from thegradcafe.com's public survey results, stores them
as JSON, cleans the data, and runs a provided local-LLM standardizer over
program/university names. Full assignment constraints live in
`../../CLAUDE.md` (module) and `../../../CLAUDE.md` (course-wide).

### Pre-implementation findings (2026-09-13)

Probed live before designing, since the instructor's Sept 7 note warned of
Cloudflare blocking a plain `urllib`/`requests` pull:

- `robots.txt` (`https://www.thegradcafe.com/robots.txt`): `User-agent: *`
  → `Allow: /`, with only `/signin`, `/register`, `/forgot-password`,
  `/reset-password`, `/confirm-password`, `/verify-email`, `/profile`
  disallowed. `/survey` and `/result/*` are not restricted. There is a
  separate `User-agent: ClaudeBot` → `Disallow: /` entry (Anthropic's own
  training crawler) — noted for transparency in the README, but not
  applicable to a student script using a standard browser/urllib User-Agent.
- A plain `curl` GET with a normal Chrome User-Agent to
  `https://www.thegradcafe.com/survey?page=1` returned `200 OK` immediately
  with no Cloudflare "Just a moment..." interstitial. Cloudflare is not
  currently blocking plain requests, so per the course CLAUDE.md's own
  fallback guidance, the hybrid manual-Cloudflare-verification / Selenium
  workflow is unnecessary right now.
- The survey page is an Inertia.js app: the entire page's data is embedded
  as JSON in a `data-page="..."` attribute on `<div id="app">` in the raw
  HTML — no client-side JS execution needed to obtain it. Structure:
  `props.results.data` = list of 20 record dicts, `props.results.meta` =
  `{per_page, next_cursor, prev_cursor, total}`.
- Pagination is cursor-based, not `page=N` (that query param is silently
  ignored — every `page=N` request returns page 1). Passing
  `?cursor=<next_cursor from previous response>` correctly advances.
- Each record dict already arrives structurally clean: `id`, `school`,
  `program`, `level`, `decision`, `decision_label`, `acceptedDate` /
  `rejectedDate` / `waitlistedDate` / `interviewDate`, `date_of_notification`,
  `season`, `status` (American/International), `ugpa`, `greq`, `grev`,
  `grew`, `gres`, `notes`, `created_at`, `added_on_label`.
- Total available at probe time: 958,850 records — far above the 30,000
  minimum.

These findings materially simplify the build: no Selenium, no manual
Cloudflare step, no HTML-table scraping/regex-guessing of fields — just
`urllib` + BeautifulSoup (to pull the one attribute) + `json.loads`.

## Amendment 2026-09-13: LLM step scope, after hands-on benchmarking

Before finalizing the plan, actually installed `llm_hosting`'s dependencies
and benchmarked it on this machine:

- `llama-cpp-python` (the pin in `llm_hosting/requirements.txt`,
  `>=0.2.90,<0.3.0`) has no prebuilt wheel on PyPI for this range — PyPI
  only hosts an sdist requiring a C/C++ compiler (nmake/MSVC), which isn't
  installed on this machine. The assignment's own instructions anticipate
  needing "to debug/adjust slightly for local Python/system," so
  `llm_hosting/requirements.txt` will be updated to install
  `llama-cpp-python` from the project's own prebuilt CPU wheel index
  (`https://abetlen.github.io/llama-cpp-python/whl/cpu`), pinned to
  `0.3.35` — a `py3-none-win_amd64` ctypes-wrapper wheel, installs with no
  compiler needed, verified to reproduce `sample_data.json`'s expected
  output exactly.
- Measured throughput: ~0.92s/record single-process (default threading,
  all 16 cores), ~0.74s/record when sharded across 4 parallel processes (4
  threads each) — parallelizing barely helps because this model's
  inference is memory-bandwidth-bound, not thread-count-bound. At ~0.9s/
  record, standardizing all 40,000 scraped records would take ~8-10 hours
  of continuous runtime, which doesn't fit a single session.
- **Decision (user-confirmed):** `applicant_data.json` still holds the full
  ~40,000 scraped records (satisfies the 30,000 SHALL minimum).
  `llm_extend_applicant_data.json` covers a **documented subsample of the
  first 5,000 records** (~1.3 hours at measured throughput) rather than the
  full set. This is a deliberate, documented scope reduction, not a bug —
  the README's "known bugs"/notes section states the subsample size and
  that the remaining records were not run through the LLM standardizer due
  to CPU-only runtime constraints on this hardware.

## Goals / Non-goals

**Goals**
- `scrape.py`: pull ~40,000 records via `urllib`, respecting `robots.txt`,
  with resumable checkpointing and polite throttling.
- `clean.py`: normalize the scraped data without destroying raw fields.
- Run `llm_hosting/app.py` over the cleaned data to produce
  `llm_extend_applicant_data.json`.
- `applicant_data.json` (raw-ish, parsed) and
  `llm_extend_applicant_data.json` (LLM-standardized) as valid JSON.
- `screenshot.jpg` of `robots.txt` + README compliance write-up.
- README (`readme.txt`) and `requirements.txt` per the module template.

**Non-goals**
- Selenium / browser automation for the actual scrape (not needed given the
  findings above — documented as the reason in the README).
- Any bypass of robots.txt, auth, or rate limits.
- Deduplicating/standardizing beyond what `llm_hosting/app.py` + light
  post-processing does — outlier cleanup is explicitly deferred to a later
  module per the assignment.

## Architecture

```
scrape.py          -- fetch + parse + checkpoint + save raw applicant data
clean.py            -- normalize applicant data (types, missing values)
llm_hosting/         -- instructor-provided subpackage (unmodified except
                         for documented canonical-list tweaks, if any)
applicant_data.json           -- output of scrape_data() -> clean_data()
llm_extend_applicant_data.json -- output of running llm_hosting/app.py over
                                   applicant_data.json
robots.txt / screenshot.jpg   -- compliance evidence
readme.txt, requirements.txt
```

### `scrape.py`

Functions (module-level, per assignment's SHOULD naming):

- `scrape_data(target_count, output_path, checkpoint_path, delay_seconds) -> list[dict]`
  Main driver. Loads any existing checkpoint (`{"next_cursor": ..., "seen_ids": [...]}`)
  and any partially-written `output_path`, then loops:
  1. Build the survey URL via `urllib.parse.urlencode`/`urlunparse`.
  2. `_check_robots_allowed(url)` — `urllib.robotparser.RobotFileParser` against
     the live `robots.txt`; abort with a clear error if disallowed.
  3. `_fetch_page(url)` — `urllib.request.Request` with a real browser
     User-Agent header, `urllib.request.urlopen`. On HTTP error or non-200
     status (403/429/5xx), stop the run entirely (do not retry/backoff-loop
     indefinitely, do not switch tactics to evade) — log what happened and
     exit cleanly so it can be resumed later.
  4. `_extract_page_records(html_text) -> (records, next_cursor, total)` —
     BeautifulSoup finds `div#app`, reads its `data-page` attribute,
     `json.loads` it, returns `props.results.data`, `props.results.meta.next_cursor`.
  5. `_parse_record(raw) -> dict` — maps one API record into our schema
     (below), skipping/deduping by `id` against `seen_ids`.
  6. Append parsed records to the in-memory list and to `output_path` /
     checkpoint every N pages (e.g. every 25 pages / 500 records) so a kill
     partway through loses at most that window.
  7. `time.sleep(delay_seconds)` between requests (~0.75-1s).
  8. Stop when `len(seen_ids) >= target_count` or `next_cursor` is `None`
     (end of results).
- `save_data(records, path)` / `load_data(path)` — thin JSON read/write
  helpers reused by `clean.py` and the checkpoint logic.
- Private helpers: `_build_survey_url`, `_check_robots_allowed`,
  `_fetch_page`, `_extract_page_records`, `_parse_record`.
- `argparse` CLI: `--target` (default 40000), `--output`
  (`applicant_data.json`), `--checkpoint`, `--delay`, `--resume` (default
  behavior — resuming is automatic if a checkpoint exists, so this task's
  design treats "rerunnable with no manual steps" as the default, not an
  opt-in flag).

### Record schema (written to `applicant_data.json`)

```
{
  "id": int,                        # GradCafe's numeric result id
  "url": str,                       # https://www.thegradcafe.com/result/<id>
  "program_raw": str,               # API's "program", untouched
  "university_raw": str,            # API's "school", untouched
  "program": str,                   # "{program_raw}, {university_raw}" —
                                     # legacy combined format llm_hosting/app.py expects
  "degree": str | None,             # API's "level" (Masters/PhD/MFA/...)
  "applicant_status": str | None,   # "Accepted" / "Rejected" / "Wait listed" / "Interview"
  "status_date": str | None,        # ISO date matching whichever of
                                     # accepted/rejected/waitlisted/interviewDate is set
  "status_label_raw": str | None,   # API's "decision_label", kept for traceability
  "term": str | None,               # API's "season", e.g. "Fall 2024"
  "us_or_international": str | None,# API's "status" (American/International)
  "gre_score": float | None,        # API's "greq"
  "gre_v": float | None,            # API's "grev"
  "gre_aw": float | None,           # API's "grew"
  "gre_subject": float | None,      # API's "gres" (kept, not a required field)
  "gpa": float | None,              # API's "ugpa"
  "comments": str | None,           # API's "notes"
  "date_added": str | None,         # API's "added_on_label"
  "date_added_raw": str | None      # API's "created_at" (ISO), for traceability
}
```

Consistent missing-value representation: `None` everywhere (never mixed
with `""`).

### `clean.py`

- `clean_data(records) -> list[dict]`: strips stray whitespace, decodes any
  residual HTML entities in text fields (belt-and-suspenders — the JSON
  source shouldn't have any), coerces GPA/GRE fields to `float` where
  parseable else `None`, leaves `program_raw`/`program`/`university_raw`
  untouched. Never mutates the original raw fields.
- Private helper: `_normalize_status(value)` for whitespace/casing only —
  does not alter the meaning of Accepted/Rejected/Wait listed/Interview.

### LLM standardization

After `clean_data()`, take the **first 5,000 records** (by scrape order)
from `applicant_data.json` and run `llm_hosting/app.py --file <subsample>
--out <ndjson>` (CLI mode, single process, default threading — benchmarking
showed multi-process sharding isn't worth the added complexity on this
hardware) to produce `llm_extend_applicant_data.json`. The `.jsonl` CLI
output is converted into a single JSON array (the deliverable name implies
one JSON document) before being saved. Adds `llm-generated-program` /
`llm-generated-university` per record on top of the existing fields
(nothing removed or overwritten). The README documents the subsample size
and why.

### Compliance evidence

- `robots.txt` saved into `module_2/` for reference.
- `screenshot.jpg`: real browser screenshot of
  `https://www.thegradcafe.com/robots.txt`, captured via the Chrome browser
  tool.
- README section explaining: what was checked, that `/survey`/`/result/`
  are allowed for `User-agent: *`, the throttling used, and the
  ClaudeBot-specific disallow entry noted for transparency (not applicable
  to this script's User-Agent).

## Error handling

- Any non-200 response, or a 403/429, stops `scrape_data()` immediately
  with a clear message — never retried in a tight loop, never worked around.
- Malformed/missing `data-page` attribute on a given page → log and skip
  that page (don't crash the whole run), but do not silently skip more than
  a couple of pages in a row (treat as a stop condition if it recurs, since
  that likely signals a layout change worth a human look).
- Partial writes are safe: checkpoint + output file are updated together
  periodically, so a resume never duplicates records (dedup by `id`).

## Testing / verification

- After the full scrape: assert `applicant_data.json` parses as valid JSON,
  record count ≥ 40,000, spot-check ~5 records' fields against the live
  `/result/<id>` page.
- After cleaning: assert no raw fields were dropped/overwritten, missing
  values are consistently `None`.
- After LLM standardization: assert `llm_extend_applicant_data.json` has
  exactly 5,000 records (the documented subsample), each with the two new
  fields plus every original field intact.

## Git workflow

Commit + push directly to `main` incrementally as pieces land: scaffold →
working scraper (small test run) → full ~40k pull → `clean.py` → LLM
standardization output → README/requirements/screenshot. Matches this
repo's existing single-branch history.
