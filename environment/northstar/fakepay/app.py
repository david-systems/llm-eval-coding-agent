"""FakePay HTTP API.

All operations are keyed by the merchant's transaction reference and are
idempotent: repeating an operation returns the current authoritative state
without repeating its effect.

    POST /v1/transactions/{reference}/authorize   {"amount": "12.34", "card_number": "..."}
    POST /v1/transactions/{reference}/capture
    POST /v1/transactions/{reference}/void
    GET  /v1/transactions/{reference}

Void of an unknown reference records a voided "tombstone", so an authorization
for that reference that arrives later (e.g. a delayed request) is refused.

Deterministic test cards (all other 12-19 digit numbers are approved):
    4000000000000002  declined (card_declined)
    4000000000009995  declined (insufficient_funds)
    4000000000000341  authorizes, but capture is refused
"""

from __future__ import annotations

import hmac
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from fakepay.config import Settings
from fakepay.models import Status, Transaction, TransactionEvent

DECLINED_CARDS = {"4000000000000002": "card_declined", "4000000000009995": "insufficient_funds"}
CAPTURE_REFUSED_CARDS = {"4000000000000341"}
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


class AuthorizeBody(BaseModel):
    amount: str
    card_number: str


class ProcessorError(Exception):
    def __init__(self, status_code: int, error: str, transaction: Optional[Transaction] = None):
        # Serialized immediately: the transaction's session is gone by the time the handler runs.
        self.status_code, self.error = status_code, error
        self.transaction = None if transaction is None else serialize(transaction)


def serialize(txn: Transaction) -> dict:
    return {
        "reference": txn.reference,
        "status": txn.status,
        "amount": None if txn.amount is None else f"{txn.amount:.2f}",
        "card_last4": txn.card_last4,
        "decline_code": txn.decline_code,
        "events": [event.kind for event in txn.events],
    }


def create_app(settings: Optional[Settings] = None, session_factory: Optional[sessionmaker[Session]] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if session_factory is None:
        session_factory = sessionmaker(create_engine(settings.database_url, pool_pre_ping=True), expire_on_commit=False)

    app = FastAPI(title="FakePay", docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(authorization: str = Header(default="")) -> None:
        if not hmac.compare_digest(authorization, f"Bearer {settings.api_key}"):
            raise HTTPException(status_code=401, detail="invalid API key")

    def valid_reference(reference: str) -> str:
        if not REFERENCE_PATTERN.match(reference):
            raise HTTPException(status_code=422, detail="invalid reference")
        return reference

    @app.exception_handler(ProcessorError)
    async def processor_error(request: Request, exc: ProcessorError):
        body = {"error": exc.error}
        if exc.transaction is not None:
            body["transaction"] = exc.transaction
        return JSONResponse(body, status_code=exc.status_code)

    def locked(db: Session, reference: str) -> Optional[Transaction]:
        return db.scalar(
            select(Transaction).where(Transaction.reference == reference).with_for_update()
            .execution_options(populate_existing=True)
        )

    def record(db: Session, txn: Transaction, status: Status) -> None:
        txn.status = status.value
        txn.events.append(TransactionEvent(kind=status.value))

    @app.post("/v1/transactions/{reference}/authorize", dependencies=[Depends(authenticate)])
    def authorize(body: AuthorizeBody, reference: str = Depends(valid_reference)):
        try:
            amount = Decimal(body.amount)
        except InvalidOperation:
            raise HTTPException(status_code=422, detail="invalid amount") from None
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
            raise HTTPException(status_code=422, detail="invalid amount")
        card = "".join(ch for ch in body.card_number if ch.isdigit())
        if not 12 <= len(card) <= 19:
            raise HTTPException(status_code=422, detail="invalid card number")

        decline_code = DECLINED_CARDS.get(card)
        with session_factory.begin() as db:
            created = db.scalar(
                pg_insert(Transaction)
                .values(
                    reference=reference,
                    status=(Status.DECLINED if decline_code else Status.AUTHORIZED).value,
                    amount=amount,
                    card_last4=card[-4:],
                    decline_code=decline_code,
                    refuse_capture=card in CAPTURE_REFUSED_CARDS,
                )
                .on_conflict_do_nothing(index_elements=["reference"])
                .returning(Transaction.id)
            )
            txn = locked(db, reference)
            if created is not None:
                txn.events.append(TransactionEvent(kind=txn.status))
            elif txn.amount is not None and txn.amount != amount:
                raise ProcessorError(409, "amount_mismatch", txn)
            # A tombstone (voided before any authorization) stays voided.
            return serialize(txn)

    @app.post("/v1/transactions/{reference}/capture", dependencies=[Depends(authenticate)])
    def capture(reference: str = Depends(valid_reference)):
        with session_factory.begin() as db:
            txn = locked(db, reference)
            if txn is None:
                raise ProcessorError(404, "not_found")
            if txn.status == Status.CAPTURED.value:
                return serialize(txn)
            if txn.status != Status.AUTHORIZED.value:
                raise ProcessorError(409, "invalid_state", txn)
            if txn.refuse_capture:
                raise ProcessorError(402, "capture_refused", txn)
            record(db, txn, Status.CAPTURED)
            db.flush()
            return serialize(txn)

    @app.post("/v1/transactions/{reference}/void", dependencies=[Depends(authenticate)])
    def void(reference: str = Depends(valid_reference)):
        with session_factory.begin() as db:
            created = db.scalar(
                pg_insert(Transaction)
                .values(reference=reference, status=Status.VOIDED.value)
                .on_conflict_do_nothing(index_elements=["reference"])
                .returning(Transaction.id)
            )
            txn = locked(db, reference)
            if created is not None:
                txn.events.append(TransactionEvent(kind="voided"))
            elif txn.status == Status.CAPTURED.value:
                raise ProcessorError(409, "invalid_state", txn)
            elif txn.status == Status.AUTHORIZED.value:
                record(db, txn, Status.VOIDED)
            db.flush()
            return serialize(txn)  # voided, or declined (nothing to release)

    @app.get("/v1/transactions/{reference}", dependencies=[Depends(authenticate)])
    def status(reference: str = Depends(valid_reference)):
        with session_factory() as db:
            txn = db.scalar(select(Transaction).where(Transaction.reference == reference))
            if txn is None:
                raise ProcessorError(404, "not_found")
            return serialize(txn)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
