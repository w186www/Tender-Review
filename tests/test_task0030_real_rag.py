"""TASK-0030 U10: authorized legal candidates enter the semantic request unchanged."""

from __future__ import annotations

import hashlib

import pytest

from bidding_compliance.model_gateway.contracts import DataPolicy
from bidding_compliance.services.real_ai_runtime import (
    MAX_LEGAL_CANDIDATES_PER_CANDIDATE,
    MAX_LEGAL_QUOTE_CHARACTERS,
    SEMANTIC_PROMPT,
    SEMANTIC_PROMPT_VERSION,
    AuthorizedTenderMinimizer,
    real_ai_policy,
)

DOCUMENT = "a" * 64
CANDIDATE = "b" * 64
EVIDENCE = "c" * 64
QUOTE = "投标人必须在本市设立分公司满三年。"


def payload(*, legal: bool = True) -> dict[str, object]:
    document = {
        "document_candidates": {
            "candidates": [
                {
                    "candidate_id": CANDIDATE,
                    "category": "qualification",
                    "matched_reason": "疑似地域限制",
                    "source_excerpts": [
                        {
                            "document_sha256": DOCUMENT,
                            "quote": QUOTE,
                            "quote_sha256": hashlib.sha256(QUOTE.encode()).hexdigest(),
                        }
                    ],
                }
            ]
        }
    }
    if not legal:
        return document
    return {
        **document,
        "prompt_version": SEMANTIC_PROMPT_VERSION,
        "candidate_legal_evidence": {
            CANDIDATE: {
                "work_item_id": CANDIDATE,
                "result": {
                    "hits": [
                        {
                            "evidence_id": EVIDENCE,
                            "law_id": "law-1",
                            "title": "中华人民共和国招标投标法实施条例",
                            "article": "第三十二条",
                            "version": "2019年第三次修订",
                            "quote": "招标人不得以不合理条件限制、排斥潜在投标人。",
                            "version_status": "unverified",
                            "eligible_for_confirmation": False,
                            "reason": "unverified",
                            "score": 0.5,
                        }
                    ]
                },
            }
        },
        "candidate_related_document_evidence": {CANDIDATE: []},
    }


def test_semantic_prompt_describes_legal_candidates_and_bumps_the_version():
    assert SEMANTIC_PROMPT_VERSION == "task0029-semantic-fulltext-v1"
    assert "legal_candidates" in SEMANTIC_PROMPT
    assert "legal_evidence_ids只能填写" in SEMANTIC_PROMPT
    assert "关联章节用于检索全文中的例外、替代条款、反向证据" in SEMANTIC_PROMPT
    assert "没有实际法规候选原文支持" in SEMANTIC_PROMPT


def test_minimizer_sends_legal_candidates_with_ids_and_status():
    minimizer = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))
    safe = minimizer(payload(), real_ai_policy().data_policy)

    assert safe["law_text_included"] is True
    hits = safe["legal_candidates"][CANDIDATE]
    assert len(hits) == 1
    assert hits[0]["evidence_id"] == EVIDENCE
    assert hits[0]["article"] == "第三十二条"
    assert hits[0]["version_status"] == "unverified"
    assert hits[0]["eligible_for_confirmation"] is False
    assert hits[0]["quote"] == "招标人不得以不合理条件限制、排斥潜在投标人。"


def test_minimizer_bounds_legal_quote_and_marks_truncation():
    minimizer = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))
    long_quote = "法" * (MAX_LEGAL_QUOTE_CHARACTERS + 50)
    raw = payload()
    raw["candidate_legal_evidence"][CANDIDATE]["result"]["hits"][0]["quote"] = long_quote

    hit = minimizer(raw, DataPolicy.CONFIDENTIAL)["legal_candidates"][CANDIDATE][0]
    assert hit["quote"] == long_quote[:MAX_LEGAL_QUOTE_CHARACTERS]
    assert hit["quote_truncated"] is True


def test_minimizer_limits_the_number_of_legal_candidates():
    minimizer = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))
    raw = payload()
    hits = raw["candidate_legal_evidence"][CANDIDATE]["result"]["hits"]
    template = hits[0]
    hits.extend({**template, "evidence_id": f"{index:064x}"} for index in range(20))

    safe = minimizer(raw, DataPolicy.CONFIDENTIAL)
    assert len(safe["legal_candidates"][CANDIDATE]) == MAX_LEGAL_CANDIDATES_PER_CANDIDATE


