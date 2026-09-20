import json

from run_llm_standardization import build_subsample, convert_jsonl_to_json


def test_build_subsample_takes_first_n_records(tmp_path):
    input_path = tmp_path / "applicant_data.json"
    records = [{"id": i} for i in range(10)]
    input_path.write_text(json.dumps(records), encoding="utf-8")

    subsample_path = tmp_path / "subsample.json"
    count = build_subsample(str(input_path), str(subsample_path), size=3)

    assert count == 3
    written = json.loads(subsample_path.read_text(encoding="utf-8"))
    assert [r["id"] for r in written] == [0, 1, 2]


def test_build_subsample_handles_fewer_records_than_size(tmp_path):
    input_path = tmp_path / "applicant_data.json"
    records = [{"id": 1}]
    input_path.write_text(json.dumps(records), encoding="utf-8")

    subsample_path = tmp_path / "subsample.json"
    count = build_subsample(str(input_path), str(subsample_path), size=5000)
    assert count == 1


def test_convert_jsonl_to_json_round_trip(tmp_path):
    jsonl_path = tmp_path / "out.jsonl"
    jsonl_path.write_text(
        '{"id": 1}\n{"id": 2}\n\n{"id": 3}\n', encoding="utf-8"
    )
    json_path = tmp_path / "out.json"

    count = convert_jsonl_to_json(str(jsonl_path), str(json_path))

    assert count == 3
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert [r["id"] for r in data] == [1, 2, 3]
