"""Request plumbing shared by storefront and admin routes: database sessions,
CSRF protection, flash messages, authentication guards, and rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from northstar.models import AdminUser, Customer
from northstar.money import format_money
from northstar.security import new_token, tokens_match

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# --------------------------------------------------------------------------- database


def get_db(request: Request) -> Iterator[Session]:
    """A session per request. Handlers commit explicitly; anything uncommitted rolls back."""
    with request.app.state.session_factory() as session:
        yield session


# --------------------------------------------------------------------------- forms & CSRF


async def form_data(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: value for key, value in form.items() if isinstance(value, str)}


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = request.session["csrf_token"] = new_token()
    return token


def rotate_csrf_token(request: Request) -> None:
    request.session["csrf_token"] = new_token()


async def verify_csrf(request: Request) -> None:
    """Synchronizer-token CSRF check for every state-changing request."""
    if request.method not in UNSAFE_METHODS:
        return
    form = await request.form()
    submitted = form.get("csrf_token") or request.headers.get("x-csrf-token")
    if not tokens_match(submitted if isinstance(submitted, str) else None, request.session.get("csrf_token")):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token. Reload the page and try again.")


# --------------------------------------------------------------------------- flash messages


def flash(request: Request, message: str, category: str = "info") -> None:
    request.session.setdefault("flashes", []).append([category, message])


def pop_flashes(request: Request) -> list[list[str]]:
    return request.session.pop("flashes", [])


# --------------------------------------------------------------------------- identity


class LoginRequired(Exception):
    def __init__(self, next_path: str):
        self.next_path = next_path


class AdminLoginRequired(LoginRequired):
    pass


def current_customer(request: Request, db: Session = Depends(get_db)) -> Optional[Customer]:
    customer_id = request.session.get("customer_id")
    if customer_id is None:
        return None
    customer = db.get(Customer, customer_id)
    if customer is None:
        request.session.pop("customer_id", None)
    return customer


def require_customer(request: Request, customer: Optional[Customer] = Depends(current_customer)) -> Customer:
    if customer is None:
        raise LoginRequired(request.url.path)
    return customer


def current_admin(request: Request, db: Session = Depends(get_db)) -> Optional[AdminUser]:
    admin_id = request.session.get("admin_id")
    return db.get(AdminUser, admin_id) if admin_id is not None else None


def require_admin(request: Request, admin: Optional[AdminUser] = Depends(current_admin)) -> AdminUser:
    if admin is None:
        raise AdminLoginRequired(request.url.path if request.method == "GET" else "/admin")
    return admin


def safe_next(target: Optional[str], default: str) -> str:
    """Only allow same-site relative redirects."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def login_url(base: str, next_path: str) -> str:
    return f"{base}?next={quote(next_path)}"


# --------------------------------------------------------------------------- rendering


def render(request: Request, template: str, status_code: int = 200, **context: Any):
    return templates.TemplateResponse(request, template, context, status_code=status_code)


templates.env.globals.update(money=format_money, csrf_token=csrf_token, pop_flashes=pop_flashes)
