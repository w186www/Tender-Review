"""Focused deterministic tests for the five TASK-0007 candidate skills."""

import hashlib
import json
from pathlib import Path

import pytest

from bidding_compliance.domain.rules.engine import SKILLS, discover
from bidding_compliance.domain.rules.models import (
    DiscoveryInputSnapshot,
    DocumentVersionRef,
    LocatedFragment,
    RuleMatch,
    RuleReference,
    SkillScan,
)
from bidding_compliance.ingestion.schemas import Fragment

SOURCE_SHA = "a" * 64


def fragment(
    text: str,
    *,
    locator: str = "paragraph:0",
    section: str = "正文",
    page: int | None = None,
    kind: str = "paragraph",
    table: int | None = None,
    row: int | None = None,
    column: int | None = None,
) -> Fragment:
    return Fragment(
        locator=locator,
        page=page,
        bbox=[0, 0, 100, 100] if page is not None else None,
        coordinate_system="pdf_points" if page is not None else "ooxml",
        kind=kind,
        section=section,
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source="native",
        confidence=None,
        table=table,
        row=row,
        column=column,
    )


def located(text: str, **kwargs) -> LocatedFragment:
    value = fragment(text, **kwargs)
    provisional = DocumentVersionRef(
        document_id="doc-a",
        raw_source_sha256=SOURCE_SHA,
        parse_version=1,
        context_version=1,
        fragments_sha256="0" * 64,
        document_version_ref="doc-version:sha256:" + "0" * 64,
        fragment_count=1,
    )
    return LocatedFragment(provisional, "section-a", 1, value)


