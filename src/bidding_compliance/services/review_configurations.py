"""Tenant-admin lifecycle for immutable references to existing review capabilities."""

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.domain.review_configuration import (
    ModelPolicySnapshot,
    ReviewConfigurationSnapshot,
)
from bidding_compliance.domain.rules.engine import SKILLS, ruleset_sha256
from bidding_compliance.domain.rules.models import SkillId
from bidding_compliance.legal.hashing import canonical_hash
from bidding_compliance.model_gateway.contracts import ModelPolicy
from bidding_compliance.persistence.models import (
    AuditEvent,
    LegalCorpusState,
    ReviewConfigurationEvent,
    ReviewConfigurationRevision,
    ReviewConfigurationState,
)
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.legal_management import read_publication

Operation = Literal["draft", "publish", "disable", "rollback"]


def _require_admin(session: Session, principal: Principal) -> None:
    require_identity(session, principal)
    if principal.role is not Role.ADMIN:
        audit(session, principal.tenant_id, principal.user_id, "configuration.operation_denied")
        session.commit()
        raise PermissionError("configuration management requires admin role")


def _state(
    session: Session, principal: Principal, *, create: bool
) -> ReviewConfigurationState | None:
    current = session.get(ReviewConfigurationState, principal.tenant_id, populate_existing=True)
    if current is None and create:
        current = ReviewConfigurationState(
            tenant_id=principal.tenant_id,
            sequence=0,
            active_revision_id=None,
            draft_sequence=0,
            draft_revision_id=None,
        )
        session.add(current)
        session.flush()
    return current


def _runtime_limits(base: ModelPolicy, proposed: ModelPolicy) -> None:
    if proposed.profile != base.profile or proposed.data_policy != base.data_policy:
        raise ValueError("profile and data policy are fixed by the authorized runtime gateway")
    if proposed.timeout_seconds > base.timeout_seconds:
        raise ValueError("configuration cannot increase the runtime timeout ceiling")
    if proposed.max_attempts > base.max_attempts:
        raise ValueError("configuration cannot increase the runtime retry ceiling")
    if proposed.temperature > base.temperature:
        raise ValueError("configuration cannot increase the runtime temperature ceiling")
    for proposed_value, runtime_value, name in (
        (proposed.max_input_tokens, base.max_input_tokens, "input token"),
        (proposed.max_output_tokens, base.max_output_tokens, "output token"),
    ):
        if runtime_value is not None and (proposed_value is None or proposed_value > runtime_value):
            raise ValueError(f"configuration cannot increase the runtime {name} ceiling")


def _build_snapshot(
    session: Session,
    principal: Principal,
    *,
    legal_publication_id: str,
    skill_ids: tuple[str, ...],
    model_policy: ModelPolicy,
    runtime_policy: ModelPolicy,
) -> dict[str, Any]:
    if not skill_ids or len(skill_ids) != len(set(skill_ids)):
        raise ValueError("select one or more unique installed skills")
    unknown = set(skill_ids) - set(SKILLS)
    if unknown:
        raise ValueError("configuration references an unavailable skill")
    _runtime_limits(runtime_policy, model_policy)
    legal_state = session.get(LegalCorpusState, 1, populate_existing=True)
    if legal_state is None or legal_state.publication_id != legal_publication_id:
        raise FileExistsError("legal publication changed; create a new configuration draft")
    publication, _ = read_publication(session, principal, legal_publication_id)
    if publication.publication_id != legal_publication_id or not publication.revision_id:
        raise ValueError("configuration requires an enabled legal publication")
    ordered = cast(tuple[SkillId, ...], tuple(sorted(skill_ids)))
    skill_versions: dict[str, str] = {
        skill_id: str(SKILLS[skill_id].DEFINITION.skill_version) for skill_id in ordered
    }
    rule_versions: dict[str, str] = {
        reference.rule_id: str(reference.rule_version)
        for skill_id in ordered
        for reference in SKILLS[skill_id].DEFINITION.rules
    }
    snapshot = ReviewConfigurationSnapshot(
        legal_publication_id=legal_publication_id,
        skill_ids=ordered,
        skill_versions=skill_versions,
        rule_versions=rule_versions,
        ruleset_sha256=ruleset_sha256(ordered),
        model_policy=ModelPolicySnapshot.from_policy(model_policy),
    )
    return snapshot.model_dump(mode="json")


