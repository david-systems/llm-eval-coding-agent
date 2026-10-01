"""Shipping, tax, and order-total rules.

Pure functions: no database access, so the rules are testable in isolation and
shared by the cart display, checkout, and seed data.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from northstar.models import CustomerLevel
from northstar.money import ZERO, to_money

TAX_RATE = Decimal("0.0825")
FLAT_SHIPPING = Decimal("20.00")

# Merchandise subtotal at or above which shipping is free. ``None`` is a guest.
FREE_SHIPPING_THRESHOLDS: dict[Optional[CustomerLevel], Decimal] = {
    None: Decimal("999.00"),
    CustomerLevel.RETAIL: Decimal("999.00"),
    CustomerLevel.CONTRACTOR: Decimal("250.00"),
    CustomerLevel.VIP: Decimal("0.00"),  # always free
}


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal


def line_total(unit_price: Decimal, quantity: int) -> Decimal:
    return to_money(unit_price * quantity)


def merchandise_subtotal(lines: Iterable[tuple[Decimal, int]]) -> Decimal:
    return to_money(sum((line_total(price, qty) for price, qty in lines), ZERO))


def shipping_charge(subtotal: Decimal, level: Optional[CustomerLevel]) -> Decimal:
    """Shipping for a merchandise subtotal; ``level`` is None for guests."""
    if subtotal >= FREE_SHIPPING_THRESHOLDS[level]:
        return ZERO
    return FLAT_SHIPPING


def sales_tax(taxable_merchandise: Decimal) -> Decimal:
    """8.25% of taxable merchandise (all merchandise is taxable), half-up to the cent.

    Tax is computed once on the order merchandise subtotal, not per line.
    Shipping is never passed in: it is not taxable.
    """
    return to_money(taxable_merchandise * TAX_RATE)


def calculate_totals(lines: Iterable[tuple[Decimal, int]], level: Optional[CustomerLevel]) -> Totals:
    subtotal = merchandise_subtotal(lines)
    shipping = shipping_charge(subtotal, level)
    tax = sales_tax(subtotal)
    return Totals(subtotal=subtotal, shipping=shipping, tax=tax, total=subtotal + shipping + tax)
