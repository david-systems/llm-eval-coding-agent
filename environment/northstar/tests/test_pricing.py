"""Shipping, tax, and order-total rules (spec sections 13, 14; invariants 13-18)."""

from decimal import Decimal

import pytest

from northstar.models import CustomerLevel
from northstar.money import format_money, parse_money, to_money
from northstar.pricing import calculate_totals, sales_tax, shipping_charge

D = Decimal
GUEST = None
RETAIL, CONTRACTOR, VIP = CustomerLevel.RETAIL, CustomerLevel.CONTRACTOR, CustomerLevel.VIP


@pytest.mark.parametrize(
    "level, subtotal, expected",
    [
        (GUEST, "998.99", "20.00"),
        (GUEST, "999.00", "0.00"),
        (GUEST, "1500.00", "0.00"),
        (RETAIL, "10.00", "20.00"),
        (RETAIL, "998.99", "20.00"),
        (RETAIL, "999.00", "0.00"),
        (CONTRACTOR, "249.99", "20.00"),
        (CONTRACTOR, "250.00", "0.00"),
        (CONTRACTOR, "998.99", "0.00"),
        (VIP, "0.01", "0.00"),
        (VIP, "5.00", "0.00"),
        (VIP, "5000.00", "0.00"),
    ],
)
def test_shipping_rules_by_customer_level(level, subtotal, expected):
    assert shipping_charge(D(subtotal), level) == D(expected)


def test_non_free_shipping_is_exactly_twenty_dollars():
    for level in (GUEST, RETAIL, CONTRACTOR):
        assert shipping_charge(D("1.00"), level) == D("20.00")


@pytest.mark.parametrize(
    "taxable, expected",
    [
        ("100.00", "8.25"),
        ("999.00", "82.42"),  # 82.4175 -> 82.42
        ("2.00", "0.17"),  # 0.165 exactly: half-up, not banker's (0.16)
        ("10.06", "0.83"),  # 0.82995
        ("0.06", "0.00"),  # 0.00495
        ("1234.56", "101.85"),  # 101.8512
    ],
)
def test_sales_tax_is_8_25_percent_rounded_half_up(taxable, expected):
    assert sales_tax(D(taxable)) == D(expected)


def test_tax_is_computed_on_order_subtotal_not_per_line():
    # Three lines of $2.00 -> per-line tax would be 3 x 0.17 = 0.51; order-level is 0.495 -> 0.50.
    totals = calculate_totals([(D("2.00"), 1), (D("2.00"), 1), (D("2.00"), 1)], VIP)
    assert totals.tax == D("0.50")


def test_shipping_is_not_taxed():
    with_shipping = calculate_totals([(D("100.00"), 1)], RETAIL)
    without_shipping = calculate_totals([(D("100.00"), 1)], VIP)
    assert with_shipping.shipping == D("20.00")
    assert without_shipping.shipping == D("0.00")
    assert with_shipping.tax == without_shipping.tax == D("8.25")


def test_order_totals():
    totals = calculate_totals([(D("19.99"), 3), (D("149.00"), 1)], RETAIL)
    assert totals.subtotal == D("208.97")
    assert totals.shipping == D("20.00")
    assert totals.tax == D("17.24")  # 17.240025
    assert totals.total == D("246.21")


def test_free_shipping_threshold_uses_merchandise_subtotal_before_tax():
    # $950 + tax exceeds $999, but the pre-tax subtotal does not qualify.
    totals = calculate_totals([(D("950.00"), 1)], RETAIL)
    assert totals.shipping == D("20.00")
    assert totals.total == D("950.00") + D("20.00") + D("78.38")


def test_contractor_order_just_over_threshold():
    totals = calculate_totals([(D("125.00"), 2)], CONTRACTOR)
    assert (totals.subtotal, totals.shipping, totals.tax, totals.total) == (
        D("250.00"),
        D("0.00"),
        D("20.63"),
        D("270.63"),
    )


def test_money_helpers_reject_floats_and_bad_input():
    with pytest.raises(TypeError):
        to_money(1.1)  # type: ignore[arg-type]
    assert parse_money("$1,299.99") == D("1299.99")
    for bad in ("", "abc", "-1", "1.005", "NaN"):
        with pytest.raises(ValueError):
            parse_money(bad)
    assert format_money(D("1234.5")) == "$1,234.50"
