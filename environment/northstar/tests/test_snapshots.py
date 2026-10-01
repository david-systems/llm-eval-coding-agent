"""Completed orders are immutable historical records (spec section 19; invariants 19-22)."""

from decimal import Decimal

from northstar.models import Customer, CustomerLevel, Product
from northstar.services.orders import customer_orders, get_order


def _snapshot(order):
    return (
        order.email,
        order.first_name,
        order.customer_level,
        order.subtotal,
        order.shipping,
        order.tax,
        order.total,
        [(l.sku, l.product_name, l.brand_name, l.quantity, l.unit_price, l.unit_cost, l.line_total) for l in order.lines],
    )


def test_order_snapshot_survives_catalog_and_customer_changes(factory, checkout_service, session_factory):
    customer = factory.customer(level=CustomerLevel.CONTRACTOR, first_name="Riley")
    product = factory.product(
        name="Summit 4-Burner Grill", price="600.00", cost="390.00", map_price="580.00", map_enforced=True
    )
    order_id = checkout_service.checkout(
        factory.checkout_request(factory.cart((product, 1), customer=customer), customer)
    ).order_id

    with session_factory() as db:
        before = _snapshot(get_order(db, order_id))

    with session_factory.begin() as admin:
        p = admin.get(Product, product.id)
        p.name, p.price, p.cost, p.map_price, p.is_active = "Renamed Grill", Decimal("1.00"), Decimal("0.50"), None, False
        p.map_enforced = False
        c = admin.get(Customer, customer.id)
        c.first_name, c.email, c.level = "Changed", "changed@example.com", CustomerLevel.VIP

    with session_factory() as db:
        order = get_order(db, order_id)
        assert _snapshot(order) == before
        assert order.lines[0].product_name == "Summit 4-Burner Grill"
        # The order remains a valid historical record in the customer's history.
        assert [o.id for o in customer_orders(db, customer.id)] == [order_id]


def test_historical_cost_snapshot(factory, checkout_service, session_factory):
    product = factory.product(price="200.00", cost="120.00", inventory_qty=10)
    first = checkout_service.checkout(factory.checkout_request(factory.cart((product, 1)))).order_id

    with session_factory.begin() as admin:
        admin.get(Product, product.id).cost = Decimal("140.00")

    second = checkout_service.checkout(factory.checkout_request(factory.cart((product, 2)))).order_id

    with session_factory() as db:
        assert get_order(db, first).lines[0].unit_cost == Decimal("120.00")
        assert get_order(db, second).lines[0].unit_cost == Decimal("140.00")
        assert get_order(db, second).total_cost == Decimal("280.00")


def test_historical_price_snapshot(factory, checkout_service, session_factory):
    product = factory.product(price="80.00")
    first = checkout_service.checkout(factory.checkout_request(factory.cart((product, 1)))).order_id
    with session_factory.begin() as admin:
        admin.get(Product, product.id).price = Decimal("95.00")
    second = checkout_service.checkout(factory.checkout_request(factory.cart((product, 1)))).order_id
    with session_factory() as db:
        assert get_order(db, first).lines[0].unit_price == Decimal("80.00")
        assert get_order(db, second).lines[0].unit_price == Decimal("95.00")
