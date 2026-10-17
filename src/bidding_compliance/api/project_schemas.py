"""Closed request/response schemas matching the versioned OpenAPI contract."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from bidding_compliance.domain.identity import Role


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(ClosedModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1024)


class AccessToken(ClosedModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - public OAuth token type
    expires_in: int = Field(ge=60, le=3600)


class Identity(ClosedModel):
    tenant_id: str
    user_id: str
    username: str
    role: Role


class Logout(ClosedModel):
    status: Literal["revoked"] = "revoked"


class ProjectCreate(ClosedModel):
    name: str = Field(min_length=1, max_length=300)
    procurement_type: Literal["government", "enterprise", "other"]
    project_type: Literal["works", "goods", "services"]
    region: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    budget_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False, strict=True)
    applicable_system: str | None = Field(default=None, max_length=1000)
    procurement_method: Literal["tender", "non_tender", "unknown"] = "unknown"
    buyer_type: Literal["government_entity", "enterprise", "other", "unknown"] = "unknown"
    subject_type: Literal[
        "works", "works_related_goods", "works_related_services", "goods", "services", "unknown",
    ] = "unknown"
    legal_frameworks: tuple[Literal["tendering", "government_procurement"], ...] = Field(
        default=(), max_length=2,
    )


class ProjectUpdate(ProjectCreate):
    expected_version: int = Field(ge=1, strict=True)


class ProjectResponse(ProjectCreate):
    project_id: str
    tenant_id: str
    version: int = Field(ge=1)
    created_at: datetime


class ProjectList(ClosedModel):
    items: list[ProjectResponse]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class ProjectHistory(ClosedModel):
    items: list[ProjectResponse]
