"""Persist model-call identity and result before allowing review execution to continue."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from bidding_compliance.domain.identity import Principal
from bidding_compliance.model_gateway.contracts import (
    JsonObject,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from bidding_compliance.model_gateway.protocol import ModelGateway
from bidding_compliance.persistence.models import ReviewEngineRun, ReviewModelCall
from bidding_compliance.services.review_persistence import (
    authorized_run,
    content_hash,
    put_artifact,
    read_artifact,
)

LOGGER = logging.getLogger(__name__)


def _request_hash(request: ModelRequest, schema: JsonObject, policy: ModelPolicy) -> str:
    return content_hash(
        {
            "call_id": request.call_id,
            "tenant_id": request.tenant_id,
            "review_task_id": request.review_task_id,
            "node_run_id": request.node_run_id,
            "prompt_version": request.prompt_version,
            "system_instruction": request.system_instruction,
            "input_payload": dict(request.input_payload),
            "metadata": dict(request.metadata),
            "output_schema": dict(schema),
            "policy": {
                "profile": policy.profile,
                "timeout_seconds": policy.timeout_seconds,
                "max_attempts": policy.max_attempts,
                "max_input_tokens": policy.max_input_tokens,
                "max_output_tokens": policy.max_output_tokens,
                "temperature": policy.temperature,
                "data_policy": policy.data_policy.value,
            },
        }
    )


def _response_data(response: ModelResponse) -> dict[str, Any]:
    return {
        "call_id": response.call_id,
        "provider": response.provider,
        "model": response.model,
        "profile": response.profile,
        "content": dict(response.content),
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "estimated_cost": response.usage.estimated_cost,
        },
        "latency_ms": response.latency_ms,
        "response_hash": response.response_hash,
        "finish_reason": response.finish_reason,
    }


def _response_from_data(value: dict[str, Any]) -> ModelResponse:
    return ModelResponse(
        call_id=value["call_id"],
        provider=value["provider"],
        model=value["model"],
        profile=value["profile"],
        content=value["content"],
        usage=ModelUsage(**value["usage"]),
        latency_ms=value["latency_ms"],
        response_hash=value["response_hash"],
        finish_reason=value.get("finish_reason"),
    )


class PersistedModelGateway:
    """Journal a dispatch before provider I/O and its response before returning it."""

    def __init__(
        self,
        delegate: ModelGateway,
        *,
        session_factory: sessionmaker[Session],
        principal: Principal,
        run: ReviewEngineRun,
    ) -> None:
        self.delegate = delegate
        self.session_factory = session_factory
        self.principal = principal
        self.run = run

    def prompt_sha256(self, prompt_version: str) -> str:
        return self.delegate.prompt_sha256(prompt_version)

    def _open_or_restore(
        self, request: ModelRequest, schema: JsonObject, policy: ModelPolicy
    ) -> tuple[str, ModelResponse | None]:
        if (
            request.tenant_id != self.principal.tenant_id
            or request.review_task_id != self.run.review_task_id
        ):
            raise ValueError("model call tenant or task differs from its authorized review run")
        digest = _request_hash(request, schema, policy)
        with self.session_factory() as session:
            run = authorized_run(
                session,
                self.principal,
                self.run.review_task_id,
                self.run.run_id,
            )
            if run.snapshot_hash != self.run.snapshot_hash:
                raise ValueError("model call does not match its frozen review snapshot")
            row = session.get(
                ReviewModelCall,
                (self.principal.tenant_id, request.call_id),
                populate_existing=True,
            )
            if row is not None:
                if (
                    row.review_task_id != self.run.review_task_id
                    or row.run_id != self.run.run_id
                    or row.actor_id != self.run.actor_id
                    or row.request_hash != digest
                    or row.node_run_id != request.node_run_id
                ):
                    raise ValueError("model call identity conflicts with its frozen request")
                if row.state == "succeeded" and row.response_ref is not None:
                    artifact = read_artifact(
                        session,
                        self.principal.tenant_id,
                        row.response_ref,
                        review_task_id=self.run.review_task_id,
                        run_id=self.run.run_id,
                    )
                    if (
                        artifact.get("call_id") != request.call_id
                        or artifact.get("request_hash") != digest
                        or content_hash(artifact.get("response")) != row.response_hash
                    ):
                        raise ValueError("persisted model response provenance mismatch")
                    return digest, _response_from_data(artifact["response"])
                if row.state == "dispatched":
                    row.state = "unknown"
                    row.usage_status = "unknown"
                    row.error_code = "call_outcome_unknown"
                    row.updated_at = datetime.now(UTC)
                    session.commit()
                    raise RuntimeError(
                        "model call outcome is unknown; automatic replay is forbidden"
                    )
                raise RuntimeError("model call is not eligible for automatic replay")

            document_hashes = sorted(
                {
                    str(item["raw_source_sha256"])
                    for item in self.run.snapshot.get("document_requests", [])
                }
            )
            now = datetime.now(UTC)
            session.add(
                ReviewModelCall(
                    tenant_id=self.principal.tenant_id,
                    call_id=request.call_id,
                    review_task_id=self.run.review_task_id,
                    run_id=self.run.run_id,
                    actor_id=self.run.actor_id,
                    node_run_id=request.node_run_id,
                    attempt=self.run.retry_count + 1,
                    request_hash=digest,
                    document_hashes=document_hashes,
                    usage_status="unknown",
                    state="dispatched",
                    response_ref=None,
                    response_hash=None,
                    error_code=None,
                    execution_generation=run.execution_generation,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        return digest, None

    def _mark_unknown(self, call_id: str, error_code: str) -> None:
        with self.session_factory() as session:
            authorized_run(
                session,
                self.principal,
                self.run.review_task_id,
                self.run.run_id,
            )
            row = session.get(
                ReviewModelCall,
                (self.principal.tenant_id, call_id),
                populate_existing=True,
            )
            if row is None or row.state != "dispatched":
                return
            row.state = "unknown"
            row.usage_status = "unknown"
            row.error_code = error_code[:100]
            row.updated_at = datetime.now(UTC)
            session.commit()

    def _persist_response(
        self,
        request: ModelRequest,
        request_hash: str,
        response: ModelResponse,
    ) -> None:
        with self.session_factory() as session:
            authorized_run(
                session,
                self.principal,
                self.run.review_task_id,
                self.run.run_id,
            )
            row = session.get(
                ReviewModelCall,
                (self.principal.tenant_id, request.call_id),
                populate_existing=True,
            )
            if row is None or row.state != "dispatched" or row.request_hash != request_hash:
                raise RuntimeError("model call lease or identity changed before response commit")
            response_data = _response_data(response)
            response_hash = content_hash(response_data)
            response_ref = put_artifact(
                session,
                self.principal.tenant_id,
                self.run.review_task_id,
                self.run.run_id,
                "model_call_response",
                {
                    "call_id": request.call_id,
                    "request_hash": request_hash,
                    "response": response_data,
                },
            )
            row.state = "succeeded"
            row.usage_status = "reported"
            row.response_ref = response_ref
            row.response_hash = response_hash
            row.updated_at = datetime.now(UTC)
            session.commit()

    async def generate_structured(
        self,
        request: ModelRequest,
        output_schema: JsonObject,
        policy: ModelPolicy,
    ) -> ModelResponse:
        request_hash, cached = self._open_or_restore(request, output_schema, policy)
        if cached is not None:
            return cached
        try:
            response = await self.delegate.generate_structured(request, output_schema, policy)
        except BaseException as exc:
            error_code = getattr(getattr(exc, "code", None), "value", "call_outcome_unknown")
            try:
                self._mark_unknown(request.call_id, str(error_code))
            except Exception as mark_error:
                # The durable dispatch row remains and is treated as unknown by the next worker.
                LOGGER.error(
                    "model_call_unknown_mark_failed error_type=%s",
                    type(mark_error).__name__,
                )
            raise
        self._persist_response(request, request_hash, response)
        return response
