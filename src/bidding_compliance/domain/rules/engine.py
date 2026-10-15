"""Deterministic, model-free execution for the five versioned review skills."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Literal, cast

from bidding_compliance.domain.rules.models import (
    CandidateFinding,
    CandidateSource,
    CoverageStatus,
    DiscoveryInputSnapshot,
    DiscoveryResult,
    LocatedFragment,
    RetrievalTopic,
    RuleDefinition,
    SkillCoverage,
    SkillId,
    SkillScan,
    SourceExcerpt,
)
from bidding_compliance.domain.skills import (
    contract,
    evaluation,
    procedure,
    qualification,
    technical,
)

SKILLS = {
    module.DEFINITION.skill_id: module
    for module in (qualification, technical, evaluation, contract, procedure)
}
ENGINE_VERSION: Literal["1.0.0"] = "1.0.0"
TOPIC_TEXT = {
    "qualification_review": "投标人资格条件、注册地、分支机构及地区限制依据",
    "technical_review": "技术参数、品牌型号指定及同等替代表述",
    "evaluation_review": "评分标准分项分值、总分及评分表完整性",
    "contract_review": "合同关键条款、价款、付款、违约责任及未填写占位符",
    "procedure_review": "投标截止、文件递交截止与开标日期时间",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _rule_index() -> dict[str, RuleDefinition]:
    result: dict[str, RuleDefinition] = {}
    for module in SKILLS.values():
        for rule in module.RULES:
            if rule.rule_id in result:
                raise ValueError("duplicate fixed rule id")
            result[rule.rule_id] = rule
        for reference in module.DEFINITION.rules:
            rule = next((r for r in module.RULES if r.rule_id == reference.rule_id), None)
            if rule is None or rule.rule_version != reference.rule_version:
                raise ValueError("skill references an unavailable rule version")
            if rule.category != module.DEFINITION.category:
                raise ValueError("skill references a rule outside its category")
    return result


def ruleset_sha256(skill_ids: tuple[SkillId, ...]) -> str:
    rules = _rule_index()
    payload = []
    for skill_id in sorted(skill_ids):
        module = SKILLS[skill_id]
        payload.append(
            {
                "skill": module.DEFINITION.model_dump(mode="json"),
                "rules": [
                    rules[item.rule_id].model_dump(mode="json") for item in module.DEFINITION.rules
                ],
            }
        )
    return _sha(payload)


def _excerpt(item: LocatedFragment) -> SourceExcerpt:
    fragment = item.fragment
    actual = hashlib.sha256(fragment.text.encode("utf-8")).hexdigest()
    if fragment.text_sha256 != actual:
        raise ValueError("effective fragment text hash mismatch")
    return SourceExcerpt(
        document_id=item.document.document_id,
        document_sha256=item.document.raw_source_sha256,
        section_id=item.section_id,
        section_revision=item.section_revision,
        locator=fragment.locator,
        page=fragment.page,
        bbox=(
            cast(tuple[float, float, float, float], tuple(fragment.bbox))
            if fragment.bbox is not None
            else None
        ),
        coordinate_system=fragment.coordinate_system,
        quote=fragment.text,
        quote_sha256=actual,
    )


def _result_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def discover(
    snapshot: DiscoveryInputSnapshot,
    fragments_by_document: Mapping[str, tuple[LocatedFragment, ...]],
    skill_ids: tuple[SkillId, ...] = tuple(SKILLS),
) -> DiscoveryResult:
    """Scan a frozen set of effective fragments and return stable candidate evidence."""
    if not skill_ids or len(set(skill_ids)) != len(skill_ids):
        raise ValueError("dispatched skills must be non-empty and unique")
    if any(skill_id not in SKILLS for skill_id in skill_ids):
        raise ValueError("unsupported skill requested")
    document_refs = {item.document_version_ref for item in snapshot.documents}
    all_fragments = tuple(
        sorted(
            (fragment for group in fragments_by_document.values() for fragment in group),
            key=lambda item: (
                item.document.document_version_ref,
                item.section_id,
                item.fragment.locator,
            ),
        )
    )
    if any(item.document.document_version_ref not in document_refs for item in all_fragments):
        raise ValueError("fragment is outside the frozen input snapshot")
    refs = {item.document_version_ref: item for item in snapshot.documents}
    for reference, document in refs.items():
        matching = [
            item for item in all_fragments if item.document.document_version_ref == reference
        ]
        if len(matching) != document.fragment_count:
            raise ValueError("fragment count differs from the frozen input snapshot")
        fragment_payload = [
            {
                "section_id": item.section_id,
                "section_revision": item.section_revision,
                "fragment": item.fragment.model_dump(mode="json"),
            }
            for item in matching
        ]
        if _sha(fragment_payload) != document.fragments_sha256:
            raise ValueError("fragment digest differs from the frozen input snapshot")
    staged: dict[str, list[tuple[CandidateSource, tuple[SourceExcerpt, ...], str, str]]] = (
        defaultdict(list)
    )
    coverage: list[SkillCoverage] = []
    topics: list[RetrievalTopic] = []
    rule_index = _rule_index()

    for skill_id in skill_ids:
        module = SKILLS[skill_id]
        definition = module.DEFINITION
        try:
            scan: SkillScan = module.scan(all_fragments)
            failed = False
        except Exception:
            scan = SkillScan((), "incomplete", "unsupported_score_table")
            failed = True
        for match in scan.matches:
            rule = rule_index.get(match.rule_id)
            if rule is None or not rule.enabled or rule.category != definition.category:
                failed = True
                continue
            excerpts = tuple(
                sorted(
                    {_excerpt(item) for item in match.sources},
                    key=lambda x: (x.document_id, x.section_id, x.locator, x.quote_sha256),
                )
            )
            if not excerpts or len(excerpts) > 20:
                failed = True
                continue
            doc_ref_by_id = {
                item.document_id: item.document_version_ref for item in snapshot.documents
            }
            excerpt_refs = {doc_ref_by_id.get(item.document_id) for item in excerpts}
            if None in excerpt_refs or len(excerpt_refs) != 1:
                failed = True
                continue
            document_ref = cast(str, next(iter(excerpt_refs)))
            source = CandidateSource(
                skill_id=skill_id,
                skill_version=definition.skill_version,
                rule_id=rule.rule_id,
                rule_version=rule.rule_version,
                source_excerpts=excerpts,
                matched_reason=match.reason,
            )
            equivalence = rule.equivalence_group or rule.rule_id
            key = _sha(
                {
                    "category": definition.category,
                    "document_version_ref": document_ref,
                    "problem_key": match.problem_key,
                    "equivalence": equivalence,
                    "locations": [
                        (item.section_id, item.locator, item.quote_sha256) for item in excerpts
                    ],
                }
            )
            staged[key].append((source, excerpts, match.problem_key, document_ref))

        candidate_count = sum(
            1
            for entries in staged.values()
            if any(entry[0].skill_id == skill_id for entry in entries)
        )
        coverage_status: CoverageStatus
        if failed:
            coverage_status = "failed"
        elif scan.status == "incomplete":
            coverage_status = "incomplete"
        elif scan.status == "not_applicable":
            coverage_status = "not_applicable"
        else:
            coverage_status = (
                "completed_with_candidates" if candidate_count else "completed_no_candidates"
            )
        coverage.append(
            SkillCoverage(
                skill_id=skill_id,
                skill_version=definition.skill_version,
                category=definition.category,
                status=coverage_status,
                scanned_documents=snapshot.documents,
                evaluated_rules=definition.rules,
                candidates_found=candidate_count,
                reason="rule_execution_failed" if failed else scan.reason,
            )
        )
        topics.append(
            RetrievalTopic(
                topic_id=f"{skill_id}:{definition.skill_version}",
                skill_id=skill_id,
                skill_version=definition.skill_version,
                category=definition.category,
                query_text=TOPIC_TEXT[skill_id],
                source_rules=definition.rules,
            )
        )

    candidates: list[CandidateFinding] = []
    for key, entries in sorted(staged.items()):
        sources = tuple(
            sorted(
                {entry[0] for entry in entries},
                key=lambda item: (str(item.skill_id), str(item.rule_id), str(item.rule_version)),
            )
        )
        primary = sources[0]
        exemplar = entries[0]
        candidate_id = _sha(
            {
                "deduplication_key": key,
                "provenance": sorted(
                    {
                        (item.skill_id, item.skill_version, item.rule_id, item.rule_version)
                        for item in sources
                    }
                ),
            }
        )
        candidates.append(
            CandidateFinding(
                candidate_id=candidate_id,
                category=SKILLS[primary.skill_id].DEFINITION.category,
                skill_id=primary.skill_id,
                skill_version=primary.skill_version,
                rule_id=primary.rule_id,
                rule_version=primary.rule_version,
                document_version_ref=exemplar[3],
                problem_key=exemplar[2],
                deduplication_key=key,
                source_excerpts=tuple(
                    sorted(set(exemplar[1]), key=lambda x: (x.section_id, x.locator))
                ),
                matched_reason=primary.matched_reason,
                provenance=sources,
            )
        )
    result_status: Literal[
        "completed", "completed_with_incomplete_skill", "completed_with_failed_skill"
    ] = "completed"
    if any(item.status == "failed" for item in coverage):
        result_status = "completed_with_failed_skill"
    elif any(item.status == "incomplete" for item in coverage):
        result_status = "completed_with_incomplete_skill"
    payload: dict[str, object] = {
        "schema_version": "v1alpha1",
        "engine_version": ENGINE_VERSION,
        "input_snapshot": snapshot.model_dump(mode="json"),
        "ruleset_sha256": ruleset_sha256(skill_ids),
        "status": result_status,
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "skill_coverages": [item.model_dump(mode="json") for item in coverage],
        "retrieval_topics": [item.model_dump(mode="json") for item in topics],
    }
    return DiscoveryResult(
        schema_version="v1alpha1",
        engine_version=ENGINE_VERSION,
        input_snapshot=snapshot,
        ruleset_sha256=str(payload["ruleset_sha256"]),
        status=result_status,
        candidates=tuple(candidates),
        skill_coverages=tuple(coverage),
        retrieval_topics=tuple(topics),
        result_sha256=_result_hash(payload),
    )


def combine_discoveries(results: Sequence[DiscoveryResult]) -> DiscoveryResult:
    """Join dynamic per-Skill results with the same stable de-duplication identity."""
    if not results:
        raise ValueError("at least one Skill result is required")
    snapshot = results[0].input_snapshot
    if any(item.input_snapshot != snapshot for item in results):
        raise ValueError("Skill workers used different frozen input snapshots")
    coverages = [coverage for result in results for coverage in result.skill_coverages]
    topics = [topic for result in results for topic in result.retrieval_topics]
    skill_ids = tuple(sorted(item.skill_id for item in coverages))
    if len(set(skill_ids)) != len(skill_ids) or set(skill_ids) != set(SKILLS):
        raise ValueError("dynamic Skill fanout is incomplete or duplicated")
    groups: dict[str, list[CandidateFinding]] = defaultdict(list)
    for result in results:
        for candidate in result.candidates:
            groups[candidate.deduplication_key].append(candidate)
    candidates: list[CandidateFinding] = []
    for key, members in sorted(groups.items()):
        provenance = tuple(
            sorted(
                {source for candidate in members for source in candidate.provenance},
                key=lambda item: (item.skill_id, item.rule_id, item.rule_version),
            )
        )
        exemplar = min(members, key=lambda item: item.candidate_id)
        primary = provenance[0]
        if primary.origin != "rule" or primary.skill_id is None:
            raise ValueError("Skill fanout can only combine deterministic rule candidates")
        candidate_id = _sha(
            {
                "deduplication_key": key,
                "provenance": sorted(
                    {
                        (item.skill_id, item.skill_version, item.rule_id, item.rule_version)
                        for item in provenance
                    }
                ),
            }
        )
        candidates.append(
            CandidateFinding(
                candidate_id=candidate_id,
                category=SKILLS[primary.skill_id].DEFINITION.category,
                skill_id=primary.skill_id,
                skill_version=primary.skill_version,
                rule_id=primary.rule_id,
                rule_version=primary.rule_version,
                document_version_ref=exemplar.document_version_ref,
                problem_key=exemplar.problem_key,
                deduplication_key=key,
                source_excerpts=exemplar.source_excerpts,
                matched_reason=primary.matched_reason,
                provenance=provenance,
            )
        )
    candidate_counts = {skill_id: 0 for skill_id in skill_ids}
    for candidate in candidates:
        for skill_id in {source.skill_id for source in candidate.provenance}:
            assert skill_id is not None
            candidate_counts[skill_id] += 1
    coverages = [
        coverage.model_copy(update={"candidates_found": candidate_counts[coverage.skill_id]})
        for coverage in coverages
    ]
    status: Literal[
        "completed", "completed_with_incomplete_skill", "completed_with_failed_skill"
    ] = "completed"
    if any(item.status == "failed" for item in coverages):
        status = "completed_with_failed_skill"
    elif any(item.status == "incomplete" for item in coverages):
        status = "completed_with_incomplete_skill"
    payload: dict[str, object] = {
        "schema_version": "v1alpha1",
        "engine_version": ENGINE_VERSION,
        "input_snapshot": snapshot.model_dump(mode="json"),
        "ruleset_sha256": ruleset_sha256(skill_ids),
        "status": status,
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "skill_coverages": [item.model_dump(mode="json") for item in coverages],
        "retrieval_topics": [item.model_dump(mode="json") for item in topics],
    }
    return DiscoveryResult(
        schema_version="v1alpha1",
        engine_version=ENGINE_VERSION,
        input_snapshot=snapshot,
        ruleset_sha256=str(payload["ruleset_sha256"]),
        status=status,
        candidates=tuple(candidates),
        skill_coverages=tuple(coverages),
        retrieval_topics=tuple(topics),
        result_sha256=_result_hash(payload),
    )
