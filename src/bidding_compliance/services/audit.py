"""Read-only, tenant-scoped audit queries for authorized auditors."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.persistence.models import AuditEvent
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity


def list_events(
    session: Session,
    principal: Principal,
    *,
    resource_id: str | None,
    actor_id: str | None,
    action: str | None,
    from_time: datetime | None,
    to_time: datetime | None,
    offset: int,
    limit: int,
) -> tuple[list[AuditEvent], int]:
    require_identity(session, principal)
    if principal.role is not Role.AUDITOR:
        audit(session, principal.tenant_id, principal.user_id, "audit.query_denied")
        session.commit()
        raise PermissionError("audit query requires auditor role")
    if from_time is not None and to_time is not None and from_time > to_time:
        raise ValueError("audit time range is invalid")
    filters = [AuditEvent.tenant_id == principal.tenant_id]
    if resource_id:
        filters.append(AuditEvent.resource_id == resource_id)
    if actor_id:
        filters.append(AuditEvent.actor_id == actor_id)
    if action:
        filters.append(AuditEvent.action == action)
    if from_time:
        filters.append(AuditEvent.occurred_at >= from_time)
    if to_time:
        filters.append(AuditEvent.occurred_at <= to_time)
    total = session.scalar(
        select(func.count()).select_from(AuditEvent).where(*filters)
    ) or 0
    rows = list(
        session.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.event_id)
            .offset(offset)
            .limit(limit)
        )
    )
    audit(session, principal.tenant_id, principal.user_id, "audit.query")
    session.commit()
    return rows, total
