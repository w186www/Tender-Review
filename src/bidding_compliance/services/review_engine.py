"""Durable task-0009 LangGraph orchestration and PostgreSQL checkpoint lifecycle."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command
from psycopg.rows import dict_row
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.domain.review_configuration import ModelPolicySnapshot
from bidding_compliance.domain.rules.engine import SKILLS, ruleset_sha256
from bidding_compliance.domain.rules.models import DiscoveryDocumentRequest
from bidding_compliance.domain.runtime_provenance import (
    FrozenParserIdentity,
    ReviewRuntimeProvenance,
)
from bidding_compliance.graph.review import build_review_graph, initial_state
from bidding_compliance.legal.contracts import RetrievalRuntimeSnapshot
from bidding_compliance.legal.corpus import index_hash
from bidding_compliance.legal.embedding_provider import character_embedding_identity
from bidding_compliance.model_gateway.contracts import ModelPolicy
from bidding_compliance.model_gateway.errors import GatewayErrorCode, ModelGatewayError
from bidding_compliance.model_gateway.protocol import ModelGateway
from bidding_compliance.persistence.models import (
    ReviewArtifact,
    ReviewDecision,
    ReviewEngineRun,
    ReviewTask,
)
from bidding_compliance.services.candidate_discovery import snapshot_for_project
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.legal_management import read_publication
from bidding_compliance.services.projects import find_project
from bidding_compliance.services.review_configurations import resolve_execution_configuration
from bidding_compliance.services.review_persistence import (
    approved_findings,
    authorized_run,
    content_hash,
    update_run_status,
)
from bidding_compliance.services.review_persistence import (
    cancel_review as persist_cancel,
)
from bidding_compliance.services.review_persistence import (
    submit_decision as persist_decision,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    """Caller-pinned review identity and immutable document/configuration inputs."""

    review_task_id: str
    project_id: str
    run_id: str
    document_requests: tuple[DiscoveryDocumentRequest, ...]
    review_date: date
    prompt_version: str
    model_profile: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.review_task_id):
            raise ValueError("review_task_id must be a bounded opaque identifier")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.project_id):
            raise ValueError("project_id must be a bounded opaque identifier")
        if str(UUID(self.run_id)) != self.run_id:
            raise ValueError("run_id must be a canonical UUID")
        if not self.document_requests or len(self.document_requests) > 100:
            raise ValueError("one to one hundred pinned documents are required")
        if len({item.document_id for item in self.document_requests}) != len(
            self.document_requests
        ):
            raise ValueError("duplicate document request")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.prompt_version):
            raise ValueError("prompt version must be an immutable version identifier")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.model_profile):
            raise ValueError("model profile must be a bounded identifier")


@dataclass(frozen=True, slots=True)
class ReviewRunHandle:
    tenant_id: str
    review_task_id: str
    run_id: str
    project_id: str
    status: str
    snapshot: dict[str, Any]
    snapshot_hash: str
    retry_count: int
    failure_code: str | None
    publication_id: str | None
    revision_id: str | None


class ReviewEngine:
    """Requires PostgreSQL runtime state and a caller-authorized ModelGateway."""

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        gateway: ModelGateway,
        model_policy: ModelPolicy,
        legal_root: Path | None = None,
        enable_llm_discovery: bool = False,
        retriever_factory: Any = None,
    ) -> None:
        if settings.database_url is None:
            raise RuntimeError("PostgreSQL database configuration is required")
        self.settings = settings
        self.session_factory = session_factory
        self.gateway = gateway
        self.model_policy = model_policy
        self.legal_root = legal_root or Path(".")
        self.enable_llm_discovery = enable_llm_discovery
        self.retriever_factory = retriever_factory

    def _request_hash(self, request: ReviewRequest, prompt_sha256: str) -> str:
        return content_hash(
            {
                "project_id": request.project_id,
                "document_requests": [
                    item.model_dump(mode="json")
                    for item in sorted(request.document_requests, key=lambda item: item.document_id)
                ],
                "review_date": request.review_date.isoformat(),
                "prompt_version": request.prompt_version,
                "prompt_sha256": prompt_sha256,
                "model_profile": request.model_profile,
                "model_policy": self._policy_snapshot(),
            }
        )

    def _policy_snapshot(self) -> dict[str, Any]:
        return {
            "profile": self.model_policy.profile,
            "timeout_seconds": self.model_policy.timeout_seconds,
            "max_attempts": self.model_policy.max_attempts,
            "max_input_tokens": self.model_policy.max_input_tokens,
            "max_output_tokens": self.model_policy.max_output_tokens,
            "temperature": self.model_policy.temperature,
            "data_policy": self.model_policy.data_policy.value,
        }

    @staticmethod
    def _handle(row: ReviewEngineRun) -> ReviewRunHandle:
        return ReviewRunHandle(
            tenant_id=row.tenant_id,
            review_task_id=row.review_task_id,
            run_id=row.run_id,
            project_id=row.project_id,
            status=row.status,
            snapshot=row.snapshot,
            snapshot_hash=row.snapshot_hash,
            retry_count=row.retry_count,
            failure_code=row.failure_code,
            publication_id=row.publication_id,
            revision_id=row.revision_id,
        )

    def _freeze_run(self, principal: Principal, request: ReviewRequest) -> ReviewRunHandle:
        if principal.role is not Role.REVIEWER:
            raise PermissionError("review creation requires reviewer role")
        if request.model_profile != self.model_policy.profile:
            raise ValueError("request profile differs from the configured gateway policy")
        prompt_sha256 = self.gateway.prompt_sha256(request.prompt_version)
        if not re.fullmatch(r"[a-f0-9]{64}", prompt_sha256):
            raise ValueError("approved prompt digest is invalid")
        request_hash = self._request_hash(request, prompt_sha256)
        with self.session_factory() as session:
            require_identity(session, principal)
            existing = session.get(
                ReviewEngineRun,
                (principal.tenant_id, request.review_task_id, request.run_id),
                populate_existing=True,
            )
            if existing is not None:
                if (
                    existing.request_hash != request_hash
                    or existing.project_id != request.project_id
                ):
                    raise ValueError("duplicate delivery changed the frozen review request")
                find_project(session, principal, existing.project_id)
                return self._handle(existing)
            project = find_project(session, principal, request.project_id)
            input_snapshot, _ = snapshot_for_project(
                session,
                principal,
                request.project_id,
                tuple(sorted(request.document_requests, key=lambda item: item.document_id)),
            )
            config_revision_id, config_hash, config_snapshot = resolve_execution_configuration(
                session, principal, self.model_policy
            )
            config_policy = ModelPolicySnapshot.model_validate(
                config_snapshot["model_policy"]
            ).to_policy()
            if request.model_profile != config_policy.profile:
                raise ValueError("request profile differs from the active review configuration")
            publication, bundle = read_publication(
                session, principal, config_snapshot["legal_publication_id"]
            )
            skill_ids = list(config_snapshot["skill_ids"])
            context_hash = content_hash(project.context)
            retrieval_runtime = (
                self.retriever_factory(
                    bundle.index, publication.publication_id, publication.revision_id
                ).runtime_snapshot(10)
                if self.retriever_factory is not None
                else RetrievalRuntimeSnapshot(
                    top_k=10, embedding_identity=character_embedding_identity()
                )
            )
            embedding_identity = retrieval_runtime.embedding_identity
            runtime_provenance = ReviewRuntimeProvenance(
                parser_documents=tuple(
                    FrozenParserIdentity(
                        document_id=document.document_id,
                        identity=document.ocr_runtime,
                        identity_sha256=document.ocr_runtime_sha256,
                    )
                    for document in input_snapshot.documents
                ),
                embedding_identity=embedding_identity,
                retrieval=retrieval_runtime,
                vector_index_build_id=retrieval_runtime.vector_index_build_id,
                prompt_version=request.prompt_version,
                prompt_sha256=prompt_sha256,
                model_profile=request.model_profile,
                model_config_revision_id=config_revision_id or "code-default",
                model_config_sha256=config_hash,
            )
            frozen = {
                "schema_version": "task0009-review-snapshot.v1",
                "tenant_id": principal.tenant_id,
                "project_id": request.project_id,
                "review_task_id": request.review_task_id,
                "run_id": request.run_id,
                "project_version": project.version,
                "project_context_sha256": context_hash,
                "input_snapshot": input_snapshot.model_dump(mode="json"),
                "document_requests": [
                    item.model_dump(mode="json")
                    for item in sorted(request.document_requests, key=lambda item: item.document_id)
                ],
                "skill_ids": skill_ids,
                "skill_versions": {
                    skill_id: SKILLS[skill_id].DEFINITION.skill_version for skill_id in skill_ids
                },
                "ruleset_sha256": ruleset_sha256(tuple(skill_ids)),
                "review_date": request.review_date.isoformat(),
                "legal_publication_id": publication.publication_id,
                "legal_revision_id": publication.revision_id,
                "legal_index_hash": index_hash(bundle.index),
                "prompt_version": request.prompt_version,
                "model_profile": request.model_profile,
                "model_policy": config_snapshot["model_policy"],
                "configuration_revision_id": config_revision_id,
                "configuration_snapshot_hash": config_hash,
                "configuration_snapshot": config_snapshot,
                "runtime_provenance": runtime_provenance.model_dump(mode="json"),
            }
            snapshot_hash = content_hash(frozen)
            task = session.get(
                ReviewTask, (principal.tenant_id, request.review_task_id), populate_existing=True
            )
            if task is not None:
                raise ValueError("review_task_id is already bound to a different run")
            now = datetime.now(UTC)
            task = ReviewTask(
                tenant_id=principal.tenant_id,
                review_task_id=request.review_task_id,
                project_id=request.project_id,
                run_id=request.run_id,
                status="queued",
            )
            row = ReviewEngineRun(
                tenant_id=principal.tenant_id,
                review_task_id=request.review_task_id,
                run_id=request.run_id,
                project_id=request.project_id,
                actor_id=principal.user_id,
                status="queued",
                snapshot=frozen,
                snapshot_hash=snapshot_hash,
                request_hash=request_hash,
                retry_count=0,
                failure_code=None,
                publication_id=publication.publication_id,
                revision_id=publication.revision_id,
                created_at=now,
                updated_at=now,
            )
            session.add(task)
            try:
                # Keep both writes atomic while establishing the FK target first.
                session.flush()
                session.add(row)
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                duplicate = session.get(
                    ReviewEngineRun,
                    (principal.tenant_id, request.review_task_id, request.run_id),
                    populate_existing=True,
                )
                if duplicate is None:
                    raise
                if duplicate.request_hash != request_hash:
                    raise ValueError(
                        "concurrent task delivery conflicts with the frozen request"
                    ) from exc
                return self._handle(duplicate)
            return self._handle(row)

    @staticmethod
    def _thread_id(principal: Principal, task_id: str, run_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", principal.tenant_id):
            raise ValueError("tenant identifier is not valid for checkpoint isolation")
        return f"{principal.tenant_id}:{task_id}:{run_id}"

    def _connection_info(self) -> str:
        assert self.settings.database_url is not None
        value = self.settings.database_url.get_secret_value()
        value = value.replace("postgresql+psycopg://", "postgresql://", 1)
        if not value.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("durable review checkpoints require PostgreSQL")
        return value

    def create_run(self, principal: Principal, request: ReviewRequest) -> ReviewRunHandle:
        """Freeze and persist a review before a worker starts executing it."""
        return self._freeze_run(principal, request)

    async def start(self, principal: Principal, request: ReviewRequest) -> dict[str, Any]:
        row = self.create_run(principal, request)
        if row.status in {"waiting_human", "result_published", "failed", "cancelled"}:
            return await self._read_graph_state(principal, row)
        if row.status == "queued":
            with self.session_factory() as session:
                update_run_status(session, principal, row.review_task_id, row.run_id, "running")
        return await self._invoke(principal, row, resume=False, retry=False)

    async def resume(
        self, principal: Principal, review_task_id: str, run_id: str
    ) -> dict[str, Any]:
        if principal.role is not Role.REVIEWER:
            raise PermissionError("review resume requires reviewer role")
        with self.session_factory() as session:
            mutable_row = authorized_run(session, principal, review_task_id, run_id)
            row = self._handle(mutable_row)
            if row.status != "waiting_human":
                raise ValueError("review is not waiting for human review")
            merged = session.scalar(
                select(ReviewArtifact).where(
                    ReviewArtifact.tenant_id == principal.tenant_id,
                    ReviewArtifact.review_task_id == review_task_id,
                    ReviewArtifact.run_id == run_id,
                    ReviewArtifact.kind == "merged_findings",
                )
            )
            if merged is None or content_hash(merged.content) != merged.content_hash:
                raise ValueError("review evidence artifact is unavailable")
            approved_findings(session, principal, mutable_row, merged.content["findings"])
            decisions = list(
                session.scalars(
                    select(ReviewDecision).where(
                        ReviewDecision.tenant_id == principal.tenant_id,
                        ReviewDecision.review_task_id == review_task_id,
                        ReviewDecision.run_id == run_id,
                    )
                )
            )
            decision_ids = sorted(item.decision_id for item in decisions)
        return await self._invoke(
            principal,
            row,
            resume=True,
            retry=False,
            resume_value={"decision_ids": decision_ids},
        )

    async def retry(self, principal: Principal, review_task_id: str, run_id: str) -> dict[str, Any]:
        if principal.role is not Role.REVIEWER:
            raise PermissionError("review retry requires reviewer role")
        retryable = {
            GatewayErrorCode.TIMEOUT.value,
            GatewayErrorCode.RATE_LIMITED.value,
            GatewayErrorCode.PROVIDER_UNAVAILABLE.value,
            GatewayErrorCode.PROVIDER_ERROR.value,
            # A provider can emit a non-conforming structured response for a single batch.
            # Replaying the frozen input stays bounded by retry_count, and every accepted
            # batch is reused from its recorded artifact instead of being paid for again.
            GatewayErrorCode.RESPONSE_INVALID.value,
        }
        with self.session_factory() as session:
            mutable_row = authorized_run(session, principal, review_task_id, run_id)
            if (
                mutable_row.status != "failed"
                or mutable_row.failure_code not in retryable
                or mutable_row.retry_count >= 2
            ):
                raise ValueError("review failure is not eligible for a bounded retry")
            mutable_row.retry_count += 1
            mutable_row.status = "running"
            mutable_row.failure_code = None
            mutable_row.updated_at = datetime.now(UTC)
            task = session.get(ReviewTask, (principal.tenant_id, review_task_id))
            if task is not None:
                task.status = "running"
            audit(session, principal.tenant_id, principal.user_id, "review.retry", review_task_id)
            session.commit()
            row = self._handle(mutable_row)
        return await self._invoke(principal, row, resume=False, retry=True)

    def cancel(self, principal: Principal, review_task_id: str, run_id: str) -> None:
        with self.session_factory() as session:
            persist_cancel(session, principal, review_task_id, run_id)

    def submit_decision(
        self,
        principal: Principal,
        *,
        review_task_id: str,
        run_id: str,
        finding_id: str,
        decision: str,
        request_id: str,
        reason: str,
        modified_finding: dict[str, Any] | None = None,
    ) -> ReviewDecision:
        with self.session_factory() as session:
            return persist_decision(
                session,
                principal,
                review_task_id=review_task_id,
                run_id=run_id,
                finding_id=finding_id,
                decision=decision,
                request_id=request_id,
                reason=reason,
                modified_finding=modified_finding,
            )

    async def _read_graph_state(self, principal: Principal, row: ReviewRunHandle) -> dict[str, Any]:
        return await self._invoke(principal, row, resume=False, retry=False, read_only=True)

    async def _invoke(
        self,
        principal: Principal,
        row: ReviewRunHandle,
        *,
        resume: bool,
        retry: bool,
        read_only: bool = False,
        resume_value: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thread_id = self._thread_id(principal, row.review_task_id, row.run_id)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
        conn = await psycopg.AsyncConnection.connect(
            self._connection_info(), autocommit=True, row_factory=dict_row
        )
        try:
            await conn.execute(
                "SELECT set_config('app.tenant_id', %s, false)", (principal.tenant_id,)
            )
            migration_cursor = await conn.execute(
                "SELECT max(v) AS version FROM checkpoint_migrations"
            )
            migration_row = await migration_cursor.fetchone()
            if migration_row is None:
                raise RuntimeError("task0009 checkpoint schema migration is missing")
            version = migration_row["version"]
            if version != 9:
                raise RuntimeError("task0009 checkpoint schema migration is missing")
            lock_cursor = await conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired", (thread_id,)
            )
            lock_row = await lock_cursor.fetchone()
            acquired = lock_row["acquired"] if lock_row is not None else False
            if not acquired:
                with self.session_factory() as session:
                    current = authorized_run(session, principal, row.review_task_id, row.run_id)
                    return {"status": current.status, "busy": True}
            saver = AsyncPostgresSaver(conn, serde=JsonPlusSerializer(pickle_fallback=False))
            frozen_policy = (
                ModelPolicySnapshot.model_validate(row.snapshot["model_policy"]).to_policy()
                if "configuration_snapshot" in row.snapshot
                else self.model_policy
            )
            graph = build_review_graph(
                session_factory=self.session_factory,
                principal=principal,
                gateway=self.gateway,
                model_policy=frozen_policy,
                checkpointer=saver,
                legal_root=self.legal_root,
                skill_ids=tuple(row.snapshot.get("skill_ids", SKILLS.keys())),
                enable_llm_discovery=self.enable_llm_discovery,
                retriever_factory=self.retriever_factory,
            )
            saved = await graph.aget_state(config)
            values = dict(saved.values) if saved and saved.values else {}
            if read_only:
                if values:
                    return values
                return {
                    "status": row.status,
                    "review_task_id": row.review_task_id,
                    "run_id": row.run_id,
                }
            if resume:
                if not saved or not saved.next or resume_value is None:
                    raise ValueError("durable human interrupt is not available to resume")
                result = await graph.ainvoke(Command(resume=resume_value), config)
            elif retry:
                result = await graph.ainvoke(
                    Command(
                        update={"status": "running", "retry_count": row.retry_count, "errors": []},
                        goto="load_context",
                    ),
                    config,
                )
            elif values:
                if values.get("status") in {
                    "waiting_human",
                    "result_published",
                    "failed",
                    "cancelled",
                }:
                    return values
                if not saved.next:
                    return values
                result = await graph.ainvoke(None, config)
            else:
                result = await graph.ainvoke(
                    initial_state(
                        tenant_id=principal.tenant_id,
                        project_id=row.project_id,
                        review_task_id=row.review_task_id,
                        run_id=row.run_id,
                        document_refs=[
                            item["document_id"]
                            for item in row.snapshot["input_snapshot"]["documents"]
                        ],
                    ),
                    config,
                )
            return dict(result)
        except Exception as exc:
            if not isinstance(exc, PermissionError):
                failure_code = (
                    exc.code.value
                    if isinstance(exc, ModelGatewayError)
                    else "review_execution_failed"
                )
                try:
                    with self.session_factory() as session:
                        latest = authorized_run(session, principal, row.review_task_id, row.run_id)
                        if latest.status not in {"cancelled", "result_published", "waiting_human"}:
                            latest.status = "failed"
                            latest.failure_code = failure_code
                            latest.updated_at = datetime.now(UTC)
                            task = session.get(
                                ReviewTask, (principal.tenant_id, row.review_task_id)
                            )
                            if task is not None:
                                task.status = "failed"
                            session.commit()
                except Exception:
                    LOGGER.warning("Could not persist the review execution failure state")
            raise
        finally:
            try:
                await conn.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (thread_id,)
                )
            except Exception:
                LOGGER.debug("PostgreSQL released the review lock when its connection closed")
            await conn.close()
