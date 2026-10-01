"""Money handling.

All currency is represented as ``Decimal`` quantized to whole cents and stored
as ``NUMERIC(12, 2)``. Floats never participate in money calculations.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def to_money(value: Decimal | int | str) -> Decimal:
    """Round a value to whole cents, half-up (e.g. 0.165 -> 0.17)."""
    if isinstance(value, float):
        raise TypeError("floats are not accepted for money values")
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def parse_money(text: str) -> Decimal:
    """Parse user-entered money such as '1,299.99' or '$45'.

    Raises ValueError for malformed, negative, or sub-cent input.
    """
    cleaned = (text or "").strip().replace(",", "").removeprefix("$").strip()
    if not cleaned:
        raise ValueError("A price is required.")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"'{text}' is not a valid amount.") from None
    if not value.is_finite():
        raise ValueError(f"'{text}' is not a valid amount.")
    if value < 0:
        raise ValueError("Amounts cannot be negative.")
    if value != value.quantize(CENT):
        raise ValueError("Amounts cannot contain fractions of a cent.")
    if value >= Decimal("10000000000"):
        raise ValueError("Amount is too large.")
    return value.quantize(CENT)


def format_money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"${to_money(value):,.2f}"
