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
