"""Test harness.

Northstar: each test session drops and recreates the Northstar test database
and builds it with the real Alembic migrations; each test starts from
truncated tables. Truncation (rather than a rolled-back outer transaction) is
used because checkout and concurrency tests need real commits visible across
connections.

FakePay: the suite runs its own private FakePay server (the real FakePay app,
in a background thread, over real HTTP) backed by FakePay's own test
database. Northstar code under test reaches it only through ``FakePayClient``;
a fault-injecting transport sits under that client. Test assertions about
payment state also go through FakePay's public API. Only this harness touches
FakePay's database, to reset it between tests.
"""

from __future__ import annotations

import os
import re
import socket
import threading
from datetime import timedelta
from pathlib import Path

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from fakepay.app import create_app as create_fakepay_app
from fakepay.cli import init_db as init_fakepay_db
from fakepay.config import Settings as FakePaySettings
from northstar.config import Settings
from northstar.db import make_engine, make_session_factory
from northstar.models import Base
from northstar.services.checkout import CheckoutService
from northstar.services.payments import FakePayClient
from northstar.services.reconciliation import ReconciliationPolicy, Reconciler
from northstar.web.app import create_app
from tests.factories import Factory
from tests.faults import FaultInjector

ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://northstar:northstar@localhost:5433/northstar_test"
)
TEST_FAKEPAY_DATABASE_URL = os.environ.get(
    "TEST_FAKEPAY_DATABASE_URL", "postgresql+psycopg://fakepay:fakepay@localhost:5434/fakepay_test"
)
FAKEPAY_API_KEY = "fakepay-test-key"
TABLES = ", ".join(table.name for table in Base.metadata.sorted_tables)

# Reconciliation policy for tests: examine every unfinished attempt, never abandon
# unless a test explicitly asks for it.
NEVER = timedelta(days=36500)


def _recreate_database(url: str) -> None:
    parsed = make_url(url)
    name = parsed.database
    if not name or not re.fullmatch(r"[a-z0-9_]+", name) or "test" not in name:
        raise RuntimeError(f"refusing to recreate non-test database {name!r}")
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()


def migrate(url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")


# --------------------------------------------------------------------------- Northstar database


@pytest.fixture(scope="session")
def engine():
    _recreate_database(TEST_DATABASE_URL)
    migrate(TEST_DATABASE_URL)
    engine = make_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture(autouse=True)
def clean_database(engine, fakepay_engine):
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        conn.execute(text("INSERT INTO site_settings (id, announcement_text, announcement_active) VALUES (1, '', false)"))
    with fakepay_engine.begin() as conn:
        conn.execute(text("TRUNCATE transaction_events, transactions RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def factory(session_factory) -> Factory:
    return Factory(session_factory)


# --------------------------------------------------------------------------- FakePay (separate service)


@pytest.fixture(scope="session")
def fakepay_engine():
    _recreate_database(TEST_FAKEPAY_DATABASE_URL)
    init_fakepay_db(TEST_FAKEPAY_DATABASE_URL)
    engine = create_engine(TEST_FAKEPAY_DATABASE_URL, pool_size=20)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def fakepay_url(fakepay_engine):
    """Run the real FakePay app over HTTP on an ephemeral local port."""
    app = create_fakepay_app(
        FakePaySettings(database_url=TEST_FAKEPAY_DATABASE_URL, api_key=FAKEPAY_API_KEY),
        session_factory=sessionmaker(fakepay_engine, expire_on_commit=False),
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", limit_concurrency=200))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("FakePay test server failed to start")
        threading.Event().wait(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def faults() -> FaultInjector:
    injector = FaultInjector()
    yield injector
    injector.close()


@pytest.fixture
def payments(fakepay_url, faults) -> FakePayClient:
    """The client Northstar code uses, with the fault injector under it."""
    client = FakePayClient(fakepay_url, FAKEPAY_API_KEY, transport=faults)
    yield client
    client.close()


@pytest.fixture
def processor(fakepay_url) -> FakePayClient:
    """An independent, fault-free client for observing FakePay's authoritative state."""
    client = FakePayClient(fakepay_url, FAKEPAY_API_KEY)
    yield client
    client.close()


# --------------------------------------------------------------------------- Northstar services


@pytest.fixture
def checkout_service(session_factory, payments) -> CheckoutService:
    return CheckoutService(session_factory, payments)


@pytest.fixture
def reconciler(session_factory, checkout_service) -> Reconciler:
    return Reconciler(session_factory, checkout_service, ReconciliationPolicy(min_age=timedelta(0), abandon_after=NEVER))


@pytest.fixture
def abandoning_reconciler(session_factory, checkout_service) -> Reconciler:
    """A reconciler whose policy is to stop waiting for unconfirmed authorizations now."""
    return Reconciler(
        session_factory, checkout_service, ReconciliationPolicy(min_age=timedelta(0), abandon_after=timedelta(0))
    )


@pytest.fixture
def app(session_factory, payments):
    settings = Settings(database_url=TEST_DATABASE_URL, secret_key="test-secret")
    return create_app(settings, session_factory=session_factory, payments=payments)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def other_client(app):
    """A second, independent browser."""
    with TestClient(app) as test_client:
        yield test_client
