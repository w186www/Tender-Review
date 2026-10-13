"""Closed legal DTOs; JSON contracts generated before consumers are implemented."""

from datetime import date
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = str
Procurement = Literal["government", "enterprise", "other"]
ProjectType = Literal["works", "goods", "services"]
Reason = Literal["valid", "unverified", "outside_verification_horizon", "unlocated"]
VersionStatus = Literal["verified_current", "verified_historical", "unverified"]


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


class RetrievalQuery(Closed):
    text: str = Field(min_length=1, max_length=1000)
    review_date: date
    region: str = Field(min_length=1, max_length=200)
    procurement_type: Procurement
    project_type: ProjectType
    limit: int = Field(default=10, ge=1, le=50, strict=True)
    include_references: bool = False


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


class RetrievalResult(Closed):
    schema_version: Literal["v1alpha1"] = "v1alpha1"
    snapshot_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    retrieval_version: Literal["bm25-char-cosine-rrf-1"] = "bm25-char-cosine-rrf-1"
    query: RetrievalQuery
    hits: tuple[LegalHit, ...]
