"""Read access to completed orders."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from northstar.models import Order


def get_order(db: Session, order_id: int) -> Optional[Order]:
    return db.scalar(select(Order).where(Order.id == order_id).options(selectinload(Order.lines)))


def customer_orders(db: Session, customer_id: int) -> list[Order]:
    stmt = (
        select(Order)
        .where(Order.customer_id == customer_id)
        .options(selectinload(Order.lines))
        .order_by(Order.placed_at.desc(), Order.id.desc())
    )
    return list(db.scalars(stmt))


def admin_orders(db: Session, search: Optional[str] = None) -> list[Order]:
    stmt = select(Order).options(selectinload(Order.lines)).order_by(Order.placed_at.desc(), Order.id.desc())
    if search:
        term = search.strip()
        pattern = f"%{term}%"
        conditions = [
            Order.email.ilike(pattern),
            func.concat(Order.first_name, " ", Order.last_name).ilike(pattern),
        ]
        digits = term.upper().removeprefix("NS-")
        if digits.isdigit():
            conditions.append(Order.id == int(digits) - 100000)
        stmt = stmt.where(or_(*conditions))
    return list(db.scalars(stmt))
