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
    document = {"document_candidates": {"candidates": [
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
    ]}}
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
    }


def test_semantic_prompt_describes_legal_candidates_and_bumps_the_version():
    assert SEMANTIC_PROMPT_VERSION == "task0030-semantic-rag-v1"
    assert "legal_candidates" in SEMANTIC_PROMPT
    assert "legal_evidence_ids只能填写" in SEMANTIC_PROMPT


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