def freeze(items: tuple[LocatedFragment, ...], *, parse_version: int = 1):
    def canonical(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    items = tuple(sorted(items, key=lambda item: (item.section_id, item.fragment.locator)))
    fragments_hash = hashlib.sha256(
        canonical(
            [
                {
                    "section_id": item.section_id,
                    "section_revision": item.section_revision,
                    "fragment": item.fragment.model_dump(mode="json"),
                }
                for item in items
            ]
        )
    ).hexdigest()
    version_hash = hashlib.sha256(
        canonical(
            {
                "tenant_id": "tenant-a",
                "project_id": "project-a",
                "document_id": "doc-a",
                "raw_source_sha256": SOURCE_SHA,
                "parse_version": parse_version,
                "context_version": 1,
                "fragments_sha256": fragments_hash,
            }
        )
    ).hexdigest()
    ref = "doc-version:sha256:" + version_hash
    doc = DocumentVersionRef(
        document_id="doc-a",
        raw_source_sha256=SOURCE_SHA,
        parse_version=parse_version,
        context_version=1,
        fragments_sha256=fragments_hash,
        document_version_ref=ref,
        fragment_count=len(items),
    )
    actual = tuple(
        LocatedFragment(doc, item.section_id, item.section_revision, item.fragment)
        for item in items
    )
    snapshot = DiscoveryInputSnapshot(
        tenant_id="tenant-a",
        project_id="project-a",
        project_version=1,
        project_context_sha256="c" * 64,
        project_context_ref="project-version:sha256:"
        + hashlib.sha256(
            canonical(
                {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "version": 1,
                    "context_sha256": "c" * 64,
                }
            )
        ).hexdigest(),
        documents=(doc,),
    )
    return snapshot, {"doc-a": actual}


@pytest.mark.parametrize(
    ("skill_id", "positive", "negative"),
    [
        (
            "qualification_review",
            "投标人必须在本市注册并设立分支机构。",
            "项目所在地在本市，施工现场须设项目部。",
        ),
        (
            "technical_review",
            "技术参数：设备只接受甲牌品牌型号。",
            "技术参数：甲牌品牌型号仅供参考，可接受等效产品。",
        ),
        (
            "contract_review",
            "付款期限：待填写",
            "备注：待定",
        ),
        (
            "procedure_review",
            "投标截止时间：2026年10月20日 09:00 北京时间；开标时间：2026年10月20日 08:30 北京时间",
            "投标截止时间：2026年10月20日 09:00 北京时间；开标时间：2026年10月20日 09:30 北京时间",
        ),
    ],
)
def test_fragment_skills_detect_only_explicit_candidate_conditions(skill_id, positive, negative):
    module = SKILLS[skill_id]
    scope = "投标人资格要求" if skill_id == "qualification_review" else "正文"
    if skill_id == "contract_review":
        scope = "合同条款"
    assert module.scan((located(positive, section=scope),)).matches
    no_candidate = module.scan((located(negative, section=scope),))
    assert not no_candidate.matches
    assert no_candidate.status == "completed"


def test_qualification_does_not_treat_worksite_locality_as_bidder_registration():
    scan = SKILLS["qualification_review"].scan(
        (located("项目所在地在本市，投标人应按本地施工现场要求配置人员。"),)
    )
    assert scan.matches == ()


def test_technical_conflicting_exclusive_and_equivalent_language_is_incomplete():
    result = SKILLS["technical_review"].scan(
        (located("设备只接受甲牌品牌型号，但同时允许等效产品。", section="技术参数"),)
    )
    assert result.status == "incomplete"
    assert result.reason == "ambiguous_technical_requirement"


def test_procedure_fails_closed_for_missing_duplicate_and_conflicting_timezone():
    missing = SKILLS["procedure_review"].scan((located("投标截止时间另行通知。"),))
    duplicate = SKILLS["procedure_review"].scan(
        (
            located(
                "投标截止时间：2026年10月20日 09:00，投标文件递交截止时间：2026年10月20日 09:00。"
            ),
            located("开标时间：2026年10月20日 08:00。", locator="paragraph:1"),
        )
    )
    timezone = SKILLS["procedure_review"].scan(
        (
            located(
                "投标截止时间：2026年10月20日 09:00 北京时间；"
                "开标时间：2026年10月20日 08:00 UTC+0800。"
            ),
        )
    )
    missing_timezone = SKILLS["procedure_review"].scan(
        (located("投标截止时间：2026年10月20日 09:00；开标时间：2026年10月20日 08:00。"),)
    )
    invalid_timezone = SKILLS["procedure_review"].scan(
        (located("投标截止时间：2026年10月20日 09:00 UTC+9999。"),)
    )
    assert missing.status == "incomplete"
    assert duplicate.status == "incomplete"
    assert timezone.status == "incomplete"
    assert missing_timezone.reason == "missing_timezone"
    assert invalid_timezone.status == "incomplete"
    multi_round = SKILLS["procedure_review"].scan(
        (located("第一轮开标时间：2026年10月20日 08:00 北京时间。"),)
    )
    assert multi_round.reason == "ambiguous_tender_times"


def test_contract_ignores_unrelated_placeholder_inside_contract_section():
    result = SKILLS["contract_review"].scan((located("备注：待定", section="合同条款"),))
    assert result.matches == ()
    out_of_scope = SKILLS["contract_review"].scan((located("付款期限：待定", section="采购要求"),))
    assert out_of_scope.matches == ()
    assert out_of_scope.status == "not_applicable"


def test_contract_skill_uses_pdf_chapter_pages_when_pdf_fragments_have_no_section_labels():
    result = SKILLS["contract_review"].scan(
        (
            located("第五章 合同条款及格式", locator="pdf/page/61/line/1", page=61, section=""),
            located("付款期限：待填写", locator="pdf/page/70/line/5", page=70, section=""),
            located("第九章 投标文件格式", locator="pdf/page/115/line/1", page=115, section=""),
            located("付款期限：待填写", locator="pdf/page/116/line/5", page=116, section=""),
        )
    )

    assert len(result.matches) == 1
    assert result.matches[0].sources[0].fragment.page == 70


def test_contract_skill_scope_does_not_make_ordinary_procurement_text_a_contract():
    result = SKILLS["contract_review"].scan((located("付款期限：待填写", section="采购要求"),))
    assert result.matches == ()
    assert result.status == "not_applicable"


def test_score_table_sums_complete_components_and_fails_closed_on_missing_cell():
    table = (
        located("评分项目", locator="cell:0:0", kind="table_cell", table=0, row=0, column=0),
        located("分值", locator="cell:0:1", kind="table_cell", table=0, row=0, column=1),
        located("技术", locator="cell:1:0", kind="table_cell", table=0, row=1, column=0),
        located("30分", locator="cell:1:1", kind="table_cell", table=0, row=1, column=1),
        located("商务", locator="cell:2:0", kind="table_cell", table=0, row=2, column=0),
        located("20分", locator="cell:2:1", kind="table_cell", table=0, row=2, column=1),
        located("总分", locator="cell:3:0", kind="table_cell", table=0, row=3, column=0),
        located("60分", locator="cell:3:1", kind="table_cell", table=0, row=3, column=1),
    )
    result = SKILLS["evaluation_review"].scan(table)
    assert len(result.matches) == 1
    assert len(result.matches[0].sources) == 3
    incomplete = SKILLS["evaluation_review"].scan(table[:-2] + table[-1:])
    assert incomplete.status == "incomplete"
    second_table = tuple(
        LocatedFragment(
            item.document,
            item.section_id,
            item.section_revision,
            item.fragment.model_copy(
                update={
                    "table": 1,
                    "locator": item.fragment.locator.replace("cell:", "cell:table1:"),
                }
            ),
        )
        for item in table
    )
    assert SKILLS["evaluation_review"].scan(table + second_table).reason == "ambiguous_score_table"
    correct_total = table[:-1] + (
        located("50分", locator="cell:3:1", kind="table_cell", table=0, row=3, column=1),
    )
    assert not SKILLS["evaluation_review"].scan(correct_total).matches


def test_tables_and_procedure_events_never_join_across_document_versions():
    source = located("评分项目", locator="cell:0:0", kind="table_cell", table=0, row=0, column=0)
    other_doc = DocumentVersionRef(
        document_id="doc-b",
        raw_source_sha256="b" * 64,
        parse_version=1,
        context_version=1,
        fragments_sha256="e" * 64,
        document_version_ref="doc-version:sha256:" + "f" * 64,
        fragment_count=1,
    )
    other_cell = LocatedFragment(
        other_doc,
        "section-b",
        1,
        fragment("分值", locator="cell:0:1", kind="table_cell", table=0, row=0, column=1),
    )
    score = SKILLS["evaluation_review"].scan((source, other_cell))
    assert score.status == "incomplete"
    cutoff = located("投标截止时间：2026年10月20日 09:00 北京时间", locator="paragraph:cutoff")
    opening = LocatedFragment(
        other_doc,
        "section-b",
        1,
        fragment("开标时间：2026年10月20日 08:00 北京时间", locator="paragraph:opening"),
    )
    procedure_result = SKILLS["procedure_review"].scan((cutoff, opening))
    assert procedure_result.status == "incomplete"
    assert procedure_result.matches == ()


def test_discovery_output_is_repeatable_and_has_topics_even_without_findings():
    snapshot, mapping = freeze((located("没有命中规则的正文。"),))
    first = discover(snapshot, mapping)
    second = discover(snapshot, mapping)
    assert first == second
    assert first.candidates == ()
    assert {item.skill_id for item in first.retrieval_topics} == set(SKILLS)
    assert all(item.status == "not_applicable" for item in first.skill_coverages)


@pytest.mark.parametrize("skill_id", tuple(SKILLS))
def test_each_skill_records_not_applicable_separately_from_no_candidates(skill_id):
    assert (
        SKILLS[skill_id].scan((located("一般说明。", section="其他条款"),)).status
        == "not_applicable"
    )


def test_discovery_keeps_versioned_locator_and_refuses_snapshot_drift():
    snapshot, mapping = freeze((located("投标人必须在本市注册。", section="资格要求"),))
    result = discover(snapshot, mapping)
    candidate = result.candidates[0]
    assert candidate.status == "candidate"
    assert candidate.source_excerpts[0].section_id == "section-a"
    assert candidate.rule_version == candidate.provenance[0].rule_version
    assert result.engine_version == "1.0.0"
    original = mapping["doc-a"][0]
    changed = {
        "doc-a": (
            LocatedFragment(
                original.document,
                original.section_id,
                original.section_revision,
                fragment("不同文本"),
            ),
        )
    }
    with pytest.raises(ValueError, match="fragment digest"):
        discover(snapshot, changed)


def test_duplicate_matches_merge_but_different_locations_and_document_versions_remain_distinct():
    first = located("投标人必须在本市注册。", locator="paragraph:1", section="投标人资格要求")
    same_text_elsewhere = located(
        "投标人必须在本市注册。", locator="paragraph:2", section="投标人资格要求"
    )
    snapshot, mapping = freeze((first, first, same_text_elsewhere))
    result = discover(snapshot, mapping, ("qualification_review",))
    assert len(result.candidates) == 2
    assert all(len(item.provenance) == 1 for item in result.candidates)

    reordered_snapshot, reordered_mapping = freeze((same_text_elsewhere, first, first))
    reordered = discover(reordered_snapshot, reordered_mapping, ("qualification_review",))
    assert reordered.candidates == result.candidates

    new_version_snapshot, new_version_mapping = freeze((first,), parse_version=2)
    old_version = discover(freeze((first,))[0], freeze((first,))[1], ("qualification_review",))
    new_version = discover(new_version_snapshot, new_version_mapping, ("qualification_review",))
    assert new_version.candidates[0].candidate_id != old_version.candidates[0].candidate_id


def test_candidate_identity_changes_when_rule_version_changes(monkeypatch):
    from bidding_compliance.domain.skills import qualification

    fragments = (located("投标人必须在本市注册。", section="投标人资格要求"),)
    snapshot, mapping = freeze(fragments)
    original_result = discover(snapshot, mapping, ("qualification_review",))
    old_definition = qualification.DEFINITION
    old_rules = qualification.RULES
    updated_rule = old_rules[0].model_copy(update={"rule_version": "1.0.1"})
    updated_reference = old_definition.rules[0].model_copy(update={"rule_version": "1.0.1"})
    monkeypatch.setattr(
        qualification,
        "DEFINITION",
        old_definition.model_copy(update={"rules": (updated_reference,)}),
    )
    monkeypatch.setattr(qualification, "RULES", (updated_rule,))
    updated_result = discover(snapshot, mapping, ("qualification_review",))
    assert updated_result.candidates[0].candidate_id != original_result.candidates[0].candidate_id


def test_skill_exception_is_recorded_as_failed_without_claiming_success(monkeypatch):
    snapshot, mapping = freeze((located("可读正文。"),))
    monkeypatch.setattr(
        SKILLS["technical_review"], "scan", lambda *_: (_ for _ in ()).throw(RuntimeError())
    )
    result = discover(snapshot, mapping)
    technical_coverage = next(
        item for item in result.skill_coverages if item.skill_id == "technical_review"
    )
    assert result.status == "completed_with_failed_skill"
    assert technical_coverage.status == "failed"
    assert technical_coverage.reason == "rule_execution_failed"


def test_gc0001_semantics_remain_a_candidate_requiring_law_and_human_review():
    case = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "evals/golden_cases/GC-0001-region-restriction.json"
        ).read_text(encoding="utf-8")
    )
    assert case["expected"] == {
        "category": "qualification",
        "minimum_status": "suspected",
        "requires_legal_evidence": True,
        "requires_human_review": True,
    }
    text = case["document_excerpt"]["text"]
    parsed_fragment = Fragment(
        locator="pdf/page/10/paragraph/0",
        page=case["document_excerpt"]["page"],
        bbox=[0.0, 0.0, 1.0, 1.0],
        coordinate_system="pdf_points",
        kind="paragraph",
        section=case["document_excerpt"]["section"],
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source="native",
    )
    item = located(text, section=parsed_fragment.section)
    item = LocatedFragment(item.document, item.section_id, item.section_revision, parsed_fragment)
    snapshot, mapping = freeze((item,))
    result = discover(snapshot, mapping, ("qualification_review",))
    assert len(result.candidates) == 1
    assert result.candidates[0].status == "candidate"
    assert result.candidates[0].category == case["expected"]["category"]


