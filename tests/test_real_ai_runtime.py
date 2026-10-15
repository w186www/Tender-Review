"""Actual business runtime assembly: negative egress tests use an explicit fake transport."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from bidding_compliance.model_gateway.contracts import ModelRequest
from bidding_compliance.model_gateway.errors import ModelGatewayError
from bidding_compliance.services.llm_candidate_discovery import discovery_schema
from bidding_compliance.services.real_ai_runtime import (
    DISCOVERY_PROMPT_VERSION,
    create_dec005_gateway,
    real_ai_policy,
)
from bidding_compliance.services.risk_language import unverified_risk_text


def request(document_hash: str = "a" * 64) -> ModelRequest:
    return ModelRequest(
        call_id="bounded-call",
        tenant_id="tenant-a",
        review_task_id="review-task",
        node_run_id="bounded-node",
        prompt_version=DISCOVERY_PROMPT_VERSION,
        system_instruction="client-supplied instructions must be ignored",
        input_payload={
            "discovery_sections": [
                {
                    "section_key": "s000000c000",
                    "document_sha256": document_hash,
                    "text": "条款疑点。联系人：张三，电话：(022)12345678，"
                    "邮箱：person@example.test",
                }
            ]
        },
    )


def configured(tmp_path: Path, calls: list[dict[str, object]]):
    def handle(wire: httpx.Request) -> httpx.Response:
        body = json.loads(wire.content)
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"schema_version": "v1alpha1", "findings": []})
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )

    return create_dec005_gateway(
        api_key="example-only-credential",
        workspace_id="contract-workspace",
        tenant_id="tenant-a",
        allowed_document_sha256=frozenset({"a" * 64}),
        ledger_path=tmp_path / "budget.sqlite",
        audit_path=tmp_path / "audit.jsonl",
        transport=httpx.MockTransport(handle),
    )


def test_real_route_minimizes_and_audits_supplier_response(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    gateway, authorization, budget = configured(tmp_path, calls)
    authorization.trusted_calls["bounded-call"] = ("tenant-a", "review-task", "bounded-node")
    result = asyncio.run(
        gateway.generate_structured(request(), discovery_schema(), real_ai_policy())
    )
    assert result.provider == "bailian" and result.model == "qwen3.8-flash"
    assert result.usage.input_tokens == 100
    body = json.dumps(calls, ensure_ascii=False)
    for private in (
        "张三",
        "12345678",
        "person@example.test",
        "a" * 64,
        "client-supplied instructions",
    ):
        assert private not in body
    audit = (tmp_path / "audit.jsonl").read_text()
    assert "provider_reported" in audit
    assert "example-only-credential" not in audit
    assert budget.summary()["llm_calls"] == 1


@pytest.mark.parametrize("credential,workspace", [("", "space"), ("key", ""), ("", "")])
def test_missing_credentials_cannot_create_online_success(
    tmp_path: Path,
    credential: str,
    workspace: str,
) -> None:
    with pytest.raises(ValueError, match="requires server-side"):
        create_dec005_gateway(
            api_key=credential,
            workspace_id=workspace,
            tenant_id="tenant-a",
            allowed_document_sha256=frozenset({"a" * 64}),
            ledger_path=tmp_path / "budget.sqlite",
            audit_path=tmp_path / "audit.jsonl",
        )
    assert not (tmp_path / "budget.sqlite").exists()


def test_unauthorized_document_is_never_sent(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    gateway, authorization, budget = configured(tmp_path, calls)
    authorization.trusted_calls["bounded-call"] = ("tenant-a", "review-task", "bounded-node")
    with pytest.raises(ModelGatewayError):
        asyncio.run(
            gateway.generate_structured(request("b" * 64), discovery_schema(), real_ai_policy())
        )
    assert not calls and budget.summary()["llm_calls"] == 0


def test_untrusted_run_identity_is_never_sent(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    gateway, _, budget = configured(tmp_path, calls)
    with pytest.raises(ModelGatewayError):
        asyncio.run(gateway.generate_structured(request(), discovery_schema(), real_ai_policy()))
    assert not calls and budget.summary()["llm_calls"] == 0


def test_actual_gateway_refuses_exhausted_shared_budget(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    gateway, authorization, budget = configured(tmp_path, calls)
    authorization.trusted_calls["bounded-call"] = ("tenant-a", "review-task", "bounded-node")
    budget.llm_limit = 0
    with pytest.raises(ModelGatewayError):
        asyncio.run(gateway.generate_structured(request(), discovery_schema(), real_ai_policy()))
    assert not calls


def test_unverified_model_text_cannot_declare_illegality() -> None:
    result = unverified_risk_text(
        "要求额外注册地条件。该条件明确违反政府采购法，构成违法。需核对必要性。"
    )
    assert "要求额外注册地条件" in result and "需核对必要性" in result
    assert "违反" not in result and "违法" not in result
    assert "缺少有效法规支持" in result
