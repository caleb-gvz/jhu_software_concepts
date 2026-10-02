"""Command-line entry points and error paths of the ETL / reporting scripts.

Each ``main()`` is called directly with arguments, the database is the scratch test
database (via ``DATABASE_URL``), and anything that would reach the network or start a
subprocess is replaced by a fake.
"""

import json
import urllib.error

import psycopg
import pytest

import clean
import load_data
import make_pdfs
import orm_queries
import pull_data
import query_data
import run_llm_standardization
import scrape
from load_data import (
    DataFileError,
    RejectedRecord,
    _read_json_list,
    _report_rejections,
    load_records,
    validate_record,
)
from models import Applicant, get_session
from questions import get_question
from query_data import get_query
from scrape import ScrapeError
from tests.doubles import FakeScraper, make_record
from tests.test_query_data import SEED
from tests.test_scrape import _allow_all_robots_parser, _page_html, _record

pytestmark = pytest.mark.db

UNREACHABLE_DATABASE = "postgresql://nobody@127.0.0.1:1/nowhere?connect_timeout=2"


@pytest.fixture
def use_test_database(monkeypatch, db_url, test_conn):
    """Point every DATABASE_URL-driven script at the (empty) scratch database."""
    monkeypatch.setenv("DATABASE_URL", db_url)
    return test_conn


@pytest.fixture
def use_unreachable_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE)


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---- record validation -----------------------------------------------------------------

@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (None, "record is null"),
        ([1, 2], "record is a list, not a JSON object"),
        ("text", "record is a str, not a JSON object"),
        ({"program": "x"}, "record has no 'id' field"),
        ({"id": None}, "record id None is not a whole number"),
        ({"id": True}, "record id True is not a whole number"),
        ({"id": "12a"}, "record id '12a' is not a whole number"),
        ({"id": 3.5}, "record id 3.5 is not a whole number"),
        ({"id": 0}, "record id 0 is outside the valid range 1..2147483647"),
        ({"id": 2**31}, "record id 2147483648 is outside the valid range 1..2147483647"),
    ],
)
def test_validate_record_explains_why_a_record_is_unusable(record, reason):
    assert validate_record(record) == reason


def test_validate_record_accepts_numeric_string_ids():
    assert validate_record({"id": " 42 "}) is None
    assert load_data.record_to_row({"id": " 42 "})["p_id"] == 42


def test_a_batch_with_no_usable_records_writes_nothing(test_conn):
    result = load_records(test_conn, [None, {"id": "x"}])
    assert result.added == 0 and len(result.rejected) == 2


def test_non_numeric_scores_become_null():
    assert load_data.record_to_row({"id": 1, "gpa": "n/a", "gre_score": [1]})["gpa"] is None


