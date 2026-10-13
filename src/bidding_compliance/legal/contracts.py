"""Closed legal DTOs; JSON contracts generated before consumers are implemented."""

from datetime import date, datetime
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .regions import ALIASES, normalize_region

REGION_VALUES: list[JsonValue] = [value for value in sorted(set(ALIASES.values()))]

Digest = str
Procurement = Literal["government", "enterprise", "other"]
ProjectType = Literal["works", "goods", "services"]
Reason = Literal["valid", "unverified", "outside_verification_horizon", "unlocated"]
VersionStatus = Literal["verified_current", "verified_historical", "unverified"]
ExclusionReason = Literal[
    "not_yet_effective", "expired", "jurisdiction_mismatch", "procurement_mismatch",
    "project_type_mismatch", "unverified", "outside_verification_horizon",
    "unlocated", "no_text_match", "context_incomplete",
]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class LegalVersion(Closed):
    law_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=500)
    text_path: str = Field(min_length=1, max_length=500)
    text_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    source_uri: str = Field(min_length=1, max_length=2048)
    source_snapshot_path: str = Field(min_length=1, max_length=500)
    source_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    captured_on: date
    verification: Literal["verified", "unverified"]
    verified_through: date | None
    effective_from: date | None
    effective_to: date | None
    jurisdictions: tuple[str, ...] = Field(min_length=1, max_length=50)
    procurement_types: tuple[Procurement, ...] = Field(min_length=1, max_length=3)
    project_types: tuple[ProjectType, ...] = Field(min_length=1, max_length=3)
    authority: Literal["law", "regulation", "department_rule", "policy", "reference"]
    verification_note: str = Field(min_length=1, max_length=2000)

    @field_validator("jurisdictions")
    @classmethod
    def valid_regions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(normalize_region(value) for value in values)

    @model_validator(mode="after")
    def valid_metadata(self) -> Self:
        url = urlsplit(self.source_uri)
        if (
            url.scheme not in {"https", "http"} or not url.hostname
            or not url.hostname.endswith(".gov.cn") or url.username or url.password
            or (self.verification == "verified" and url.scheme != "https")
        ):
            raise ValueError("official source required; verified sources require HTTPS")
        if self.effective_to and (
            not self.effective_from or self.effective_to <= self.effective_from
        ):
            raise ValueError("effective interval must be nonempty [from, to)")
        if self.verification == "verified" and (
            not self.effective_from or not self.verified_through
            or self.verified_through < self.effective_from
            or self.authority == "reference"
        ):
            raise ValueError("verified versions require dates and normative authority")
        if any(not region.strip() for region in self.jurisdictions):
            raise ValueError("jurisdiction must not be empty")
        return self


class LegalManifest(Closed):
    schema_version: Literal["v1alpha1"] = "v1alpha1"
    versions: tuple[LegalVersion, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_versions(self) -> Self:
        keys = [(v.law_id, v.version) for v in self.versions]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate legal version")
        for i, left in enumerate(self.versions):
            for right in self.versions[i + 1:]:
                if left.law_id != right.law_id:
                    continue
                if left.verification != "verified" or right.verification != "verified":
                    continue
                if left.effective_from is None or right.effective_from is None:
                    raise ValueError("verified interval missing")
                if (
                    (left.effective_to is None or right.effective_from < left.effective_to)
                    and (right.effective_to is None or left.effective_from < right.effective_to)
                ):
                    raise ValueError("overlapping verified versions")
        return self


class LegalClause(Closed):
    clause_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    law_id: str
    version: str
    article: str | None
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=8000)
    quote_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")


class LegalIndex(Closed):
    schema_version: Literal["v1alpha1"] = "v1alpha1"
    pipeline_version: Literal["legal-ingestion-1"] = "legal-ingestion-1"
    manifest: LegalManifest
    clauses: tuple[LegalClause, ...] = Field(min_length=1, max_length=50000)


class RetrievalInput(Closed):
    text: str = Field(min_length=1, max_length=1000)
    review_date: date
    limit: int = Field(default=10, ge=1, le=50, strict=True)
    include_references: bool = False


class RetrievalQuery(RetrievalInput):
    schema_version: Literal["v1alpha2"] = "v1alpha2"
    region: str = Field(
        min_length=1, max_length=200,
        json_schema_extra={"enum": REGION_VALUES},
    )
    procurement_type: Procurement
    project_type: ProjectType

    @field_validator("region")
    @classmethod
    def valid_region(cls, value: str) -> str:
        return normalize_region(value)


class LegalHit(Closed):
    evidence_id: str
    law_id: str
    title: str
    article: str | None
    version: str
    quote: str
    quote_hash: str
    source_uri: str
    source_hash: str
    text_hash: str
    locator: str
    effective_from: date | None
    effective_to: date | None
    version_status: VersionStatus
    eligible_for_confirmation: bool
    reason: Reason
    score: float = Field(ge=0)


class Excluded(Closed):
    law_id: str | None = None
    version: str | None = None
    reasons: tuple[ExclusionReason, ...] = Field(min_length=1)


class RunSnapshot(Closed):
    run_id: str = Field(min_length=36, max_length=36)
    tenant_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    actor_id: str = Field(min_length=1, max_length=64)
    context_version: int = Field(ge=1, strict=True)
    context_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    request_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    review_date: date
    review_date_source: Literal["explicit_actor_input"] = "explicit_actor_input"
    created_at: datetime


class RetrievalResult(Closed):
    model_config = ConfigDict(json_schema_extra={
        "allOf": [
            {
                "if": {"properties": {"status": {"const": "context_incomplete"}},
                       "required": ["status"]},
                "then": {"properties": {
                    "query": {"type": "null"}, "hits": {"maxItems": 0},
                    "context_error": {"enum": ["REGION_UNMAPPED", "CONTEXT_INVALID"]},
                    "excluded": {"minItems": 1},
                }, "required": ["context_error", "excluded"]},
            },
            {
                "if": {"properties": {"status": {"const": "complete"}}},
                "then": {"properties": {
                    "query": {"type": "object"}, "context_error": {"type": "null"},
                }},
            },
        ],
    })
    schema_version: Literal["v1alpha2"] = "v1alpha2"
    snapshot_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    retrieval_version: Literal["bm25-char-cosine-rrf-2"] = "bm25-char-cosine-rrf-2"
    normalization_version: Literal["cn-regions-1"] = "cn-regions-1"
    status: Literal["complete", "context_incomplete"] = "complete"
    context_error: Literal["REGION_UNMAPPED", "CONTEXT_INVALID"] | None = None
    query: RetrievalQuery | None
    hits: tuple[LegalHit, ...]
    excluded: tuple[Excluded, ...] = ()
    run_snapshot: RunSnapshot | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        if self.status == "context_incomplete":
            if self.query is not None or self.hits or self.context_error is None:
                raise ValueError("incomplete context cannot produce query or evidence")
            if not any("context_incomplete" in x.reasons for x in self.excluded):
                raise ValueError("incomplete context requires an exclusion")
        elif self.query is None or self.context_error is not None:
            raise ValueError("complete retrieval requires query and no context error")
        if self.run_snapshot and self.query:
            if self.run_snapshot.review_date != self.query.review_date:
                raise ValueError("run date does not match query date")
        return self
