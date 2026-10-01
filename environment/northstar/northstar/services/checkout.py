"""Checkout: converts an active cart into a completed order.

Payment is handled by an external processor (FakePay) that cannot share a
database transaction with Northstar, and any call to it can end without an
answer. Checkout is therefore a persisted state machine per attempt
(identified by the client's idempotency key). Each step is either one short
local transaction or one idempotent processor call, and the intent to make a
processor call is committed before the call is made.

    AUTHORIZING --authorize ok--> AUTHORIZED --reserve ok--> CAPTURING --capture ok--> COMPLETED
         |                            |                          |
         | declined                   | recheck fails            | capture refused:
         v                            v                          v release reservation
       FAILED  <------ void ok ---- VOIDING <---------------------+
         ^
         +-- (abandoned, processor has no record) -> VOIDING (void leaves a tombstone)

AUTHORIZING  Phase 1 committed the quote (fixed monetary terms). The
             authorization may or may not have reached the processor.
AUTHORIZED   The processor confirmed the authorization.
CAPTURING    Phase 2 locked, rechecked, decremented inventory, froze the cart
             (CHECKING_OUT), and snapshotted the lines. Capture may have been sent.
VOIDING      The attempt cannot complete; the authorization must be released.
COMPLETED    Capture confirmed; the order exists.
FAILED       Terminal; replaying the key returns the stored failure.

Correctness rules:

* An order is created only after the processor confirms capture.
* An unknown processor result never advances or fails an attempt. The attempt
  stays in its state and is resolved later from the processor's authoritative
  status (a same-key checkout resubmission or the reconciler). The shopper's
  status page only displays the attempt's current state; it never advances it.
* Every local transition is a compare-and-set on the attempt's status, and
  every processor operation is idempotent. Any number of workers (the original
  request, a same-key retry, reconcilers) may drive one attempt concurrently
  without duplicating effects.
* Elapsed time is never treated as evidence of a processor outcome. The only
  time-based decision is the reconciler's policy to stop waiting for an
  authorization the processor has no record of - and even then the attempt
  fails only after an explicit void has made that authorization impossible.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Optional, Union

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from northstar import pricing
from northstar.models import (
    TERMINAL_ATTEMPT_STATUSES,
    AttemptStatus,
    Cart,
    CartStatus,
    CheckoutAttempt,
    Customer,
    Order,
    OrderLine,
    Product,
)
from northstar.services import ValidationError
from northstar.services.customers import EMAIL_PATTERN, normalize_email
from northstar.services.payments import (
    FakePayClient,
    PaymentOutcomeUnknown,
    PaymentRejected,
    PaymentStatus,
    Transaction,
    is_plausible_card_number,
    normalize_card_number,
)

log = logging.getLogger(__name__)

MAX_KEY_LENGTH = 100
MAX_STEPS = 20  # guards the drive loop; a full successful checkout takes 4 steps

PROCESSING_MESSAGE = (
    "We're confirming your payment with our payment processor. "
    "Your order will be confirmed as soon as we have the result."
)


# --------------------------------------------------------------------------- request / outcome types


@dataclass(frozen=True)
class Contact:
    email: str
    first_name: str
    last_name: str
    address_line1: str
    city: str
    state: str
    postal_code: str
    address_line2: str = ""


@dataclass(frozen=True)
class CheckoutRequest:
    idempotency_key: str
    cart_id: int
    customer_id: Optional[int]
    contact: Contact
    card_number: str = field(repr=False)


class Outcome:
    COMPLETED = "completed"
    FAILED = "failed"
    PROCESSING = "processing"  # payment outcome not yet known; resolved by reconciliation
    CONFLICT = "conflict"  # key already used for a different cart/customer


@dataclass(frozen=True)
class CheckoutOutcome:
    status: str
    order_id: Optional[int] = None
    failure_code: Optional[str] = None
    message: Optional[str] = None
    replayed: bool = False

    @property
    def ok(self) -> bool:
        return self.status == Outcome.COMPLETED


class CheckoutFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class PaymentProtocolError(Exception):
    """The processor reported a state that Northstar's protocol can never produce."""


FAILURES = {
    "payment_declined": "Your payment was declined. Please use a different card.",
    "payment_capture_refused": "Your payment could not be completed, so your order was not placed. You have not been charged.",
    "payment_unconfirmed": "We could not confirm your payment, so your order was not placed. You have not been charged.",
    "payment_cancelled": "This payment was cancelled, so your order was not placed. You have not been charged.",
}


