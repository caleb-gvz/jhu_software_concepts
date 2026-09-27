"""Build ``module_3.zip`` for Canvas.

    python make_zip.py

The archive holds the whole ``module_3`` folder (under a top-level ``module_3/``
directory) minus everything the assignment says not to submit: virtual
environments, caches, credentials (``.env``), the instructions PDF, the multi-hundred-MB
LLM model, intermediate LLM work files, and Claude Code files.
"""

from __future__ import annotations

import fnmatch
import os
import sys
import zipfile
from pathlib import Path
from typing import List

ARCHIVE_ROOT = "module_3"

EXCLUDED_DIRECTORIES = {
    ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".playwright-mcp", ".claude", ".idea", ".vscode", ".git",
}
# Relative POSIX paths of directories to skip (the downloaded LLM weights).
EXCLUDED_RELATIVE_DIRECTORIES = {"llm_hosting/models"}
EXCLUDED_FILE_NAMES = {
    ".env", "CLAUDE.md", "CLAUDE.local.md", "module 3 instructions.pdf", "module_3.zip",
    "scrape_checkpoint.json", ".DS_Store", "Thumbs.db",
}
EXCLUDED_FILE_PATTERNS = (
    "*.pyc", "*.pyo", "*.jsonl", "*.gguf", "*.dump", "*.backup", "llm_shard_*.json", ".env.*",
)
ALLOWED_DESPITE_PATTERNS = {".env.example"}


def _is_excluded_file(name: str) -> bool:
    if name in ALLOWED_DESPITE_PATTERNS:
        return False
    return name in EXCLUDED_FILE_NAMES or any(
        fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS
    )


def collect_files(module_dir: Path) -> List[Path]:
    """Every file that belongs in the submission, sorted."""
    module_dir = Path(module_dir)
    included: List[Path] = []
    for directory, subdirectories, file_names in os.walk(module_dir):
        relative_directory = Path(directory).relative_to(module_dir).as_posix()
        subdirectories[:] = [
            name for name in subdirectories
            if name not in EXCLUDED_DIRECTORIES
            and (f"{relative_directory}/{name}".lstrip("./")) not in EXCLUDED_RELATIVE_DIRECTORIES
        ]
        for file_name in file_names:
            if not _is_excluded_file(file_name):
                included.append(Path(directory) / file_name)
    return sorted(included)


def build_zip(module_dir: Path, out_path: Path) -> int:
    """Write the archive and return how many files it contains."""
    module_dir, out_path = Path(module_dir), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    files = [path for path in collect_files(module_dir) if path.resolve() != out_path.resolve()]
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{ARCHIVE_ROOT}/{path.relative_to(module_dir).as_posix()}")
    return len(files)


def main() -> int:
    module_dir = Path(__file__).resolve().parent
    out_path = module_dir / "module_3.zip"
    count = build_zip(module_dir, out_path)
    size_mb = out_path.stat().st_size / 1_000_000
    print(f"Wrote {out_path.name}: {count} files, {size_mb:.1f} MB")
    with zipfile.ZipFile(out_path) as archive:
        for name in archive.namelist():
            print("  ", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
