"""Customer-facing storefront routes."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from northstar.models import Cart, CartStatus, CheckoutAttempt, Customer
from northstar.services import NotFound, ValidationError, carts, catalog, content, orders
from northstar.services.checkout import CheckoutRequest, Outcome, parse_checkout_form
from northstar.services.customers import authenticate_customer
from northstar.web.deps import (
    current_customer,
    flash,
    form_data,
    get_db,
    render,
    require_customer,
    rotate_csrf_token,
    safe_next,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])

GUEST_CART_KEY = "guest_cart_token"
GUEST_ORDERS_KEY = "guest_order_ids"
PENDING_CHECKOUTS_KEY = "pending_checkout_keys"


CHECKING_OUT_MESSAGE = "Your order is being processed, so your cart can't be changed until your payment is confirmed."


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# --------------------------------------------------------------------------- helpers


def resolve_cart(request: Request, db: Session, customer: Optional[Customer], *, create: bool = False) -> Optional[Cart]:
    """The shopper's active cart: persisted per customer, or found via the guest cookie token."""
    if customer is not None:
        return carts.get_or_create_customer_cart(db, customer.id) if create else carts.get_customer_cart(db, customer.id)
    cart = carts.get_guest_cart(db, request.session.get(GUEST_CART_KEY))
    if cart is None:
        request.session.pop(GUEST_CART_KEY, None)
        if create:
            cart = carts.create_guest_cart(db)
            request.session[GUEST_CART_KEY] = cart.guest_token
    return cart


def merge_guest_cart_into(request: Request, db: Session, customer: Customer) -> bool:
    """Merge the session's guest cart into the customer's cart (login rule).

    If either cart is reserved by a checkout whose payment is still being
    confirmed, the merge is deferred: the guest token stays in the session and
    the merge is retried on the next cart interaction. Caller commits.
    """
    token = request.session.get(GUEST_CART_KEY)
    if not token:
        return False
    try:
        merged = carts.merge_guest_cart(db, token, customer.id)
    except carts.CartCheckingOutError:
        db.rollback()
        return False
    request.session.pop(GUEST_CART_KEY, None)
    return merged is not None


def page(request: Request, db: Session, customer: Optional[Customer], template: str, status_code: int = 200, **ctx):
    """Render a storefront page with the shared header context."""
    cart = resolve_cart(request, db, customer)
    return render(
        request,
        template,
        status_code=status_code,
        customer=customer,
        cart_count=sum(i.quantity for i in cart.items) if cart else 0,
        nav_categories=catalog.top_level_categories(db),
        **ctx,
    )


# --------------------------------------------------------------------------- browsing


@router.get("/")
def home(request: Request, db: Session = Depends(get_db), customer=Depends(current_customer)):
    return page(
        request,
        db,
        customer,
        "store/home.html",
        announcement=content.active_announcement(db),
        featured=catalog.featured_products(db),
        new_arrivals=catalog.new_products(db),
    )


@router.get("/products")
def product_list(
    request: Request,
    q: Optional[str] = None,
    brand: Optional[str] = None,
    db: Session = Depends(get_db),
    customer=Depends(current_customer),
):
    products = catalog.storefront_products(db, brand_slug=brand, search=q)
    return page(
        request, db, customer, "store/products.html",
        heading="All products", products=products, brands=catalog.list_brands(db), q=q or "", brand=brand, category=None,
    )


@router.get("/categories/{slug}")
def category_page(
    slug: str,
    request: Request,
    brand: Optional[str] = None,
    db: Session = Depends(get_db),
    customer=Depends(current_customer),
):
    category = catalog.get_category_by_slug(db, slug)
    products = catalog.storefront_products(db, category=category, brand_slug=brand)
    return page(
        request, db, customer, "store/products.html",
        heading=category.name, products=products, brands=catalog.list_brands(db), q="", brand=brand, category=category,
    )


@router.get("/products/{sku}")
def product_detail(sku: str, request: Request, db: Session = Depends(get_db), customer=Depends(current_customer)):
    product = catalog.get_active_product_by_sku(db, sku)
    return page(request, db, customer, "store/product.html", product=product)


# --------------------------------------------------------------------------- cart


@router.get("/cart")
def view_cart(request: Request, db: Session = Depends(get_db), customer=Depends(current_customer)):
    if customer is not None and merge_guest_cart_into(request, db, customer):
        db.commit()
    cart = resolve_cart(request, db, customer)
    view = carts.view_cart(cart, customer.level if customer else None)
    return page(request, db, customer, "store/cart.html", cart=view, pending_key=_pending_key(request))


