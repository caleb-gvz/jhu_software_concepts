"""Scrape GradCafe survey results into a resumable, checkpointed JSON file."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from bs4 import BeautifulSoup

BASE_URL = "https://www.thegradcafe.com"
SURVEY_PATH = "/survey"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _build_survey_url(cursor: Optional[str] = None) -> str:
    """Build a GradCafe survey URL, optionally paginated by cursor."""
    query = {"cursor": cursor} if cursor else {}
    query_string = urllib.parse.urlencode(query)
    return urllib.parse.urlunparse(
        ("https", "www.thegradcafe.com", SURVEY_PATH, "", query_string, "")
    )


def _check_robots_allowed(
    url: str, parser: urllib.robotparser.RobotFileParser
) -> bool:
    """Check whether our User-Agent may fetch this URL per robots.txt."""
    return parser.can_fetch(USER_AGENT, url)


def _merge_robots_groups(robots_text: str) -> str:
    """Merge multiple robots.txt records for the same user-agent into one.

    Python's urllib.robotparser silently drops every wildcard
    (`User-agent: *`) record after the first one it sees, which would make
    our compliance check miss any Disallow rules declared in a later `*`
    block. GradCafe's real robots.txt has exactly this shape: a
    Cloudflare-managed `*` block, then a separate site-specific `*` block
    with the actual Disallow rules.
    """
    groups: List[Tuple[List[str], List[str]]] = []
    current_agents: List[str] = []
    current_directives: List[str] = []
    agent_block_open = False

    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if not agent_block_open:
                if current_agents:
                    groups.append((current_agents, current_directives))
                current_agents = []
                current_directives = []
            current_agents.append(value)
            agent_block_open = True
        else:
            current_directives.append(f"{field}: {value}")
            agent_block_open = False

    if current_agents:
        groups.append((current_agents, current_directives))

    merged: "OrderedDict[str, List[str]]" = OrderedDict()
    for agents, directives in groups:
        for agent in agents:
            merged.setdefault(agent, []).extend(directives)

    lines: List[str] = []
    for agent, directives in merged.items():
        lines.append(f"User-agent: {agent}")
        lines.extend(_sort_directives_by_specificity(directives))
        lines.append("")
    return "\n".join(lines)


def _sort_directives_by_specificity(directives: List[str]) -> List[str]:
    """Order Allow/Disallow lines by descending path length.

    urllib.robotparser.Entry.allowance() returns the FIRST ruleline (in
    list order) whose path prefix-matches — it does not pick the longest
    (most specific) match like most real crawlers do. Without this
    reordering, a generic "Allow: /" listed before a specific
    "Disallow: /signin" would always win, silently defeating the merge in
    _merge_robots_groups above. Non-rule directives (Sitemap, Crawl-delay,
    Content-Signal, ...) are left in their original relative order.
    """
    rule_lines = []
    other_lines = []
    for directive in directives:
        field = directive.split(":", 1)[0].strip().lower()
        if field in ("allow", "disallow"):
            rule_lines.append(directive)
        else:
            other_lines.append(directive)
    rule_lines.sort(key=lambda d: -len(d.split(":", 1)[1].strip()))
    return rule_lines + other_lines


def _fetch_robots_text(robots_url: str = BASE_URL + "/robots.txt") -> str:
    """Fetch the raw text of a robots.txt file."""
    request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def _load_robots_parser(
    robots_url: str = BASE_URL + "/robots.txt",
) -> urllib.robotparser.RobotFileParser:
    """Fetch robots.txt, merge duplicate user-agent groups, and parse it."""
    merged_text = _merge_robots_groups(_fetch_robots_text(robots_url))
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(merged_text.splitlines())
    return rp


def _fetch_page(url: str, user_agent: str = USER_AGENT) -> str:
    """Fetch a URL's HTML body. Raises on non-2xx (caller decides to stop)."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def _extract_page_records(
    html_text: str,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Pull the Inertia.js `data-page` JSON payload's results off a survey page."""
    soup = BeautifulSoup(html_text, "html.parser")
    app_div = soup.find(id="app")
    if app_div is None or not app_div.has_attr("data-page"):
        raise ValueError("Could not locate data-page payload in survey HTML")
    payload = json.loads(app_div["data-page"])
    results = payload["props"]["results"]
    return results["data"], results["meta"].get("next_cursor")


_DECISION_DATE_FIELDS = (
    "acceptedDate",
    "rejectedDate",
    "waitlistedDate",
    "interviewDate",
)


def _coerce_float(value: Any) -> Optional[float]:
    """Best-effort float coercion; GradCafe's API mixes int/str/None types."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map one GradCafe API record into our applicant_data.json schema."""
    program_raw = (raw.get("program") or "").strip()
    university_raw = (raw.get("school") or "").strip()

    status_date = None
    for field in _DECISION_DATE_FIELDS:
        if raw.get(field):
            status_date = raw[field]
            break

    combined_program = (
        f"{program_raw}, {university_raw}" if university_raw else program_raw
    )

    return {
        "id": raw["id"],
        "url": f"{BASE_URL}/result/{raw['id']}",
        "program_raw": program_raw,
        "university_raw": university_raw,
        "program": combined_program,
        "degree": raw.get("level"),
        "applicant_status": raw.get("decision"),
        "status_date": status_date,
        "status_label_raw": raw.get("decision_label"),
        "term": raw.get("season"),
        "us_or_international": raw.get("status"),
        "gre_score": _coerce_float(raw.get("greq")),
        "gre_v": _coerce_float(raw.get("grev")),
        "gre_aw": _coerce_float(raw.get("grew")),
        "gre_subject": _coerce_float(raw.get("gres")),
        "gpa": _coerce_float(raw.get("ugpa")),
        "comments": raw.get("notes"),
        "date_added": raw.get("added_on_label"),
        "date_added_raw": raw.get("created_at"),
    }


