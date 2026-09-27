"""Output formatting shared by the console scripts, the PDF builder, and Flask.

The assignment fixes one format per kind of result:
counts are whole numbers, percentages show two decimals and a % sign, and every
average shows two decimals. Keeping the rules here means the raw-SQL output, the
ORM output, the PDF, and the web page can never disagree about formatting.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Union

Number = Union[int, float, Decimal]

NOT_AVAILABLE = "N/A"


def _to_decimal(value: Number) -> Decimal:
    """Convert via str() so 3.785 means 3.785, not its binary-float approximation."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _two_places(value: Number) -> str:
    """Round half-up to two decimal places, as a person would round by hand."""
    return str(_to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt_count(value: Optional[int]) -> str:
    """Whole number with thousands separators, e.g. 19,290."""
    return NOT_AVAILABLE if value is None else f"{int(value):,}"


def fmt_percent(value: Optional[Number]) -> str:
    """Percentage with two decimals and a % sign, e.g. 50.09%."""
    return NOT_AVAILABLE if value is None else f"{_two_places(value)}%"


def fmt_average(value: Optional[Number]) -> str:
    """Average with two decimals, e.g. 3.79."""
    return NOT_AVAILABLE if value is None else _two_places(value)


def fmt_signed_difference(value: Optional[int]) -> str:
    """Difference with an explicit sign (+3, -2); zero has no sign."""
    if value is None:
        return NOT_AVAILABLE
    return f"{int(value):+d}" if value else "0"
