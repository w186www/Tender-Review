"""TASK-0028 U05 PostgreSQL budget ledger semantics on a migrated database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker
from test_identity_projects import system as shared_system

from bidding_compliance.model_gateway.errors import ModelGatewayError
from bidding_compliance.model_gateway.postgres_budget import PostgresBudgetLedger
from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import (
    ModelBudgetAccount,
    ModelBudgetReservation,
)
from bidding_compliance.services.execution_authorization import set_execution_policy
from bidding_compliance.services.product_runtime import create_product_runtime

system = shared_system
AUTH_ID = "product:test"


def seed_policy(engine, *, budget: str = "10", max_call: str = "0.25") -> None:
    with Session(engine) as session:
        set_tenant(session, "a")
        set_execution_policy(
            session,
            tenant_id="a",
            actor_id="admin",
            allowed_providers=["bailian"],
            allowed_purposes=["external_review"],
            budget_cny=Decimal(budget),
            max_call_cny=Decimal(max_call),
            max_embedding_batch_cny=Decimal("0.10"),
            max_authorization_ttl_seconds=3600,
            budget_authorization_id=AUTH_ID,
        )


def ledger(engine, *, max_call: str = "0.25") -> PostgresBudgetLedger:
    return PostgresBudgetLedger(
        sessionmaker(engine, expire_on_commit=False),
        tenant_id="a",
        authorization_id=AUTH_ID,
        max_call_cny=Decimal(max_call),
    )


def account(engine) -> tuple[Decimal, Decimal, Decimal]:
    with Session(engine) as session:
        set_tenant(session, "a")
        row = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        return Decimal(row.limit_cny), Decimal(row.reserved_cny), Decimal(row.spent_cny)


def test_reserve_dispatch_settle_and_duplicate_settlement(system):
    _, engine, _, _ = system
    seed_policy(engine)
    budget = ledger(engine)
    reservation = budget.reserve(
        "a", "task-1", Decimal("0.25"), call_id="call-1", kind="llm"
    )
    assert account(engine) == (Decimal("10"), Decimal("0.25"), Decimal("0"))
    budget.mark_dispatched(reservation)
    budget.settle(reservation, Decimal("0.10"))
    assert account(engine) == (Decimal("10"), Decimal("0"), Decimal("0.10"))
    with pytest.raises(ModelGatewayError):
        budget.settle(reservation, Decimal("0.05"))
    assert account(engine) == (Decimal("10"), Decimal("0"), Decimal("0.10"))
    with Session(engine) as session:
        set_tenant(session, "a")
        row = session.get(ModelBudgetReservation, ("a", reservation.reservation_id))
        assert row.status == "settled"
        assert Decimal(row.charge_cny) == Decimal("0.10")


def test_over_reservation_is_rejected_without_partial_state(system):
    _, engine, _, _ = system
    seed_policy(engine, budget="0.25", max_call="0.25")
    budget = ledger(engine)
    first = budget.reserve("a", "task-1", Decimal("0.25"), call_id="call-1")
    assert first.reservation_id
    with pytest.raises(ModelGatewayError):
        budget.reserve("a", "task-2", Decimal("0.01"), call_id="call-2")
    assert account(engine) == (Decimal("0.25"), Decimal("0.25"), Decimal("0"))
    with Session(engine) as session:
        set_tenant(session, "a")
        assert (
            session.scalar(select(func.count()).select_from(ModelBudgetReservation)) == 1
        )


def test_same_call_identity_is_idempotent_and_final_outcome_blocks_replay(system):
    _, engine, _, _ = system
    seed_policy(engine)
    budget = ledger(engine)
    first = budget.reserve("a", "task-1", Decimal("0.25"), call_id="call-u")
    second = budget.reserve("a", "task-1", Decimal("0.25"), call_id="call-u")
    assert second.reservation_id == first.reservation_id
    assert account(engine) == (Decimal("10"), Decimal("0.25"), Decimal("0"))
    budget.mark_dispatched(first)
    assert budget.mark_call_unknown("a", "call-u") is True
    assert budget.mark_call_unknown("a", "call-u") is False
    assert account(engine) == (Decimal("10"), Decimal("0"), Decimal("0.25"))
    with pytest.raises(ModelGatewayError):
        budget.reserve("a", "task-1", Decimal("0.25"), call_id="call-u")


def test_unknown_reservation_retains_the_full_ceiling(system):
    _, engine, _, _ = system
    seed_policy(engine)
    budget = ledger(engine)
    reservation = budget.reserve("a", "task-1", Decimal("0.25"), call_id="call-x")
    budget.mark_dispatched(reservation)
    budget.consume_reservation(reservation)
    assert account(engine) == (Decimal("10"), Decimal("0"), Decimal("0.25"))
    with Session(engine) as session:
        set_tenant(session, "a")
        row = session.get(ModelBudgetReservation, ("a", reservation.reservation_id))
        assert row.status == "unknown"
        assert Decimal(row.charge_cny) == Decimal("0.25")


def test_reconcile_releases_only_never_dispatched_stale_reservations(system):
    _, engine, _, _ = system
    seed_policy(engine)
    budget = ledger(engine)
    reserved = budget.reserve("a", "task-1", Decimal("0.10"), call_id="call-r")
    dispatched = budget.reserve("a", "task-1", Decimal("0.10"), call_id="call-d")
    budget.mark_dispatched(dispatched)
    stale = datetime.now(UTC) - timedelta(hours=2)
    with Session(engine) as session:
        set_tenant(session, "a")
        session.execute(
            update(ModelBudgetReservation)
            .where(ModelBudgetReservation.reservation_id.in_([reserved.reservation_id]))
            .values(updated_at=stale)
        )
        session.execute(
            update(ModelBudgetReservation)
            .where(ModelBudgetReservation.reservation_id.in_([dispatched.reservation_id]))
            .values(updated_at=stale)
        )
        session.commit()
    result = budget.reconcile_orphaned(now=datetime.now(UTC))
    assert result == {"released": 1, "unknown": 1}
    assert account(engine) == (Decimal("10"), Decimal("0"), Decimal("0.10"))
    with Session(engine) as session:
        set_tenant(session, "a")
        statuses = {
            row.reservation_id: row.status
            for row in session.scalars(select(ModelBudgetReservation))
        }
        assert statuses[reserved.reservation_id] == "released"
        assert statuses[dispatched.reservation_id] == "unknown"


def test_summary_survives_a_new_ledger_instance(system):
    _, engine, _, _ = system
    seed_policy(engine)
    first = ledger(engine)
    reservation = first.reserve("a", "task-1", Decimal("0.25"), call_id="call-s")
    first.settle(reservation, Decimal("0.01"))
    second = ledger(engine)
    summary = second.summary()
    assert Decimal(summary["limit_cny"]) == Decimal("10")
    assert Decimal(summary["spent_cny"]) == Decimal("0.01")
    assert summary["reservation_counts"] == {"settled": 1}


def test_product_runtime_uses_the_explicit_tenant_and_rejects_a_mismatched_account(
    system, tmp_path
):
    _, engine, settings, _ = system
    seed_policy(engine)
    with Session(engine) as session:
        set_tenant(session, "a")
        account_row = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        account_row.limit_cny = Decimal("11")
        session.commit()
    with pytest.raises(ValueError, match="account limit differ"):
        create_product_runtime(
            settings=settings,
            database=engine,
            tenant_id="a",
            provider="bailian",
            purpose="external_review",
            model="qwen3.8-flash",
            api_key="configured-synthetic",
            workspace_id="synthetic-workspace",
            budget_authorization_id=AUTH_ID,
            private_root=tmp_path,
        )
    with Session(engine) as session:
        set_tenant(session, "a")
        account_row = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        account_row.limit_cny = Decimal("10")
        session.commit()
    runtime = create_product_runtime(
        settings=settings,
        database=engine,
        tenant_id="a",
        provider="bailian",
        purpose="external_review",
        model="qwen3.8-flash",
        api_key="configured-synthetic",
        workspace_id="synthetic-workspace",
        budget_authorization_id=AUTH_ID,
        private_root=tmp_path,
    )
    assert runtime.app.state.product_tenant_id == "a"
    assert runtime.app.state.external_authorization_mode == "postgres"
    assert runtime.gate.tenant_id == "a"
    assert runtime.gate.allowed_hashes() == frozenset()
    assert runtime.reconciliation == {"released": 0, "unknown": 0}
