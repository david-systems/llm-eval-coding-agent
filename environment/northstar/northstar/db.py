"""Database engine and session factory construction."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False lets services return ORM objects whose attributes
    # remain readable after their transaction commits.
    return sessionmaker(bind=engine, expire_on_commit=False)
