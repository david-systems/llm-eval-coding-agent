"""Competing checkouts for limited inventory (spec section 11; invariants 3, 4, 6)."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from northstar.services.checkout import Outcome
from northstar.services.payments import PaymentStatus
from tests.helpers import inventory, order_count, payment_statuses
from tests.invariants import assert_consistent


@pytest.fixture(autouse=True)
def _consistent_afterwards(session_factory, processor):
    yield
    assert_consistent(session_factory, processor)


def _race(factory, checkout_service, faults, requests):
    # Every buyer is held after its authorization succeeds until all buyers are
    # authorized, so they genuinely compete for the rows in the reservation step.
    faults.barrier("authorize", parties=len(requests), when="after")
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(checkout_service.checkout, requests))


def test_two_checkouts_compete_for_final_unit(factory, checkout_service, faults, session_factory, processor):
    product = factory.product(inventory_qty=1)
    requests = [factory.checkout_request(factory.cart((product, 1))) for _ in range(2)]

    outcomes = _race(factory, checkout_service, faults, requests)

    assert sorted(o.status for o in outcomes) == [Outcome.COMPLETED, Outcome.FAILED]
    assert next(o for o in outcomes if not o.ok).failure_code == "insufficient_inventory"
    assert order_count(session_factory) == 1
    assert inventory(session_factory, product) == 0
    assert payment_statuses(session_factory, processor) == [PaymentStatus.CAPTURED, PaymentStatus.VOIDED]


def test_many_buyers_limited_stock(factory, checkout_service, faults, session_factory, processor):
    product = factory.product(inventory_qty=3)
    requests = [factory.checkout_request(factory.cart((product, 1))) for _ in range(10)]

    outcomes = _race(factory, checkout_service, faults, requests)

    assert sum(o.ok for o in outcomes) == 3
    assert all(o.failure_code == "insufficient_inventory" for o in outcomes if not o.ok)
    assert order_count(session_factory) == 3
    assert inventory(session_factory, product) == 0
    statuses = payment_statuses(session_factory, processor)
    assert statuses.count(PaymentStatus.CAPTURED) == 3
    assert statuses.count(PaymentStatus.VOIDED) == 7


def test_multi_product_carts_lock_without_deadlock(factory, checkout_service, faults, session_factory):
    """Carts listing the same products in different orders all complete."""
    a = factory.product(inventory_qty=10)
    b = factory.product(inventory_qty=10)
    requests = [
        factory.checkout_request(factory.cart((a, 1), (b, 1)) if i % 2 else factory.cart((b, 1), (a, 1)))
        for i in range(6)
    ]
    outcomes = _race(factory, checkout_service, faults, requests)

    assert all(o.ok for o in outcomes), outcomes
    assert inventory(session_factory, a) == 4 and inventory(session_factory, b) == 4


def test_two_keys_racing_on_same_cart_produce_one_order(factory, checkout_service, faults, session_factory, processor):
    product = factory.product(inventory_qty=10)
    cart_id = factory.cart((product, 1))
    requests = [factory.checkout_request(cart_id) for _ in range(2)]  # distinct keys

    outcomes = _race(factory, checkout_service, faults, requests)

    assert sorted(o.status for o in outcomes) == [Outcome.COMPLETED, Outcome.FAILED]
    assert next(o for o in outcomes if not o.ok).failure_code == "cart_not_active"
    assert order_count(session_factory) == 1
    assert inventory(session_factory, product) == 9
    assert payment_statuses(session_factory, processor) == [PaymentStatus.CAPTURED, PaymentStatus.VOIDED]