def test_read_json_list_reports_missing_invalid_and_non_list_files(tmp_path):
    with pytest.raises(DataFileError, match="does not exist"):
        _read_json_list(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(DataFileError, match="is not valid JSON"):
        _read_json_list(bad)
    with pytest.raises(DataFileError, match="not a dict"):
        _read_json_list(_write_json(tmp_path / "obj.json", {"id": 1}))


def test_report_rejections_is_silent_when_nothing_was_rejected(capsys):
    _report_rejections("records", [])
    assert capsys.readouterr().err == ""


def test_report_rejections_summarises_long_lists(capsys):
    rejected = [RejectedRecord(index, "record is null") for index in range(25)]
    _report_rejections("records", rejected)
    err = capsys.readouterr().err
    assert "Skipped 25 unusable records" in err
    assert "record #20: record is null" in err and "record #21" not in err
    assert "... and 5 more" in err


def test_clean_data_passes_non_dict_records_through_in_place():
    cleaned = clean.clean_data([None, {"id": 1, "comments": "  a  b "}])
    assert cleaned == [None, {"id": 1, "comments": "a b"}]


# ---- load_data.py -----------------------------------------------------------------------

def test_load_records_rolls_back_the_whole_batch_when_the_database_rejects_it(test_conn):
    # PostgreSQL text cannot contain NUL bytes, so the second row makes the write fail.
    batch = [make_record(1), make_record(2, comments="bad\x00byte"), make_record(3)]

    with pytest.raises(psycopg.DataError):
        load_records(test_conn, batch)

    with test_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM applicants")
        assert cur.fetchone()[0] == 0          # row 1 was not left behind


def test_load_data_main_loads_resets_and_reports(tmp_path, capsys, use_test_database):
    data = _write_json(tmp_path / "data.json", [make_record(1), make_record(2)])

    assert load_data.main(["--data", str(data), "--llm-data", str(tmp_path / "none.json")]) == 0
    assert "added 2 new rows" in capsys.readouterr().out

    assert load_data.main(["--data", str(data), "--llm-data", str(tmp_path / "none.json"),
                           "--reset"]) == 0
    assert "added 2 new rows; skipped 0 unusable records; table now has 2 rows" in capsys.readouterr().out


def test_load_data_main_rejects_an_unreadable_data_file(tmp_path, capsys):
    assert load_data.main(["--data", str(tmp_path / "missing.json")]) == 1
    assert "Cannot load data" in capsys.readouterr().err


def test_load_data_main_ignores_an_unreadable_llm_file(tmp_path, capsys, use_test_database):
    data = _write_json(tmp_path / "data.json", [make_record(1)])
    llm = tmp_path / "llm.json"
    llm.write_text("oops", encoding="utf-8")

    assert load_data.main(["--data", str(data), "--llm-data", str(llm)]) == 0
    captured = capsys.readouterr()
    assert "Warning: ignoring LLM data" in captured.err
    assert "added 1 new rows" in captured.out


def test_load_data_main_reports_an_unreachable_database(tmp_path, capsys, use_unreachable_database):
    data = _write_json(tmp_path / "data.json", [make_record(1)])
    assert load_data.main(["--data", str(data), "--llm-data", str(tmp_path / "none.json")]) == 1
    assert "Could not connect to PostgreSQL" in capsys.readouterr().err


# ---- pull_data.py ------------------------------------------------------------------------

def test_default_scraper_calls_the_module_2_scraper_with_the_page_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pull_data, "scrape_new_records",
        lambda known_ids, max_pages: calls.append((known_ids, max_pages)) or ["r"],
    )
    assert pull_data.default_scraper({1}, 5) == ["r"]
    assert calls == [({1}, 5)]


def test_pull_summary_mentions_skipped_records():
    assert pull_data.PullResult(added=2, skipped=1).summary() == (
        "Added 2 new records to the database. 1 unusable record was skipped."
    )
    assert pull_data.PullResult(added=0, skipped=2).summary().endswith(
        "2 unusable records were skipped."
    )


def test_pull_skips_and_counts_null_records_from_the_scraper(test_conn):
    result = pull_data.pull_new_data(
        test_conn, scrape_fn=FakeScraper([make_record(1), None, make_record(2)])
    )
    assert (result.added, result.skipped, result.error) == (2, 1, None)


def test_pull_data_main_success_and_scrape_error_exit_codes(monkeypatch, capsys, use_test_database):
    # default_scraper looks up scrape_new_records at call time, so this fakes the network.
    monkeypatch.setattr(pull_data, "scrape_new_records",
                        lambda known_ids, max_pages: [make_record(1)])
    assert pull_data.main() == 0
    out = capsys.readouterr().out
    assert "Checking Grad Cafe for new entries..." in out
    assert "Added 1 new record to the database." in out

    def offline(known_ids, max_pages):
        raise ScrapeError("Could not reach Grad Cafe (offline).")

    monkeypatch.setattr(pull_data, "scrape_new_records", offline)
    assert pull_data.main() == 2
    assert "Pull stopped: Could not reach Grad Cafe (offline)." in capsys.readouterr().out


def test_pull_data_main_reports_an_unreachable_database(capsys, use_unreachable_database):
    assert pull_data.main() == 2
    assert "could not connect to the database" in capsys.readouterr().out


# ---- query_data.py / orm_queries.py / questions.py / models.py --------------------------

def test_unknown_question_numbers_raise_key_error():
    with pytest.raises(KeyError):
        get_question("42")
    with pytest.raises(KeyError):
        get_query("42")


def test_query_data_main_prints_every_question(capsys, use_test_database):
    load_records(use_test_database, SEED)
    assert query_data.main() == 0
    out = capsys.readouterr().out
    assert "Question 1:" in out and "Original question 2:" in out
    assert "Fall 2026 applicant count: 7" in out


def test_orm_queries_main_prints_every_question_and_marks_the_required_ones(capsys, use_test_database):
    load_records(use_test_database, SEED)
    assert orm_queries.main() == 0
    out = capsys.readouterr().out
    assert "Question 1:" in out and "[required ORM question]" in out
    assert "Percent international: 33.33%" in out


def test_query_scripts_report_an_unreachable_database(capsys, use_unreachable_database):
    assert query_data.main() == 1
    assert "Could not connect to PostgreSQL" in capsys.readouterr().err
    assert orm_queries.main() == 1
    assert "Could not connect to PostgreSQL" in capsys.readouterr().err


