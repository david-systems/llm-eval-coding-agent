"""Small committed-data builders for tests."""

from __future__ import annotations

import itertools
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from northstar.models import Brand, Category, Customer, CustomerLevel, Product
from northstar.security import hash_password
from northstar.services import carts
from northstar.services.checkout import CheckoutRequest, Contact
from northstar.services.customers import create_admin

PASSWORD = "northstar123"

# FakePay deterministic test cards.
APPROVED_CARD = "4242424242424242"
DECLINED_CARD = "4000000000000002"
CAPTURE_REFUSED_CARD = "4000000000000341"
PASSWORD_HASH = hash_password(PASSWORD)  # hashed once: scrypt is deliberately slow


def contact(email: str = "guest@example.com") -> Contact:
    return Contact(
        email=email,
        first_name="Pat",
        last_name="Guest",
        address_line1="1 Trail Rd",
        city="Bend",
        state="OR",
        postal_code="97701",
    )


def new_key() -> str:
    return str(uuid.uuid4())


class Factory:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.sessions = session_factory
        self._seq = itertools.count(1)

    def _save(self, obj):
        with self.sessions.begin() as db:
            db.add(obj)
        return obj

    def brand(self, name: Optional[str] = None) -> Brand:
        n = next(self._seq)
        name = name or f"Brand {n}"
        return self._save(Brand(name=name, slug=f"brand-{n}"))

    def category(self, name: Optional[str] = None, parent: Optional[Category] = None) -> Category:
        n = next(self._seq)
        return self._save(Category(name=name or f"Category {n}", slug=f"category-{n}", parent_id=parent.id if parent else None))

    def product(self, **overrides) -> Product:
        n = next(self._seq)
        if "brand_id" not in overrides:
            overrides["brand_id"] = self.brand().id
        if "category_id" not in overrides:
            overrides["category_id"] = self.category().id
        values = dict(
            sku=f"TEST-{n:04d}",
            name=f"Test Product {n}",
            description="",
            msrp=Decimal("120.00"),
            map_price=None,
            map_enforced=False,
            price=Decimal("100.00"),
            cost=Decimal("60.00"),
            inventory_qty=10,
            is_active=True,
        )
        values.update(overrides)
        for money_field in ("msrp", "map_price", "price", "cost"):
            if isinstance(values[money_field], (str, int)):
                values[money_field] = Decimal(values[money_field])
        return self._save(Product(**values))

    def customer(self, level: CustomerLevel = CustomerLevel.RETAIL, email: Optional[str] = None, **extra) -> Customer:
        n = next(self._seq)
        return self._save(
            Customer(
                email=email or f"customer{n}@example.com",
                password_hash=PASSWORD_HASH,
                first_name=extra.pop("first_name", "Casey"),
                last_name=extra.pop("last_name", f"Customer{n}"),
                level=level,
                **extra,
            )
        )

    def admin(self, username: str = "admin"):
        with self.sessions.begin() as db:
            return create_admin(db, username, PASSWORD)

    def cart(self, *lines: tuple[Product, int], customer: Optional[Customer] = None) -> int:
        """Create an active cart (guest unless ``customer``) holding ``lines``; returns its id."""
        with self.sessions.begin() as db:
            cart = carts.get_or_create_customer_cart(db, customer.id) if customer else carts.create_guest_cart(db)
            for product, qty in lines:
                carts.add_item(db, cart.id, product.id, qty)
            return cart.id

    def checkout_request(
        self,
        cart_id: int,
        customer: Optional[Customer] = None,
        *,
        key: Optional[str] = None,
        card: str = APPROVED_CARD,
    ) -> CheckoutRequest:
        return CheckoutRequest(
            idempotency_key=key or new_key(),
            cart_id=cart_id,
            customer_id=customer.id if customer else None,
            contact=contact(customer.email if customer else "guest@example.com"),
            card_number=card,
        )
