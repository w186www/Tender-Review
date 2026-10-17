"""Product-mode tenant policy, per-file external authorization and egress gate.

The product authority is PostgreSQL only. Every approval/revocation is written with its
tenant audit event in one transaction; the egress gate re-reads the database before each
freeze and each outbound payload, so a revocation applies to the next request. A request
that was already sent cannot be recalled; that boundary is documented instead of hidden.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from bidding_compliance.core.dates import as_utc
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.persistence.database import require_runtime_role, set_tenant
from bidding_compliance.persistence.models import (
    Document,
    DocumentExternalAuthorization,
    ModelBudgetAccount,
    ModelExecutionPolicy,
    User,
)
from bidding_compliance.services.documents import find_document
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity

PURPOSE_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,63}")
PROVIDER_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{1,63}")
DEFAULT_AUTHORIZATION_SECONDS = 86_400
MAX_REASON_CHARACTERS = 500


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    tenant_id: str
    policy_version: int
    allowed_providers: frozenset[str]
    allowed_purposes: frozenset[str]
    budget_cny: Decimal
    max_call_cny: Decimal
    max_embedding_batch_cny: Decimal
    max_authorization_ttl_seconds: int
    active: bool


def _policy(row: ModelExecutionPolicy) -> ExecutionPolicy:
    return ExecutionPolicy(
        tenant_id=row.tenant_id,
        policy_version=row.policy_version,
        allowed_providers=frozenset(str(item) for item in row.allowed_providers),
        allowed_purposes=frozenset(str(item) for item in row.allowed_purposes),
        budget_cny=Decimal(row.budget_cny),
        max_call_cny=Decimal(row.max_call_cny),
        max_embedding_batch_cny=Decimal(row.max_embedding_batch_cny),
        max_authorization_ttl_seconds=row.max_authorization_ttl_seconds,
        active=row.active,
    )


def require_execution_policy(
    session: Session, tenant_id: str, *, provider: str, purpose: str
) -> ExecutionPolicy:
    """Load the tenant policy and fail closed unless it allows this exact egress."""
    set_tenant(session, tenant_id)
    row = session.get(ModelExecutionPolicy, tenant_id, populate_existing=True)
    if row is None:
        raise PermissionError("tenant execution policy is not configured")
    policy = _policy(row)
    if not policy.active:
        raise PermissionError("tenant execution policy is not active")
    if provider not in policy.allowed_providers:
        raise PermissionError("provider is not allowed by the tenant execution policy")
    if purpose not in policy.allowed_purposes:
        raise PermissionError("purpose is not allowed by the tenant execution policy")
    return policy


def set_execution_policy(
    session: Session,
    *,
    tenant_id: str,
    actor_id: str,
    allowed_providers: Sequence[str],
    allowed_purposes: Sequence[str],
    budget_cny: Decimal,
    max_call_cny: Decimal,
    max_embedding_batch_cny: Decimal,
    max_authorization_ttl_seconds: int,
    active: bool = True,
    budget_authorization_id: str | None = None,
) -> ModelExecutionPolicy:
    """Provision or update one tenant policy and its single budget account atomically."""
    set_tenant(session, tenant_id)
    user = session.get(User, (tenant_id, actor_id), populate_existing=True)
    if user is None or not user.active or user.role != Role.ADMIN.value:
        raise PermissionError("execution policy management requires an active admin")
    providers = sorted({_validate_provider(item) for item in allowed_providers})
    purposes = sorted({_validate_purpose(item) for item in allowed_purposes})
    if not providers or not purposes:
        raise ValueError("at least one provider and one purpose are required")
    if (
        not budget_cny.is_finite()
        or budget_cny < 0
        or not max_call_cny.is_finite()
        or max_call_cny <= 0
        or not max_embedding_batch_cny.is_finite()
        or max_embedding_batch_cny <= 0
        or not 60 <= max_authorization_ttl_seconds <= 2_592_000
    ):
        raise ValueError("execution policy limits are invalid")
    now = datetime.now(UTC)
    authorization_identity = budget_authorization_id or f"product:{tenant_id}"
    policy = session.get(ModelExecutionPolicy, tenant_id, populate_existing=True)
    account = session.get(
        ModelBudgetAccount,
        (tenant_id, authorization_identity),
        populate_existing=True,
    )
    if account is not None:
        if budget_cny < Decimal(account.reserved_cny) + Decimal(account.spent_cny):
            raise ValueError("budget cannot be reduced below reserved and spent funds")
        account.limit_cny = budget_cny
        account.updated_at = now
    else:
        account = ModelBudgetAccount(
            tenant_id=tenant_id,
            authorization_id=authorization_identity,
            limit_cny=budget_cny,
            reserved_cny=Decimal(0),
            spent_cny=Decimal(0),
            updated_at=now,
        )
        session.add(account)
    if policy is None:
        policy = ModelExecutionPolicy(
            tenant_id=tenant_id,
            policy_version=1,
            allowed_providers=providers,
            allowed_purposes=purposes,
            budget_cny=budget_cny,
            max_call_cny=max_call_cny,
            max_embedding_batch_cny=max_embedding_batch_cny,
            max_authorization_ttl_seconds=max_authorization_ttl_seconds,
            active=active,
            updated_by=actor_id,
            updated_at=now,
        )
        session.add(policy)
    else:
        policy.policy_version += 1
        policy.allowed_providers = providers
        policy.allowed_purposes = purposes
        policy.budget_cny = budget_cny
        policy.max_call_cny = max_call_cny
        policy.max_embedding_batch_cny = max_embedding_batch_cny
        policy.max_authorization_ttl_seconds = max_authorization_ttl_seconds
        policy.active = active
        policy.updated_by = actor_id
        policy.updated_at = now
    try:
        session.flush()
        audit(
            session,
            tenant_id,
            actor_id,
            "model_execution_policy.updated",
            tenant_id,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return policy


def _bounded_reason(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_REASON_CHARACTERS
        or any(character < " " for character in value)
    ):
        raise ValueError("an authorization reason is required and must be a single bounded line")
    return value


def _validate_purpose(value: str) -> str:
    if not isinstance(value, str) or not PURPOSE_PATTERN.fullmatch(value):
        raise ValueError("purpose is not a bounded execution purpose")
    return value


def _validate_provider(value: str) -> str:
    if not isinstance(value, str) or not PROVIDER_PATTERN.fullmatch(value):
        raise ValueError("provider is not a bounded provider identity")
    return value


def _active_row(
    session: Session,
    *,
    tenant_id: str,
    project_id: str,
    document_id: str,
    document_sha256: str,
    parse_version: int,
    purpose: str,
    provider: str,
    for_update: bool = False,
) -> DocumentExternalAuthorization | None:
    statement = select(DocumentExternalAuthorization).where(
        DocumentExternalAuthorization.tenant_id == tenant_id,
        DocumentExternalAuthorization.project_id == project_id,
        DocumentExternalAuthorization.document_id == document_id,
        DocumentExternalAuthorization.document_sha256 == document_sha256,
        DocumentExternalAuthorization.parse_version == parse_version,
        DocumentExternalAuthorization.purpose == purpose,
        DocumentExternalAuthorization.provider == provider,
        DocumentExternalAuthorization.state == "active",
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def approve_document(
    session: Session,
    principal: Principal,
    project_id: str,
    document_id: str,
    *,
    reason: str,
    purpose: str,
    provider: str,
    expires_at: datetime | None = None,
) -> DocumentExternalAuthorization:
    """Record one version-bound approval and its audit event in one transaction."""
    require_identity(session, principal)
    if principal.role is not Role.REVIEWER:
        audit(
            session,
            principal.tenant_id,
            principal.user_id,
            "document.external_authorization_denied",
            document_id,
        )
        session.commit()
        raise PermissionError("external authorization requires reviewer role")
    reason = _bounded_reason(reason)
    purpose = _validate_purpose(purpose)
    provider = _validate_provider(provider)
    document = find_document(session, principal, project_id, document_id)
    if document.parse_version < 1:
        raise ValueError("external authorization requires a parsed document version")
    policy = require_execution_policy(
        session, principal.tenant_id, provider=provider, purpose=purpose
    )
    now = datetime.now(UTC)
    if expires_at is None:
        seconds = min(policy.max_authorization_ttl_seconds, DEFAULT_AUTHORIZATION_SECONDS)
        expiry = now + timedelta(seconds=seconds)
    else:
        expiry = as_utc(expires_at)
        maximum = now + timedelta(seconds=policy.max_authorization_ttl_seconds)
        if expiry <= now or expiry > maximum:
            raise ValueError("authorization expiry is outside the tenant policy lifetime")
    existing = _active_row(
        session,
        tenant_id=principal.tenant_id,
        project_id=project_id,
        document_id=document.document_id,
        document_sha256=document.sha256,
        parse_version=document.parse_version,
        purpose=purpose,
        provider=provider,
        for_update=True,
    )
    if existing is not None:
        # One active approval per document version/purpose/provider. A repeated request
        # returns the already-recorded row instead of writing a second authorization or
        # audit event; changing the terms requires an explicit revoke then approve.
        return existing
    row = DocumentExternalAuthorization(
        tenant_id=principal.tenant_id,
        authorization_id=uuid4().hex,
        project_id=project_id,
        document_id=document.document_id,
        document_sha256=document.sha256,
        parse_version=document.parse_version,
        purpose=purpose,
        provider=provider,
        policy_version=policy.policy_version,
        state="active",
        reason=reason,
        approved_by=principal.user_id,
        approved_at=now,
        expires_at=expiry,
        revoked_by=None,
        revoked_at=None,
        revocation_reason=None,
        source="api",
        source_record_id=None,
    )
    try:
        session.add(row)
        session.flush()
        audit(
            session,
            principal.tenant_id,
            principal.user_id,
            "document.external_authorization_approved",
            document.document_id,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        set_tenant(session, principal.tenant_id)
        existing = _active_row(
            session,
            tenant_id=principal.tenant_id,
            project_id=project_id,
            document_id=document.document_id,
            document_sha256=document.sha256,
            parse_version=document.parse_version,
            purpose=purpose,
            provider=provider,
        )
        if existing is not None:
            return existing
        raise FileExistsError("concurrent authorization conflicted") from exc
    except Exception:
        session.rollback()
        raise
    return row


def revoke_document(
    session: Session,
    principal: Principal,
    project_id: str,
    document_id: str,
    *,
    reason: str,
    purpose: str,
    provider: str,
) -> DocumentExternalAuthorization:
    """Revoke the active approval for one version; the next egress check sees it."""
    require_identity(session, principal)
    if principal.role is not Role.REVIEWER:
        audit(
            session,
            principal.tenant_id,
            principal.user_id,
            "document.external_authorization_revoke_denied",
            document_id,
        )
        session.commit()
        raise PermissionError("external authorization revocation requires reviewer role")
    reason = _bounded_reason(reason)
    purpose = _validate_purpose(purpose)
    provider = _validate_provider(provider)
    document = find_document(session, principal, project_id, document_id)
    now = datetime.now(UTC)
    row = _active_row(
        session,
        tenant_id=principal.tenant_id,
        project_id=project_id,
        document_id=document.document_id,
        document_sha256=document.sha256,
        parse_version=document.parse_version,
        purpose=purpose,
        provider=provider,
        for_update=True,
    )
    if row is None:
        previous = session.scalar(
            select(DocumentExternalAuthorization)
            .where(
                DocumentExternalAuthorization.tenant_id == principal.tenant_id,
                DocumentExternalAuthorization.project_id == project_id,
                DocumentExternalAuthorization.document_id == document.document_id,
                DocumentExternalAuthorization.document_sha256 == document.sha256,
                DocumentExternalAuthorization.parse_version == document.parse_version,
                DocumentExternalAuthorization.purpose == purpose,
                DocumentExternalAuthorization.provider == provider,
                DocumentExternalAuthorization.state == "revoked",
            )
            .order_by(DocumentExternalAuthorization.revoked_at.desc())
        )
        if previous is not None:
            return previous
        raise LookupError("no active external authorization exists")
    try:
        row.state = "revoked"
        row.revoked_by = principal.user_id
        row.revoked_at = now
        row.revocation_reason = reason
        audit(
            session,
            principal.tenant_id,
            principal.user_id,
            "document.external_authorization_revoked",
            document.document_id,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return row


def authorization_response(row: DocumentExternalAuthorization) -> dict[str, Any]:
    return {
        "authorization_id": row.authorization_id,
        "document_id": row.document_id,
        "sha256": row.document_sha256,
        "parse_version": row.parse_version,
        "purpose": row.purpose,
        "provider": row.provider,
        "action": "approve" if row.state == "active" else "revoke",
        "approved_at": as_utc(row.approved_at).isoformat(),
        "expires_at": as_utc(row.expires_at).isoformat(),
        "approved_by": row.approved_by,
        "policy_version": row.policy_version,
    }


class PostgresAuthorizationGate:
    """Database-backed per-file gate for freezing runs and every outbound payload."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        tenant_id: str,
        purpose: str,
        provider: str,
    ) -> None:
        self.session_factory = session_factory
        self.tenant_id = tenant_id
        self.purpose = _validate_purpose(purpose)
        self.provider = _validate_provider(provider)

    def allowed_hashes(self) -> frozenset[str]:
        """Currently active, unexpired, policy-allowed file hashes for this tenant."""
        now = datetime.now(UTC)
        with self.session_factory() as session:
            require_runtime_role(session)
            policy = require_execution_policy(
                session, self.tenant_id, provider=self.provider, purpose=self.purpose
            )
            rows = session.scalars(
                select(DocumentExternalAuthorization).where(
                    DocumentExternalAuthorization.tenant_id == self.tenant_id,
                    DocumentExternalAuthorization.purpose == self.purpose,
                    DocumentExternalAuthorization.provider == self.provider,
                    DocumentExternalAuthorization.state == "active",
                )
            )
            return frozenset(
                row.document_sha256
                for row in rows
                if as_utc(row.expires_at) > now
                and row.policy_version <= policy.policy_version
            )

    def require_run(
        self,
        *,
        tenant_id: str,
        project_id: str,
        documents: Sequence[tuple[str, str, int]],
    ) -> None:
        """Fail the frozen run unless every exact document version is still approved."""
        if tenant_id != self.tenant_id:
            raise PermissionError("review tenant is not the product execution tenant")
        if not documents:
            raise PermissionError("no document is authorized for external processing")
        now = datetime.now(UTC)
        with self.session_factory() as session:
            require_runtime_role(session)
            try:
                policy = require_execution_policy(
                    session, self.tenant_id, provider=self.provider, purpose=self.purpose
                )
            except PermissionError as exc:
                raise PermissionError(
                    "this document is not authorized for external processing"
                ) from exc
            for document_id, sha256, parse_version in documents:
                row = session.scalar(
                    select(DocumentExternalAuthorization).where(
                        DocumentExternalAuthorization.tenant_id == self.tenant_id,
                        DocumentExternalAuthorization.project_id == project_id,
                        DocumentExternalAuthorization.document_id == document_id,
                        DocumentExternalAuthorization.document_sha256 == sha256,
                        DocumentExternalAuthorization.parse_version == parse_version,
                        DocumentExternalAuthorization.purpose == self.purpose,
                        DocumentExternalAuthorization.provider == self.provider,
                        DocumentExternalAuthorization.state == "active",
                    )
                )
                if (
                    row is None
                    or as_utc(row.expires_at) <= now
                    or row.policy_version > policy.policy_version
                ):
                    raise PermissionError(
                        "this document is not authorized for external processing"
                    )
                document = session.get(Document, (self.tenant_id, document_id))
                if (
                    document is None
                    or document.project_id != project_id
                    or document.sha256 != sha256
                    or document.parse_version != parse_version
                ):
                    raise PermissionError(
                        "this document version changed after external authorization"
                    )


def authorization_rows(
    session: Session, tenant_id: str, document_id: str
) -> Iterable[DocumentExternalAuthorization]:
    set_tenant(session, tenant_id)
    return session.scalars(
        select(DocumentExternalAuthorization)
        .where(
            DocumentExternalAuthorization.tenant_id == tenant_id,
            DocumentExternalAuthorization.document_id == document_id,
        )
        .order_by(DocumentExternalAuthorization.approved_at)
    )
