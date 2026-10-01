"""SQLAlchemy ORM models.

Business invariants that can be expressed declaratively are enforced by the
database as well as by services: non-negative inventory, one active cart per
customer, one order per cart and per checkout attempt, unique idempotency keys,
and the fixed set of customer levels.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(12, 2)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """A VARCHAR + CHECK constraint enum storing the member values."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class CustomerLevel(str, enum.Enum):
    RETAIL = "retail"
    CONTRACTOR = "contractor"
    VIP = "vip"

    @property
    def label(self) -> str:
        return "VIP" if self is CustomerLevel.VIP else self.value.capitalize()


class CartStatus(str, enum.Enum):
    ACTIVE = "active"
    CHECKING_OUT = "checking_out"  # inventory reserved; payment capture in progress
    COMPLETED = "completed"  # checked out; can never be checked out again
    MERGED = "merged"  # guest cart folded into a customer cart at login


OPEN_CART_STATUSES = (CartStatus.ACTIVE, CartStatus.CHECKING_OUT)


class AttemptStatus(str, enum.Enum):
    """Checkout attempt states. See northstar/services/checkout.py for the protocol."""

    AUTHORIZING = "authorizing"  # quoted; authorization may have been sent
    AUTHORIZED = "authorized"  # processor confirmed the authorization
    CAPTURING = "capturing"  # inventory reserved; capture may have been sent
    VOIDING = "voiding"  # cannot complete; authorization must be released
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_ATTEMPT_STATUSES = (AttemptStatus.COMPLETED, AttemptStatus.FAILED)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- catalog


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)


class Category(Base):
    """A top-level category (parent_id is NULL) or a subcategory.

    Only two levels are supported; services refuse deeper nesting.
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    parent: Mapped[Optional[Category]] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Category]] = relationship(
        back_populates="parent", order_by="Category.position, Category.name"
    )

    __table_args__ = (CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),)

    @property
    def is_top_level(self) -> bool:
        return self.parent_id is None


class Product(TimestampMixin, Base):
    """One sellable SKU."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    msrp: Mapped[Decimal] = mapped_column(MONEY)
    map_price: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    map_enforced: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    price: Mapped[Decimal] = mapped_column(MONEY)  # Northstar's current selling price
    cost: Mapped[Decimal] = mapped_column(MONEY)
    inventory_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_new: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Optimistic-concurrency version: admin edits submitted against a stale
    # version are rejected so they cannot overwrite checkout inventory changes.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    brand: Mapped[Brand] = relationship(lazy="joined")
    category: Mapped[Category] = relationship(lazy="joined")

    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        CheckConstraint("inventory_qty >= 0", name="inventory_non_negative"),
        CheckConstraint("msrp >= 0 AND price >= 0 AND cost >= 0", name="prices_non_negative"),
        CheckConstraint("map_price IS NULL OR map_price >= 0", name="map_non_negative"),
        CheckConstraint("NOT map_enforced OR map_price IS NOT NULL", name="enforced_map_has_price"),
    )

    @property
    def in_stock(self) -> bool:
        return self.inventory_qty > 0

    @property
    def is_below_map(self) -> bool:
        """True when MAP is enforced and the selling price is below MAP."""
        return bool(self.map_enforced and self.map_price is not None and self.price < self.map_price)


