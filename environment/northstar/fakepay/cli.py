"""FakePay commands.

    python -m fakepay.cli init-db   # create FakePay's tables in its own database (idempotent)
    python -m fakepay.cli serve     # init-db, then serve the API on port 8100
"""

from __future__ import annotations

import argparse

import uvicorn
from sqlalchemy import create_engine

from fakepay.config import Settings
from fakepay.models import Base


def init_db(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fakepay")
    parser.add_argument("command", choices=["init-db", "serve"])
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    init_db(settings.database_url)
    if args.command == "serve":
        uvicorn.run("fakepay.app:create_app", factory=True, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
