"""Provider-neutral embeddings, with explicitly guarded live Bailian requests."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Callable, Sequence
from decimal import Decimal
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


class EmbeddingCallGuard(Protocol):
    """Trusted authorization/budget scope shared with the chat runtime.

    Reservation validates the exact, pre-authorized request hash and charges an
    attempt before transport. Unsettled reservations retain their full ceiling.
    """

    def reserve_external(self, *, kind: str, request_hash: str, ceiling: Decimal) -> str: ...

    def settle_external(self, reservation: str, actual: Decimal) -> None: ...


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
    """Credentials are explicit backend injections; nothing reads the environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    region: str = Field(pattern=r"^(beijing|singapore)$")
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    model_id: str = Field(pattern=r"^(qwen3\.7-text-embedding|text-embedding-v4)$")
    dimensions: int = Field(ge=1, le=8192)
    timeout_seconds: float = Field(default=10, gt=0, le=60)
    max_text_utf8_bytes: int = Field(default=8192, ge=1, le=8192)
    max_batch_utf8_bytes: int = Field(default=32768, ge=1, le=81920)
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
    """One bounded attempt; real transport requires authorization, budget and audit."""

    @staticmethod
    def _mock_client_only(client: httpx.Client) -> bool:
        return isinstance(getattr(client, "_transport", None), httpx.MockTransport) and all(
            mounted is None or isinstance(mounted, httpx.MockTransport)
            for mounted in getattr(client, "_mounts", {}).values()
        )

    def __init__(
        self,
        settings: DashScopeEmbeddingSettings,
        *,
        client: httpx.Client | None = None,
        guard: EmbeddingCallGuard | None = None,
        audit_sink: Callable[[dict[str, object]], None] | None = None,
        input_price_per_million: Decimal | None = None,
    ) -> None:
        self.settings = settings
        self.identity = settings.identity()
        self.max_batch_items = MODEL_MAX_BATCH_ITEMS[settings.model_id]
        self._client = client
        self._guard = guard
        self._audit_sink = audit_sink
        self._input_price = input_price_per_million
        self._semaphore = threading.BoundedSemaphore(1)
        self._live = client is not None and not self._mock_client_only(client)
        self.execution_mode = "online" if self._live else "mock_contract"
        identity_values = self.identity.model_dump(exclude={"identity_sha256"})
        identity_values["parameters"] = {
            **self.identity.parameters, "execution_mode": self.execution_mode
        }
        self.identity = EmbeddingModelIdentity.create(**identity_values)
        if settings.enabled:
            if client is None:
                raise ValueError("an explicitly injected HTTP client is required")
            if self._live and (guard is None or audit_sink is None):
                raise ValueError("MockTransport only unless a trusted guard and audit are injected")
            if self._live and (
                settings.region != "beijing"
                or input_price_per_million is None
                or not input_price_per_million.is_finite()
                or input_price_per_million <= 0
            ):
                raise ValueError("live embedding requires Beijing and explicit positive pricing")
            if self._live and getattr(client, "_trust_env", True):
                raise ValueError("live embedding client must disable environment proxy injection")

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
        if not self._semaphore.acquire(timeout=self.settings.timeout_seconds):
            raise EmbeddingTimeout()
        attempt: dict[str, object] = {}
        try:
            return self._embed(texts, attempt)
        except Exception as exc:
            if attempt and self._audit_sink is not None:
                self._audit_sink({
                    "event": "embedding.request_failed",
                    **attempt,
                    "failure_category": (
                        exc.code if isinstance(exc, EmbeddingProviderError) else "EMBEDDING_FAILED"
                    ),
                    "reserved_cost_cny": "0.10",
                    "retries": 0,
                })
            raise
        finally:
            self._semaphore.release()

    def _embed(self, texts: Sequence[str], attempt: dict[str, object]) -> list[list[float]]:
        if not self.settings.enabled:
            raise EmbeddingProviderError("EMBEDDING_PROVIDER_DISABLED")
        if (
            self._client is None
            or self.settings.api_key is None
            or not self.settings.api_key.get_secret_value().strip()
        ):
            raise EmbeddingAuthorizationError()
        if self._live == self._mock_client_only(self._client):
            raise EmbeddingAuthorizationError()
        values = list(texts)
        if not values:
            return []
        if len(values) > self.max_batch_items or any(
            not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > self.settings.max_text_utf8_bytes
            for text in values
        ):
            raise EmbeddingProtocolError()
        if sum(len(text.encode("utf-8")) for text in values) > self.settings.max_batch_utf8_bytes:
            raise EmbeddingProtocolError()
        request_payload = {
            "model": self.settings.model_id,
            "input": values,
            "dimensions": self.settings.dimensions,
            "encoding_format": "float",
        }
        canonical_request = json.dumps(
            request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        request_hash = hashlib.sha256(canonical_request).hexdigest()
        reservation = None
        started = time.monotonic()
        if self._live:
            assert self._guard is not None and self._audit_sink is not None
            assert self._input_price is not None
            token_ceiling = sum(len(text.encode("utf-8")) for text in values)
            if Decimal(token_ceiling) * self._input_price / Decimal(1_000_000) > Decimal("0.10"):
                raise EmbeddingProviderError("EMBEDDING_BUDGET_EXCEEDED")
            reservation = self._guard.reserve_external(
                kind="embedding", request_hash=request_hash, ceiling=Decimal("0.10")
            )
            attempt.update(request_hash=request_hash, reservation_id=reservation)
            self._audit_sink(
                {
                    "event": "embedding.request_reserved",
                    "request_hash": request_hash,
                    "reservation_id": reservation,
                    "identity_sha256": self.identity.identity_sha256,
                    "provider": "dashscope",
                    "model": self.settings.model_id,
                    "mode": "online",
                    "items": len(values),
                    "input_utf8_bytes": sum(len(text.encode("utf-8")) for text in values),
                    "reserved_cost_cny": "0.10",
                }
            )
        try:
            response = self._client.post(
                self.settings.endpoint,
                headers={
                    "Authorization": "Bearer " + self.settings.api_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=self.settings.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise EmbeddingTimeout() from None
        except httpx.TransportError:
            raise EmbeddingProviderUnavailable() from None

        if 300 <= response.status_code < 400:
            raise EmbeddingProtocolError()
        if len(response.content) > self.max_batch_items * self.settings.dimensions * 32 + 65536:
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
        if self._live:
            assert self._input_price is not None and self._audit_sink is not None
            assert self._guard is not None and reservation is not None
            # UTF-8 bytes are the conservative input token ceiling used before
            # transport. Unexpected usage fails closed and retains the reservation.
            if total_tokens > sum(len(text.encode("utf-8")) for text in values):
                raise EmbeddingProtocolError(request_id)
            actual = Decimal(total_tokens) * self._input_price / Decimal(1_000_000)
            if actual > Decimal("0.10"):
                raise EmbeddingProtocolError(request_id)
            self._audit_sink(
                {
                    "event": "embedding.response_validated",
                    "request_hash": request_hash,
                    "reservation_id": reservation,
                    "identity_sha256": self.identity.identity_sha256,
                    "provider": "dashscope",
                    "model": self.settings.model_id,
                    "mode": "online",
                    "request_id": request_id,
                    "response_hash": hashlib.sha256(response.content).hexdigest(),
                    "total_tokens": total_tokens,
                    "estimated_cost_cny": str(actual),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "retries": 0,
                }
            )
            self._guard.settle_external(reservation, actual)
        return [item for item in result if item is not None]

    @staticmethod
    def _header_request_id(response: httpx.Response) -> str | None:
        value = response.headers.get("x-request-id") or response.headers.get("request-id")
        return value if value and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) else None
