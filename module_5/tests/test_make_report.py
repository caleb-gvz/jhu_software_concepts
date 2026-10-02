"""``make_report.py``: README sections + evidence files -> module_5_report.pdf."""

from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.platypus import Image, Paragraph, Preformatted, Table

import make_report
from make_report import (
    EVIDENCE,
    REPORT_SECTIONS,
    ReportError,
    build_report,
    inline_markup,
    markdown_flowables,
    read_sections,
)

pytestmark = pytest.mark.db

REAL_MODULE_DIR = Path(__file__).resolve().parents[1]

README = """\
# Title

Intro paragraph that is not in any section.

## Fresh Install

Plain paragraph with `code`, **bold**, *italic* and a [link](https://example.com).
A second line of the same paragraph.

### A subheading

* first bullet with `x < y & z`
* second bullet
1. numbered one
2. numbered two

```bash
pip install -r requirements.txt   # a command
```

| Column A | Column B |
|---|---|
| a1 | b1 `code` |
| a2 | b2 |

## Other Section

Not selected for the report.
"""


def _text(path):
    return "\n".join(page.extract_text() for page in PdfReader(str(path)).pages)


def _png(path, size=(40, 20)):
    from PIL import Image as PilImage

    PilImage.new("RGB", size, (200, 30, 30)).save(path)


def _module_dir(tmp_path, sections=REPORT_SECTIONS, evidence=True):
    """A fake module folder: a README with every report section, plus evidence files."""
    body = "# Title\n\n" + "\n".join(
        f"## {name}\n\nText of the {name} section.\n" for name in sections
    )
    (tmp_path / "README.md").write_text(body, encoding="utf-8")
    if evidence:
        for item in EVIDENCE:
            target = tmp_path / item.filename
            if item.kind == "image":
                _png(target)
            else:
                target.write_text(f"EVIDENCE-FROM-{item.filename}\nsecond line", encoding="utf-8")
    return tmp_path


# ---- reading the README -------------------------------------------------------------------

def test_read_sections_splits_on_level_two_headings_and_ignores_the_preamble():
    sections = read_sections(README)

    assert list(sections) == ["Fresh Install", "Other Section"]
    assert "Intro paragraph" not in "\n".join(sections["Fresh Install"])
    assert sections["Other Section"] == ["", "Not selected for the report."]


# ---- inline markup ------------------------------------------------------------------------

def test_inline_markup_converts_bold_italic_code_and_links_and_escapes_xml():
    out = inline_markup("**b** and *i* and `x < y & z` and [site](https://example.com)")

    assert "<b>b</b>" in out and "<i>i</i>" in out
    assert "x &lt; y &amp; z" in out and "<font" in out
    assert "site (https://example.com)" in out
    assert "<y" not in out                                   # nothing unescaped survives


def test_bold_text_may_contain_inline_code():
    out = inline_markup("**Permissions granted to `gradcafe_m5_app`, and why**")

    assert "**" not in out
    assert out.startswith("<b>") and out.endswith("</b>")
    assert "gradcafe_m5_app</font>" in out


def test_every_heading_style_keeps_with_the_content_that_follows_it():
    # Otherwise an "Evidence: ..." heading can be stranded at the foot of a page while its
    # screenshot starts on the next one.
    styles = make_report.build_styles()

    assert all(styles[name].keepWithNext for name in ("h1", "h2", "h3"))


def test_inline_markup_leaves_stars_inside_code_alone():
    assert "*args" in inline_markup("call `f(*args)` now")


# ---- block conversion ---------------------------------------------------------------------

def test_markdown_flowables_produce_paragraphs_bullets_code_and_tables():
    lines = read_sections(README)["Fresh Install"]
    flowables = markdown_flowables(lines)

    kinds = [type(item) for item in flowables]
    assert Table in kinds and Preformatted in kinds and Paragraph in kinds
    texts = [item.text for item in flowables if isinstance(item, Paragraph)]
    assert any("A second line of the same paragraph" in text for text in texts)  # lines joined
    assert any(text == "A subheading" or "A subheading" in text for text in texts)
    bullets = [item for item in flowables if isinstance(item, Paragraph) and item.bulletText]
    assert [b.bulletText for b in bullets] == ["•", "•", "1.", "2."]
    code = [item for item in flowables if isinstance(item, Preformatted)][0]
    assert "pip install -r requirements.txt" in "\n".join(code.lines)


def test_a_table_column_is_never_narrower_than_its_longest_unbroken_word():
    rows = [
        "| Role | Purpose | Holds |",
        "|---|---|---|",
        "| `gradcafe_m5_owner` | " + "A long explanation made of many short words. " * 6
        + " | Ownership of everything, as the schema owner |",
    ]

    table = make_report._table(rows, make_report.build_styles())

    assert table._colWidths[0] >= len("gradcafe_m5_owner") * 5.4 + 12      # text + cell padding
    assert sum(table._colWidths) == pytest.approx(make_report.TEXT_WIDTH)


def test_columns_shrink_evenly_when_their_unbreakable_words_cannot_all_fit():
    word = "w" * 80
    widths = make_report._column_widths([[word, word, word], [word, word, word]])

    assert sum(widths) == pytest.approx(make_report.TEXT_WIDTH)
    assert widths[0] == pytest.approx(widths[1]) == pytest.approx(widths[2])


def test_very_long_code_lines_are_wrapped_so_they_stay_on_the_page():
    long_line = "x" * 300
    flowables = markdown_flowables(["```", long_line, "```"])

    code = [item for item in flowables if isinstance(item, Preformatted)][0]
    assert max(len(line) for line in code.lines) <= make_report.CODE_WIDTH_CHARS
    assert "".join(code.lines).replace(" ", "") == long_line