@router.post("/cart/add")
def cart_add(
    request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db), customer=Depends(current_customer)
):
    try:
        product = catalog.get_active_product_by_sku(db, form.get("sku", ""))
        quantity = carts.parse_quantity(form.get("quantity", "1"), allow_zero=False)
        if customer is not None:
            merge_guest_cart_into(request, db, customer)
        cart = resolve_cart(request, db, customer, create=True)
        carts.add_item(db, cart.id, product.id, quantity)
        db.commit()
    except carts.CartCheckingOutError:
        db.rollback()
        flash(request, CHECKING_OUT_MESSAGE, "error")
        return redirect("/cart")
    except NotFound:
        flash(request, "That product is not available.", "error")
        return redirect("/cart")
    except ValidationError as exc:
        db.rollback()
        flash(request, " ".join(exc.errors.values()), "error")
        return redirect(f"/products/{product.sku}")
    flash(request, f"Added {quantity} × {product.name} to your cart.", "success")
    return redirect("/cart")


@router.post("/cart/update")
def cart_update(
    request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db), customer=Depends(current_customer)
):
    cart = resolve_cart(request, db, customer)
    try:
        if cart is None:
            raise NotFound("cart")
        product_id = int(form.get("product_id", "0"))
        quantity = 0 if form.get("action") == "remove" else carts.parse_quantity(form.get("quantity"), allow_zero=True)
        carts.set_quantity(db, cart.id, product_id, quantity)
        db.commit()
        flash(request, "Item removed." if quantity == 0 else "Cart updated.", "success")
    except (NotFound, ValueError):
        db.rollback()
        flash(request, "That item is no longer in your cart.", "error")
    except ValidationError as exc:
        db.rollback()
        flash(request, " ".join(exc.errors.values()), "error")
    except carts.CartCheckingOutError:
        db.rollback()
        flash(request, CHECKING_OUT_MESSAGE, "error")
    except carts.CartClosedError:
        db.rollback()
        flash(request, "That cart has already been checked out.", "error")
    return redirect("/cart")


# --------------------------------------------------------------------------- checkout


def _checkout_page(request, db, customer, cart, *, key, values, errors=None, message=None, status_code=200):
    view = carts.view_cart(cart, customer.level if customer else None)
    return page(
        request, db, customer, "store/checkout.html", status_code=status_code,
        cart=view, idempotency_key=key, values=values, errors=errors or {}, message=message,
    )


def _prefill(customer: Optional[Customer]) -> dict[str, str]:
    if customer is None:
        return {}
    fields = ("email", "first_name", "last_name", "address_line1", "address_line2", "city", "state", "postal_code")
    return {name: getattr(customer, name) for name in fields}


@router.get("/checkout")
def checkout_form(request: Request, db: Session = Depends(get_db), customer=Depends(current_customer)):
    cart = resolve_cart(request, db, customer)
    if cart is None or not cart.items:
        flash(request, "Your cart is empty.", "info")
        return redirect("/cart")
    if cart.status == CartStatus.CHECKING_OUT:
        pending = _pending_key(request)
        if pending:
            return redirect(f"/checkout/status/{pending}")
        flash(request, CHECKING_OUT_MESSAGE, "info")
        return redirect("/cart")
    # A fresh idempotency key per rendered form: resubmitting this form is a
    # retry of the same attempt; a new visit is a new attempt.
    return _checkout_page(request, db, customer, cart, key=str(uuid.uuid4()), values=_prefill(customer))


@router.post("/checkout")
def checkout_submit(
    request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db), customer=Depends(current_customer)
):
    key = form.get("idempotency_key", "").strip()
    if not key:
        flash(request, "Your checkout session expired. Please try again.", "error")
        return redirect("/cart")
    values = {k: v for k, v in form.items() if k not in ("card_number", "csrf_token")}
    cart = resolve_cart(request, db, customer)

    try:
        contact, card_number = parse_checkout_form(form)
    except ValidationError as exc:
        if cart is None or not cart.items:
            return redirect("/cart")
        return _checkout_page(request, db, customer, cart, key=key, values=values, errors=exc.errors, status_code=422)

    # A resubmitted form (double click, refresh) may find its cart already
    # closed by the first submission; it is then a retry of that attempt.
    cart_id = cart.id if cart is not None else _attempt_cart_id(db, key, customer)
    if cart_id is None:
        flash(request, "Your cart is empty.", "info")
        return redirect("/cart")
    db.rollback()  # end this request's read transaction; checkout manages its own

    outcome = request.app.state.checkout_service.checkout(
        CheckoutRequest(
            idempotency_key=key,
            cart_id=cart_id,
            customer_id=customer.id if customer else None,
            contact=contact,
            card_number=card_number,
        )
    )

    if outcome.status == Outcome.COMPLETED:
        return _completed(request, customer, key, outcome.order_id)
    if outcome.status == Outcome.PROCESSING:
        _remember_pending(request, key)
        return redirect(f"/checkout/status/{key}")

    cart = resolve_cart(request, db, customer)
    if cart is None or not cart.items:
        flash(request, outcome.message or "We could not complete your order.", "error")
        return redirect("/cart")
    # A failure is final for its key, so the next submit is a new attempt.
    next_key = str(uuid.uuid4())
    return _checkout_page(
        request, db, customer, cart, key=next_key, values=values, message=outcome.message, status_code=409
    )


