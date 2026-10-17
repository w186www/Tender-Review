"""PostgreSQL budget authority for product mode: atomic multi-worker reserve/settle.

The account row is the single quota. A conditional UPDATE reserves only when
``reserved + spent + amount <= limit``; SQLite is supported for focused tests, while
PostgreSQL is the product authority. Unknown outcomes are charged at their ceiling and are
never released or replayed. A reservation that was never marked ``dispatched`` can be
released after an explicit timeout; that is the only release path.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import ModelBudgetAccount, ModelBudgetReservation

from .budget import BudgetReservation
from .errors import GatewayErrorCode, ModelGatewayError

MAX_REASON_HASH = 64


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _rowcount(result: Any) -> int:
    return int(getattr(result, "rowcount", 0))


def _reject(message: str) -> ModelGatewayError:
    return ModelGatewayError(GatewayErrorCode.BUDGET_EXCEEDED, message)


class PostgresBudgetLedger:
    """One tenant+authorization account; every operation is a single DB transaction."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        tenant_id: str,
        authorization_id: str,
        max_call_cny: Decimal = Decimal("0.25"),
        max_embedding_batch_cny: Decimal = Decimal("0.10"),
        reservation_ttl_seconds: int = 900,
        dispatched_ttl_seconds: int = 3600,
    ) -> None:
        if not max_call_cny.is_finite() or max_call_cny <= 0:
            raise ValueError("max call budget must be a finite positive amount")
        if not max_embedding_batch_cny.is_finite() or max_embedding_batch_cny <= 0:
            raise ValueError("max embedding budget must be a finite positive amount")
        self.session_factory = session_factory
        self.tenant_id = tenant_id
        self.authorization_id = authorization_id
        self.max_call_cny = max_call_cny
        self.max_embedding_batch_cny = max_embedding_batch_cny
        self.reservation_ttl_seconds = reservation_ttl_seconds
        self.dispatched_ttl_seconds = dispatched_ttl_seconds

    def _session(self) -> Session:
        session = self.session_factory()
        set_tenant(session, self.tenant_id)
        return session

    def verify_account(self) -> dict[str, Any]:
        with self._session() as session:
            account = session.get(
                ModelBudgetAccount,
                (self.tenant_id, self.authorization_id),
                populate_existing=True,
            )
            if account is None:
                raise _reject("no PostgreSQL budget account is provisioned for this tenant")
            return self._account(account)

    @staticmethod
    def _account(account: ModelBudgetAccount) -> dict[str, str]:
        return {
            "tenant_id": account.tenant_id,
            "authorization_id": account.authorization_id,
            "limit_cny": str(_dec(account.limit_cny)),
            "reserved_cny": str(_dec(account.reserved_cny)),
            "spent_cny": str(_dec(account.spent_cny)),
        }

    def _reserve(
        self,
        *,
        tenant_id: str,
        task_id: str | None,
        amount: Decimal,
        call_id: str | None,
        kind: str,
        run_id: str | None,
        request_hash: str,
    ) -> BudgetReservation:
        if tenant_id != self.tenant_id:
            raise _reject("budget tenant differs from the provisioned account")
        if kind not in {"llm", "embedding"}:
            raise _reject("budget kind is invalid")
        ceiling_limit = self.max_call_cny if kind == "llm" else self.max_embedding_batch_cny
        if not amount.is_finite() or amount <= 0 or amount > ceiling_limit:
            raise _reject("Budget quote exceeds its configured ceiling.")
        if kind == "llm" and not task_id:
            raise _reject("LLM reservations require a review task identity")
        if len(request_hash) != 64 or any(
            character not in "0123456789abcdef" for character in request_hash
        ):
            raise _reject("budget request hash is invalid")
        now = datetime.now(UTC)
        with self._session() as session:
            if call_id is not None:
                existing = session.scalar(
                    select(ModelBudgetReservation).where(
                        ModelBudgetReservation.tenant_id == self.tenant_id,
                        ModelBudgetReservation.call_id == call_id,
                    )
                )
                if existing is not None:
                    if (
                        existing.review_task_id != task_id
                        or existing.kind != kind
                        or _dec(existing.ceiling_cny) != amount
                        or existing.request_hash != request_hash
                    ):
                        raise _reject("budget reservation identity conflicts with this call")
                    if existing.status not in {"reserved", "dispatched"}:
                        raise _reject("this model call already has a final budget outcome")
                    return BudgetReservation(
                        existing.reservation_id,
                        self.tenant_id,
                        task_id or "",
                        amount,
                        kind,
                        call_id,
                    )
            updated = session.execute(
                update(ModelBudgetAccount)
                .where(
                    ModelBudgetAccount.tenant_id == self.tenant_id,
                    ModelBudgetAccount.authorization_id == self.authorization_id,
                    ModelBudgetAccount.reserved_cny
                    + ModelBudgetAccount.spent_cny
                    + amount
                    <= ModelBudgetAccount.limit_cny,
                )
                .values(
                    reserved_cny=ModelBudgetAccount.reserved_cny + amount,
                    updated_at=now,
                )
            )
            if _rowcount(updated) != 1:
                session.rollback()
                raise _reject("The tenant budget is insufficient or the account is missing.")
            identifier = uuid4().hex
            session.add(
                ModelBudgetReservation(
                    tenant_id=self.tenant_id,
                    reservation_id=identifier,
                    authorization_id=self.authorization_id,
                    review_task_id=task_id,
                    review_run_id=run_id,
                    call_id=call_id,
                    kind=kind,
                    request_hash=request_hash,
                    ceiling_cny=amount,
                    charge_cny=None,
                    status="reserved",
                    source="product",
                    source_ref=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if call_id is not None:
                    existing = session.scalar(
                        select(ModelBudgetReservation).where(
                            ModelBudgetReservation.tenant_id == self.tenant_id,
                            ModelBudgetReservation.call_id == call_id,
                        )
                    )
                    if existing is not None and existing.status in {"reserved", "dispatched"}:
                        return BudgetReservation(
                            existing.reservation_id,
                            self.tenant_id,
                            task_id or "",
                            amount,
                            kind,
                            call_id,
                        )
                raise _reject("budget reservation conflicted") from exc
            return BudgetReservation(
                identifier, self.tenant_id, task_id or "", amount, kind, call_id
            )

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
        digest = request_hash or hashlib.sha256(
            f"{tenant_id}:{task_id}:{call_id or uuid4().hex}".encode()
        ).hexdigest()
        return self._reserve(
            tenant_id=tenant_id,
            task_id=task_id,
            amount=amount,
            call_id=call_id,
            kind=kind,
            run_id=run_id,
            request_hash=digest,
        )

    def reserve_external(self, *, kind: str, request_hash: str, ceiling: Decimal) -> str:
        return self._reserve(
            tenant_id=self.tenant_id,
            task_id=None,
            amount=ceiling,
            call_id=None,
            kind=kind,
            run_id=None,
            request_hash=request_hash,
        ).reservation_id

    def mark_dispatched(self, reservation: BudgetReservation) -> None:
        now = datetime.now(UTC)
        with self._session() as session:
            changed = session.execute(
                update(ModelBudgetReservation)
                .where(
                    ModelBudgetReservation.tenant_id == self.tenant_id,
                    ModelBudgetReservation.reservation_id == reservation.reservation_id,
                    ModelBudgetReservation.status == "reserved",
                )
                .values(status="dispatched", updated_at=now)
            )
            if _rowcount(changed) != 1:
                session.rollback()
                raise _reject("budget reservation is not eligible for dispatch")
            session.commit()

    def _finish(
        self,
        reservation_id: str,
        *,
        charge: Decimal,
        status: str,
    ) -> None:
        now = datetime.now(UTC)
        with self._session() as session:
            row = session.scalar(
                select(ModelBudgetReservation).where(
                    ModelBudgetReservation.tenant_id == self.tenant_id,
                    ModelBudgetReservation.reservation_id == reservation_id,
                )
            )
            if row is None:
                raise _reject("budget reservation is missing")
            ceiling = _dec(row.ceiling_cny)
            if status in {"settled", "unknown"} and (charge < 0 or charge > ceiling):
                raise _reject("actual usage exceeds the reserved budget")
            if status == "released" and charge != 0:
                raise _reject("a released reservation must carry a zero charge")
            changed = session.execute(
                update(ModelBudgetReservation)
                .where(
                    ModelBudgetReservation.tenant_id == self.tenant_id,
                    ModelBudgetReservation.reservation_id == reservation_id,
                    ModelBudgetReservation.status.in_(["reserved", "dispatched"]),
                )
                .values(status=status, charge_cny=charge, updated_at=now)
            )
            if _rowcount(changed) != 1:
                session.rollback()
                raise _reject("budget reservation was already settled or released")
            account = session.execute(
                update(ModelBudgetAccount)
                .where(
                    ModelBudgetAccount.tenant_id == self.tenant_id,
                    ModelBudgetAccount.authorization_id == self.authorization_id,
                    ModelBudgetAccount.reserved_cny >= ceiling,
                )
                .values(
                    reserved_cny=ModelBudgetAccount.reserved_cny - ceiling,
                    spent_cny=ModelBudgetAccount.spent_cny + charge,
                    updated_at=now,
                )
            )
            if _rowcount(account) != 1:
                session.rollback()
                raise _reject("budget account does not match its reservation")
            try:
                session.commit()
            except Exception:
                session.rollback()
                raise

    def settle(self, reservation: BudgetReservation, actual: Decimal) -> None:
        if not actual.is_finite() or actual < 0:
            raise _reject("settled cost is invalid")
        self._finish(reservation.reservation_id, charge=actual, status="settled")

    def settle_external(self, reservation: str, actual: Decimal) -> None:
        if not actual.is_finite() or actual < 0:
            raise _reject("settled cost is invalid")
        self._finish(reservation, charge=actual, status="settled")

    def consume_reservation(self, reservation: BudgetReservation) -> None:
        """Unknown outcome: retain the full ceiling, never release or replay."""
        self._finish(
            reservation.reservation_id,
            charge=reservation.amount,
            status="unknown",
        )

    def mark_call_unknown(self, tenant_id: str, call_id: str) -> bool:
        """Charge a dispatched-but-unresolved call at its ceiling; idempotent."""
        if tenant_id != self.tenant_id:
            raise _reject("budget tenant differs from the provisioned account")
        now = datetime.now(UTC)
        with self._session() as session:
            row = session.scalar(
                select(ModelBudgetReservation).where(
                    ModelBudgetReservation.tenant_id == self.tenant_id,
                    ModelBudgetReservation.call_id == call_id,
                )
            )
            if row is None:
                return False
            if row.status in {"settled", "unknown", "released"}:
                return False
            ceiling = _dec(row.ceiling_cny)
            changed = session.execute(
                update(ModelBudgetReservation)
                .where(
                    ModelBudgetReservation.tenant_id == self.tenant_id,
                    ModelBudgetReservation.reservation_id == row.reservation_id,
                    ModelBudgetReservation.status.in_(["reserved", "dispatched"]),
                )
                .values(status="unknown", charge_cny=ceiling, updated_at=now)
            )
            if _rowcount(changed) != 1:
                session.rollback()
                return False
            account = session.execute(
                update(ModelBudgetAccount)
                .where(
                    ModelBudgetAccount.tenant_id == self.tenant_id,
                    ModelBudgetAccount.authorization_id == self.authorization_id,
                    ModelBudgetAccount.reserved_cny >= ceiling,
                )
                .values(
                    reserved_cny=ModelBudgetAccount.reserved_cny - ceiling,
                    spent_cny=ModelBudgetAccount.spent_cny + ceiling,
                    updated_at=now,
                )
            )
            if _rowcount(account) != 1:
                session.rollback()
                raise _reject("budget account does not match its reservation")
            session.commit()
            return True

    def reconcile_orphaned(self, *, now: datetime | None = None) -> dict[str, int]:
        """Resolve stale reservations after a restart; never releases dispatched calls."""
        current = now or datetime.now(UTC)
        released = unknown = 0
        with self._session() as session:
            stale_reserved = list(
                session.scalars(
                    select(ModelBudgetReservation).where(
                        ModelBudgetReservation.tenant_id == self.tenant_id,
                        ModelBudgetReservation.status == "reserved",
                        ModelBudgetReservation.updated_at
                        <= current - timedelta(seconds=self.reservation_ttl_seconds),
                    )
                )
            )
            stale_dispatched = list(
                session.scalars(
                    select(ModelBudgetReservation).where(
                        ModelBudgetReservation.tenant_id == self.tenant_id,
                        ModelBudgetReservation.status == "dispatched",
                        ModelBudgetReservation.updated_at
                        <= current - timedelta(seconds=self.dispatched_ttl_seconds),
                    )
                )
            )
        for row in stale_reserved:
            try:
                self._finish(row.reservation_id, charge=Decimal(0), status="released")
                released += 1
            except ModelGatewayError:
                continue
        for row in stale_dispatched:
            try:
                self._finish(
                    row.reservation_id,
                    charge=_dec(row.ceiling_cny),
                    status="unknown",
                )
                unknown += 1
            except ModelGatewayError:
                continue
        return {"released": released, "unknown": unknown}

    def summary(self) -> dict[str, Any]:
        with self._session() as session:
            account = session.get(
                ModelBudgetAccount,
                (self.tenant_id, self.authorization_id),
                populate_existing=True,
            )
            rows = session.execute(
                select(ModelBudgetReservation.status, func.count())
                .where(ModelBudgetReservation.tenant_id == self.tenant_id)
                .group_by(ModelBudgetReservation.status)
            ).all()
            counts: dict[str, int] = {
                str(status): int(count) for status, count in rows
            }
            account_data = (
                self._account(account)
                if account is not None
                else {"tenant_id": self.tenant_id, "authorization_id": self.authorization_id}
            )
            return {
                **account_data,
                "reservation_counts": counts,
            }
