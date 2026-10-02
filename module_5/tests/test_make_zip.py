"""The Canvas submission zip: right contents, no environments/caches/secrets."""

import zipfile

import pytest

import make_zip
from make_zip import archive_entries, build_zip, collect_files

pytestmark = pytest.mark.integration


def _touch(root, relative, text="x"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _names(root):
    return sorted(path.relative_to(root).as_posix() for path in collect_files(root))


DELIVERABLES = (
    "src/load_data.py", "src/flask_app.py", "src/web_assets/templates/analysis.html",
    "src/web_assets/static/style.css", "src/db_setup.sql", "src/llm_hosting/app.py",
    "src/llm_hosting/requirements.txt", "tests/test_buttons.py", "tests/fixtures/page.html",
    "README.md", "requirements.txt", "requirements.in", "setup.py", "pytest.ini",
    "coverage_summary.txt", "pylint_report.txt", "dependency.svg", "dependency.png",
    "snyk-analysis.png", "actions_success.png", "module_5_report.pdf",
    "least_privilege_evidence.txt", ".env.example", ".gitignore",
)


def test_deliverables_are_included(tmp_path):
    for name in DELIVERABLES:
        _touch(tmp_path, name)
    assert _names(tmp_path) == sorted(DELIVERABLES)


def test_environments_caches_secrets_and_generated_files_are_excluded(tmp_path):
    _touch(tmp_path, "src/keep.py")
    for name in (
        ".venv/Scripts/python.exe", "venv/x", "env/y", "src/__pycache__/a.pyc",
        "tests/__pycache__/b.pyc", ".pytest_cache/v/cache/nodeids", "htmlcov/index.html",
        ".coverage", ".coverage.host.123", ".playwright-mcp/page.png", ".claude/settings.json",
        ".env", ".env.local", "CLAUDE.md", "module_5_instructions.pdf",
        "module 5 instructions.pdf", "module_5.zip", "module_4.zip", "module_3.zip",
        "src/llm_shard_0.json", "src/llm_shard_0.jsonl",
        "src/scrape_checkpoint.json", "src/llm_hosting/models/model.gguf",
        "docs/_build/doctrees/index.doctree", "docs/_build/html/.doctrees/index.doctree",
        "docs/_build/html/.buildinfo",
        ".idea/workspace.xml", "dump.dump", "notes.pyc", ".git/HEAD",
        "src/gradcafe_analysis.egg-info/PKG-INFO", "build/lib/load_data.py", "dist/x.whl",
    ):
        _touch(tmp_path, name)
    assert _names(tmp_path) == ["src/keep.py"]


def test_zip_puts_everything_under_module_5_and_adds_the_repo_workflow(tmp_path):
    module_dir = tmp_path / "module_5"
    _touch(module_dir, "src/load_data.py", "print('hi')")
    _touch(module_dir, ".env", "PGPASSWORD=secret")
    _touch(tmp_path, ".github/workflows/ci.yml", "name: module_5 CI")
    out = module_dir / "module_5.zip"

    count = build_zip(module_dir, out)

    with zipfile.ZipFile(out) as archive:
        assert sorted(archive.namelist()) == [
            ".github/workflows/ci.yml", "module_5/src/load_data.py",
        ]
        assert archive.testzip() is None
        assert archive.read(".github/workflows/ci.yml") == b"name: module_5 CI"
    assert count == 2


def test_zip_without_a_workflow_file_still_builds(tmp_path):
    _touch(tmp_path, "a.py")
    entries = archive_entries(tmp_path, tmp_path / "module_5.zip")
    assert [name for _, name in entries] == ["module_5/a.py"]


def test_zip_never_includes_itself(tmp_path):
    _touch(tmp_path, "a.py")
    out = tmp_path / "custom-name.zip"
    build_zip(tmp_path, out)
    build_zip(tmp_path, out)          # rebuilding must not swallow the previous zip
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist() == ["module_5/a.py"]


def test_main_writes_module_5_zip_next_to_src_and_lists_it(tmp_path, monkeypatch, capsys):
    module_dir = tmp_path / "module_5"
    _touch(module_dir, "src/make_zip.py")
    _touch(module_dir, "README.md")
    monkeypatch.setattr(make_zip, "__file__", str(module_dir / "src" / "make_zip.py"))

    assert make_zip.main() == 0

    output = capsys.readouterr().out
    assert "Wrote module_5.zip: 2 files" in output
    assert "module_5/README.md" in output
    assert (module_dir / "module_5.zip").is_file()
