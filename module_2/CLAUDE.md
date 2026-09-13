# Module 2 — Assignment: Web Scraping (Grad Cafe)

100 points · file upload + GitHub
This file is loaded together with the course-level `../CLAUDE.md`. That file
has the standing engineering/academic-integrity rules; this file has the
assignment-specific requirements and rubric for module_2 only.

## ⚠️ Instructor's live update (inserted Sept 7, 2026) — read before scraping
Cloudflare is currently interfering with the "old" Selenium-only approach:
- A plain `requests`/`urllib` scrape gets blocked with HTTP 403.
- A Selenium-controlled browser gets stuck in a repeated "verify you are
  human" loop.

**Workaround the instructor used this semester (hybrid capture approach):**
1. Open Grad Cafe in a normal Chrome browser — **not** Selenium.
2. Let a human complete Cloudflare's verification manually (a one-time thing
   per session; after that the automation just runs).
3. Once the results table is visible, use a small helper script to capture
   the page's *current* rendered HTML from that Chrome session.
4. Feed the saved HTML into the existing parser (BeautifulSoup/regex/string
   methods).
5. Repeat for the next page; close pages as you go.

Instructor's reference throughput with this approach (for scale/sanity
checking, not a target to hit exactly): ~400 records / 20 pages / ~110
seconds, parallelized. At that rate, 30k rows is roughly a 2.5-hour pull.
**If a pull breaks partway through, the expectation is to resume from where
it left off — not restart from scratch.** Design `scrape_data()`/checkpointing
with that in mind (e.g. persist progress and dedupe on URL/result ID).

Imports the instructor's own reference solution used (for context, not a
requirement to match exactly): `argparse`, `subprocess`, `time`, `pathlib.Path`,
`typing.List`/`Tuple`, `urllib.parse.urlparse`, `bs4.BeautifulSoup`.

The assignment page also still describes a **prior recommended** pure-Selenium
workflow (urllib to build/validate URLs → Selenium loads + waits for results →
`page_source` → BeautifulSoup/regex/string parse). Treat that as the fallback
if Cloudflare isn't actually blocking things when you get to it — the hybrid
capture approach above is only necessary if the plain approaches get blocked.

## Required deliverables (recap)
- [ ] SSH URL to the GitHub repo (`jhu_software_concepts`, private)
- [ ] `module_2/scrape.py` — scraping logic
- [ ] `module_2/clean.py` — data cleaning logic
- [ ] `module_2/llm_hosting/` — the instructor-provided local-LLM files (as a subpackage)
- [ ] `module_2/applicant_data.json` — raw-ish scraped + parsed data
- [ ] `module_2/llm_extend_applicant_data.json` — cleaned/standardized output
- [ ] `module_2/robots.txt` evidence: `screenshot.jpg` + explanation in README
- [ ] `module_2/README` (readme.txt) — see template below
- [ ] `module_2/requirements.txt`
- Push to GitHub before the deadline; also submit the zipped `module_2` folder
  via Canvas (graders compare timestamps between the two).

## SHALL requirements
- Programmatic Python scraper (Python 3.10+).
- Use `urllib` to construct/inspect/manage Grad Cafe URLs.
- Store scraped data as JSON in `applicant_data.json`, with reasonable,
  descriptive keys.
- At least 30,000 graduate applicant entries.
- README + requirements.txt (full env reconstruction) included.
- Private GitHub repo `jhu_software_concepts`, with all assignment materials
  inside a `module_2` folder.
- Check `robots.txt` before scraping; include a screenshot + written
  explanation of that check in the README.
- Scrape only publicly accessible pages; be polite (avoid rapid repeated
  requests); **stop** if the site blocks/rate-limits/rejects requests rather
  than working around it.
- Clean the data per the cleaning section below.

### Required fields (when available)
Program Name · University · Comments · Date Added to Grad Cafe · URL to the
entry · Applicant Status (Accepted/Rejected/Waitlisted, with acceptance or
rejection date) · Semester + Year of program start · International/American ·
GRE Score · GRE V Score · GRE AW · Masters or PhD · GPA

### Also SHALL
- Preserve the original raw program/applicant listing text for traceability.
- Use a consistent representation for missing values (e.g. `None` or `""`)
  across the dataset.
- `applicant_data.json` must be valid, loadable JSON.

## SHOULD (aim for these)
- Use BeautifulSoup / string methods / regex to extract data.
- Use Selenium when results are dynamically rendered/paginated/hard to reach
  via static `urllib` alone — see the hybrid-approach note above.
- Use Selenium only as a rendering tool for public pages, with **explicit
  waits** for elements (avoid bare `time.sleep()` where an explicit wait works).
