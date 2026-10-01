"""Deterministic seed data (spec section 23) and the reproducible order history."""

import hashlib
import json

import pytest
from sqlalchemy import select, text

from northstar import pricing
from northstar.models import Cart, CartStatus, Category, Customer, CustomerLevel, Order, Product
from northstar.seed import seed
from northstar.services.customers import authenticate_admin, authenticate_customer
from tests.conftest import TABLES

# Content columns only: surrogate timestamps and password hashes (random salts) are excluded.
DIGEST_QUERIES = [
    "SELECT name, slug FROM brands ORDER BY id",
    "SELECT name, slug, parent_id, position FROM categories ORDER BY id",
    "SELECT sku, name, description, brand_id, category_id, msrp, map_price, map_enforced, price, cost, "
    "inventory_qty, is_active, is_featured, is_new FROM products ORDER BY id",
    "SELECT email, first_name, last_name, level, phone, address_line1, city, state, postal_code FROM customers ORDER BY id",
    "SELECT cart_id, customer_id, customer_level, email, subtotal, shipping, tax, total, placed_at FROM orders ORDER BY id",
    "SELECT order_id, sku, product_name, brand_name, quantity, unit_price, unit_cost, line_total FROM order_lines ORDER BY id",
    "SELECT customer_id, status FROM carts ORDER BY id",
    "SELECT announcement_text, announcement_active FROM site_settings",
]


def _seed_digest(session_factory) -> str:
    with session_factory() as db:
        rows = [[list(map(str, row)) for row in db.execute(text(q))] for q in DIGEST_QUERIES]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


@pytest.fixture
def seeded(session_factory):
    with session_factory.begin() as db:
        seed(db)


def test_seed_is_deterministic(session_factory, engine):
    with session_factory.begin() as db:
        seed(db)
    first = _seed_digest(session_factory)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        conn.execute(text("INSERT INTO site_settings (id) VALUES (1)"))
    with session_factory.begin() as db:
        seed(db)
    assert _seed_digest(session_factory) == first


def test_seed_refuses_to_run_twice(seeded, session_factory):
    with pytest.raises(RuntimeError), session_factory.begin() as db:
        seed(db)


def test_seed_catalog_shape(seeded, db):
    products = db.scalars(select(Product)).unique().all()
    assert 50 <= len(products) <= 100
    assert len({p.brand_id for p in products}) >= 5
    tops = db.scalars(select(Category).where(Category.parent_id.is_(None))).all()
    assert len(tops) >= 5 and all(top.children for top in tops)
    assert all(p.category.parent_id is not None for p in products)  # products sit in subcategories

    prices = sorted(p.price for p in products)
    assert prices[0] < 30 and prices[-1] > 2000  # varied price points
    assert any(p.map_enforced for p in products) and any(p.map_price is None for p in products)
    assert any(p.map_enforced and p.price == p.map_price for p in products)  # at MAP
    assert any(p.map_enforced and p.price > p.map_price for p in products)  # above MAP
    assert [p.sku for p in products if p.is_below_map] == ["EMB-PL-850"]  # deliberate admin warning example
    assert any(0 < p.inventory_qty <= 3 for p in products) and any(p.inventory_qty == 0 for p in products)
    assert any(p.is_featured and p.is_active for p in products)
    assert any(p.is_new and p.is_active for p in products)
    assert any(not p.is_active for p in products)


def test_seed_customers_and_accounts(seeded, db):
    customers = db.scalars(select(Customer)).all()
    assert 20 <= len(customers) <= 50
    assert {c.level for c in customers} == set(CustomerLevel)
    for email in ("olivia.bennett@example.com", "marcus.reed@example.com", "sofia.alvarez@example.com"):
        assert authenticate_customer(db, email, "northstar123") is not None
    assert authenticate_admin(db, "admin", "northstar123") is not None


def test_seed_order_history_is_internally_consistent(seeded, db):
    orders = db.scalars(select(Order)).all()
    assert len(orders) >= 30
    assert any(o.customer_id is None for o in orders) and any(o.customer_id for o in orders)
    for order in orders:
        expected = pricing.calculate_totals([(l.unit_price, l.quantity) for l in order.lines], order.customer_level)
        assert (order.subtotal, order.shipping, order.tax, order.total) == (
            expected.subtotal, expected.shipping, expected.tax, expected.total
        ), order.id
        assert order.is_imported and order.payment_reference.startswith("IMPORTED-")  # no FakePay record
    # History includes a since-discontinued product, and prices that differ from today's.
    inactive_skus = {p.sku for p in db.scalars(select(Product).where(Product.is_active.is_(False)))}
    history_skus = {line.sku for o in orders for line in o.lines}
    assert inactive_skus & history_skus
    current = {p.sku: p.price for p in db.scalars(select(Product))}
    assert any(line.unit_price != current[line.sku] for o in orders for line in o.lines)


def test_seed_has_persisted_customer_carts(seeded, db):
    active = db.scalars(select(Cart).where(Cart.status == CartStatus.ACTIVE, Cart.customer_id.is_not(None))).all()
    assert len(active) >= 1 and all(cart.items for cart in active)


def test_seeded_store_renders(seeded, client):
    home = client.get("/").text
    assert "Free shipping on orders of $999" in home
    assert client.get("/categories/grills").status_code == 200
    assert client.get("/products/EMB-GG-4B").status_code == 200
    assert client.get("/products/RDG-GG-3LX").status_code == 404  # discontinued