def test_models_default_session_and_readable_repr():
    applicant = Applicant(p_id=7, term="Fall 2026", status="Accepted")
    assert repr(applicant) == "Applicant(p_id=7, term='Fall 2026', status='Accepted')"
    with get_session() as session:
        assert session.bind is not None


# ---- make_pdfs.py --------------------------------------------------------------------------

def test_make_pdfs_main_writes_both_pdfs_from_the_database(tmp_path, monkeypatch, capsys,
                                                          use_test_database):
    load_records(use_test_database, SEED)
    monkeypatch.setattr(make_pdfs, "MODULE_DIR", tmp_path)

    assert make_pdfs.main() == 0

    assert (tmp_path / "query_results.pdf").stat().st_size > 0
    assert (tmp_path / "limitations.pdf").stat().st_size > 0
    assert "Wrote query_results.pdf and limitations.pdf" in capsys.readouterr().out


def test_make_pdfs_main_reports_an_unreachable_database(capsys, use_unreachable_database):
    assert make_pdfs.main() == 1
    assert "Could not connect to PostgreSQL" in capsys.readouterr().err


def test_query_results_pdf_prints_notes(tmp_path):
    from pypdf import PdfReader

    path = tmp_path / "q.pdf"
    make_pdfs.build_query_results_pdf([], path, 0, "2026-09-26", notes=["A note worth reading."])
    assert "A note worth reading." in PdfReader(str(path)).pages[0].extract_text()


# ---- clean.py -------------------------------------------------------------------------------

def test_clean_main_cleans_a_file_into_an_output_file(tmp_path, capsys):
    source = _write_json(tmp_path / "raw.json", [{"id": 1, "comments": "  spaced   out  "}])
    output = tmp_path / "clean.json"

    clean.main(["--input", str(source), "--output", str(output)])

    assert json.loads(output.read_text(encoding="utf-8")) == [{"id": 1, "comments": "spaced out"}]
    assert "Cleaned 1 records" in capsys.readouterr().out


# ---- scrape.py ------------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text):
        self._body = text.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None


def test_robots_and_page_fetchers_read_the_response_body(monkeypatch):
    requested = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        return _FakeResponse("User-agent: *\nDisallow: /signin\n")

    monkeypatch.setattr(scrape.urllib.request, "urlopen", fake_urlopen)

    parser = scrape._load_robots_parser("https://example.test/robots.txt")
    assert parser.can_fetch(scrape.USER_AGENT, "https://example.test/survey")
    assert not parser.can_fetch(scrape.USER_AGENT, "https://example.test/signin")
    assert scrape._fetch_page("https://example.test/survey").startswith("User-agent")
    assert requested == ["https://example.test/robots.txt", "https://example.test/survey"]


def _disallow_all():
    import urllib.robotparser

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    return parser


def test_scrape_data_loads_robots_when_not_given_and_stops_when_disallowed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scrape, "_load_robots_parser", _disallow_all)
    records = scrape.scrape_data(1, str(tmp_path / "o.json"), str(tmp_path / "c.json"),
                                 delay_seconds=0, fetch_fn=lambda url: pytest.fail("fetched"))
    assert records == []
    assert "robots.txt disallows" in capsys.readouterr().out


def test_scrape_data_stops_on_an_unparseable_page_and_skips_repeated_ids(tmp_path, capsys):
    pages = iter([_page_html([_record(1), _record(1)], "next"), "<html>no payload</html>"])
    records = scrape.scrape_data(5, str(tmp_path / "o.json"), str(tmp_path / "c.json"),
                                 delay_seconds=0, fetch_fn=lambda url: next(pages),
                                 robots_parser=_allow_all_robots_parser())
    assert [record["id"] for record in records] == [1]
    assert "Could not parse page" in capsys.readouterr().out


def test_scrape_data_sleeps_between_pages_only_while_more_are_needed(tmp_path, monkeypatch):
    delays = []
    monkeypatch.setattr(scrape.time, "sleep", delays.append)
    pages = iter([_page_html([_record(1)], "c2"), _page_html([_record(2)], None)])
    scrape.scrape_data(5, str(tmp_path / "o.json"), str(tmp_path / "c.json"), delay_seconds=0.5,
                       fetch_fn=lambda url: next(pages), robots_parser=_allow_all_robots_parser())
    assert delays == [0.5]


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (urllib.error.HTTPError("u", 503, "Unavailable", {}, None), "Could not read robots.txt (HTTP 503)."),
        (urllib.error.URLError("offline"), "Could not reach Grad Cafe (offline)."),
    ],
)
def test_scrape_new_records_reports_robots_txt_failures(monkeypatch, error, message):
    def failing_loader():
        raise error

    monkeypatch.setattr(scrape, "_load_robots_parser", failing_loader)
    with pytest.raises(ScrapeError) as caught:
        scrape.scrape_new_records(set(), fetch_fn=lambda url: pytest.fail("fetched"))
    assert str(caught.value) == message
    assert caught.value.partial_records == []


