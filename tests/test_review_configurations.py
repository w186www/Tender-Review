"""TASK-0011 FR-013: immutable tenant releases and auditable configuration CAS."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_legal_publications import (
    principal as legal_principal,
)
from test_legal_publications import (
    publish_request,
)
from test_legal_publications import (
    revision as create_legal_revision,
)
from test_legal_retrieval import version
from test_legal_runs import system as base_fixture

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.domain.review_configuration import ModelPolicySnapshot
from bidding_compliance.model_gateway.contracts import DataPolicy, ModelPolicy
from bidding_compliance.persistence.models import (
    AuditEvent,
    AuthSession,
    LegalOperatorGrant,
    ReviewConfigurationRevision,
    ReviewConfigurationState,
    User,
)
from bidding_compliance.services import legal_management
from bidding_compliance.services import review_configurations as configurations

_base_system = base_fixture


@pytest.fixture
def configuration_system(_base_system, tmp_path):
    engine, _, _ = _base_system
    root = tmp_path
    public = tmp_path / "knowledge/legal"
    public.mkdir(parents=True)
    metadata = version(public).model_copy(
        update={
            "text_path": "knowledge/legal/law.txt",
            "source_snapshot_path": "knowledge/legal/law.txt",
        }
    )
    with Session(engine) as session:
        for tenant in ("a", "b"):
            session.add(
                LegalOperatorGrant(
                    tenant_id=tenant,
                    user_id="u",
                    active=True,
                    capabilities=["ingest", "verify", "publish", "disable", "rollback"],
                )
            )
        session.commit()
    now = datetime.now(UTC)
    with Session(engine) as session:
        for tenant, user_id in (("a", "manager"), ("b", "manager")):
            session.add(
                User(
                    tenant_id=tenant,
                    user_id=user_id,
                    username=user_id,
                    role="admin",
                    password_hash=str(uuid4()),
                    active=True,
                )
            )
        session.flush()
        for tenant, user_id in (("a", "manager"), ("b", "manager")):
            session.add(
                AuthSession(
                    tenant_id=tenant,
                    session_id="manager-session",
                    user_id=user_id,
                    expires_at=now + timedelta(hours=1),
                    revoked=False,
                )
            )
        session.commit()

    with Session(engine) as session:
        legal_revision = create_legal_revision(session, root, metadata)
        publication = legal_management.publish(
            session, legal_principal(), publish_request(legal_revision.revision_id)
        )
        publication_id = publication.publication_id
    admin = Principal("a", "manager", "manager", Role.ADMIN, "manager-session")
    other_admin = Principal("b", "manager", "manager", Role.ADMIN, "manager-session")
    runtime_policy = ModelPolicy(
        profile="task0011-offline-verification",
        timeout_seconds=90,
        max_attempts=2,
        max_input_tokens=64_000,
        max_output_tokens=8_000,
        temperature=0,
        data_policy=DataPolicy.CONFIDENTIAL,
    )
    yield engine, admin, other_admin, publication_id, runtime_policy


def make_draft(session, *, principal, state, publication, policy, runtime_policy, skills, reason):
    return configurations.create_draft(
        session,
        principal,
        request_id=str(uuid4()),
        expected_sequence=state.sequence,
        expected_draft_sequence=state.draft_sequence,
        expected_legal_publication_id=publication,
        skill_ids=skills,
        model_policy=policy,
        runtime_policy=runtime_policy,
        reason=reason,
    )


def test_releases_publish_rollback_and_preserve_frozen_history(configuration_system):
    engine, admin, _, publication, runtime_policy = configuration_system
    with Session(engine) as session:
        first = make_draft(
            session,
            principal=admin,
            state=type("Initial", (), {"sequence": 0, "draft_sequence": 0})(),
            publication=publication,
            policy=runtime_policy,
            runtime_policy=runtime_policy,
            skills=("qualification_review", "contract_review"),
            reason="第一版规则组合",
        )
        first_hash = first.snapshot_hash
        event = configurations.publish_draft(
            session,
            admin,
            revision_id=first.revision_id,
            expected_sequence=1,
            request_id=str(uuid4()),
            reason="启用第一版",
        )
        assert event.operation == "publish"
        first_snapshot = dict(first.snapshot)

        state = session.get(ReviewConfigurationState, "a")
        assert state is not None
        narrowed_policy = ModelPolicy(
            profile=runtime_policy.profile,
            timeout_seconds=45,
            max_attempts=1,
            max_input_tokens=32_000,
            max_output_tokens=4_000,
            temperature=0,
            data_policy=runtime_policy.data_policy,
        )
        second = make_draft(
            session,
            principal=admin,
            state=state,
            publication=publication,
            policy=narrowed_policy,
            runtime_policy=runtime_policy,
            skills=("qualification_review",),
            reason="缩小执行资源上限",
        )
        configurations.publish_draft(
            session,
            admin,
            revision_id=second.revision_id,
            expected_sequence=3,
            request_id=str(uuid4()),
            reason="启用第二版",
        )

        frozen_policy = configurations.verify_frozen_configuration(
            session,
            admin,
            revision_id=first.revision_id,
            snapshot_hash=first_hash,
            snapshot=first_snapshot,
            runtime_policy=runtime_policy,
        )
        assert frozen_policy == runtime_policy
        assert first.snapshot_hash == first_hash
        assert first.snapshot["skill_ids"] == ["contract_review", "qualification_review"]

        configurations.rollback(
            session,
            admin,
            revision_id=first.revision_id,
            expected_sequence=4,
            request_id=str(uuid4()),
            reason="恢复第一版",
        )
        active_id, snapshot_hash, active_snapshot = configurations.resolve_execution_configuration(
            session, admin, runtime_policy
        )
        assert active_id == first.revision_id
        assert snapshot_hash == first_hash
        assert active_snapshot == first_snapshot
        assert first.snapshot_hash == first_hash

        configurations.deactivate(
            session,
            admin,
            expected_sequence=5,
            request_id=str(uuid4()),
            reason="停用配置",
        )
        fallback_id, _, fallback = configurations.resolve_execution_configuration(
            session, admin, runtime_policy
        )
        assert fallback_id is None
        assert len(fallback["skill_ids"]) == 5

        history = configurations.list_configurations(session, admin)
        assert [item["operation"] for item in history["events"]] == [
            "disable",
            "rollback",
            "publish",
            "draft",
            "publish",
            "draft",
        ]
        assert all(item["actor_id"] == admin.user_id for item in history["events"])
        assert (
            session.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == admin.tenant_id,
                    AuditEvent.action == "configuration.rollback",
                )
            )
            is not None
        )


def test_config_management_enforces_admin_tenant_hashes_and_append_only(configuration_system):
    engine, admin, other_admin, publication, runtime_policy = configuration_system
    reviewer = legal_principal()
    with Session(engine) as session:
        with pytest.raises(PermissionError, match="requires admin"):
            configurations.list_configurations(session, reviewer)

    with Session(engine) as session:
        state = configurations.list_configurations(session, other_admin)
        assert state["items"] == []
        assert configurations.configuration_catalog(session, admin, runtime_policy)["skills"]
        revision = make_draft(
            session,
            principal=admin,
            state=type("Initial", (), {"sequence": 0, "draft_sequence": 0})(),
            publication=publication,
            policy=runtime_policy,
            runtime_policy=runtime_policy,
            skills=("qualification_review",),
            reason="只用于检查历史不可覆盖",
        )
        assert len(revision.snapshot_hash) == 64
        with pytest.raises(IntegrityError):
            session.execute(
                update(ReviewConfigurationRevision)
                .where(
                    ReviewConfigurationRevision.tenant_id == admin.tenant_id,
                    ReviewConfigurationRevision.revision_id == revision.revision_id,
                )
                .values(reason="silent overwrite")
            )
        session.rollback()

    with Session(engine) as session:
        assert (
            session.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == admin.tenant_id,
                    AuditEvent.action == "configuration.operation_denied",
                )
            )
            is not None
        )


def test_model_configuration_never_accepts_secrets_or_exceeds_runtime_guard(
    configuration_system,
):
    _, _, _, _, runtime_policy = configuration_system
    data = ModelPolicySnapshot.from_policy(runtime_policy).model_dump(mode="json")
    with pytest.raises(ValidationError):
        ModelPolicySnapshot.model_validate({**data, "api" + "_key": "never-accepted"})

    excessive = ModelPolicy(
        profile=runtime_policy.profile,
        timeout_seconds=runtime_policy.timeout_seconds + 1,
        max_attempts=runtime_policy.max_attempts,
        max_input_tokens=runtime_policy.max_input_tokens,
        max_output_tokens=runtime_policy.max_output_tokens,
        temperature=runtime_policy.temperature,
        data_policy=runtime_policy.data_policy,
    )
    with pytest.raises(ValueError, match="timeout"):
        configurations._runtime_limits(runtime_policy, excessive)
