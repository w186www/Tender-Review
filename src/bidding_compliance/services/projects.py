"""Tenant-scoped project transactions with immutable snapshots and idempotency."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import IdempotencyRecord, Project, ProjectVersion
from bidding_compliance.services.identity import audit


def require_write(session: Session, principal: Principal) -> None:
    if not principal.can_write_project():
        audit(session, principal.tenant_id, principal.user_id, "project.denied")
        session.commit()
        raise PermissionError("project write forbidden")


def snapshot(project: Project) -> dict[str, Any]:
    return {
        **project.context,
        "tenant_id": project.tenant_id,
        "project_id": project.project_id,
        "version": project.version,
        "created_at": project.created_at.replace(tzinfo=UTC).isoformat(),
    }


def find_project(session: Session, principal: Principal, project_id: str) -> Project:
    set_tenant(session, principal.tenant_id)
    project = session.scalar(
        select(Project).where(
            Project.tenant_id == principal.tenant_id, Project.project_id == project_id
        )
    )
    if project is None:
        raise LookupError("resource unavailable")
    return project


def list_projects(
    session: Session, principal: Principal, offset: int, limit: int
) -> list[dict[str, Any]]:
    set_tenant(session, principal.tenant_id)
    rows = session.scalars(
        select(Project)
        .where(Project.tenant_id == principal.tenant_id)
        .order_by(Project.created_at, Project.project_id)
        .offset(offset)
        .limit(limit)
    )
    return [snapshot(row) for row in rows]


def history(session: Session, principal: Principal, project_id: str) -> list[dict[str, Any]]:
    find_project(session, principal, project_id)
    return list(
        session.scalars(
            select(ProjectVersion.snapshot)
            .where(
                ProjectVersion.tenant_id == principal.tenant_id,
                ProjectVersion.project_id == project_id,
            )
            .order_by(ProjectVersion.version)
        )
    )


def create_project(
    session: Session, principal: Principal, context: dict[str, Any], idempotency_key: str
) -> dict[str, Any]:
    require_write(session, principal)
    set_tenant(session, principal.tenant_id)
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    request_hash = hashlib.sha256(
        json.dumps(context, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    identity = (principal.tenant_id, principal.user_id, key_hash)
    existing = session.get(IdempotencyRecord, identity)
    if existing:
        if existing.request_hash != request_hash:
            raise FileExistsError("idempotency conflict")
        return existing.response
    project = Project(
        tenant_id=principal.tenant_id,
        project_id=str(uuid4()),
        version=1,
        context=context,
        created_by=principal.user_id,
        created_at=datetime.now(UTC),
    )
    result = snapshot(project)
    try:
        # Claim the unique key before any project side effect; concurrent inserts serialize.
        session.add(
            IdempotencyRecord(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                key_hash=key_hash,
                request_hash=request_hash,
                response=result,
            )
        )
        session.flush()
        session.add(project)
        session.flush()
        session.add(
            ProjectVersion(
                tenant_id=principal.tenant_id,
                project_id=project.project_id,
                version=1,
                snapshot=result,
                changed_by=principal.user_id,
                changed_at=datetime.now(UTC),
            )
        )
        audit(
            session, principal.tenant_id, principal.user_id, "project.created", project.project_id
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        set_tenant(session, principal.tenant_id)
        existing = session.get(IdempotencyRecord, identity)
        if existing is None or existing.request_hash != request_hash:
            raise FileExistsError("idempotency conflict") from None
        return existing.response
    return result


def update_project(
    session: Session,
    principal: Principal,
    project_id: str,
    expected_version: int,
    context: dict[str, Any],
) -> dict[str, Any]:
    require_write(session, principal)
    project = find_project(session, principal, project_id)
    result = {**snapshot(project), **context, "version": expected_version + 1}
    changed = session.execute(
        update(Project)
        .where(
            Project.tenant_id == principal.tenant_id,
            Project.project_id == project_id,
            Project.version == expected_version,
        )
        .values(context=context, version=expected_version + 1)
        .returning(Project.project_id)
    ).scalar_one_or_none()
    if changed is None:
        raise FileExistsError("version conflict")
    session.add(
        ProjectVersion(
            tenant_id=principal.tenant_id,
            project_id=project_id,
            version=expected_version + 1,
            snapshot=result,
            changed_by=principal.user_id,
            changed_at=datetime.now(UTC),
        )
    )
    audit(session, principal.tenant_id, principal.user_id, "project.updated", project_id)
    session.commit()
    return result
