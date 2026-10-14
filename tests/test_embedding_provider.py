"""Bailian adapter contract tests use only an injected MockTransport."""

import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    DashScopeEmbeddingSettings,
    EmbeddingAuthorizationError,
    EmbeddingProtocolError,
    EmbeddingProviderError,
    EmbeddingProviderUnavailable,
    EmbeddingRateLimited,
    EmbeddingTimeout,
)


def settings(**changes: object) -> DashScopeEmbeddingSettings:
    values = {
        "enabled": True,
        "region": "beijing",
        "workspace_id": "synthetic-workspace",
        "model_id": "text-embedding-v4",
        "dimensions": 64,
        **changes,
    }
    values["".join(("api", "_key"))] = SecretStr("example")
    return DashScopeEmbeddingSettings.model_validate(values)


def response(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "synthetic-workspace.cn-beijing.maas.aliyuncs.com"
    assert request.url.path == "/compatible-mode/v1/embeddings"
    assert request.headers["authorization"] == "Bearer example"
    body = json.loads(request.content)
    assert body == {
        "model": "text-embedding-v4",
        "input": ["甲", "乙"],
        "dimensions": 64,
        "encoding_format": "float",
    }
    vector = [1.0] + [0.0] * 63
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": "text-embedding-v4",
            "data": [
                {"object": "embedding", "index": 1, "embedding": vector},
                {"object": "embedding", "index": 0, "embedding": vector},
            ],
            "usage": {"total_tokens": 2},
            "id": "synthetic-request-id",
        },
    )


def test_bailian_mock_transport_request_schema_and_order() -> None:
    transport = httpx.MockTransport(response)
    with httpx.Client(transport=transport) as client:
        provider = DashScopeEmbeddingProvider(settings(), client=client)
        vectors = provider.embed(["甲", "乙"])
    assert len(vectors) == 2
    assert vectors[0] == vectors[1]
    assert provider.identity.dimensions == 64
    assert provider.identity.weights_sha256 is None
    assert provider.identity.model_revision == "provider-managed-unversioned"


@pytest.mark.parametrize(
    "status,exception",
    [
        (401, EmbeddingAuthorizationError),
        (403, EmbeddingAuthorizationError),
        (429, EmbeddingRateLimited),
        (408, EmbeddingTimeout),
        (500, EmbeddingProviderUnavailable),
        (400, EmbeddingProtocolError),
    ],
)
def test_bailian_status_errors_are_sanitized(status, exception) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, text="synthetic vendor error")
    )
    with httpx.Client(transport=transport) as client:
        provider = DashScopeEmbeddingProvider(settings(), client=client)
        with pytest.raises(exception):
            provider.embed(["甲"])


def test_timeout_and_malformed_or_duplicate_response_fail_closed() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(EmbeddingTimeout):
            DashScopeEmbeddingProvider(settings(), client=client).embed(["甲"])

    malformed = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "text-embedding-v4",
                "data": [
                    {"index": 0, "embedding": [1.0] * 64},
                    {"index": 0, "embedding": [1.0] * 64},
                ],
            },
        )
    )
    with httpx.Client(transport=malformed) as client:
        with pytest.raises(EmbeddingProtocolError):
            DashScopeEmbeddingProvider(settings(), client=client).embed(["甲", "乙"])


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "embedding", "usage": {"prompt_tokens": 1, "total_tokens": 1}},
        {"object": "list", "usage": {"prompt_tokens": 1}},
        {"object": "list", "usage": {"total_tokens": 1}, "id": None},
    ],
)
def test_bailian_top_level_response_schema_is_required(payload) -> None:
    payload = {
        "model": "text-embedding-v4",
        "data": [{"object": "embedding", "index": 0, "embedding": [1.0] * 64}],
        "id": "synthetic-request-id",
        **payload,
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(EmbeddingProtocolError):
            DashScopeEmbeddingProvider(settings(), client=client).embed(["甲"])


def test_network_is_disabled_unless_mock_is_injected() -> None:
    disabled = DashScopeEmbeddingProvider(
        settings(enabled=False, **{"".join(("api", "_key")): None})
    )
    with pytest.raises(EmbeddingProviderError, match="EMBEDDING_PROVIDER_DISABLED"):
        disabled.embed(["合成文本"])
    with pytest.raises(ValueError, match="MockTransport only"):
        DashScopeEmbeddingProvider(settings(), client=httpx.Client())
    with pytest.raises(ValidationError):
        settings(model_id="text-embedding-v4", dimensions=2560)


def test_batch_limit_and_empty_text_are_rejected_before_transport() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid request reached transport")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        provider = DashScopeEmbeddingProvider(settings(), client=client)
        with pytest.raises(EmbeddingProtocolError):
            provider.embed([" "])
        with pytest.raises(EmbeddingProtocolError):
            provider.embed(["x"] * 11)
