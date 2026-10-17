"""Budget reservation port and atomic in-process reference ledger.

The in-process implementation is for single-process use and tests only. It does not
provide cross-worker consistency; production must inject a transactional shared ledger.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from .errors import GatewayErrorCode, ModelGatewayError


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    reservation_id: str
    tenant_id: str
    review_task_id: str
    amount: Decimal
    kind: str = "llm"
    call_id: str | None = None


class BudgetLedger(Protocol):
    def reserve(
        self,
        tenant_id: str,
        task_id: str,
        amount: Decimal,
        *,
        call_id: str | None = None,
        kind: str = "llm",
        run_id: str | None = None,
        request_hash: str | None = None,
    ) -> BudgetReservation: ...

    def mark_dispatched(self, reservation: BudgetReservation) -> None: ...

    def settle(self, reservation: BudgetReservation, actual: Decimal) -> None: ...

    def consume_reservation(self, reservation: BudgetReservation) -> None: ...


class ExternalBudgetLedger(Protocol):
    """The embedding runtime needs only the durable external reservation methods."""

    def reserve_external(self, *, kind: str, request_hash: str, ceiling: Decimal) -> str: ...

    def settle_external(self, reservation: str, actual: Decimal) -> None: ...


class InMemoryBudgetLedger:
    """Atomic only within one Python process; missing limits fail closed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._limits: dict[tuple[str, str], Decimal] = {}
        self._reserved: dict[str, BudgetReservation] = {}
        self._spent: dict[tuple[str, str], Decimal] = {}

    def set_limit(self, tenant_id: str, task_id: str, amount: Decimal) -> None:
        if not amount.is_finite() or amount < 0:
            raise ValueError("budget limit must be a finite nonnegative amount")
        with self._lock:
            key = (tenant_id, task_id)
            reserved = sum(
                item.amount
                for item in self._reserved.values()
                if (item.tenant_id, item.review_task_id) == key
            )
            if amount < self._spent.get(key, Decimal(0)) + reserved:
                raise ValueError("budget limit cannot be reduced below spent and reserved funds")
            self._limits[key] = amount

    def reserve(
        self,
        tenant_id: str,
        task_id: str,
        amount: Decimal,
        *,
        call_id: str | None = None,
        kind: str = "llm",
        run_id: str | None = None,
        request_hash: str | None = None,
    ) -> BudgetReservation:
        if not amount.is_finite() or amount < 0:
            raise ModelGatewayError(GatewayErrorCode.BUDGET_EXCEEDED, "Budget quote is invalid.")
        key = (tenant_id, task_id)
        with self._lock:
            limit = self._limits.get(key)
            if limit is None:
                raise ModelGatewayError(
                    GatewayErrorCode.BUDGET_EXCEEDED, "No trusted task budget is configured."
                )
            reserved = sum(
                item.amount
                for item in self._reserved.values()
                if (item.tenant_id, item.review_task_id) == key
            )
            if self._spent.get(key, Decimal(0)) + reserved + amount > limit:
                raise ModelGatewayError(
                    GatewayErrorCode.BUDGET_EXCEEDED, "The task budget is insufficient."
                )
            reservation = BudgetReservation(
                uuid.uuid4().hex, tenant_id, task_id, amount, kind, call_id
            )
            self._reserved[reservation.reservation_id] = reservation
            return reservation

    def mark_dispatched(self, reservation: BudgetReservation) -> None:
        if reservation.reservation_id not in self._reserved:
            raise ModelGatewayError(
                GatewayErrorCode.BUDGET_EXCEEDED, "Budget reservation is invalid."
            )

    def settle(self, reservation: BudgetReservation, actual: Decimal) -> None:
        if not actual.is_finite() or actual < 0 or actual > reservation.amount:
            raise ModelGatewayError(
                GatewayErrorCode.BUDGET_EXCEEDED, "Actual usage exceeded its reserved budget."
            )
        self._finish(reservation, actual)

    def consume_reservation(self, reservation: BudgetReservation) -> None:
        """Charge the full ceiling when failure leaves incurred cost unknown."""
        self._finish(reservation, reservation.amount)

    def _finish(self, reservation: BudgetReservation, charge: Decimal) -> None:
        key = (reservation.tenant_id, reservation.review_task_id)
        with self._lock:
            current = self._reserved.pop(reservation.reservation_id, None)
            if current != reservation:
                raise ModelGatewayError(
                    GatewayErrorCode.BUDGET_EXCEEDED, "Budget reservation is invalid."
                )
            self._spent[key] = self._spent.get(key, Decimal(0)) + charge
