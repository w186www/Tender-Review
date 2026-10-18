"""TASK-0028 U05 product authorization: transaction, revoke, version and tenant boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_identity_projects import sign_in
from test_identity_projects import system as shared_system
from test_ingestion import upload

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.model_gateway.authorization import AuthorizationPolicy
from bidding_compliance.model_gateway.contracts import DataPolicy, ModelRequest
from bidding_compliance.model_gateway.errors import ModelGatewayError
from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import (
    AuditEvent,
    Document,
    DocumentExternalAuthorization,
    ModelBudgetAccount,
    ModelExecutionPolicy,
    User,
)
from bidding_compliance.services import execution_authorization as authz
from bidding_compliance.services import identity
from bidding_compliance.services.execution_authorization import (
    PostgresAuthorizationGate,
    approve_document,
    set_execution_policy,
)
from bidding_compliance.services.legal import require_identity

system = shared_system
AUTH_ID = "product:test"


def product_mode(client) -> None:
    client.app.state.external_authorization_mode = "postgres"
    client.app.state.external_authorization_purpose = "external_review"
    client.app.state.external_authorization_provider = "bailian"


def seed_policy(
    engine,
    tenant: str = "a",
    *,
    budget: str = "10",
    ttl: int = 3600,
    active: bool = True,
) -> None:
    with Session(engine) as session:
        set_tenant(session, tenant)
        set_execution_policy(
            session,
            tenant_id=tenant,
            actor_id="admin",
            allowed_providers=["bailian"],
            allowed_purposes=["external_review"],
            budget_cny=Decimal(budget),
            max_call_cny=Decimal("0.25"),
            max_embedding_batch_cny=Decimal("0.10"),
            max_authorization_ttl_seconds=ttl,
            active=active,
            budget_authorization_id=AUTH_ID,
        )


def prepare_document(system):
    client, engine, _, _ = system
    headers = sign_in(system)
    project, uploaded = upload(system, headers=headers)
    document = uploaded.json()
    with Session(engine) as session:
        set_tenant(session, "a")
        row = session.get(Document, ("a", document["document_id"]))
        assert row is not None
        row.parse_version = 1
        row.status = "ready"
        session.commit()
    return project, document, headers


def endpoint(project: str, document: str) -> str:
    return f"/api/v1/projects/{project}/documents/{document}/external-authorization"


def gate(engine, tenant: str = "a", provider: str = "bailian", purpose: str = "external_review"):
    return PostgresAuthorizationGate(
        sessionmaker(engine, expire_on_commit=False),
        tenant_id=tenant,
        purpose=purpose,
        provider=provider,
    )


def current_principal(system) -> Principal:
    _, engine, settings, password = system
    with Session(engine) as session:
        token = identity.login(session, settings, "a", "reviewer", password)
        return identity.authenticate(session, settings, token)


def test_approval_is_version_bound_idempotent_and_audited_once(system):
    client, engine, _, _ = system
    seed_policy(engine)
    product_mode(client)
    project, document, headers = prepare_document(system)
    url = endpoint(project, document["document_id"])

    first = client.post(
        url, headers=headers, json={"reason": "合成样本逐文件授权", "confirmed": True}
    )
    assert first.status_code == 201, first.text
    payload = first.json()
    assert payload["action"] == "approve"
    assert payload["purpose"] == "external_review"
    assert payload["provider"] == "bailian"
    assert payload["parse_version"] == 1
    assert payload["authorization_id"]
    assert payload["expires_at"]

    second = client.post(
        url, headers=headers, json={"reason": "重复提交", "confirmed": True}
    )
    assert second.status_code == 201, second.text
    assert second.json()["authorization_id"] == payload["authorization_id"]

    with Session(engine) as session:
        set_tenant(session, "a")
        rows = list(session.scalars(select(DocumentExternalAuthorization)))
        assert len(rows) == 1
        assert rows[0].state == "active"
        assert rows[0].document_sha256 == document["sha256"]
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "document.external_authorization_approved"
                )
            )
        )
        assert len(events) == 1

    live = gate(engine)
    assert document["sha256"] in live.allowed_hashes()
    live.require_run(
        tenant_id="a",
        project_id=project,
        documents=[(document["document_id"], document["sha256"], 1)],
    )
    with pytest.raises(PermissionError):
        live.require_run(
            tenant_id="a",
            project_id=project,
            documents=[(document["document_id"], document["sha256"], 2)],
        )


def test_audit_failure_rolls_back_the_authorization(system, monkeypatch):
    _, engine, _, _ = system
    seed_policy(engine)
    project, document, _ = prepare_document(system)
    principal = current_principal(system)

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic audit write failure")

    monkeypatch.setattr(authz, "audit", fail)
    with Session(engine) as session:
        with pytest.raises(RuntimeError):
            approve_document(
                session,
                principal,
                project,
                document["document_id"],
                reason="审计失败必须回滚",
                purpose="external_review",
                provider="bailian",
            )
        session.rollback()
    with Session(engine) as session:
        set_tenant(session, "a")
        assert session.scalar(select(func.count()).select_from(DocumentExternalAuthorization)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "document.external_authorization_approved")
            )
            == 0
        )


def test_revoke_is_effective_on_the_next_gate_check_and_reapproval_is_new(system):
    client, engine, _, _ = system
    seed_policy(engine)
    product_mode(client)
    project, document, headers = prepare_document(system)
    url = endpoint(project, document["document_id"])
    approved = client.post(
        url, headers=headers, json={"reason": "撤销前授权", "confirmed": True}
    ).json()
    live = gate(engine)
    assert document["sha256"] in live.allowed_hashes()

    revoked = client.post(
        url + "/revoke", headers=headers, json={"reason": "立即撤销", "confirmed": True}
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["action"] == "revoke"
    assert revoked.json()["authorization_id"] == approved["authorization_id"]
    assert live.allowed_hashes() == frozenset()
    with pytest.raises(PermissionError):
        live.require_run(
            tenant_id="a",
            project_id=project,
            documents=[(document["document_id"], document["sha256"], 1)],
        )

    repeated = client.post(
        url + "/revoke", headers=headers, json={"reason": "重复撤销", "confirmed": True}
    )
    assert repeated.status_code == 200
    assert repeated.json()["authorization_id"] == approved["authorization_id"]

    again = client.post(url, headers=headers, json={"reason": "撤销后重新授权", "confirmed": True})
    assert again.status_code == 201
    assert again.json()["authorization_id"] != approved["authorization_id"]
    assert document["sha256"] in gate(engine).allowed_hashes()


def test_expiry_version_and_policy_mismatch_fail_closed(system, monkeypatch):
    client, engine, _, _ = system
    seed_policy(engine, ttl=60)
    product_mode(client)
    project, document, headers = prepare_document(system)
    client.post(
        endpoint(project, document["document_id"]),
        headers=headers,
        json={"reason": "短期授权", "confirmed": True},
    )
    live = gate(engine)
    assert document["sha256"] in live.allowed_hashes()

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(authz, "datetime", Future)
    assert live.allowed_hashes() == frozenset()
    monkeypatch.undo()

    with Session(engine) as session:
        set_tenant(session, "a")
        row = session.get(Document, ("a", document["document_id"]))
        row.parse_version = 2
        session.commit()
    with pytest.raises(PermissionError):
        live.require_run(
            tenant_id="a",
            project_id=project,
            documents=[(document["document_id"], document["sha256"], 1)],
        )

    with pytest.raises(PermissionError):
        gate(engine, provider="other").allowed_hashes()
    with pytest.raises(PermissionError):
        gate(engine, purpose="other_purpose").allowed_hashes()
    with Session(engine) as session:
        set_tenant(session, "a")
        policy = session.get(ModelExecutionPolicy, "a")
        policy.active = False
        session.commit()
    with pytest.raises(PermissionError):
        live.allowed_hashes()


def test_tenant_isolation_covers_api_gate_and_audit_reads(system):
    client, engine, _, _ = system
    seed_policy(engine, "a")
    seed_policy(engine, "b")
    product_mode(client)
    project, document, reviewer_a = prepare_document(system)
    auditor_a = sign_in(system, role="auditor")
    reviewer_b = sign_in(system, tenant="b", role="reviewer")
    auditor_b = sign_in(system, tenant="b", role="auditor")

    assert (
        client.post(
            endpoint(project, document["document_id"]),
            headers=reviewer_b,
            json={"reason": "跨租户越权", "confirmed": True},
        ).status_code
        == 404
    )
    assert (
        client.post(
            endpoint(project, document["document_id"]),
            headers=auditor_a,
            json={"reason": "审计员不能登记", "confirmed": True},
        ).status_code
        == 403
    )
    assert (
        client.post(
            endpoint(project, document["document_id"]),
            headers=reviewer_a,
            json={"reason": "租户甲授权", "confirmed": True},
        ).status_code
        == 201
    )
    assert gate(engine, "b").allowed_hashes() == frozenset()
    assert document["sha256"] in gate(engine, "a").allowed_hashes()

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


def test_gateway_authorization_rejects_a_foreign_tenant_even_with_a_trusted_call():
    policy = AuthorizationPolicy(
        trusted_calls={"call-1": ("a", "task-1", "node-1")},
        tenant_providers={"a": frozenset({"bailian"})},
        provider_data_policies={"bailian": frozenset({DataPolicy.CONFIDENTIAL})},
    )
    foreign = ModelRequest(
        call_id="call-1",
        tenant_id="b",
        review_task_id="task-1",
        node_run_id="node-1",
        prompt_version="p",
        system_instruction="s",
        input_payload={},
    )
    with pytest.raises(ModelGatewayError):
        policy.authorize(foreign, "bailian", DataPolicy.CONFIDENTIAL)


def test_background_worker_rechecks_current_user_and_role_but_not_a_login_session(system):
    _, engine, _, _ = system
    principal = current_principal(system)
    background = Principal(
        "a",
        "reviewer",
        "reviewer",
        Role.REVIEWER,
        "worker",
        background_worker=True,
        execution_lease_id="lease-a",
        execution_generation=1,
    )
    with Session(engine) as session:
        require_identity(session, principal)
        require_identity(session, background)
    with Session(engine) as session:
        row = session.get(User, ("a", "reviewer"))
        row.active = False
        session.commit()
    with Session(engine) as session:
        with pytest.raises(PermissionError):
            require_identity(session, principal)
        with pytest.raises(PermissionError):
            require_identity(session, background)
    with Session(engine) as session:
        row = session.get(User, ("a", "reviewer"))
        row.active = True
        row.role = "auditor"
        session.commit()
    with Session(engine) as session:
        with pytest.raises(PermissionError):
            require_identity(session, background)


def test_policy_provisioning_requires_admin_and_uses_one_account(system):
    _, engine, _, _ = system
    with Session(engine) as session:
        set_tenant(session, "a")
        with pytest.raises(PermissionError):
            set_execution_policy(
                session,
                tenant_id="a",
                actor_id="reviewer",
                allowed_providers=["bailian"],
                allowed_purposes=["external_review"],
                budget_cny=Decimal("1"),
                max_call_cny=Decimal("0.25"),
                max_embedding_batch_cny=Decimal("0.10"),
                max_authorization_ttl_seconds=3600,
                budget_authorization_id=AUTH_ID,
            )
        session.rollback()
    seed_policy(engine, budget="5")
    with Session(engine) as session:
        set_tenant(session, "a")
        account = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        assert account is not None
        assert Decimal(account.limit_cny) == Decimal("5")
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "model_execution_policy.updated")
            )
            == 1
        )
        policy = session.get(ModelExecutionPolicy, "a")
        assert policy is not None and policy.policy_version == 1
