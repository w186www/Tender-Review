"""Production review DAG over the existing discovery, legal and gateway services."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bidding_compliance.domain.identity import Principal
from bidding_compliance.domain.rules.engine import SKILLS, combine_discoveries, ruleset_sha256
from bidding_compliance.domain.rules.models import (
    CandidateFinding,
    DiscoveryDocumentRequest,
    DiscoveryResult,
)
from bidding_compliance.graph.state import ComplianceReviewState
from bidding_compliance.legal.adoption import (
    binding_for,
    load_adoption_policy,
    load_rule_law_bindings,
)
from bidding_compliance.legal.corpus import index_hash
from bidding_compliance.model_gateway.contracts import (
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from bidding_compliance.model_gateway.errors import GatewayErrorCode, ModelGatewayError
from bidding_compliance.model_gateway.protocol import ModelGateway
from bidding_compliance.persistence.models import (
    ReviewArtifact,
    ReviewDecision,
    ReviewEngineRun,
    ReviewTask,
)
from bidding_compliance.services import candidate_discovery as candidate_service
from bidding_compliance.services import llm_candidate_discovery as llm_discovery
from bidding_compliance.services.candidate_discovery import snapshot_for_project
from bidding_compliance.services.documents import find_document, sections
from bidding_compliance.services.evidence_checker import (
    evidence_status_for_support,
    has_confirmable_legal_support,
    verify_document_excerpt,
    verify_legal_hit,
)
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.legal_management import (
    read_publication,
    retrieve_published_for_project,
)
from bidding_compliance.services.review_configurations import verify_frozen_configuration
from bidding_compliance.services.review_persistence import (
    MAX_ARTIFACT_BYTES,
    RESULT_PENDING_ID,
    approved_findings,
    authorized_run,
    content_hash,
    put_artifact,
    read_artifact,
)
from bidding_compliance.services.review_persistence import (
    publish_result as persist_result,
)
from bidding_compliance.services.review_projection import merge_duplicate_findings
from bidding_compliance.services.risk_language import unverified_risk_text

ROOT = Path(__file__).resolve().parents[3]
MAX_STATE_BYTES = 64_000
MAX_CANDIDATES_FOR_REVIEW = 100
MAX_ERRORS = 100
# Semantic analysis is chunked so one oversized request cannot exceed the authorized
# provider timeout. Batches are ordered by candidate_id, so the split is reproducible.
SEMANTIC_BATCH_CANDIDATES = 8
MAX_SEMANTIC_BATCHES = 13
# Non-selected retrieval hits are supporting context only; bound the visible list so a
# finding does not carry ten loosely related statutes into the reviewer/report surface.
MAX_REFERENCE_ONLY_CLAUSES = 3


class SkillWorkItem(TypedDict):
    skill_id: str
    tenant_id: str
    project_id: str
    review_task_id: str
    run_id: str
    review_snapshot_ref: str


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _discovery_from_artifact(value: object) -> DiscoveryResult:
    return DiscoveryResult.model_validate_json(_json(value))


def _assert_bounded(state: Mapping[str, Any]) -> None:
    if len(_json(state).encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("LangGraph state exceeds the 64 KiB reference-only limit")
    if len(state.get("findings", [])) > 500 or len(state.get("errors", [])) > MAX_ERRORS:
        raise ValueError("LangGraph state item limit exceeded")


def _load_run(session: Session, principal: Principal, state: Mapping[str, Any]) -> ReviewEngineRun:
    row = authorized_run(session, principal, state["review_task_id"], state["run_id"])
    if row.status == "cancelled":
        raise RuntimeError("review run cancelled")
    if content_hash(row.snapshot) != row.snapshot_hash:
        raise ValueError("review input snapshot hash mismatch")
    return row


def _required_ref(state: Mapping[str, Any], key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"required artifact reference is missing: {key}")
    return value


def _snapshot_inputs(
    session: Session,
    principal: Principal,
    row: ReviewEngineRun,
    model_policy: ModelPolicy,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from bidding_compliance.services.projects import find_project

    snapshot = row.snapshot
    requests = tuple(
        DiscoveryDocumentRequest.model_validate(item) for item in snapshot["document_requests"]
    )
    input_snapshot, _ = snapshot_for_project(session, principal, row.project_id, requests)
    if input_snapshot.model_dump(mode="json") != snapshot["input_snapshot"]:
        raise ValueError("review input changed; this frozen run cannot be resumed")
    project = find_project(session, principal, row.project_id)
    context = json.loads(_json(project.context))
    if (
        project.version != snapshot["project_version"]
        or content_hash(context) != snapshot["project_context_sha256"]
    ):
        raise ValueError("project context changed; create a new review run")
    publication, bundle = read_publication(session, principal, snapshot["legal_publication_id"])
    if (
        publication.publication_id != row.publication_id
        or publication.revision_id != row.revision_id
        or index_hash(bundle.index) != snapshot["legal_index_hash"]
    ):
        raise ValueError("pinned legal publication changed or is unavailable")
    skill_ids = tuple(snapshot["skill_ids"])
    if snapshot["ruleset_sha256"] != ruleset_sha256(skill_ids):
        raise ValueError("review ruleset snapshot mismatch")
    if "configuration_snapshot" in snapshot:
        frozen_configuration = snapshot["configuration_snapshot"]
        if (
            frozen_configuration.get("legal_publication_id") != snapshot["legal_publication_id"]
            or frozen_configuration.get("skill_ids") != list(skill_ids)
            or frozen_configuration.get("ruleset_sha256") != snapshot["ruleset_sha256"]
            or frozen_configuration.get("model_policy") != snapshot["model_policy"]
        ):
            raise ValueError("review configuration snapshot does not match run snapshot")
        verified_policy = verify_frozen_configuration(
            session,
            principal,
            revision_id=snapshot["configuration_revision_id"],
            snapshot_hash=snapshot["configuration_snapshot_hash"],
            snapshot=frozen_configuration,
            runtime_policy=model_policy,
        )
        if verified_policy != model_policy:
            raise ValueError("model policy differs from the frozen configuration")
    elif snapshot["model_policy"] != {
        "profile": model_policy.profile,
        "timeout_seconds": model_policy.timeout_seconds,
        "max_attempts": model_policy.max_attempts,
        "max_input_tokens": model_policy.max_input_tokens,
        "max_output_tokens": model_policy.max_output_tokens,
        "temperature": model_policy.temperature,
        "data_policy": model_policy.data_policy.value,
    }:
        raise ValueError("model policy changed; this frozen run cannot be resumed")
    return snapshot, context


def _analysis_schema(root: Path = ROOT) -> dict[str, Any]:
    schema = json.loads(
        (root / "contracts/schemas/semantic-analysis.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return cast(dict[str, Any], schema)


def _semantic_batches(
    candidates: tuple[CandidateFinding, ...],
) -> tuple[tuple[CandidateFinding, ...], ...]:
    """Order candidates by stable ID and chunk them for bounded single requests."""
    ordered = sorted(candidates, key=lambda item: item.candidate_id)
    return tuple(
        tuple(ordered[start : start + SEMANTIC_BATCH_CANDIDATES])
        for start in range(0, len(ordered), SEMANTIC_BATCH_CANDIDATES)
    )


def _semantic_call_parts(
    tenant_id: str, task_id: str, run_id: str, *, single: bool, index: int
) -> tuple[str, str]:
    """Keep the historical single-request call identity when one batch suffices."""
    suffix = "" if single else f":{index}"
    call_id = hashlib.sha256(
        f"{tenant_id}:{task_id}:{run_id}:semantic{suffix}".encode()
    ).hexdigest()
    return call_id, f"semantic{suffix}"


def _semantic_batch_kind(index: int, *, single: bool) -> str:
    return "model_analysis" if single else f"semantic_analysis_batch_{index}"


def _retry_call_id(call_id: str, retry_count: int) -> str:
    if retry_count <= 0:
        return call_id
    retry_identity = f"{call_id}\0retry:{retry_count}".encode()
    return hashlib.sha256(retry_identity).hexdigest()


def _semantic_response(record: Mapping[str, Any]) -> ModelResponse:
    """Rebuild exactly what the provider returned so a cached batch needs no new call."""
    return ModelResponse(
        call_id=str(record["call_id"]),
        provider=str(record["provider"]),
        model=str(record["model"]),
        profile=str(record["profile"]),
        content=dict(record["content"]),
        usage=ModelUsage(**dict(record["usage"])),
        latency_ms=int(record["latency_ms"]),
        response_hash=str(record["response_hash"]),
        finish_reason=str(record["finish_reason"]),
    )


async def _run_semantic_batch(
    gateway: Any, request: ModelRequest, schema: dict[str, Any], policy: ModelPolicy
) -> ModelResponse:
    """One bounded structured request; a provider contract error may be retried once."""
    max_attempts = min(2, policy.max_attempts)
    response: ModelResponse | None = None
    for attempt in range(max_attempts):
        try:
            candidate = await gateway.generate_structured(request, schema, policy)
            Draft202012Validator(schema).validate(dict(candidate.content))
            if (
                candidate.call_id != request.call_id
                or candidate.profile != policy.profile
                or hashlib.sha256(_json(candidate.content).encode("utf-8")).hexdigest()
                != candidate.response_hash
            ):
                raise ModelGatewayError(
                    GatewayErrorCode.RESPONSE_INVALID,
                    "Structured response provenance failed validation.",
                )
            response = candidate
            break
        except ModelGatewayError as exc:
            if attempt + 1 < max_attempts and exc.code is GatewayErrorCode.RESPONSE_INVALID:
                continue
            raise
        except ValidationError as exc:
            if attempt + 1 < max_attempts:
                continue
            raise ModelGatewayError(
                GatewayErrorCode.RESPONSE_INVALID,
                "Structured response failed within the configured attempt limit.",
            ) from exc
    if response is None:
        raise ModelGatewayError(
            GatewayErrorCode.RESPONSE_INVALID,
            "Structured response failed within the configured attempt limit.",
        )
    return response


def _risk_schema(root: Path = ROOT) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((root / "contracts/schemas/risk.schema.json").read_text(encoding="utf-8")),
    )


def _evidence_schema(root: Path = ROOT) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((root / "contracts/schemas/evidence.schema.json").read_text(encoding="utf-8")),
    )


def build_review_graph(
    *,
    session_factory: sessionmaker[Session],
    principal: Principal,
    gateway: ModelGateway,
    model_policy: ModelPolicy,
    checkpointer: BaseCheckpointSaver[Any],
    skill_ids: tuple[str, ...] | None = None,
    legal_root: Path | None = None,
    enable_llm_discovery: bool = False,
    retriever_factory: Any = None,
) -> Any:
    """Compile the persisted review DAG. A per-invocation principal is rechecked per node."""
    schema_root = legal_root or ROOT
    adoption_policy = load_adoption_policy(schema_root)
    rule_law_bindings = (
        load_rule_law_bindings(schema_root, adoption_policy)
        if adoption_policy is not None
        else ()
    )
    analysis_schema = _analysis_schema(schema_root)
    selected_skill_ids = tuple(sorted(skill_ids or SKILLS))
    if (
        not selected_skill_ids
        or len(selected_skill_ids) != len(set(selected_skill_ids))
        or set(selected_skill_ids) - set(SKILLS)
    ):
        raise ValueError("review graph references an invalid installed Skill set")

    def with_session(
        function: Callable[[Session], dict[str, Any]],
    ) -> Callable[[ComplianceReviewState], dict[str, Any]]:
        def node(state: ComplianceReviewState) -> dict[str, Any]:
            with session_factory() as session:
                return function(session)

        return node

    def load_context(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            snapshot, context = _snapshot_inputs(session, principal, row, model_policy)
            snapshot_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "review_snapshot",
                snapshot,
            )
            context_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "project_context",
                {
                    "project_id": row.project_id,
                    "version": snapshot["project_version"],
                    "context_sha256": snapshot["project_context_sha256"],
                    "context": context,
                },
            )
            session.commit()
            return {
                "status": "running",
                "project_context_ref": context_ref,
                "review_snapshot_ref": snapshot_ref,
                "document_refs": [
                    item["document_version_ref"] for item in snapshot["input_snapshot"]["documents"]
                ],
                "review_date": snapshot["review_date"],
                "legal_publication_id": snapshot["legal_publication_id"],
                "legal_revision_id": snapshot["legal_revision_id"],
                "retry_count": row.retry_count,
            }

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    def parse_document(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            snapshot, _ = _snapshot_inputs(session, principal, row, model_policy)
            sections_payload = []
            for request_payload in snapshot["document_requests"]:
                request = DiscoveryDocumentRequest.model_validate(request_payload)
                doc = find_document(session, principal, row.project_id, request.document_id)
                parsed = sections(session, principal, row.project_id, request.document_id)
                sections_payload.append(
                    {
                        "document_id": doc.document_id,
                        "document_version_ref": next(
                            item["document_version_ref"]
                            for item in snapshot["input_snapshot"]["documents"]
                            if item["document_id"] == doc.document_id
                        ),
                        "raw_source_sha256": doc.sha256,
                        "parse_version": doc.parse_version,
                        "section_count": len(parsed.items),
                        "sections": [
                            {
                                "section_id": item.section_id,
                                "revision": item.revision,
                                "locator": item.effective.locator,
                                "text_sha256": item.effective.text_sha256,
                            }
                            for item in parsed.items
                        ],
                    }
                )
            index_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "section_index",
                {"documents": sections_payload},
            )
            session.commit()
            return {"section_index_ref": index_ref}

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    def quality_gate(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            snapshot, _ = _snapshot_inputs(session, principal, row, model_policy)
            documents_ready = all(
                item["section_count"] > 0
                for item in read_artifact(
                    session,
                    principal.tenant_id,
                    _required_ref(state, "section_index_ref"),
                    review_task_id=row.review_task_id,
                    run_id=row.run_id,
                )["documents"]
            )
            passed = bool(snapshot["input_snapshot"]["documents"]) and documents_ready
            record = {
                "status": "passed" if passed else "waiting_human",
                "parse_state": "ready_and_confirmed" if passed else "incomplete",
                "reason": None if passed else "no_confirmed_parsed_sections",
            }
            quality_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "parse_quality",
                record,
            )
            if not passed:
                row.status = "waiting_human"
                row.updated_at = datetime.now(UTC)
            session.commit()
            return {
                "parse_quality_ref": quality_ref,
                "status": "running" if passed else "waiting_human",
                "errors": []
                if passed
                else [
                    {
                        "code": "parse_quality_required",
                        "message": "Confirmed parsed sections are required.",
                        "node": "quality_gate",
                        "retryable": False,
                    }
                ],
            }

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    def plan_review(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            snapshot, _ = _snapshot_inputs(session, principal, row, model_policy)
            plan = {
                "plan_version": "task0009-plan-1",
                "snapshot_hash": row.snapshot_hash,
                "skill_ids": snapshot["skill_ids"],
                "candidate_topics_required": True,
                "prompt_version": snapshot["prompt_version"],
                "model_profile": snapshot["model_profile"],
                "legal_publication_id": snapshot["legal_publication_id"],
                "review_date": snapshot["review_date"],
            }
            plan_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "review_plan",
                plan,
            )
            session.commit()
            return {"review_plan_ref": plan_ref}

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    def dispatch_skills(state: ComplianceReviewState) -> list[Send]:
        if not state.get("review_snapshot_ref"):
            raise ValueError("review snapshot must be frozen before Skill dispatch")
        skills = selected_skill_ids
        return [
            Send(
                "skill_work",
                {
                    "skill_id": skill_id,
                    "tenant_id": state["tenant_id"],
                    "project_id": state["project_id"],
                    "review_task_id": state["review_task_id"],
                    "run_id": state["run_id"],
                    "review_snapshot_ref": state["review_snapshot_ref"],
                },
            )
            for skill_id in skills
        ]

    def candidate_discovery(state: ComplianceReviewState) -> dict[str, Any]:
        skill_ids = list(selected_skill_ids)
        return {
            "skill_expected": skill_ids,
            "skill_finished": [],
            "skill_result_refs": [],
        }

    def skill_work(item: SkillWorkItem) -> dict[str, Any]:
        skill_id = item["skill_id"]
        with session_factory() as session:
            row = authorized_run(session, principal, item["review_task_id"], item["run_id"])
            if row.status == "cancelled":
                raise RuntimeError("review run cancelled")
            snapshot = read_artifact(
                session,
                principal.tenant_id,
                item["review_snapshot_ref"],
                review_task_id=row.review_task_id,
                run_id=row.run_id,
            )
            requests = tuple(
                DiscoveryDocumentRequest.model_validate(entry)
                for entry in snapshot["document_requests"]
            )
            try:
                result = candidate_service.discover_for_project(
                    session,
                    principal,
                    row.project_id,
                    requests,
                    skill_ids=(skill_id,),  # type: ignore[arg-type]
                )
                if result.input_snapshot.model_dump(mode="json") != snapshot["input_snapshot"]:
                    raise ValueError("skill input no longer matches the frozen snapshot")
                content = {"skill_id": skill_id, "result": result.model_dump(mode="json")}
                kind = "skill_" + skill_id
            except PermissionError:
                raise
            except (LookupError, FileExistsError, ValueError, OSError):
                content = {"skill_id": skill_id, "error_code": "skill_execution_failed"}
                kind = "skill_failure_" + skill_id
            artifact_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                kind,
                content,
            )
            session.commit()
            return {"skill_finished": [skill_id], "skill_result_refs": [artifact_ref]}

    def candidate_join(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            expected = set(state.get("skill_expected", []))
            finished = set(state.get("skill_finished", []))
            references = state.get("skill_result_refs", [])
            if not expected or expected != finished or len(references) != len(expected):
                raise ValueError("candidate discovery join is incomplete")
            results: list[DiscoveryResult] = []
            errors: list[dict[str, Any]] = []
            for reference in references:
                payload = read_artifact(
                    session,
                    principal.tenant_id,
                    reference,
                    review_task_id=row.review_task_id,
                    run_id=row.run_id,
                )
                if "error_code" in payload:
                    errors.append(
                        {
                            "code": payload["error_code"],
                            "message": (
                                "One Skill could not complete; its coverage remains visible."
                            ),
                            "node": "candidate_discovery",
                            "retryable": False,
                        }
                    )
                else:
                    results.append(_discovery_from_artifact(payload["result"]))
            if len(results) != len(expected):
                join_payload = {
                    "status": "failed_skill",
                    "skill_expected": sorted(expected),
                    "skill_result_refs": references,
                }
                discovery_ref = put_artifact(
                    session,
                    principal.tenant_id,
                    row.review_task_id,
                    row.run_id,
                    "candidate_discovery",
                    join_payload,
                )
                session.commit()
                return {
                    "discovery_ref": discovery_ref,
                    "rule_findings_ref": discovery_ref,
                    "errors": errors,
                }
            joined = combine_discoveries(results)
            if len(joined.candidates) > MAX_CANDIDATES_FOR_REVIEW:
                return {
                    "errors": [
                        {
                            "code": "review_resource_limit",
                            "message": "Candidate count exceeds the bounded review limit.",
                            "node": "candidate_discovery",
                            "retryable": False,
                        }
                    ],
                    "status": "failed",
                }
            discovery_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "rule_candidate_discovery" if enable_llm_discovery else "candidate_discovery",
                joined.model_dump(mode="json"),
            )
            session.commit()
            return {
                "discovery_ref": discovery_ref,
                "rule_findings_ref": discovery_ref,
                "errors": errors,
            }

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    async def llm_candidate_discovery(state: ComplianceReviewState) -> dict[str, Any]:
        schema = llm_discovery.discovery_schema(schema_root)
        result: dict[str, Any]
        try:
            with session_factory() as session:
                row = _load_run(session, principal, state)
                snapshot, _ = _snapshot_inputs(session, principal, row, model_policy)
                discovery = _discovery_from_artifact(
                    read_artifact(
                        session,
                        principal.tenant_id,
                        _required_ref(state, "discovery_ref"),
                        review_task_id=row.review_task_id,
                        run_id=row.run_id,
                    )
                )
                requests = tuple(
                    DiscoveryDocumentRequest.model_validate(item)
                    for item in snapshot["document_requests"]
                )
                input_snapshot, located = snapshot_for_project(
                    session,
                    principal,
                    row.project_id,
                    requests,
                )
                if input_snapshot != discovery.input_snapshot:
                    raise ValueError("discovery fragments no longer match the frozen input")
                batches = llm_discovery.plan_discovery(located)
                section_count = sum(len(batch.sections) for batch in batches)
                plan = {
                    "snapshot_hash": row.snapshot_hash,
                    "status": "planned",
                    "prompt_version": llm_discovery.TASK0023_DISCOVERY_PROMPT_VERSION,
                    "batch_count": len(batches),
                    "sections": [
                        section.coverage() for batch in batches for section in batch.sections
                    ],
                }
                plan_ref = put_artifact(
                    session,
                    principal.tenant_id,
                    row.review_task_id,
                    row.run_id,
                    "llm_discovery_plan",
                    plan,
                )
                session.commit()
            candidates: list[CandidateFinding] = []
            batch_results = []
            pending = list(batches)
            next_index = len(batches)
            subdivision_batches = 0
            while pending:
                batch = pending.pop(0)
                request = llm_discovery.make_discovery_request(
                    batch,
                    tenant_id=principal.tenant_id,
                    task_id=row.review_task_id,
                    run_id=row.run_id,
                    snapshot_hash=row.snapshot_hash,
                )
                kind = f"llm_discovery_batch_{batch.index}"
                with session_factory() as session:
                    current = _load_run(session, principal, state)
                    _snapshot_inputs(session, principal, current, model_policy)
                    saved = list(
                        session.scalars(
                            select(ReviewArtifact).where(
                                ReviewArtifact.tenant_id == principal.tenant_id,
                                ReviewArtifact.review_task_id == row.review_task_id,
                                ReviewArtifact.run_id == row.run_id,
                                ReviewArtifact.kind == kind,
                            )
                        )
                    )
                    if len(saved) > 1:
                        raise ValueError("ambiguous discovery batch cache")
                    cached = saved[0] if saved else None
                    if cached is not None:
                        if (
                            content_hash(cached.content) != cached.content_hash
                            or cached.content.get("input_hash") != batch.input_hash
                            or cached.content.get("snapshot_hash") != row.snapshot_hash
                        ):
                            raise ValueError("discovery batch cache provenance mismatch")
                        record = cached.content
                        response = ModelResponse(
                            call_id=record["call_id"],
                            provider=record["provider"],
                            model=record["model"],
                            profile=record["profile"],
                            content=record["content"],
                            usage=ModelUsage(**record["usage"]),
                            latency_ms=record["latency_ms"],
                            response_hash=record["response_hash"],
                            finish_reason=record["finish_reason"],
                        )
                    else:
                        response = None
                try:
                    if response is None:
                        if row.retry_count:
                            request = replace(
                                request,
                                call_id=_retry_call_id(request.call_id, row.retry_count),
                            )
                        response = await gateway.generate_structured(
                            request,
                            schema,
                            replace(model_policy, max_attempts=1, max_output_tokens=2048),
                        )
                    accepted, rejected = llm_discovery.validate_response(
                        batch,
                        response,
                        expected_call_id=request.call_id,
                        profile=model_policy.profile,
                        schema=schema,
                    )
                except (ModelGatewayError, ValidationError, ValueError) as exc:
                    failure_code = (
                        exc.code.value
                        if isinstance(exc, ModelGatewayError)
                        else "response_invalid"
                    )
                    failed_children: tuple[Any, ...] = ()
                    if (
                        len(batch.sections) >= 2
                        and subdivision_batches + 2
                        <= llm_discovery.MAX_SUBDIVISION_BATCHES
                    ):
                        failed_children = llm_discovery.subdivide_batch(batch, next_index)
                    if failed_children:
                        next_index += len(failed_children)
                        subdivision_batches += len(failed_children)
                        pending.extend(failed_children)
                    batch_results.append(
                        {
                            "batch_index": batch.index,
                            "parent_index": batch.parent_index,
                            "depth": batch.depth,
                            "batch_input_hash": batch.input_hash,
                            "section_count": len(batch.sections),
                            "source_unit_hashes": sorted(
                                {
                                    llm_discovery.source_unit_hash(item.located)
                                    for item in batch.sections
                                }
                            ),
                            "accepted_count": 0,
                            "rejected_count": 0,
                            "saturated": False,
                            "subdivided": bool(failed_children),
                            "status": "subdivided" if failed_children else "failed",
                            "failure_code": failure_code,
                            "artifact_ref": None,
                            "response_hash": None,
                            "subdivision_children": [
                                child.index for child in failed_children
                            ],
                        }
                    )
                    continue
                record = {
                    "snapshot_hash": row.snapshot_hash,
                    "input_hash": batch.input_hash,
                    "batch_index": batch.index,
                    "call_id": response.call_id,
                    "provider": response.provider,
                    "model": response.model,
                    "profile": response.profile,
                    "response_hash": response.response_hash,
                    "content": dict(response.content),
                    "latency_ms": response.latency_ms,
                    "finish_reason": response.finish_reason,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "estimated_cost": response.usage.estimated_cost,
                    },
                    "accepted_count": len(accepted),
                    "rejections": list(rejected),
                    "sections": [item.coverage() for item in batch.sections],
                }
                with session_factory() as session:
                    _load_run(session, principal, state)
                    ref = put_artifact(
                        session,
                        principal.tenant_id,
                        row.review_task_id,
                        row.run_id,
                        kind,
                        record,
                    )
                    session.commit()
                candidates.extend(accepted)
                coverage = llm_discovery.batch_coverage(
                    batch, len(accepted), len(rejected)
                )
                children: tuple[Any, ...] = ()
                if (
                    coverage["saturated"]
                    and subdivision_batches + 2
                    <= llm_discovery.MAX_SUBDIVISION_BATCHES
                ):
                    children = llm_discovery.subdivide_batch(batch, next_index)
                    if children:
                        coverage = llm_discovery.batch_coverage(
                            batch, len(accepted), len(rejected), subdivided=True
                        )
                        next_index += len(children)
                        subdivision_batches += len(children)
                        pending.extend(children)
                batch_results.append(
                    {
                        **coverage,
                        "artifact_ref": ref,
                        "response_hash": response.response_hash,
                        "finish_reason": response.finish_reason,
                        "rejection_summaries": list(rejected),
                        "accepted_candidate_family_hashes": sorted(
                            {
                                llm_discovery.candidate_family_hash(candidate)
                                for candidate in accepted
                            }
                        ),
                        "subdivision_children": [child.index for child in children],
                    }
                )
            failed_batches = [
                item for item in batch_results if item.get("status") == "failed"
            ]
            if failed_batches and not candidates and len(failed_batches) == len(batch_results):
                last_failure = failed_batches[-1].get("failure_code")
                raw_code = last_failure if isinstance(last_failure, str) else "response_invalid"
                try:
                    error_code = GatewayErrorCode(raw_code)
                except ValueError:
                    error_code = GatewayErrorCode.RESPONSE_INVALID
                raise ModelGatewayError(
                    error_code,
                    "every model discovery batch failed; no coverage is available",
                )
            joined = llm_discovery.merge_model_candidates(discovery, candidates)
            if len(joined.candidates) > MAX_CANDIDATES_FOR_REVIEW:
                raise ValueError("LLM discovery exceeds the bounded review candidate limit")
            with session_factory() as session:
                _load_run(session, principal, state)
                coverage_ref = put_artifact(
                    session,
                    principal.tenant_id,
                    row.review_task_id,
                    row.run_id,
                    "llm_candidate_discovery",
                    {
                        **plan,
                        "status": (
                            "completed_with_failures"
                            if any(item.get("status") == "failed" for item in batch_results)
                            else "completed"
                        ),
                        "plan_ref": plan_ref,
                        "batches": batch_results,
                        "coverage": llm_discovery.coverage_summary(
                            batch_results, section_count=section_count
                        ),
                        "candidate_count": len(candidates),
                    },
                )
                discovery_ref = put_artifact(
                    session,
                    principal.tenant_id,
                    row.review_task_id,
                    row.run_id,
                    "candidate_discovery",
                    joined.model_dump(mode="json"),
                )
                session.commit()
            result = {
                "llm_discovery_ref": coverage_ref,
                "discovery_ref": discovery_ref,
                "rule_findings_ref": discovery_ref,
            }
        except PermissionError:
            raise
        except ModelGatewayError as exc:
            # Keep the provider error code so the bounded retry policy can see which
            # failures are transient instead of collapsing them into one generic code.
            result = {
                "status": "failed",
                "errors": [
                    {
                        "code": exc.code.value,
                        "message": "Exhaustive model discovery failed under the authorized policy.",
                        "node": "llm_candidate_discovery",
                        "retryable": exc.retryable,
                    }
                ],
            }
        except (ValueError, ValidationError):
            result = {
                "status": "failed",
                "errors": [
                    {
                        "code": "llm_discovery_failed",
                        "message": "Exhaustive model discovery failed under the authorized policy.",
                        "node": "llm_candidate_discovery",
                        "retryable": False,
                    }
                ],
            }
        _assert_bounded({**state, **result})
        return result

    def legal_retrieval(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            snapshot, _ = _snapshot_inputs(session, principal, row, model_policy)
            discovery_payload = read_artifact(
                session,
                principal.tenant_id,
                _required_ref(state, "discovery_ref"),
                review_task_id=row.review_task_id,
                run_id=row.run_id,
            )
            if discovery_payload.get("status") == "failed_skill":
                return {
                    "status": "failed",
                    "errors": [
                        {
                            "code": "skill_execution_failed",
                            "message": "Candidate discovery did not complete for every Skill.",
                            "node": "legal_retrieval",
                            "retryable": False,
                        }
                    ],
                }
            discovery = _discovery_from_artifact(discovery_payload)
            queries: list[tuple[str, str]] = [
                (topic.topic_id, topic.query_text) for topic in discovery.retrieval_topics
            ]
            for candidate in discovery.candidates:
                quote = " ".join(item.quote for item in candidate.source_excerpts)
                query = " ".join(
                    (candidate.category, candidate.problem_key, candidate.matched_reason, quote)
                )[:1000]
                queries.append((candidate.candidate_id, query))
            records = []
            for work_item_id, query in queries:
                result = retrieve_published_for_project(
                    session,
                    principal,
                    row.project_id,
                    text=query,
                    review_date=date.fromisoformat(snapshot["review_date"]),
                    include_references=True,
                    limit=10,
                    publication_id=row.publication_id,
                    retriever_factory=retriever_factory,
                )
                if result.run_snapshot is None:
                    continue
                if result.run_snapshot.tenant_id != principal.tenant_id:
                    raise PermissionError("retrieval result tenant mismatch")
                records.append(
                    {
                        "work_item_id": work_item_id,
                        "publication_id": row.publication_id,
                        "revision_id": row.revision_id,
                        "result": result.model_dump(mode="json"),
                    }
                )
            if len(records) != len(queries):
                raise ValueError("legal retrieval did not produce a frozen result for every query")
            # Retrieval commits its durable run, ending the transaction-local RLS
            # settings. Revalidate the actor and restore scope before artifact write.
            require_identity(session, principal)
            content = {
                "publication_id": row.publication_id,
                "revision_id": row.revision_id,
                "review_date": snapshot["review_date"],
                "results": records,
            }
            retrieval_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "legal_retrieval",
                content,
            )
            session.commit()
            return {"retrieval_results_ref": retrieval_ref}

        try:
            result = with_session(action)(state)
        except PermissionError:
            raise
        except Exception as exc:
            # Log only the exception type and field paths; never the query/document text.
            diagnostic = type(exc).__name__
            error_method = getattr(exc, "errors", None)
            if callable(error_method):
                paths = [
                    ".".join(str(part) for part in item.get("loc", ()))
                    for item in error_method()
                ]
                paths = [path for path in paths if path]
                if paths:
                    diagnostic += ":" + ",".join(paths)
            print(f"legal_retrieval_failed {diagnostic}", file=sys.stderr, flush=True)
            return {
                "status": "failed",
                "errors": [
                    {
                        "code": "legal_retrieval_failed",
                        "message": "Published legal retrieval failed; no analysis will be started.",
                        "node": "legal_retrieval",
                        "retryable": False,
                    }
                ],
            }
        _assert_bounded({**state, **result})
        return result

    async def semantic_analysis(state: ComplianceReviewState) -> dict[str, Any]:
        try:
            with session_factory() as session:
                row = _load_run(session, principal, state)
                snapshot, context = _snapshot_inputs(session, principal, row, model_policy)
                discovery = _discovery_from_artifact(
                    read_artifact(
                        session,
                        principal.tenant_id,
                        _required_ref(state, "discovery_ref"),
                        review_task_id=row.review_task_id,
                        run_id=row.run_id,
                    )
                )
                retrieval = read_artifact(
                    session,
                    principal.tenant_id,
                    _required_ref(state, "retrieval_results_ref"),
                    review_task_id=row.review_task_id,
                    run_id=row.run_id,
                )
                project_context = read_artifact(
                    session,
                    principal.tenant_id,
                    _required_ref(state, "project_context_ref"),
                    review_task_id=row.review_task_id,
                    run_id=row.run_id,
                )
                if (
                    project_context.get("context_sha256") != snapshot["project_context_sha256"]
                    or project_context.get("context") != context
                    or retrieval["publication_id"] != row.publication_id
                    or retrieval["revision_id"] != row.revision_id
                ):
                    raise ValueError("semantic analysis inputs do not match the frozen run")
                if len(discovery.candidates) > MAX_CANDIDATES_FOR_REVIEW:
                    raise ValueError("review candidate limit exceeded")
                retrieval_by_id = {
                    item["work_item_id"]: item["result"] for item in retrieval["results"]
                }
                if not discovery.candidates:
                    # A legitimate zero-candidate result needs no paid semantic call. Record
                    # an explicit empty analysis artifact so merge/report/manual-confirmation
                    # paths receive the same shape as a completed analysis.
                    empty_content = {"schema_version": "v1alpha1", "findings": []}
                    zero_payload = {
                        "schema_version": "v1alpha1",
                        "prompt_version": snapshot["prompt_version"],
                        "model_profile": snapshot["model_profile"],
                        "response_hash": hashlib.sha256(
                            _json(empty_content).encode("utf-8")
                        ).hexdigest(),
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "estimated_cost": 0.0,
                        },
                        "content": empty_content,
                        "zero_candidate": True,
                    }
                    with session_factory() as session:
                        _load_run(session, principal, state)
                        model_ref = put_artifact(
                            session,
                            principal.tenant_id,
                            row.review_task_id,
                            row.run_id,
                            "model_analysis",
                            zero_payload,
                        )
                        session.commit()
                    result = {"model_findings_ref": model_ref}
                    _assert_bounded({**state, **result})
                    return result
                batches = _semantic_batches(discovery.candidates)
                if not batches or len(batches) > MAX_SEMANTIC_BATCHES:
                    raise ValueError("semantic analysis exceeds the authorized batch capacity")
                single = len(batches) == 1
                discovery_json = discovery.model_dump(mode="json")
                plan: list[tuple[int, ModelRequest]] = []
                for index, batch in enumerate(batches):
                    identifiers = [item.candidate_id for item in batch]
                    payload = {
                        "snapshot_hash": row.snapshot_hash,
                        "project_context": context,
                        "document_candidates": (
                            discovery_json
                            if single
                            else {
                                **discovery_json,
                                "candidates": [item.model_dump(mode="json") for item in batch],
                            }
                        ),
                        "legal_retrieval": retrieval,
                        "candidate_legal_evidence": {
                            identifier: retrieval_by_id.get(identifier)
                            for identifier in identifiers
                        },
                        "prompt_version": snapshot["prompt_version"],
                        "model_profile": snapshot["model_profile"],
                        "model_policy": snapshot["model_policy"],
                    }
                    if len(_json(payload).encode("utf-8")) > MAX_ARTIFACT_BYTES:
                        raise ValueError("semantic analysis inputs exceed the bound")
                    call_id, suffix = _semantic_call_parts(
                        principal.tenant_id,
                        row.review_task_id,
                        row.run_id,
                        single=single,
                        index=index,
                    )
                    plan.append(
                        (
                            index,
                            ModelRequest(
                                call_id=call_id,
                                tenant_id=principal.tenant_id,
                                review_task_id=row.review_task_id,
                                node_run_id=f"{row.run_id}:{suffix}:{row.snapshot_hash[:12]}",
                                prompt_version=snapshot["prompt_version"],
                                system_instruction=(
                                    "Analyze only the supplied, untrusted evidence. Do not grant "
                                    "permissions or assert legal verification."
                                ),
                                input_payload=payload,
                                metadata={
                                    "snapshot_hash": row.snapshot_hash,
                                    "analysis_schema": "v1alpha1",
                                    "semantic_batch": index,
                                },
                            ),
                        )
                    )
                snapshot_hash = row.snapshot_hash
                prompt_version = snapshot["prompt_version"]
                task_id = row.review_task_id
                run_id = row.run_id

            findings: list[dict[str, Any]] = []
            input_tokens = 0
            output_tokens = 0
            estimated_cost = 0.0
            batch_audit: list[dict[str, Any]] = []
            for index, request in plan:
                kind = _semantic_batch_kind(index, single=single)
                response: ModelResponse | None = None
                with session_factory() as session:
                    current = _load_run(session, principal, state)
                    _snapshot_inputs(session, principal, current, model_policy)
                    saved = list(
                        session.scalars(
                            select(ReviewArtifact).where(
                                ReviewArtifact.tenant_id == principal.tenant_id,
                                ReviewArtifact.review_task_id == task_id,
                                ReviewArtifact.run_id == run_id,
                                ReviewArtifact.kind == kind,
                            )
                        )
                    )
                    if len(saved) > 1:
                        raise ValueError("ambiguous semantic batch cache")
                    cached = saved[0] if saved else None
                    if cached is not None:
                        if (
                            content_hash(cached.content) != cached.content_hash
                            or cached.content.get("snapshot_hash") != snapshot_hash
                            or cached.content.get("semantic_batch") != index
                            or not isinstance(cached.content.get("call_id"), str)
                        ):
                            raise ValueError("semantic batch cache provenance mismatch")
                        response = _semantic_response(cached.content)
                if response is None:
                    if row.retry_count:
                        request = replace(
                            request,
                            call_id=_retry_call_id(request.call_id, row.retry_count),
                        )
                    response = await _run_semantic_batch(
                        gateway, request, analysis_schema, model_policy
                    )
                record = {
                    "snapshot_hash": snapshot_hash,
                    "semantic_batch": index,
                    "semantic_batch_count": len(plan),
                    "call_id": response.call_id,
                    "provider": response.provider,
                    "model": response.model,
                    "profile": response.profile,
                    "response_hash": response.response_hash,
                    "content": dict(response.content),
                    "latency_ms": response.latency_ms,
                    "finish_reason": response.finish_reason,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "estimated_cost": response.usage.estimated_cost,
                    },
                }
                if not single:
                    with session_factory() as session:
                        _load_run(session, principal, state)
                        put_artifact(session, principal.tenant_id, task_id, run_id, kind, record)
                        session.commit()
                batch_findings = list(dict(response.content).get("findings", []))
                findings.extend(batch_findings)
                input_tokens += response.usage.input_tokens
                output_tokens += response.usage.output_tokens
                estimated_cost += float(response.usage.estimated_cost or 0.0)
                batch_audit.append(
                    {
                        "batch_index": index,
                        "call_id": response.call_id,
                        "response_hash": response.response_hash,
                        "finding_count": len(batch_findings),
                        "provider": response.provider,
                        "model": response.model,
                        "profile": response.profile,
                    }
                )
            if not batch_audit:
                raise ValueError("semantic analysis produced no batch result")
        except ModelGatewayError as exc:
            return {
                "status": "failed",
                "errors": [
                    {
                        "code": exc.code.value,
                        "message": "Structured model analysis failed under the configured policy.",
                        "node": "semantic_analysis",
                        "retryable": exc.retryable,
                    }
                ],
            }
        head = batch_audit[0]
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
        }
        if single:
            # Keep the historical single-request artifact identical to the original shape.
            model_payload: dict[str, Any] = {
                "schema_version": "v1alpha1",
                "prompt_version": prompt_version,
                "model_profile": head["profile"],
                "provider": head["provider"],
                "model": head["model"],
                "response_hash": head["response_hash"],
                "usage": usage,
                "content": {"schema_version": "v1alpha1", "findings": findings},
            }
        else:
            merged_content = {"schema_version": "v1alpha1", "findings": findings}
            model_payload = {
                "schema_version": "v1alpha1",
                "prompt_version": prompt_version,
                "model_profile": head["profile"],
                "provider": head["provider"],
                "model": head["model"],
                "response_hash": hashlib.sha256(
                    _json(merged_content).encode("utf-8")
                ).hexdigest(),
                "usage": usage,
                "content": merged_content,
                "semantic_batches": batch_audit,
            }
        with session_factory() as session:
            row = _load_run(session, principal, state)
            model_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "model_analysis",
                model_payload,
            )
            session.commit()
        result = {"model_findings_ref": model_ref}
        _assert_bounded({**state, **result})
        return result

    def merge_findings(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            snapshot, _ = _snapshot_inputs(session, principal, row, model_policy)
            discovery = _discovery_from_artifact(
                read_artifact(
                    session,
                    principal.tenant_id,
                    _required_ref(state, "discovery_ref"),
                    review_task_id=row.review_task_id,
                    run_id=row.run_id,
                )
            )
            model_record = read_artifact(
                session,
                principal.tenant_id,
                _required_ref(state, "model_findings_ref"),
                review_task_id=row.review_task_id,
                run_id=row.run_id,
            )
            model_items = model_record["content"].get("findings", [])
            by_candidate = {}
            invalid_model_refs = False
            allowed_ids = {candidate.candidate_id for candidate in discovery.candidates}
            for item in model_items:
                candidate_id = item.get("candidate_id")
                if candidate_id not in allowed_ids or candidate_id in by_candidate:
                    invalid_model_refs = True
                    continue
                by_candidate[candidate_id] = item
            legal_payload = read_artifact(
                session,
                principal.tenant_id,
                _required_ref(state, "retrieval_results_ref"),
                review_task_id=row.review_task_id,
                run_id=row.run_id,
            )
            results_by_id = {item["work_item_id"]: item for item in legal_payload["results"]}
            doc_refs = {
                item["document_id"]: item["document_version_ref"]
                for item in snapshot["input_snapshot"]["documents"]
            }
            risk_schema = _risk_schema(schema_root)
            evidence_schema = _evidence_schema(schema_root)
            from referencing import Registry, Resource

            registry = Registry().with_resources(
                [
                    (
                        "https://bidding-compliance.local/schemas/risk.schema.json",
                        Resource.from_contents(risk_schema),
                    ),
                    (
                        "https://bidding-compliance.local/schemas/evidence.schema.json",
                        Resource.from_contents(evidence_schema),
                    ),
                ]
            )
            risk_validator = Draft202012Validator(risk_schema, registry=registry)
            findings: list[dict[str, Any]] = []
            for candidate in discovery.candidates:
                model = by_candidate.get(candidate.candidate_id)
                candidate_result = results_by_id.get(candidate.candidate_id)
                doc_evidence = []
                document_valid = True
                for excerpt in candidate.source_excerpts:
                    evidence = verify_document_excerpt(
                        session,
                        principal,
                        project_id=row.project_id,
                        candidate=candidate,
                        excerpt=excerpt,
                        expected_document_refs=doc_refs,
                    )
                    if evidence is None:
                        document_valid = False
                    else:
                        doc_evidence.append(evidence)
                source_hashes = set(model.get("source_quote_sha256", [])) if model else set()
                if model and (
                    not source_hashes
                    or not source_hashes.issubset(
                        {item.quote_sha256 for item in candidate.source_excerpts}
                    )
                ):
                    document_valid = False
                selected_laws = set(model.get("legal_evidence_ids", [])) if model else set()
                # The model only received the first MAX_LEGAL_CANDIDATES_PER_CANDIDATE hits.
                # An ID outside that exposed set is treated as an invalid selection rather
                # than being honoured just because it exists deeper in the same retrieval run.
                exposed_evidence_ids = (
                    {
                        hit["evidence_id"]
                        for hit in candidate_result["result"]["hits"][
                            : llm_discovery.MAX_LEGAL_CANDIDATES_PER_CANDIDATE
                        ]
                    }
                    if candidate_result is not None
                    else set()
                )
                allowed_selected_laws = selected_laws & exposed_evidence_ids
                # verify_legal_hit proves a citation is genuine (the clause exists in the frozen
                # publication, the retrieval run reads back identically and the bytes match). It
                # says nothing about whether the clause is in force or applicable. Only clauses
                # that also satisfy the confirmation chain may act as formal legal evidence; the
                # rest stay reference-only even when the model selected them.
                confirmable_laws: list[Any] = []
                unconfirmed_laws: list[Any] = []
                law_invalid = bool(selected_laws - exposed_evidence_ids)
                if allowed_selected_laws and candidate_result is not None:
                    for hit_payload in candidate_result["result"]["hits"]:
                        if hit_payload["evidence_id"] not in allowed_selected_laws:
                            continue
                        hit, quote = verify_legal_hit(
                            session,
                            principal,
                            publication_id=row.publication_id or "",
                            revision_id=row.revision_id or "",
                            result_payload=candidate_result["result"],
                            hit_payload=hit_payload,
                        )
                        if hit is None or quote != hit.quote:
                            law_invalid = True
                            continue
                        if hit.eligible_for_confirmation:
                            confirmable_laws.append(hit)
                        else:
                            unconfirmed_laws.append(hit)
                    verified_ids = {
                        item.evidence_id for item in (*confirmable_laws, *unconfirmed_laws)
                    }
                    if len(verified_ids) != len(allowed_selected_laws):
                        law_invalid = True
                elif selected_laws:
                    law_invalid = True
                assessment = model["assessment"] if model else "uncertain"
                conflicts = []
                if assessment == "no_issue":
                    conflicts.append(
                        {
                            "source": "model",
                            "assessment": "no_issue",
                            "summary": (
                                "Deterministic candidate discovery and semantic analysis disagree."
                            ),
                        }
                    )
                if invalid_model_refs:
                    conflicts.append(
                        {
                            "source": "model",
                            "assessment": "invalid_reference",
                            "summary": "Unknown or duplicate model candidate reference.",
                        }
                    )
                # Citation authenticity and applicability do not approve a rule-to-law binding.
                # No such binding has been manually approved for this release (D2 is pending),
                # so keep even verified clauses as references and do not emit a legal conclusion.
                rule_law_binding_confirmed = False
                legal_valid = (
                    rule_law_binding_confirmed
                    and has_confirmable_legal_support(confirmable_laws, invalid=law_invalid)
                )
                evidence_status = evidence_status_for_support(
                    document_valid=document_valid, legal_valid=legal_valid
                )
                source = candidate.source_excerpts[0]
                primary_evidence = (
                    doc_evidence[0]
                    if doc_evidence
                    else {
                        "evidence_id": candidate.candidate_id,
                        "kind": "document",
                        "title": "待复核原文引用",
                        "article": None,
                        "quote": source.quote,
                        "source_uri": f"artifact://document/{source.document_sha256}",
                        "source_hash": source.document_sha256,
                        "page": source.page,
                        "locator": source.locator,
                        "effective_from": None,
                        "effective_to": None,
                        "version_status": "unverified",
                        "jurisdiction": None,
                    }
                )
                # A verified citation is not formal support for a finding until its rule binding
                # has a separate human confirmation.
                legal_evidence = (
                    [hit.evidence.model_dump(mode="json") for hit in confirmable_laws]
                    if rule_law_binding_confirmed
                    else []
                )
                # Genuine but unconfirmed clauses stay visible as references, so the report never
                # hides that law was found without verified applicability. Clauses the model
                # selected are included here too when they are not confirmable, which keeps the
                # classification truthful even when the model asks for an unverified clause.
                candidate_rule_ids = {
                    item.rule_id
                    for item in candidate.provenance
                    if item.origin == "rule" and item.rule_id is not None
                }

                def reference_payload(
                    hit: Any,
                    *,
                    selected: bool,
                    reason: str | None = None,
                    candidate_rule_ids: set[str] = candidate_rule_ids,
                ) -> dict[str, Any]:
                    payload = {
                        **hit.evidence.model_dump(mode="json"),
                        "confirmation_reason": reason or hit.reason,
                        "version_status": hit.version_status,
                        "applicable": False,
                        "selected_by_model": selected,
                        "adoption_status": getattr(hit, "adoption_status", "not_adopted"),
                        "adoption_policy_id": (
                            adoption_policy.policy_id if adoption_policy is not None else None
                        ),
                    }
                    if selected:
                        binding = binding_for(
                            rule_law_bindings,
                            rule_ids=candidate_rule_ids,
                            law_id=getattr(hit, "law_id", ""),
                            version=getattr(hit, "version", ""),
                            article=getattr(hit, "article", None),
                        )
                        if binding is not None:
                            payload.update(
                                {
                                    "rule_law_binding_id": binding.binding_id,
                                    "rule_law_binding_reason": binding.reason,
                                    "rule_law_binding_asserted_by": binding.asserted_by,
                                }
                            )
                    return payload

                legal_references: list[dict[str, Any]] = [
                    reference_payload(hit, selected=True) for hit in unconfirmed_laws
                ]
                if not rule_law_binding_confirmed:
                    legal_references.extend(
                        reference_payload(
                            hit,
                            selected=True,
                            reason="rule_law_binding_unreviewed",
                        )
                        for hit in confirmable_laws
                    )
                if candidate_result is not None:
                    reference_only_count = 0
                    for hit_payload in candidate_result["result"]["hits"]:
                        if hit_payload["evidence_id"] in allowed_selected_laws:
                            continue
                        if reference_only_count >= MAX_REFERENCE_ONLY_CLAUSES:
                            break
                        reference_hit, _ = verify_legal_hit(
                            session,
                            principal,
                            publication_id=row.publication_id or "",
                            revision_id=row.revision_id or "",
                            result_payload=candidate_result["result"],
                            hit_payload=hit_payload,
                        )
                        if reference_hit is None:
                            continue
                        legal_references.append(
                            reference_payload(reference_hit, selected=False)
                        )
                        reference_only_count += 1
                # A configured rule-law association is surfaced for the reviewer even when
                # the model chose not to cite it. It remains a reference, never formal
                # evidence, and only appears when the exact clause was retrieved.
                if candidate_result is not None and candidate_rule_ids:
                    existing_by_id = {
                        item.get("evidence_id"): item for item in legal_references
                    }
                    for hit_payload in candidate_result["result"]["hits"]:
                        binding_hit, _ = verify_legal_hit(
                            session,
                            principal,
                            publication_id=row.publication_id or "",
                            revision_id=row.revision_id or "",
                            result_payload=candidate_result["result"],
                            hit_payload=hit_payload,
                        )
                        if binding_hit is None:
                            continue
                        binding = binding_for(
                            rule_law_bindings,
                            rule_ids=candidate_rule_ids,
                            law_id=binding_hit.law_id,
                            version=binding_hit.version,
                            article=binding_hit.article,
                        )
                        if binding is None:
                            continue
                        configured = reference_payload(binding_hit, selected=True)
                        configured["selected_by_model"] = False
                        existing_reference = existing_by_id.get(binding_hit.evidence_id)
                        if existing_reference is not None:
                            existing_reference.update(
                                {
                                    "rule_law_binding_id": binding.binding_id,
                                    "rule_law_binding_reason": binding.reason,
                                    "rule_law_binding_asserted_by": binding.asserted_by,
                                }
                            )
                        else:
                            legal_references.insert(0, configured)
                            existing_by_id[binding_hit.evidence_id] = configured
                category = candidate.category
                finding_id = hashlib.sha256(
                    f"{principal.tenant_id}:{row.review_task_id}:{row.run_id}:{candidate.candidate_id}".encode()
                ).hexdigest()
                sources: list[str] = sorted({item.origin for item in candidate.provenance})
                if model:
                    sources.append("model")
                if legal_evidence:
                    sources.append("retrieval")
                finding: dict[str, Any] = {
                    "finding_id": finding_id,
                    "category": category,
                    "title": model.get("title", candidate.matched_reason[:300])
                    if model
                    else candidate.matched_reason[:300],
                    "description": model.get("description", candidate.matched_reason)
                    if model
                    else candidate.matched_reason,
                    "severity": model.get("severity", "medium") if model else "medium",
                    "evidence_status": evidence_status,
                    "review_status": "pending",
                    "source_excerpt": primary_evidence,
                    "sources": sorted(set(sources)),
                    "evidence": doc_evidence + legal_evidence,
                    "rule_ids": sorted(
                        {
                            item.rule_id
                            for item in candidate.provenance
                            if item.origin == "rule" and item.rule_id is not None
                        }
                    ),
                    "reasoning_summary": model.get("reasoning_summary")
                    if model
                    else "No semantic analysis was returned.",
                    "recommendation": model.get(
                        "recommendation", "由审查员核对该候选及其证据后决定。"
                    )
                    if model
                    else "由审查员核对该候选及其证据后决定。",
                    "confidence": model.get("confidence") if model else None,
                    "legal_references": legal_references,
                }
                if conflicts:
                    finding["conflicts"] = conflicts
                if not legal_valid:
                    for field in ("title", "description", "recommendation", "reasoning_summary"):
                        value = finding.get(field)
                        if isinstance(value, str):
                            finding[field] = unverified_risk_text(value)
                    finding["title"] = "待核验：" + finding["title"][:295]
                    finding["description"] = (
                        "本项为待核验风险，尚无法律违法认定依据。" + finding["description"]
                    )[:4000]
                risk_validator.validate(finding)
                findings.append(finding)
            findings = merge_duplicate_findings(findings)
            findings.sort(key=lambda item: item["finding_id"])
            artifact_payload = {
                "snapshot_hash": row.snapshot_hash,
                "discovery_ref": state["discovery_ref"],
                "model_findings_ref": state["model_findings_ref"],
                "retrieval_results_ref": state["retrieval_results_ref"],
                "findings": findings,
            }
            merged_ref = put_artifact(
                session,
                principal.tenant_id,
                row.review_task_id,
                row.run_id,
                "merged_findings",
                artifact_payload,
            )
            session.commit()
            return {
                "rule_findings_ref": merged_ref,
                "findings": [
                    {
                        "finding_id": item["finding_id"],
                        "title": item["title"][:300],
                        "category": item["category"],
                        "severity": item["severity"],
                        "evidence_status": item["evidence_status"],
                        "review_status": item["review_status"],
                    }
                    for item in findings
                ],
            }

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    def evidence_check(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            merged = read_artifact(
                session,
                principal.tenant_id,
                _required_ref(state, "rule_findings_ref"),
                review_task_id=row.review_task_id,
                run_id=row.run_id,
            )
            findings = merged["findings"]
            pending = [item["finding_id"] for item in findings] or [RESULT_PENDING_ID]
            row.status = "waiting_human"
            row.updated_at = datetime.now(UTC)
            task = session.get(ReviewTask, (principal.tenant_id, row.review_task_id))
            if task is not None:
                task.status = "waiting_human"
            session.commit()
            summaries = [
                {
                    "finding_id": item["finding_id"],
                    "title": item["title"][:300],
                    "category": item["category"],
                    "severity": item["severity"],
                    "evidence_status": item["evidence_status"],
                    "review_status": item["review_status"],
                }
                for item in findings
            ]
            return {"findings": summaries, "pending_review_ids": pending, "status": "waiting_human"}

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    def human_risk_review(state: ComplianceReviewState) -> dict[str, Any]:
        resume = interrupt(
            {
                "review_task_id": state["review_task_id"],
                "run_id": state["run_id"],
                "pending_review_ids": state.get("pending_review_ids", []),
                "snapshot_ref": state.get("review_snapshot_ref"),
            }
        )
        if not isinstance(resume, dict) or not isinstance(resume.get("decision_ids"), list):
            raise PermissionError("a persisted human decision is required to resume")

        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            worker_resume = (
                principal.background_worker
                and row.status == "running"
                and row.action == "resume"
            )
            if row.status != "waiting_human" and not worker_resume:
                raise ValueError("review is no longer waiting for human review")
            _snapshot_inputs(session, principal, row, model_policy)
            merged = read_artifact(
                session,
                principal.tenant_id,
                _required_ref(state, "rule_findings_ref"),
                review_task_id=row.review_task_id,
                run_id=row.run_id,
            )
            approved = approved_findings(session, principal, row, merged["findings"])
            submitted_ids = sorted(str(item) for item in resume["decision_ids"])
            persisted_ids = sorted(
                str(item)
                for item in session.scalars(
                    select(ReviewDecision.decision_id).where(
                        ReviewDecision.tenant_id == principal.tenant_id,
                        ReviewDecision.review_task_id == row.review_task_id,
                        ReviewDecision.run_id == row.run_id,
                    )
                )
            )
            if submitted_ids != persisted_ids:
                raise PermissionError("resume token does not match persisted reviewer decisions")
            row.status = "running"
            row.updated_at = datetime.now(UTC)
            task = session.get(ReviewTask, (principal.tenant_id, row.review_task_id))
            if task is not None:
                task.status = "running"
            session.commit()
            summaries = [
                {
                    "finding_id": item["finding_id"],
                    "title": item["title"][:300],
                    "category": item["category"],
                    "severity": item["severity"],
                    "evidence_status": item["evidence_status"],
                    "review_status": item["review_status"],
                }
                for item in approved
            ]
            return {"findings": summaries, "status": "running"}

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    def publish_result(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            merged = read_artifact(
                session,
                principal.tenant_id,
                _required_ref(state, "rule_findings_ref"),
                review_task_id=row.review_task_id,
                run_id=row.run_id,
            )
            record = persist_result(
                session,
                principal,
                row=row,
                findings=merged["findings"],
            )
            return {
                "result_ref": f"review-result://{record.result_id}/{record.content_hash}",
                "status": "result_published",
                "report_ref": None,
            }

        result = with_session(action)(state)
        _assert_bounded({**state, **result})
        return result

    def generate_report(state: ComplianceReviewState) -> dict[str, Any]:
        # Report rendering is explicitly deferred to the later reporting task.
        if state.get("result_ref") is None:
            raise ValueError("published result is required before report handoff")
        return {"report_ref": None, "status": "result_published"}

    def finalize_task(state: ComplianceReviewState) -> dict[str, Any]:
        # A database result is durable; this task does not claim an unimplemented report.
        return {"status": "result_published", "report_ref": None}

    def failed(state: ComplianceReviewState) -> dict[str, Any]:
        def action(session: Session) -> dict[str, Any]:
            row = _load_run(session, principal, state)
            row.status = "failed"
            row.failure_code = (
                state.get("errors", [{}])[-1].get("code", "review_failed")
                if state.get("errors")
                else "review_failed"
            )
            row.updated_at = datetime.now(UTC)
            task = session.get(ReviewTask, (principal.tenant_id, row.review_task_id))
            if task is not None:
                task.status = "failed"
            session.commit()
            return {"status": "failed"}

        return with_session(action)(state)

    def route_after_quality(state: ComplianceReviewState) -> str:
        return "plan_review" if state["status"] == "running" else "human_parse_review"

    def human_parse_review(state: ComplianceReviewState) -> dict[str, Any]:
        # Persistent interrupt only; parse correction management is intentionally out of scope.
        interrupt(
            {
                "reason": "confirmed_parsed_sections_required",
                "review_task_id": state["review_task_id"],
                "run_id": state["run_id"],
            }
        )
        return {"status": "waiting_human"}

    def route_after_discovery(state: ComplianceReviewState) -> str:
        if state["status"] == "failed":
            return "failed"
        return "llm_candidate_discovery" if enable_llm_discovery else "legal_retrieval"

    def route_after_llm_discovery(state: ComplianceReviewState) -> str:
        return "failed" if state["status"] == "failed" else "legal_retrieval"

    def route_after_retrieval(state: ComplianceReviewState) -> str:
        return "failed" if state["status"] == "failed" else "semantic_analysis"

    def route_after_semantics(state: ComplianceReviewState) -> str:
        return "failed" if state["status"] == "failed" else "merge_findings"

    graph = StateGraph(ComplianceReviewState)
    graph.add_node("load_context", load_context)
    graph.add_node("parse_document", parse_document)
    graph.add_node("quality_gate", quality_gate)
    graph.add_node("human_parse_review", human_parse_review)
    graph.add_node("plan_review", plan_review)
    graph.add_node("candidate_discovery", candidate_discovery)
    graph.add_node("skill_work", cast(Any, skill_work), input_schema=SkillWorkItem)
    graph.add_node("candidate_join", candidate_join)
    if enable_llm_discovery:
        graph.add_node("llm_candidate_discovery", llm_candidate_discovery)
    graph.add_node("legal_retrieval", legal_retrieval)
    graph.add_node("semantic_analysis", semantic_analysis)
    graph.add_node("merge_findings", merge_findings)
    graph.add_node("evidence_check", evidence_check)
    graph.add_node("human_risk_review", human_risk_review)
    graph.add_node("publish_result", publish_result)
    graph.add_node("generate_report", generate_report)
    graph.add_node("finalize_task", finalize_task)
    graph.add_node("failed", failed)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "parse_document")
    graph.add_edge("parse_document", "quality_gate")
    graph.add_conditional_edges(
        "quality_gate",
        route_after_quality,
        {"plan_review": "plan_review", "human_parse_review": "human_parse_review"},
    )
    graph.add_edge("human_parse_review", END)
    graph.add_edge("plan_review", "candidate_discovery")
    graph.add_conditional_edges("candidate_discovery", dispatch_skills)
    graph.add_edge("skill_work", "candidate_join")
    graph.add_conditional_edges(
        "candidate_join",
        route_after_discovery,
        {
            "legal_retrieval": "legal_retrieval",
            "failed": "failed",
            **(
                {"llm_candidate_discovery": "llm_candidate_discovery"}
                if enable_llm_discovery
                else {}
            ),
        },
    )
    if enable_llm_discovery:
        graph.add_conditional_edges(
            "llm_candidate_discovery",
            route_after_llm_discovery,
            {"legal_retrieval": "legal_retrieval", "failed": "failed"},
        )
    graph.add_conditional_edges(
        "legal_retrieval",
        route_after_retrieval,
        {"semantic_analysis": "semantic_analysis", "failed": "failed"},
    )
    graph.add_conditional_edges(
        "semantic_analysis",
        route_after_semantics,
        {"merge_findings": "merge_findings", "failed": "failed"},
    )
    graph.add_edge("merge_findings", "evidence_check")
    graph.add_edge("evidence_check", "human_risk_review")
    graph.add_edge("human_risk_review", "publish_result")
    graph.add_edge("publish_result", "generate_report")
    graph.add_edge("generate_report", "finalize_task")
    graph.add_edge("finalize_task", END)
    graph.add_edge("failed", END)
    return graph.compile(checkpointer=checkpointer)


def initial_state(
    *,
    tenant_id: str,
    project_id: str,
    review_task_id: str,
    run_id: str,
    document_refs: list[str],
) -> ComplianceReviewState:
    return ComplianceReviewState(
        schema_version="v1alpha2",
        tenant_id=tenant_id,
        project_id=project_id,
        review_task_id=review_task_id,
        run_id=run_id,
        status="queued",
        document_refs=document_refs,
        findings=[],
        errors=[],
    )