def test_minimizer_refuses_legal_candidates_for_an_unlisted_candidate():
    minimizer = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))
    raw = payload()
    raw["candidate_legal_evidence"]["d" * 64] = raw["candidate_legal_evidence"][CANDIDATE]

    with pytest.raises(ValueError, match="unknown candidate"):
        minimizer(raw, DataPolicy.CONFIDENTIAL)


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_id", "not-a-hash"),
        ("title", ""),
        ("version", ""),
        ("quote", ""),
        ("version_status", ""),
        ("reason", ""),
        ("eligible_for_confirmation", "false"),
    ],
)
def test_minimizer_refuses_malformed_legal_candidate_fields(field, value):
    minimizer = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))
    raw = payload()
    raw["candidate_legal_evidence"][CANDIDATE]["result"]["hits"][0][field] = value

    with pytest.raises(ValueError, match="legal candidate"):
        minimizer(raw, DataPolicy.CONFIDENTIAL)


def test_minimizer_without_legal_candidates_stays_backward_compatible():
    minimizer = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))
    safe = minimizer(payload(legal=False), DataPolicy.CONFIDENTIAL)

    assert safe["legal_candidates"] == {}
    assert safe["law_text_included"] is False


def test_minimizer_validates_and_sends_frozen_related_document_excerpts():
    quote = "同等性能其他品牌的产品也可以参与响应。"
    item = {
        "evidence_id": "d" * 64,
        "document_id": "doc-a",
        "document_sha256": DOCUMENT,
        "section_id": "section-a",
        "section_revision": 1,
        "locator": "pdf/page/54/line/8",
        "page": 54,
        "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
        "title": "全文交叉核对原文（非单独风险结论）",
        "quote": quote,
        "coordinate_system": "pdf_points",
    }
    raw = payload()
    raw["candidate_related_document_evidence"] = {CANDIDATE: [item]}

    safe = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))(raw, real_ai_policy().data_policy)
    assert safe["related_document_evidence"][CANDIDATE] == [
        {
            "evidence_id": "d" * 64,
            "quote_sha256": item["quote_sha256"],
            "quote": quote,
            "page": 54,
            "locator": "pdf/page/54/line/8",
        }
    ]

    item["document_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="related document evidence"):
        AuthorizedTenderMinimizer(frozenset({DOCUMENT}))(raw, real_ai_policy().data_policy)


def test_legacy_frozen_prompt_keeps_the_law_free_payload():
    minimizer = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))
    raw = payload()
    raw["prompt_version"] = "task0023-semantic-v1"

    safe = minimizer(raw, DataPolicy.CONFIDENTIAL)
    assert safe["legal_candidates"] == {}
    assert safe["law_text_included"] is False


def test_public_legal_text_is_bounded_but_not_pii_rewritten():
    minimizer = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))
    raw = payload()
    legal_quote = "第十四条 招标人应当自确定中标人之日起15日内提交书面报告，联系电话010-12345678。"
    raw["candidate_legal_evidence"][CANDIDATE]["result"]["hits"][0]["quote"] = legal_quote

    hit = minimizer(raw, DataPolicy.CONFIDENTIAL)["legal_candidates"][CANDIDATE][0]
    # The legal source is public and must stay verbatim for server-side revalidation; only
    # the tender document excerpt is subject to privacy redaction.
    assert hit["quote"] == legal_quote


def _finding(**overrides):
    value = {
        "finding_id": overrides.pop("finding_id", "f" * 64),
        "category": "qualification",
        "title": "candidate",
        "severity": "medium",
        "evidence_status": "insufficient_evidence",
        "review_status": "pending",
        "sources": ["model"],
        "rule_ids": [],
        "evidence": [],
        "legal_references": [],
        "confidence": 0.5,
        "source_excerpt": {
            "source_hash": DOCUMENT,
            "locator": "pdf/page/1/line/11",
            "quote": QUOTE,
        },
    }
    value.update(overrides)
    return value


