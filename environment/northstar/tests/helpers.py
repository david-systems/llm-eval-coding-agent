"""Assertions about persisted checkout state (payment state via FakePay's API only)."""

from __future__ import annotations

from sqlalchemy import func, select

from northstar.models import Cart, CheckoutAttempt, Order, Product
from northstar.services.payments import FakePayClient, PaymentStatus


def inventory(session_factory, product) -> int:
    with session_factory() as db:
        return db.get(Product, product.id).inventory_qty


def order_count(session_factory) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(Order))


def cart_status(session_factory, cart_id):
    with session_factory() as db:
        return db.get(Cart, cart_id).status


def attempt(session_factory, key) -> CheckoutAttempt:
    with session_factory() as db:
        return db.scalar(select(CheckoutAttempt).where(CheckoutAttempt.idempotency_key == key))


def transaction(session_factory, processor: FakePayClient, key):
    """FakePay's authoritative record for the attempt with this idempotency key."""
    return processor.get(attempt(session_factory, key).payment_reference)


def payment_statuses(session_factory, processor: FakePayClient) -> list[PaymentStatus]:
    """Authoritative processor status of every attempt's transaction (attempts with none are omitted)."""
    with session_factory() as db:
        references = db.scalars(select(CheckoutAttempt.payment_reference).order_by(CheckoutAttempt.id)).all()
    statuses = [txn.status for ref in references if (txn := processor.get(ref)) is not None]
    return sorted(statuses, key=lambda status: status.value)
