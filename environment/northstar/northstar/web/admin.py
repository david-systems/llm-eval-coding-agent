"""Administration routes. Everything except login requires an authenticated administrator."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from northstar.models import TERMINAL_ATTEMPT_STATUSES, CheckoutAttempt, Customer, CustomerLevel, Order, Product
from northstar.services import NotFound, ValidationError, catalog, content, customers, orders
from northstar.web.deps import (
    current_admin,
    flash,
    form_data,
    get_db,
    render,
    require_admin,
    rotate_csrf_token,
    safe_next,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])
# Every /admin route except login/logout is behind administrator authentication.
secured = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def admin_page(request: Request, template: str, status_code: int = 200, **ctx):
    return render(request, template, status_code=status_code, admin_nav=True, **ctx)


# --------------------------------------------------------------------------- login


@router.get("/admin/login")
def login_form(request: Request, next: Optional[str] = None, admin=Depends(current_admin)):
    if admin is not None:
        return redirect(safe_next(next, "/admin"))
    return render(request, "admin/login.html", next=safe_next(next, "/admin"), error=None, username="")


@router.post("/admin/login")
def login_submit(request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db)):
    next_path = safe_next(form.get("next"), "/admin")
    admin = customers.authenticate_admin(db, form.get("username", ""), form.get("password", ""))
    if admin is None:
        return render(
            request, "admin/login.html", status_code=401,
            next=next_path, error="Incorrect username or password.", username=form.get("username", ""),
        )
    request.session["admin_id"] = admin.id
    rotate_csrf_token(request)
    return redirect(next_path if next_path.startswith("/admin") else "/admin")


@router.post("/admin/logout")
def logout(request: Request):
    request.session.pop("admin_id", None)
    rotate_csrf_token(request)
    return redirect("/admin/login")


# --------------------------------------------------------------------------- dashboard


@secured.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    return admin_page(
        request,
        "admin/dashboard.html",
        product_count=db.scalar(select(func.count()).select_from(Product)),
        customer_count=db.scalar(select(func.count()).select_from(Customer)),
        order_count=db.scalar(select(func.count()).select_from(Order)),
        revenue=db.scalar(select(func.coalesce(func.sum(Order.total), 0))),
        below_map=catalog.below_map_products(db),
        low_stock=catalog.low_stock_products(db),
        unresolved=db.scalars(
            select(CheckoutAttempt)
            .where(CheckoutAttempt.status.not_in(TERMINAL_ATTEMPT_STATUSES))
            .order_by(CheckoutAttempt.created_at)
        ).all(),
    )


# --------------------------------------------------------------------------- products


def _product_form_page(request, db, *, product=None, values, errors=None, status_code=200):
    return admin_page(
        request,
        "admin/product_form.html",
        status_code=status_code,
        product=product,
        values=values,
        errors=errors or {},
        brands=catalog.list_brands(db),
        categories=catalog.category_options(db),
    )


def _product_values(product: Product) -> dict[str, str]:
    return {
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "brand_id": str(product.brand_id),
        "category_id": str(product.category_id),
        "msrp": f"{product.msrp:.2f}",
        "map_price": f"{product.map_price:.2f}" if product.map_price is not None else "",
        "map_enforced": "on" if product.map_enforced else "",
        "price": f"{product.price:.2f}",
        "cost": f"{product.cost:.2f}",
        "inventory_qty": str(product.inventory_qty),
        "is_active": "on" if product.is_active else "",
        "is_featured": "on" if product.is_featured else "",
        "is_new": "on" if product.is_new else "",
        "version": str(product.version),
    }


def _map_warning(request: Request, product: Product) -> None:
    if product.is_below_map:
        flash(
            request,
            f"MAP warning: {product.sku} is priced at ${product.price:,.2f}, below its enforced "
            f"MAP of ${product.map_price:,.2f}.",
            "warning",
        )


@secured.get("/products")
def product_list(request: Request, q: Optional[str] = None, below_map: bool = False, db: Session = Depends(get_db)):
    return admin_page(
        request, "admin/products.html",
        products=catalog.admin_product_list(db, search=q, only_below_map=below_map), q=q or "", below_map=below_map,
    )


@secured.get("/products/new")
def product_new(request: Request, db: Session = Depends(get_db)):
    return _product_form_page(request, db, values={"is_active": "on", "inventory_qty": "0"})


@secured.post("/products/new")
def product_create(request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db)):
    try:
        product = catalog.create_product(db, catalog.parse_product_form(form))
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _product_form_page(request, db, values=form, errors=exc.errors, status_code=422)
    flash(request, f"Created {product.sku}.", "success")
    _map_warning(request, product)
    return redirect(f"/admin/products/{product.id}")


@secured.get("/products/{product_id}")
def product_edit(product_id: int, request: Request, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound(product_id)
    return _product_form_page(request, db, product=product, values=_product_values(product))


@secured.post("/products/{product_id}")
def product_update(product_id: int, request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound(product_id)
    try:
        data = catalog.parse_product_form(form, sku_required=False)
        product = catalog.update_product(db, product_id, data, expected_version=int(form.get("version", "0")))
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _product_form_page(
            request, db, product=product, values={**form, "sku": product.sku}, errors=exc.errors, status_code=422
        )
    except (catalog.StaleProductError, ValueError):
        db.rollback()
        db.refresh(product)
        flash(request, "This product changed since you opened it (for example, a sale updated its inventory). "
                       "Review the current values and apply your changes again.", "error")
        return _product_form_page(request, db, product=product, values=_product_values(product), status_code=409)
    flash(request, f"Saved {product.sku}.", "success")
    _map_warning(request, product)
    return redirect(f"/admin/products/{product.id}")


@secured.post("/products/{product_id}/flag")
def product_flag(product_id: int, request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db)):
    try:
        product = catalog.set_product_flag(db, product_id, form.get("flag", ""), form.get("value") == "true")
        db.commit()
        flash(request, f"Updated {product.sku}.", "success")
    except ValidationError as exc:
        db.rollback()
        flash(request, " ".join(exc.errors.values()), "error")
    return redirect(safe_next(form.get("next"), "/admin/products"))


# --------------------------------------------------------------------------- homepage content


@secured.get("/homepage")
def homepage_content(request: Request, db: Session = Depends(get_db)):
    settings = content.get_site_settings(db)
    return admin_page(
        request, "admin/homepage.html",
        values={"announcement_text": settings.announcement_text, "announcement_active": settings.announcement_active},
        errors={},
        featured=catalog.featured_products(db, limit=100),
        new_arrivals=catalog.new_products(db, limit=100),
        inactive_flagged=[p for p in catalog.admin_product_list(db) if not p.is_active and (p.is_featured or p.is_new)],
    )


@secured.post("/homepage")
def homepage_update(request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db)):
    active = form.get("announcement_active") == "on"
    try:
        content.update_announcement(db, form.get("announcement_text", ""), active)
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return admin_page(
            request, "admin/homepage.html", status_code=422,
            values={"announcement_text": form.get("announcement_text", ""), "announcement_active": active},
            errors=exc.errors,
            featured=catalog.featured_products(db, limit=100),
            new_arrivals=catalog.new_products(db, limit=100),
            inactive_flagged=[],
        )
    flash(request, "Homepage announcement saved.", "success")
    return redirect("/admin/homepage")


# --------------------------------------------------------------------------- customers


def _customer_form_page(request, *, customer=None, values, errors=None, status_code=200, recent_orders=()):
    return admin_page(
        request, "admin/customer_form.html", status_code=status_code,
        customer=customer, values=values, errors=errors or {}, levels=list(CustomerLevel), recent_orders=recent_orders,
    )


@secured.get("/customers")
def customer_list(request: Request, q: Optional[str] = None, db: Session = Depends(get_db)):
    return admin_page(request, "admin/customers.html", customers=customers.list_customers(db, q), q=q or "")


@secured.get("/customers/new")
def customer_new(request: Request):
    return _customer_form_page(request, values={"level": CustomerLevel.RETAIL.value})


@secured.post("/customers/new")
def customer_create(request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db)):
    try:
        customer = customers.create_customer(db, customers.parse_customer_form(form, password_required=True))
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _customer_form_page(request, values=form, errors=exc.errors, status_code=422)
    flash(request, f"Created customer {customer.email} ({customer.level.label}).", "success")
    return redirect(f"/admin/customers/{customer.id}")


@secured.get("/customers/{customer_id}")
def customer_edit(customer_id: int, request: Request, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFound(customer_id)
    values = {
        name: getattr(customer, name)
        for name in ("email", "first_name", "last_name", *customers.ADDRESS_FIELDS)
    }
    values["level"] = customer.level.value
    return _customer_form_page(
        request, customer=customer, values=values, recent_orders=orders.customer_orders(db, customer.id)[:10]
    )


@secured.post("/customers/{customer_id}")
def customer_update(customer_id: int, request: Request, form: dict = Depends(form_data), db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFound(customer_id)
    try:
        customers.update_customer(db, customer_id, customers.parse_customer_form(form, password_required=False))
        db.commit()
    except ValidationError as exc:
        db.rollback()
        return _customer_form_page(request, customer=customer, values=form, errors=exc.errors, status_code=422)
    flash(request, f"Saved {customer.email}. Level: {customer.level.label}.", "success")
    return redirect(f"/admin/customers/{customer_id}")


# --------------------------------------------------------------------------- orders


@secured.get("/orders")
def order_list(request: Request, q: Optional[str] = None, db: Session = Depends(get_db)):
    return admin_page(request, "admin/orders.html", orders=orders.admin_orders(db, q), q=q or "")


@secured.get("/orders/{order_id}")
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = orders.get_order(db, order_id)
    if order is None:
        raise NotFound(order_id)
    return admin_page(request, "admin/order.html", order=order)


router.include_router(secured)