def test_scrape_new_records_loads_robots_when_not_given(monkeypatch):
    monkeypatch.setattr(scrape, "_load_robots_parser", _allow_all_robots_parser)
    records = scrape.scrape_new_records(set(), fetch_fn=lambda url: _page_html([_record(5)], None))
    assert [record["id"] for record in records] == [5]


def test_scrape_main_passes_its_arguments_to_scrape_data(monkeypatch, capsys):
    calls = []

    def fake_scrape_data(**kwargs):
        calls.append(kwargs)
        return [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(scrape, "scrape_data", fake_scrape_data)
    scrape.main(["--target", "2", "--output", "o.json", "--checkpoint", "c.json", "--delay", "0"])

    assert calls == [{"target_count": 2, "output_path": "o.json",
                      "checkpoint_path": "c.json", "delay_seconds": 0.0}]
    assert "Scraped 2 records -> o.json" in capsys.readouterr().out


# ---- run_llm_standardization.py --------------------------------------------------------------

class _FakeProcess:
    def __init__(self, command, cwd, env):
        self.command, self.cwd, self.env = command, cwd, env
        self.waited = False

    def wait(self):
        self.waited = True
        return 0


def _fake_module_dir(tmp_path, records):
    (tmp_path / "llm_hosting").mkdir()
    _write_json(tmp_path / "applicant_data.json", records)
    return tmp_path


def test_launch_shards_writes_inputs_and_starts_one_process_per_non_empty_shard(tmp_path, monkeypatch, capsys):
    started = []
    monkeypatch.setattr(run_llm_standardization.subprocess, "Popen",
                        lambda command, cwd, env: started.append(_FakeProcess(command, cwd, env)) or started[-1])

    processes = run_llm_standardization._launch_shards(tmp_path, [[{"id": 1}], [], [{"id": 3}]], 2)

    assert len(processes) == 2
    assert json.loads((tmp_path / "llm_shard_0.json").read_text(encoding="utf-8")) == [{"id": 1}]
    assert not (tmp_path / "llm_shard_1.json").exists()
    assert "--append" in started[0].command and started[0].env["N_THREADS"] == "2"
    assert "Shard 2: 1 records" in capsys.readouterr().out


def test_run_llm_main_plans_launches_waits_and_merges(tmp_path, monkeypatch, capsys):
    module_dir = _fake_module_dir(tmp_path, [{"id": 1}, {"id": 2}])
    (module_dir / "llm_shard_0.jsonl").write_text('{"id": 1, "llm-generated-program": "A"}\n\n',
                                                  encoding="utf-8")
    monkeypatch.setattr(run_llm_standardization, "__file__", str(module_dir / "run_llm_standardization.py"))
    launched = []

    def fake_launch(directory, shards, threads):
        launched.append([[record["id"] for record in shard] for shard in shards])
        return [_FakeProcess([], None, {})]

    monkeypatch.setattr(run_llm_standardization, "_launch_shards", fake_launch)

    run_llm_standardization.main(["--shards", "2", "--threads", "1"])

    assert launched == [[[2], []]]                     # id 1 was already standardized
    merged = json.loads((module_dir / "llm_extend_applicant_data.json").read_text(encoding="utf-8"))
    assert [record["id"] for record in merged] == [1]
    out = capsys.readouterr().out
    assert "2 records total, 1 already standardized, 1 to do." in out


def test_run_llm_main_merge_only_skips_the_model(tmp_path, monkeypatch, capsys):
    module_dir = _fake_module_dir(tmp_path, [])
    (module_dir / "llm_shard_0.jsonl").write_text('{"id": 5}\n', encoding="utf-8")
    monkeypatch.setattr(run_llm_standardization, "__file__", str(module_dir / "run_llm_standardization.py"))
    monkeypatch.setattr(run_llm_standardization, "_launch_shards",
                        lambda *args: pytest.fail("the model must not run"))

    run_llm_standardization.main(["--merge-only"])

    assert "Wrote 1 standardized records" in capsys.readouterr().out
