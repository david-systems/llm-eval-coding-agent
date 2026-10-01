"""FakePay, the simulated external processor, through its HTTP API; and how
Northstar's client classifies processor results."""

import socket
import threading
import time
from decimal import Decimal

import httpx
import pytest

from northstar.config import Settings
from northstar.services.payments import FakePayClient, PaymentOutcomeUnknown, PaymentRejected, PaymentStatus
from northstar.web.app import make_payments_client
from tests.conftest import FAKEPAY_API_KEY
from tests.factories import APPROVED_CARD, CAPTURE_REFUSED_CARD, DECLINED_CARD

TEN = Decimal("10.00")


def test_authorize_capture_and_status(processor):
    txn = processor.authorize("ref-1", TEN, APPROVED_CARD)
    assert (txn.status, txn.amount, txn.card_last4) == (PaymentStatus.AUTHORIZED, TEN, "4242")
    assert processor.capture("ref-1").status == PaymentStatus.CAPTURED
    assert processor.capture("ref-1").status == PaymentStatus.CAPTURED  # idempotent
    final = processor.get("ref-1")
    assert final.status == PaymentStatus.CAPTURED
    assert final.events == ("authorized", "captured")  # one effect each, despite the repeat


@pytest.mark.parametrize("card, code", [(DECLINED_CARD, "card_declined"), ("4000 0000 0000 9995", "insufficient_funds")])
def test_declined_cards(processor, card, code):
    txn = processor.authorize("ref-2", TEN, card)
    assert txn.status == PaymentStatus.DECLINED and txn.decline_code == code
    with pytest.raises(PaymentRejected) as exc:
        processor.capture("ref-2")
    assert exc.value.code == "invalid_state"
    assert processor.void("ref-2").status == PaymentStatus.DECLINED  # nothing to release


def test_authorize_is_idempotent_per_reference(processor):
    first = processor.authorize("ref-3", TEN, APPROVED_CARD)
    assert processor.authorize("ref-3", TEN, APPROVED_CARD) == first
    assert processor.get("ref-3").events == ("authorized",)
    with pytest.raises(PaymentRejected) as exc:
        processor.authorize("ref-3", Decimal("11.00"), APPROVED_CARD)
    assert exc.value.code == "amount_mismatch"


def test_void_releases_authorization_and_blocks_capture(processor):
    processor.authorize("ref-4", TEN, APPROVED_CARD)
    assert processor.void("ref-4").status == PaymentStatus.VOIDED
    assert processor.void("ref-4").status == PaymentStatus.VOIDED  # idempotent
    with pytest.raises(PaymentRejected) as exc:
        processor.capture("ref-4")
    assert exc.value.code == "invalid_state"
    assert processor.get("ref-4").events == ("authorized", "voided")


def test_captured_payment_cannot_be_voided(processor):
    processor.authorize("ref-5", TEN, APPROVED_CARD)
    processor.capture("ref-5")
    with pytest.raises(PaymentRejected) as exc:
        processor.void("ref-5")
    assert exc.value.code == "invalid_state" and exc.value.transaction.status == PaymentStatus.CAPTURED


def test_void_before_authorization_leaves_tombstone_that_blocks_late_authorization(processor):
    assert processor.get("ref-6") is None
    assert processor.void("ref-6").status == PaymentStatus.VOIDED
    late = processor.authorize("ref-6", TEN, APPROVED_CARD)  # e.g. a delayed request arriving now
    assert late.status == PaymentStatus.VOIDED
    assert processor.get("ref-6").events == ("voided",)


def test_capture_refusal_card(processor):
    processor.authorize("ref-7", TEN, CAPTURE_REFUSED_CARD)
    for _ in range(2):  # deterministic: refused every time
        with pytest.raises(PaymentRejected) as exc:
            processor.capture("ref-7")
        assert exc.value.code == "capture_refused"
    assert processor.get("ref-7").status == PaymentStatus.AUTHORIZED
    assert processor.void("ref-7").status == PaymentStatus.VOIDED


def test_unknown_reference(processor):
    assert processor.get("missing") is None
    with pytest.raises(PaymentRejected) as exc:
        processor.capture("missing")
    assert exc.value.code == "not_found"


def test_concurrent_authorize_and_void_on_one_reference_converge(processor):
    """Concurrent external invocation, correct convergence regardless of arrival order:
    whichever of authorize/void actually reaches the processor first, the reference ends
    voided with no duplicate effects and never a capture."""
    ref = "race-concurrent"
    barrier = threading.Barrier(2)

    def do_authorize():
        barrier.wait()
        try:
            processor.authorize(ref, TEN, APPROVED_CARD)
        except PaymentRejected:
            pass

    def do_void():
        barrier.wait()
        processor.void(ref)

    t1 = threading.Thread(target=do_authorize)
    t2 = threading.Thread(target=do_void)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    txn = processor.get(ref)
    assert txn.status == PaymentStatus.VOIDED
    assert len(txn.events) == len(set(txn.events))
    assert "captured" not in txn.events
    assert txn.events in (("voided",), ("authorized", "voided"))


def test_api_requires_key(fakepay_url):
    assert httpx.get(f"{fakepay_url}/v1/transactions/x").status_code == 401
    with pytest.raises(RuntimeError):
        FakePayClient(fakepay_url, "wrong-key").get("x")


# --------------------------------------------------------------------------- client result classification


def _client(handler) -> FakePayClient:
    return FakePayClient("http://fakepay.invalid", FAKEPAY_API_KEY, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, json={"error": "boom"}),
        lambda request: httpx.Response(503, text="unavailable"),
        lambda request: httpx.Response(200, text="not json"),
        lambda request: httpx.Response(200, json={"unexpected": True}),
    ],
)
def test_server_errors_and_garbage_are_unknown_outcomes(handler):
    with pytest.raises(PaymentOutcomeUnknown):
        _client(handler).capture("ref")


def test_transport_failures_are_unknown_outcomes(payments, faults):
    faults.drop("authorize")
    with pytest.raises(PaymentOutcomeUnknown):
        payments.authorize("ref-8", TEN, APPROVED_CARD)
    assert faults.delivered["authorize"] == 0

    faults.lose_response("capture")
    payments.authorize("ref-8", TEN, APPROVED_CARD)
    with pytest.raises(PaymentOutcomeUnknown):
        payments.capture("ref-8")
    assert payments.get("ref-8").status == PaymentStatus.CAPTURED  # it happened; only the answer was lost


def test_interactive_request_bounds_are_short():
    """One request must fail fast so an unresponsive FakePay reaches the processing page
    promptly. Behavioral: a real request against a peer that completes the TCP handshake
    but never sends an HTTP response must time out and surface as PaymentOutcomeUnknown
    within (roughly) the configured bound, not hang indefinitely."""
    settings = Settings()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]

    def accept_and_stall():
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        # Never send a response; just hold the connection open.

    thread = threading.Thread(target=accept_and_stall, daemon=True)
    thread.start()

    client = make_payments_client(
        Settings(
            fakepay_url=f"http://127.0.0.1:{port}",
            fakepay_api_key=settings.fakepay_api_key,
            fakepay_timeout_seconds=settings.fakepay_timeout_seconds,
            fakepay_connect_timeout_seconds=settings.fakepay_connect_timeout_seconds,
        )
    )
    try:
        start = time.monotonic()
        with pytest.raises(PaymentOutcomeUnknown):
            client.get("some-reference")
        elapsed = time.monotonic() - start
        assert elapsed < settings.fakepay_timeout_seconds + 2.0
    finally:
        client.close()
        sock.close()