def save_data(records: List[Dict[str, Any]], path: str) -> None:
    """Write records to disk as a single JSON array."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def load_data(path: str) -> List[Dict[str, Any]]:
    """Load records from disk, or an empty list if the file doesn't exist yet."""
    if not Path(path).exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_checkpoint(path: str) -> Dict[str, Any]:
    if not Path(path).exists():
        return {"next_cursor": None, "seen_ids": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_checkpoint(checkpoint: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f)


def scrape_data(
    target_count: int,
    output_path: str = "applicant_data.json",
    checkpoint_path: str = "scrape_checkpoint.json",
    delay_seconds: float = 0.75,
    fetch_fn=_fetch_page,
    robots_parser: Optional[urllib.robotparser.RobotFileParser] = None,
) -> List[Dict[str, Any]]:
    """Scrape GradCafe survey results up to target_count, resumably."""
    checkpoint = _load_checkpoint(checkpoint_path)
    records = load_data(output_path)
    seen_ids = set(checkpoint.get("seen_ids", []))
    cursor = checkpoint.get("next_cursor")

    if robots_parser is None:
        robots_parser = _load_robots_parser()

    pages_since_save = 0
    while len(seen_ids) < target_count:
        url = _build_survey_url(cursor)
        if not _check_robots_allowed(url, robots_parser):
            print(f"robots.txt disallows {url}; stopping.")
            break
        try:
            html_text = fetch_fn(url)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"Request blocked/failed ({exc}); stopping without retry.")
            break

        try:
            page_records, next_cursor = _extract_page_records(html_text)
        except ValueError as exc:
            print(f"Could not parse page ({exc}); stopping.")
            break

        for raw in page_records:
            rid = raw.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            records.append(_parse_record(raw))

        cursor = next_cursor
        pages_since_save += 1
        if pages_since_save >= 25 or next_cursor is None:
            save_data(records, output_path)
            _save_checkpoint(
                {"next_cursor": cursor, "seen_ids": list(seen_ids)}, checkpoint_path
            )
            pages_since_save = 0

        if next_cursor is None:
            print("Reached end of available results.")
            break

        if len(seen_ids) < target_count:
            time.sleep(delay_seconds)

    save_data(records, output_path)
    _save_checkpoint(
        {"next_cursor": cursor, "seen_ids": list(seen_ids)}, checkpoint_path
    )
    return records


class ScrapeError(Exception):
    """A pull could not continue (blocked, offline, unreadable page, robots.txt).

    ``partial_records`` holds any records gathered before the failure so the caller
    can still keep them.
    """

    def __init__(
        self, message: str, partial_records: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        super().__init__(message)
        self.partial_records = partial_records or []


def scrape_new_records(
    known_ids: Set[int],
    max_pages: int = 20,
    delay_seconds: float = 0.75,
    fetch_fn=_fetch_page,
    robots_parser: Optional[urllib.robotparser.RobotFileParser] = None,
) -> List[Dict[str, Any]]:
    """Fetch the newest survey pages and return records whose id is not in known_ids.

    Grad Cafe lists newest entries first, so this starts at the first page (no
    cursor) and walks forward until it reaches a page with nothing new, runs out of
    pages, or hits ``max_pages``. It reuses this module's URL builder, robots.txt
    check, page parser, and record parser, so the results have exactly the same
    schema as ``scrape_data``. Any failure raises ScrapeError with a readable
    message and whatever was collected so far.
    """
    new_records: List[Dict[str, Any]] = []
    seen_ids = set(known_ids)

    if robots_parser is None:
        try:
            robots_parser = _load_robots_parser()
        except urllib.error.HTTPError as exc:
            raise ScrapeError(f"Could not read robots.txt (HTTP {exc.code}).") from exc
        except urllib.error.URLError as exc:
            raise ScrapeError(f"Could not reach Grad Cafe ({exc.reason}).") from exc

    cursor: Optional[str] = None
    for _ in range(max_pages):
        url = _build_survey_url(cursor)
        if not _check_robots_allowed(url, robots_parser):
            raise ScrapeError(f"robots.txt disallows fetching {url}.", new_records)
        try:
            html_text = fetch_fn(url)
        except urllib.error.HTTPError as exc:
            raise ScrapeError(
                f"Grad Cafe blocked or rejected the request (HTTP {exc.code}).",
                new_records,
            ) from exc
        except urllib.error.URLError as exc:
            raise ScrapeError(
                f"Could not reach Grad Cafe ({exc.reason}).", new_records
            ) from exc

        try:
            page_records, next_cursor = _extract_page_records(html_text)
        except ValueError as exc:
            raise ScrapeError(
                f"Could not read the Grad Cafe page ({exc}).", new_records
            ) from exc

        fresh = [raw for raw in page_records if raw.get("id") not in seen_ids]
        for raw in fresh:
            seen_ids.add(raw["id"])
            new_records.append(_parse_record(raw))

        if not fresh or next_cursor is None:
            break  # reached entries we already have, or the last page
        cursor = next_cursor
        time.sleep(delay_seconds)

    return new_records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape GradCafe survey results into a JSON file."
    )
    parser.add_argument("--target", type=int, default=40000)
    parser.add_argument("--output", default="applicant_data.json")
    parser.add_argument("--checkpoint", default="scrape_checkpoint.json")
    parser.add_argument("--delay", type=float, default=0.75)
    args = parser.parse_args()

    records = scrape_data(
        target_count=args.target,
        output_path=args.output,
        checkpoint_path=args.checkpoint,
        delay_seconds=args.delay,
    )
    print(f"Scraped {len(records)} records -> {args.output}")


if __name__ == "__main__":
    main()
