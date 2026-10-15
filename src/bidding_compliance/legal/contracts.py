"""Closed legal DTOs; JSON contracts generated before consumers are implemented."""

import hashlib
import json
import re
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self, cast
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

from bidding_compliance.ingestion.schemas import IngestionPolicy

from .regions import ALIASES, normalize_region

REGION_VALUES: list[JsonValue] = [value for value in sorted(set(ALIASES.values()))]

Digest = str
Procurement = Literal["government", "enterprise", "other"]
ProjectType = Literal["works", "goods", "services"]
Method = Literal["tender", "non_tender"]
Buyer = Literal["government_entity", "enterprise", "other"]
Subject = Literal["works", "works_related_goods", "works_related_services", "goods", "services"]
Framework = Literal["tendering", "government_procurement"]
Reason = Literal[
    "valid",
    "unverified",
    "outside_verification_horizon",
    "unlocated",
    "unknown_end",
    "clause_unverified",
    "extraction_unverified",
    "applicability_unverified",
]
VersionStatus = Literal["verified_current", "verified_historical", "unverified"]
ExclusionReason = Literal[
    "not_yet_effective",
    "expired",
    "jurisdiction_mismatch",
    "procurement_mismatch",
    "project_type_mismatch",
    "unverified",
    "outside_verification_horizon",
    "unlocated",
    "no_text_match",
    "context_incomplete",
    "unknown_end",
    "clause_unverified",
    "extraction_unverified",
    "applicability_unverified",
    "method_mismatch",
    "buyer_mismatch",
    "subject_mismatch",
    "framework_mismatch",
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


class Applicability(Closed):
    procurement_methods: tuple[Method, ...] = Field(min_length=1, max_length=2)
    buyer_types: tuple[Buyer, ...] = Field(min_length=1, max_length=3)
    subject_types: tuple[Subject, ...] = Field(min_length=1, max_length=5)
    legal_frameworks: tuple[Framework, ...] = Field(min_length=1, max_length=2)
    jurisdictions: tuple[str, ...] | None = None
    procurement_types: tuple[Procurement, ...] | None = None
    project_types: tuple[ProjectType, ...] | None = None

    @field_validator("jurisdictions")
    @classmethod
    def valid_scope_regions(cls, values: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if values == ():
            raise ValueError("empty jurisdiction restriction")
        return tuple(normalize_region(x) for x in values) if values else None


class ClauseScope(Closed):
    article: str = Field(min_length=1, max_length=200)
    scope: Applicability
    note: str = Field(min_length=1, max_length=2000)


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
    source_format: Literal["text", "moj_html", "pdf"] = "text"
    extraction_header: str = Field(default="", max_length=2000)
    expected_articles: tuple[str, ...] | None = None
    applicability: Applicability | None = None
    clause_scopes: tuple[ClauseScope, ...] = ()
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
            url.scheme not in {"https", "http"}
            or not url.hostname
            or not url.hostname.endswith(".gov.cn")
            or url.username
            or url.password
            or (self.verification == "verified" and url.scheme != "https")
        ):
            raise ValueError("official source required; verified sources require HTTPS")
        if self.effective_to and self.effective_from and self.effective_to <= self.effective_from:
            raise ValueError("effective interval must be nonempty [from, to)")
        if (self.end_status == "confirmed_end") != (self.effective_to is not None):
            raise ValueError("version end status/date mismatch")
        if self.verification == "verified" and (
            not self.effective_from
            or not self.verified_through
            or self.verified_through < self.effective_from
            or self.authority == "reference"
        ):
            raise ValueError("verified versions require dates and normative authority")
        if any(not region.strip() for region in self.jurisdictions):
            raise ValueError("jurisdiction must not be empty")
        articles = [x.article for x in self.clause_effects]
        if len(articles) != len(set(articles)):
            raise ValueError("duplicate clause effect")
        scope_articles = [x.article for x in self.clause_scopes]
        if len(scope_articles) != len(set(scope_articles)):
            raise ValueError("duplicate clause scope")
        for effect in self.clause_effects:
            starts = [x for x in (effect.effective_from, self.effective_from) if x is not None]
            start = max(starts) if starts else None
            ends = [x for x in (effect.effective_to, self.effective_to) if x is not None]
            if start and ends and min(ends) <= start:
                raise ValueError("clause interval outside version")
        return self


class LegalManifest(Closed):
    schema_version: Literal["v1alpha3"] = "v1alpha3"
    versions: tuple[LegalVersion, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_versions(self) -> Self:
        keys = [(v.law_id, v.version) for v in self.versions]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate legal version")
        titles: dict[str, str] = {}
        for version in self.versions:
            title = "".join(version.title.split()).casefold()
            if title in titles and titles[title] != version.law_id:
                raise ValueError("source change cannot replace legal title identity")
            titles[title] = version.law_id
        for i, left in enumerate(self.versions):
            for right in self.versions[i + 1 :]:
                if left.law_id != right.law_id:
                    continue
                if left.verification != "verified" or right.verification != "verified":
                    continue
                if left.effective_from is None or right.effective_from is None:
                    raise ValueError("verified interval missing")
                if (left.effective_to is None or right.effective_from < left.effective_to) and (
                    right.effective_to is None or left.effective_from < right.effective_to
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


class SourceSpan(Closed):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    kind: Literal["text", "html_text", "html_entity", "pdf_glyph", "header", "separator"]
    byte_start: int | None = Field(default=None, ge=0)
    byte_end: int | None = Field(default=None, gt=0)
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def complete_locator(self) -> Self:
        if self.end <= self.start:
            raise ValueError("empty source span")
        if self.kind in {"text", "html_text", "html_entity"}:
            if self.byte_start is None or self.byte_end is None or self.byte_end <= self.byte_start:
                raise ValueError("source byte span required")
        elif self.kind == "pdf_glyph" and (
            self.page is None
            or self.bbox is None
            or self.bbox[2] < self.bbox[0]
            or self.bbox[3] < self.bbox[1]
        ):
            raise ValueError("PDF page/glyph box required")
        return self


class SourceExclusion(Closed):
    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float]
    text: str = Field(min_length=1, max_length=1000)
    reason: Literal["page_number"]


class SourceMap(Closed):
    law_id: str
    version: str
    source_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    text_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    extraction_version: Literal["identity-1", "moj-html-map-1", "pdf-glyph-map-1"]
    spans: tuple[SourceSpan, ...] = Field(min_length=1, max_length=200000)
    raw_exclusions: tuple[SourceExclusion, ...] = ()


class TextExclusion(Closed):
    law_id: str
    version: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    reason: Literal["preamble", "chapter", "whitespace", "toc"]


class SourceExtractionRequest(Closed):
    payload_base64: str = Field(min_length=1, max_length=2666668)
    policy: IngestionPolicy


class SourceExtractionResult(Closed):
    text: str = Field(min_length=1, max_length=100000)
    spans: tuple[SourceSpan, ...] = Field(min_length=1, max_length=200000)
    raw_exclusions: tuple[SourceExclusion, ...] = ()


class LegalIndex(Closed):
    schema_version: Literal["v1alpha4"] = "v1alpha4"
    pipeline_version: Literal["legal-ingestion-4"] = "legal-ingestion-4"
    manifest: LegalManifest
    clauses: tuple[LegalClause, ...] = Field(min_length=1, max_length=50000)
    source_maps: tuple[SourceMap, ...]
    text_exclusions: tuple[TextExclusion, ...]


class RetrievalInput(Closed):
    text: str = Field(min_length=1, max_length=1000)
    review_date: date
    limit: int = Field(default=10, ge=1, le=50, strict=True)
    include_references: bool = False


class RetrievalQuery(RetrievalInput):
    schema_version: Literal["v1alpha3"] = "v1alpha3"
    region: str = Field(
        min_length=1,
        max_length=200,
        json_schema_extra={"enum": REGION_VALUES},
    )
    procurement_type: Procurement
    project_type: ProjectType
    procurement_method: Method
    buyer_type: Buyer
    subject_type: Subject
    legal_frameworks: tuple[Framework, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def consistent_context(self) -> Self:
        expected_subject = {
            "works": "works",
            "works_related_goods": "goods",
            "works_related_services": "services",
            "goods": "goods",
            "services": "services",
        }[self.subject_type]
        if expected_subject != self.project_type:
            raise ValueError("CONTEXT_INVALID: subject/project mismatch")
        expected_buyer = {
            "government": "government_entity",
            "enterprise": "enterprise",
            "other": "other",
        }[self.procurement_type]
        if self.buyer_type != expected_buyer:
            raise ValueError("CONTEXT_INVALID: buyer/procurement mismatch")
        frameworks: tuple[Framework, ...]
        if self.procurement_type == "government":
            frameworks = (
                ("tendering", "government_procurement")
                if (
                    self.procurement_method == "tender"
                    and self.subject_type
                    in {
                        "works",
                        "works_related_goods",
                        "works_related_services",
                    }
                )
                else ("government_procurement",)
            )
        elif self.procurement_type == "enterprise":
            frameworks = ("tendering",) if self.procurement_method == "tender" else ()
        else:
            frameworks = self.legal_frameworks
        # An enterprise non-tender procurement has no confirmable statutory framework. That
        # is an unknown framework, not a mismatching one: retrieval may still propose
        # potentially relevant law, but every hit stays applicability_unverified because
        # confirmation_reason refuses to return "valid" without a confirmed framework.
        # An explicitly supplied framework that contradicts the derived one is still refused.
        if self.legal_frameworks and self.legal_frameworks != frameworks:
            raise ValueError("CONTEXT_INVALID: confirmed consistent legal frameworks required")
        if len(set(frameworks)) != len(frameworks):
            raise ValueError("CONTEXT_INVALID: duplicate framework")
        object.__setattr__(self, "legal_frameworks", frameworks)
        return self

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
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"eligible_for_confirmation": {"const": True}},
                        "required": ["eligible_for_confirmation"],
                    },
                    "then": {
                        "properties": {
                            "reason": {"const": "valid"},
                            "version_status": {"const": "verified_current"},
                            "article": {"type": "string", "minLength": 1},
                            "effective_from": {"type": "string", "format": "date"},
                        }
                    },
                    "else": {
                        "properties": {
                            "reason": {
                                "enum": [
                                    "unverified",
                                    "outside_verification_horizon",
                                    "unlocated",
                                    "unknown_end",
                                    "clause_unverified",
                                    "extraction_unverified",
                                    "applicability_unverified",
                                ]
                            },
                            "version_status": {"const": "unverified"},
                        }
                    },
                }
            ],
        }
    )
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
    applicable_frameworks: tuple[Framework, ...]
    score: float = Field(ge=0)
    evidence: Annotated[
        EvidenceRef,
        WithJsonSchema(
            {
                "$ref": "https://bidding-compliance.local/schemas/evidence.schema.json",
            }
        ),
    ]

    @model_validator(mode="after")
    def consistent_evidence(self) -> Self:
        eligible = self.reason == "valid"
        if self.eligible_for_confirmation != eligible or self.version_status != (
            "verified_current" if eligible else "unverified"
        ):
            raise ValueError("legal evidence eligibility mismatch")
        if eligible and (not self.article or self.effective_from is None):
            raise ValueError("confirmable legal evidence requires article and effective date")
        if eligible and not self.applicable_frameworks:
            raise ValueError("confirmable legal evidence requires applicable framework")
        if self.effective_to and self.effective_from and self.effective_to <= self.effective_from:
            raise ValueError("legal evidence interval mismatch")
        match = re.fullmatch(r"(.+)#chars=([0-9]+):([0-9]+)", self.locator)
        if match is None or int(match[3]) - int(match[2]) != len(self.quote):
            raise ValueError("legal quotation locator mismatch")
        if hashlib.sha256(self.quote.encode("utf-8")).hexdigest() != self.quote_hash:
            raise ValueError("legal quotation hash mismatch")
        evidence = self.evidence
        expected = {
            "evidence_id": self.evidence_id,
            "title": self.title,
            "article": self.article,
            "quote": self.quote,
            "source_uri": "artifact://legal-text/" + self.text_hash,
            "source_hash": self.text_hash,
            "locator": f"chars={match[2]}:{match[3]}",
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "version_status": self.version_status,
        }
        if (
            evidence.kind not in {"law", "policy"}
            or evidence.page is not None
            or any(getattr(evidence, key) != value for key, value in expected.items())
        ):
            raise ValueError("formal evidence association mismatch")
        return self