# --------------------------------------------------------------------------- form parsing


CONTACT_FIELDS = ("email", "first_name", "last_name", "address_line1", "address_line2", "city", "state", "postal_code")
REQUIRED_CONTACT_FIELDS = {
    "email": "Email",
    "first_name": "First name",
    "last_name": "Last name",
    "address_line1": "Address",
    "city": "City",
    "state": "State",
    "postal_code": "Postal code",
}


def parse_checkout_form(form: dict[str, str]) -> tuple[Contact, str]:
    """Validate checkout form input. Returns (contact, card digits)."""
    values = {name: (form.get(name) or "").strip() for name in CONTACT_FIELDS}
    values["email"] = normalize_email(values["email"])
    errors = {name: f"{label} is required." for name, label in REQUIRED_CONTACT_FIELDS.items() if not values[name]}
    if values["email"] and not EMAIL_PATTERN.match(values["email"]):
        errors["email"] = "Enter a valid email address."
    for name in CONTACT_FIELDS:
        if len(values[name]) > 200:
            errors[name] = "Too long."
    card = normalize_card_number(form.get("card_number", ""))
    if not is_plausible_card_number(card):
        errors["card_number"] = "Enter a card number (12-19 digits)."
    if errors:
        raise ValidationError(errors)
    return Contact(**values), card


# --------------------------------------------------------------------------- service


_STOP = "stop"  # a step could make no progress without new information


