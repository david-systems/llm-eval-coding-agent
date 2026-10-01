"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+psycopg://northstar:northstar@localhost:5433/northstar"


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    secret_key: str = "dev-insecure-secret-change-me"
    session_cookie_secure: bool = False

    # External payment processor (FakePay). Northstar knows only its API.
    fakepay_url: str = "http://localhost:8100"
    fakepay_api_key: str = "fakepay-dev-key"
    # Bounds for one interactive processor request: connect, and read (overall response wait).
    fakepay_timeout_seconds: float = 3.0
    fakepay_connect_timeout_seconds: float = 1.0

    # Reconciliation scheduling policy (not evidence of any payment outcome).
    reconcile_interval_seconds: int = 15
    reconcile_min_age_seconds: int = 30
    checkout_abandon_after_seconds: int = 600

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        return cls(
            database_url=env("DATABASE_URL", DEFAULT_DATABASE_URL),
            secret_key=env("SECRET_KEY", cls.secret_key),
            session_cookie_secure=env("SESSION_COOKIE_SECURE", "false").lower() == "true",
            fakepay_url=env("FAKEPAY_URL", cls.fakepay_url),
            fakepay_api_key=env("FAKEPAY_API_KEY", cls.fakepay_api_key),
            fakepay_timeout_seconds=float(env("FAKEPAY_TIMEOUT_SECONDS", cls.fakepay_timeout_seconds)),
            fakepay_connect_timeout_seconds=float(
                env("FAKEPAY_CONNECT_TIMEOUT_SECONDS", cls.fakepay_connect_timeout_seconds)
            ),
            reconcile_interval_seconds=int(env("RECONCILE_INTERVAL_SECONDS", cls.reconcile_interval_seconds)),
            reconcile_min_age_seconds=int(env("RECONCILE_MIN_AGE_SECONDS", cls.reconcile_min_age_seconds)),
            checkout_abandon_after_seconds=int(env("CHECKOUT_ABANDON_AFTER_SECONDS", cls.checkout_abandon_after_seconds)),
        )
