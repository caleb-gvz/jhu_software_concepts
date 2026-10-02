"""Build ``module_5.zip`` for the Canvas upload.

    python src/make_zip.py

The archive holds the whole ``module_5`` folder under a top-level ``module_5/``
directory, plus the repository's CI workflow at ``.github/workflows/tests.yml`` (it lives
one level above ``module_5`` in the repo). Everything the assignment says not to submit
is left out: virtual environments, caches (``__pycache__``, ``.pytest_cache``,
``.coverage``, ``htmlcov``), credentials (``.env``), the instructions PDF, the
multi-hundred-MB LLM model, intermediate LLM work files, Sphinx's doctree cache, and
Claude Code files.
"""

from __future__ import annotations

import fnmatch
import os
import sys
import zipfile
from pathlib import Path
from typing import List, Tuple

ARCHIVE_ROOT = "module_5"
ZIP_NAME = "module_5.zip"
WORKFLOW_RELATIVE_PATH = ".github/workflows/tests.yml"

EXCLUDED_DIRECTORIES = {
    ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".playwright-mcp", ".claude", ".idea", ".vscode", ".git", "htmlcov",
}
# Relative POSIX paths of directories to skip (LLM weights, Sphinx's pickled doctrees).
EXCLUDED_RELATIVE_DIRECTORIES = {
    "src/llm_hosting/models", "docs/_build/doctrees", "docs/_build/html/.doctrees",
}
EXCLUDED_FILE_NAMES = {
    ".env", ".coverage", "CLAUDE.md", "CLAUDE.local.md", "module 5 instructions.pdf",
    "module_3.zip", ZIP_NAME, "scrape_checkpoint.json", ".DS_Store", "Thumbs.db",
    ".buildinfo",
}
EXCLUDED_FILE_PATTERNS = (
    "*.pyc", "*.pyo", "*.jsonl", "*.gguf", "*.dump", "*.backup", "llm_shard_*.json",
    ".env.*", ".coverage.*",
)
ALLOWED_DESPITE_PATTERNS = {".env.example"}


def _is_excluded_file(name: str) -> bool:
    """True for files that must never be submitted (secrets, caches, work files)."""
    if name in ALLOWED_DESPITE_PATTERNS:
        return False
    return name in EXCLUDED_FILE_NAMES or any(
        fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS
    )


def collect_files(module_dir: Path) -> List[Path]:
    """Every file under ``module_dir`` that belongs in the submission, sorted."""
    module_dir = Path(module_dir)
    included: List[Path] = []
    for directory, subdirectories, file_names in os.walk(module_dir):
        relative_directory = Path(directory).relative_to(module_dir).as_posix()
        prefix = "" if relative_directory == "." else f"{relative_directory}/"
        subdirectories[:] = [
            name for name in subdirectories
            if name not in EXCLUDED_DIRECTORIES
            and f"{prefix}{name}" not in EXCLUDED_RELATIVE_DIRECTORIES
        ]
        for file_name in file_names:
            if not _is_excluded_file(file_name):
                included.append(Path(directory) / file_name)
    return sorted(included)


def archive_entries(module_dir: Path, out_path: Path) -> List[Tuple[Path, str]]:
    """(source file, name inside the zip) for every file the archive will contain."""
    module_dir = Path(module_dir)
    entries = [
        (path, f"{ARCHIVE_ROOT}/{path.relative_to(module_dir).as_posix()}")
        for path in collect_files(module_dir)
        if path.resolve() != Path(out_path).resolve()
    ]
    workflow = module_dir.parent / WORKFLOW_RELATIVE_PATH
    if workflow.is_file():
        entries.append((workflow, WORKFLOW_RELATIVE_PATH))
    return entries


def build_zip(module_dir: Path, out_path: Path) -> int:
    """Write the archive and return how many files it contains."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    entries = archive_entries(module_dir, out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in entries:
            archive.write(path, name)
    return len(entries)


def main() -> int:
    """Build ``module_5/module_5.zip`` and list its contents."""
    module_dir = Path(__file__).resolve().parents[1]
    out_path = module_dir / ZIP_NAME
    count = build_zip(module_dir, out_path)
    size_mb = out_path.stat().st_size / 1_000_000
    print(f"Wrote {out_path.name}: {count} files, {size_mb:.1f} MB")
    with zipfile.ZipFile(out_path) as archive:
        for name in archive.namelist():
            print("  ", name)
    return 0


if __name__ == "__main__":  # pragma: no cover  (only calls main(), which is tested)
    sys.exit(main())