def test_explicitly_equivalent_rules_merge_without_losing_provenance(monkeypatch):
    from bidding_compliance.domain.skills import qualification

    item = located("投标人必须在本市注册。", section="投标人资格要求")
    snapshot, mapping = freeze((item,))
    first_rule = qualification.RULES[0]
    second_rule = first_rule.model_copy(update={"rule_id": "TASK0007.QUAL.LOCAL-REGISTRATION-ALT"})
    second_reference = RuleReference(
        rule_id=second_rule.rule_id, rule_version=second_rule.rule_version
    )
    monkeypatch.setattr(qualification, "RULES", (first_rule, second_rule))
    monkeypatch.setattr(
        qualification,
        "DEFINITION",
        qualification.DEFINITION.model_copy(
            update={"rules": qualification.DEFINITION.rules + (second_reference,)}
        ),
    )
    monkeypatch.setattr(
        qualification,
        "scan",
        lambda _: SkillScan(
            (
                RuleMatch(first_rule.rule_id, "same-local-condition", "same reason", (item,)),
                RuleMatch(second_rule.rule_id, "same-local-condition", "same reason", (item,)),
            )
        ),
    )
    result = discover(snapshot, mapping, ("qualification_review",))
    assert len(result.candidates) == 1
    assert {source.rule_id for source in result.candidates[0].provenance} == {
        first_rule.rule_id,
        second_rule.rule_id,
    }


@pytest.mark.parametrize(
    "case_file",
    [
        "GC-0002-exclusive-brand.json",
        "GC-0003-score-total-mismatch.json",
        "GC-0004-key-contract-placeholder.json",
        "GC-0005-tender-time-order.json",
    ],
)
def test_golden_skill_cases_match_deterministic_candidate_counts(case_file):
    case = json.loads(
        (Path(__file__).resolve().parents[1] / "evals/golden_cases" / case_file).read_text(
            encoding="utf-8"
        )
    )
    fragments = []
    for index, item in enumerate(case["input_fragments"]):
        fragments.append(
            located(
                item["text"],
                locator=item.get(
                    "locator", f"cell:{item.get('row', index)}:{item.get('column', 0)}"
                ),
                section=item.get("section", "评分标准"),
                kind="table_cell" if "table" in item else "paragraph",
                table=item.get("table"),
                row=item.get("row"),
                column=item.get("column"),
            )
        )
    scan = SKILLS[case["skill_id"]].scan(tuple(fragments))
    expected = case["expected"]
    actual_status = "completed_with_candidates" if scan.matches else scan.status
    assert len(scan.matches) == expected["candidate_count"]
    assert actual_status == expected["coverage_status"]
