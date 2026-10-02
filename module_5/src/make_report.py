"""Build ``module_5_report.pdf`` from the README and the evidence files.

    python src/make_report.py            # build with whatever evidence exists
    python src/make_report.py --strict   # refuse to build if required evidence is missing

The report explains the work (installing with pip and uv, the dependency graph, the SQL
injection defenses, the least-privilege database, Pylint, Snyk, CI) by rendering the
matching README sections, so the PDF and the README can never disagree. After each
section it appends the evidence that belongs to it: command output captured to text
files, and screenshots. A small, tested Markdown subset is rendered (headings,
paragraphs, bullets, fenced code, tables, bold/italic/inline code, links).
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Dict, List, Optional, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    Image,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MODULE_DIR = Path(__file__).resolve().parents[1]
REPORT_NAME = "module_5_report.pdf"
STUDENT = "Caleb Gevertz"
JHED = "cgevert1"

PAGE_MARGIN = 0.8 * inch
TEXT_WIDTH = letter[0] - 2 * PAGE_MARGIN
CODE_WIDTH_CHARS = 98          # Courier 7.5pt fits about 107 characters across TEXT_WIDTH

# README "## " headings, in the order they appear in the PDF.
REPORT_SECTIONS = (
    "Fresh Install",
    "Running",
    "Packaging: why setup.py matters",
    "Dependency graph",
    "SQL injection defenses",
    "Least-privilege database",
    "Static analysis: Pylint (10/10)",
    "Snyk dependency scan",
    "Continuous integration",
    "Tests",
)


@dataclass(frozen=True)
class Evidence:
    """A file appended to the PDF right after the README section it supports."""

    title: str
    filename: str
    kind: str            # "text" (shown verbatim) or "image"
    after: str           # the README section it follows
    required: bool = True


EVIDENCE = (
    Evidence("Dependency graph (rendered from dependency.svg)", "dependency.png", "image",
             "Dependency graph"),
    Evidence("Least-privilege evidence: psql output", "least_privilege_evidence.txt", "text",
             "Least-privilege database"),
    Evidence("Pylint output", "pylint_report.txt", "text", "Static analysis: Pylint (10/10)"),
    Evidence("snyk test (snyk-analysis.png)", "snyk-analysis.png", "image",
             "Snyk dependency scan"),
    Evidence("snyk code test (extra credit)", "snyk-code-analysis.png", "image",
             "Snyk dependency scan", required=False),
    Evidence("GitHub Actions: a successful run", "actions_success.png", "image",
             "Continuous integration"),
    Evidence("Test and coverage summary", "coverage_summary.txt", "text", "Tests"),
)


class ReportError(Exception):
    """The report cannot be built (for example a README section is missing)."""


class MissingEvidenceError(ReportError):
    """``--strict`` was requested and required evidence files are missing."""

    def __init__(self, missing: Sequence[str]) -> None:
        super().__init__("required evidence is missing: " + ", ".join(missing))
        self.missing = list(missing)


# ---- reading and converting Markdown ----------------------------------------------------

def read_sections(readme_text: str) -> Dict[str, List[str]]:
    """``{heading: lines}`` for every ``## `` section (text before the first is ignored)."""
    sections: Dict[str, List[str]] = {}
    current: Optional[List[str]] = None
    in_fence = False
    for line in readme_text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            current = sections.setdefault(line[3:].strip(), [])
        elif current is not None:
            current.append(line)
    return sections


def ascii_safe(text: str) -> str:
    """Replace characters the built-in PDF fonts cannot draw (they would show as boxes)."""
    replacements = {"→": "->", "≥": ">=", "≤": "<=", "…": "...", "×": "x"}
    for char, plain in replacements.items():
        text = text.replace(char, plain)
    return text.encode("cp1252", "replace").decode("cp1252")


def inline_markup(text: str) -> str:
    """Markdown inline syntax -> ReportLab paragraph markup (XML-escaped)."""
    code_spans: List[str] = []

    def stash(match: re.Match) -> str:
        code_spans.append(f'<font face="Courier" size="9">{escape(match.group(1))}</font>')
        return f"\x00{len(code_spans) - 1}\x00"          # a placeholder bold/italic skip over

    converted = escape(re.sub(r"`([^`]+)`", stash, ascii_safe(text)))
    converted = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", converted)
    converted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", converted)
    converted = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", converted)
    return re.sub(r"\x00(\d+)\x00", lambda match: code_spans[int(match.group(1))], converted)


