"""Storefront flows through HTTP: browsing, carts, login, checkout, order history."""

import re
from decimal import Decimal

from sqlalchemy import select

from northstar.models import Cart, CartStatus, CheckoutAttempt, CustomerLevel, Order, Product
from northstar.services import content
from tests.helpers import inventory, order_count
from tests.invariants import assert_consistent
from tests.web import add_to_cart, checkout_key, csrf, login_customer, post, submit_checkout


def _order_id(response) -> int:
    assert response.status_code == 303, response.text
    return int(re.match(r"/orders/(\d+)/confirmation", response.headers["location"]).group(1))


# --------------------------------------------------------------------------- homepage & browsing


def test_homepage_shows_featured_new_and_announcement(client, factory, db):
    factory.product(name="Featured Grill", is_featured=True)
    factory.product(name="Fresh Fire Pit", is_new=True)
    factory.product(name="Hidden Featured", is_featured=True, is_active=False)
    content.update_announcement(db, "Spring sale on fire pits!", True)
    db.commit()

    html = client.get("/").text
    featured = html.split('id="featured"')[1].split('id="new-arrivals"')[0]
    new = html.split('id="new-arrivals"')[1]
    assert "Featured Grill" in featured and "Fresh Fire Pit" not in featured
    assert "Fresh Fire Pit" in new
    assert "Hidden Featured" not in html
    assert "Spring sale on fire pits!" in html


def test_hidden_announcement_is_not_rendered(client, db):
    content.update_announcement(db, "Old news", False)
    db.commit()
    assert "Old news" not in client.get("/").text


def test_category_browsing_and_product_detail(client, factory, db):
    grills = factory.category("Grills")
    gas = factory.category("Gas Grills", parent=grills)
    product = factory.product(name="Ridge 3-Burner", category_id=gas.id, inventory_qty=0)
    top = client.get(f"/categories/{grills.slug}")
    assert top.status_code == 200 and "Ridge 3-Burner" in top.text and "Gas Grills" in top.text
    detail = client.get(f"/products/{product.sku}")
    assert detail.status_code == 200 and "Out of Stock" in detail.text
    assert "In Stock" in client.get(f"/products/{factory.product(inventory_qty=4).sku}").text


def test_inactive_product_is_not_purchasable_on_storefront(client, factory):
    product = factory.product(name="Retired Smoker", is_active=False)
    assert client.get(f"/products/{product.sku}").status_code == 404
    assert "Retired Smoker" not in client.get("/products").text
    add_to_cart(client, product.sku)
    assert "Retired Smoker" not in client.get("/cart").text


def test_search_and_unknown_pages(client, factory):
    factory.product(name="Cast Iron Griddle")
    assert "Cast Iron Griddle" in client.get("/products?q=griddle").text
    assert client.get("/categories/nope").status_code == 404
    assert client.get("/no-such-page").status_code == 404


# --------------------------------------------------------------------------- CSRF


def test_state_changing_requests_require_csrf_token(client, factory):
    product = factory.product()
    no_token = client.post("/cart/add", data={"sku": product.sku, "quantity": "1"}, follow_redirects=False)
    assert no_token.status_code == 403
    bad_token = post(client, "/cart/add", {"sku": product.sku, "quantity": "1"}, token="forged")
    assert bad_token.status_code == 403
    assert "Your cart is empty" in client.get("/cart").text
    assert add_to_cart(client, product.sku).status_code == 303


def test_csrf_token_from_another_session_is_rejected(client, other_client, factory):
    product = factory.product()
    stolen = csrf(other_client)
    assert post(client, "/cart/add", {"sku": product.sku}, token=stolen).status_code == 403


def test_login_and_admin_login_forms_require_csrf(client, factory):
    factory.customer(email="c@example.com")
    assert client.post("/login", data={"email": "c@example.com", "password": "northstar123"}).status_code == 403


# --------------------------------------------------------------------------- carts


def test_guest_cart_add_update_remove_and_totals(client, factory):
    a = factory.product(name="Grill Brush", price="25.00")
    b = factory.product(name="Grill Cover", price="80.00")
    add_to_cart(client, a.sku, 2)
    add_to_cart(client, b.sku, 1)
    html = client.get("/cart").text
    assert "$130.00" in html and "$20.00" in html and "$10.73" in html  # subtotal, shipping, tax

    post(client, "/cart/update", {"product_id": str(a.id), "quantity": "4", "action": "update"})
    post(client, "/cart/update", {"product_id": str(b.id), "action": "remove"})
    html = client.get("/cart").text
    assert "Grill Cover" not in html and 'value="4"' in html and "$100.00" in html


