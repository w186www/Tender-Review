"""TASK-0021 contract tests for the official Bailian Chat Completions protocol."""

from __future__ import annotations

import asyncio
import hashlib
import json
from functools import wraps
from pathlib import Path

import httpx
import pytest

from bidding_compliance.model_gateway import DataPolicy, ModelPolicy, ModelRequest
from bidding_compliance.model_gateway.adapters.bailian_qwen_adapter import (
    BailianQwenChatAdapter,
    _qwen_json_schema,
)
from bidding_compliance.model_gateway.errors import GatewayErrorCode, ModelGatewayError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/schemas/semantic-analysis.schema.json").read_text())
CONTENT = {"schema_version": "v1alpha1", "findings": []}
REQUEST = ModelRequest(
    call_id="task0021-call-1",
    tenant_id="tenant-a",
    review_task_id="task0021-task-1",
    node_run_id="task0021-run-1:semantic:0123456789ab",
    prompt_version="task0021-qwen-synthetic-v1",
    system_instruction="Analyze only the approved synthetic excerpt.",
    input_payload={"dataset_id": "task0021-synthetic-tender-v1", "candidates": []},
)
POLICY = ModelPolicy(
    profile="task0021-online-qwen",
    timeout_seconds=1,
    max_attempts=1,
    max_input_tokens=8192,
    max_output_tokens=1024,
    temperature=0,
    data_policy=DataPolicy.PUBLIC,
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def response_body(content: object = CONTENT, *, finish_reason: str = "stop") -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(content, ensure_ascii=False),
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 31, "completion_tokens": 7},
    }


def test_T0021_001_qwen_schema_is_narrowed_only_for_the_provider_wire_schema() -> None:
    provider_schema = _qwen_json_schema(SCHEMA)
    assert provider_schema["$defs"]["finding"]["required"] == sorted(
        SCHEMA["$defs"]["finding"]["required"] + ["confidence"]
    )
    assert "uniqueItems" not in json.dumps(provider_schema)
    assert SCHEMA["$defs"]["finding"]["properties"]["source_quote_sha256"]["uniqueItems"]
    assert SCHEMA["$defs"]["finding"]["properties"]["legal_evidence_ids"]["uniqueItems"]


@async_test
async def test_T0021_001_qwen_chat_round_trip_uses_fixed_beijing_workspace_and_json_schema():
    captured = {}

    def send(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=response_body())

    adapter = BailianQwenChatAdapter(
        "test-secret-never-log",
        "workspace-123",
        transport=httpx.MockTransport(send),
    )
    result = await adapter.generate(REQUEST, SCHEMA, POLICY, "qwen3.8-flash")
    assert captured["url"] == (
        "https://workspace-123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert "api.openai.com" not in captured["url"]
    assert captured["headers"]["authorization"] == "Bearer test-secret-never-log"
    body = captured["body"]
    assert body["model"] == "qwen3.8-flash"
    assert body["enable_thinking"] is False
    assert body["max_completion_tokens"] == 1024
    assert body["stream"] is False
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "uniqueItems" not in json.dumps(body["response_format"]["json_schema"]["schema"])
    assert result.content == CONTENT
    assert result.usage.input_tokens == 31 and result.usage.output_tokens == 7
    assert result.finish_reason == "stop"


@pytest.mark.parametrize(
    "key,workspace,model",
    [
        (None, "workspace-123", "qwen3.8-flash"),
        ("secret", "https://api.openai.com", "qwen3.8-flash"),
        ("secret", "workspace-123", "text-embedding-v3"),
    ],
)
@async_test
async def test_T0021_001_missing_credentials_unsafe_workspace_or_wrong_model_fail_closed(
    key, workspace, model
):
    def unexpected(_request):
        pytest.fail("invalid configuration must not make an HTTP request")

    adapter = BailianQwenChatAdapter(key, workspace, transport=httpx.MockTransport(unexpected))
    with pytest.raises(ModelGatewayError) as error:
        await adapter.generate(REQUEST, SCHEMA, POLICY, model)
    assert error.value.code is GatewayErrorCode.PROVIDER_UNAUTHORIZED


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, GatewayErrorCode.PROVIDER_UNAUTHORIZED),
        (403, GatewayErrorCode.PROVIDER_UNAUTHORIZED),
        (408, GatewayErrorCode.TIMEOUT),
        (429, GatewayErrorCode.RATE_LIMITED),
        (503, GatewayErrorCode.PROVIDER_UNAVAILABLE),
        (504, GatewayErrorCode.TIMEOUT),
    ],
)
@async_test
async def test_T0021_001_http_failures_are_sanitized(status, expected, caplog):
    adapter = BailianQwenChatAdapter(
        "secret-do-not-log",
        "workspace-123",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status, text="private provider body")
        ),
    )
    with pytest.raises(ModelGatewayError) as error:
        await adapter.generate(REQUEST, SCHEMA, POLICY, "qwen3.8-flash")
    assert error.value.code is expected
    assert "private provider body" not in str(error.value)
    assert "secret-do-not-log" not in caplog.text


@async_test
async def test_T0021_001_transport_timeout_is_sanitized_and_typed(caplog):
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail")

    adapter = BailianQwenChatAdapter(
        "secret-do-not-log", "workspace-123", transport=httpx.MockTransport(timeout)
    )
    with pytest.raises(ModelGatewayError) as error:
        await adapter.generate(REQUEST, SCHEMA, POLICY, "qwen3.8-flash")
    assert error.value.code is GatewayErrorCode.TIMEOUT
    assert "private timeout detail" not in str(error.value)
    assert "secret-do-not-log" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {
            "choices": [{"message": {"content": "{}"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
        {
            "choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
        {
            "choices": [
                {"message": {"content": "{}", "refusal": "refused"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
        {
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": True, "completion_tokens": 1},
        },
    ],
)
@async_test
async def test_T0021_001_malformed_truncated_or_non_schema_output_is_rejected(body):
    adapter = BailianQwenChatAdapter(
        "secret",
        "workspace-123",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)),
    )
    with pytest.raises(ModelGatewayError) as error:
        await adapter.generate(REQUEST, SCHEMA, POLICY, "qwen3.8-flash")
    assert error.value.code is GatewayErrorCode.RESPONSE_INVALID


@async_test
async def test_T0021_001_provider_schema_unique_items_omission_does_not_disable_local_rejection():
    quote = "合成条款"
    quote_hash = hashlib.sha256(quote.encode()).hexdigest()
    finding = {
        "candidate_id": "a" * 64,
        "assessment": "potential_issue",
        "title": "synthetic semantic finding",
        "description": "semantic analysis result",
        "severity": "medium",
        "source_quote_sha256": [quote_hash, quote_hash],
        "legal_evidence_ids": [],
        "recommendation": "由人工复核",
        "reasoning_summary": "合成输入判断",
        "confidence": None,
    }
    output = {"schema_version": "v1alpha1", "findings": [finding]}
    adapter = BailianQwenChatAdapter(
        "secret",
        "workspace-123",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=response_body(output))
        ),
    )
    with pytest.raises(ModelGatewayError) as error:
        await adapter.generate(REQUEST, SCHEMA, POLICY, "qwen3.8-flash")
    assert error.value.code is GatewayErrorCode.RESPONSE_INVALID