def test_an_unterminated_code_fence_still_renders_what_was_collected():
    flowables = markdown_flowables(["```", "orphan line"])

    assert "orphan line" in "\n".join(
        [item for item in flowables if isinstance(item, Preformatted)][0].lines
    )


# ---- building the PDF ---------------------------------------------------------------------

def test_build_report_writes_a_pdf_with_a_cover_every_section_and_all_evidence(tmp_path):
    module = _module_dir(tmp_path)
    out = tmp_path / "report.pdf"

    missing = build_report(module, out, strict=True)

    text = _text(out)
    assert missing == []
    assert "Caleb Gevertz" in text and "cgevert1" in text and "Module 5" in text
    for name in REPORT_SECTIONS:
        assert f"Text of the {name} section." in text
    for item in EVIDENCE:
        assert item.title in text
        if item.kind == "text":
            assert f"EVIDENCE-FROM-{item.filename}" in text


def test_evidence_follows_the_section_it_belongs_to(tmp_path):
    module = _module_dir(tmp_path)
    out = tmp_path / "report.pdf"
    build_report(module, out)

    text = _text(out)
    for item in EVIDENCE:
        assert text.index(f"Text of the {item.after} section.") < text.index(item.title)


def test_missing_evidence_is_noted_in_the_pdf_and_reported_to_the_caller(tmp_path):
    module = _module_dir(tmp_path, evidence=False)
    out = tmp_path / "report.pdf"

    missing = build_report(module, out)

    required = [item.filename for item in EVIDENCE if item.required]
    assert missing == required
    assert "not found" in _text(out)


def test_optional_evidence_is_skipped_silently_when_absent(tmp_path):
    module = _module_dir(tmp_path)
    optional = [item for item in EVIDENCE if not item.required]
    assert optional, "the extra-credit Snyk Code evidence should be optional"
    for item in optional:
        (module / item.filename).unlink()
    out = tmp_path / "report.pdf"

    assert build_report(module, out, strict=True) == []
    assert all(item.title not in _text(out) for item in optional)


def test_a_readme_without_a_report_section_is_an_error(tmp_path):
    module = _module_dir(tmp_path, sections=REPORT_SECTIONS[:-1])

    with pytest.raises(ReportError, match=REPORT_SECTIONS[-1]):
        build_report(module, tmp_path / "report.pdf")


def test_images_are_scaled_to_fit_the_page_width(tmp_path):
    big = tmp_path / "big.png"
    _png(big, size=(4000, 3000))

    image = make_report.fit_image(big, max_width=400, max_height=500)

    assert isinstance(image, Image)
    assert image.drawWidth <= 400 and image.drawHeight <= 500
    assert image.drawWidth / image.drawHeight == pytest.approx(4000 / 3000)


def test_main_builds_the_pdf_next_to_the_readme_and_reports_success(tmp_path, monkeypatch, capsys):
    module = _module_dir(tmp_path)
    monkeypatch.setattr(make_report, "MODULE_DIR", module)

    assert make_report.main([]) == 0

    assert (module / "module_5_report.pdf").stat().st_size > 1000
    assert "Wrote module_5_report.pdf" in capsys.readouterr().out


def test_main_strict_fails_and_names_the_missing_evidence(tmp_path, monkeypatch, capsys):
    module = _module_dir(tmp_path, evidence=False)
    monkeypatch.setattr(make_report, "MODULE_DIR", module)

    assert make_report.main(["--strict"]) == 1

    err = capsys.readouterr().err
    for item in EVIDENCE:
        if item.required:
            assert item.filename in err


def test_main_without_strict_still_builds_but_warns_about_missing_evidence(
    tmp_path, monkeypatch, capsys
):
    module = _module_dir(tmp_path, evidence=False)
    monkeypatch.setattr(make_report, "MODULE_DIR", module)

    assert make_report.main([]) == 0

    captured = capsys.readouterr()
    assert (module / "module_5_report.pdf").is_file()
    assert "Warning: evidence not found" in captured.err
    assert "snyk-analysis.png" in captured.err


def test_main_reports_a_missing_report_section_instead_of_crashing(tmp_path, monkeypatch, capsys):
    module = _module_dir(tmp_path, sections=REPORT_SECTIONS[:-1])
    monkeypatch.setattr(make_report, "MODULE_DIR", module)

    assert make_report.main([]) == 2
    assert REPORT_SECTIONS[-1] in capsys.readouterr().err


def test_the_real_readme_contains_every_section_the_report_needs():
    sections = read_sections((REAL_MODULE_DIR / "README.md").read_text(encoding="utf-8"))

    assert [name for name in REPORT_SECTIONS if name not in sections] == []


def test_the_report_covers_every_topic_the_assignment_requires(tmp_path):
    out = tmp_path / "real.pdf"
    build_report(REAL_MODULE_DIR, out)   # non-strict: evidence screenshots may not exist yet

    text = " ".join(_text(out).split()).lower()
    for phrase in (
        "pip install -r requirements.txt",          # install with pip
        "uv pip sync",                              # install with uv
        "key dependencies",                         # dependency graph summary
        "sql injection defenses",
        "sql.identifier",                           # safe composition
        "construction is separate from execution",
        "clamp_limit",                              # LIMIT enforcement
        "least-privilege",
        "gradcafe_m5_app",                          # the role and its grants
        "why packaging matters",
        "github actions",
    ):
        assert phrase in text, phrase
