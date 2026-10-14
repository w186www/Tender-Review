"""Closed, versioned discovery contracts; no infrastructure or model dependencies."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidding_compliance.ingestion.schemas import Fragment, OCRRuntimeIdentity

Category = Literal["qualification", "technical", "evaluation", "contract", "procedure"]
SkillId = Literal[
    "qualification_review",
    "technical_review",
    "evaluation_review",
    "contract_review",
    "procedure_review",
]
CheckId = Literal[
    "local_registration_restriction",
    "exclusive_brand_requirement",
    "structured_score_total",
    "contract_key_placeholder",
    "tender_time_order",
]
CoverageStatus = Literal[
    "completed_no_candidates",
    "completed_with_candidates",
    "not_applicable",
    "incomplete",
    "failed",
]

_CHECK_CATEGORY: dict[str, str] = {
    "local_registration_restriction": "qualification",
    "exclusive_brand_requirement": "technical",
    "structured_score_total": "evaluation",
    "contract_key_placeholder": "contract",
    "tender_time_order": "procedure",
}
_SKILL_CATEGORY: dict[str, str] = {
    "qualification_review": "qualification",
    "technical_review": "technical",
    "evaluation_review": "evaluation",
    "contract_review": "contract",
    "procedure_review": "procedure",
}
_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class RuleReference(Closed):
    rule_id: str = Field(min_length=1, max_length=128)
    rule_version: str = Field(pattern=_SEMVER.pattern)


class RuleDefinition(Closed):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"check_id": {"const": check_id}},
                        "required": ["check_id"],
                    },
                    "then": {"properties": {"category": {"const": category}}},
                }
                for check_id, category in _CHECK_CATEGORY.items()
            ]
        },
    )
    schema_version: Literal["v1alpha1"] = "v1alpha1"
    rule_id: str = Field(min_length=1, max_length=128)
    rule_version: str = Field(pattern=_SEMVER.pattern)
    category: Category
    check_id: CheckId
    applicability: Literal["fragment", "structured_table", "document_timeline"]
    explanation_template: str = Field(min_length=1, max_length=2000)
    equivalence_group: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool = True

    @model_validator(mode="after")
    def supported_definition(self) -> Self:
        if not _SEMVER.fullmatch(self.rule_version):
            raise ValueError("rule_version must be stable semantic versioning")
        if _CHECK_CATEGORY[self.check_id] != self.category:
            raise ValueError("check implementation does not belong to this category")
        return self


class SkillDefinition(Closed):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"skill_id": {"const": skill_id}},
                        "required": ["skill_id"],
                    },
                    "then": {"properties": {"category": {"const": category}}},
                }
                for skill_id, category in _SKILL_CATEGORY.items()
            ]
        },
    )
    schema_version: Literal["v1alpha1"] = "v1alpha1"
    skill_id: SkillId
    skill_version: str = Field(pattern=_SEMVER.pattern)
    category: Category
    rules: tuple[RuleReference, ...] = Field(min_length=1, max_length=100)
    input_schema_version: Literal["parsed-document.v1alpha1"] = "parsed-document.v1alpha1"
    output_schema_version: Literal["candidate-discovery.v1alpha1"] = "candidate-discovery.v1alpha1"

    @model_validator(mode="after")
    def consistent_skill(self) -> Self:
        if not _SEMVER.fullmatch(self.skill_version):
            raise ValueError("skill_version must be stable semantic versioning")
        if _SKILL_CATEGORY[self.skill_id] != self.category:
            raise ValueError("skill category does not match the five-skill contract")
        identities = [(rule.rule_id, rule.rule_version) for rule in self.rules]
        if len(identities) != len(set(identities)):
            raise ValueError("skill has duplicate rule references")
        return self


class DocumentVersionRef(Closed):
    document_id: str = Field(min_length=1, max_length=128)
    raw_source_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    parse_version: int = Field(ge=1, strict=True)
    context_version: int = Field(ge=1, strict=True)
    fragments_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    ocr_runtime: OCRRuntimeIdentity | None = None
    ocr_runtime_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    document_version_ref: str = Field(pattern="^doc-version:sha256:[a-f0-9]{64}$")
    fragment_count: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def parser_hash_matches(self) -> Self:
        if self.ocr_runtime is None:
            if self.ocr_runtime_sha256 is not None:
                raise ValueError("OCR runtime hash has no identity")
        elif self.ocr_runtime.identity_sha256 != self.ocr_runtime_sha256:
            raise ValueError("OCR runtime identity hash mismatch")
        return self


class DiscoveryDocumentRequest(Closed):
    """Caller-pinned document versions; service reads content from trusted storage."""

    document_id: str = Field(min_length=1, max_length=128)
    raw_source_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    parse_version: int = Field(ge=1, strict=True)
    context_version: int = Field(ge=1, strict=True)


class DiscoveryInputSnapshot(Closed):
    tenant_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    project_version: int = Field(ge=1, strict=True)
    project_context_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    project_context_ref: str = Field(pattern="^project-version:sha256:[a-f0-9]{64}$")
    documents: tuple[DocumentVersionRef, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_documents(self) -> Self:
        identifiers = [item.document_id for item in self.documents]
        refs = [item.document_version_ref for item in self.documents]
        if len(identifiers) != len(set(identifiers)) or len(refs) != len(set(refs)):
            raise ValueError("document snapshot references must be unique")
        project_ref = hashlib.sha256(
            json.dumps(
                {
                    "tenant_id": self.tenant_id,
                    "project_id": self.project_id,
                    "version": self.project_version,
                    "context_sha256": self.project_context_sha256,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.project_context_ref != "project-version:sha256:" + project_ref:
            raise ValueError("project context reference is not bound to its snapshot")
        for item in self.documents:
            version_payload = {
                "tenant_id": self.tenant_id,
                "project_id": self.project_id,
                "document_id": item.document_id,
                "raw_source_sha256": item.raw_source_sha256,
                "parse_version": item.parse_version,
                "context_version": item.context_version,
                "fragments_sha256": item.fragments_sha256,
            }
            if item.ocr_runtime_sha256 is not None:
                version_payload["ocr_runtime_sha256"] = item.ocr_runtime_sha256
            version_hash = hashlib.sha256(
                json.dumps(
                    version_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if item.document_version_ref != "doc-version:sha256:" + version_hash:
                raise ValueError("document version reference is not bound to its snapshot")
        return self


class SourceExcerpt(Closed):
    document_id: str = Field(min_length=1, max_length=128)
    document_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    section_id: str = Field(min_length=1, max_length=128)
    section_revision: int = Field(ge=1, strict=True)
    locator: str = Field(min_length=1, max_length=500)
    page: int | None = Field(default=None, ge=1, le=300)
    bbox: tuple[float, float, float, float] | None = None
    coordinate_system: Literal["pdf_points", "image_pixels", "ooxml"]
    quote: str = Field(min_length=1, max_length=8000)
    quote_sha256: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def source_is_real(self) -> Self:
        if hashlib.sha256(self.quote.encode("utf-8")).hexdigest() != self.quote_sha256:
            raise ValueError("source excerpt hash does not match its text")
        if self.coordinate_system == "ooxml":
            if self.page is not None or self.bbox is not None:
                raise ValueError("OOXML source excerpt cannot invent rendered coordinates")
        elif self.page is None or self.bbox is None:
            raise ValueError("page and bounding box are required for visual sources")
        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if min(self.bbox) < 0 or x1 < x0 or y1 < y0:
                raise ValueError("invalid source bounding box")
        return self


class CandidateSource(Closed):
    skill_id: SkillId
    skill_version: str = Field(pattern=_SEMVER.pattern)
    rule_id: str = Field(min_length=1, max_length=128)
    rule_version: str = Field(pattern=_SEMVER.pattern)
    source_excerpts: tuple[SourceExcerpt, ...] = Field(min_length=1, max_length=20)
    matched_reason: str = Field(min_length=1, max_length=2000)


class CandidateFinding(Closed):
    candidate_id: str = Field(pattern="^[a-f0-9]{64}$")
    category: Category
    status: Literal["candidate"] = "candidate"
    skill_id: SkillId
    skill_version: str = Field(pattern=_SEMVER.pattern)
    rule_id: str = Field(min_length=1, max_length=128)
    rule_version: str = Field(pattern=_SEMVER.pattern)
    document_version_ref: str = Field(pattern="^doc-version:sha256:[a-f0-9]{64}$")
    problem_key: str = Field(min_length=1, max_length=128)
    deduplication_key: str = Field(pattern="^[a-f0-9]{64}$")
    source_excerpts: tuple[SourceExcerpt, ...] = Field(min_length=1, max_length=20)
    matched_reason: str = Field(min_length=1, max_length=2000)
    provenance: tuple[CandidateSource, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def primary_provenance(self) -> Self:
        if _SKILL_CATEGORY[self.skill_id] != self.category:
            raise ValueError("candidate category does not match its skill")
        if not any(
            item.skill_id == self.skill_id
            and item.skill_version == self.skill_version
            and item.rule_id == self.rule_id
            and item.rule_version == self.rule_version
            for item in self.provenance
        ):
            raise ValueError("candidate primary rule and skill must be present in provenance")
        if len(set(self.source_excerpts)) != len(self.source_excerpts):
            raise ValueError("duplicate source excerpt in candidate")
        provenance_excerpts = {
            excerpt for source in self.provenance for excerpt in source.source_excerpts
        }
        if provenance_excerpts != set(self.source_excerpts):
            raise ValueError("candidate excerpts do not match their provenance")
        identity = {
            "deduplication_key": self.deduplication_key,
            "provenance": sorted(
                {
                    (item.skill_id, item.skill_version, item.rule_id, item.rule_version)
                    for item in self.provenance
                }
            ),
        }
        canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != self.candidate_id:
            raise ValueError("candidate identity does not match its stable provenance")
        return self


class SkillCoverage(Closed):
    skill_id: SkillId
    skill_version: str = Field(pattern=_SEMVER.pattern)
    category: Category
    status: CoverageStatus
    scanned_documents: tuple[DocumentVersionRef, ...] = Field(min_length=1, max_length=100)
    evaluated_rules: tuple[RuleReference, ...] = Field(min_length=1, max_length=100)
    candidates_found: int = Field(ge=0, strict=True)
    reason: (
        Literal[
            "unsupported_score_table",
            "ambiguous_score_table",
            "ambiguous_tender_times",
            "inconsistent_timezones",
            "missing_timezone",
            "ambiguous_technical_requirement",
            "rule_execution_failed",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def coherent_status(self) -> Self:
        if (self.status in {"incomplete", "failed"}) != (self.reason is not None):
            raise ValueError("incomplete/failed skill coverage requires a concrete reason")
        if self.status == "completed_no_candidates" and self.candidates_found != 0:
            raise ValueError("completed_no_candidates cannot report a finding")
        if self.status == "completed_with_candidates" and self.candidates_found == 0:
            raise ValueError("completed_with_candidates requires a finding")
        if self.status == "not_applicable" and self.candidates_found != 0:
            raise ValueError("not_applicable cannot report a finding")
        return self


class RetrievalTopic(Closed):
    topic_id: str = Field(min_length=1, max_length=128)
    skill_id: SkillId
    skill_version: str = Field(pattern=_SEMVER.pattern)
    category: Category
    query_text: str = Field(min_length=1, max_length=1000)
    source_rules: tuple[RuleReference, ...] = Field(min_length=1, max_length=100)


class DiscoveryResult(Closed):
    schema_version: Literal["v1alpha1"] = "v1alpha1"
    engine_version: Literal["1.0.0"] = "1.0.0"
    input_snapshot: DiscoveryInputSnapshot
    ruleset_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    status: Literal[
        "completed",
        "completed_with_incomplete_skill",
        "completed_with_failed_skill",
    ]
    candidates: tuple[CandidateFinding, ...] = Field(max_length=10000)
    skill_coverages: tuple[SkillCoverage, ...] = Field(min_length=1, max_length=5)
    retrieval_topics: tuple[RetrievalTopic, ...] = Field(min_length=1, max_length=5)
    result_sha256: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        skill_ids = [item.skill_id for item in self.skill_coverages]
        topic_ids = [item.skill_id for item in self.retrieval_topics]
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(set(skill_ids)) != len(skill_ids) or set(skill_ids) != set(topic_ids):
            raise ValueError("each dispatched skill requires one coverage record and topic")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("duplicate candidate identity")
        documents = {item.document_version_ref for item in self.input_snapshot.documents}
        if any(item.document_version_ref not in documents for item in self.candidates):
            raise ValueError("candidate refers to a document outside the frozen input")
        finding_counts = {skill: 0 for skill in skill_ids}
        refs_by_id = {doc.document_id: doc for doc in self.input_snapshot.documents}
        for finding in self.candidates:
            for skill_id in {item.skill_id for item in finding.provenance}:
                if skill_id not in finding_counts:
                    raise ValueError(
                        "candidate provenance includes a skill that was not dispatched"
                    )
                finding_counts[skill_id] += 1
            if any(
                item.document_id not in refs_by_id
                or item.document_sha256 != refs_by_id[item.document_id].raw_source_sha256
                for item in finding.source_excerpts
            ):
                raise ValueError("candidate source does not match an input document")
        for coverage in self.skill_coverages:
            if coverage.candidates_found != finding_counts[coverage.skill_id]:
                raise ValueError("skill coverage candidate count mismatch")
        if self.status == "completed_with_incomplete_skill" and not any(
            item.status == "incomplete" for item in self.skill_coverages
        ):
            raise ValueError("result status hides incomplete coverage")
        if self.status == "completed_with_failed_skill" and not any(
            item.status == "failed" for item in self.skill_coverages
        ):
            raise ValueError("result status hides skill failure")
        payload = self.model_dump(mode="json", exclude={"result_sha256"})
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != self.result_sha256:
            raise ValueError("discovery result hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class LocatedFragment:
    document: DocumentVersionRef
    section_id: str
    section_revision: int
    fragment: Fragment


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule_id: str
    problem_key: str
    reason: str
    sources: tuple[LocatedFragment, ...]


@dataclass(frozen=True, slots=True)
class SkillScan:
    matches: tuple[RuleMatch, ...]
    status: Literal["completed", "not_applicable", "incomplete"] = "completed"
    reason: (
        Literal[
            "unsupported_score_table",
            "ambiguous_score_table",
            "ambiguous_tender_times",
            "inconsistent_timezones",
            "missing_timezone",
            "ambiguous_technical_requirement",
        ]
        | None
    ) = None
