"""Tenant-authorized immutable artifacts, human decisions and result publication."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing import Registry, Resource
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bidding_compliance.core.dates import isoformat_utc
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.persistence.models import (
    ReviewArtifact,
    ReviewDecision,
    ReviewEngineRun,
    ReviewResult,
    ReviewTask,
)
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.projects import find_project

MAX_ARTIFACT_BYTES = 20_000_000
RESULT_PENDING_ID = "__review_complete__"
ROOT = Path(__file__).resolve().parents[3]


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def put_artifact(
    session: Session,
    tenant_id: str,
    review_task_id: str,
    run_id: str,
    kind: str,
    content: dict[str, Any],
) -> str:
    encoded = canonical_json(content).encode("utf-8")
    if len(encoded) > MAX_ARTIFACT_BYTES:
        raise ValueError("review artifact exceeds its storage limit")
    digest = hashlib.sha256(encoded).hexdigest()
    artifact_id = hashlib.sha256(
        f"{tenant_id}\0{review_task_id}\0{run_id}\0{kind}\0{digest}".encode()
    ).hexdigest()
    row = ReviewArtifact(
        tenant_id=tenant_id,
        artifact_id=artifact_id,
        review_task_id=review_task_id,
        run_id=run_id,
        kind=kind,
        content=content,
        content_hash=digest,
        created_at=datetime.now(UTC),
    )
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            insert(ReviewArtifact)
            .values(
                tenant_id=row.tenant_id,
                artifact_id=row.artifact_id,
                review_task_id=row.review_task_id,
                run_id=row.run_id,
                kind=row.kind,
                content=row.content,
                content_hash=row.content_hash,
                created_at=row.created_at,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "artifact_id"])
        )
    else:
        existing = session.get(ReviewArtifact, (tenant_id, artifact_id))
        if existing is None:
            session.add(row)
            session.flush()
    existing = session.get(ReviewArtifact, (tenant_id, artifact_id), populate_existing=True)
    if existing is None or existing.content_hash != digest or existing.content != content:
        raise ValueError("review artifact idempotency conflict")
    return f"artifact://review/{artifact_id}/{digest}"


def read_artifact(
    session: Session,
    tenant_id: str,
    reference: str,
    *,
    review_task_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not reference.startswith("artifact://review/"):
        raise ValueError("invalid review artifact reference")
    parts = reference.removeprefix("artifact://review/").split("/")
    if len(parts) != 2 or any(len(item) != 64 for item in parts):
        raise ValueError("invalid review artifact reference")
    artifact_id, expected_hash = parts
    row = session.get(ReviewArtifact, (tenant_id, artifact_id), populate_existing=True)
    if (
        row is None
        or row.content_hash != expected_hash
        or content_hash(row.content) != expected_hash
        or (review_task_id is not None and row.review_task_id != review_task_id)
        or (run_id is not None and row.run_id != run_id)
    ):
        raise ValueError("review artifact provenance mismatch")
    return row.content


def authorized_run(
    session: Session,
    principal: Principal,
    review_task_id: str,
    run_id: str,
) -> ReviewEngineRun:
    require_identity(session, principal)
    row = session.get(
        ReviewEngineRun,
        (principal.tenant_id, review_task_id, run_id),
        populate_existing=True,
    )
    if row is None:
        raise LookupError("resource unavailable")
    find_project(session, principal, row.project_id)
    return row


def update_run_status(
    session: Session,
    principal: Principal,
    review_task_id: str,
    run_id: str,
    status: str,
) -> None:
    row = authorized_run(session, principal, review_task_id, run_id)
    allowed = {
        "queued": {"running", "cancelled", "failed"},
        "running": {"running", "waiting_human", "result_published", "cancelled", "failed"},
        "waiting_human": {"waiting_human", "running", "cancelled", "failed"},
        "failed": {"failed", "running", "cancelled"},
        "cancelled": {"cancelled"},
        "result_published": {"result_published"},
    }
    if status not in allowed.get(row.status, set()):
        raise ValueError("invalid review run status transition")
    row.status = status
    row.updated_at = datetime.now(UTC)
    task = session.get(ReviewTask, (principal.tenant_id, review_task_id))
    if task is not None and status in {"queued", "running", "waiting_human", "failed", "cancelled"}:
        task.status = status
    session.commit()


def cancel_review(
    session: Session,
    principal: Principal,
    review_task_id: str,
    run_id: str,
) -> None:
    if principal.role is not Role.REVIEWER:
        raise PermissionError("review cancellation requires reviewer role")
    row = authorized_run(session, principal, review_task_id, run_id)
    if row.status == "result_published":
        raise ValueError("published result cannot be cancelled")
    row.status = "cancelled"
    row.updated_at = datetime.now(UTC)
    task = session.get(ReviewTask, (principal.tenant_id, review_task_id))
    if task is not None:
        task.status = "cancelled"
    audit(session, principal.tenant_id, principal.user_id, "review.cancel", review_task_id)
    session.commit()


def _finding_for_decision(
    session: Session,
    principal: Principal,
    row: ReviewEngineRun,
    finding_id: str,
) -> dict[str, Any] | None:
    artifact = session.scalar(
        select(ReviewArtifact).where(
            ReviewArtifact.tenant_id == principal.tenant_id,
            ReviewArtifact.review_task_id == row.review_task_id,
            ReviewArtifact.run_id == row.run_id,
            ReviewArtifact.kind == "merged_findings",
        )
    )
    if artifact is None or content_hash(artifact.content) != artifact.content_hash:
        return None
    for finding in artifact.content.get("findings", []):
        if finding.get("finding_id") == finding_id:
            return cast(dict[str, Any], finding)
    return None


def submit_decision(
    session: Session,
    principal: Principal,
    *,
    review_task_id: str,
    run_id: str,
    finding_id: str,
    decision: str,
    request_id: str,
    reason: str,
    modified_finding: dict[str, Any] | None = None,
    expected_snapshot_hash: str | None = None,
    request_trace_id: str | None = None,
) -> ReviewDecision:
    require_identity(session, principal)
    if principal.role is not Role.REVIEWER:
        audit(session, principal.tenant_id, principal.user_id, "review.decision_denied", finding_id)
        session.commit()
        raise PermissionError("human review requires reviewer role")
    row = authorized_run(session, principal, review_task_id, run_id)
    if row.snapshot_hash != content_hash(row.snapshot):
        raise ValueError("review snapshot hash mismatch")
    if expected_snapshot_hash is not None and expected_snapshot_hash != row.snapshot_hash:
        raise ValueError("review result version conflict")
    existing_request = session.scalar(
        select(ReviewDecision).where(
            ReviewDecision.tenant_id == principal.tenant_id,
            ReviewDecision.reviewer_id == principal.user_id,
            ReviewDecision.request_id == request_id,
        )
    )
    if existing_request is not None:
        if (
            existing_request.review_task_id != review_task_id
            or existing_request.run_id != run_id
            or existing_request.finding_id != finding_id
            or existing_request.decision != decision
            or existing_request.reason != reason
            or existing_request.modified_finding != modified_finding
        ):
            raise ValueError("decision request idempotency conflict")
        return existing_request
    if row.status != "waiting_human":
        raise ValueError("review is not waiting for a human decision")
    finding = _finding_for_decision(session, principal, row, finding_id)
    if finding_id == RESULT_PENDING_ID:
        if decision != "confirm_no_findings" or finding is not None:
            raise ValueError("no-findings confirmation is not applicable")
        merged = session.scalar(
            select(ReviewArtifact).where(
                ReviewArtifact.tenant_id == principal.tenant_id,
                ReviewArtifact.review_task_id == review_task_id,
                ReviewArtifact.run_id == run_id,
                ReviewArtifact.kind == "merged_findings",
            )
        )
        if merged is None or merged.content.get("findings"):
            raise ValueError("no-findings confirmation requires an empty review")
    elif finding is None or decision == "confirm_no_findings":
        raise LookupError("finding is not pending review")
    if decision not in {"accept", "modify", "reject", "confirm_no_findings"}:
        raise ValueError("unsupported human decision")
    if (decision == "modify") != (modified_finding is not None):
        raise ValueError("modified finding is required only for modify decisions")
    if decision == "modify" and not modified_finding:
        raise ValueError("modify decisions require at least one allowed field")
    if decision == "modify":
        assert finding is not None and modified_finding is not None
        allowed = {"title", "description", "severity", "recommendation", "reasoning_summary"}
        if set(modified_finding) - allowed:
            raise ValueError("human edits cannot replace evidence, identity or provenance")
        if set(modified_finding) & {"severity"} and modified_finding["severity"] not in {
            "low",
            "medium",
            "high",
            "critical",
        }:
            raise ValueError("invalid modified severity")
        for key, value in modified_finding.items():
            if not isinstance(value, str):
                raise ValueError("human edits must be bounded text values")
            limit = 300 if key == "title" else 4000
            if not value.strip() or len(value) > limit:
                raise ValueError("human edit is empty or exceeds its field limit")
    if not request_id or len(request_id) > 64 or not reason.strip() or len(reason) > 2000:
        raise ValueError("decision request and reason are required")
    prior = session.scalar(
        select(ReviewDecision).where(
            ReviewDecision.tenant_id == principal.tenant_id,
            ReviewDecision.review_task_id == review_task_id,
            ReviewDecision.run_id == run_id,
            ReviewDecision.finding_id == finding_id,
        )
    )
    if prior is not None:
        if (
            prior.decision == decision
            and prior.reason == reason
            and prior.modified_finding == modified_finding
            and prior.reviewer_id == principal.user_id
        ):
            return prior
        raise ValueError("finding already has a conflicting immutable decision") from None
    decided_at = datetime.now(UTC)
    before_state = finding or {"finding_id": RESULT_PENDING_ID, "review_status": "pending"}
    decision_row = ReviewDecision(
        tenant_id=principal.tenant_id,
        decision_id=str(uuid4()),
        review_task_id=review_task_id,
        run_id=run_id,
        finding_id=finding_id,
        decision=decision,
        before_state=before_state,
        after_state=_decision_projection(
            before_state, decision, modified_finding, principal, reason, decided_at
        ),
        modified_finding=modified_finding,
        snapshot_hash=row.snapshot_hash,
        reviewer_id=principal.user_id,
        request_id=request_id,
        request_trace_id=request_trace_id,
        reason=reason.strip(),
        decided_at=decided_at,
    )
    session.add(decision_row)
    audit(session, principal.tenant_id, principal.user_id, "review.decision", finding_id)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        authorized_run(session, principal, review_task_id, run_id)
        replay = session.scalar(
            select(ReviewDecision).where(
                ReviewDecision.tenant_id == principal.tenant_id,
                ReviewDecision.reviewer_id == principal.user_id,
                ReviewDecision.request_id == request_id,
            )
        )
        if replay is not None and (
            replay.review_task_id == review_task_id
            and replay.run_id == run_id
            and replay.finding_id == finding_id
            and replay.decision == decision
            and replay.reason == reason.strip()
            and replay.modified_finding == modified_finding
        ):
            return replay
        raise ValueError("finding already has a conflicting immutable decision") from None
    return decision_row


def _decision_projection(
    finding: dict[str, Any],
    decision: str,
    modified_finding: dict[str, Any] | None,
    principal: Principal,
    reason: str,
    decided_at: datetime,
) -> dict[str, Any]:
    projected = json.loads(canonical_json(finding))
    if decision == "confirm_no_findings":
        projected["review_status"] = "confirmed_no_findings"
        projected["human_review"] = {
            "reviewer_id": principal.user_id,
            "decided_at": isoformat_utc(decided_at),
            "reason": reason.strip(),
        }
        return cast(dict[str, Any], projected)
    if decision == "modify":
        projected.update(modified_finding or {})
    projected["review_status"] = {
        "accept": "accepted",
        "modify": "modified",
        "reject": "rejected",
    }[decision]
    projected["human_review"] = {
        "reviewer_id": principal.user_id,
        "decided_at": isoformat_utc(decided_at),
        "reason": reason.strip(),
    }
    return cast(dict[str, Any], projected)


def approved_findings(
    session: Session,
    principal: Principal,
    row: ReviewEngineRun,
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected = [item["finding_id"] for item in findings] or [RESULT_PENDING_ID]
    decisions = list(
        session.scalars(
            select(ReviewDecision).where(
                ReviewDecision.tenant_id == principal.tenant_id,
                ReviewDecision.review_task_id == row.review_task_id,
                ReviewDecision.run_id == row.run_id,
                ReviewDecision.snapshot_hash == row.snapshot_hash,
            )
        )
    )
    by_finding = {item.finding_id: item for item in decisions}
    if set(by_finding) != set(expected):
        raise PermissionError("every pending finding requires a persisted reviewer decision")
    if not findings and by_finding[RESULT_PENDING_ID].decision != "confirm_no_findings":
        raise PermissionError("an empty result requires explicit human confirmation")
    risk_schema = json.loads(
        (ROOT / "contracts/schemas/risk.schema.json").read_text(encoding="utf-8")
    )
    evidence_schema = json.loads(
        (ROOT / "contracts/schemas/evidence.schema.json").read_text(encoding="utf-8")
    )
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
    validator = Draft202012Validator(risk_schema, registry=registry)
    result = []
    for original in findings:
        decision = by_finding[original["finding_id"]]
        if decision.reviewer_id == "" or decision.decision == "confirm_no_findings":
            raise ValueError("invalid finding review decision")
        item = (
            json.loads(canonical_json(decision.after_state))
            if decision.after_state is not None
            else json.loads(canonical_json(original))
        )
        if decision.after_state is None:
            if decision.decision == "modify":
                item.update(decision.modified_finding or {})
            item["review_status"] = {
                "accept": "accepted",
                "modify": "modified",
                "reject": "rejected",
            }[decision.decision]
            item["human_review"] = {
                "reviewer_id": decision.reviewer_id,
                "decided_at": isoformat_utc(decision.decided_at),
                "reason": decision.reason,
            }
        if item.get("evidence_status") != original.get("evidence_status"):
            raise ValueError("human review cannot change the independently checked evidence status")
        validator.validate(item)
        result.append(item)
    return result


def publish_result(
    session: Session,
    principal: Principal,
    *,
    row: ReviewEngineRun,
    findings: list[dict[str, Any]],
) -> ReviewResult:
    if principal.role is not Role.REVIEWER:
        raise PermissionError("result publication requires reviewer role")
    locked = session.scalar(
        select(ReviewEngineRun)
        .where(
            ReviewEngineRun.tenant_id == principal.tenant_id,
            ReviewEngineRun.review_task_id == row.review_task_id,
            ReviewEngineRun.run_id == row.run_id,
        )
        .with_for_update()
    )
    if locked is None or locked.snapshot_hash != content_hash(locked.snapshot):
        raise ValueError("review run snapshot is unavailable or changed")
    if locked.status not in {"running", "waiting_human", "result_published"}:
        raise ValueError("review run is not approved for publication")
    approved = approved_findings(session, principal, locked, findings)
    payload = {
        "schema_version": "v1alpha1",
        "tenant_id": principal.tenant_id,
        "project_id": locked.project_id,
        "review_task_id": locked.review_task_id,
        "run_id": locked.run_id,
        "snapshot_hash": locked.snapshot_hash,
        "findings": approved,
        "report_status": "not_generated",
    }
    digest = content_hash(payload)
    idempotency_key = hashlib.sha256(
        f"{principal.tenant_id}\0{locked.review_task_id}\0{locked.run_id}\0{locked.snapshot_hash}".encode()
    ).hexdigest()
    existing = session.scalar(
        select(ReviewResult).where(
            ReviewResult.tenant_id == principal.tenant_id,
            ReviewResult.review_task_id == locked.review_task_id,
            ReviewResult.run_id == locked.run_id,
            ReviewResult.snapshot_hash == locked.snapshot_hash,
        )
    )
    if existing is not None:
        if existing.content_hash != digest or content_hash(existing.content) != digest:
            raise ValueError("published result payload conflicts with its immutable identity")
        locked.status = "result_published"
        locked.updated_at = datetime.now(UTC)
        session.commit()
        return existing
    record = ReviewResult(
        tenant_id=principal.tenant_id,
        result_id=str(uuid4()),
        review_task_id=locked.review_task_id,
        run_id=locked.run_id,
        snapshot_hash=locked.snapshot_hash,
        idempotency_key=idempotency_key,
        content=payload,
        content_hash=digest,
        reviewer_id=principal.user_id,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    locked.status = "result_published"
    locked.updated_at = datetime.now(UTC)
    # ReviewTask remains running until a report/finalization task exists.
    audit(
        session, principal.tenant_id, principal.user_id, "review.result_published", record.result_id
    )
    session.commit()
    return record