def build_styles() -> Dict[str, ParagraphStyle]:
    """Paragraph styles used by the report."""
    base = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=base["BodyText"], fontSize=9.5, leading=13, spaceAfter=5)
    return {
        "title": ParagraphStyle("T", parent=base["Title"], fontSize=22, leading=27),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontSize=15, spaceBefore=6,
                             keepWithNext=1),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontSize=12, spaceBefore=8,
                             keepWithNext=1),
        "h3": ParagraphStyle("H3", parent=base["Heading3"], fontSize=10.5, spaceBefore=6,
                             keepWithNext=1),
        "body": body,
        "bullet": ParagraphStyle("Bullet", parent=body, leftIndent=16, bulletIndent=4),
        "cell": ParagraphStyle("Cell", parent=body, fontSize=8.5, leading=11, spaceAfter=0),
        "code": ParagraphStyle("Code", fontName="Courier", fontSize=7.5, leading=9,
                               backColor=colors.whitesmoke, borderPadding=3, spaceAfter=6),
    }


def code_block(lines: Sequence[str], style: ParagraphStyle) -> Preformatted:
    """Monospaced block; lines longer than the page are wrapped with an indent."""
    wrapped: List[str] = []
    for line in lines:
        text = ascii_safe(line.rstrip())
        wrapped.extend(
            textwrap.wrap(text, CODE_WIDTH_CHARS, subsequent_indent="    ",
                          replace_whitespace=False, drop_whitespace=False,
                          break_long_words=True) or [""]
        )
    return Preformatted("\n".join(wrapped), style)


def _column_widths(cells: Sequence[Sequence[str]]) -> List[float]:
    """Widths summing to ``TEXT_WIDTH``: no column narrower than its longest unbroken word
    (plus cell padding); the remaining space is shared in proportion to how much text a
    column holds."""
    columns = range(len(cells[0]))
    floors = [
        5.4 * max(len(word) for row in cells for word in re.sub(r"[`*]", "", row[col]).split())
        + 12
        for col in columns
    ]
    weights = [min(max(len(row[col]) for row in cells), 60) + 8 for col in columns]
    spare = TEXT_WIDTH - sum(floors)
    if spare <= 0:                                  # more text than fits: shrink all evenly
        return [width * TEXT_WIDTH / sum(floors) for width in floors]
    return [floor + spare * weight / sum(weights) for floor, weight in zip(floors, weights)]


def _table(rows: Sequence[str], styles: Dict[str, ParagraphStyle]) -> Table:
    """A Markdown pipe table; the separator row is dropped and columns are weighted by text."""
    cells = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
    cells = [row for row in cells if not all(re.fullmatch(r":?-{3,}:?", c) for c in row)]
    widths = _column_widths(cells)
    data = [[Paragraph(inline_markup(c), styles["cell"]) for c in row] for row in cells]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


@dataclass
class _MarkdownReader:
    """Walks README lines once and collects flowables."""

    lines: Sequence[str]
    styles: Dict[str, ParagraphStyle]
    flowables: List[Flowable] = field(default_factory=list)
    _text: List[str] = field(default_factory=list)      # the paragraph or list item in progress
    _bullet: Optional[str] = None

    ITEM: ClassVar[re.Pattern] = re.compile(r"^\s*([*-]|\d+\.)\s+(.*)$")

    def _flush(self) -> None:
        if self._text:
            style = self.styles["body" if self._bullet is None else "bullet"]
            self.flowables.append(
                Paragraph(inline_markup(" ".join(self._text)), style, bulletText=self._bullet)
            )
        self._text, self._bullet = [], None

    def _take_while(self, start: int, keep) -> int:
        """Index of the first line at or after ``start`` for which ``keep`` is false."""
        end = start
        while end < len(self.lines) and keep(self.lines[end]):
            end += 1
        return end

    def read(self) -> List[Flowable]:
        """Convert every line to flowables."""
        index = 0
        while index < len(self.lines):
            index = self._read_block(index)
        self._flush()
        return self.flowables

    def _read_block(self, index: int) -> int:
        line = self.lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            self._flush()
            end = self._take_while(index + 1, lambda text: not text.strip().startswith("```"))
            self.flowables.append(code_block(self.lines[index + 1:end], self.styles["code"]))
            return end + 1                                  # skip the closing fence
        if stripped.startswith("|"):
            self._flush()
            end = self._take_while(index, lambda text: text.strip().startswith("|"))
            self.flowables.append(_table(self.lines[index:end], self.styles))
            self.flowables.append(Spacer(1, 6))
            return end
        heading = re.match(r"^(#{3,4})\s+(.*)$", stripped)
        if heading:
            self._flush()
            self.flowables.append(Paragraph(inline_markup(heading.group(2)), self.styles["h3"]))
            return index + 1
        item = self.ITEM.match(line)
        if item:
            self._flush()
            marker = item.group(1)
            self._bullet = "•" if marker in "*-" else marker
            self._text = [item.group(2)]
            return index + 1
        if not stripped:
            self._flush()
        else:
            self._text.append(stripped)
        return index + 1


