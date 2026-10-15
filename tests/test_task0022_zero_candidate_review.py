"""TASK-0022 regression tests for a legitimate empty offline review input."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from bidding_compliance.model_gateway.contracts import ModelRequest
from scripts.check_review_engine import OfflineReviewGateway, _canonical_hash, _policy

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_SCHEMA = json.loads(
    (ROOT / "contracts/schemas/semantic-analysis.schema.json").read_text(encoding="utf-8")
)


def _request(*, candidates: list[dict], results: list[dict], evidence: dict) -> ModelRequest:
    return ModelRequest(
        call_id=hashlib.sha256(b"task0022-empty-candidate-call").hexdigest(),
        tenant_id="task0022-tenant",
        review_task_id="task0022-empty-candidate-review",
        node_run_id="task0022-run:semantic:0123456789ab",
        prompt_version="task0022-offline-v1",
        system_instruction="Analyze supplied evidence only.",
        input_payload={
            "document_candidates": {"candidates": candidates},
            "legal_retrieval": {"results": results},
            "candidate_legal_evidence": evidence,
        },
        metadata={"snapshot_hash": "a" * 64, "analysis_schema": "v1alpha1"},
    )


def test_empty_candidates_return_schema_valid_empty_findings_with_provenance():
    gateway = OfflineReviewGateway()
    request = _request(candidates=[], results=[], evidence={})
    policy = _policy()

    response = asyncio.run(gateway.generate_structured(request, ANALYSIS_SCHEMA, policy))

    Draft202012Validator(ANALYSIS_SCHEMA).validate(dict(response.content))
    assert response.content == {"schema_version": "v1alpha1", "findings": []}
    assert response.call_id == request.call_id
    assert response.provider == "offline-verification"
    assert response.model == "synthetic-protocol-adapter"
    assert response.profile == policy.profile
    assert response.response_hash == _canonical_hash(response.content)
    assert gateway.calls == 1
    assert not gateway.saw_candidates
    assert not gateway.saw_legal_results


def test_nonempty_candidates_still_require_published_law_results():
    candidate_id = "b" * 64
    candidate = {"candidate_id": candidate_id, "source_excerpts": []}
    gateway = OfflineReviewGateway()

    with pytest.raises(AssertionError, match="published-law results"):
        asyncio.run(
            gateway.generate_structured(
                _request(candidates=[candidate], results=[], evidence={candidate_id: {}}),
                ANALYSIS_SCHEMA,
                _policy(),
            )
        )


def test_empty_candidate_input_rejects_unbound_candidate_evidence():
    gateway = OfflineReviewGateway()

    with pytest.raises(AssertionError, match="candidate-specific legal results"):
        asyncio.run(
            gateway.generate_structured(
                _request(candidates=[], results=[], evidence={"c" * 64: {}}),
                ANALYSIS_SCHEMA,
                _policy(),
            )
        )