def _attempt_cart_id(db: Session, key: str, customer: Optional[Customer]) -> Optional[int]:
    customer_id = customer.id if customer else None
    return db.scalar(
        select(CheckoutAttempt.cart_id).where(
            CheckoutAttempt.idempotency_key == key,
            CheckoutAttempt.customer_id.is_(None) if customer_id is None else CheckoutAttempt.customer_id == customer_id,
        )
    )


def _completed(request: Request, customer: Optional[Customer], key: str, order_id: int) -> RedirectResponse:
    _forget_pending(request, key)
    if customer is None:
        request.session.pop(GUEST_CART_KEY, None)
        owned = request.session.get(GUEST_ORDERS_KEY, [])
        if order_id not in owned:
            request.session[GUEST_ORDERS_KEY] = (owned + [order_id])[-20:]
    return redirect(f"/orders/{order_id}/confirmation")


def _remember_pending(request: Request, key: str) -> None:
    pending = request.session.get(PENDING_CHECKOUTS_KEY, [])
    if key not in pending:
        request.session[PENDING_CHECKOUTS_KEY] = (pending + [key])[-5:]


def _forget_pending(request: Request, key: str) -> None:
    pending = [k for k in request.session.get(PENDING_CHECKOUTS_KEY, []) if k != key]
    if pending:
        request.session[PENDING_CHECKOUTS_KEY] = pending
    else:
        request.session.pop(PENDING_CHECKOUTS_KEY, None)


def _pending_key(request: Request) -> Optional[str]:
    pending = request.session.get(PENDING_CHECKOUTS_KEY, [])
    return pending[-1] if pending else None


@router.get("/checkout/status/{key}")
def checkout_status(key: str, request: Request, db: Session = Depends(get_db), customer=Depends(current_customer)):
    """Where a shopper waits while the payment outcome is being established.

    Read-only: it displays Northstar's recorded state for the attempt and never
    contacts the processor or advances checkout. The reconciler (or a same-key
    checkout resubmission) resolves unfinished attempts; reloading this page
    shows the result once it is recorded.
    """
    attempt = db.scalar(select(CheckoutAttempt).where(CheckoutAttempt.idempotency_key == key))
    owns = attempt is not None and (
        key in request.session.get(PENDING_CHECKOUTS_KEY, [])
        or (customer is not None and attempt.customer_id == customer.id)
    )
    if not owns:
        raise NotFound(key)
    db.rollback()
    outcome = request.app.state.checkout_service.current_outcome(key)
    if outcome.status == Outcome.COMPLETED:
        return _completed(request, customer, key, outcome.order_id)
    if outcome.status == Outcome.FAILED:
        _forget_pending(request, key)
        flash(request, outcome.message or "We could not complete your order.", "error")
        return redirect("/cart")
    return page(request, db, customer, "store/processing.html", message=outcome.message)


@router.get("/orders/{order_id}/confirmation")
def order_confirmation(order_id: int, request: Request, db: Session = Depends(get_db), customer=Depends(current_customer)):
    order = orders.get_order(db, order_id)
    owns = order is not None and (
        (customer is not None and order.customer_id == customer.id)
        or (order.customer_id is None and order_id in request.session.get(GUEST_ORDERS_KEY, []))
    )
    if not owns:
        raise NotFound(order_id)
    return page(request, db, customer, "store/confirmation.html", order=order)


# --------------------------------------------------------------------------- accounts


@router.get("/login")
def login_form(request: Request, next: Optional[str] = None, db: Session = Depends(get_db), customer=Depends(current_customer)):
    return page(request, db, customer, "store/login.html", next=safe_next(next, "/"), error=None, email="")


@router.post("/login")
def login_submit(request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db)):
    next_path = safe_next(form.get("next"), "/")
    customer = authenticate_customer(db, form.get("email", ""), form.get("password", ""))
    if customer is None:
        return page(
            request, db, None, "store/login.html", status_code=401,
            next=next_path, error="Incorrect email or password.", email=form.get("email", ""),
        )
    merged = merge_guest_cart_into(request, db, customer)
    db.commit()
    request.session["customer_id"] = customer.id
    rotate_csrf_token(request)
    flash(request, f"Welcome back, {customer.first_name}." + (" Your cart items were saved to your account." if merged else ""), "success")
    return redirect(next_path)


@router.post("/logout")
def logout(request: Request):
    request.session.pop("customer_id", None)
    request.session.pop(GUEST_CART_KEY, None)
    request.session.pop(GUEST_ORDERS_KEY, None)
    rotate_csrf_token(request)
    flash(request, "You have been signed out.", "info")
    return redirect("/")


@router.get("/account/orders")
def order_history(request: Request, db: Session = Depends(get_db), customer: Customer = Depends(require_customer)):
    return page(request, db, customer, "store/orders.html", orders=orders.customer_orders(db, customer.id))


@router.get("/account/orders/{order_id}")
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db), customer: Customer = Depends(require_customer)):
    order = orders.get_order(db, order_id)
    if order is None or order.customer_id != customer.id:
        raise NotFound(order_id)
    return page(request, db, customer, "store/order.html", order=order)
