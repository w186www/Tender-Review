"""Provider-neutral, content-free errors for the model gateway."""

from __future__ import annotations

from enum import StrEnum


class GatewayErrorCode(StrEnum):
    INPUT_INVALID = "input_invalid"
    SCHEMA_INVALID = "schema_invalid"
    PROVIDER_UNAUTHORIZED = "provider_unauthorized"
    DATA_POLICY_REJECTED = "data_policy_rejected"
    BUDGET_EXCEEDED = "budget_exceeded"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_ERROR = "provider_error"
    RESPONSE_INVALID = "response_invalid"
    CANCELLED = "cancelled"
    AUDIT_FAILED = "audit_failed"


class ModelGatewayError(Exception):
    """Safe-to-surface failure; never includes prompts, headers, or provider bodies."""

    def __init__(
        self,
        code: GatewayErrorCode,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
