import json

import pytest

from run_llm_standardization import (
    find_completed_ids,
    is_priority_record,
    merge_outputs,
    plan_shards,
)

pytestmark = pytest.mark.db


def _rec(record_id, term="Fall 2026", status="Accepted", degree="PhD"):
    return {
        "id": record_id,
        "term": term,
        "applicant_status": status,
        "degree": degree,
    }


def test_priority_is_fall_2026_accepted_phd():
    assert is_priority_record(_rec(1))
    assert is_priority_record(_rec(2, term=" fall 2026 ", status="accepted", degree="phd"))
    assert not is_priority_record(_rec(3, term="Fall 2025"))
    assert not is_priority_record(_rec(4, status="Rejected"))
    assert not is_priority_record(_rec(5, degree="Masters"))


def test_priority_tolerates_missing_fields():
    assert not is_priority_record({"id": 6, "term": None, "applicant_status": None})


def test_plan_shards_puts_priority_first_and_skips_done():
    records = [_rec(1, degree="Masters"), _rec(2), _rec(3), _rec(4), _rec(5, degree="Masters")]

    shards = plan_shards(records, done_ids={3}, shards=2)

    # remaining order is priority rows (2, 4) then the rest (1, 5), dealt round-robin
    assert [r["id"] for r in shards[0]] == [2, 1]
    assert [r["id"] for r in shards[1]] == [4, 5]


def test_plan_shards_does_not_mutate_input():
    records = [_rec(1, degree="Masters"), _rec(2)]
    plan_shards(records, done_ids=set(), shards=2)
    assert [r["id"] for r in records] == [1, 2]


def test_find_completed_ids_reads_json_and_ignores_truncated_jsonl_line(tmp_path):
    finished = tmp_path / "llm_extend.json"
    finished.write_text(json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")
    shard = tmp_path / "shard.jsonl"
    shard.write_text('{"id": 7}\n{"id": 8}\n{"id": 9', encoding="utf-8")

    assert find_completed_ids([finished, shard]) == {1, 2, 7, 8}


def test_find_completed_ids_skips_missing_files(tmp_path):
    assert find_completed_ids([tmp_path / "does_not_exist.jsonl"]) == set()


def test_merge_outputs_unions_sources_and_later_source_wins(tmp_path):
    base = tmp_path / "base.json"
    base.write_text(
        json.dumps([{"id": 1, "llm-generated-program": "old"}, {"id": 2}]),
        encoding="utf-8",
    )
    shard = tmp_path / "shard.jsonl"
    shard.write_text(
        '{"id": 1, "llm-generated-program": "new"}\n{"id": 3}\n', encoding="utf-8"
    )
    output = tmp_path / "merged.json"

    count = merge_outputs([base, shard], output)

    merged = json.loads(output.read_text(encoding="utf-8"))
    assert count == 3
    assert [r["id"] for r in merged] == [1, 2, 3]
    assert merged[0]["llm-generated-program"] == "new"
