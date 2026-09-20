"""Run the instructor's llm_hosting standardizer over a documented subsample.

Full-dataset LLM standardization was benchmarked at ~0.9s/record on this
machine with negligible speedup from multiprocessing (memory-bandwidth
bound), i.e. 8-10 hours for the full ~40,000-record dataset. Per a
documented scope decision, this script standardizes only the first
SUBSAMPLE_SIZE records; see module_2/docs/superpowers/specs/
2026-09-13-gradcafe-scraper-design.md and readme.txt for details.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

SUBSAMPLE_SIZE = 5000


def build_subsample(input_path: str, subsample_path: str, size: int = SUBSAMPLE_SIZE) -> int:
    """Write the first `size` records of input_path to subsample_path. Returns the count written."""
    with open(input_path, "r", encoding="utf-8") as f:
        records: List[Dict[str, Any]] = json.load(f)
    subsample = records[:size]
    with open(subsample_path, "w", encoding="utf-8") as f:
        json.dump(subsample, f, ensure_ascii=False)
    return len(subsample)


def convert_jsonl_to_json(jsonl_path: str, json_path: str) -> int:
    """Convert app.py's JSON-Lines CLI output into a single JSON array. Returns the count."""
    records: List[Dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return len(records)


def main() -> None:
    module_dir = Path(__file__).resolve().parent
    input_path = module_dir / "applicant_data.json"
    subsample_path = module_dir / "llm_subsample.json"
    jsonl_path = module_dir / "llm_extend_applicant_data.jsonl"
    output_path = module_dir / "llm_extend_applicant_data.json"
    llm_hosting_dir = module_dir / "llm_hosting"

    count = build_subsample(str(input_path), str(subsample_path))
    print(f"Built subsample of {count} records at {subsample_path}")

    subprocess.run(
        [
            sys.executable,
            str(llm_hosting_dir / "app.py"),
            "--file",
            str(subsample_path),
            "--out",
            str(jsonl_path),
        ],
        check=True,
        cwd=str(llm_hosting_dir),
    )

    total = convert_jsonl_to_json(str(jsonl_path), str(output_path))
    print(f"Wrote {total} standardized records to {output_path}")


if __name__ == "__main__":
    main()
