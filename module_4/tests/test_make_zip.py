import zipfile

from make_zip import build_zip, collect_files


def _touch(root, relative, text="x"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _names(root):
    return sorted(path.relative_to(root).as_posix() for path in collect_files(root))


def test_deliverables_are_included(tmp_path):
    for name in ("load_data.py", "README.md", "requirements.txt", "github.txt", "query_results.pdf",
                 "templates/analysis.html", "static/style.css", "screenshots/flask_page.png",
                 ".env.example", ".gitignore", "llm_hosting/app.py", "llm_hosting/requirements.txt"):
        _touch(tmp_path, name)
    assert _names(tmp_path) == sorted([
        "load_data.py", "README.md", "requirements.txt", "github.txt", "query_results.pdf",
        "templates/analysis.html", "static/style.css", "screenshots/flask_page.png",
        ".env.example", ".gitignore", "llm_hosting/app.py", "llm_hosting/requirements.txt",
    ])


def test_environments_caches_secrets_and_generated_files_are_excluded(tmp_path):
    _touch(tmp_path, "keep.py")
    for name in (
        ".venv/Scripts/python.exe", "venv/x", "__pycache__/a.pyc", "tests/__pycache__/b.pyc",
        ".pytest_cache/v/cache", ".playwright-mcp/page.png", ".claude/settings.json",
        ".env", "CLAUDE.md", "module 3 instructions.pdf", "module_3.zip",
        "llm_shard_0.json", "llm_shard_0.jsonl", "llm_extend.jsonl", "scrape_checkpoint.json",
        "llm_hosting/models/model.gguf", ".idea/workspace.xml", "dump.dump", "notes.pyc",
    ):
        _touch(tmp_path, name)
    assert _names(tmp_path) == ["keep.py"]


def test_zip_contains_everything_under_a_module_3_folder(tmp_path):
    _touch(tmp_path, "load_data.py", "print('hi')")
    _touch(tmp_path, "static/style.css", "body{}")
    _touch(tmp_path, ".env", "PGPASSWORD=secret")
    out = tmp_path / "out" / "module_3.zip"

    count = build_zip(tmp_path, out)

    with zipfile.ZipFile(out) as archive:
        assert sorted(archive.namelist()) == ["module_3/load_data.py", "module_3/static/style.css"]
        assert archive.testzip() is None
    assert count == 2


def test_zip_never_includes_itself(tmp_path):
    _touch(tmp_path, "a.py")
    out = tmp_path / "module_3.zip"
    build_zip(tmp_path, out)
    build_zip(tmp_path, out)          # rebuilding must not swallow the previous zip
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist() == ["module_3/a.py"]