def configuration_catalog(
    session: Session, principal: Principal, runtime_policy: ModelPolicy
) -> dict[str, Any]:
    _require_admin(session, principal)
    return {
        "skills": [
            {
                "skill_id": module.DEFINITION.skill_id,
                "skill_version": module.DEFINITION.skill_version,
                "category": module.DEFINITION.category,
                "rule_versions": {
                    reference.rule_id: reference.rule_version
                    for reference in module.DEFINITION.rules
                },
            }
            for module in SKILLS.values()
        ],
        "model_policy": ModelPolicySnapshot.from_policy(runtime_policy).model_dump(mode="json"),
        "model_configuration_boundary": (
            "provider routing, online authorization, and credentials are controlled "
            "outside this release"
        ),
    }


def _idempotent_event(
    session: Session,
    principal: Principal,
    request_id: str,
    request_hash: str,
) -> ReviewConfigurationEvent | None:
    event = session.scalar(
        select(ReviewConfigurationEvent).where(
            ReviewConfigurationEvent.tenant_id == principal.tenant_id,
            ReviewConfigurationEvent.actor_id == principal.user_id,
            ReviewConfigurationEvent.request_id == request_id,
        )
    )
    if event and event.request_hash != request_hash:
        raise FileExistsError("configuration idempotency key was reused with different content")
    return event