def markdown_flowables(lines: Sequence[str], styles: Optional[Dict[str, ParagraphStyle]] = None
                       ) -> List[Flowable]:
    """Convert README lines (one section's body) to ReportLab flowables."""
    return _MarkdownReader(lines, styles or build_styles()).read()


# ---- evidence ---------------------------------------------------------------------------

def fit_image(path: Path, max_width: float, max_height: float) -> Image:
    """An image scaled down (never up) to fit the box, keeping its proportions."""
    image = Image(str(path))
    scale = min(1.0, max_width / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    return image


def _evidence_flowables(item: Evidence, module_dir: Path, styles: Dict[str, ParagraphStyle]
                        ) -> List[Flowable]:
    path = module_dir / item.filename
    heading = Paragraph(f"Evidence: {inline_markup(item.title)}", styles["h3"])
    if not path.is_file():
        note = Paragraph(f"<i>{escape(item.filename)} not found.</i>", styles["body"])
        return [heading, note] if item.required else []
    if item.kind == "image":
        return [heading, fit_image(path, TEXT_WIDTH, 6.5 * inch), Spacer(1, 8)]
    text = path.read_text(encoding="utf-8").splitlines()
    return [heading, code_block(text, styles["code"])]


def _cover(styles: Dict[str, ParagraphStyle]) -> List[Flowable]:
    details = [
        ["Student", f"{STUDENT} (JHED: {JHED})"],
        ["Course", "Modern Software Concepts in Python, Johns Hopkins University"],
        ["Assignment", "Module 5 - Software Assurance + Secure SQL (SQLi Defense)"],
        ["Date", datetime.date.today().isoformat()],
        ["Repository", "jhu_software_concepts / module_5"],
    ]
    table = Table([[Paragraph(f"<b>{k}</b>", styles["cell"]), Paragraph(escape(v), styles["cell"])]
                   for k, v in details], colWidths=[1.3 * inch, TEXT_WIDTH - 1.3 * inch])
    table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
    contents = "; ".join(REPORT_SECTIONS)
    return [
        Spacer(1, 1.2 * inch),
        Paragraph("Module 5 Report", styles["title"]),
        Paragraph("Software Assurance + Secure SQL (SQLi Defense)", styles["h2"]),
        Spacer(1, 0.3 * inch), table, Spacer(1, 0.3 * inch),
        Paragraph(f"<b>Contents:</b> {escape(contents)}.", styles["body"]),
        PageBreak(),
    ]


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(letter[0] / 2, 0.45 * inch, f"Module 5 report - page {doc.page}")
    canvas.restoreState()


# ---- building the PDF -------------------------------------------------------------------

def build_report(module_dir: Path, output_path: Optional[Path] = None,
                 strict: bool = False) -> List[str]:
    """Write the PDF and return the names of required evidence files that were missing.

    With ``strict`` a missing required evidence file raises ``MissingEvidenceError``
    *before* anything is written. A README without one of ``REPORT_SECTIONS`` always raises
    ``ReportError``.
    """
    sections = read_sections((module_dir / "README.md").read_text(encoding="utf-8"))
    absent = [name for name in REPORT_SECTIONS if name not in sections]
    if absent:
        raise ReportError("README.md has no section: " + ", ".join(absent))
    missing = [item.filename for item in EVIDENCE
               if item.required and not (module_dir / item.filename).is_file()]
    if strict and missing:
        raise MissingEvidenceError(missing)

    styles = build_styles()
    story: List[Flowable] = _cover(styles)
    for name in REPORT_SECTIONS:
        story.append(Paragraph(inline_markup(name), styles["h1"]))
        story.extend(markdown_flowables(sections[name], styles))
        for item in EVIDENCE:
            if item.after == name:
                story.extend(_evidence_flowables(item, module_dir, styles))
    document = SimpleDocTemplate(
        str(output_path or module_dir / REPORT_NAME), pagesize=letter,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN, topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN, title="Module 5 Report", author=STUDENT,
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return missing


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point: build the report next to the README."""
    parser = argparse.ArgumentParser(description="Build module_5_report.pdf.")
    parser.add_argument("--strict", action="store_true",
                        help="exit with status 1 instead of building if evidence is missing")
    args = parser.parse_args(argv)
    try:
        missing = build_report(MODULE_DIR, strict=args.strict)
    except MissingEvidenceError as exc:
        print(f"Not building: {exc}", file=sys.stderr)
        return 1
    except ReportError as exc:
        print(f"Cannot build the report: {exc}", file=sys.stderr)
        return 2
    if missing:
        print("Warning: evidence not found: " + ", ".join(missing), file=sys.stderr)
    print(f"Wrote {REPORT_NAME}")
    return 0


if __name__ == "__main__":  # pragma: no cover  (only calls main(), which is tested)
    sys.exit(main())
