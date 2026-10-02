"""``GET /applicants``: the one endpoint that turns query-string values into SQL.

It must answer normal requests with JSON and treat hostile input safely: no crash, no
leaked or dumped data ("everything returned"), and the table is never altered.
"""

import pytest

from load_data import COLUMNS, load_records
from tests.test_query_data import SEED, _rec

pytestmark = pytest.mark.web


@pytest.fixture
def client(make_app, test_conn):
    """A test client on an app bound to the scratch database, pre-loaded with ``SEED``."""
    load_records(test_conn, SEED)
    return make_app().test_client()


def _ids(response):
    return [row["p_id"] for row in response.get_json()["applicants"]]


def test_applicants_returns_json_rows_with_every_stored_column(client):
    response = client.get("/applicants?term=fall 2026&status=accepted")

    body = response.get_json()
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert body["count"] == 5 == len(body["applicants"])
    assert _ids(response) == [1, 3, 5, 14, 15]
    assert set(body["applicants"][0]) == set(COLUMNS)


def test_applicants_defaults_to_every_row_in_key_order_with_the_default_limit(client):
    body = client.get("/applicants").get_json()

    assert [row["p_id"] for row in body["applicants"]] == list(range(1, 16))
    assert body["limit"] == 100


def test_applicants_sorts_by_an_allowed_column_in_either_direction(client):
    ascending = client.get("/applicants?term=fall 2026&sort=gpa")
    descending = client.get("/applicants?term=fall 2026&sort=gpa&direction=DESC")

    assert _ids(ascending) == [5, 3, 4, 1, 2, 14, 15]
    assert _ids(descending) == [1, 4, 3, 5, 2, 14, 15]


def test_applicants_reports_dates_as_iso_strings(make_app, test_conn):
    dated = _rec(1)
    dated["date_added_raw"] = "2026-09-10"
    load_records(test_conn, [dated])

    row = make_app().test_client().get("/applicants").get_json()["applicants"][0]

    assert row["date_added"] == "2026-09-10"


def test_applicants_clamps_an_oversized_limit_instead_of_dumping_the_table(make_app, test_conn):
    load_records(test_conn, [_rec(record_id) for record_id in range(1, 131)])
    client = make_app().test_client()

    huge = client.get("/applicants?limit=99999999").get_json()
    zero = client.get("/applicants?limit=0").get_json()
    negative = client.get("/applicants?limit=-5").get_json()

    assert (huge["limit"], huge["count"]) == (100, 100)
    assert (zero["limit"], zero["count"]) == (1, 1)
    assert (negative["limit"], negative["count"]) == (1, 1)


@pytest.mark.parametrize("limit", ["abc", "", "1; DROP TABLE applicants", "1 OR 1=1", "2.5", "1e3"])
def test_applicants_rejects_a_limit_that_is_not_a_whole_number(client, limit):
    response = client.get("/applicants", query_string={"limit": limit})

    assert response.status_code == 400
    assert "limit" in response.get_json()["error"]
    assert client.get("/applicants").get_json()["count"] == 15      # nothing was dropped


@pytest.mark.parametrize(
    "sort",
    ["p_id; DROP TABLE applicants --", "p_id DESC", "(SELECT 1)", "pg_sleep(5)", "nope", ""],
)
def test_applicants_rejects_a_sort_that_is_not_an_allowed_column(client, sort):
    response = client.get("/applicants", query_string={"sort": sort})

    assert response.status_code == 400
    assert "sort" in response.get_json()["error"]
    assert client.get("/applicants").get_json()["count"] == 15


@pytest.mark.parametrize("direction", ["sideways", "asc; DROP TABLE applicants", "", "desc,p_id"])
def test_applicants_rejects_a_direction_that_is_not_asc_or_desc(client, direction):
    response = client.get("/applicants", query_string={"direction": direction})

    assert response.status_code == 400
    assert "direction" in response.get_json()["error"]


@pytest.mark.parametrize(
    "payload",
    ["' OR '1'='1", "fall 2026' OR 'x'='x", "'; DROP TABLE applicants; --", "%", "_", "fall%"],
)
def test_applicants_treats_injection_text_as_a_value_that_matches_nothing(client, payload):
    for field in ("term", "status"):
        response = client.get("/applicants", query_string={field: payload})

        assert response.status_code == 200
        assert response.get_json()["count"] == 0          # no "everything returned"

    assert client.get("/applicants").get_json()["count"] == 15      # table intact, nothing leaked


def test_applicants_error_responses_do_not_echo_the_hostile_input(client):
    response = client.get("/applicants", query_string={"sort": "<script>alert(1)</script>"})

    assert response.status_code == 400
    assert "<script>" not in response.get_data(as_text=True)


def test_applicants_is_read_only(client):
    assert client.post("/applicants").status_code == 405
    assert client.delete("/applicants").status_code == 405


def test_applicants_answers_503_when_the_database_is_unreachable(make_app):
    app = make_app({"DATABASE_URL": "postgresql://nobody@127.0.0.1:1/nowhere?connect_timeout=2"})

    response = app.test_client().get("/applicants")

    assert response.status_code == 503
    assert response.get_json()["ok"] is False