- Reasonable delays/throttling between requests; list `selenium` in
  `requirements.txt` if used.
- Document in the README: which approach was used (urllib-only / Selenium /
  hybrid) and, if Selenium, which browser+driver setup.
- Structure: `scrape.py` (scraping), `clean.py` (cleaning), functions/class
  methods named `scrape_data()`, `clean_data()`, `save_data()`, `load_data()`,
  with private helpers underscore-prefixed.
- No leftover HTML tags/entities in final data; handle messy/inconsistent
  data gracefully; keep raw fields alongside cleaned ones.
- Clear comments, well-named variables.

## SHOULD NOT / SHALL NOT (hard limits — do not implement around these)
- Do **not** use tools/methods outside BeautifulSoup, string methods, regex,
  or Selenium page-rendering utilities without approval.
- Do **not** destructively modify the original program field — keep raw +
  cleaned side by side.
- Do **not** hard-code applicant records manually, and do **not** fabricate
  or alter outcomes/dates/scores/universities/programs/comments beyond
  documented cleaning.
- Do **not** scrape anything disallowed by `robots.txt`.
- Do **not** use Selenium/urllib/BeautifulSoup/anything else to bypass
  `robots.txt`, logins, access controls, CAPTCHAs, or rate limits — including
  via browser automation. (See the hybrid-approach note: manual human
  verification once is fine; scripted bypass is not.)
- Do **not** scrape private/login-protected/restricted or unnecessary
  personally-identifying data.
- Do **not** submit code requiring secret API keys, paid services, or
  unrecoverable local paths.
- Do **not** submit `applicant_data.json` in a non-JSON format, and don't
  omit README / requirements.txt / robots.txt evidence / repo structure.

## Data cleaning (Part 2)
Program/university names arrive messy and inconsistently formatted (e.g.
"JHU" vs "Johns Hopkins" vs "Johns Hopkins University" vs "John Hopkins").
The instructor-provided approach:
1. Add the provided zip's contents to the repo as a subpackage:
   `module_2/llm_hosting/`.
2. `cd` into it, `pip install -r requirements.txt`.
3. Run `python app.py --file "your_part_1.json" > out.json` (expect to need
   to debug/adjust slightly for local Python/system — that's expected, per
   the instructor).
4. Parallelize this step across available CPU cores if practical — the
   instructor explicitly recommends this for speed.
5. Output adds two new fields per record: an LLM-standardized program name
   and an LLM-standardized university name, alongside (not replacing) the
   original raw `program` field.
6. Save the final result as `module_2/llm_extend_applicant_data.json`.
7. In the README, document: any edits made to the canonical lists/post-
   processing, and a brief note on systematic edge cases still seen after
   cleaning (this doesn't need to be perfect — outliers get revisited next
   module).

## README (readme.txt) template
```
Name: Caleb Gevert (JHED: cgevert1)
Module Info: Module 2 — Web Scraping — Due [confirm date on Canvas]

Approach:
[Describe the scraping approach used (urllib-only / Selenium / hybrid capture),
why, how pagination/checkpointing/resume works, how parsing extracts each
required field, and how robots.txt was checked. Describe the cleaning
pipeline: local LLM standardization + post-processing/fuzzy-matching, and any
canonical-list edits made.]

Known Bugs:
[List anything not fully working and how you'd fix it, or omit this section
if everything works.]
```

## Grading rubric — quick-reference checklist (100 pts)
- GitHub setup & submission (15): private `jhu_software_concepts` repo,
  organized `module_2` folder, meaningful incremental commits, correct SSH
  URL, Canvas zip matches GitHub.
- Responsible scraping / robots.txt (12): checked before scraping,
  `screenshot.jpg` included, README explains compliance, polite throttling,
  no bypassing.
- Scraping functionality (18): programmatic Python pull, uses `urllib`,
  handles pagination, ≥30,000 entries, rerunnable by grader with no manual
  steps or unrecoverable paths.
- Parsing / required fields (15): program+university, status/date/URL,
  comments, accept/reject date, term, intl/domestic, GRE/GRE V/GRE AW/GPA/degree.
- JSON output (10): `applicant_data.json` present, valid, descriptive keys,
  consistent missing-value handling, raw text preserved.
- Data cleaning / local LLM (12): `llm_hosting/` included, standardization
  actually run, `llm_extend_applicant_data.json` included, original data
  preserved alongside standardized fields, canonical-list/edge-case notes.
- Project structure (10): `scrape.py`, `clean.py`, sufficient
  `requirements.txt`, Python 3.10+, README has clear setup/run instructions.
- Code quality (8): clarity, naming, comments, function/class structure,
  underscore-prefixed private helpers.