class Excluded(Closed):
    law_id: str | None = None
    version: str | None = None
    article: str | None = None
    reasons: tuple[ExclusionReason, ...] = Field(min_length=1)


class EmbeddingModelIdentity(Closed):
    """Pinned provider/model contract used to keep vector spaces isolated."""

    schema_version: Literal["v1alpha1"] = "v1alpha1"
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    region: str = Field(pattern=r"^[a-z][a-z0-9-]{0,49}$")
    model_id: str = Field(min_length=1, max_length=200)
    model_revision: str = Field(min_length=1, max_length=200)
    dimensions: int | None = Field(default=None, ge=1, le=8192)
    tokenizer_identity: str = Field(min_length=1, max_length=200)
    weights_sha256: Digest | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    tokenizer_sha256: Digest | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    api_contract_version: str = Field(min_length=1, max_length=100)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    identity_sha256: Digest = Field(pattern=r"^[a-f0-9]{64}$")

    @staticmethod
    def canonical_hash(payload: dict[str, JsonValue]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def create(cls, **values: object) -> "EmbeddingModelIdentity":
        normalized = cls.model_construct(**cast(Any, values), identity_sha256="")
        payload = normalized.model_dump(mode="json", exclude={"identity_sha256"})
        return cls.model_validate({**payload, "identity_sha256": cls.canonical_hash(payload)})

    @model_validator(mode="after")
    def identity_matches_fields(self) -> Self:
        if (self.provider == "character") != (self.region == "local"):
            raise ValueError("embedding provider and region mismatch")
        if self.provider == "character" and self.dimensions is not None:
            raise ValueError("character vectors do not have a fixed dense dimension")
        if self.provider != "character" and self.dimensions is None:
            raise ValueError("dense embedding dimensions are required")
        payload = self.model_dump(mode="json", exclude={"identity_sha256"})
        if self.identity_sha256 != self.canonical_hash(payload):
            raise ValueError("embedding identity hash mismatch")
        return self


class RetrievalRuntimeSnapshot(Closed):
    """Algorithm settings frozen with a retrieval run; this is not call-level audit."""

    schema_version: Literal["v1alpha1"] = "v1alpha1"
    algorithm: Literal["bm25-char-cosine-rrf-5", "bm25-dense-cosine-rrf-1"] = (
        "bm25-char-cosine-rrf-5"
    )
    top_k: int = Field(ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    bm25_weight: float = Field(default=1.0, gt=0, le=100)
    embedding_weight: float = Field(default=1.0, gt=0, le=100)
    reranker_enabled: bool = False
    reranker_version: str | None = Field(default=None, max_length=200)
    embedding_identity: EmbeddingModelIdentity
    vector_index_build_id: Digest | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    vector_index_item_count: int | None = Field(default=None, ge=0)
    vector_source_item_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def supported_runtime(self) -> Self:
        if self.reranker_enabled != (self.reranker_version is not None):
            raise ValueError("reranker state and version mismatch")
        if self.algorithm == "bm25-char-cosine-rrf-5":
            if self.embedding_identity.provider != "character" or any(
                value is not None for value in (
                    self.vector_index_build_id, self.vector_index_item_count,
                    self.vector_source_item_count,
                )
            ):
                raise ValueError("baseline retrieval cannot activate a dense vector index")
        elif (
            self.embedding_identity.provider == "character"
            or self.vector_index_build_id is None
            or self.vector_index_item_count is None
            or self.vector_source_item_count is None
            or self.vector_index_item_count > self.vector_source_item_count
        ):
            raise ValueError("dense retrieval requires bound vector identity and explicit coverage")
        return self


class RetrievalRankingTrace(Closed):
    clause_id: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    bm25_rank: int | None = Field(default=None, ge=1)
    bm25_score: float | None = None
    vector_rank: int | None = Field(default=None, ge=1)
    vector_score: float | None = None
    fused_score: float = Field(ge=0)


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
    runtime: RetrievalRuntimeSnapshot | None = None
    created_at: datetime


class RetrievalResult(Closed):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"status": {"const": "context_incomplete"}},
                        "required": ["status"],
                    },
                    "then": {
                        "properties": {
                            "query": {"type": "null"},
                            "hits": {"maxItems": 0},
                            "context_error": {"enum": ["REGION_UNMAPPED", "CONTEXT_INVALID"]},
                            "excluded": {"minItems": 1},
                        },
                        "required": ["context_error", "excluded"],
                    },
                },
                {
                    "if": {"properties": {"status": {"const": "complete"}}},
                    "then": {
                        "properties": {
                            "query": {"type": "object"},
                            "context_error": {"type": "null"},
                        }
                    },
                },
            ],
        }
    )
    schema_version: Literal["v1alpha5"] = "v1alpha5"
    snapshot_hash: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    retrieval_version: Literal["bm25-char-cosine-rrf-5", "bm25-dense-cosine-rrf-1"] = (
        "bm25-char-cosine-rrf-5"
    )
    normalization_version: Literal["cn-regions-1"] = "cn-regions-1"
    status: Literal["complete", "context_incomplete"] = "complete"
    context_error: Literal["REGION_UNMAPPED", "CONTEXT_INVALID"] | None = None
    query: RetrievalQuery | None
    hits: tuple[LegalHit, ...]
    citable_evidence: tuple[str, ...] = Field(json_schema_extra={"uniqueItems": True})
    excluded: tuple[Excluded, ...] = ()
    run_snapshot: RunSnapshot | None = None
    ranking_trace: tuple[RetrievalRankingTrace, ...] = ()

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        identities = [hit.evidence_id for hit in self.hits]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate evidence identity")
        if self.ranking_trace and (
            tuple(item.clause_id for item in self.ranking_trace) != tuple(identities)
            or any(
                item.fused_score != hit.score
                for item, hit in zip(self.ranking_trace, self.hits, strict=True)
            )
        ):
            raise ValueError("retrieval ranking trace does not match returned evidence")
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
                if len(set(hit.applicable_frameworks)) != len(hit.applicable_frameworks) or (
                    set(hit.applicable_frameworks) - set(self.query.legal_frameworks)
                ):
                    raise ValueError("evidence framework/query mismatch")
                if hit.reason != "valid" and not self.query.include_references:
                    raise ValueError("reference evidence requires explicit reference mode")
                if hit.evidence.jurisdiction != self.query.region:
                    raise ValueError("evidence jurisdiction mismatch")
                if (hit.effective_from and self.query.review_date < hit.effective_from) or (
                    hit.effective_to and self.query.review_date >= hit.effective_to
                ):
                    raise ValueError("evidence is outside review date interval")
        if self.run_snapshot and self.query:
            if self.run_snapshot.review_date != self.query.review_date:
                raise ValueError("run date does not match query date")
            if self.run_snapshot.runtime and self.run_snapshot.runtime.top_k != self.query.limit:
                raise ValueError("run retrieval top-k does not match query")
            if self.run_snapshot.runtime and (
                self.run_snapshot.runtime.algorithm != self.retrieval_version
            ):
                raise ValueError("run retrieval algorithm does not match result")
        return self
