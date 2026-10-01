"""Checkout behavior (spec sections 11, 15, 16, 18, 20)."""

from decimal import Decimal

import pytest

from northstar.models import AttemptStatus, CartStatus, CustomerLevel, Product
from northstar.services import ValidationError, carts
from northstar.services.checkout import Outcome, parse_checkout_form
from northstar.services.orders import get_order
from northstar.services.payments import PaymentStatus
from tests.factories import CAPTURE_REFUSED_CARD, DECLINED_CARD, new_key
from tests.helpers import attempt, cart_status, inventory, order_count, payment_statuses, transaction
from tests.invariants import assert_consistent


@pytest.fixture(autouse=True)
def _consistent_afterwards(session_factory, processor):
    yield
    assert_consistent(session_factory, processor)


def test_guest_checkout_creates_completed_order(processor, factory, checkout_service, session_factory, db):
    product = factory.product(price="100.00", cost="61.50", inventory_qty=5)
    cart_id = factory.cart((product, 2))

    outcome = checkout_service.checkout(factory.checkout_request(cart_id))

    assert outcome.ok and outcome.order_id
    order = get_order(db, outcome.order_id)
    assert order.status == "completed"
    assert order.customer_id is None and order.customer_level is None
    assert (order.subtotal, order.shipping, order.tax, order.total) == (
        Decimal("200.00"),
        Decimal("20.00"),
        Decimal("16.50"),
        Decimal("236.50"),
    )
    [line] = order.lines
    assert (line.sku, line.quantity, line.unit_price, line.unit_cost, line.line_total) == (
        product.sku,
        2,
        Decimal("100.00"),
        Decimal("61.50"),
        Decimal("200.00"),
    )
    assert order.card_last4 == "4242"
    txn = processor.get(order.payment_reference)  # FakePay's authoritative record
    assert txn.status == PaymentStatus.CAPTURED and txn.amount == order.total
    assert inventory(session_factory, product) == 3
    assert cart_status(session_factory, cart_id) == CartStatus.COMPLETED
    assert payment_statuses(session_factory, processor) == [PaymentStatus.CAPTURED]


@pytest.mark.parametrize(
    "level, unit_price, qty, expected_shipping",
    [
        (CustomerLevel.RETAIL, "499.50", 2, "0.00"),  # exactly 999.00
        (CustomerLevel.RETAIL, "499.00", 2, "20.00"),
        (CustomerLevel.CONTRACTOR, "125.00", 2, "0.00"),
        (CustomerLevel.CONTRACTOR, "124.99", 2, "20.00"),
        (CustomerLevel.VIP, "4.99", 1, "0.00"),
    ],
)
def test_registered_checkout_applies_customer_level_shipping(
    factory, checkout_service, db, level, unit_price, qty, expected_shipping
):
    customer = factory.customer(level=level)
    product = factory.product(price=unit_price)
    cart_id = factory.cart((product, qty), customer=customer)

    outcome = checkout_service.checkout(factory.checkout_request(cart_id, customer))

    order = get_order(db, outcome.order_id)
    assert order.customer_id == customer.id and order.customer_level == level
    assert order.shipping == Decimal(expected_shipping)
    assert order.total == order.subtotal + order.shipping + order.tax


def test_guest_shipping_threshold(factory, checkout_service, db):
    below = factory.cart((factory.product(price="998.99"), 1))
    at = factory.cart((factory.product(price="999.00"), 1))
    assert get_order(db, checkout_service.checkout(factory.checkout_request(below)).order_id).shipping == Decimal("20.00")
    assert get_order(db, checkout_service.checkout(factory.checkout_request(at)).order_id).shipping == Decimal("0.00")


def test_customer_gets_new_active_cart_after_checkout(factory, checkout_service, db):
    customer = factory.customer()
    product = factory.product()
    cart_id = factory.cart((product, 1), customer=customer)
    assert checkout_service.checkout(factory.checkout_request(cart_id, customer)).ok

    assert carts.get_customer_cart(db, customer.id) is None
    new_cart = carts.get_or_create_customer_cart(db, customer.id)
    db.commit()
    assert new_cart.id != cart_id and new_cart.status == CartStatus.ACTIVE


def test_checkout_uses_price_at_checkout_not_when_added(factory, checkout_service, db, session_factory):
    product = factory.product(price="100.00")
    cart_id = factory.cart((product, 1))
    with session_factory.begin() as admin:
        admin.get(Product, product.id).price = Decimal("120.00")

    outcome = checkout_service.checkout(factory.checkout_request(cart_id))
    assert get_order(db, outcome.order_id).lines[0].unit_price == Decimal("120.00")


