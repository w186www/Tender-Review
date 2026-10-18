"""Explicit server-side model authorization; request metadata is never consulted."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import DataPolicy, ModelRequest
from .errors import GatewayErrorCode, ModelGatewayError


@dataclass(frozen=True, slots=True)
class AuthorizationPolicy:
    # call_id -> (trusted tenant_id, review_task_id, node_run_id), populated by
    # authenticated server-side orchestration. Request fields alone are not identity.
    trusted_calls: dict[str, tuple[str, str, str]]
    tenant_providers: dict[str, frozenset[str]]
    provider_data_policies: dict[str, frozenset[DataPolicy]]

    def authorize(self, request: ModelRequest, provider: str, data_policy: DataPolicy) -> None:
        if self.trusted_calls.get(request.call_id) != (
            request.tenant_id,
            request.review_task_id,
            request.node_run_id,
        ):
            raise ModelGatewayError(
                GatewayErrorCode.INPUT_INVALID,
                "Model request is not bound to a trusted tenant, task, and node context.",
                diagnostic_code="untrusted_call_context",
            )
        if provider not in self.tenant_providers.get(request.tenant_id, frozenset()):
            raise ModelGatewayError(
                GatewayErrorCode.PROVIDER_UNAUTHORIZED,
                "Provider is not authorized for this tenant.",
            )
        if data_policy not in self.provider_data_policies.get(provider, frozenset()):
            raise ModelGatewayError(
                GatewayErrorCode.DATA_POLICY_REJECTED,
                "The data classification is not authorized for external processing.",
            )
