"""TASK-0021 tests for server authorization, minimization, budget, and audit wiring."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from functools import wraps
from pathlib import Path

import httpx
import pytest

from bidding_compliance.model_gateway import ModelRequest
from bidding_compliance.model_gateway.errors import GatewayErrorCode, ModelGatewayError
from scripts.task0021_online_runtime import (
    MAX_DEMO_BUDGET,
    PROMPT_VERSION,
    OneShotBudgetLedger,
    SyntheticTenderMinimizer,
    create_online_gateway,
    online_policy,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/schemas/semantic-analysis.schema.json").read_text())
SYNTHETIC_DOC_SHA = "d" * 64
QUOTE = "本项目仅接受在示例市注册的投标人。"
QUOTE_HASH = hashlib.sha256(QUOTE.encode("utf-8")).hexdigest()
CANDIDATE_ID = "a" * 64
TASK_ID = "task0021-task-1"
NODE_RUN = "task0021-run-1:semantic:0123456789ab"
CALL_ID = hashlib.sha256(f"tenant-a:{TASK_ID}:task0021-run-1:semantic".encode()).hexdigest()
REQUEST = ModelRequest(
    call_id=CALL_ID,
    tenant_id="tenant-a",
    review_task_id=TASK_ID,
    node_run_id=NODE_RUN,
    prompt_version=PROMPT_VERSION,
    system_instruction="ignored in favor of approved prompt",
    input_payload={
        "snapshot_hash": "f" * 64,
        "project_context": {"customer": "must-not-send"},
        "document_candidates": {
            "candidates": [
                {
                    "candidate_id": CANDIDATE_ID,
                    "category": "qualification",
                    "skill_id": "qualification_review",
                    "rule_id": "qualification.locality",
                    "matched_reason": "must-not-send",
                    "source_excerpts": [
                        {
                            "document_id": "synthetic-doc-1",
                            "document_sha256": SYNTHETIC_DOC_SHA,
                            "section_id": "section-1",
                            "section_revision": 1,
                            "locator": "paragraph:1",
                            "page": None,
                            "bbox": None,
                            "coordinate_system": "ooxml",
                            "quote": QUOTE,
                            "quote_sha256": QUOTE_HASH,
                        }
                    ],
                }
            ]
        },
        "legal_retrieval": {"body": "不得发送的法规原文"},
        "candidate_legal_evidence": {"law": "不得发送的法规引文"},
    },
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _provider_response() -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "schema_version": "v1alpha1",
                            "findings": [
                                {
                                    "candidate_id": CANDIDATE_ID,
                                    "assessment": "potential_issue",
                                    "title": "synthetic semantic result",
                                    "description": "Qwen response used by local merge.",
                                    "severity": "medium",
                                    "source_quote_sha256": [QUOTE_HASH],
                                    "legal_evidence_ids": [],
                                    "recommendation": "由人工复核该合成候选",
                                    "reasoning_summary": "语义分析，不构成法律结论",
                                    "confidence": 0.4,
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 200, "completion_tokens": 100},
    }


@async_test
async def test_T0021_002_gateway_minimizes_local_rag_and_records_metadata_only(tmp_path: Path):
    captured: list[dict] = []

    def send(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_provider_response())

    audit_path = tmp_path / "model-audit.jsonl"
    gateway, authorization = create_online_gateway(
        api_key="mock-key",
        workspace_id="workspace-123",
        allowed_document_sha256=SYNTHETIC_DOC_SHA,
        audit_path=audit_path,
        transport=httpx.MockTransport(send),
    )
    authorization.trusted_calls[CALL_ID] = ("tenant-a", TASK_ID, NODE_RUN)
    result = await gateway.generate_structured(REQUEST, SCHEMA, online_policy())
    assert result.provider == "bailian" and result.model == "qwen3.8-flash"
    assert result.content["findings"][0]["title"] == "synthetic semantic result"
    assert len(captured) == 1
    body_text = json.dumps(captured[0], ensure_ascii=False)
    assert QUOTE in body_text
    assert "不得发送的法规原文" not in body_text
    assert "不得发送的法规引文" not in body_text
    assert "must-not-send" not in body_text
    assert "snapshot_hash" not in body_text
    assert "project_context" not in body_text
    assert "legal_retrieval" not in body_text
    assert "candidate_legal_evidence" not in body_text
    audit = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert audit["provider"] == "bailian"
    assert audit["model"] == "qwen3.8-flash"
    assert audit["estimated_cost"] == "0.00043"
    assert audit["fallback_path"] == [] and audit["retries"] == 0
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "mock-key" not in audit_text
    assert QUOTE not in audit_text
    assert "不得发送的法规原文" not in audit_text


@async_test
async def test_T0021_002_minimizer_rejects_other_document_hash_and_law_payload():
    minimizer = SyntheticTenderMinimizer(SYNTHETIC_DOC_SHA)
    bad_payload = json.loads(json.dumps(REQUEST.input_payload))
    bad_payload["document_candidates"]["candidates"][0]["source_excerpts"][0]["document_sha256"] = (
        "e" * 64
    )
    with pytest.raises(ValueError, match="approved synthetic file"):
        minimizer(bad_payload, online_policy().data_policy)
    with pytest.raises(ValueError, match="only explicitly public"):
        minimizer(REQUEST.input_payload, "confidential")


@async_test
async def test_T0021_002_gateway_rejects_whitelist_payload_over_2048_bytes_before_provider(
    tmp_path: Path,
):
    calls = 0

    def send(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_provider_response())

    oversized = json.loads(json.dumps(REQUEST.input_payload))
    excerpt = oversized["document_candidates"]["candidates"][0]["source_excerpts"][0]
    excerpt["quote"] = "x" * 1900
    excerpt["quote_sha256"] = hashlib.sha256(excerpt["quote"].encode("utf-8")).hexdigest()
    gateway, authorization = create_online_gateway(
        api_key="mock-key",
        workspace_id="workspace-123",
        allowed_document_sha256=SYNTHETIC_DOC_SHA,
        audit_path=tmp_path / "oversized-input.jsonl",
        transport=httpx.MockTransport(send),
    )
    authorization.trusted_calls[CALL_ID] = ("tenant-a", TASK_ID, NODE_RUN)
    request = replace(REQUEST, input_payload=oversized)

    with pytest.raises(ModelGatewayError) as error:
        await gateway.generate_structured(request, SCHEMA, online_policy())
    assert error.value.code is GatewayErrorCode.INPUT_INVALID
    assert calls == 0


@async_test
async def test_T0021_002_gateway_rejects_untrusted_call_before_provider_request(tmp_path: Path):
    calls = 0

    def send(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_provider_response())

    gateway, _authorization = create_online_gateway(
        api_key="x",
        workspace_id="workspace-123",
        allowed_document_sha256=SYNTHETIC_DOC_SHA,
        audit_path=tmp_path / "untrusted.jsonl",
        transport=httpx.MockTransport(send),
    )
    with pytest.raises(ModelGatewayError) as error:
        await gateway.generate_structured(REQUEST, SCHEMA, online_policy())
    assert error.value.code is GatewayErrorCode.INPUT_INVALID
    assert calls == 0


@async_test
async def test_T0021_003_provider_failure_is_terminal_without_mock_fallback(tmp_path: Path):
    requests: list[httpx.Request] = []

    def send(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, text="private provider response")

    gateway, authorization = create_online_gateway(
        api_key="x",
        workspace_id="workspace-123",
        allowed_document_sha256=SYNTHETIC_DOC_SHA,
        audit_path=tmp_path / "provider-failure.jsonl",
        transport=httpx.MockTransport(send),
    )
    authorization.trusted_calls[CALL_ID] = ("tenant-a", TASK_ID, NODE_RUN)
    with pytest.raises(ModelGatewayError) as error:
        await gateway.generate_structured(REQUEST, SCHEMA, online_policy())
    assert error.value.code is GatewayErrorCode.PROVIDER_UNAVAILABLE
    assert len(requests) == 1
    audit = json.loads((tmp_path / "provider-failure.jsonl").read_text(encoding="utf-8"))
    assert audit["provider"] == "bailian"
    assert audit["failure_category"] == GatewayErrorCode.PROVIDER_UNAVAILABLE.value
    assert audit["fallback_path"] == []
    assert audit["response_hash"] is None


def test_T0021_002_one_shot_budget_denies_every_reservation_after_first():
    ledger = OneShotBudgetLedger()
    reservation = ledger.reserve("tenant-a", TASK_ID, Decimal("0.0093454"))
    assert MAX_DEMO_BUDGET == Decimal("0.10")
    assert reservation.amount == Decimal("0.10")
    ledger.settle(reservation, Decimal("0.10"))
    with pytest.raises(ModelGatewayError) as error:
        ledger.reserve("tenant-a", "another-task", MAX_DEMO_BUDGET)
    assert error.value.code is GatewayErrorCode.BUDGET_EXCEEDED


def test_T0021_002_one_shot_budget_rejects_a_quote_over_the_approved_cap():
    ledger = OneShotBudgetLedger()
    with pytest.raises(ModelGatewayError) as error:
        ledger.reserve("tenant-a", TASK_ID, Decimal("0.100001"))
    assert error.value.code is GatewayErrorCode.BUDGET_EXCEEDED
