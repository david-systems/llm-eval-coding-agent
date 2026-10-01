"""Carts: persistence, quantity changes, and guest-cart merge (spec section 12)."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from northstar.models import Cart, CartStatus, CustomerLevel
from northstar.services import ValidationError
from northstar.services import carts


def _quantities(db, cart_id):
    cart = db.get(Cart, cart_id)
    db.refresh(cart)
    return {item.product_id: item.quantity for item in cart.items}


def test_add_change_and_remove_items(factory, db):
    a, b = factory.product(), factory.product()
    cart_id = factory.cart()
    carts.add_item(db, cart_id, a.id, 2)
    carts.add_item(db, cart_id, a.id, 1)  # adding again increases the quantity
    carts.add_item(db, cart_id, b.id, 1)
    db.commit()
    assert _quantities(db, cart_id) == {a.id: 3, b.id: 1}

    carts.set_quantity(db, cart_id, a.id, 5)
    carts.remove_item(db, cart_id, b.id)
    db.commit()
    assert _quantities(db, cart_id) == {a.id: 5}

    carts.set_quantity(db, cart_id, a.id, 0)  # zero removes the line
    db.commit()
    assert _quantities(db, cart_id) == {}


def test_quantity_input_validation():
    assert carts.parse_quantity("3", allow_zero=False) == 3
    assert carts.parse_quantity("0", allow_zero=True) == 0
    for bad in ("0", "-1", "abc", "1000", None):
        with pytest.raises(ValidationError):
            carts.parse_quantity(bad, allow_zero=False)


def test_cart_is_not_an_inventory_reservation(factory, db):
    product = factory.product(inventory_qty=1)
    cart_id = factory.cart((product, 5))  # adding more than stock is allowed; checkout decides
    view = carts.view_cart(db.get(Cart, cart_id), None)
    assert view.lines[0].issue == "Not enough stock for this quantity"
    assert db.get(type(product), product.id).inventory_qty == 1


def test_inactive_products_cannot_be_added(factory, db):
    product = factory.product(is_active=False)
    cart_id = factory.cart()
    with pytest.raises(ValidationError):
        carts.add_item(db, cart_id, product.id, 1)


def test_cart_totals_use_current_price_and_level(factory, db):
    product = factory.product(price="100.00")
    customer = factory.customer(level=CustomerLevel.CONTRACTOR)
    cart_id = factory.cart((product, 3), customer=customer)
    view = carts.view_cart(db.get(Cart, cart_id), CustomerLevel.CONTRACTOR)
    assert (view.totals.subtotal, view.totals.shipping, view.totals.tax) == (
        Decimal("300.00"),
        Decimal("0.00"),
        Decimal("24.75"),
    )
    with factory.sessions.begin() as other:
        other.get(type(product), product.id).price = Decimal("50.00")
    db.expire_all()
    view = carts.view_cart(db.get(Cart, cart_id), CustomerLevel.CONTRACTOR)
    assert view.totals.subtotal == Decimal("150.00")
    assert view.totals.shipping == Decimal("20.00")


def test_registered_customer_cart_persists(factory, session_factory):
    product = factory.product()
    customer = factory.customer()
    cart_id = factory.cart((product, 2), customer=customer)
    # A later, independent session (e.g. after logout/login) finds the same cart.
    with session_factory() as later:
        cart = carts.get_customer_cart(later, customer.id)
        assert cart.id == cart_id
        assert [(i.product_id, i.quantity) for i in cart.items] == [(product.id, 2)]


def test_one_active_cart_per_customer_enforced_by_database(factory, db):
    customer = factory.customer()
    factory.cart(customer=customer)
    db.add(Cart(customer_id=customer.id, status=CartStatus.ACTIVE))
    with pytest.raises(IntegrityError):
        db.commit()


def test_guest_cart_merges_into_customer_cart_combining_duplicate_skus(factory, db):
    shared, only_guest, only_customer = factory.product(), factory.product(), factory.product()
    customer = factory.customer()
    customer_cart_id = factory.cart((shared, 2), (only_customer, 1), customer=customer)
    guest_cart_id = factory.cart((shared, 3), (only_guest, 4))
    guest_token = db.get(Cart, guest_cart_id).guest_token

    merged = carts.merge_guest_cart(db, guest_token, customer.id)
    db.commit()

    assert merged.id == customer_cart_id  # the registered cart remains the active cart
    assert _quantities(db, customer_cart_id) == {shared.id: 5, only_customer.id: 1, only_guest.id: 4}
    guest = db.get(Cart, guest_cart_id)
    assert guest.status == CartStatus.MERGED
    assert carts.get_guest_cart(db, guest_token) is None
    assert carts.get_customer_cart(db, customer.id).id == customer_cart_id


def test_guest_cart_becomes_customer_cart_when_customer_has_none(factory, db):
    product = factory.product()
    customer = factory.customer()
    guest_cart_id = factory.cart((product, 2))
    token = db.get(Cart, guest_cart_id).guest_token

    merged = carts.merge_guest_cart(db, token, customer.id)
    db.commit()
    assert merged.customer_id == customer.id
    assert _quantities(db, merged.id) == {product.id: 2}


def test_merge_without_guest_cart_is_noop(factory, db):
    customer = factory.customer()
    assert carts.merge_guest_cart(db, None, customer.id) is None
    assert carts.merge_guest_cart(db, "unknown-token", customer.id) is None
    assert db.scalar(select(Cart).where(Cart.customer_id == customer.id)) is None


def test_closed_cart_cannot_be_modified(factory, db):
    product = factory.product()
    cart_id = factory.cart((product, 1))
    db.get(Cart, cart_id).status = CartStatus.COMPLETED
    db.commit()
    with pytest.raises(carts.CartClosedError):
        carts.add_item(db, cart_id, product.id, 1)


def test_cart_reserved_by_checkout_is_current_but_frozen(factory, db):
    customer = factory.customer()
    product = factory.product()
    cart_id = factory.cart((product, 1), customer=customer)
    db.get(Cart, cart_id).status = CartStatus.CHECKING_OUT
    db.commit()

    assert carts.get_customer_cart(db, customer.id).id == cart_id  # still the shopper's cart
    assert carts.get_or_create_customer_cart(db, customer.id).id == cart_id  # no second cart
    with pytest.raises(carts.CartCheckingOutError):
        carts.add_item(db, cart_id, product.id, 1)
    db.rollback()
    assert carts.view_cart(db.get(Cart, cart_id), None).checking_out


def test_guest_merge_is_deferred_while_customer_cart_is_checking_out(factory, db):
    customer = factory.customer()
    product = factory.product()
    customer_cart = factory.cart((product, 1), customer=customer)
    guest_cart = factory.cart((product, 2))
    token = db.get(Cart, guest_cart).guest_token
    db.get(Cart, customer_cart).status = CartStatus.CHECKING_OUT
    db.commit()

    with pytest.raises(carts.CartCheckingOutError):
        carts.merge_guest_cart(db, token, customer.id)
    db.rollback()
    assert db.get(Cart, guest_cart).status == CartStatus.ACTIVE  # nothing lost; merge retried later

    db.get(Cart, customer_cart).status = CartStatus.ACTIVE  # e.g. capture was refused
    db.commit()
    carts.merge_guest_cart(db, token, customer.id)
    db.commit()
    assert _quantities(db, customer_cart) == {product.id: 3}
