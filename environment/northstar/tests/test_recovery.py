"""Failure and recovery across the Northstar / FakePay boundary.

Every scenario is made deterministic with the fault injector (drop a request,
lose a response, hold a request at a gate, simulate a crash at a point) - never
with sleeps or wall-clock races. After each scenario the cross-boundary
invariants are checked through FakePay's public API.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from northstar.models import AttemptStatus, CartStatus, Product
from northstar.services import carts
from northstar.services.checkout import Outcome
from northstar.services.payments import PaymentStatus
from northstar.services.reconciliation import ReconciliationPolicy, Reconciler
from tests.factories import CAPTURE_REFUSED_CARD
from tests.faults import SimulatedCrash
from tests.helpers import attempt, cart_status, inventory, order_count, transaction
from tests.invariants import assert_consistent


@pytest.fixture(autouse=True)
def _consistent_afterwards(session_factory, processor):
    yield
    assert_consistent(session_factory, processor)


@pytest.fixture
def setup(factory):
    """A product with 5 in stock and a guest cart holding 2 of it."""
    product = factory.product(inventory_qty=5, price="50.00")
    cart_id = factory.cart((product, 2))
    return product, cart_id


def _sell_out(session_factory, product):
    def action():
        with session_factory.begin() as db:
            db.get(Product, product.id).inventory_qty = 0
    return action


# --------------------------------------------------------------------------- request never reaches FakePay


def test_authorize_not_delivered_leaves_attempt_unresolved_then_retry_completes(
    setup, factory, checkout_service, faults, processor, session_factory
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.unavailable("authorize")

    outcome = checkout_service.checkout(request)

    assert outcome.status == Outcome.PROCESSING  # neither success nor failure is reported
    assert faults.delivered["authorize"] == 0
    assert faults.attempted["authorize"] == 1  # one bounded request; no synchronous retry
    assert processor.get(attempt(session_factory, request.idempotency_key).payment_reference) is None
    assert inventory(session_factory, product) == 5 and cart_status(session_factory, cart_id) == CartStatus.ACTIVE

    faults.clear()
    retried = checkout_service.checkout(request)  # same key: the shopper resubmits
    assert retried.ok and order_count(session_factory) == 1
    assert inventory(session_factory, product) == 3


def test_reconciler_does_not_guess_when_processor_has_no_record(
    setup, factory, checkout_service, faults, reconciler, session_factory, processor
):
    _, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.unavailable("authorize")
    checkout_service.checkout(request)
    faults.clear()

    # Within the recovery period the reconciler only looks; it cannot authorize
    # (it has no card details) and does not treat "no record yet" as failure.
    assert reconciler.run_once() == {Outcome.PROCESSING: 1}
    assert attempt(session_factory, request.idempotency_key).status == AttemptStatus.AUTHORIZING
    assert transaction(session_factory, processor, request.idempotency_key) is None
    assert_consistent(session_factory, processor, allow_unfinished=True)
    checkout_service.checkout(request)  # resolve for the final invariant check


def test_abandoned_unconfirmed_authorization_is_voided_before_failing(
    setup, factory, checkout_service, faults, abandoning_reconciler, session_factory, processor
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.unavailable("authorize")
    checkout_service.checkout(request)
    faults.clear()

    assert abandoning_reconciler.run_once() == {Outcome.FAILED: 1}

    txn = transaction(session_factory, processor, request.idempotency_key)
    assert txn.status == PaymentStatus.VOIDED and txn.events == ("voided",)  # tombstone
    assert attempt(session_factory, request.idempotency_key).failure_code == "payment_unconfirmed"
    assert checkout_service.checkout(request).failure_code == "payment_unconfirmed"  # replay: stored failure
    assert inventory(session_factory, product) == 5 and cart_status(session_factory, cart_id) == CartStatus.ACTIVE


def test_abandonment_is_blocked_while_processor_is_unreachable(
    setup, factory, checkout_service, faults, abandoning_reconciler, session_factory, processor
):
    """Elapsed time alone never fails an attempt: without a confirmed void, it stays unresolved."""
    _, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.unavailable()
    checkout_service.checkout(request)

    assert abandoning_reconciler.run_once() == {Outcome.PROCESSING: 1}
    assert attempt(session_factory, request.idempotency_key).status == AttemptStatus.AUTHORIZING

    faults.clear()
    assert abandoning_reconciler.run_once() == {Outcome.FAILED: 1}


# --------------------------------------------------------------------------- delayed authorization vs void


def test_delayed_authorization_arriving_after_void_cannot_succeed(
    setup, factory, checkout_service, faults, abandoning_reconciler, session_factory, processor
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    gate = faults.gate("authorize", when="before")  # the request is in flight, not yet at FakePay

    with ThreadPoolExecutor(max_workers=1) as pool:
        live = pool.submit(checkout_service.checkout, request)
        gate.wait_reached()
        assert abandoning_reconciler.run_once() == {Outcome.FAILED: 1}  # voids first
        gate.release()  # the delayed authorization now reaches FakePay
        outcome = live.result()

    assert outcome.status == Outcome.FAILED
    txn = transaction(session_factory, processor, request.idempotency_key)
    assert txn.status == PaymentStatus.VOIDED and "authorized" not in txn.events
    assert order_count(session_factory) == 0 and inventory(session_factory, product) == 5


def test_authorization_that_succeeded_is_never_abandoned(
    setup, factory, checkout_service, faults, abandoning_reconciler, session_factory, processor
):
    """The authorization reached FakePay but its response is held. Even a reconciler
    past the abandonment period finds it authorized and completes the checkout."""
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    gate = faults.gate("authorize", when="after")

    with ThreadPoolExecutor(max_workers=1) as pool:
        live = pool.submit(checkout_service.checkout, request)
        gate.wait_reached()
        assert abandoning_reconciler.run_once() == {Outcome.COMPLETED: 1}
        gate.release()
        outcome = live.result()

    assert outcome.ok and order_count(session_factory) == 1
    assert inventory(session_factory, product) == 3
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")


# --------------------------------------------------------------------------- response lost after FakePay applied it


def test_authorize_response_lost_once_shows_processing_then_resubmission_completes(
    setup, factory, checkout_service, faults, session_factory, processor
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.lose_response("authorize")

    outcome = checkout_service.checkout(request)

    # FakePay authorized, but Northstar got no answer: uncertainty is preserved, not retried or guessed.
    assert outcome.status == Outcome.PROCESSING
    assert faults.attempted["authorize"] == 1 and faults.attempted["capture"] == 0
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.AUTHORIZED
    assert order_count(session_factory) == 0 and inventory(session_factory, product) == 5

    assert checkout_service.checkout(request).ok  # same-key resubmission: idempotent authorize, then capture
    assert faults.delivered["authorize"] == 2  # the resubmitted authorize returned the original authorization
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 3


def test_authorize_responses_all_lost_then_reconciled_to_completion(
    setup, factory, checkout_service, faults, reconciler, session_factory, processor
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.lose_response("authorize", occurrence=None)

    assert checkout_service.checkout(request).status == Outcome.PROCESSING
    assert faults.attempted["authorize"] == 1  # exactly one request per operation
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.AUTHORIZED
    assert order_count(session_factory) == 0

    faults.clear()
    assert reconciler.run_once() == {Outcome.COMPLETED: 1}
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 3


def test_capture_response_lost_once_is_resolved_by_reconciler_without_second_effect(
    setup, factory, checkout_service, faults, reconciler, session_factory, processor
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.lose_response("capture")

    assert checkout_service.checkout(request).status == Outcome.PROCESSING
    assert faults.attempted["capture"] == 1  # not retried synchronously
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.CAPTURED
    assert order_count(session_factory) == 0

    assert reconciler.run_once() == {Outcome.COMPLETED: 1}  # idempotent capture returns the existing capture
    assert faults.attempted["capture"] == 2
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 3


def test_captured_payment_with_lost_responses_is_recovered_into_order(
    setup, factory, checkout_service, faults, reconciler, session_factory, processor
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.lose_response("capture", occurrence=None)

    outcome = checkout_service.checkout(request)

    # FakePay captured, but Northstar has no confirmation: no order yet, stock stays reserved.
    assert outcome.status == Outcome.PROCESSING
    assert faults.attempted["capture"] == 1
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.CAPTURED
    assert order_count(session_factory) == 0
    assert inventory(session_factory, product) == 3
    assert cart_status(session_factory, cart_id) == CartStatus.CHECKING_OUT
    assert_consistent(session_factory, processor, allow_unfinished=True)

    faults.clear()
    assert reconciler.run_once() == {Outcome.COMPLETED: 1}
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 3
    assert cart_status(session_factory, cart_id) == CartStatus.COMPLETED
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")


def test_void_response_lost_is_reconciled(setup, factory, checkout_service, faults, reconciler, session_factory, processor):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.run("authorize", _sell_out(session_factory, product))
    faults.lose_response("void", occurrence=None)

    assert checkout_service.checkout(request).status == Outcome.PROCESSING
    assert faults.attempted["void"] == 1  # one bounded request; the reconciler retries later
    assert attempt(session_factory, request.idempotency_key).status == AttemptStatus.VOIDING

    faults.clear()
    assert reconciler.run_once() == {Outcome.FAILED: 1}
    assert attempt(session_factory, request.idempotency_key).failure_code == "insufficient_inventory"
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.VOIDED


# --------------------------------------------------------------------------- processor unavailable mid-checkout


def test_processor_unavailable_during_capture(setup, factory, checkout_service, faults, reconciler, session_factory, processor, db):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.unavailable("capture")

    assert checkout_service.checkout(request).status == Outcome.PROCESSING
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.AUTHORIZED
    # The reserved cart cannot be edited while its payment is unresolved.
    with pytest.raises(carts.CartCheckingOutError):
        carts.add_item(db, cart_id, product.id, 1)
    db.rollback()
    assert reconciler.run_once() == {Outcome.PROCESSING: 1}  # still unreachable: nothing guessed

    faults.clear()
    assert reconciler.run_once() == {Outcome.COMPLETED: 1}
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 3


# --------------------------------------------------------------------------- capture refused


def test_capture_refusal_releases_reservation(setup, factory, checkout_service, session_factory, processor):
    product, cart_id = setup
    request = factory.checkout_request(cart_id, card=CAPTURE_REFUSED_CARD)

    outcome = checkout_service.checkout(request)

    assert outcome.failure_code == "payment_capture_refused"
    assert inventory(session_factory, product) == 5
    assert cart_status(session_factory, cart_id) == CartStatus.ACTIVE
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "voided")


# --------------------------------------------------------------------------- crash at consequential boundaries


@pytest.mark.parametrize(
    "op, when, expected_state",
    [
        ("authorize", "before", AttemptStatus.AUTHORIZING),  # never sent
        ("authorize", "after", AttemptStatus.AUTHORIZING),  # authorized at FakePay; Northstar unaware
        ("capture", "before", AttemptStatus.CAPTURING),  # stock reserved; capture never sent
        ("capture", "after", AttemptStatus.CAPTURING),  # captured at FakePay; no order yet
    ],
)
def test_crash_then_recovery_completes_exactly_once(
    setup, factory, checkout_service, faults, reconciler, session_factory, processor, op, when, expected_state
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.crash(op, when)

    with pytest.raises(SimulatedCrash):
        checkout_service.checkout(request)
    assert attempt(session_factory, request.idempotency_key).status == expected_state
    assert order_count(session_factory) == 0
    assert_consistent(session_factory, processor, allow_unfinished=True)

    if (op, when) == ("authorize", "before"):
        # Nothing reached FakePay; only the shopper (who has the card) can retry.
        assert checkout_service.checkout(request).ok
    else:
        assert reconciler.run_once() == {Outcome.COMPLETED: 1}
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 3
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")


def test_crash_after_authorization_then_stock_gone_voids_on_recovery(
    setup, factory, checkout_service, faults, reconciler, session_factory, processor
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.crash("authorize", "after")
    with pytest.raises(SimulatedCrash):
        checkout_service.checkout(request)
    _sell_out(session_factory, product)()

    assert reconciler.run_once() == {Outcome.FAILED: 1}
    assert attempt(session_factory, request.idempotency_key).failure_code == "insufficient_inventory"
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.VOIDED


def test_crash_after_capture_refusal_recovers(setup, factory, checkout_service, faults, reconciler, session_factory, processor):
    product, cart_id = setup
    request = factory.checkout_request(cart_id, card=CAPTURE_REFUSED_CARD)
    faults.crash("capture", "after")
    with pytest.raises(SimulatedCrash):
        checkout_service.checkout(request)
    assert inventory(session_factory, product) == 3  # still reserved

    assert reconciler.run_once() == {Outcome.FAILED: 1}
    assert inventory(session_factory, product) == 5
    assert cart_status(session_factory, cart_id) == CartStatus.ACTIVE
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.VOIDED


def test_crash_before_void_recovers(setup, factory, checkout_service, faults, reconciler, session_factory, processor):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.run("authorize", _sell_out(session_factory, product))
    faults.crash("void", "before")
    with pytest.raises(SimulatedCrash):
        checkout_service.checkout(request)
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.AUTHORIZED

    assert reconciler.run_once() == {Outcome.FAILED: 1}
    assert transaction(session_factory, processor, request.idempotency_key).status == PaymentStatus.VOIDED


# --------------------------------------------------------------------------- concurrent recovery


def test_concurrent_reconcilers_and_retries_complete_once(
    setup, factory, checkout_service, faults, session_factory, processor
):
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.crash("capture", "after")  # captured at FakePay, no order in Northstar
    with pytest.raises(SimulatedCrash):
        checkout_service.checkout(request)

    reconcilers = [
        Reconciler(session_factory, checkout_service, ReconciliationPolicy(min_age=timedelta(0))) for _ in range(4)
    ]
    start = threading.Barrier(6)

    def work(i):
        start.wait()
        if i < 4:
            return reconcilers[i].run_once()
        return checkout_service.checkout(request).status

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(work, range(6)))

    for result in results:
        if isinstance(result, str):  # a same-key retry
            assert result == Outcome.COMPLETED
        else:  # a reconciler pass: it either completed the attempt or found it already done
            assert set(result) <= {Outcome.COMPLETED}
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 3
    assert transaction(session_factory, processor, request.idempotency_key).events == ("authorized", "captured")


def test_concurrent_abandonment_and_late_authorization_agree(
    setup, factory, checkout_service, faults, session_factory, processor
):
    """Several abandoning reconcilers race a delayed authorization: exactly one
    consistent outcome (voided, failed, no order)."""
    product, cart_id = setup
    request = factory.checkout_request(cart_id)
    gate = faults.gate("authorize", when="before")
    abandoning = [
        Reconciler(session_factory, checkout_service, ReconciliationPolicy(min_age=timedelta(0), abandon_after=timedelta(0)))
        for _ in range(3)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        live = pool.submit(checkout_service.checkout, request)
        gate.wait_reached()
        list(pool.map(lambda r: r.run_once(), abandoning))
        gate.release()
        assert live.result().status == Outcome.FAILED

    txn = transaction(session_factory, processor, request.idempotency_key)
    assert txn.status == PaymentStatus.VOIDED and txn.events == ("voided",)
    assert order_count(session_factory) == 0 and inventory(session_factory, product) == 5


# --------------------------------------------------------------------------- reconciliation scheduling policy


def test_reconciler_skips_recently_updated_attempts(setup, factory, checkout_service, faults, session_factory):
    _, cart_id = setup
    request = factory.checkout_request(cart_id)
    faults.unavailable("capture")
    checkout_service.checkout(request)
    faults.clear()

    polite = Reconciler(session_factory, checkout_service, ReconciliationPolicy(min_age=timedelta(minutes=5)))
    assert polite.unfinished_attempts() == []  # scheduling only: too recent to examine yet

    later = Reconciler(
        session_factory, checkout_service, ReconciliationPolicy(min_age=timedelta(minutes=5)),
        clock=lambda: datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    assert later.run_once() == {Outcome.COMPLETED: 1}