# --------------------------------------------------------------------------- people


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lower-cased
    password_hash: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    level: Mapped[CustomerLevel] = mapped_column(
        _enum(CustomerLevel, "customer_level"),
        default=CustomerLevel.RETAIL,
        server_default=CustomerLevel.RETAIL.value,
    )
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    address_line1: Mapped[str] = mapped_column(String(200), default="", server_default="")
    address_line2: Mapped[str] = mapped_column(String(200), default="", server_default="")
    city: Mapped[str] = mapped_column(String(100), default="", server_default="")
    state: Mapped[str] = mapped_column(String(50), default="", server_default="")
    postal_code: Mapped[str] = mapped_column(String(20), default="", server_default="")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class AdminUser(Base):
    """Administrators are separate from customers and have no customer level."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


# --------------------------------------------------------------------------- carts


class Cart(TimestampMixin, Base):
    """A shopping cart owned by a registered customer or by a guest token."""

    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    guest_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    status: Mapped[CartStatus] = mapped_column(
        _enum(CartStatus, "cart_status"), default=CartStatus.ACTIVE, server_default=CartStatus.ACTIVE.value
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", order_by="CartItem.id"
    )

    __table_args__ = (
        CheckConstraint("customer_id IS NOT NULL OR guest_token IS NOT NULL", name="has_owner"),
        # A registered customer has at most one open (active or checking-out) cart.
        Index(
            "uq_carts_one_open_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'checking_out') AND customer_id IS NOT NULL"),
        ),
    )


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


# --------------------------------------------------------------------------- checkout


class CheckoutAttempt(TimestampMixin, Base):
    """One checkout attempt, identified by a client-supplied idempotency key.

    Stores the Phase 1 quote (which fixes the attempt's monetary terms), the
    processor transaction reference, the inventory reservation, and the
    terminal outcome replayed for retries with the same key.
    """

    __tablename__ = "checkout_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"), index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[AttemptStatus] = mapped_column(_enum(AttemptStatus, "attempt_status"))
    # Northstar-generated, globally unique reference for this attempt's processor transaction.
    payment_reference: Mapped[str] = mapped_column(String(64), unique=True)
    card_last4: Mapped[Optional[str]] = mapped_column(String(4))

    # Contact / shipping details supplied with the request.
    email: Mapped[str] = mapped_column(String(254))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    address_line1: Mapped[str] = mapped_column(String(200))
    address_line2: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(50))
    postal_code: Mapped[str] = mapped_column(String(20))

    # Phase 1 quote (NULL until quoted).
    customer_level: Mapped[Optional[CustomerLevel]] = mapped_column(_enum(CustomerLevel, "attempt_level"))
    quote_lines: Mapped[Optional[list]] = mapped_column(JSONB)
    subtotal: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    shipping: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    tax: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    total: Mapped[Optional[Decimal]] = mapped_column(MONEY)

    # Snapshot of reserved lines (Phase 2): product identity, quantity, quoted
    # price and cost at reservation. Used to finalize the order after capture or
    # to release the reservation if capture is refused.
    reserved_lines: Mapped[Optional[list]] = mapped_column(JSONB)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50))
    failure_message: Mapped[Optional[str]] = mapped_column(Text)

    order: Mapped[Optional[Order]] = relationship(back_populates="checkout_attempt", uselist=False)


# --------------------------------------------------------------------------- orders


class Order(Base):
    """A completed order: an immutable historical record of one purchase.

    Every value needed to reconstruct the transaction is copied here rather
    than read through to current catalog or customer data.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="completed", server_default="completed")
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id"), unique=True)
    # NULL only for imported historical orders (seed data), which predate FakePay.
    checkout_attempt_id: Mapped[Optional[int]] = mapped_column(ForeignKey("checkout_attempts.id"), unique=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    customer_level: Mapped[Optional[CustomerLevel]] = mapped_column(_enum(CustomerLevel, "order_level"))

    email: Mapped[str] = mapped_column(String(254))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    address_line1: Mapped[str] = mapped_column(String(200))
    address_line2: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(50))
    postal_code: Mapped[str] = mapped_column(String(20))

    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    shipping: Mapped[Decimal] = mapped_column(MONEY)
    tax: Mapped[Decimal] = mapped_column(MONEY)
    total: Mapped[Decimal] = mapped_column(MONEY)

    payment_reference: Mapped[str] = mapped_column(String(64), unique=True)
    card_last4: Mapped[str] = mapped_column(String(4))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderLine.id"
    )
    checkout_attempt: Mapped[Optional[CheckoutAttempt]] = relationship(back_populates="order")

    @property
    def is_imported(self) -> bool:
        return self.checkout_attempt_id is None

    __table_args__ = (
        CheckConstraint("status = 'completed'", name="status_completed"),
        CheckConstraint("total = subtotal + shipping + tax", name="total_consistent"),
    )

    @property
    def number(self) -> str:
        return f"NS-{100000 + self.id}"

    @property
    def customer_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def total_cost(self) -> Decimal:
        return sum((line.unit_cost * line.quantity for line in self.lines), Decimal("0.00"))


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    # Reference only; historical values below are never read through this link.
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    sku: Mapped[str] = mapped_column(String(40))
    product_name: Mapped[str] = mapped_column(String(200))
    brand_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)

    order: Mapped[Order] = relationship(back_populates="lines")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("line_total = unit_price * quantity", name="line_total_consistent"),
    )


# --------------------------------------------------------------------------- content


class SiteSettings(Base):
    """Singleton row holding administratively managed homepage content."""

    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    announcement_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    announcement_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
