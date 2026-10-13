"""Stable data contracts shared by model adapters and business nodes."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

JsonObject = Mapping[str, Any]


class DataPolicy(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


def _positive_tokens(value: int | None, name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
        raise ValueError(f"{name} must be a positive integer")


def _identifier(value: str, name: str, maximum: int = 128) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a nonempty string of at most {maximum} characters")


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    """Runtime controls that an adapter must enforce or report as unsupported."""

    profile: str
    timeout_seconds: float
    max_attempts: int = 2
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    temperature: float = 0.0
    data_policy: DataPolicy = DataPolicy.CONFIDENTIAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_policy", DataPolicy(self.data_policy))
        _identifier(self.profile, "profile", 100)
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= 3
        ):
            raise ValueError("max_attempts must be between 1 and 3")
        if not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        _positive_tokens(self.max_input_tokens, "max_input_tokens")
        _positive_tokens(self.max_output_tokens, "max_output_tokens")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A minimal request with explicit provenance and no provider fields."""

    call_id: str
    tenant_id: str
    review_task_id: str
    node_run_id: str
    prompt_version: str
    system_instruction: str
    input_payload: JsonObject
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = {
            "call_id": self.call_id,
            "tenant_id": self.tenant_id,
            "review_task_id": self.review_task_id,
            "node_run_id": self.node_run_id,
            "prompt_version": self.prompt_version,
        }
        for name, value in required.items():
            _identifier(value, name)


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    estimated_cost: float | None = None

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.input_tokens, self.output_tokens)
        ):
            raise ValueError("token usage must not be negative")
        if self.estimated_cost is not None and (
            not math.isfinite(self.estimated_cost) or self.estimated_cost < 0
        ):
            raise ValueError("estimated_cost must not be negative")


@dataclass(frozen=True, slots=True)
class ModelResponse:
    call_id: str
    provider: str
    model: str
    profile: str
    content: JsonObject
    usage: ModelUsage
    latency_ms: int
    response_hash: str
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("call_id", self.call_id, 128),
            ("provider", self.provider, 100),
            ("model", self.model, 200),
            ("profile", self.profile, 100),
        ):
            _identifier(value, name, maximum)
        if (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, int)
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must not be negative")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", self.response_hash):
            raise ValueError("response_hash must be a SHA-256 hexadecimal digest")
        if self.finish_reason is not None and len(self.finish_reason) > 100:
            raise ValueError("finish_reason must not exceed 100 characters")
