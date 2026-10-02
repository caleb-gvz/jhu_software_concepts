"""The LIMIT guard shared by every query: clamping, composing and binding the limit.

Nothing here needs a database; the statements are only composed and rendered.
"""

import pytest
from psycopg import sql

from sql_safety import DEFAULT_LIMIT, MAX_LIMIT, MIN_LIMIT, clamp_limit, limit_params, limited

pytestmark = pytest.mark.db


def test_the_documented_bounds_are_one_to_one_hundred():
    assert (MIN_LIMIT, MAX_LIMIT) == (1, 100)
    assert MIN_LIMIT <= DEFAULT_LIMIT <= MAX_LIMIT


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (None, DEFAULT_LIMIT),      # nothing asked for: the default, never "everything"
        (25, 25),
        (1, 1),
        (100, 100),
        (101, 100),                 # one over the maximum
        (10**12, 100),              # an absurdly large request is clamped, not honoured
        (0, 1),
        (-5, 1),
        ("7", 7),                   # query-string values arrive as text
        (" 42 ", 42),
        ("5000", 100),
        ("-3", 1),
    ],
)
def test_clamp_limit_keeps_every_request_inside_the_allowed_range(requested, expected):
    assert clamp_limit(requested) == expected


@pytest.mark.parametrize(
    "hostile",
    ["abc", "", "1; DROP TABLE applicants", "1 OR 1=1", "0x10", "1e3", 2.5, True, [], {}, b"5"],
)
def test_clamp_limit_rejects_anything_that_is_not_a_whole_number(hostile):
    with pytest.raises(ValueError, match="limit"):
        clamp_limit(hostile)


def test_clamp_limit_uses_the_caller_supplied_default():
    assert clamp_limit(None, default=10) == 10


def test_limited_appends_a_bound_limit_placeholder_to_a_composed_statement():
    statement = sql.SQL("SELECT {column} FROM {table}").format(
        column=sql.Identifier("p_id"), table=sql.Identifier("applicants")
    )

    assert limited(statement).as_string() == 'SELECT "p_id" FROM "applicants" LIMIT %(limit)s'


def test_limit_params_adds_the_clamped_limit_without_mutating_the_inputs():
    original = {"term": "fall 2026"}

    assert limit_params(5000, original) == {"term": "fall 2026", "limit": 100}
    assert original == {"term": "fall 2026"}
    assert limit_params() == {"limit": DEFAULT_LIMIT}


def test_limit_params_does_not_let_a_caller_parameter_override_the_limit():
    assert limit_params(3, {"limit": 10**9}) == {"limit": 3}
