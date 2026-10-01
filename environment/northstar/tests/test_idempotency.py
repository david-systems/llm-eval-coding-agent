"""Checkout idempotency (spec section 17; invariant 7), across the payment boundary."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from northstar.models import CartStatus, Product
from northstar.services.checkout import Outcome
from northstar.services.payments import PaymentStatus
from tests.factories import DECLINED_CARD, new_key
from tests.helpers import cart_status, inventory, order_count, payment_statuses, transaction
from tests.invariants import assert_consistent


@pytest.fixture(autouse=True)
def _consistent_afterwards(session_factory, processor):
    yield
    assert_consistent(session_factory, processor)


def test_replaying_successful_key_returns_original_order(factory, checkout_service, session_factory, processor, faults):
    product = factory.product(inventory_qty=5)
    request = factory.checkout_request(factory.cart((product, 2)))

    first = checkout_service.checkout(request)
    second = checkout_service.checkout(request)

    assert first.ok and second.ok
    assert second.order_id == first.order_id and second.replayed
    assert order_count(session_factory) == 1
    assert inventory(session_factory, product) == 3  # decremented once
    assert faults.delivered["authorize"] == 1 and faults.delivered["capture"] == 1  # replay made no processor calls
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")


def test_replay_after_later_catalog_changes_still_returns_original(factory, checkout_service, session_factory):
    product = factory.product(inventory_qty=1)
    request = factory.checkout_request(factory.cart((product, 1)))
    first = checkout_service.checkout(request)
    with session_factory.begin() as admin:
        admin.get(Product, product.id).is_active = False  # would now fail validation
    assert checkout_service.checkout(request).order_id == first.order_id


def test_failed_key_is_final_and_replays_stored_failure(factory, checkout_service, session_factory):
    product = factory.product(inventory_qty=0)
    cart_id = factory.cart((product, 1))
    request = factory.checkout_request(cart_id)

    first = checkout_service.checkout(request)
    assert first.failure_code == "insufficient_inventory"

    with session_factory.begin() as admin:
        admin.get(Product, product.id).inventory_qty = 10  # the condition is now resolved

    replay = checkout_service.checkout(request)
    assert replay.status == Outcome.FAILED and replay.replayed
    assert replay.failure_code == "insufficient_inventory"
    assert order_count(session_factory) == 0

    # A genuinely new attempt uses a new key.
    assert checkout_service.checkout(factory.checkout_request(cart_id, key=new_key())).ok


def test_declined_key_replays_decline_without_new_authorization(factory, checkout_service, session_factory, processor, faults):
    request = factory.checkout_request(factory.cart((factory.product(), 1)), card=DECLINED_CARD)
    checkout_service.checkout(request)
    replay = checkout_service.checkout(request)
    assert replay.failure_code == "payment_declined" and replay.replayed
    assert faults.delivered["authorize"] == 1
    assert payment_statuses(session_factory, processor) == [PaymentStatus.DECLINED]


def test_key_reused_for_different_cart_is_conflict(factory, checkout_service, session_factory):
    key = new_key()
    first_cart = factory.cart((factory.product(), 1))
    other_cart = factory.cart((factory.product(), 1))
    assert checkout_service.checkout(factory.checkout_request(first_cart, key=key)).ok

    conflict = checkout_service.checkout(factory.checkout_request(other_cart, key=key))
    assert conflict.status == Outcome.CONFLICT
    assert order_count(session_factory) == 1


def test_key_reused_by_different_customer_is_conflict(factory, checkout_service, session_factory, faults):
    alice, bob = factory.customer(), factory.customer()
    key = new_key()
    alice_product = factory.product(inventory_qty=5)
    bob_product = factory.product(inventory_qty=5)
    alice_cart = factory.cart((alice_product, 1), customer=alice)
    bob_cart = factory.cart((bob_product, 1), customer=bob)

    first = checkout_service.checkout(factory.checkout_request(alice_cart, alice, key=key))
    assert first.ok

    conflict = checkout_service.checkout(factory.checkout_request(bob_cart, bob, key=key))
    assert conflict.status == Outcome.CONFLICT

    # Bob's own cart and inventory are untouched by the rejected reuse attempt.
    assert cart_status(session_factory, bob_cart) == CartStatus.ACTIVE
    assert inventory(session_factory, bob_product) == 5

    # Only Alice's order exists; nothing was created for Bob.
    assert order_count(session_factory) == 1

    # Alice's checkout remains correct.
    assert cart_status(session_factory, alice_cart) == CartStatus.COMPLETED
    assert inventory(session_factory, alice_product) == 4

    # No processor contact was made on Bob's behalf beyond Alice's original attempt.
    assert faults.attempted["authorize"] == 1
    assert faults.delivered["authorize"] == 1
    assert faults.attempted["capture"] == 1
    assert faults.delivered["capture"] == 1


def test_concurrent_requests_with_same_key_create_one_order(factory, checkout_service, session_factory, processor):
    """Every concurrent retry helps drive the one attempt; all see the same order."""
    product = factory.product(inventory_qty=10)
    request = factory.checkout_request(factory.cart((product, 1)))
    start = threading.Barrier(8)

    def submit(_):
        start.wait()
        return checkout_service.checkout(request)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(submit, range(8)))

    assert all(o.ok for o in outcomes), outcomes
    assert len({o.order_id for o in outcomes}) == 1
    assert order_count(session_factory) == 1
    assert inventory(session_factory, product) == 9
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")


def test_retry_while_original_is_still_in_flight(factory, checkout_service, session_factory, processor, faults):
    """The original request stalls before its authorization reaches the processor;
    a same-key retry completes the checkout, and the stalled request then reports
    the same order - one authorization, one capture."""
    product = factory.product(inventory_qty=10)
    request = factory.checkout_request(factory.cart((product, 1)))
    gate = faults.gate("authorize", when="before", occurrence=1)

    with ThreadPoolExecutor(max_workers=1) as pool:
        original = pool.submit(checkout_service.checkout, request)
        gate.wait_reached()
        retry = checkout_service.checkout(request)
        gate.release()
        first = original.result()

    assert retry.ok and first.ok and retry.order_id == first.order_id
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 9
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")


def test_blank_key_is_rejected(factory, checkout_service):
    request = factory.checkout_request(factory.cart((factory.product(), 1)), key=" ")
    with pytest.raises(ValueError):
        checkout_service.checkout(request)