class CheckoutService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        payments: FakePayClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._sessions = session_factory
        self._payments = payments
        self._now = clock

    # ----------------------------------------------------------------- entry points

    def checkout(self, request: CheckoutRequest) -> CheckoutOutcome:
        """Start a checkout attempt, or retry/replay the attempt for this key."""
        key = (request.idempotency_key or "").strip()
        if not key or len(key) > MAX_KEY_LENGTH:
            raise ValueError("a checkout idempotency key of 1-100 characters is required")
        started = self._begin(request)
        if isinstance(started, CheckoutOutcome):
            return started
        return self._drive(started, card_number=request.card_number)

    def resume(self, attempt_id: int, *, abandon_unconfirmed: bool = False) -> CheckoutOutcome:
        """Advance an attempt using the processor's authoritative state (no card details).

        ``abandon_unconfirmed`` is the reconciler's policy decision to stop
        waiting for an authorization the processor has no record of. It does
        not assume the authorization failed: the attempt is voided at the
        processor first, which also blocks any delayed authorization.
        """
        return self._drive(attempt_id, card_number=None, abandon_unconfirmed=abandon_unconfirmed)

    def current_outcome(self, idempotency_key: str) -> Optional[CheckoutOutcome]:
        """Northstar's recorded state for this key. Read-only: no processor call, no state change."""
        with self._sessions() as db:
            attempt = db.scalar(select(CheckoutAttempt).where(CheckoutAttempt.idempotency_key == idempotency_key))
        return None if attempt is None else self._outcome(attempt)

    # ----------------------------------------------------------------- phase 1

    def _begin(self, request: CheckoutRequest) -> Union[CheckoutOutcome, int]:
        """Create and quote the attempt, or find the existing attempt for this key."""
        with self._sessions.begin() as db:
            inserted_id = db.scalar(
                pg_insert(CheckoutAttempt)
                .values(
                    idempotency_key=request.idempotency_key,
                    cart_id=request.cart_id,
                    customer_id=request.customer_id,
                    status=AttemptStatus.AUTHORIZING.value,
                    payment_reference=f"ns_{uuid.uuid4().hex}",
                    **{name: getattr(request.contact, name) for name in CONTACT_FIELDS},
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
                .returning(CheckoutAttempt.id)
            )
            if inserted_id is None:
                attempt = db.scalar(
                    select(CheckoutAttempt).where(CheckoutAttempt.idempotency_key == request.idempotency_key)
                )
                if attempt.cart_id != request.cart_id or attempt.customer_id != request.customer_id:
                    return CheckoutOutcome(
                        Outcome.CONFLICT,
                        failure_code="idempotency_conflict",
                        message="This checkout key was already used for a different cart.",
                    )
                if attempt.status in TERMINAL_ATTEMPT_STATUSES:
                    return self._outcome(attempt, replayed=True)
                return attempt.id  # unfinished: this request helps drive it

            attempt = db.get(CheckoutAttempt, inserted_id)
            try:
                self._quote(db, attempt)
            except CheckoutFailure as failure:
                self._set_failed(attempt, failure.code, failure.message)
                return CheckoutOutcome(Outcome.FAILED, failure_code=failure.code, message=failure.message)
            return attempt.id

    def _quote(self, db: Session, attempt: CheckoutAttempt) -> None:
        """Validate the cart and fix the attempt's monetary terms."""
        cart = db.get(Cart, attempt.cart_id)
        if cart is None or cart.customer_id != attempt.customer_id:
            raise CheckoutFailure("cart_not_found", "Your cart could not be found.")
        _check_cart_open(cart)
        if not cart.items:
            raise CheckoutFailure("empty_cart", "Your cart is empty.")
        for item in cart.items:
            _check_purchasable(item.product, item.quantity)

        level = None
        if attempt.customer_id is not None:
            level = db.get(Customer, attempt.customer_id).level
        lines = sorted(
            ({"product_id": i.product_id, "quantity": i.quantity, "unit_price": str(i.product.price)} for i in cart.items),
            key=lambda line: line["product_id"],
        )
        totals = pricing.calculate_totals(((Decimal(l["unit_price"]), l["quantity"]) for l in lines), level)
        attempt.customer_level = level
        attempt.quote_lines = lines
        attempt.subtotal = totals.subtotal
        attempt.shipping = totals.shipping
        attempt.tax = totals.tax
        attempt.total = totals.total

    # ----------------------------------------------------------------- the drive loop

    def _drive(self, attempt_id: int, *, card_number: Optional[str], abandon_unconfirmed: bool = False) -> CheckoutOutcome:
        """Advance the attempt one step at a time until it is terminal or cannot progress.

        Each processor operation is one bounded request. If its outcome is
        unknown (never sent, or sent without a usable answer), nothing is
        inferred and nothing is retried synchronously: the attempt stays as it
        is and the shopper sees PROCESSING. A same-key resubmission or the
        reconciler then re-drives it; processor operations are idempotent, so
        that is safe whether or not the earlier request took effect.
        """
        for _ in range(MAX_STEPS):
            attempt = self._load(attempt_id)
            if attempt.status in TERMINAL_ATTEMPT_STATUSES:
                return self._outcome(attempt)
            try:
                if attempt.status == AttemptStatus.AUTHORIZING:
                    progress = self._step_authorize(attempt, card_number, abandon_unconfirmed)
                elif attempt.status == AttemptStatus.AUTHORIZED:
                    progress = self._step_reserve(attempt.id)
                elif attempt.status == AttemptStatus.CAPTURING:
                    progress = self._step_capture(attempt)
                else:
                    progress = self._step_void(attempt)
            except PaymentOutcomeUnknown as exc:
                log.warning("checkout attempt %s: payment outcome unknown (%s)", attempt_id, exc)
                return self._processing()
            if progress == _STOP:
                return self._processing()
        return self._processing()

    # ----------------------------------------------------------------- AUTHORIZING

    def _step_authorize(self, attempt: CheckoutAttempt, card_number: Optional[str], abandon: bool):
        if card_number is not None:
            # Idempotent per reference: a retry returns the original authorization.
            txn = self._payments.authorize(attempt.payment_reference, attempt.total, card_number)
        else:
            txn = self._payments.get(attempt.payment_reference)
            if txn is None:
                if not abandon:
                    return _STOP  # nothing is known yet; wait for a same-key retry or the reconciler
                # Stop waiting. Voiding first makes a still-in-flight authorization impossible.
                self._transition(
                    attempt.id, AttemptStatus.AUTHORIZING, AttemptStatus.VOIDING,
                    failure_code="payment_unconfirmed", failure_message=FAILURES["payment_unconfirmed"],
                )
                return None

        if txn.status in (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED):
            # CAPTURED here means this worker is stale: another worker already
            # advanced the attempt and captured. The compare-and-set is then a
            # no-op and the loop re-reads the attempt's real state.
            self._transition(attempt.id, AttemptStatus.AUTHORIZING, AttemptStatus.AUTHORIZED, card_last4=txn.card_last4)
        elif txn.status == PaymentStatus.DECLINED:
            self._transition(
                attempt.id, AttemptStatus.AUTHORIZING, AttemptStatus.FAILED, card_last4=txn.card_last4,
                failure_code="payment_declined", failure_message=FAILURES["payment_declined"],
            )
        else:  # VOIDED
            # Only Northstar voids its references, and only after leaving AUTHORIZING;
            # the transition below is a no-op in that case and the loop re-reads.
            self._transition(
                attempt.id, AttemptStatus.AUTHORIZING, AttemptStatus.FAILED,
                failure_code="payment_cancelled", failure_message=FAILURES["payment_cancelled"],
            )
        return None

    # ----------------------------------------------------------------- AUTHORIZED -> reserve (phase 2)

    def _step_reserve(self, attempt_id: int):
        """Lock, recheck, and reserve inventory in one short transaction."""
        with self._sessions.begin() as db:
            attempt = self._lock_attempt(db, attempt_id)
            if attempt.status != AttemptStatus.AUTHORIZED:
                return None  # another worker moved it
            try:
                cart, products = self._lock_and_recheck(db, attempt)
            except CheckoutFailure as failure:
                attempt.status = AttemptStatus.VOIDING
                attempt.failure_code, attempt.failure_message = failure.code, failure.message
                return None

            quoted = {line["product_id"]: line for line in attempt.quote_lines}
            reserved = []
            for product in products:
                line = quoted[product.id]
                product.inventory_qty -= line["quantity"]
                reserved.append({
                    "product_id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "brand": product.brand.name,
                    "quantity": line["quantity"],
                    "unit_price": line["unit_price"],
                    "unit_cost": str(product.cost),
                })
            cart.status = CartStatus.CHECKING_OUT
            attempt.reserved_lines = reserved
            attempt.status = AttemptStatus.CAPTURING
        return None

    def _lock_and_recheck(self, db: Session, attempt: CheckoutAttempt) -> tuple[Cart, list[Product]]:
        cart = db.scalar(
            select(Cart).where(Cart.id == attempt.cart_id).with_for_update().execution_options(populate_existing=True)
        )
        if cart.status != CartStatus.ACTIVE:
            raise CheckoutFailure("cart_not_active", "This cart has already been checked out.")
        db.refresh(cart, ["items"])
        quoted = {line["product_id"]: line["quantity"] for line in attempt.quote_lines}
        if {i.product_id: i.quantity for i in cart.items} != quoted:
            raise CheckoutFailure("cart_changed", "Your cart changed during checkout. Please review it and try again.")
        products = self._lock_products(db, quoted)
        for product in products:
            _check_purchasable(product, quoted[product.id])
        return cart, products

    # ----------------------------------------------------------------- CAPTURING

    def _step_capture(self, attempt: CheckoutAttempt):
        try:
            txn = self._payments.capture(attempt.payment_reference)
        except PaymentRejected as rejected:
            # Definitive: the processor will not capture this authorization.
            log.warning("checkout attempt %s: capture refused (%s)", attempt.id, rejected.code)
            self._release_reservation(attempt.id)
            return None
        if txn.status != PaymentStatus.CAPTURED:
            raise PaymentProtocolError(f"capture of {txn.reference} returned {txn.status.value}")
        self._complete(attempt.id)
        return None

    def _complete(self, attempt_id: int) -> None:
        """Capture is confirmed: create the completed order from the reservation snapshot."""
        with self._sessions.begin() as db:
            attempt = self._lock_attempt(db, attempt_id)
            if attempt.status != AttemptStatus.CAPTURING:
                return
            cart = db.scalar(select(Cart).where(Cart.id == attempt.cart_id).with_for_update())
            order = Order(
                cart_id=cart.id,
                checkout_attempt_id=attempt.id,
                customer_id=attempt.customer_id,
                customer_level=attempt.customer_level,
                **{name: getattr(attempt, name) for name in CONTACT_FIELDS},
                subtotal=attempt.subtotal,
                shipping=attempt.shipping,
                tax=attempt.tax,
                total=attempt.total,
                payment_reference=attempt.payment_reference,
                card_last4=attempt.card_last4 or "",
                placed_at=self._now(),
            )
            for line in attempt.reserved_lines:
                unit_price = Decimal(line["unit_price"])
                order.lines.append(
                    OrderLine(
                        product_id=line["product_id"],
                        sku=line["sku"],
                        product_name=line["name"],
                        brand_name=line["brand"],
                        quantity=line["quantity"],
                        unit_price=unit_price,
                        unit_cost=Decimal(line["unit_cost"]),
                        line_total=pricing.line_total(unit_price, line["quantity"]),
                    )
                )
            db.add(order)
            cart.status = CartStatus.COMPLETED
            cart.closed_at = self._now()
            attempt.status = AttemptStatus.COMPLETED

    def _release_reservation(self, attempt_id: int) -> None:
        """Capture was refused: return reserved inventory, reopen the cart, then void."""
        with self._sessions.begin() as db:
            attempt = self._lock_attempt(db, attempt_id)
            if attempt.status != AttemptStatus.CAPTURING:
                return
            cart = db.scalar(select(Cart).where(Cart.id == attempt.cart_id).with_for_update())
            reserved = {line["product_id"]: line["quantity"] for line in attempt.reserved_lines}
            for product in self._lock_products(db, reserved):
                product.inventory_qty += reserved[product.id]
            cart.status = CartStatus.ACTIVE
            attempt.status = AttemptStatus.VOIDING
            attempt.failure_code = "payment_capture_refused"
            attempt.failure_message = FAILURES["payment_capture_refused"]

    # ----------------------------------------------------------------- VOIDING

    def _step_void(self, attempt: CheckoutAttempt):
        try:
            txn = self._payments.void(attempt.payment_reference)
        except PaymentRejected as rejected:
            # Void is only requested when no capture was requested or capture was refused.
            raise PaymentProtocolError(f"void of {attempt.payment_reference} refused: {rejected.code}") from rejected
        if txn.status not in (PaymentStatus.VOIDED, PaymentStatus.DECLINED):
            raise PaymentProtocolError(f"void of {txn.reference} returned {txn.status.value}")
        self._transition(attempt.id, AttemptStatus.VOIDING, AttemptStatus.FAILED)
        return None

    # ----------------------------------------------------------------- helpers

    def _load(self, attempt_id: int) -> CheckoutAttempt:
        with self._sessions() as db:
            return db.get(CheckoutAttempt, attempt_id)

    @staticmethod
    def _lock_attempt(db: Session, attempt_id: int) -> CheckoutAttempt:
        return db.get(CheckoutAttempt, attempt_id, with_for_update=True, populate_existing=True)

    @staticmethod
    def _lock_products(db: Session, product_ids) -> list[Product]:
        # Lock in id order (no deadlocks); populate_existing replaces any copies
        # already loaded in this session with the locked, current row values.
        return list(
            db.scalars(
                select(Product)
                .where(Product.id.in_(list(product_ids)))
                .order_by(Product.id)
                .with_for_update(of=Product)
                .execution_options(populate_existing=True)
            ).unique()
        )

    def _transition(self, attempt_id: int, expected: AttemptStatus, new: AttemptStatus, **values) -> bool:
        """Compare-and-set the attempt's status. Returns False if another worker moved it first."""
        with self._sessions.begin() as db:
            result = db.execute(
                update(CheckoutAttempt)
                .where(CheckoutAttempt.id == attempt_id, CheckoutAttempt.status == expected)
                .values(status=new, **values)
            )
            return result.rowcount == 1

    @staticmethod
    def _set_failed(attempt: CheckoutAttempt, code: str, message: str) -> None:
        attempt.status = AttemptStatus.FAILED
        attempt.failure_code = code
        attempt.failure_message = message

    def _outcome(self, attempt: CheckoutAttempt, replayed: bool = False) -> CheckoutOutcome:
        if attempt.status == AttemptStatus.COMPLETED:
            with self._sessions() as db:
                order_id = db.scalar(select(Order.id).where(Order.checkout_attempt_id == attempt.id))
            return CheckoutOutcome(Outcome.COMPLETED, order_id=order_id, replayed=replayed)
        if attempt.status == AttemptStatus.FAILED:
            return CheckoutOutcome(
                Outcome.FAILED, failure_code=attempt.failure_code, message=attempt.failure_message, replayed=replayed
            )
        return self._processing()

    @staticmethod
    def _processing() -> CheckoutOutcome:
        return CheckoutOutcome(Outcome.PROCESSING, message=PROCESSING_MESSAGE)


def _check_cart_open(cart: Cart) -> None:
    if cart.status == CartStatus.CHECKING_OUT:
        raise CheckoutFailure("cart_not_active", "A checkout for this cart is already being processed.")
    if cart.status != CartStatus.ACTIVE:
        raise CheckoutFailure("cart_not_active", "This cart has already been checked out.")


def _check_purchasable(product: Product, quantity: int) -> None:
    if not product.is_active:
        raise CheckoutFailure("product_unavailable", f"{product.name} is no longer available.")
    if product.inventory_qty < quantity:
        raise CheckoutFailure(
            "insufficient_inventory",
            f"Sorry, there is not enough stock of {product.name} to fill your order.",
        )
