"""Reconciliation of unfinished checkout attempts against the payment processor.

The reconciler finds attempts that are not terminal and drives each forward
from the processor's authoritative state (see ``CheckoutService.resume``).

Two time settings exist, and both are scheduling policy, never evidence:

* ``min_age`` - skip attempts updated very recently, so the reconciler does not
  needlessly compete with the request that is still working on them. (Competing
  would be harmless: all transitions are compare-and-set and all processor
  operations idempotent.)
* ``abandon_after`` - once an attempt is this old, stop waiting for an
  authorization the processor has no record of. The attempt is then voided at
  the processor (which also blocks a delayed authorization) before it fails.
  An authorization the processor reports as successful is never abandoned:
  checkout continues, subject to the normal inventory/product recheck.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from northstar.models import TERMINAL_ATTEMPT_STATUSES, CheckoutAttempt
from northstar.services.checkout import CheckoutService

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationPolicy:
    min_age: timedelta = timedelta(seconds=30)
    abandon_after: timedelta = timedelta(minutes=10)


class Reconciler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        checkout: CheckoutService,
        policy: ReconciliationPolicy = ReconciliationPolicy(),
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._sessions = session_factory
        self._checkout = checkout
        self._policy = policy
        self._now = clock

    def unfinished_attempts(self) -> list[tuple[int, datetime]]:
        cutoff = self._now() - self._policy.min_age
        with self._sessions() as db:
            rows = db.execute(
                select(CheckoutAttempt.id, CheckoutAttempt.created_at)
                .where(CheckoutAttempt.status.not_in(TERMINAL_ATTEMPT_STATUSES), CheckoutAttempt.updated_at <= cutoff)
                .order_by(CheckoutAttempt.id)
            ).all()
        return [(row.id, row.created_at) for row in rows]

    def run_once(self) -> Counter:
        """Examine every eligible unfinished attempt once. Returns outcome counts."""
        results: Counter = Counter()
        now = self._now()
        for attempt_id, created_at in self.unfinished_attempts():
            abandon = created_at <= now - self._policy.abandon_after
            try:
                outcome = self._checkout.resume(attempt_id, abandon_unconfirmed=abandon)
            except Exception:
                log.exception("reconciliation of checkout attempt %s failed", attempt_id)
                results["error"] += 1
                continue
            results[outcome.status] += 1
        return results
