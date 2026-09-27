"""Run the instructor's llm_hosting standardizer over the applicant data.

Full-dataset standardization takes many hours on CPU (~0.75-0.9 s/record), so this
driver is built to be interrupted and resumed, and to spend its first minutes on the
rows that can change the analysis:

* Question 9 only compares rows that are Fall 2026 + accepted + PhD (decided by the
  ORIGINAL term/status/degree fields), so those "priority" rows are standardized
  first. Every other row is standardized afterwards, as time allows.
* Work is split into shards that run as parallel subprocesses (one output file per
  shard, flushed after every record).
* On start-up, ids that already appear in any output file are skipped, so re-running
  the script after a crash or reboot continues where it left off.
* When the shards finish (or on ``--merge-only``), all outputs are merged into
  ``llm_extend_applicant_data.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

DEFAULT_SHARDS = 4
DEFAULT_THREADS_PER_SHARD = 3

Record = Dict[str, Any]


def is_priority_record(record: Record) -> bool:
    """True for Fall 2026 + accepted + PhD rows (the only rows Q8/Q9 can select)."""
    term = (record.get("term") or "").strip().lower()
    status = (record.get("applicant_status") or "").strip().lower()
    degree = (record.get("degree") or "").strip().lower()
    return term == "fall 2026" and status.startswith("accept") and degree == "phd"


def _read_records(path: Path) -> List[Record]:
    """Read a JSON array file or a JSON-Lines file; unreadable lines are skipped.

    A shard that was killed mid-write can leave a truncated final line, so JSON-Lines
    parsing is deliberately forgiving. A missing file yields no records.
    """
    if not path.exists():
        return []
    if path.suffix == ".jsonl":
        records: List[Record] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_completed_ids(paths: Iterable[Path]) -> Set[int]:
    """Ids that already have LLM output in any of the given files."""
    return {record["id"] for path in paths for record in _read_records(path) if "id" in record}


def plan_shards(
    records: List[Record], done_ids: Set[int], shards: int
) -> List[List[Record]]:
    """Split the not-yet-done records into `shards` lists, priority rows first.

    Rows are dealt round-robin from a priority-first ordering, so every shard works
    through its share of the priority rows before touching any other row.
    """
    remaining = [r for r in records if r["id"] not in done_ids]
    ordered = [r for r in remaining if is_priority_record(r)] + [
        r for r in remaining if not is_priority_record(r)
    ]
    return [ordered[i::shards] for i in range(shards)]


def merge_outputs(enriched_paths: Iterable[Path], output_path: Path) -> int:
    """Union every enriched file by id (later files win) into one JSON array.

    Returns the number of records written, sorted by id.
    """
    by_id: Dict[int, Record] = {}
    for path in enriched_paths:
        for record in _read_records(Path(path)):
            by_id[record["id"]] = record
    merged = [by_id[record_id] for record_id in sorted(by_id)]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return len(merged)


def _launch_shards(
    module_dir: Path, shards: List[List[Record]], threads_per_shard: int
) -> List[subprocess.Popen]:
    """Start one llm_hosting/app.py process per non-empty shard."""
    llm_hosting_dir = module_dir / "llm_hosting"
    processes: List[subprocess.Popen] = []
    for index, shard in enumerate(shards):
        if not shard:
            continue
        shard_input = module_dir / f"llm_shard_{index}.json"
        shard_output = module_dir / f"llm_shard_{index}.jsonl"
        with open(shard_input, "w", encoding="utf-8") as f:
            json.dump(shard, f, ensure_ascii=False)
        env = dict(os.environ, N_THREADS=str(threads_per_shard))
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(llm_hosting_dir / "app.py"),
                    "--file",
                    str(shard_input),
                    "--out",
                    str(shard_output),
                    "--append",
                ],
                cwd=str(llm_hosting_dir),
                env=env,
            )
        )
        print(f"Shard {index}: {len(shard)} records -> {shard_output.name}")
    return processes


def main(argv: Optional[List[str]] = None) -> None:
    """Command-line entry point: standardize what is left, then merge all outputs."""
    parser = argparse.ArgumentParser(description="Prioritised, resumable LLM standardization.")
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARDS)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS_PER_SHARD)
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="Skip running the LLM; just merge existing outputs into the final JSON.",
    )
    args = parser.parse_args(argv)

    module_dir = Path(__file__).resolve().parent
    input_path = module_dir / "applicant_data.json"
    final_path = module_dir / "llm_extend_applicant_data.json"
    shard_outputs = sorted(module_dir.glob("llm_shard_*.jsonl"))

    if not args.merge_only:
        records = _read_records(input_path)
        done_ids = find_completed_ids([final_path, *shard_outputs])
        shards = plan_shards(records, done_ids, args.shards)
        print(f"{len(records)} records total, {len(done_ids)} already standardized, "
              f"{sum(len(s) for s in shards)} to do.")
        processes = _launch_shards(module_dir, shards, args.threads)
        for process in processes:
            process.wait()
        shard_outputs = sorted(module_dir.glob("llm_shard_*.jsonl"))

    total = merge_outputs([final_path, *shard_outputs], final_path)
    print(f"Wrote {total} standardized records to {final_path}")


if __name__ == "__main__":
    main()
