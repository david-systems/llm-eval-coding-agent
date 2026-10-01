from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+psycopg://fakepay:fakepay@localhost:5434/fakepay"


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    api_key: str = "fakepay-dev-key"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("FAKEPAY_DATABASE_URL", DEFAULT_DATABASE_URL),
            api_key=os.environ.get("FAKEPAY_API_KEY", cls.api_key),
        )
