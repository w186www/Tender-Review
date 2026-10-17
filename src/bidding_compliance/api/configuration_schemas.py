"""Closed API contracts for task configuration and legal publication management."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidding_compliance.domain.review_configuration import ModelPolicySnapshot
from bidding_compliance.domain.rules.models import SkillId


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SkillCatalogItem(Closed):
    skill_id: SkillId
    skill_version: str
    category: str
    rule_versions: dict[str, str]


class ConfigurationCatalog(Closed):
    skills: list[SkillCatalogItem]
    model_policy: ModelPolicySnapshot
    model_configuration_boundary: str


class ConfigurationDraftRequest(Closed):
    request_id: str = Field(min_length=16, max_length=64)
    expected_sequence: int = Field(ge=0)
    expected_draft_sequence: int = Field(ge=0)
    expected_legal_publication_id: str = Field(min_length=1, max_length=36)
    skill_ids: list[SkillId] = Field(min_length=1, max_length=5)
    model_policy: ModelPolicySnapshot
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_skills(self) -> "ConfigurationDraftRequest":
        if len(self.skill_ids) != len(set(self.skill_ids)):
            raise ValueError("skill_ids must be unique")
        return self


class ConfigurationPublishRequest(Closed):
    request_id: str = Field(min_length=16, max_length=64)
    expected_sequence: int = Field(ge=0)
    revision_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=1, max_length=1000)


class ConfigurationDisableRequest(Closed):
    request_id: str = Field(min_length=16, max_length=64)
    expected_sequence: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class ConfigurationRollbackRequest(Closed):
    request_id: str = Field(min_length=16, max_length=64)
    expected_sequence: int = Field(ge=0)
    target_revision_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=1, max_length=1000)


class ConfigurationRevisionItem(Closed):
    revision_id: str
    revision_sequence: int
    parent_revision_id: str | None
    snapshot: dict[str, object]
    snapshot_hash: str
    reason: str
    actor_id: str
    created_at: datetime
    status: Literal["active", "draft", "inactive"]


class ConfigurationEventItem(Closed):
    event_id: str
    sequence: int
    operation: Literal["draft", "publish", "disable", "rollback"]
    revision_id: str | None
    previous_active_id: str | None
    active_revision_id: str | None
    actor_id: str
    request_id: str
    reason: str
    created_at: datetime


class ConfigurationStateResponse(Closed):
    sequence: int
    draft_sequence: int
    active_revision_id: str | None
    draft_revision_id: str | None
    items: list[ConfigurationRevisionItem]
    events: list[ConfigurationEventItem]


class LegalDraftRequest(Closed):
    request_id: str = Field(min_length=16, max_length=64)
    expected_draft_sequence: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class LegalVersionSummary(Closed):
    law_id: str
    title: str
    version: str
    verification: str
    verified_through: date | None
    end_status: str


class LegalRevisionItem(Closed):
    revision_id: str
    draft_sequence: int
    parent_id: str | None
    operation: Literal["ingest", "verify"]
    content_hash: str
    index_hash: str
    reason: str
    actor_id: str
    created_at: datetime
    versions: list[LegalVersionSummary]


class LegalPublicationItem(Closed):
    publication_id: str
    sequence: int
    previous_id: str | None
    target_id: str | None
    revision_id: str | None
    operation: Literal["publish", "disable", "rollback"]
    reason: str
    actor_id: str
    created_at: datetime


class LegalManagementResponse(Closed):
    sequence: int
    publication_id: str | None
    draft_sequence: int
    draft_revision_id: str | None
    capabilities: list[str]
    revisions: list[LegalRevisionItem]
    publications: list[LegalPublicationItem]
