"""FakePay's own persistent state: one row per merchant transaction reference."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Status(str, enum.Enum):
    AUTHORIZED = "authorized"
    DECLINED = "declined"
    CAPTURED = "captured"
    VOIDED = "voided"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    # NULL amount marks a void "tombstone": the merchant cancelled a reference
    # before any authorization for it arrived.
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    card_last4: Mapped[Optional[str]] = mapped_column(String(4))
    decline_code: Mapped[Optional[str]] = mapped_column(String(40))
    refuse_capture: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    events: Mapped[list[TransactionEvent]] = relationship(order_by="TransactionEvent.id", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('authorized', 'declined', 'captured', 'voided')", name="ck_transactions_status"),
        CheckConstraint("amount IS NULL OR amount > 0", name="ck_transactions_amount_positive"),
    )


class TransactionEvent(Base):
    """Audit trail of state-changing effects (one row per real effect, never per retry)."""

    __tablename__ = "transaction_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
