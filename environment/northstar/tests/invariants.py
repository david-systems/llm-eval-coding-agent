"""Cross-boundary consistency checks.

Northstar state is read from Northstar's database; payment state is read only
through FakePay's public API, exactly as Northstar itself would see it.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select

from northstar.models import AttemptStatus, Cart, CheckoutAttempt, Order, Product
from northstar.services.payments import FakePayClient, PaymentStatus


def violations(session_factory, processor: FakePayClient, *, allow_unfinished: bool = False) -> list[str]:
    with session_factory() as db:
        attempts = db.scalars(select(CheckoutAttempt).order_by(CheckoutAttempt.id)).all()
        orders = db.scalars(select(Order)).all()
        products = db.scalars(select(Product)).unique().all()
        carts = {c.id: c for c in db.scalars(select(Cart))}

    problems: list[str] = []
    orders_by_attempt = Counter(o.checkout_attempt_id for o in orders if o.checkout_attempt_id)
    orders_by_cart = Counter(o.cart_id for o in orders)
    order_for = {o.checkout_attempt_id: o for o in orders}

    problems += [f"cart {cart_id} has {n} orders" for cart_id, n in orders_by_cart.items() if n > 1]
    problems += [f"{p.sku} inventory is negative" for p in products if p.inventory_qty < 0]

    for attempt in attempts:
        label = f"attempt {attempt.id} ({attempt.status.value})"
        txn = processor.get(attempt.payment_reference)
        n_orders = orders_by_attempt[attempt.id]
        if txn is not None:
            repeated = [kind for kind, n in Counter(txn.events).items() if n > 1]
            if repeated:
                problems.append(f"{label}: duplicate payment effects {repeated}")

        if attempt.status == AttemptStatus.COMPLETED:
            if n_orders != 1:
                problems.append(f"{label}: {n_orders} orders")
            if txn is None or txn.status != PaymentStatus.CAPTURED:
                problems.append(f"{label}: completed without confirmed capture ({txn and txn.status})")
            elif txn.amount != attempt.total or order_for[attempt.id].total != attempt.total:
                problems.append(f"{label}: captured amount does not match order total")
        elif attempt.status == AttemptStatus.FAILED:
            if n_orders:
                problems.append(f"{label}: failed attempt has an order")
            if txn is not None and txn.status not in (PaymentStatus.DECLINED, PaymentStatus.VOIDED):
                problems.append(f"{label}: failed attempt left payment {txn.status.value}")
        else:
            if n_orders:
                problems.append(f"{label}: unfinished attempt has an order")
            if txn is not None and txn.status == PaymentStatus.CAPTURED and attempt.status != AttemptStatus.CAPTURING:
                problems.append(f"{label}: captured payment cannot be recovered from this state")
            if not allow_unfinished:
                problems.append(f"{label}: unresolved")
    # A reserved cart is held by exactly one attempt that is awaiting capture.
    capturing = Counter(a.cart_id for a in attempts if a.status == AttemptStatus.CAPTURING)
    for cart in carts.values():
        if cart.status.value == "checking_out" and capturing[cart.id] != 1:
            problems.append(f"cart {cart.id} is reserved by {capturing[cart.id]} capturing attempts")
    return problems


def assert_consistent(session_factory, processor: FakePayClient, *, allow_unfinished: bool = False) -> None:
    problems = violations(session_factory, processor, allow_unfinished=allow_unfinished)
    assert not problems, "\n".join(problems)
