"""Tenant-scoped read contracts for audit history."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AuditEventResponse(Closed):
    event_id: str
    actor_id: str | None
    action: str
    resource_id: str | None
    request_id: str
    occurred_at: datetime


class AuditEventList(Closed):
    items: list[AuditEventResponse]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
