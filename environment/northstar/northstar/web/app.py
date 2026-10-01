"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from northstar.config import Settings
from northstar.db import make_engine, make_session_factory
from northstar.services import NotFound
from northstar.services.checkout import CheckoutService
from northstar.services.payments import FakePayClient
from northstar.web import admin, storefront
from northstar.web.deps import AdminLoginRequired, LoginRequired, login_url, render

STATIC_DIR = Path(__file__).parent / "static"


def make_payments_client(settings: Settings) -> FakePayClient:
    return FakePayClient(
        settings.fakepay_url,
        settings.fakepay_api_key,
        timeout_seconds=settings.fakepay_timeout_seconds,
        connect_timeout_seconds=settings.fakepay_connect_timeout_seconds,
    )


def create_app(
    settings: Optional[Settings] = None,
    *,
    session_factory: Optional[sessionmaker[Session]] = None,
    payments: Optional[FakePayClient] = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if session_factory is None:
        session_factory = make_session_factory(make_engine(settings.database_url))
    payments = payments or make_payments_client(settings)

    app = FastAPI(title="Northstar Outdoor Living", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.checkout_service = CheckoutService(session_factory, payments)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="northstar_session",
        same_site="lax",
        https_only=settings.session_cookie_secure,
        max_age=14 * 24 * 3600,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(storefront.router)
    app.include_router(admin.router)

    @app.exception_handler(AdminLoginRequired)
    async def admin_login_required(request: Request, exc: AdminLoginRequired):
        return RedirectResponse(login_url("/admin/login", exc.next_path), status_code=303)

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired):
        return RedirectResponse(login_url("/login", exc.next_path), status_code=303)

    @app.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound):
        return render(request, "error.html", status_code=404, title="Not found", message="We couldn't find that page.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        title = "Not found" if exc.status_code == 404 else "Something went wrong"
        message = exc.detail if exc.status_code != 404 else "We couldn't find that page."
        return render(request, "error.html", status_code=exc.status_code, title=title, message=message)

    return app
