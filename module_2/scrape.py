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
from typing import Any, Dict, List, Optional, Tuple

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


def _check_robots_allowed(
    url: str, parser: urllib.robotparser.RobotFileParser
) -> bool:
    """Check whether our User-Agent may fetch this URL per robots.txt."""
    return parser.can_fetch(USER_AGENT, url)