def test_duplicate_findings_on_the_same_excerpt_merge_sources_and_evidence():
    from bidding_compliance.services.review_projection import merge_duplicate_findings

    model_one = _finding(
        finding_id="1" * 64,
        evidence=[{"evidence_id": "1" * 64, "source_hash": DOCUMENT}],
        legal_references=[{"evidence_id": EVIDENCE, "selected_by_model": False, "title": "law"}],
    )
    model_two = _finding(
        finding_id="2" * 64,
        title="same issue from the subdivided child batch",
        evidence=[{"evidence_id": "1" * 64, "source_hash": DOCUMENT}],
        legal_references=[{"evidence_id": EVIDENCE, "selected_by_model": True, "title": "law"}],
    )
    rule = _finding(
        finding_id="3" * 64,
        severity="high",
        evidence_status="suspected",
        sources=["rule"],
        rule_ids=["TASK0007.QUAL.LOCAL-REGISTRATION"],
        evidence=[{"evidence_id": "2" * 64, "source_hash": DOCUMENT}],
    )
    other = _finding(
        source_excerpt={
            "source_hash": DOCUMENT,
            "locator": "pdf/page/1/line/12",
            "quote": "另一条不同的原文。",
        }
    )

    issue_keys = {
        "1" * 64: "registration-restriction",
        "2" * 64: "registration-restriction",
        "3" * 64: "registration-restriction",
    }
    first = merge_duplicate_findings([model_one, model_two, rule, other], issue_keys=issue_keys)
    second = merge_duplicate_findings([other, rule, model_two, model_one], issue_keys=issue_keys)

    assert len(first) == 2
    merged = next(item for item in first if item["source_excerpt"]["locator"].endswith("11"))
    assert merged["sources"] == ["model", "rule"]
    assert merged["rule_ids"] == ["TASK0007.QUAL.LOCAL-REGISTRATION"]
    assert merged["severity"] == "high"
    assert merged["evidence_status"] == "insufficient_evidence"
    assert {item["evidence_id"] for item in merged["evidence"]} == {"1" * 64, "2" * 64}
    assert merged["legal_references"][0]["selected_by_model"] is True
    assert (
        merged["finding_id"]
        == next(item for item in second if item["source_excerpt"]["locator"].endswith("11"))[
            "finding_id"
        ]
    )
    assert merged["finding_id"] in {item["finding_id"] for item in (model_one, model_two, rule)}
    assert merged["review_status"] == "pending"


def test_findings_on_different_excerpts_are_not_merged():
    from bidding_compliance.services.review_projection import merge_duplicate_findings

    one = _finding()
    two = _finding(
        source_excerpt={
            "source_hash": DOCUMENT,
            "locator": "pdf/page/1/line/23",
            "quote": "开标时间：2026年10月20日 08:30。",
        }
    )
    merged = merge_duplicate_findings([one, two])
    assert len(merged) == 2


def test_findings_for_distinct_issues_on_the_same_excerpt_are_not_merged():
    from bidding_compliance.services.review_projection import merge_duplicate_findings

    one = _finding(finding_id="1" * 64, title="联系人信息相同")
    two = _finding(finding_id="2" * 64, title="机器码或加密锁号相同")
    merged = merge_duplicate_findings(
        [one, two],
        issue_keys={"1" * 64: "contact-identity", "2" * 64: "machine-identity"},
    )
    assert len(merged) == 2


