"""Provider-neutral embedding port and a MockTransport-only Bailian contract adapter."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .contracts import EmbeddingModelIdentity


class EmbeddingProviderError(RuntimeError):
    """Sanitized provider failure; never retains request bodies or credentials."""

    def __init__(self, code: str, request_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.request_id = request_id


class EmbeddingTimeout(EmbeddingProviderError):
    def __init__(self) -> None:
        super().__init__("EMBEDDING_TIMEOUT")


class EmbeddingRateLimited(EmbeddingProviderError):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("EMBEDDING_RATE_LIMITED", request_id)


class EmbeddingAuthorizationError(EmbeddingProviderError):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("EMBEDDING_AUTHORIZATION_FAILED", request_id)


class EmbeddingProviderUnavailable(EmbeddingProviderError):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("EMBEDDING_PROVIDER_UNAVAILABLE", request_id)


class EmbeddingProtocolError(EmbeddingProviderError):
    def __init__(self, request_id: str | None = None) -> None:
        super().__init__("EMBEDDING_RESPONSE_INVALID", request_id)


class EmbeddingProvider(Protocol):
    identity: EmbeddingModelIdentity

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


MODEL_DIMENSIONS: dict[str, frozenset[int]] = {
    "qwen3.7-text-embedding": frozenset({256, 512, 768, 1024, 1536, 2048, 2560}),
    "text-embedding-v4": frozenset({64, 128, 256, 512, 768, 1024, 1536, 2048}),
}
MODEL_MAX_BATCH_ITEMS: dict[str, int] = {
    "qwen3.7-text-embedding": 20,
    "text-embedding-v4": 10,
}

REGION_HOSTS = {
    "beijing": "cn-beijing.maas.aliyuncs.com",
    "singapore": "ap-southeast-1.maas.aliyuncs.com",
}


def character_embedding_identity() -> EmbeddingModelIdentity:
    """Identity for the measured, existing sparse CharacterEmbedding implementation."""
    return EmbeddingModelIdentity.create(
        provider="character",
        region="local",
        model_id="character-bigram-1",
        model_revision="character-bigram-1",
        dimensions=None,
        tokenizer_identity="bidding-compliance.legal.retrieval.terms-v1",
        weights_sha256=None,
        tokenizer_sha256=None,
        api_contract_version="internal-sparse-embedding-v1",
        parameters={"tokenization": "CJK-bigrams-lowercase-latin", "normalization": "cosine"},
    )


class DashScopeEmbeddingSettings(BaseModel):
    """Non-secret provider settings; enabled remains false for this task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    region: str = Field(pattern=r"^(beijing|singapore)$")
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    model_id: str = Field(pattern=r"^(qwen3\.7-text-embedding|text-embedding-v4)$")
    dimensions: int = Field(ge=1, le=8192)
    timeout_seconds: float = Field(default=10, gt=0, le=60)
    api_key: SecretStr | None = Field(default=None, repr=False, exclude=True)

    @model_validator(mode="after")
    def supported_dimensions(self) -> DashScopeEmbeddingSettings:
        if self.dimensions not in MODEL_DIMENSIONS[self.model_id]:
            raise ValueError("dimensions are not supported by the selected model")
        return self

    @property
    def endpoint(self) -> str:
        host = REGION_HOSTS[self.region]
        return f"https://{self.workspace_id}.{host}/compatible-mode/v1/embeddings"

    def identity(self) -> EmbeddingModelIdentity:
        return EmbeddingModelIdentity.create(
            provider="dashscope",
            region=self.region,
            model_id=self.model_id,
            model_revision="provider-managed-unversioned",
            dimensions=self.dimensions,
            tokenizer_identity="provider-managed-unversioned",
            weights_sha256=None,
            tokenizer_sha256=None,
            api_contract_version="openai-compatible-embeddings-v1",
            parameters={"dimensions": self.dimensions, "encoding_format": "float"},
        )


