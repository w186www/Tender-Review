"""Legal evidence classification: only fully confirmed clauses may act as formal evidence.

Citation genuineness (verify_legal_hit) is not legal confirmation. A clause that is genuine
but unverified, past its verification horizon, or without a declared applicability must stay
reference-only even when the model selects it in legal_evidence_ids.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bidding_compliance.graph import review


def _hit(*, eligible: bool, reason: str, version_status: str) -> SimpleNamespace:
    return SimpleNamespace(
        evidence=SimpleNamespace(
            model_dump=lambda **_: {
                "evidence_id": "e" * 64,
                "kind": "law",
                "title": "中华人民共和国民法典",
                "article": "第五百八十五条",
                "quote": "约定的违约金过分高于造成的损失的，可以请求适当减少。",
                "source_uri": "https://www.gov.cn/example",
                "source_hash": "f" * 64,
                "locator": "article:585",
                "page": None,
                "effective_from": None,
                "effective_to": None,
                "version_status": version_status,
                "jurisdiction": "CN",
            }
        ),
        reason=reason,
        version_status=version_status,
        eligible_for_confirmation=eligible,
        law_id="civil-code",
        version="2020-05-28",
        quote_hash="a" * 64,
        source_uri="https://www.gov.cn/example",
        source_hash="b" * 64,
        text_hash="f" * 64,
        locator="https://www.gov.cn/example#chars=100:134",
        effective_from=None,
        effective_to=None,
        applicable_frameworks=("tendering",),
        adoption_status="not_adopted",
        article="第五百八十五条",
        quote="约定的违约金过分高于造成的损失的，可以请求适当减少。",
        evidence_id="e" * 64,
    )


def _merge(
    monkeypatch,
    *,
    selected: bool,
    verified,
    hits=None,
    description="需人工核对原文与适用法规。",
    return_artifacts=False,
):
    """Run merge_findings with one model candidate and a controlled retrieval result."""
    from test_llm_candidate_discovery import graph_harness

    nodes, state, artifacts, _, _ = graph_harness(monkeypatch)
    discovered = asyncio.run(nodes["llm_candidate_discovery"](state))
    (candidate,) = artifacts[discovered["discovery_ref"]]["candidates"]
    source = candidate["source_excerpts"][0]
    model_entry = {
        "candidate_id": candidate["candidate_id"],
        "assessment": "potential_issue",
        "title": "待核验疑点",
        "description": description,
        "severity": "medium",
        "source_quote_sha256": [source["quote_sha256"]],
        "legal_evidence_ids": ["e" * 64] if selected else [],
        "recommendation": "由审查员核验。",
        "reasoning_summary": "合成夹具。",
    }
    artifacts["model"] = {"content": {"findings": [model_entry]}}
    hit = verified[0] or _hit(
        eligible=False, reason="unverified", version_status="unverified"
    )
    persisted_hit = {
        "evidence_id": hit.evidence_id,
        "law_id": hit.law_id,
        "title": hit.evidence.model_dump()["title"],
        "article": hit.article,
        "version": hit.version,
        "quote": hit.quote,
        "quote_hash": hit.quote_hash,
        "source_uri": hit.source_uri,
        "source_hash": hit.source_hash,
        "text_hash": hit.text_hash,
        "locator": hit.locator,
        "applicable_frameworks": list(hit.applicable_frameworks),
        "adoption_status": hit.adoption_status,
        "eligible_for_confirmation": hit.eligible_for_confirmation,
        "reason": hit.reason,
    }
    artifacts["retrieval"] = {
        "results": [
            {
                "work_item_id": candidate["candidate_id"],
                "result": {
                    "query": {"legal_frameworks": ["tendering"]},
                    "hits": hits if hits is not None else [persisted_hit],
                },
            }
        ]
    }
    monkeypatch.setattr(
        review,
        "verify_document_excerpt",
        lambda *_a, **_k: {
            "evidence_id": "b" * 64,
            "kind": "document",
            "title": "招标原文",
            "quote": source["quote"],
            "source_uri": "artifact://document/" + "a" * 64,
            "source_hash": "a" * 64,
            "page": None,
            "locator": source["locator"],
            "version_status": "unverified",
        },
    )
    monkeypatch.setattr(review, "verify_legal_hit", lambda *_a, **_k: verified)
    state.update(discovered, model_findings_ref="model", retrieval_results_ref="retrieval")
    merged = nodes["merge_findings"](state)
    (finding,) = artifacts[merged["rule_findings_ref"]]["findings"]
    return (finding, artifacts) if return_artifacts else finding


@pytest.mark.parametrize(
    ("reason", "version_status", "eligible"),
    [
        ("unverified", "unverified", False),
        ("outside_verification_horizon", "unverified", False),
        ("applicability_unverified", "unverified", False),
    ],
)
def test_unconfirmed_clause_selected_by_model_stays_reference_only(
    monkeypatch, reason, version_status, eligible
):
    """A genuine but unconfirmed clause never becomes formal evidence for the finding."""
    hit = _hit(eligible=eligible, reason=reason, version_status=version_status)
    finding = _merge(monkeypatch, selected=True, verified=(hit, hit.quote))

    assert finding["evidence"] and all(
        item["kind"] == "document" for item in finding["evidence"]
    ), "formal evidence must contain no legal clause"
    assert len(finding["legal_references"]) == 1
    reference = finding["legal_references"][0]
    assert reference["law_id"] == "civil-code"
    assert reference["version"] == "2020-05-28"
    assert reference["official_source_uri"] == "https://www.gov.cn/example"
    assert reference["official_source_hash"] == "b" * 64
    assert reference["text_hash"] == "f" * 64
    assert reference["applicable_frameworks"] == ["tendering"]
    assert reference["applicable"] is False
    assert reference["confirmation_reason"] == reason
    assert "retrieval" not in finding["sources"]
    assert finding["evidence_status"] == "insufficient_evidence"


def test_verified_clause_without_rule_binding_stays_reference_only(monkeypatch):
    """A verified clause needs a separately approved rule binding before supporting a claim."""
    hit = _hit(eligible=True, reason="valid", version_status="verified_current")
    finding = _merge(monkeypatch, selected=True, verified=(hit, hit.quote))

    assert all(item["kind"] == "document" for item in finding["evidence"])
    assert len(finding["legal_references"]) == 1
    reference = finding["legal_references"][0]
    assert reference["version_status"] == "verified_current"
    assert reference["eligible_for_confirmation"] is True
    assert reference["confirmation_reason"] == "rule_law_binding_unreviewed"
    assert reference["applicable"] is False
    assert "retrieval" not in finding["sources"]
    assert finding["evidence_status"] == "insufficient_evidence"


def test_verified_clause_does_not_let_model_claim_illegality_without_rule_binding(monkeypatch):
    hit = _hit(eligible=True, reason="valid", version_status="verified_current")
    finding = _merge(
        monkeypatch,
        selected=True,
        verified=(hit, hit.quote),
        description="该行为违法，应依法处罚。",
    )

    assert "该行为违法" not in finding["description"]
    assert "依法处罚" not in finding["description"]
    assert "尚无法律违法认定依据" in finding["description"]
    assert finding["evidence_status"] == "insufficient_evidence"


@pytest.mark.parametrize("failure", ["unreadable_run", "quote_mismatch"])
def test_tampered_or_cross_publication_reference_is_rejected(monkeypatch, failure):
    """A citation that cannot be revalidated yields neither evidence nor reference."""
    hit = _hit(eligible=False, reason="unverified", version_status="unverified")
    # unreadable_run: the saved run cannot be revalidated at all.
    # quote_mismatch: the clause resolves but its bytes differ from the cited quote.
    verified = (
        (None, None) if failure == "unreadable_run" else (hit, "与所引条文不符的文本")
    )
    finding = _merge(monkeypatch, selected=True, verified=verified)

    assert all(item["kind"] == "document" for item in finding["evidence"])
    assert finding["legal_references"] == []
    assert "retrieval" not in finding["sources"]
    # An unusable citation never upgrades the finding either.
    assert finding["evidence_status"] == "insufficient_evidence"


def test_model_selecting_nothing_keeps_references_traceable_in_retrieval_artifact(monkeypatch):
    """Unselected law stays in the frozen retrieval artifact, not finding support."""
    hit = _hit(eligible=False, reason="unverified", version_status="unverified")
    finding, artifacts = _merge(
        monkeypatch,
        selected=False,
        verified=(hit, hit.quote),
        return_artifacts=True,
    )

    assert finding["legal_references"] == []
    assert all(item["kind"] == "document" for item in finding["evidence"])
    assert finding["evidence_status"] == "insufficient_evidence"
    (retrieval_record,) = artifacts["retrieval"]["results"]
    (retrieved,) = retrieval_record["result"]["hits"]
    assert retrieval_record["work_item_id"]
    assert retrieved["evidence_id"] == hit.evidence_id
    assert retrieved["law_id"] == hit.law_id
    assert retrieved["version"] == hit.version
    assert retrieved["article"] == hit.article
    assert retrieved["quote"] == hit.quote
    assert retrieved["source_uri"] == hit.source_uri
    assert retrieved["source_hash"] == hit.source_hash
    assert retrieved["text_hash"] == hit.text_hash
    assert retrieved["applicable_frameworks"] == ["tendering"]
    assert retrieved["adoption_status"] == hit.adoption_status