def test_invalid_quantity_is_rejected(client, factory):
    product = factory.product()
    add_to_cart(client, product.sku, 0)
    assert "Your cart is empty" in client.get("/cart").text


def test_registered_cart_persists_across_logout_and_login(client, other_client, factory):
    customer = factory.customer(email="persist@example.com")
    product = factory.product(name="Patio Umbrella")
    login_customer(client, customer.email)
    add_to_cart(client, product.sku, 3)
    post(client, "/logout")
    assert "Patio Umbrella" not in client.get("/cart").text

    login_customer(other_client, customer.email)  # a different browser/session
    html = other_client.get("/cart").text
    assert "Patio Umbrella" in html and 'value="3"' in html


def test_login_merges_guest_cart_combining_duplicate_skus(client, factory, db):
    customer = factory.customer(email="merge@example.com")
    shared, guest_only = factory.product(name="Shared Grate"), factory.product(name="Guest Tongs")
    factory.cart((shared, 2), customer=customer)

    add_to_cart(client, shared.sku, 1)
    add_to_cart(client, guest_only.sku, 2)
    login_customer(client, customer.email)

    cart = db.scalar(select(Cart).where(Cart.customer_id == customer.id, Cart.status == CartStatus.ACTIVE))
    assert {i.product_id: i.quantity for i in cart.items} == {shared.id: 3, guest_only.id: 2}
    assert db.scalar(select(Cart).where(Cart.customer_id.is_(None), Cart.status == CartStatus.ACTIVE)) is None


def test_failed_login(client, factory):
    factory.customer(email="real@example.com")
    response = post(client, "/login", {"email": "real@example.com", "password": "wrong"})
    assert response.status_code == 401 and "Incorrect email or password" in response.text


# --------------------------------------------------------------------------- checkout


def test_guest_checkout_end_to_end(client, other_client, factory, session_factory, db):
    product = factory.product(name="Blackpine Kamado", price="1200.00", inventory_qty=2)
    add_to_cart(client, product.sku)

    order_id = _order_id(submit_checkout(client, checkout_key(client)))

    page = client.get(f"/orders/{order_id}/confirmation")
    assert page.status_code == 200 and f"NS-{100000 + order_id}" in page.text
    order = db.get(Order, order_id)
    assert order.customer_id is None and order.shipping == Decimal("0.00")  # guest, >= $999
    assert order.total == Decimal("1299.00")
    assert inventory(session_factory, product) == 1
    assert "Your cart is empty" in client.get("/cart").text
    # Another browser cannot view a guest's confirmation.
    assert other_client.get(f"/orders/{order_id}/confirmation").status_code == 404


def test_resubmitted_checkout_form_returns_same_order(client, factory, session_factory):
    product = factory.product(inventory_qty=5)
    add_to_cart(client, product.sku)
    key = checkout_key(client)

    first = _order_id(submit_checkout(client, key))
    second = _order_id(submit_checkout(client, key))  # e.g. double click / refresh

    assert first == second
    assert order_count(session_factory) == 1
    assert inventory(session_factory, product) == 4


def test_declined_card_shows_error_and_keeps_cart(client, factory, session_factory):
    product = factory.product(inventory_qty=5)
    add_to_cart(client, product.sku)
    key = checkout_key(client)

    response = submit_checkout(client, key, card_number="4000 0000 0000 0002")

    assert response.status_code == 409 and "declined" in response.text
    new_key = re.search(r'name="idempotency_key" value="([^"]+)"', response.text).group(1)
    assert new_key != key  # a failed attempt is final; the next submit is a new attempt
    assert order_count(session_factory) == 0 and inventory(session_factory, product) == 5
    assert _order_id(submit_checkout(client, new_key))


def test_checkout_insufficient_inventory_message(client, factory, session_factory):
    product = factory.product(inventory_qty=1)
    add_to_cart(client, product.sku, 2)
    response = submit_checkout(client, checkout_key(client))
    assert response.status_code == 409 and "not enough stock" in response.text
    assert inventory(session_factory, product) == 1


def test_checkout_form_validation_errors(client, factory):
    add_to_cart(client, factory.product().sku)
    response = submit_checkout(client, checkout_key(client), email="bad", card_number="1")
    assert response.status_code == 422 and "valid email" in response.text and "card number" in response.text


def test_empty_cart_checkout_redirects(client):
    assert client.get("/checkout", follow_redirects=False).status_code == 303


