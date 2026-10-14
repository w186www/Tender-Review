"""Closed legal DTOs; JSON contracts generated before consumers are implemented."""

import hashlib
import re
from datetime import date, datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from .regions import ALIASES, normalize_region

REGION_VALUES: list[JsonValue] = [value for value in sorted(set(ALIASES.values()))]

Digest = str
Procurement = Literal["government", "enterprise", "other"]
ProjectType = Literal["works", "goods", "services"]
Reason = Literal[
    "valid", "unverified", "outside_verification_horizon", "unlocated",
    "unknown_end", "clause_unverified",
]
VersionStatus = Literal["verified_current", "verified_historical", "unverified"]
ExclusionReason = Literal[
    "not_yet_effective", "expired", "jurisdiction_mismatch", "procurement_mismatch",
    "project_type_mismatch", "unverified", "outside_verification_horizon",
    "unlocated", "no_text_match", "context_incomplete", "unknown_end", "clause_unverified",
]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ClauseEffect(Closed):
    article: str = Field(min_length=1, max_length=200)
    effective_from: date | None = None
    effective_to: date | None = None
    end_status: Literal["inherit", "unknown", "confirmed_open", "confirmed_end"] = "inherit"
    verification: Literal["verified", "unverified"]
    note: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def consistent_end(self) -> Self:
        if (self.end_status == "confirmed_end") != (self.effective_to is not None):
            raise ValueError("clause end status/date mismatch")
        if self.effective_from and self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("clause interval must be nonempty")
        return self


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
    end_status: Literal["unknown", "confirmed_open", "confirmed_end"] = "unknown"
    clause_effects: tuple[ClauseEffect, ...] = ()
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
        if self.effective_to and self.effective_from and self.effective_to <= self.effective_from:
            raise ValueError("effective interval must be nonempty [from, to)")
        if (self.end_status == "confirmed_end") != (self.effective_to is not None):
            raise ValueError("version end status/date mismatch")
        if self.verification == "verified" and (
            not self.effective_from or not self.verified_through
            or self.verified_through < self.effective_from
            or self.authority == "reference"
        ):
            raise ValueError("verified versions require dates and normative authority")
        if any(not region.strip() for region in self.jurisdictions):
            raise ValueError("jurisdiction must not be empty")
        articles = [x.article for x in self.clause_effects]
        if len(articles) != len(set(articles)):
            raise ValueError("duplicate clause effect")
        for effect in self.clause_effects:
            starts = [x for x in (effect.effective_from, self.effective_from) if x is not None]
            start = max(starts) if starts else None
            ends = [x for x in (effect.effective_to, self.effective_to) if x is not None]
            if start and ends and min(ends) <= start:
                raise ValueError("clause interval outside version")
        return self


class LegalManifest(Closed):
    schema_version: Literal["v1alpha2"] = "v1alpha2"
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
    schema_version: Literal["v1alpha2"] = "v1alpha2"
    pipeline_version: Literal["legal-ingestion-2"] = "legal-ingestion-2"
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


class EvidenceRef(Closed):
    """Runtime validation of the existing formal EvidenceRef, referenced directly in JSON."""

    evidence_id: str = Field(min_length=1, max_length=128)
    kind: Literal["document", "law", "policy", "internal_rule"]
    title: str = Field(min_length=1, max_length=500)
    article: str | None = Field(default=None, max_length=200)
    quote: str = Field(min_length=1, max_length=8000)
    source_uri: str = Field(min_length=1, max_length=2048)
    source_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    page: int | None = Field(default=None, ge=1, strict=True)
    locator: str | None = Field(default=None, max_length=500)
    effective_from: date | None = None
    effective_to: date | None = None
    version_status: VersionStatus
    jurisdiction: str | None = Field(default=None, max_length=200)