def test_task0029_merges_known_semantic_duplicates_but_keeps_distinct_brand_issues():
    from bidding_compliance.services.review_projection import merge_duplicate_findings

    public_quote = "公示期限：1日。文件另一条写明公示发布次日起3日。"
    public_one = _finding(
        finding_id="1" * 64,
        category="procedure",
        title="中标结果公示期限仅1日且与关联条款矛盾",
        description="本处公示期限为1日，文件关联章节另有3日规定。",
        source_excerpt={"source_hash": DOCUMENT, "locator": "p16:1", "quote": public_quote},
    )
    public_two = _finding(
        finding_id="2" * 64,
        category="procedure",
        title="中标结果公示期限短于常规要求",
        description="公示期限较短。",
        source_excerpt={"source_hash": DOCUMENT, "locator": "p16:1", "quote": public_quote},
    )
    inquiry_quote = "应配合调查并在规定期限内举证，否则依法处理。"
    inquiry_one = _finding(
        finding_id="3" * 64,
        category="qualification",
        title="配合调查义务指向不明",
        description="拒不配合调查并未在规定期限举证的处理后果需要明确。",
        source_excerpt={"source_hash": DOCUMENT, "locator": "p21:1", "quote": inquiry_quote},
    )
    inquiry_two = _finding(
        finding_id="4" * 64,
        category="qualification",
        title="配合调查义务及处罚标准模糊",
        description="未说明配合调查的举证期限。",
        source_excerpt={"source_hash": DOCUMENT, "locator": "p21:1", "quote": inquiry_quote},
    )
    brand_quote = "替代品牌评审未通过时，中标后只能使用推荐品牌且价格不予调整。"
    criteria = _finding(
        finding_id="5" * 64,
        category="technical",
        title="品牌替换评审标准主观",
        description="评审标准缺少客观量化方法。",
        source_excerpt={"source_hash": DOCUMENT, "locator": "p18:1", "quote": brand_quote},
    )
    price_lock = _finding(
        finding_id="6" * 64,
        category="technical",
        title="品牌锁定机制不公",
        description="中标后强制使用推荐品牌且价格不予调整。",
        source_excerpt={"source_hash": DOCUMENT, "locator": "p18:1", "quote": brand_quote},
    )
    autonomy = _finding(
        finding_id="7" * 64,
        category="technical",
        title="采购自主权受限",
        description="替代品牌评审未通过后，中标人仍须改用推荐品牌。",
        source_excerpt={"source_hash": DOCUMENT, "locator": "p18:1", "quote": brand_quote},
    )
    merged = merge_duplicate_findings(
        [public_one, public_two, inquiry_one, inquiry_two, criteria, price_lock, autonomy],
        issue_keys={str(index) * 64: str(index) * 64 for index in range(1, 8)},
    )

    assert len(merged) == 4
    public = next(item for item in merged if item["category"] == "procedure")
    inquiry = next(item for item in merged if item["category"] == "qualification")
    technical = [item for item in merged if item["category"] == "technical"]
    assert "一日与三日" in public["title"]
    assert "起止计算方式" in public["recommendation"]
    assert "限期举证要求不够明确" in inquiry["title"]
    assert len(technical) == 2
    assert any("评审标准" in item["title"] for item in technical)
    assert any("中标后处理" in item["title"] for item in technical)


def test_task0029_merges_same_fact_duplicates_and_keeps_different_scoring_issues():
    from bidding_compliance.services.review_projection import merge_duplicate_findings

    cases = [
        (
            "qualification",
            "信用管理系统查不到企业信用分的，本项按最低档得分。",
            [
                ("信用分缺失直接判最低档", "未区分系统故障等非主观原因。"),
                ("信用分缺失直接判最低档，缺乏救济机制", "没有写明信用异议的纠错机会。"),
            ],
            "信用分缺失时按最低档计分的处理需补充分情形规则",
        ),
        (
            "contract",
            "项目经理变更按照通知执行；未按要求履行的，追究违约责任。",
            [
                ("客观原因变更人员收违约金", "未区分获准变更与违约情形。"),
                ("项目经理变更与违约责任衔接不清", "客观原因变更是否承担违约责任未说明。"),
            ],
            "项目经理变更条件与违约责任的衔接需明确",
        ),
        (
            "procedure",
            "同一事项规定不一致的，以编排顺序在后者为准。",
            [
                ("文件冲突以后者为准", "未说明该规则与合同条款优先顺序如何衔接。"),
                ("文件冲突解释规则存歧义", "需明确澄清文件与原文件的关系。"),
            ],
            "同一事项在招标文件中的冲突优先顺序需明确",
        ),
        (
            "qualification",
            "拒不配合调查的，由天长市发展和改革委员会依法处理。",
            [
                ("指定发改委处理投诉", "需核对该项目的行政监督职责。"),
                ("指定发改委执法管辖存疑", "需核对该机构的地域管辖权。"),
            ],
            "投诉或调查处理部门及管辖依据需明确",
        ),
        (
            "qualification",
            "项目经理不得在其他尚未完工项目任职。",
            [
                ("项目经理多标段任职限制不清", "未明确是否包括本项目其他标段。"),
                ("项目经理任职限制不明", "其他未完工项目的范围需要明确。"),
            ],
            "项目经理未完工项目限制的范围需明确",
        ),
        (
            "evaluation",
            "其中J=9%，该值由招标人根据具体项目情况自行设定。",
            [
                ("J值设定依据不清", "未说明设定范围及评分影响。"),
                ("J参数自行设定风险", "没有说明计算条件及取值边界。"),
            ],
            "J值的设定依据与评分影响需明确",
        ),
        (
            "evaluation",
            "招标人在线抽取K值，评标委员会根据抽取的K值计算F值。",
            [
                ("K值抽取过程不透明", "未说明抽取时点和见证方式。"),
                ("K值及F值计算流程不清", "取值范围和公式需公开。"),
            ],
            "K值抽取及计算过程需明确",
        ),
    ]
    findings = []
    for index, (category, quote, variants, _expected_title) in enumerate(cases, start=1):
        for offset, (title, description) in enumerate(variants):
            finding_id = str(index * 10 + offset) * 64
            findings.append(
                _finding(
                    finding_id=finding_id,
                    category=category,
                    title=title,
                    description=description,
                    source_excerpt={
                        "source_hash": DOCUMENT,
                        "locator": f"p{index}:same-cell",
                        "quote": quote,
                    },
                )
            )
    distinct_formula = _finding(
        finding_id="9" * 64,
        category="evaluation",
        title="报价偏差率公式量纲歧义",
        source_excerpt={
            "source_hash": DOCUMENT,
            "locator": "p41:same-table",
            "quote": "偏差率乘以100并按不同区间扣分。",
        },
    )
    distinct_low_bid = _finding(
        finding_id="8" * 64,
        category="evaluation",
        title="低价扣分系数较低",
        source_excerpt={
            "source_hash": DOCUMENT,
            "locator": "p41:same-table",
            "quote": "偏差率乘以100并按不同区间扣分。",
        },
    )
    merged = merge_duplicate_findings([*findings, distinct_formula, distinct_low_bid])

    assert len(merged) == len(cases) + 2
    for index, (_category, _quote, _variants, expected_title) in enumerate(cases, start=1):
        locator = f"p{index}:same-cell"
        item = next(
            finding
            for finding in merged
            if finding["source_excerpt"]["locator"] == locator
        )
        assert item["title"] == expected_title
        assert item["review_status"] == "pending"
    remaining_scoring_issues = {
        item["title"]
        for item in merged
        if item["source_excerpt"]["locator"] == "p41:same-table"
    }
    assert remaining_scoring_issues == {"报价偏差率公式量纲歧义", "低价扣分系数较低"}