def create_draft(
    session: Session,
    principal: Principal,
    *,
    request_id: str,
    expected_sequence: int,
    expected_draft_sequence: int,
    expected_legal_publication_id: str,
    skill_ids: tuple[str, ...],
    model_policy: ModelPolicy,
    runtime_policy: ModelPolicy,
    reason: str,
) -> ReviewConfigurationRevision:
    _require_admin(session, principal)
    if not 16 <= len(request_id) <= 64:
        raise ValueError("configuration request id length is invalid")
    snapshot = _build_snapshot(
        session,
        principal,
        legal_publication_id=expected_legal_publication_id,
        skill_ids=skill_ids,
        model_policy=model_policy,
        runtime_policy=runtime_policy,
    )
    snapshot_hash = canonical_hash(snapshot)
    request_hash = canonical_hash(
        {
            "expected_sequence": expected_sequence,
            "expected_draft_sequence": expected_draft_sequence,
            "snapshot_hash": snapshot_hash,
            "reason": reason,
        }
    )
    existing = session.scalar(
        select(ReviewConfigurationRevision).where(
            ReviewConfigurationRevision.tenant_id == principal.tenant_id,
            ReviewConfigurationRevision.actor_id == principal.user_id,
            ReviewConfigurationRevision.request_id == request_id,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise FileExistsError("configuration idempotency key was reused with different content")
        return existing
    state = _state(session, principal, create=True)
    assert state is not None
    if state.sequence != expected_sequence or state.draft_sequence != expected_draft_sequence:
        raise FileExistsError("stale configuration state")
    now = datetime.now(UTC)
    revision = ReviewConfigurationRevision(
        tenant_id=principal.tenant_id,
        revision_id=str(uuid4()),
        revision_sequence=state.draft_sequence + 1,
        parent_revision_id=state.draft_revision_id,
        actor_id=principal.user_id,
        request_id=request_id,
        request_hash=request_hash,
        snapshot=snapshot,
        snapshot_hash=snapshot_hash,
        reason=reason,
        created_at=now,
    )
    event = ReviewConfigurationEvent(
        tenant_id=principal.tenant_id,
        event_id=str(uuid4()),
        sequence=state.sequence + 1,
        operation="draft",
        revision_id=revision.revision_id,
        previous_active_id=state.active_revision_id,
        active_revision_id=state.active_revision_id,
        actor_id=principal.user_id,
        request_id=request_id,
        request_hash=request_hash,
        expected_sequence=state.sequence,
        reason=reason,
        created_at=now,
    )
    try:
        session.add(revision)
        session.flush()
        session.add(event)
        session.flush()
        changed = cast(
            CursorResult[Any],
            session.execute(
                update(ReviewConfigurationState)
                .where(
                    ReviewConfigurationState.tenant_id == principal.tenant_id,
                    ReviewConfigurationState.sequence == expected_sequence,
                    ReviewConfigurationState.draft_sequence == expected_draft_sequence,
                )
                .values(
                    sequence=expected_sequence + 1,
                    draft_sequence=expected_draft_sequence + 1,
                    draft_revision_id=revision.revision_id,
                )
            ),
        ).rowcount
        if changed != 1:
            raise FileExistsError("concurrent configuration draft conflict")
        audit(
            session,
            principal.tenant_id,
            principal.user_id,
            "configuration.draft",
            revision.revision_id,
        )
        session.commit()
        return revision
    except IntegrityError as exc:
        session.rollback()
        duplicate = session.scalar(
            select(ReviewConfigurationRevision).where(
                ReviewConfigurationRevision.tenant_id == principal.tenant_id,
                ReviewConfigurationRevision.actor_id == principal.user_id,
                ReviewConfigurationRevision.request_id == request_id,
            )
        )
        if duplicate and duplicate.request_hash == request_hash:
            return duplicate
        raise FileExistsError("concurrent configuration draft conflict") from exc
    except Exception:
        session.rollback()
        raise


def _transition(
    session: Session,
    principal: Principal,
    *,
    operation: Operation,
    request_id: str,
    expected_sequence: int,
    reason: str,
    revision_id: str | None = None,
) -> ReviewConfigurationEvent:
    _require_admin(session, principal)
    request_hash = canonical_hash(
        {
            "operation": operation,
            "expected_sequence": expected_sequence,
            "revision_id": revision_id,
            "reason": reason,
        }
    )
    duplicate = _idempotent_event(session, principal, request_id, request_hash)
    if duplicate:
        return duplicate
    state = _state(session, principal, create=False)
    if state is None or state.sequence != expected_sequence:
        raise FileExistsError("stale configuration state")
    current_active = state.active_revision_id
    current_draft = state.draft_revision_id

    if operation == "publish":
        if current_draft is None or revision_id != current_draft:
            raise FileExistsError("the requested revision is not the current draft")
        revision = session.get(
            ReviewConfigurationRevision,
            (principal.tenant_id, revision_id),
            populate_existing=True,
        )
        if revision is None or canonical_hash(revision.snapshot) != revision.snapshot_hash:
            raise LookupError("configuration draft is unavailable or changed")
        draft = ReviewConfigurationSnapshot.model_validate(revision.snapshot)
        legal_state = session.get(LegalCorpusState, 1, populate_existing=True)
        if legal_state is None or legal_state.publication_id != draft.legal_publication_id:
            raise FileExistsError("legal publication changed; create a new configuration draft")
        active_id = revision_id
    elif operation == "disable":
        if current_active is None:
            raise ValueError("no active configuration to deactivate")
        if revision_id is not None:
            raise ValueError("deactivate does not accept a revision id")
        active_id = None
    else:
        if revision_id is None:
            raise ValueError("rollback requires a target revision id")
        revision = session.get(
            ReviewConfigurationRevision,
            (principal.tenant_id, revision_id),
            populate_existing=True,
        )
        if revision is None or canonical_hash(revision.snapshot) != revision.snapshot_hash:
            raise LookupError("configuration rollback target is unavailable or changed")
        prior = session.scalar(
            select(ReviewConfigurationEvent.event_id).where(
                ReviewConfigurationEvent.tenant_id == principal.tenant_id,
                ReviewConfigurationEvent.revision_id == revision_id,
                ReviewConfigurationEvent.operation.in_(("publish", "rollback")),
            )
        )
        if prior is None:
            raise ValueError("rollback target was never published")
        target = ReviewConfigurationSnapshot.model_validate(revision.snapshot)
        legal_state = session.get(LegalCorpusState, 1, populate_existing=True)
        if legal_state is None or legal_state.publication_id != target.legal_publication_id:
            raise FileExistsError("rollback target pins a different legal publication")
        active_id = revision_id

    now = datetime.now(UTC)
    event = ReviewConfigurationEvent(
        tenant_id=principal.tenant_id,
        event_id=str(uuid4()),
        sequence=state.sequence + 1,
        operation=operation,
        revision_id=revision_id,
        previous_active_id=current_active,
        active_revision_id=active_id,
        actor_id=principal.user_id,
        request_id=request_id,
        request_hash=request_hash,
        expected_sequence=state.sequence,
        reason=reason,
        created_at=now,
    )
    try:
        session.add(event)
        session.flush()
        values: dict[str, Any] = {
            "sequence": expected_sequence + 1,
            "active_revision_id": active_id,
        }
        if operation == "publish":
            values["draft_revision_id"] = None
        changed = cast(
            CursorResult[Any],
            session.execute(
                update(ReviewConfigurationState)
                .where(
                    ReviewConfigurationState.tenant_id == principal.tenant_id,
                    ReviewConfigurationState.sequence == expected_sequence,
                    ReviewConfigurationState.active_revision_id.is_(current_active)
                    if current_active is None
                    else ReviewConfigurationState.active_revision_id == current_active,
                    ReviewConfigurationState.draft_revision_id.is_(current_draft)
                    if current_draft is None
                    else ReviewConfigurationState.draft_revision_id == current_draft,
                )
                .values(**values)
            ),
        ).rowcount
        if changed != 1:
            raise FileExistsError("concurrent configuration lifecycle conflict")
        audit(
            session,
            principal.tenant_id,
            principal.user_id,
            "configuration." + operation,
            revision_id or current_active,
        )
        session.commit()
        return event
    except Exception:
        session.rollback()
        raise


def publish_draft(
    session: Session,
    principal: Principal,
    *,
    revision_id: str,
    expected_sequence: int,
    request_id: str,
    reason: str,
) -> ReviewConfigurationEvent:
    return _transition(
        session,
        principal,
        operation="publish",
        revision_id=revision_id,
        expected_sequence=expected_sequence,
        request_id=request_id,
        reason=reason,
    )


def deactivate(
    session: Session, principal: Principal, *, expected_sequence: int, request_id: str, reason: str
) -> ReviewConfigurationEvent:
    return _transition(
        session,
        principal,
        operation="disable",
        revision_id=None,
        expected_sequence=expected_sequence,
        request_id=request_id,
        reason=reason,
    )


def rollback(
    session: Session,
    principal: Principal,
    *,
    revision_id: str,
    expected_sequence: int,
    request_id: str,
    reason: str,
) -> ReviewConfigurationEvent:
    return _transition(
        session,
        principal,
        operation="rollback",
        revision_id=revision_id,
        expected_sequence=expected_sequence,
        request_id=request_id,
        reason=reason,
    )


def _validate_snapshot(
    session: Session,
    principal: Principal,
    snapshot: dict[str, Any],
    runtime_policy: ModelPolicy,
    *,
    require_current_legal: bool,
) -> ReviewConfigurationSnapshot:
    parsed = ReviewConfigurationSnapshot.model_validate(snapshot)
    if parsed.ruleset_sha256 != ruleset_sha256(parsed.skill_ids):
        raise ValueError("configured rule and skill implementation changed")
    for skill_id in parsed.skill_ids:
        if parsed.skill_versions[skill_id] != SKILLS[skill_id].DEFINITION.skill_version:
            raise ValueError("configured skill version is not installed")
    known_rule_versions = {
        reference.rule_id: reference.rule_version
        for skill_id in parsed.skill_ids
        for reference in SKILLS[skill_id].DEFINITION.rules
    }
    if parsed.rule_versions != known_rule_versions:
        raise ValueError("configured rule version map differs from installed rules")
    _runtime_limits(runtime_policy, parsed.model_policy.to_policy())
    if require_current_legal:
        state = session.get(LegalCorpusState, 1, populate_existing=True)
        if state is None or state.publication_id != parsed.legal_publication_id:
            raise FileExistsError("active configuration pins a superseded legal publication")
    read_publication(session, principal, parsed.legal_publication_id)
    return parsed


def resolve_execution_configuration(
    session: Session, principal: Principal, runtime_policy: ModelPolicy
) -> tuple[str | None, str, dict[str, Any]]:
    """Resolve the active immutable tenant release or a named code-default snapshot."""
    require_identity(session, principal)
    state = _state(session, principal, create=False)
    if state is not None and state.active_revision_id is not None:
        revision = session.get(
            ReviewConfigurationRevision,
            (principal.tenant_id, state.active_revision_id),
            populate_existing=True,
        )
        if revision is None or canonical_hash(revision.snapshot) != revision.snapshot_hash:
            raise ValueError("active review configuration is unavailable or changed")
        parsed = _validate_snapshot(
            session, principal, revision.snapshot, runtime_policy, require_current_legal=True
        )
        return revision.revision_id, revision.snapshot_hash, parsed.model_dump(mode="json")

    legal_state = session.get(LegalCorpusState, 1, populate_existing=True)
    legal_publication_id = legal_state.publication_id if legal_state else None
    if not legal_publication_id:
        raise LookupError("no active legal publication")
    snapshot = _build_snapshot(
        session,
        principal,
        legal_publication_id=legal_publication_id,
        skill_ids=tuple(sorted(SKILLS)),
        model_policy=runtime_policy,
        runtime_policy=runtime_policy,
    )
    return None, canonical_hash(snapshot), snapshot


def verify_frozen_configuration(
    session: Session,
    principal: Principal,
    *,
    revision_id: str | None,
    snapshot_hash: str,
    snapshot: dict[str, Any],
    runtime_policy: ModelPolicy,
) -> ModelPolicy:
    """Verify the immutable release without consulting today's active pointer."""
    if canonical_hash(snapshot) != snapshot_hash:
        raise ValueError("frozen configuration hash mismatch")
    if revision_id is None:
        parsed = _validate_snapshot(
            session, principal, snapshot, runtime_policy, require_current_legal=False
        )
        return parsed.model_policy.to_policy()
    revision = session.get(
        ReviewConfigurationRevision,
        (principal.tenant_id, revision_id),
        populate_existing=True,
    )
    if revision is None or revision.snapshot_hash != snapshot_hash or revision.snapshot != snapshot:
        raise ValueError("frozen configuration release is unavailable or changed")
    published = session.scalar(
        select(ReviewConfigurationEvent.event_id).where(
            ReviewConfigurationEvent.tenant_id == principal.tenant_id,
            ReviewConfigurationEvent.revision_id == revision_id,
            ReviewConfigurationEvent.operation.in_(("publish", "rollback")),
        )
    )
    if published is None:
        raise ValueError("frozen configuration was never published")
    parsed = _validate_snapshot(
        session, principal, snapshot, runtime_policy, require_current_legal=False
    )
    return parsed.model_policy.to_policy()


def list_configurations(
    session: Session, principal: Principal, *, limit: int = 50
) -> dict[str, Any]:
    _require_admin(session, principal)
    state = _state(session, principal, create=False)
    revisions = list(
        session.scalars(
            select(ReviewConfigurationRevision)
            .where(ReviewConfigurationRevision.tenant_id == principal.tenant_id)
            .order_by(ReviewConfigurationRevision.revision_sequence.desc())
            .limit(limit)
        )
    )
    events = list(
        session.scalars(
            select(ReviewConfigurationEvent)
            .where(ReviewConfigurationEvent.tenant_id == principal.tenant_id)
            .order_by(ReviewConfigurationEvent.sequence.desc())
            .limit(limit)
        )
    )
    items = []
    for revision in revisions:
        status = (
            "active"
            if state and state.active_revision_id == revision.revision_id
            else "draft"
            if state and state.draft_revision_id == revision.revision_id
            else "inactive"
        )
        items.append(
            {
                "revision_id": revision.revision_id,
                "revision_sequence": revision.revision_sequence,
                "parent_revision_id": revision.parent_revision_id,
                "snapshot": revision.snapshot,
                "snapshot_hash": revision.snapshot_hash,
                "reason": revision.reason,
                "actor_id": revision.actor_id,
                "created_at": revision.created_at,
                "status": status,
            }
        )
    return {
        "sequence": state.sequence if state else 0,
        "draft_sequence": state.draft_sequence if state else 0,
        "active_revision_id": state.active_revision_id if state else None,
        "draft_revision_id": state.draft_revision_id if state else None,
        "items": items,
        "events": [
            {
                "event_id": item.event_id,
                "sequence": item.sequence,
                "operation": item.operation,
                "revision_id": item.revision_id,
                "previous_active_id": item.previous_active_id,
                "active_revision_id": item.active_revision_id,
                "actor_id": item.actor_id,
                "request_id": item.request_id,
                "reason": item.reason,
                "created_at": item.created_at,
            }
            for item in events
        ],
    }


def audit_events_for_config(session: Session, tenant_id: str, limit: int = 20) -> list[AuditEvent]:
    return list(
        session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action.like("configuration.%"),
            )
            .order_by(AuditEvent.occurred_at.desc())
            .limit(limit)
        )
    )
