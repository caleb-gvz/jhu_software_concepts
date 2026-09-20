Name: Caleb Gevert (JHED: cgevert1)
Module Info: Module 2 -- Web Scraping (Grad Cafe)

================================================================================
Approach
================================================================================

Scraping approach: plain urllib + BeautifulSoup (no Selenium)
--------------------------------------------------------------
The assignment's live instructor note (Sept 7) warned that Cloudflare was
blocking plain urllib/requests scrapes and getting Selenium stuck in a
"verify you are human" loop, recommending a hybrid manual-Cloudflare-
verification workaround. Before building anything, I checked whether that
was still true: on 2026-09-13, a plain HTTP GET to
https://www.thegradcafe.com/survey with a normal browser User-Agent header
returned 200 OK immediately, with no Cloudflare challenge page at all.

Digging into the response, GradCafe's survey page turned out to be an
Inertia.js application: the entire page's data -- all 20 results on that
page, plus pagination metadata -- is embedded as a single JSON blob in a
`data-page="..."` attribute on `<div id="app">` in the raw HTML. No
JavaScript execution or table-scraping is needed to get it; a static HTML
fetch already contains fully structured data (school, program, degree
level, decision + decision date, term, American/International status,
GRE Q/V/AW, GPA, comments, GradCafe's numeric result id, etc.).

Given that, I used the "prior recommended" plain-urllib workflow described
in the assignment (rather than the hybrid Selenium/manual-Cloudflare
workaround, which the assignment itself says is only necessary "if the
plain approaches get blocked" -- they weren't) with BeautifulSoup used to
pull the one `data-page` attribute out of the page instead of scraping an
HTML table. This is simpler, fully rerunnable by a grader with zero manual
steps, and avoids ever needing a browser at all.

scrape.py
---------
- `_build_survey_url(cursor)` builds the survey URL via
  `urllib.parse.urlencode`/`urlunparse`. Pagination on GradCafe's survey
  endpoint is cursor-based (`?cursor=<opaque token>`), not `page=N` --
  `page=N` is silently ignored by the backend, confirmed by testing it live.
- `_check_robots_allowed()` / `_load_robots_parser()` check robots.txt
  before every request via `urllib.robotparser`. Building this exposed a
  real bug in Python's stdlib robotparser: it silently drops every
  `User-agent: *` block after the first one it parses, and its rule
  matching returns the *first* prefix-matching Allow/Disallow line rather
  than the most specific one. GradCafe's actual robots.txt has two separate
  `User-agent: *` blocks (a Cloudflare-managed one with `Allow: /`, then a
  separate site-specific one with the real `Disallow: /signin` etc. rules)
  -- naively using `RobotFileParser.read()` would silently ignore the
  site's own disallow rules. `_merge_robots_groups()` merges same-agent
  blocks together and `_sort_directives_by_specificity()` reorders
  Allow/Disallow lines by descending path length so the specific rules are
  checked first. Verified against the live robots.txt: `/survey` and
  `/result/*` are allowed, `/signin` and `/profile` are correctly
  disallowed.
- `_fetch_page()` fetches a page via `urllib.request` with a real
  browser User-Agent header.
- `_extract_page_records()` uses BeautifulSoup to find `<div id="app">`
  and pull its `data-page` attribute (BeautifulSoup HTML-unescapes it for
  us), then `json.loads()`s it and returns `props.results.data` (the
  records) and `props.results.meta.next_cursor`.
- `_parse_record()` maps one raw GradCafe API record into our schema (see
  below), building the `url` field from the numeric `id`
  (`https://www.thegradcafe.com/result/<id>`) and coercing GPA/GRE fields
  to float where possible (GradCafe's API mixes int/str/None types for
  these -- e.g. GRE Q sometimes arrives as an int, GRE AW as a string).
- `scrape_data()` is the main loop: builds a URL, checks robots.txt, fetches
  the page, extracts records, appends newly-seen ones (deduped by
  GradCafe's numeric id), advances the cursor, and checkpoints
  (`scrape_checkpoint.json`: last cursor + every id seen so far) every 25
  pages. Any blocking/failed HTTP request stops the run immediately with a
  printed message -- it never retries in a loop or works around a block.
  Because progress is checkpointed, a killed or interrupted run resumes
  automatically on the next invocation: `save_data()`/`load_data()` and the
  checkpoint file mean no re-scraping and no duplicate records. This
  actually happened during the real run: it hit one transient SSL
  handshake timeout partway through (not a deliberate block) and stopped
  cleanly per its design; re-running the same command picked up exactly
  where it left off and finished with zero duplicate ids.
- A polite ~0.75s delay is used between requests.
- `main()` exposes a small CLI (`--target`, `--output`, `--checkpoint`,
  `--delay`).

clean.py
--------
`clean_data()` collapses internal whitespace in text fields (blank strings
become `None`), coerces GPA/GRE fields to float, and normalizes the
`applicant_status` field's whitespace only -- it never changes what the
status *means*. It never touches `program_raw`/`university_raw`/`program`
beyond whitespace trimming that `_parse_record()` already applied, so the
original raw program/university text is always preserved alongside any
derived fields, per the assignment's requirement not to destructively
modify the original program field. Missing values are represented
consistently as `None` everywhere (never mixed with empty strings).

Record schema (applicant_data.json)
------------------------------------
Each record has: id, url, program_raw, university_raw, program (a combined
"<program>, <university>" string -- see LLM section below for why),
degree, applicant_status, status_date, status_label_raw, term,
us_or_international, gre_score, gre_v, gre_aw, gre_subject, gpa, comments,
date_added, date_added_raw.

applicant_data.json contains 40,000 records (above the 30,000 minimum),
scraped and then run through clean_data().

LLM standardization (llm_hosting/, run_llm_standardization.py)
----------------------------------------------------------------
llm_hosting/app.py (instructor-provided) reads a single `program` field
per row -- expecting the legacy GradCafe format where program and
university are combined into one string, e.g. "Computer Science, Stanford
University" -- and asks a small local LLM (TinyLlama 1.1B, GGUF, via
llama-cpp-python) to split and standardize it into
`llm-generated-program` / `llm-generated-university`. Since GradCafe's
current API already gives program and university as separate clean
fields, `_parse_record()` reconstructs the combined legacy-format string
as the `program` field specifically so this pipeline has something to
split, while `program_raw`/`university_raw` keep the already-clean
separate values untouched.

Two adjustments were needed to actually run this on my machine:

1. llm_hosting/requirements.txt pinned `llama-cpp-python>=0.2.90,<0.3.0`,
   which has no prebuilt wheel on PyPI for this system (Python 3.14,
   Windows, no C/C++ compiler installed) -- `pip install` tried to build it
   from source and failed with a CMake/nmake error. The assignment itself
   anticipates this ("expect to need to debug/adjust slightly for local
   Python/system -- that's expected"). I pointed the requirement at the
   project's own prebuilt CPU wheel index instead
   (`--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu`,
   pinned to `llama-cpp-python==0.3.35`), which installs with no compiler
   needed and is verified to reproduce the sample output exactly (splits
   "Information Studies, McGill University" into "Information Studies" /
   "McGill University", matching sample_data.json).

2. Full-dataset runtime. I benchmarked actual throughput on this machine
   (16 cores) before committing to a plan: ~0.92s/record running a single
   process with the default thread count (all 16 cores), and ~0.74s/record
   when sharded across 4 parallel processes (4 threads each) -- parallelism
   barely helps because this model's CPU inference is memory-bandwidth
   bound, not thread-count bound. At that rate, running all 40,000 scraped
   records through the LLM would take roughly 8-10 hours, which doesn't fit
   a reasonable single run. This was a deliberate, discussed scope decision
   (see "Known limitations" below), not an oversight: `applicant_data.json`
   still holds the full ~40,000 scraped records, satisfying the 30,000
   minimum, while only a documented 5,000-record subsample was run through
   the LLM standardizer.

`run_llm_standardization.py` drives this: `build_subsample()` takes the
first 5,000 records of `applicant_data.json`, `app.py --file ... --out ...`
(CLI mode, single process) standardizes them to JSON-Lines, and
`convert_jsonl_to_json()` converts that into a single JSON array --
`llm_extend_applicant_data.json` -- since the deliverable is meant to be
one JSON document, not JSONL. Every field from the input is preserved
alongside the two new `llm-generated-program`/`llm-generated-university`
fields (nothing is removed or overwritten).

No canonical-list edits were needed to llm_hosting/canon_universities.txt
or canon_programs.txt -- the provided fuzzy-matching (`difflib`-based, with
a 0.86 cutoff) against those lists, plus the few hardcoded abbreviation/fix
maps in app.py, handled every case I spot-checked correctly on this
dataset. The most common systematic edge case still seen after
standardization: university names that don't appear in canon_universities.txt
at all (e.g. smaller or non-US institutions) fall back to the LLM's own
best-effort title-casing rather than a canonical form, since there's
nothing in the canonical list to fuzzy-match against.

================================================================================
robots.txt compliance
================================================================================
Checked https://www.thegradcafe.com/robots.txt before writing any scraping
code (screenshot.jpg is a real browser screenshot of that page; robots.txt
is also saved verbatim in this folder). Its `User-agent: *` block only
disallows `/signin`, `/register`, `/forgot-password`, `/reset-password`,
`/confirm-password`, `/verify-email`, and `/profile` -- `/survey` and
`/result/*`, the only paths this scraper ever requests, are allowed.
`scrape.py` checks this programmatically before every request via
`_check_robots_allowed()`, not just as a one-time manual check (see the
robotparser bug/fix described above -- the merge step was necessary for
this check to actually be correct against GradCafe's real robots.txt
shape).

For transparency: robots.txt also has a separate `User-agent: ClaudeBot`
block with `Disallow: /`. This targets Anthropic's own AI-training web
crawler product, not a student script making requests with a standard
browser User-Agent string (which is what `scrape.py` does) -- but I'm
noting it explicitly since I used Claude Code to help build this scraper
and want the compliance check to be fully transparent about everything
robots.txt says, not just the parts favorable to scraping.

Throttling: ~0.75s delay between requests, and the scraper stops
immediately (no retry loop, no working around it) on any blocking or
failed HTTP response.

================================================================================
Known Bugs / Limitations
================================================================================
- llm_extend_applicant_data.json covers a documented 5,000-record
  subsample of applicant_data.json's 40,000 records, not the full dataset.
  This was a deliberate scope decision after benchmarking real LLM
  throughput on this hardware (~0.9s/record => 8-10 hours for all 40,000),
  not an oversight -- see the LLM standardization section above for the
  full reasoning.
- A small number of records have `null` GRE/GPA fields where the original
  applicant didn't report a score -- this is real missing data from
  GradCafe, represented consistently as `None`/`null`, not a parsing gap.
- 8 of the 40,000 records (0.02%) have a `null` program_raw -- GradCafe's
  own API returned an empty program string for these entries (the
  university field was still populated). Left as `None` rather than
  fabricated, per the requirement not to invent data the source doesn't
  provide; these same 8 records also show GRE scores of 0 rather than
  null, which appears to be an upstream GradCafe data quirk tied to the
  same blank-program submissions, reproduced faithfully rather than
  "corrected" without support from the source.
