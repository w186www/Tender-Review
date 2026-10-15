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
        article="第五百八十五条",
        quote="约定的违约金过分高于造成的损失的，可以请求适当减少。",
        evidence_id="e" * 64,
    )


def _merge(monkeypatch, *, selected: bool, verified, hits=None):
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
        "description": "需人工核对原文与适用法规。",
        "severity": "medium",
        "source_quote_sha256": [source["quote_sha256"]],
        "legal_evidence_ids": ["e" * 64] if selected else [],
        "recommendation": "由审查员核验。",
        "reasoning_summary": "合成夹具。",
    }
    artifacts["model"] = {"content": {"findings": [model_entry]}}
    artifacts["retrieval"] = {
        "results": [
            {
                "work_item_id": candidate["candidate_id"],
                "result": {"hits": hits if hits is not None else [{"evidence_id": "e" * 64}]},
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
    return finding


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
    assert reference["applicable"] is False
    assert reference["confirmation_reason"] == reason
    assert "retrieval" not in finding["sources"]
    assert finding["evidence_status"] == "insufficient_evidence"


def test_confirmed_clause_becomes_formal_evidence(monkeypatch):
    """Only a clause that passed the confirmation chain enters formal evidence."""
    hit = _hit(eligible=True, reason="valid", version_status="verified_current")
    finding = _merge(monkeypatch, selected=True, verified=(hit, hit.quote))

    laws = [item for item in finding["evidence"] if item["kind"] == "law"]
    assert len(laws) == 1
    assert laws[0]["version_status"] == "verified_current"
    assert finding["legal_references"] == []
    assert "retrieval" in finding["sources"]


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


def test_model_selecting_nothing_keeps_references_available(monkeypatch):
    """With no model selection the retrieved clause is still offered as a reference."""
    hit = _hit(eligible=False, reason="unverified", version_status="unverified")
    finding = _merge(monkeypatch, selected=False, verified=(hit, hit.quote))

    assert len(finding["legal_references"]) == 1
    assert all(item["kind"] == "document" for item in finding["evidence"])
    assert finding["evidence_status"] == "insufficient_evidence"