class DashScopeEmbeddingProvider:
    """Contract-tested adapter; this release accepts only an injected MockTransport."""

    def __init__(
        self,
        settings: DashScopeEmbeddingSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.identity = settings.identity()
        self.max_batch_items = MODEL_MAX_BATCH_ITEMS[settings.model_id]
        self._client = client
        if settings.enabled:
            if client is None:
                raise ValueError("an explicitly injected HTTP client is required")
            if not isinstance(getattr(client, "_transport", None), httpx.MockTransport):
                raise ValueError("TASK-0018 permits MockTransport only; live HTTP is disabled")

    @staticmethod
    def _request_id(payload: object) -> str | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get("request_id", payload.get("id"))
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value)
            else None
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.settings.enabled:
            raise EmbeddingProviderError("EMBEDDING_PROVIDER_DISABLED")
        if self._client is None or self.settings.api_key is None:
            raise EmbeddingAuthorizationError()
        values = list(texts)
        if not values:
            return []
        if len(values) > self.max_batch_items or any(not text.strip() for text in values):
            raise EmbeddingProtocolError()
        try:
            response = self._client.post(
                self.settings.endpoint,
                headers={
                    "Authorization": "Bearer " + self.settings.api_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.settings.model_id,
                    "input": values,
                    "dimensions": self.settings.dimensions,
                    "encoding_format": "float",
                },
                timeout=self.settings.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise EmbeddingTimeout() from exc
        except httpx.TransportError as exc:
            raise EmbeddingProviderUnavailable() from exc

        if 300 <= response.status_code < 400:
            raise EmbeddingProtocolError()
        try:
            payload = response.json()
        except ValueError:
            payload = None
        request_id = self._request_id(payload) or self._header_request_id(response)
        if response.status_code in {401, 403}:
            raise EmbeddingAuthorizationError(request_id)
        if response.status_code == 429:
            raise EmbeddingRateLimited(request_id)
        if response.status_code == 408:
            raise EmbeddingTimeout()
        if response.status_code >= 500:
            raise EmbeddingProviderUnavailable(request_id)
        if response.status_code >= 400:
            raise EmbeddingProtocolError(request_id)
        if (
            not isinstance(payload, dict)
            or payload.get("model") != self.settings.model_id
            or payload.get("object") != "list"
        ):
            raise EmbeddingProtocolError(request_id)
        usage = payload.get("usage")
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        if (
            not isinstance(usage, dict)
            or not isinstance(total_tokens, int)
            or isinstance(total_tokens, bool)
            or total_tokens < 0
            or (
                prompt_tokens is not None
                and (
                    not isinstance(prompt_tokens, int)
                    or isinstance(prompt_tokens, bool)
                    or prompt_tokens != total_tokens
                )
            )
            or not isinstance(payload.get("id"), str)
            or self._request_id(payload) is None
        ):
            raise EmbeddingProtocolError(request_id)
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) != len(values):
            raise EmbeddingProtocolError(request_id)
        result: list[list[float] | None] = [None] * len(values)
        for row in rows:
            if not isinstance(row, dict):
                raise EmbeddingProtocolError(request_id)
            index, vector = row.get("index"), row.get("embedding")
            if (
                row.get("object") != "embedding"
                or not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < len(values)
                or result[index] is not None
                or not isinstance(vector, list)
                or len(vector) != self.settings.dimensions
                or any(
                    not isinstance(item, (int, float))
                    or isinstance(item, bool)
                    or not math.isfinite(float(item))
                    for item in vector
                )
            ):
                raise EmbeddingProtocolError(request_id)
            result[index] = [float(item) for item in vector]
        if any(item is None for item in result):
            raise EmbeddingProtocolError(request_id)
        return [item for item in result if item is not None]

    @staticmethod
    def _header_request_id(response: httpx.Response) -> str | None:
        value = response.headers.get("x-request-id") or response.headers.get("request-id")
        return value if value and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) else None
