"""Operational commands.

    python -m northstar.cli migrate   # apply Alembic migrations
    python -m northstar.cli seed      # load deterministic seed data into an empty database
    python -m northstar.cli init      # migrate, then seed if the catalog is empty (used by the container)
    python -m northstar.cli reset     # DESTRUCTIVE: drop everything, migrate, and seed from scratch
    python -m northstar.cli reconcile [--loop]
                                      # resolve unfinished checkouts against the payment processor
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from northstar.config import Settings
from northstar.db import make_engine, make_session_factory
from northstar.seed import is_seeded, seed
from northstar.services.checkout import CheckoutService
from northstar.services.reconciliation import ReconciliationPolicy, Reconciler
from northstar.web.app import make_payments_client

ROOT = Path(__file__).resolve().parent.parent


def migrate(database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def load_seed(database_url: str, *, only_if_empty: bool) -> bool:
    engine = make_engine(database_url)
    try:
        with make_session_factory(engine).begin() as db:
            if is_seeded(db):
                if only_if_empty:
                    return False
                raise SystemExit("Database already has data. Use `reset` to rebuild it from scratch.")
            seed(db)
            return True
    finally:
        engine.dispose()


def reset(database_url: str) -> None:
    engine = make_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    migrate(database_url)
    load_seed(database_url, only_if_empty=False)


def reconcile(settings: Settings, *, loop: bool) -> None:
    engine = make_engine(settings.database_url)
    sessions = make_session_factory(engine)
    service = CheckoutService(sessions, make_payments_client(settings))
    reconciler = Reconciler(
        sessions,
        service,
        ReconciliationPolicy(
            min_age=timedelta(seconds=settings.reconcile_min_age_seconds),
            abandon_after=timedelta(seconds=settings.checkout_abandon_after_seconds),
        ),
    )
    while True:
        results = reconciler.run_once()
        if results:
            print(f"reconciled: {dict(results)}", flush=True)
        if not loop:
            break
        time.sleep(settings.reconcile_interval_seconds)  # scheduling only


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="northstar", description="Northstar operational commands")
    parser.add_argument("command", choices=["migrate", "seed", "init", "reset", "reconcile"])
    parser.add_argument("--yes", action="store_true", help="confirm `reset` without prompting")
    parser.add_argument("--loop", action="store_true", help="`reconcile` repeatedly")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    url = settings.database_url

    if args.command == "migrate":
        migrate(url)
    elif args.command == "seed":
        load_seed(url, only_if_empty=False)
        print("Seed data loaded.")
    elif args.command == "init":
        migrate(url)
        print("Seed data loaded." if load_seed(url, only_if_empty=True) else "Database already seeded; leaving data as is.")
    elif args.command == "reset":
        if not args.yes:
            sys.exit("`reset` deletes all data. Re-run with --yes to confirm.")
        reset(url)
        print("Database reset and reseeded.")
    elif args.command == "reconcile":
        logging.basicConfig(level=logging.INFO)
        reconcile(settings, loop=args.loop)


if __name__ == "__main__":
    main()