class LegalHit(Closed):
    model_config = ConfigDict(json_schema_extra={
        "allOf": [{
            "if": {"properties": {"eligible_for_confirmation": {"const": True}},
                   "required": ["eligible_for_confirmation"]},
            "then": {"properties": {
                "reason": {"const": "valid"},
                "version_status": {"const": "verified_current"},
                "article": {"type": "string", "minLength": 1},
                "effective_from": {"type": "string", "format": "date"},
            }},
            "else": {"properties": {
                "reason": {"enum": [
                    "unverified", "outside_verification_horizon", "unlocated",
                    "unknown_end", "clause_unverified",
                ]},
                "version_status": {"const": "unverified"},
            }},
        }],
    })
    evidence_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    law_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    article: str | None = Field(max_length=200)
    version: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=1, max_length=8000)
    quote_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_uri: str = Field(min_length=1, max_length=2048)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    text_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(min_length=1, max_length=500)
    effective_from: date | None
    effective_to: date | None
    version_status: VersionStatus
    eligible_for_confirmation: bool = Field(strict=True)
    reason: Reason
    score: float = Field(ge=0)
    evidence: Annotated[EvidenceRef, WithJsonSchema({
        "$ref": "https://bidding-compliance.local/schemas/evidence.schema.json",
    })]

    @model_validator(mode="after")
    def consistent_evidence(self) -> Self:
        eligible = self.reason == "valid"
        if self.eligible_for_confirmation != eligible or self.version_status != (
            "verified_current" if eligible else "unverified"
        ):
            raise ValueError("legal evidence eligibility mismatch")
        if eligible and (not self.article or self.effective_from is None):
            raise ValueError("confirmable legal evidence requires article and effective date")
        if self.effective_to and self.effective_from and self.effective_to <= self.effective_from:
            raise ValueError("legal evidence interval mismatch")
        match = re.fullmatch(r"(.+)#chars=([0-9]+):([0-9]+)", self.locator)
        if match is None or int(match[3]) - int(match[2]) != len(self.quote):
            raise ValueError("legal quotation locator mismatch")
        if hashlib.sha256(self.quote.encode("utf-8")).hexdigest() != self.quote_hash:
            raise ValueError("legal quotation hash mismatch")
        evidence = self.evidence
        expected = {
            "evidence_id": self.evidence_id, "title": self.title, "article": self.article,
            "quote": self.quote, "source_uri": "artifact://legal-text/" + self.text_hash,
            "source_hash": self.text_hash, "locator": f"chars={match[2]}:{match[3]}",
            "effective_from": self.effective_from, "effective_to": self.effective_to,
            "version_status": self.version_status,
        }
        if evidence.kind not in {"law", "policy"} or evidence.page is not None or any(
            getattr(evidence, key) != value for key, value in expected.items()
        ):
            raise ValueError("formal evidence association mismatch")
        return self


class Excluded(Closed):
    law_id: str | None = None
    version: str | None = None
    article: str | None = None
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
    schema_version: Literal["v1alpha4"] = "v1alpha4"
    snapshot_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    retrieval_version: Literal["bm25-char-cosine-rrf-4"] = "bm25-char-cosine-rrf-4"
    normalization_version: Literal["cn-regions-1"] = "cn-regions-1"
    status: Literal["complete", "context_incomplete"] = "complete"
    context_error: Literal["REGION_UNMAPPED", "CONTEXT_INVALID"] | None = None
    query: RetrievalQuery | None
    hits: tuple[LegalHit, ...]
    citable_evidence: tuple[str, ...] = Field(json_schema_extra={"uniqueItems": True})
    excluded: tuple[Excluded, ...] = ()
    run_snapshot: RunSnapshot | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        identities = [hit.evidence_id for hit in self.hits]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate evidence identity")
        expected = tuple(hit.evidence_id for hit in self.hits if hit.eligible_for_confirmation)
        if self.citable_evidence != expected:
            raise ValueError("citable evidence association mismatch")
        if self.status == "context_incomplete":
            if self.query is not None or self.hits or self.context_error is None:
                raise ValueError("incomplete context cannot produce query or evidence")
            if not any("context_incomplete" in x.reasons for x in self.excluded):
                raise ValueError("incomplete context requires an exclusion")
        elif self.query is None or self.context_error is not None:
            raise ValueError("complete retrieval requires query and no context error")
        if self.query:
            for hit in self.hits:
                if hit.reason != "valid" and not self.query.include_references:
                    raise ValueError("reference evidence requires explicit reference mode")
                if hit.evidence.jurisdiction != self.query.region:
                    raise ValueError("evidence jurisdiction mismatch")
                if (
                    (hit.effective_from and self.query.review_date < hit.effective_from)
                    or (hit.effective_to and self.query.review_date >= hit.effective_to)
                ):
                    raise ValueError("evidence is outside review date interval")
        if self.run_snapshot and self.query:
            if self.run_snapshot.review_date != self.query.review_date:
                raise ValueError("run date does not match query date")
        return self
