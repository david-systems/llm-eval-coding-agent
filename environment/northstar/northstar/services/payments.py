"""Client for the external payment processor (FakePay).

Northstar reaches the processor only through this HTTP client; it never sees
the processor's storage and cannot share a transaction with it.

Every call ends in exactly one of three ways:

* a ``Transaction`` - the processor's authoritative state after the call;
* ``PaymentRejected`` - the processor definitively refused the operation;
* ``PaymentOutcomeUnknown`` - no authoritative answer (connection failure,
  timeout, 5xx, garbled response). The operation may or may not have taken
  effect; only a later status lookup or idempotent retry can tell.

All processor operations are idempotent per transaction reference, so
retrying any of them is always safe.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import httpx


class PaymentStatus(str, enum.Enum):
    AUTHORIZED = "authorized"
    DECLINED = "declined"
    CAPTURED = "captured"
    VOIDED = "voided"


@dataclass(frozen=True)
class Transaction:
    reference: str
    status: PaymentStatus
    amount: Optional[Decimal]
    card_last4: Optional[str]
    decline_code: Optional[str]
    events: tuple[str, ...] = ()


class PaymentOutcomeUnknown(Exception):
    """The processor's result could not be determined."""


class PaymentRejected(Exception):
    """The processor definitively refused the operation."""

    def __init__(self, code: str, transaction: Optional[Transaction]):
        super().__init__(code)
        self.code = code
        self.transaction = transaction


def normalize_card_number(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def is_plausible_card_number(digits: str) -> bool:
    return 12 <= len(digits) <= 19


class FakePayClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = 3.0,
        connect_timeout_seconds: float = 1.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds),
            transport=transport,
        )

    def authorize(self, reference: str, amount: Decimal, card_number: str) -> Transaction:
        response = self._send(
            "POST", f"/v1/transactions/{reference}/authorize",
            json={"amount": f"{amount:.2f}", "card_number": card_number},
        )
        return self._result(response)

    def capture(self, reference: str) -> Transaction:
        return self._result(self._send("POST", f"/v1/transactions/{reference}/capture"))

    def void(self, reference: str) -> Transaction:
        """Release an authorization; for an unknown reference, block any later authorization."""
        return self._result(self._send("POST", f"/v1/transactions/{reference}/void"))

    def get(self, reference: str) -> Optional[Transaction]:
        """Authoritative status, or None if the processor has no record of the reference."""
        response = self._send("GET", f"/v1/transactions/{reference}")
        if response.status_code == 404:
            return None
        return self._result(response)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ internals

    def _send(self, method: str, path: str, json: Optional[dict] = None) -> httpx.Response:
        try:
            response = self._http.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise PaymentOutcomeUnknown(f"{method} {path}: {exc!r}") from exc
        if response.status_code >= 500:
            raise PaymentOutcomeUnknown(f"{method} {path}: HTTP {response.status_code}")
        return response

    def _result(self, response: httpx.Response) -> Transaction:
        try:
            body = response.json()
        except ValueError:
            raise PaymentOutcomeUnknown(f"unreadable processor response (HTTP {response.status_code})") from None
        if response.status_code == 200:
            return _transaction(body)
        if response.status_code in (402, 404, 409):
            txn = body.get("transaction")
            return self._reject(body.get("error", "rejected"), _transaction(txn) if txn else None)
        # 401/422 etc. mean Northstar sent a bad request: a bug or misconfiguration, not a payment outcome.
        raise RuntimeError(f"payment processor rejected the request: HTTP {response.status_code} {body}")

    @staticmethod
    def _reject(code: str, txn: Optional[Transaction]):
        raise PaymentRejected(code, txn)


def _transaction(body: dict) -> Transaction:
    try:
        return Transaction(
            reference=body["reference"],
            status=PaymentStatus(body["status"]),
            amount=None if body.get("amount") is None else Decimal(body["amount"]),
            card_last4=body.get("card_last4"),
            decline_code=body.get("decline_code"),
            events=tuple(body.get("events") or ()),
        )
    except (KeyError, ValueError, TypeError):
        raise PaymentOutcomeUnknown(f"unexpected processor response: {body!r}") from None
