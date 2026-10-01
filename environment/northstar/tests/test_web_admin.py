"""Administration through HTTP: authorization, products, MAP warning, homepage, customers, orders."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from northstar.models import Customer, CustomerLevel, Product
from tests.web import add_to_cart, checkout_key, csrf, login_admin, login_customer, post, submit_checkout

ADMIN_PAGES = ["/admin", "/admin/products", "/admin/products/new", "/admin/homepage", "/admin/customers",
               "/admin/customers/new", "/admin/orders"]


@pytest.fixture
def admin_client(client, factory):
    factory.admin()
    login_admin(client)
    return client


def _product_form(product=None, **overrides):
    form = {
        "sku": "NS-NEW-01",
        "name": "Harborline Teak Bench",
        "description": "A bench.",
        "brand_id": "",
        "category_id": "",
        "msrp": "700.00",
        "map_price": "630.00",
        "map_enforced": "on",
        "price": "650.00",
        "cost": "380.00",
        "inventory_qty": "6",
        "is_active": "on",
    }
    if product is not None:
        form.update(
            sku=product.sku, brand_id=str(product.brand_id), category_id=str(product.category_id),
            version=str(product.version), name=product.name, price=f"{product.price}", cost=f"{product.cost}",
            msrp=f"{product.msrp}", map_price="" if product.map_price is None else f"{product.map_price}",
            map_enforced="on" if product.map_enforced else "", inventory_qty=str(product.inventory_qty),
            is_active="on" if product.is_active else "",
        )
    form.update(overrides)
    return {k: v for k, v in form.items() if v != ""}


# --------------------------------------------------------------------------- authorization


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_admin_pages_require_admin_login(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/admin/login")


def test_customer_login_does_not_grant_admin(client, factory):
    factory.customer(email="shopper@example.com")
    login_customer(client, "shopper@example.com")
    assert client.get("/admin/products", follow_redirects=False).status_code == 303


def test_admin_post_requires_admin(client, factory):
    brand, category = factory.brand(), factory.category()
    response = post(client, "/admin/products/new", _product_form(brand_id=str(brand.id), category_id=str(category.id)))
    assert response.status_code == 303 and response.headers["location"].startswith("/admin/login")
    with factory.sessions() as db:
        assert db.scalar(select(Product)) is None


def test_admin_login_failure_and_logout(client, factory):
    factory.admin()
    bad = post(client, "/admin/login", {"username": "admin", "password": "nope"}, token=csrf(client, "/admin/login"))
    assert bad.status_code == 401
    login_admin(client)
    for path in ADMIN_PAGES:
        assert client.get(path).status_code == 200, path
    post(client, "/admin/logout", token=csrf(client, "/admin"))
    assert client.get("/admin", follow_redirects=False).status_code == 303


# --------------------------------------------------------------------------- products


def test_admin_creates_and_edits_product(admin_client, factory, db):
    brand, category = factory.brand(), factory.category()
    created = post(admin_client, "/admin/products/new",
                   _product_form(brand_id=str(brand.id), category_id=str(category.id), map_enforced=""))
    assert created.status_code == 303
    product = db.scalar(select(Product).where(Product.sku == "NS-NEW-01"))
    assert product.price == Decimal("650.00") and product.inventory_qty == 6

    edited = post(admin_client, f"/admin/products/{product.id}",
                  _product_form(product, price="599.99", inventory_qty="11", name="Teak Bench II"))
    assert edited.status_code == 303
    db.expire_all()
    product = db.get(Product, product.id)
    assert (product.price, product.inventory_qty, product.name, product.sku) == (
        Decimal("599.99"), 11, "Teak Bench II", "NS-NEW-01"
    )


def test_product_form_validation_errors(admin_client, factory):
    response = post(admin_client, "/admin/products/new", {"sku": "", "name": "", "msrp": "abc"})
    assert response.status_code == 422 and "Name is required" in response.text


def test_stale_product_edit_is_rejected(admin_client, factory, session_factory, db):
    product = factory.product(inventory_qty=5)
    form = _product_form(product, inventory_qty="5", price="1.00")
    with session_factory.begin() as sale:  # e.g. a checkout sold one unit after the admin opened the form
        sale.get(Product, product.id).inventory_qty = 4
    response = post(admin_client, f"/admin/products/{product.id}", form)
    assert response.status_code == 409 and "changed since you opened it" in response.text
    stored = db.get(Product, product.id)
    assert stored.inventory_qty == 4 and stored.price == Decimal("100.00")


def test_map_warning_shown_when_enforced_product_priced_below_map(admin_client, factory):
    product = factory.product(map_price="500.00", map_enforced=True, price="520.00")
    response = post(admin_client, f"/admin/products/{product.id}", _product_form(product, price="480.00"))
    assert response.status_code == 303  # below-MAP pricing is allowed

    page = admin_client.get(f"/admin/products/{product.id}").text
    assert "MAP warning" in page and 'data-testid="map-warning"' in page
    assert "below-map-badge" in admin_client.get("/admin/products").text
    assert product.sku in admin_client.get("/admin").text  # dashboard lists it
    assert product.sku in admin_client.get("/admin/products?below_map=true").text


@pytest.mark.parametrize("map_price, enforced, price", [("500.00", True, "500.00"), ("500.00", False, "400.00")])
def test_no_map_warning_at_map_or_when_not_enforced(admin_client, factory, map_price, enforced, price):
    product = factory.product(map_price=map_price, map_enforced=enforced, price=price)
    page = admin_client.get(f"/admin/products/{product.id}").text
    assert 'data-testid="map-warning"' not in page
    assert "below-map-badge" not in admin_client.get("/admin/products").text


def test_below_map_price_is_shown_normally_on_storefront(admin_client, factory):
    product = factory.product(map_price="500.00", map_enforced=True, price="450.00")
    assert "$450.00" in admin_client.get(f"/products/{product.sku}").text


def test_deactivate_and_reactivate_product(admin_client, factory):
    product = factory.product()
    post(admin_client, f"/admin/products/{product.id}/flag", {"flag": "is_active", "value": "false"})
    assert admin_client.get(f"/products/{product.sku}").status_code == 404
    post(admin_client, f"/admin/products/{product.id}/flag", {"flag": "is_active", "value": "true"})
    assert admin_client.get(f"/products/{product.sku}").status_code == 200


# --------------------------------------------------------------------------- homepage


def test_featured_new_and_announcement_managed_by_admin(admin_client, factory):
    product = factory.product(name="Cedar Adirondack Chair")
    home = admin_client.get("/").text
    assert "Cedar Adirondack Chair" not in home

    post(admin_client, f"/admin/products/{product.id}/flag", {"flag": "is_featured", "value": "true"})
    post(admin_client, f"/admin/products/{product.id}/flag", {"flag": "is_new", "value": "true"})
    post(admin_client, "/admin/homepage", {"announcement_text": "Free chair covers this week", "announcement_active": "on"})
    home = admin_client.get("/").text
    featured = home.split('id="featured"')[1].split('id="new-arrivals"')[0]
    new = home.split('id="new-arrivals"')[1]
    assert "Cedar Adirondack Chair" in featured and "Cedar Adirondack Chair" in new
    assert "Free chair covers this week" in home

    post(admin_client, f"/admin/products/{product.id}/flag", {"flag": "is_featured", "value": "false"})
    post(admin_client, "/admin/homepage", {"announcement_text": "Free chair covers this week"})  # unchecked: hidden
    home = admin_client.get("/").text
    assert "Cedar Adirondack Chair" not in home.split('id="featured"')[1].split('id="new-arrivals"')[0]
    assert "Free chair covers this week" not in home


def test_unknown_flag_is_rejected(admin_client, factory, db):
    product = factory.product()
    post(admin_client, f"/admin/products/{product.id}/flag", {"flag": "price", "value": "true"})
    assert db.get(Product, product.id).price == Decimal("100.00")


# --------------------------------------------------------------------------- customers


def test_admin_creates_customer_defaulting_to_retail(admin_client, db):
    response = post(admin_client, "/admin/customers/new",
                    {"email": "fresh@example.com", "first_name": "Fresh", "last_name": "Start", "password": "longpassword"})
    assert response.status_code == 303
    assert db.scalar(select(Customer).where(Customer.email == "fresh@example.com")).level == CustomerLevel.RETAIL


def test_admin_changes_customer_level_affecting_shipping(admin_client, other_client, factory, db):
    customer = factory.customer(email="upgrade@example.com")
    product = factory.product(price="300.00")
    login_customer(other_client, customer.email)
    add_to_cart(other_client, product.sku)
    assert "$20.00" in other_client.get("/cart").text  # retail below $999

    form = {"email": customer.email, "first_name": customer.first_name, "last_name": customer.last_name, "level": "contractor"}
    assert post(admin_client, f"/admin/customers/{customer.id}", form).status_code == 303
    db.expire_all()
    assert db.get(Customer, customer.id).level == CustomerLevel.CONTRACTOR
    cart = other_client.get("/cart").text
    assert "FREE" in cart and "Contractor" in cart


def test_admin_detail_pages_render(admin_client, factory, checkout_service):
    customer = factory.customer(email="detail@example.com")
    product = factory.product(name="Detail Grill")
    order_id = checkout_service.checkout(
        factory.checkout_request(factory.cart((product, 1), customer=customer), customer)
    ).order_id
    customer_page = admin_client.get(f"/admin/customers/{customer.id}")
    assert customer_page.status_code == 200 and f"NS-{100000 + order_id}" in customer_page.text
    assert admin_client.get(f"/admin/products/{product.id}").status_code == 200
    assert admin_client.get(f"/admin/orders/{order_id}").status_code == 200
    assert admin_client.get("/admin/customers/999999").status_code == 404


def test_invalid_customer_level_rejected(admin_client, factory):
    customer = factory.customer()
    form = {"email": customer.email, "first_name": "A", "last_name": "B", "level": "platinum"}
    assert post(admin_client, f"/admin/customers/{customer.id}", form).status_code == 422


# --------------------------------------------------------------------------- orders


def test_admin_views_orders_with_historical_snapshot(admin_client, other_client, factory, session_factory):
    product = factory.product(name="Original Name", price="120.00", cost="70.00")
    add_to_cart(other_client, product.sku)
    location = submit_checkout(other_client, checkout_key(other_client)).headers["location"]
    order_id = int(location.split("/")[2])

    with session_factory.begin() as db:
        p = db.get(Product, product.id)
        p.name, p.price, p.cost = "Renamed", Decimal("1.00"), Decimal("0.50")

    listing = admin_client.get("/admin/orders").text
    assert f"NS-{100000 + order_id}" in listing and "Guest" in listing
    detail = admin_client.get(f"/admin/orders/{order_id}").text
    assert "Original Name" in detail and "$120.00" in detail and "$70.00" in detail
    assert "Renamed" not in detail


def test_dashboard_lists_checkouts_awaiting_payment_confirmation(admin_client, other_client, factory, faults):
    assert "Every checkout has a confirmed outcome" in admin_client.get("/admin").text
    add_to_cart(other_client, factory.product().sku)
    faults.unavailable("capture")
    submit_checkout(other_client, checkout_key(other_client))
    page = admin_client.get("/admin").text
    assert 'data-testid="unresolved-checkouts"' in page and "capturing" in page