def test_authorized_quote_fixes_monetary_terms(factory, session_factory, db, faults, checkout_service):
    """Changes between authorization and Phase 2 do not alter the authorized terms."""
    customer = factory.customer(level=CustomerLevel.RETAIL)
    product = factory.product(price="100.00")
    cart_id = factory.cart((product, 1), customer=customer)

    def change_price_and_level():
        with session_factory.begin() as admin:
            admin.get(Product, product.id).price = Decimal("50.00")
            admin.get(type(customer), customer.id).level = CustomerLevel.VIP

    faults.run("authorize", change_price_and_level)
    outcome = checkout_service.checkout(factory.checkout_request(cart_id, customer))

    order = get_order(db, outcome.order_id)
    assert order.lines[0].unit_price == Decimal("100.00")
    assert order.customer_level == CustomerLevel.RETAIL
    assert (order.shipping, order.total) == (Decimal("20.00"), Decimal("128.25"))


def test_insufficient_inventory_fails_without_side_effects(processor, factory, checkout_service, session_factory):
    product = factory.product(inventory_qty=2)
    cart_id = factory.cart((product, 3))

    outcome = checkout_service.checkout(factory.checkout_request(cart_id))

    assert outcome.status == Outcome.FAILED and outcome.failure_code == "insufficient_inventory"
    assert order_count(session_factory) == 0
    assert inventory(session_factory, product) == 2
    assert cart_status(session_factory, cart_id) == CartStatus.ACTIVE
    assert payment_statuses(session_factory, processor) == []  # never authorized


def test_inventory_can_reach_exactly_zero(factory, checkout_service, session_factory):
    product = factory.product(inventory_qty=3)
    assert checkout_service.checkout(factory.checkout_request(factory.cart((product, 3)))).ok
    assert inventory(session_factory, product) == 0
    outcome = checkout_service.checkout(factory.checkout_request(factory.cart((product, 1))))
    assert outcome.failure_code == "insufficient_inventory"
    assert inventory(session_factory, product) == 0


def test_inactive_product_cannot_be_purchased(factory, checkout_service, session_factory):
    product = factory.product()
    cart_id = factory.cart((product, 1))
    with session_factory.begin() as admin:
        admin.get(Product, product.id).is_active = False

    outcome = checkout_service.checkout(factory.checkout_request(cart_id))
    assert outcome.failure_code == "product_unavailable"
    assert order_count(session_factory) == 0 and inventory(session_factory, product) == 10


def test_empty_cart_cannot_be_checked_out(factory, checkout_service):
    outcome = checkout_service.checkout(factory.checkout_request(factory.cart()))
    assert outcome.failure_code == "empty_cart"


def test_declined_payment_creates_no_order(processor, factory, checkout_service, session_factory):
    product = factory.product(inventory_qty=4)
    cart_id = factory.cart((product, 1))
    key = new_key()

    outcome = checkout_service.checkout(factory.checkout_request(cart_id, key=key, card=DECLINED_CARD))

    assert outcome.status == Outcome.FAILED and outcome.failure_code == "payment_declined"
    assert order_count(session_factory) == 0
    assert inventory(session_factory, product) == 4
    assert cart_status(session_factory, cart_id) == CartStatus.ACTIVE
    assert payment_statuses(session_factory, processor) == [PaymentStatus.DECLINED]
    assert attempt(session_factory, key).status == AttemptStatus.FAILED

    # The cart is still active, so a new attempt with a good card succeeds.
    assert checkout_service.checkout(factory.checkout_request(cart_id)).ok


def test_authorization_voided_when_inventory_sold_after_authorization(processor, factory, session_factory, faults, checkout_service):
    """Stock disappears while payment is being authorized: void, clean failure."""
    product = factory.product(inventory_qty=1)
    cart_id = factory.cart((product, 1))

    def competing_sale():
        with session_factory.begin() as other:
            other.get(Product, product.id).inventory_qty = 0

    faults.run("authorize", competing_sale)
    outcome = checkout_service.checkout(factory.checkout_request(cart_id))

    assert outcome.status == Outcome.FAILED and outcome.failure_code == "insufficient_inventory"
    assert payment_statuses(session_factory, processor) == [PaymentStatus.VOIDED]
    assert order_count(session_factory) == 0
    assert inventory(session_factory, product) == 0
    assert cart_status(session_factory, cart_id) == CartStatus.ACTIVE


