"""The instructor-provided LLM standardizer (``src/llm_hosting/app.py``), without a model.

The real module imports ``llama_cpp`` and ``huggingface_hub`` and downloads a GGUF
model. These tests install tiny fake versions of both packages before importing it,
so the parsing, normalisation, HTTP and CLI code runs in milliseconds with no network,
no model file and no llama.cpp build.
"""

import importlib.util
import io
import json
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.db

LLM_DIR = Path(__file__).resolve().parents[1] / "src" / "llm_hosting"


class FakeLlama:
    """Stands in for ``llama_cpp.Llama``; replies with ``FakeLlama.reply``."""

    DEFAULT_REPLY = (
        '{"standardized_program": "Computer Science", '
        '"standardized_university": "Stanford University"}'
    )
    reply = DEFAULT_REPLY
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = []
        FakeLlama.instances.append(self)

    def create_chat_completion(self, messages, **kwargs):
        self.messages.append(messages)
        return {"choices": [{"message": {"content": FakeLlama.reply}}]}


@pytest.fixture
def llm(monkeypatch):
    """Import llm_hosting/app.py with fake llama_cpp / huggingface_hub modules."""
    downloads = []

    def fake_download(**kwargs):
        downloads.append(kwargs)
        return "models/fake.gguf"

    monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(Llama=FakeLlama))
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", types.SimpleNamespace(hf_hub_download=fake_download)
    )
    monkeypatch.setenv("CANON_UNIS_PATH", str(LLM_DIR / "canon_universities.txt"))
    monkeypatch.setenv("CANON_PROGS_PATH", str(LLM_DIR / "canon_programs.txt"))
    FakeLlama.instances = []
    FakeLlama.reply = FakeLlama.DEFAULT_REPLY

    spec = importlib.util.spec_from_file_location("llm_hosting_app", LLM_DIR / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.downloads = downloads
    return module


# ---- helpers -------------------------------------------------------------------------------

def test_read_lines_skips_blanks_and_tolerates_a_missing_file(llm, tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("  A  \n\nB\n", encoding="utf-8")
    assert llm._read_lines(str(path)) == ["A", "B"]
    assert llm._read_lines(str(tmp_path / "missing.txt")) == []
    assert "McGill University" in llm.CANON_UNIS and "Mathematics" in llm.CANON_PROGS


def test_split_fallback_splits_and_expands_known_abbreviations(llm):
    # The fallback title-cases after expanding "McG", which yields "Mcgill University";
    # the university post-normaliser then repairs it through its common-fixes table.
    program, university = llm._split_fallback("information studies, McG")
    assert (program, university) == ("Information Studies", "Mcgill University")
    assert llm._post_normalize_university(university) == "McGill University"
    assert llm._split_fallback("math at ubc") == ("Math", "University of British Columbia")
    assert llm._split_fallback("history, university of toronto") == (
        "History", "University of Toronto",
    )
    assert llm._split_fallback("  ") == ("", "Unknown")


def test_best_match_is_fuzzy_and_returns_none_without_input(llm):
    assert llm._best_match("", ["X"]) is None
    assert llm._best_match("X", []) is None
    assert llm._best_match("Mathematic", ["Mathematics"]) == "Mathematics"
    assert llm._best_match("Zzz", ["Mathematics"]) is None


def test_program_normalisation(llm):
    assert llm._post_normalize_program("computer science") == "Computer Science"      # canonical
    assert llm._post_normalize_program("Mathematic") == "Mathematics"                 # common fix
    assert llm._post_normalize_program("Computer Sciences") == "Computer Science"     # fuzzy
    assert llm._post_normalize_program("Underwater Basketweaving") == "Underwater Basketweaving"


def test_university_normalisation(llm):
    assert llm._post_normalize_university("UBC") == "University of British Columbia"   # abbreviation
    assert llm._post_normalize_university("McGiill University") == "McGill University"  # fix
    assert llm._post_normalize_university("stanford university") == "Stanford University"
    assert llm._post_normalize_university("Stanfrd University") == "Stanford University"  # fuzzy
    assert llm._post_normalize_university("Nowhere Institute") == "Nowhere Institute"
    assert llm._post_normalize_university("") == "Unknown"


def test_normalize_input_accepts_a_list_or_rows_and_ignores_anything_else(llm):
    assert llm._normalize_input([{"a": 1}]) == [{"a": 1}]
    assert llm._normalize_input({"rows": [{"b": 2}]}) == [{"b": 2}]
    assert llm._normalize_input({"rows": "nope"}) == []
    assert llm._normalize_input(None) == []


# ---- the (fake) model --------------------------------------------------------------------

def test_model_is_downloaded_and_loaded_once(llm):
    first = llm._load_llm()
    second = llm._load_llm()
    assert first is second
    assert len(llm.downloads) == 1 and llm.downloads[0]["filename"] == llm.MODEL_FILE
    assert first.kwargs["model_path"] == "models/fake.gguf"


def test_call_llm_uses_the_json_reply_and_few_shot_prompt(llm):
    result = llm._call_llm("CS, Stanford")
    assert result == {
        "standardized_program": "Computer Science",
        "standardized_university": "Stanford University",
    }
    messages = FakeLlama.instances[0].messages[0]
    assert messages[0]["role"] == "system"
    assert json.loads(messages[-1]["content"]) == {"program": "CS, Stanford"}


def test_call_llm_falls_back_to_rules_when_the_reply_is_not_json(llm):
    FakeLlama.reply = "Sorry, I cannot help with that."
    assert llm._call_llm("Mathematics, UBC") == {
        "standardized_program": "Mathematics",
        "standardized_university": "University of British Columbia",
    }


# ---- HTTP API ------------------------------------------------------------------------------

def test_health_and_standardize_endpoints(llm):
    client = llm.app.test_client()
    assert client.get("/").get_json() == {"ok": True}

    response = client.post("/standardize", json={"rows": [{"program": "CS, Stanford"}, {}]})

    rows = response.get_json()["rows"]
    assert rows[0]["llm-generated-program"] == "Computer Science"
    assert rows[0]["llm-generated-university"] == "Stanford University"
    assert len(rows) == 2


# ---- command line --------------------------------------------------------------------------

def test_cli_writes_json_lines_to_the_default_output_file(llm, tmp_path):
    source = tmp_path / "rows.json"
    source.write_text(json.dumps([{"program": "CS, Stanford"}, {"program": "Math, UBC"}]), encoding="utf-8")

    llm.main(["--file", str(source)])

    lines = (tmp_path / "rows.json.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["llm-generated-program"] for line in lines] == [
        "Computer Science", "Computer Science",
    ]


def test_cli_can_append_to_a_named_output_file(llm, tmp_path):
    source = tmp_path / "rows.json"
    source.write_text(json.dumps({"rows": [{"program": "CS, Stanford"}]}), encoding="utf-8")
    out = tmp_path / "out.jsonl"
    out.write_text('{"id": 0}\n', encoding="utf-8")

    llm.main(["--file", str(source), "--out", str(out), "--append"])

    assert len(out.read_text(encoding="utf-8").splitlines()) == 2


def test_cli_can_write_to_stdout(llm, tmp_path, monkeypatch):
    source = tmp_path / "rows.json"
    source.write_text(json.dumps([{"program": "CS, Stanford"}]), encoding="utf-8")
    captured = io.StringIO()
    monkeypatch.setattr(llm.sys, "stdout", captured)

    llm.main(["--file", str(source), "--stdout"])

    assert json.loads(captured.getvalue())["llm-generated-university"] == "Stanford University"


def test_cli_without_a_file_starts_the_http_server(llm, monkeypatch):
    calls = []
    monkeypatch.setattr(llm.app, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("PORT", "8123")

    llm.main([])

    assert calls == [{"host": "0.0.0.0", "port": 8123, "debug": False}]
