from formatting import (
    fmt_average,
    fmt_count,
    fmt_percent,
    fmt_signed_difference,
)


def test_count_is_whole_number_with_thousands_separator():
    assert fmt_count(19290) == "19,290"
    assert fmt_count(0) == "0"


def test_percent_has_two_decimals_and_percent_sign():
    assert fmt_percent(50.0876) == "50.09%"
    assert fmt_percent(39.28) == "39.28%"
    assert fmt_percent(0) == "0.00%"


def test_average_has_two_decimals():
    assert fmt_average(3.7872697974217457) == "3.79"
    assert fmt_average(164.87784679089026) == "164.88"


def test_signed_difference_always_shows_sign_except_zero():
    assert fmt_signed_difference(3) == "+3"
    assert fmt_signed_difference(-2) == "-2"
    assert fmt_signed_difference(0) == "0"


def test_missing_values_render_as_not_available():
    assert fmt_average(None) == "N/A"
    assert fmt_percent(None) == "N/A"
    assert fmt_count(None) == "N/A"
    assert fmt_signed_difference(None) == "N/A"


def test_database_decimals_are_accepted():
    from decimal import Decimal

    assert fmt_average(Decimal("3.785")) == "3.79"
    assert fmt_percent(Decimal("50.005")) == "50.01%"