def test_task0029_suppresses_only_ai_no_issue_without_rule_or_skill_conflict():
    from bidding_compliance.services.review_projection import should_suppress_model_no_issue

    assert should_suppress_model_no_issue("no_issue", {"model"})
    assert not should_suppress_model_no_issue("no_issue", {"model", "skill"})
    assert not should_suppress_model_no_issue("no_issue", {"model", "rule"})
    assert not should_suppress_model_no_issue("uncertain", {"model"})


def test_task0029_legal_reference_payload_preserves_source_version_and_applicability():
    from datetime import date
    from types import SimpleNamespace

    from bidding_compliance.graph.review import _legal_reference_payload

    evidence = SimpleNamespace(
        model_dump=lambda **_kwargs: {
            "evidence_id": EVIDENCE,
            "kind": "policy",
            "title": "招标投标法实施条例",
            "article": "第三十二条",
            "quote": "招标人不得以不合理条件限制、排斥潜在投标人。",
            "source_uri": "artifact://legal-text/" + "d" * 64,
            "source_hash": "d" * 64,
            "locator": "chars=12:36",
            "effective_from": None,
            "effective_to": None,
            "version_status": "unverified",
            "adoption_status": "project_adopted",
            "jurisdiction": "CN/安徽/滁州",
        },
    )
    hit = SimpleNamespace(
        evidence=evidence,
        law_id="law-32",
        version="2019修订版",
        quote_hash="e" * 64,
        source_uri="https://example.invalid/legal-source",
        source_hash="f" * 64,
        text_hash="d" * 64,
        locator="https://example.invalid/legal-source#chars=12:36",
        effective_from=date(2019, 3, 2),
        effective_to=None,
        version_status="unverified",
        eligible_for_confirmation=False,
        reason="outside_verification_horizon",
        applicable_frameworks=("tendering", "government_procurement"),
        adoption_status="project_adopted",
    )

    reference = _legal_reference_payload(
        hit,
        selected=True,
        adoption_policy_id="ADOPT-2026-10-18",
    )

    assert reference["law_id"] == "law-32"
    assert reference["version"] == "2019修订版"
    assert reference["official_source_uri"] == hit.source_uri
    assert reference["official_source_hash"] == "f" * 64
    assert reference["text_hash"] == "d" * 64
    assert reference["article"] == "第三十二条"
    assert reference["applicable_frameworks"] == ["tendering", "government_procurement"]
    assert reference["eligible_for_confirmation"] is False
    assert reference["reason"] == "outside_verification_horizon"
    assert reference["adoption_status"] == "project_adopted"
    assert reference["adoption_policy_id"] == "ADOPT-2026-10-18"
