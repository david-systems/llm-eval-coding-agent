"""Shopping carts for guests and registered customers.

A cart is not an inventory reservation and does not lock prices: it holds
product/quantity pairs, and totals always use current selling prices.

Every mutation locks the cart row first, which serializes it with checkout
(which locks the same row before reserving it).

While checkout holds a cart's inventory reservation and waits for payment
capture, the cart is CHECKING_OUT: it is still the shopper's current cart, but
it cannot be changed. It becomes COMPLETED when the order is created, or
ACTIVE again if the payment cannot be captured.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from northstar import pricing
from northstar.models import OPEN_CART_STATUSES, Cart, CartItem, CartStatus, Customer, CustomerLevel, Product
from northstar.security import new_token
from northstar.services import NotFound, ValidationError

MAX_QUANTITY_INPUT = 999  # sanity bound on a single quantity entry


class CartClosedError(Exception):
    """The cart has been checked out (or merged) and can no longer change."""


class CartCheckingOutError(CartClosedError):
    """The cart is reserved by a checkout whose payment is still being confirmed."""


def parse_quantity(raw: str | int | None, *, allow_zero: bool) -> int:
    try:
        quantity = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValidationError({"quantity": "Enter a whole-number quantity."}) from None
    minimum = 0 if allow_zero else 1
    if quantity < minimum or quantity > MAX_QUANTITY_INPUT:
        raise ValidationError({"quantity": f"Quantity must be between {minimum} and {MAX_QUANTITY_INPUT}."})
    return quantity


# --------------------------------------------------------------------------- lookup


def get_customer_cart(db: Session, customer_id: int) -> Optional[Cart]:
    """The customer's current cart: active, or reserved by an in-progress checkout."""
    return db.scalar(select(Cart).where(Cart.customer_id == customer_id, Cart.status.in_(OPEN_CART_STATUSES)))


def get_or_create_customer_cart(db: Session, customer_id: int) -> Cart:
    # Lock the customer row so concurrent requests cannot both create a cart.
    db.execute(select(Customer.id).where(Customer.id == customer_id).with_for_update().execution_options(populate_existing=True))
    cart = get_customer_cart(db, customer_id)
    if cart is None:
        cart = Cart(customer_id=customer_id, status=CartStatus.ACTIVE)
        db.add(cart)
        db.flush()
    return cart


def get_guest_cart(db: Session, token: Optional[str]) -> Optional[Cart]:
    if not token:
        return None
    return db.scalar(
        select(Cart).where(
            Cart.guest_token == token, Cart.customer_id.is_(None), Cart.status.in_(OPEN_CART_STATUSES)
        )
    )


def create_guest_cart(db: Session) -> Cart:
    cart = Cart(guest_token=new_token(), status=CartStatus.ACTIVE)
    db.add(cart)
    db.flush()
    return cart


def _lock_active_cart(db: Session, cart_id: int) -> Cart:
    cart = db.scalar(select(Cart).where(Cart.id == cart_id).with_for_update().execution_options(populate_existing=True))
    if cart is None:
        raise NotFound(cart_id)
    if cart.status == CartStatus.CHECKING_OUT:
        raise CartCheckingOutError()
    if cart.status != CartStatus.ACTIVE:
        raise CartClosedError()
    db.refresh(cart, ["items"])
    return cart


# --------------------------------------------------------------------------- mutation


def add_item(db: Session, cart_id: int, product_id: int, quantity: int) -> CartItem:
    """Add a quantity of a product; adding a product already in the cart increases it."""
    cart = _lock_active_cart(db, cart_id)
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise ValidationError({"product": "This product is not available for purchase."})
    item = next((i for i in cart.items if i.product_id == product_id), None)
    if item is None:
        item = CartItem(cart=cart, product=product, quantity=quantity)
        db.add(item)
    else:
        item.quantity += quantity
    db.flush()
    return item


def set_quantity(db: Session, cart_id: int, product_id: int, quantity: int) -> None:
    """Set a line's quantity; zero removes the line."""
    cart = _lock_active_cart(db, cart_id)
    item = next((i for i in cart.items if i.product_id == product_id), None)
    if item is None:
        raise NotFound(product_id)
    if quantity == 0:
        cart.items.remove(item)
    else:
        item.quantity = quantity
    db.flush()


def remove_item(db: Session, cart_id: int, product_id: int) -> None:
    set_quantity(db, cart_id, product_id, 0)


def merge_guest_cart(db: Session, guest_token: Optional[str], customer_id: int) -> Optional[Cart]:
    """Merge a guest's active cart into the customer's active cart at login.

    Quantities of a SKU present in both carts are combined. The customer's cart
    (created if needed) remains the active persisted cart; the guest cart is
    closed as merged. Returns the customer cart, or None if there was nothing
    to merge.

    Raises CartCheckingOutError if either cart is reserved by a checkout whose
    payment is still being confirmed; the caller retries the merge later.
    """
    guest = get_guest_cart(db, guest_token)
    if guest is None:
        return None
    guest = _lock_active_cart(db, guest.id)
    customer_cart = get_or_create_customer_cart(db, customer_id)
    customer_cart = _lock_active_cart(db, customer_cart.id)
    existing = {item.product_id: item for item in customer_cart.items}
    for guest_item in guest.items:
        if guest_item.product_id in existing:
            existing[guest_item.product_id].quantity += guest_item.quantity
        else:
            customer_cart.items.append(CartItem(product_id=guest_item.product_id, quantity=guest_item.quantity))
    guest.status = CartStatus.MERGED
    guest.closed_at = datetime.now(timezone.utc)
    db.flush()
    return customer_cart


# --------------------------------------------------------------------------- presentation


@dataclass(frozen=True)
class CartLine:
    product: Product
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    issue: Optional[str]  # why this line cannot currently be purchased


@dataclass(frozen=True)
class CartView:
    cart_id: Optional[int]
    lines: list[CartLine]
    totals: pricing.Totals
    level: Optional[CustomerLevel]
    checking_out: bool = False  # reserved by a checkout awaiting payment confirmation

    @property
    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def is_empty(self) -> bool:
        return not self.lines

    @property
    def has_issues(self) -> bool:
        return any(line.issue for line in self.lines)

    @property
    def free_shipping_threshold(self) -> Decimal:
        return pricing.FREE_SHIPPING_THRESHOLDS[self.level]


def view_cart(cart: Optional[Cart], level: Optional[CustomerLevel]) -> CartView:
    """Current-price view of a cart with the shipping/tax the shopper would pay now."""
    lines: list[CartLine] = []
    checking_out = cart is not None and cart.status == CartStatus.CHECKING_OUT
    for item in cart.items if cart is not None else []:
        product = item.product
        issue = None
        if checking_out:
            pass  # its inventory is already reserved; availability no longer applies
        elif not product.is_active:
            issue = "No longer available"
        elif product.inventory_qty < item.quantity:
            issue = "Out of stock" if product.inventory_qty == 0 else "Not enough stock for this quantity"
        lines.append(
            CartLine(
                product=product,
                quantity=item.quantity,
                unit_price=product.price,
                line_total=pricing.line_total(product.price, item.quantity),
                issue=issue,
            )
        )
    totals = pricing.calculate_totals(((line.unit_price, line.quantity) for line in lines), level)
    if not lines:
        totals = pricing.Totals(totals.subtotal, Decimal("0.00"), totals.tax, totals.subtotal + totals.tax)
    return CartView(cart_id=cart.id if cart else None, lines=lines, totals=totals, level=level, checking_out=checking_out)
