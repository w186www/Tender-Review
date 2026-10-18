"""Authorized query and publication operations for the human review boundary."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bidding_compliance.core.dates import isoformat_utc
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.domain.rules.models import DiscoveryDocumentRequest
from bidding_compliance.ingestion.schemas import DocumentContext
from bidding_compliance.persistence.models import (
    Document,
    DocumentContextVersion,
    DocumentSection,
    ReviewArtifact,
    ReviewDecision,
    ReviewEngineRun,
    ReviewModelCall,
    ReviewResult,
    SectionRevision,
)
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.llm_candidate_discovery import (
    MAX_BATCH_SECTIONS,
    MAX_BATCH_SOURCE_BYTES,
    MAX_DISCOVERY_BATCHES,
)
from bidding_compliance.services.project_context import (
    ProjectContextIncomplete,
    ProjectDocumentContextMismatch,
    document_context_mismatch_fields,
    project_context_issues,
)
from bidding_compliance.services.projects import find_project
from bidding_compliance.services.review_persistence import (
    authorized_run,
    content_hash,
    publish_result,
)
from bidding_compliance.services.review_projection import project_product_execution


def _require_reader(session: Session, principal: Principal) -> None:
    require_identity(session, principal)
    if principal.role not in {Role.REVIEWER, Role.AUDITOR}:
        audit(session, principal.tenant_id, principal.user_id, "review.read_denied")
        session.commit()
        raise PermissionError("review results are not authorized")


def document_requests(
    session: Session, principal: Principal, project_id: str, document_ids: list[str]
) -> tuple[DiscoveryDocumentRequest, ...]:
    require_identity(session, principal)
    if principal.role is not Role.REVIEWER:
        raise PermissionError("review creation requires reviewer role")
    project = find_project(session, principal, project_id)
    context_issues = project_context_issues(project.context)
    if context_issues:
        raise ProjectContextIncomplete(context_issues)
    rows = list(
        session.scalars(
            select(Document).where(
                Document.tenant_id == principal.tenant_id,
                Document.project_id == project_id,
                Document.document_id.in_(document_ids),
            )
        )
    )
    by_id = {row.document_id: row for row in rows}
    if len(by_id) != len(document_ids):
        raise LookupError("one or more documents are unavailable")
    selected = list(by_id)
    sections = list(
        session.scalars(
            select(DocumentSection).where(
                DocumentSection.tenant_id == principal.tenant_id,
                DocumentSection.document_id.in_(selected),
            )
        )
    )
    if len(sections) > MAX_DISCOVERY_BATCHES * MAX_BATCH_SECTIONS:
        raise ValueError("selected documents exceed the review discovery capacity")
    effective: dict[tuple[str, str], dict[str, Any]] = {}
    for revision in session.scalars(
        select(SectionRevision).where(
            SectionRevision.tenant_id == principal.tenant_id,
            SectionRevision.document_id.in_(selected),
        )
    ):
        key = (revision.document_id, revision.section_id)
        current = effective.get(key)
        if current is None or revision.revision > int(current.get("revision", 0)):
            effective[key] = revision.payload
    total_bytes = 0
    for section in sections:
        payload = effective.get((section.document_id, section.section_id), section.automatic)
        total_bytes += len(str(payload.get("text", "")).encode())
    if total_bytes > MAX_DISCOVERY_BATCHES * MAX_BATCH_SOURCE_BYTES:
        raise ValueError("selected documents exceed the review discovery capacity")
    requests = []
    for document_id in sorted(document_ids):
        row = by_id[document_id]
        if row.status != "ready" or row.parse_version < 1 or row.context_version < 1:
            raise ValueError("review requires parsed documents with confirmed context")
        context_record = session.get(
            DocumentContextVersion,
            (principal.tenant_id, document_id, row.context_version),
        )
        if context_record is None:
            raise ValueError("review requires a persisted document context confirmation")
        confirmed_context = DocumentContext.model_validate(context_record.payload)
        if not confirmed_context.confirmed or confirmed_context.manual is None:
            raise ValueError("review requires a confirmed document context")
        mismatched_fields = document_context_mismatch_fields(
            project.context, confirmed_context.manual.model_dump(mode="json")
        )
        if mismatched_fields:
            raise ProjectDocumentContextMismatch(mismatched_fields, document_id)
        requests.append(
            DiscoveryDocumentRequest(
                document_id=row.document_id,
                raw_source_sha256=row.sha256,
                parse_version=row.parse_version,
                context_version=row.context_version,
            )
        )
    return tuple(requests)


def _run_projection(session: Session, row: ReviewEngineRun) -> dict[str, Any]:
    result = session.scalar(
        select(ReviewResult).where(
            ReviewResult.tenant_id == row.tenant_id,
            ReviewResult.review_task_id == row.review_task_id,
            ReviewResult.run_id == row.run_id,
        )
    )
    return {
        "review_task_id": row.review_task_id,
        "project_id": row.project_id,
        "run_id": row.run_id,
        "status": row.status,
        "snapshot_hash": row.snapshot_hash,
        "retry_count": row.retry_count,
        "failure_code": row.failure_code,
        "result_id": result.result_id if result else None,
        "created_at": isoformat_utc(row.created_at),
        "document_ids": [item["document_id"] for item in row.snapshot.get("document_requests", [])],
        "model_runtime": _runtime_projection(session, row),
    }


def _runtime_projection(session: Session, row: ReviewEngineRun) -> dict[str, Any]:
    artifacts = list(
        session.scalars(
            select(ReviewArtifact).where(
                ReviewArtifact.tenant_id == row.tenant_id,
                ReviewArtifact.review_task_id == row.review_task_id,
                ReviewArtifact.run_id == row.run_id,
            )
        )
    )
    if any(content_hash(item.content) != item.content_hash for item in artifacts):
        raise ValueError("runtime artifact hash verification failed")
    model_records = [
        item.content
        for item in artifacts
        if item.kind == "model_analysis"
        or item.kind.startswith("llm_discovery_batch_")
        or item.kind.startswith("semantic_analysis_batch_")
    ]
    model_records = [item for item in model_records if item.get("provider") and item.get("model")]
    # The batched semantic aggregate repeats per-batch usage, so only batches are counted.
    model_records = [item for item in model_records if not item.get("semantic_batches")]
    latest = next(
        (item for item in model_records if "model_profile" in item),
        model_records[0] if model_records else {},
    )
    candidates: list[dict[str, Any]] = next(
        (
            item.content.get("candidates", [])
            for item in artifacts
            if item.kind == "candidate_discovery"
        ),
        [],
    )
    usages = [item.get("usage", {}) for item in model_records]
    provenance = row.snapshot.get("runtime_provenance", {})
    embedding = provenance.get("embedding_identity", {})
    profile = row.snapshot.get("model_profile", "")
    mode = (
        "real-qwen"
        if profile == "dec005-real-qwen"
        else ("offline-deterministic" if "offline" in profile else "unknown")
    )
    return {
        "execution_mode": mode,
        "provider": latest.get("provider"),
        "model": latest.get("model"),
        "response_received": bool(model_records),
        "model_calls": len(model_records),
        "input_tokens": sum(item.get("input_tokens", 0) for item in usages),
        "output_tokens": sum(item.get("output_tokens", 0) for item in usages),
        "estimated_cost_cny": sum(item.get("estimated_cost", 0) or 0 for item in usages),
        "skill_candidate_count": sum(item.get("origin", "rule") == "rule" for item in candidates),
        "model_candidate_count": sum(item.get("origin", "rule") == "model" for item in candidates),
        "embedding_model": embedding.get("model_id"),
        "vector_index_build_id": provenance.get("vector_index_build_id"),
    }


def get_review_status(
    session: Session, principal: Principal, review_task_id: str
) -> dict[str, Any]:
    _require_reader(session, principal)
    row = session.scalar(
        select(ReviewEngineRun).where(
            ReviewEngineRun.tenant_id == principal.tenant_id,
            ReviewEngineRun.review_task_id == review_task_id,
        )
    )
    if row is None:
        raise LookupError("review unavailable")
    find_project(session, principal, row.project_id)
    return _run_projection(session, row)


def authorize_review_control(
    session: Session, principal: Principal, review_task_id: str, run_id: str, action: str
) -> ReviewEngineRun:
    row = authorized_run(session, principal, review_task_id, run_id)
    if principal.role is not Role.REVIEWER:
        audit(
            session,
            principal.tenant_id,
            principal.user_id,
            f"review.{action}_denied",
            review_task_id,
        )
        session.commit()
        raise PermissionError("review control requires reviewer role")
    return row


def get_run_by_identity(
    session: Session, principal: Principal, review_task_id: str
) -> dict[str, Any] | None:
    _require_reader(session, principal)
    row = session.scalar(
        select(ReviewEngineRun).where(
            ReviewEngineRun.tenant_id == principal.tenant_id,
            ReviewEngineRun.review_task_id == review_task_id,
        )
    )
    if row is None:
        return None
    find_project(session, principal, row.project_id)
    return _run_projection(session, row)


def list_project_reviews(
    session: Session,
    principal: Principal,
    project_id: str,
    *,
    offset: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    _require_reader(session, principal)
    find_project(session, principal, project_id)
    condition = (ReviewEngineRun.tenant_id == principal.tenant_id) & (
        ReviewEngineRun.project_id == project_id
    )
    total = session.scalar(select(func.count()).select_from(ReviewEngineRun).where(condition)) or 0
    rows = session.scalars(
        select(ReviewEngineRun)
        .where(condition)
        .order_by(ReviewEngineRun.created_at.desc(), ReviewEngineRun.review_task_id)
        .offset(offset)
        .limit(limit)
    )
    return [_run_projection(session, row) for row in rows], total


def list_waiting(
    session: Session, principal: Principal, *, offset: int, limit: int
) -> list[dict[str, Any]]:
    _require_reader(session, principal)
    rows = session.scalars(
        select(ReviewEngineRun)
        .where(
            ReviewEngineRun.tenant_id == principal.tenant_id,
            ReviewEngineRun.status == "waiting_human",
        )
        .order_by(ReviewEngineRun.created_at, ReviewEngineRun.review_task_id)
        .offset(offset)
        .limit(limit)
    )
    result = []
    for row in rows:
        find_project(session, principal, row.project_id)
        result.append(
            {
                "review_task_id": row.review_task_id,
                "run_id": row.run_id,
                "project_id": row.project_id,
                "snapshot_hash": row.snapshot_hash,
                "status": row.status,
                "created_at": isoformat_utc(row.created_at),
            }
        )
    return result


def get_findings(
    session: Session, principal: Principal, review_task_id: str, run_id: str
) -> dict[str, Any]:
    _require_reader(session, principal)
    row = authorized_run(session, principal, review_task_id, run_id)
    artifact = session.scalar(
        select(ReviewArtifact).where(
            ReviewArtifact.tenant_id == principal.tenant_id,
            ReviewArtifact.review_task_id == review_task_id,
            ReviewArtifact.run_id == run_id,
            ReviewArtifact.kind == "merged_findings",
        )
    )
    findings = []
    if artifact is not None:
        if content_hash(artifact.content) != artifact.content_hash:
            raise ValueError("review findings artifact hash mismatch")
        findings = json.loads(json.dumps(artifact.content.get("findings", []), ensure_ascii=False))
    decisions = list(
        session.scalars(
            select(ReviewDecision).where(
                ReviewDecision.tenant_id == principal.tenant_id,
                ReviewDecision.review_task_id == review_task_id,
                ReviewDecision.run_id == run_id,
                ReviewDecision.snapshot_hash == row.snapshot_hash,
            )
        )
    )
    by_id = {item.finding_id: item for item in decisions}
    for finding in findings:
        decision = by_id.get(finding["finding_id"])
        if decision is not None:
            finding["review_status"] = {
                "accept": "accepted",
                "modify": "modified",
                "reject": "rejected",
            }[decision.decision]
            finding["human_review"] = {
                "reviewer_id": decision.reviewer_id,
                "decided_at": isoformat_utc(decision.decided_at),
                "reason": decision.reason,
            }
            if decision.modified_finding:
                finding.update(decision.modified_finding)
    pending = [item["finding_id"] for item in findings if item["finding_id"] not in by_id]
    if not findings and not any(item.finding_id == "__review_complete__" for item in decisions):
        pending = ["__review_complete__"]
    unknown_calls = session.scalar(
        select(func.count())
        .select_from(ReviewModelCall)
        .where(
            ReviewModelCall.tenant_id == principal.tenant_id,
            ReviewModelCall.review_task_id == review_task_id,
            ReviewModelCall.run_id == run_id,
            ReviewModelCall.state == "unknown",
        )
    )
    discovery = session.scalar(
        select(ReviewArtifact).where(
            ReviewArtifact.tenant_id == principal.tenant_id,
            ReviewArtifact.review_task_id == review_task_id,
            ReviewArtifact.run_id == run_id,
            ReviewArtifact.kind == "llm_candidate_discovery",
        )
    )
    coverage: dict[str, Any] | None = None
    batches: list[dict[str, Any]] | None = None
    if discovery is not None:
        if content_hash(discovery.content) != discovery.content_hash:
            raise ValueError("model discovery coverage hash mismatch")
        raw_coverage = discovery.content.get("coverage")
        if isinstance(raw_coverage, dict):
            coverage = raw_coverage
        raw_batches = discovery.content.get("batches")
        if isinstance(raw_batches, list):
            batches = raw_batches
    if coverage is None and int(_runtime_projection(session, row)["model_candidate_count"]) > 0:
        product_execution = {
            "completion_status": "partial",
            "coverage_status": "unknown",
            "unprocessed_units": 0,
            "truncated": False,
            "saturated": False,
            "reason_codes": ["coverage_not_recorded"],
            "unknown_model_call_count": int(unknown_calls or 0),
        }
    else:
        product_execution = project_product_execution(
            coverage,
            unknown_model_call_count=int(unknown_calls or 0),
            batches=batches,
        )
    product_execution["run_status"] = row.status
    if row.status in {"queued", "running"} and product_execution["completion_status"] == "complete":
        product_execution["completion_status"] = "pending"
    return {
        "review_task_id": review_task_id,
        "run_id": run_id,
        "snapshot_hash": row.snapshot_hash,
        "status": row.status,
        "findings": findings,
        "pending_finding_ids": pending,
        "product_execution": product_execution,
    }


def get_history(
    session: Session, principal: Principal, review_task_id: str, run_id: str
) -> list[ReviewDecision]:
    _require_reader(session, principal)
    authorized_run(session, principal, review_task_id, run_id)
    rows = list(
        session.scalars(
            select(ReviewDecision)
            .where(
                ReviewDecision.tenant_id == principal.tenant_id,
                ReviewDecision.review_task_id == review_task_id,
                ReviewDecision.run_id == run_id,
            )
            .order_by(ReviewDecision.decided_at, ReviewDecision.decision_id)
        )
    )
    return rows


def publish_review(
    session: Session, principal: Principal, review_task_id: str, run_id: str
) -> ReviewResult:
    require_identity(session, principal)
    if principal.role is not Role.REVIEWER:
        audit(
            session, principal.tenant_id, principal.user_id, "review.publish_denied", review_task_id
        )
        session.commit()
        raise PermissionError("result publication requires reviewer role")
    row = authorized_run(session, principal, review_task_id, run_id)
    artifact = session.scalar(
        select(ReviewArtifact).where(
            ReviewArtifact.tenant_id == principal.tenant_id,
            ReviewArtifact.review_task_id == review_task_id,
            ReviewArtifact.run_id == run_id,
            ReviewArtifact.kind == "merged_findings",
        )
    )
    if artifact is None or content_hash(artifact.content) != artifact.content_hash:
        raise ValueError("complete merged findings are unavailable")
    return publish_result(
        session,
        principal,
        row=row,
        findings=artifact.content.get("findings", []),
    )
