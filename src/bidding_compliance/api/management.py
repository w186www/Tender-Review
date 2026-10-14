"""Authorized, read-only management endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from bidding_compliance.core.dates import as_utc
from bidding_compliance.services import audit

from .management_schemas import AuditEventList, AuditEventResponse
from .projects import DB, User
from .schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1",
    responses={status: {"model": ErrorResponse} for status in (401, 403, 422, 500)},
)


@router.get("/audit/events", response_model=AuditEventList, operation_id="listAuditEvents")
def list_audit_events(
    principal: User,
    session: DB,
    resource_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: Annotated[str | None, Query(max_length=64)] = None,
    action: Annotated[str | None, Query(max_length=100)] = None,
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditEventList:
    try:
        rows, total = audit.list_events(
            session,
            principal,
            resource_id=resource_id,
            actor_id=actor_id,
            action=action,
            from_time=from_time,
            to_time=to_time,
            offset=offset,
            limit=limit,
        )
        return AuditEventList(
            items=[
                AuditEventResponse(
                    event_id=row.event_id,
                    actor_id=row.actor_id,
                    action=row.action,
                    resource_id=row.resource_id,
                    request_id=row.request_id,
                    occurred_at=as_utc(row.occurred_at),
                )
                for row in rows
            ],
            offset=offset,
            limit=limit,
            total=total,
        )
    except PermissionError as exc:
        raise HTTPException(403) from exc
    except ValueError as exc:
        raise HTTPException(422) from exc
