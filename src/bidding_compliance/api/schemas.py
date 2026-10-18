"""Response models implementing the existing OpenAPI health and error contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]
    version: str


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    HTTP_ERROR = "HTTP_ERROR"


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: ErrorCode
    message: str
    request_id: str
    details: dict[str, object] = Field(default_factory=dict)


class ExternalAuthorizationRequest(BaseModel):
    """One operator's explicit, per-file confirmation for external processing.

    ``confirmed`` must literally be ``true``: the declaration is part of the audited
    record, never a UI-only checkbox. The endpoint accepts no file content and no hash
    from the caller -- it resolves the document's own SHA-256 server-side -- so it cannot
    be used to authorize a file the caller cannot access.
    """

    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)
    confirmed: Literal[True]
    purpose: str | None = Field(default=None, min_length=3, max_length=64)
    provider: str | None = Field(default=None, min_length=2, max_length=64)
    expires_at: datetime | None = None


class ExternalAuthorizationRevocationRequest(BaseModel):
    """Explicit per-file revocation; the next egress decision observes it."""

    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)
    confirmed: Literal[True]
    purpose: str | None = Field(default=None, min_length=3, max_length=64)
    provider: str | None = Field(default=None, min_length=2, max_length=64)


class ExternalAuthorizationRecord(BaseModel):
    """One authorization/revocation record, echoed back for the operator."""

    model_config = ConfigDict(extra="forbid")
    document_id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["approve", "revoke"]
    approved_at: str
    approved_by: str
    authorization_id: str | None = None
    parse_version: int | None = Field(default=None, ge=1)
    purpose: str | None = None
    provider: str | None = None
    expires_at: str | None = None
    policy_version: int | None = Field(default=None, ge=1)
    revoked_at: str | None = None
    revoked_by: str | None = None
    revocation_reason: str | None = None
