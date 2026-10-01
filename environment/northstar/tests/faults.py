"""Deterministic fault injection on Northstar's side of the payment boundary.

``FaultInjector`` is an httpx transport placed under the real ``FakePayClient``.
It forwards requests to a real FakePay server, and can, for chosen operations
and occurrences:

* drop a request before it is sent (the processor never sees it);
* lose the response after the processor has applied the request;
* hold a request at a gate or barrier (before or after it reaches the processor);
* simulate Northstar crashing before or after a request;
* run an arbitrary action (e.g. sell out stock) at that point.

Faults are selected by operation and occurrence count, never by timing, so
every scenario is reproducible. None of this exists in production code.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

OPERATIONS = ("authorize", "capture", "void", "status")


class SimulatedCrash(BaseException):
    """Northstar 'dies' at this point. BaseException, so no application handler swallows it."""


def operation_of(request: httpx.Request) -> str:
    if request.method == "GET":
        return "status"
    return request.url.path.rstrip("/").rsplit("/", 1)[-1]


@dataclass
class _Rule:
    op: Optional[str]  # None = every operation
    when: str  # "before" (not yet sent) or "after" (processor has applied it)
    action: Callable[[httpx.Request], None]
    occurrence: Optional[int]  # None = every occurrence

    def matches(self, op: str, when: str, n: int) -> bool:
        return (self.op in (None, op)) and self.when == when and (self.occurrence in (None, n))


class Gate:
    """Blocks a request until released; ``reached`` is set when a request arrives."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self._released = threading.Event()

    def __call__(self, request: httpx.Request) -> None:
        self.reached.set()
        if not self._released.wait(timeout=30):
            raise RuntimeError("gate was never released")

    def wait_reached(self) -> None:
        if not self.reached.wait(timeout=30):
            raise RuntimeError("no request reached the gate")

    def release(self) -> None:
        self._released.set()


class FaultInjector(httpx.BaseTransport):
    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()
        self._lock = threading.Lock()
        self._rules: list[_Rule] = []
        self.attempted: Counter = Counter()  # requests Northstar tried to send, per operation
        self.delivered: Counter = Counter()  # requests the processor actually received

    # ------------------------------------------------------------------ transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        op = operation_of(request)
        with self._lock:
            self.attempted[op] += 1
            n = self.attempted[op]
            before = [r for r in self._rules if r.matches(op, "before", n)]
            after = [r for r in self._rules if r.matches(op, "after", n)]
        for rule in before:
            rule.action(request)
        response = self._inner.handle_request(request)
        response.read()
        with self._lock:
            self.delivered[op] += 1
        for rule in after:
            rule.action(request)
        return response

    def close(self) -> None:
        self._inner.close()

    # ------------------------------------------------------------------ scenario builders

    def clear(self) -> None:
        with self._lock:
            self._rules.clear()

    def _add(self, op, when, action, occurrence) -> None:
        assert op is None or op in OPERATIONS, op
        with self._lock:
            self._rules.append(_Rule(op, when, action, occurrence))

    def drop(self, op: Optional[str], occurrence: Optional[int] = 1) -> None:
        """The request fails before reaching the processor (connection error)."""
        def action(request):
            raise httpx.ConnectError("simulated: processor unreachable", request=request)
        self._add(op, "before", action, occurrence)

    def unavailable(self, op: Optional[str] = None) -> None:
        """Every request (for ``op``, or all) fails to reach the processor until ``clear()``."""
        self.drop(op, occurrence=None)

    def lose_response(self, op: str, occurrence: Optional[int] = 1) -> None:
        """The processor applies the request, but its response never arrives."""
        def action(request):
            raise httpx.ReadTimeout("simulated: response lost", request=request)
        self._add(op, "after", action, occurrence)

    def crash(self, op: str, when: str, occurrence: Optional[int] = 1) -> None:
        def action(request):
            raise SimulatedCrash(f"crash {when} {op}")
        self._add(op, when, action, occurrence)

    def run(self, op: str, action: Callable[[], None], when: str = "after", occurrence: Optional[int] = 1) -> None:
        self._add(op, when, lambda request: action(), occurrence)

    def gate(self, op: str, when: str = "before", occurrence: Optional[int] = 1) -> Gate:
        gate = Gate()
        self._add(op, when, gate, occurrence)
        return gate

    def barrier(self, op: str, parties: int, when: str = "after") -> threading.Barrier:
        barrier = threading.Barrier(parties, timeout=30)
        self._add(op, when, lambda request: barrier.wait(), None)
        return barrier