def test_authorization_voided_when_product_deactivated_after_authorization(processor, factory, session_factory, faults, checkout_service):
    product = factory.product(inventory_qty=5)
    cart_id = factory.cart((product, 1))

    def deactivate():
        with session_factory.begin() as admin:
            admin.get(Product, product.id).is_active = False

    faults.run("authorize", deactivate)
    outcome = checkout_service.checkout(factory.checkout_request(cart_id))

    assert outcome.failure_code == "product_unavailable"
    assert payment_statuses(session_factory, processor) == [PaymentStatus.VOIDED]
    assert order_count(session_factory) == 0 and inventory(session_factory, product) == 5


def test_authorization_voided_when_cart_changes_after_authorization(processor, factory, session_factory, faults, checkout_service):
    product = factory.product(inventory_qty=5)
    cart_id = factory.cart((product, 1))

    def edit_cart():
        with session_factory.begin() as other:
            carts.set_quantity(other, cart_id, product.id, 3)

    faults.run("authorize", edit_cart)
    outcome = checkout_service.checkout(factory.checkout_request(cart_id))

    assert outcome.failure_code == "cart_changed"
    assert payment_statuses(session_factory, processor) == [PaymentStatus.VOIDED]
    assert order_count(session_factory) == 0 and inventory(session_factory, product) == 5


def test_capture_refused_releases_reservation_and_voids(processor, factory, checkout_service, session_factory):
    product = factory.product(inventory_qty=3)
    cart_id = factory.cart((product, 2))
    key = new_key()

    outcome = checkout_service.checkout(factory.checkout_request(cart_id, key=key, card=CAPTURE_REFUSED_CARD))

    assert outcome.status == Outcome.FAILED and outcome.failure_code == "payment_capture_refused"
    assert order_count(session_factory) == 0
    assert inventory(session_factory, product) == 3  # reservation returned
    assert cart_status(session_factory, cart_id) == CartStatus.ACTIVE  # shopper can try again
    assert transaction(session_factory, processor, key).status == PaymentStatus.VOIDED
    # The same cart succeeds with a new attempt and a working card.
    assert checkout_service.checkout(factory.checkout_request(cart_id)).ok
    assert inventory(session_factory, product) == 1


def test_completed_cart_cannot_be_checked_out_again_with_new_key(processor, factory, checkout_service, session_factory):
    product = factory.product(inventory_qty=10)
    cart_id = factory.cart((product, 1))
    assert checkout_service.checkout(factory.checkout_request(cart_id)).ok

    again = checkout_service.checkout(factory.checkout_request(cart_id, key=new_key()))

    assert again.status == Outcome.FAILED and again.failure_code == "cart_not_active"
    assert order_count(session_factory) == 1
    assert inventory(session_factory, product) == 9
    assert payment_statuses(session_factory, processor) == [PaymentStatus.CAPTURED]


def test_checkout_rejects_another_customers_cart(factory, checkout_service, session_factory, processor, faults):
    owner, intruder = factory.customer(), factory.customer()
    product = factory.product(inventory_qty=5)
    cart_id = factory.cart((product, 1), customer=owner)
    key = new_key()

    outcome = checkout_service.checkout(factory.checkout_request(cart_id, intruder, key=key))

    assert outcome.failure_code == "cart_not_found"
    assert cart_status(session_factory, cart_id) == CartStatus.ACTIVE
    assert inventory(session_factory, product) == 5
    assert order_count(session_factory) == 0
    assert faults.delivered["authorize"] == 0

    # Zero processor contact: the failed attempt's payment_reference has no record at all,
    # not merely a voided one (authorize->void->restore would leave a VOIDED record).
    failed_attempt = attempt(session_factory, key)
    assert processor.get(failed_attempt.payment_reference) is None


def test_checkout_form_validation():
    with pytest.raises(ValidationError) as exc:
        parse_checkout_form({"email": "nope", "card_number": "12"})
    assert {"email", "first_name", "address_line1", "card_number"} <= exc.value.errors.keys()
    contact, card = parse_checkout_form(
        {
            "email": " Pat@Example.com ",
            "first_name": "Pat",
            "last_name": "Q",
            "address_line1": "1 Rd",
            "city": "Bend",
            "state": "OR",
            "postal_code": "97701",
            "card_number": "4242 4242 4242 4242",
        }
    )
    assert contact.email == "pat@example.com" and card == "4242424242424242"