def test_logged_in_checkout_and_order_history(client, other_client, factory, db):
    customer = factory.customer(email="contractor@example.com", level=CustomerLevel.CONTRACTOR)
    someone_else = factory.customer(email="else@example.com")
    product = factory.product(name="Stainless Access Door", price="260.00")
    login_customer(client, customer.email)
    add_to_cart(client, product.sku)

    order_id = _order_id(submit_checkout(client, checkout_key(client), email=customer.email))

    order = db.get(Order, order_id)
    assert order.customer_id == customer.id and order.customer_level == CustomerLevel.CONTRACTOR
    assert order.shipping == Decimal("0.00")  # contractor, >= $250
    history = client.get("/account/orders").text
    assert order.number in history
    assert "Stainless Access Door" in client.get(f"/account/orders/{order_id}").text

    login_customer(other_client, someone_else.email)
    assert other_client.get(f"/account/orders/{order_id}").status_code == 404
    assert order.number not in other_client.get("/account/orders").text


def test_order_history_requires_login(client):
    response = client.get("/account/orders", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/login")


def test_price_change_after_adding_to_cart_uses_current_price(client, factory, session_factory, db):
    product = factory.product(price="40.00")
    add_to_cart(client, product.sku)
    with session_factory.begin() as admin:
        admin.get(Product, product.id).price = Decimal("45.00")
    order_id = _order_id(submit_checkout(client, checkout_key(client)))
    assert db.get(Order, order_id).subtotal == Decimal("45.00")


# --------------------------------------------------------------------------- payment not yet confirmed


def test_unconfirmed_payment_shows_processing_until_reconciled(
    client, other_client, factory, faults, session_factory, processor, reconciler
):
    product = factory.product(name="Northglow Fire Bowl", inventory_qty=4)
    add_to_cart(client, product.sku)
    key = checkout_key(client)
    faults.unavailable("capture")

    response = submit_checkout(client, key)

    assert response.status_code == 303 and response.headers["location"] == f"/checkout/status/{key}"
    page = client.get(f"/checkout/status/{key}")
    assert page.status_code == 200 and 'data-testid="payment-processing"' in page.text
    assert order_count(session_factory) == 0  # no success reported, no order yet
    assert "declined" not in page.text.lower()

    cart_page = client.get("/cart").text
    assert 'data-testid="cart-checking-out"' in cart_page and "Proceed to checkout" not in cart_page
    add_to_cart(client, factory.product(name="Blocked Item").sku)  # blocked while the payment is unresolved
    assert "Blocked Item" not in client.get("/cart").text
    assert other_client.get(f"/checkout/status/{key}").status_code == 404  # not another shopper's page

    faults.clear()
    assert client.get(f"/checkout/status/{key}").status_code == 200  # reloading alone resolves nothing
    assert order_count(session_factory) == 0
    assert reconciler.run_once() == {"completed": 1}  # the reconciler does
    resolved = client.get(f"/checkout/status/{key}", follow_redirects=False)
    assert resolved.status_code == 303 and "/confirmation" in resolved.headers["location"]
    assert client.get(resolved.headers["location"]).status_code == 200
    assert order_count(session_factory) == 1 and inventory(session_factory, product) == 3
    assert_consistent(session_factory, processor)


def test_capture_refused_card_shows_failure_and_restores_cart(client, factory, session_factory, processor):
    product = factory.product(inventory_qty=4)
    add_to_cart(client, product.sku, 2)
    response = submit_checkout(client, checkout_key(client), card_number="4000 0000 0000 0341")
    assert response.status_code == 409 and "could not be completed" in response.text
    assert inventory(session_factory, product) == 4
    assert 'value="2"' in client.get("/cart").text  # cart is editable again
    assert_consistent(session_factory, processor)


def test_status_page_is_read_only(client, factory, faults, session_factory, processor, reconciler):
    """Repeated GETs never call the processor or change checkout, order, inventory or payment state."""
    product = factory.product(inventory_qty=4)
    add_to_cart(client, product.sku)
    key = checkout_key(client)
    faults.unavailable("capture")
    submit_checkout(client, key)  # authorized and reserved; capture outcome unknown
    faults.clear()

    def snapshot():
        with session_factory() as db:
            attempt = db.scalar(select(CheckoutAttempt))
            cart = db.scalar(select(Cart))
            state = (attempt.status, attempt.updated_at, cart.status, cart.updated_at, len(db.scalars(select(Order)).all()))
        return state, inventory(session_factory, product), processor.get(attempt.payment_reference)

    before, calls = snapshot(), dict(faults.attempted)
    for _ in range(5):
        response = client.get(f"/checkout/status/{key}")
        assert response.status_code == 200 and 'data-testid="payment-processing"' in response.text

    assert snapshot() == before  # Northstar and FakePay state untouched (FakePay still "authorized")
    assert dict(faults.attempted) == calls  # no request of any kind was sent to the processor
    assert before[2].status.value == "authorized"

    assert reconciler.run_once() == {"completed": 1}  # only the reconciler advances it
    assert order_count(session_factory) == 1
    assert_consistent(session_factory, processor)
