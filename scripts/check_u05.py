"""TASK-0028 U05 real-PostgreSQL checks used by scripts/check_postgres.py.

It is deliberately a separate module: the mandatory PostgreSQL gate stays readable and
this check owns only synthetic tenant authorization, budget concurrency and history import.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from bidding_compliance.api import create_app
from bidding_compliance.model_gateway.errors import ModelGatewayError
from bidding_compliance.model_gateway.postgres_budget import PostgresBudgetLedger
from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import (
    AuditEvent,
    Document,
    DocumentExternalAuthorization,
    LedgerImport,
    ModelBudgetAccount,
    ModelBudgetReservation,
)
from bidding_compliance.services.execution_authorization import (
    PostgresAuthorizationGate,
    set_execution_policy,
)
from bidding_compliance.services.ledger_migration import migrate_historical_ledgers

PROVIDER = "bailian"
PURPOSE = "external_review"


def _token(client: TestClient, tenant: str, role: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/token",
        json=dict(tenant_id=tenant, username=role, password=password),
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def check_u05(
    *,
    admin,
    runtime,
    runtime_settings,
    password: str,
    project: dict,
    document_id: str,
) -> None:
    with Session(admin) as db:
        set_tenant(db, "a")
        db.execute(
            update(Document)
            .where(Document.tenant_id == "a", Document.document_id == document_id)
            .values(parse_version=1, status="ready")
        )
        db.commit()
        document = db.get(Document, ("a", document_id))
        assert document is not None
        document_sha = document.sha256
    with Session(admin) as db:
        set_execution_policy(
            db,
            tenant_id="a",
            actor_id="admin",
            allowed_providers=[PROVIDER],
            allowed_purposes=[PURPOSE],
            budget_cny=Decimal("10"),
            max_call_cny=Decimal("0.25"),
            max_embedding_batch_cny=Decimal("0.10"),
            max_authorization_ttl_seconds=3600,
            budget_authorization_id="product:pg",
        )
        db.add_all(
            [
                ModelBudgetAccount(
                    tenant_id="a",
                    authorization_id="product:pg-budget",
                    limit_cny=Decimal("0.25"),
                    reserved_cny=Decimal("0"),
                    spent_cny=Decimal("0"),
                    updated_at=datetime.now(UTC),
                ),
                ModelBudgetAccount(
                    tenant_id="a",
                    authorization_id="product:pg-import",
                    limit_cny=Decimal("10"),
                    reserved_cny=Decimal("0"),
                    spent_cny=Decimal("0"),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()

    with TestClient(create_app(runtime_settings)) as client:
        client.app.state.external_authorization_mode = "postgres"
        client.app.state.external_authorization_purpose = PURPOSE
        client.app.state.external_authorization_provider = PROVIDER
        reviewer_a = _token(client, "a", "reviewer", password)
        reviewer_b = _token(client, "b", "reviewer", password)
        auditor_a = _token(client, "a", "auditor", password)
        auditor_b = _token(client, "b", "auditor", password)
        url = (
            f"/api/v1/projects/{project['project_id']}/documents/{document_id}"
            "/external-authorization"
        )
        approved = client.post(
            url, headers=reviewer_a, json={"reason": "PG 合成授权", "confirmed": True}
        )
        assert approved.status_code == 201, approved.text
        first = approved.json()
        assert first["purpose"] == PURPOSE
        assert first["provider"] == PROVIDER
        assert first["parse_version"] == 1
        duplicate = client.post(
            url, headers=reviewer_a, json={"reason": "重复授权", "confirmed": True}
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["authorization_id"] == first["authorization_id"]
        cross = client.post(
            url, headers=reviewer_b, json={"reason": "跨租户", "confirmed": True}
        )
        assert cross.status_code == 404, cross.text
        denied = client.post(
            url, headers=auditor_a, json={"reason": "审计员", "confirmed": True}
        )
        assert denied.status_code == 403, denied.text
        revoked = client.post(
            url + "/revoke",
            headers=reviewer_a,
            json={"reason": "PG 撤销", "confirmed": True},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["action"] == "revoke"
        reapproved = client.post(
            url, headers=reviewer_a, json={"reason": "重新授权", "confirmed": True}
        )
        assert reapproved.status_code == 201
        assert reapproved.json()["authorization_id"] != first["authorization_id"]
        events_a = client.get("/api/v1/audit/events", headers=auditor_a)
        events_b = client.get("/api/v1/audit/events", headers=auditor_b)
        assert events_a.status_code == events_b.status_code == 200
        assert any(
            item["action"] == "document.external_authorization_approved"
            for item in events_a.json()["items"]
        )
        assert all(
            item["action"] != "document.external_authorization_approved"
            for item in events_b.json()["items"]
        )

    factory = sessionmaker(runtime, expire_on_commit=False)
    gate = PostgresAuthorizationGate(
        factory, tenant_id="a", purpose=PURPOSE, provider=PROVIDER
    )
    assert document_sha in gate.allowed_hashes()
    gate.require_run(
        tenant_id="a",
        project_id=project["project_id"],
        documents=[(document_id, document_sha, 1)],
    )
    with TestClient(create_app(runtime_settings)) as client:
        client.app.state.external_authorization_mode = "postgres"
        client.app.state.external_authorization_purpose = PURPOSE
        client.app.state.external_authorization_provider = PROVIDER
        reviewer_a = _token(client, "a", "reviewer", password)
        url = (
            f"/api/v1/projects/{project['project_id']}/documents/{document_id}"
            "/external-authorization"
        )
        final_revoke = client.post(
            url + "/revoke",
            headers=reviewer_a,
            json={"reason": "为历史导入清空活动授权", "confirmed": True},
        )
        assert final_revoke.status_code == 200, final_revoke.text
    assert document_sha not in gate.allowed_hashes()
    try:
        PostgresAuthorizationGate(
            factory, tenant_id="b", purpose=PURPOSE, provider=PROVIDER
        ).allowed_hashes()
    except PermissionError:
        pass
    else:
        raise AssertionError("Tenant b egress was allowed without a tenant policy")

    # The database, not the service, rejects a mis-attributed approval and a cross-tenant row.
    with Session(runtime) as db:
        set_tenant(db, "a")
        db.execute(text("SELECT set_config('app.user_id','reviewer',true)"))
        db.add(
            DocumentExternalAuthorization(
                tenant_id="a",
                authorization_id="raw-actor",
                project_id=project["project_id"],
                document_id=document_id,
                document_sha256=document_sha,
                parse_version=1,
                purpose=PURPOSE,
                provider=PROVIDER,
                policy_version=1,
                state="active",
                reason="raw actor mismatch",
                approved_by="admin",
                approved_at=datetime.now(UTC),
                expires_at=datetime.now(UTC).replace(year=2030),
                revoked_by=None,
                revoked_at=None,
                revocation_reason=None,
                source="api",
                source_record_id=None,
            )
        )
        try:
            db.flush()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("Authorization actor RLS accepted a mis-attributed row")
    with Session(runtime) as db:
        set_tenant(db, "b")
        db.add(
            DocumentExternalAuthorization(
                tenant_id="a",
                authorization_id="raw-cross-tenant",
                project_id=project["project_id"],
                document_id=document_id,
                document_sha256=document_sha,
                parse_version=1,
                purpose=PURPOSE,
                provider=PROVIDER,
                policy_version=1,
                state="active",
                reason="raw cross tenant",
                approved_by="reviewer",
                approved_at=datetime.now(UTC),
                expires_at=datetime.now(UTC).replace(year=2030),
                revoked_by=None,
                revoked_at=None,
                revocation_reason=None,
                source="api",
                source_record_id=None,
            )
        )
        try:
            db.flush()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("Authorization RLS accepted a cross-tenant row")

    # Multi-worker budget: exactly one of two competing reservations may win.
    ledger = PostgresBudgetLedger(
        factory,
        tenant_id="a",
        authorization_id="product:pg-budget",
        max_call_cny=Decimal("0.25"),
    )
    from threading import Barrier, Thread

    barrier = Barrier(2)
    winners = []
    failures = []

    def compete(call_id: str) -> None:
        barrier.wait()
        try:
            winners.append(
                ledger.reserve("a", "task-pg", Decimal("0.25"), call_id=call_id)
            )
        except ModelGatewayError:
            failures.append(call_id)

    threads = [Thread(target=compete, args=(f"call-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(winners) == 1 and len(failures) == 1
    winner = winners[0]
    ledger.settle(winner, Decimal("0.10"))
    try:
        ledger.settle(winner, Decimal("0.01"))
    except ModelGatewayError:
        pass
    else:
        raise AssertionError("Duplicate settlement was accepted")
    with Session(admin) as db:
        set_tenant(db, "a")
        db.execute(
            update(ModelBudgetAccount)
            .where(
                ModelBudgetAccount.tenant_id == "a",
                ModelBudgetAccount.authorization_id == "product:pg-budget",
            )
            .values(limit_cny=Decimal("1"))
        )
        db.commit()
    unknown = ledger.reserve("a", "task-pg", Decimal("0.25"), call_id="call-unknown")
    ledger.mark_dispatched(unknown)
    assert ledger.mark_call_unknown("a", "call-unknown") is True
    assert ledger.mark_call_unknown("a", "call-unknown") is False
    stale = ledger.reserve("a", "task-pg", Decimal("0.10"), call_id="call-stale")
    with Session(runtime) as db:
        set_tenant(db, "a")
        db.execute(
            update(ModelBudgetReservation)
            .where(ModelBudgetReservation.reservation_id == stale.reservation_id)
            .values(updated_at=datetime.now(UTC) - timedelta(hours=2))
        )
        db.commit()
    assert ledger.reconcile_orphaned() == {"released": 1, "unknown": 0}
    summary = ledger.summary()
    assert Decimal(summary["spent_cny"]) == Decimal("0.35")
    assert Decimal(summary["reserved_cny"]) == Decimal("0")

    # Historical import runs on the controlled management connection, twice.
    with tempfile.TemporaryDirectory() as directory:
        ledger_path = Path(directory) / "legacy.sqlite3"
        with closing(sqlite3.connect(ledger_path)) as connection:
            connection.execute(
                "CREATE TABLE requests (id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                "request_hash TEXT NOT NULL, ceiling TEXT NOT NULL, charge TEXT NOT NULL, "
                "status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "authorization_id TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO requests(id,kind,request_hash,ceiling,charge,status,authorization_id) "
                "VALUES('legacy-settled','llm',?,'0.25','0.01','settled','DEC-LEGACY')",
                ("a" * 64,),
            )
            connection.execute(
                "INSERT INTO requests(id,kind,request_hash,ceiling,charge,status,authorization_id) "
                "VALUES('legacy-reserved','embedding',?,'0.10','0.10','reserved','DEC-LEGACY')",
                ("b" * 64,),
            )
            connection.commit()
        registry_path = Path(directory) / "registry.jsonl"
        now = datetime.now(UTC).replace(microsecond=0)
        registry_path.write_text(
            "".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                for record in (
                    {
                        "action": "approve",
                        "sha256": document_sha,
                        "document_id": document_id,
                        "reason": "PG 历史授权",
                        "approved_at": now.isoformat(),
                        "approved_by": "reviewer",
                    },
                    {
                        "action": "revoke",
                        "sha256": document_sha,
                        "document_id": document_id,
                        "reason": "PG 历史撤销",
                        "approved_at": (now + timedelta(seconds=1)).isoformat(),
                        "approved_by": "reviewer",
                    },
                )
            ),
            encoding="utf-8",
        )
        with Session(admin) as db:
            report = migrate_historical_ledgers(
                db,
                tenant_id="a",
                authorization_id="product:pg-import",
                ledger_path=ledger_path,
                registry_path=registry_path,
                actor_id="admin",
                purpose=PURPOSE,
                provider=PROVIDER,
            )
            assert report["imported_counts"]["settled"] == 1
            assert report["imported_counts"]["unknown"] == 1
            assert Decimal(report["imported_sums"]["charged_cny"]) == Decimal("0.11")
        with Session(admin) as db:
            rerun = migrate_historical_ledgers(
                db,
                tenant_id="a",
                authorization_id="product:pg-import",
                ledger_path=ledger_path,
                registry_path=registry_path,
                actor_id="admin",
                purpose=PURPOSE,
                provider=PROVIDER,
            )
            assert rerun["already_imported"] is True
    with Session(runtime) as db:
        set_tenant(db, "a")
        account = db.get(ModelBudgetAccount, ("a", "product:pg-import"))
        assert Decimal(account.spent_cny) == Decimal("0.11")
        assert Decimal(account.reserved_cny) == Decimal("0")
        assert db.scalar(select(LedgerImport)) is not None
        historical = db.scalar(
            select(DocumentExternalAuthorization).where(
                DocumentExternalAuthorization.source == "jsonl_registry"
            )
        )
        assert historical is not None and historical.state == "revoked"
    with Session(runtime) as db:
        set_tenant(db, "b")
        assert list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.like("document.external_authorization%")
                )
            )
        ) == []
