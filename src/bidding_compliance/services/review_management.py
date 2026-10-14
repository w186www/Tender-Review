"""Authorized query and publication operations for the human review boundary."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.persistence.models import (
    ReviewArtifact,
    ReviewDecision,
    ReviewEngineRun,
    ReviewResult,
)
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.projects import find_project
from bidding_compliance.services.review_persistence import (
    authorized_run,
    content_hash,
    publish_result,
)


def _require_reader(session: Session, principal: Principal) -> None:
    require_identity(session, principal)
    if principal.role not in {Role.REVIEWER, Role.AUDITOR}:
        audit(session, principal.tenant_id, principal.user_id, "review.read_denied")
        session.commit()
        raise PermissionError("review results are not authorized")


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
                "created_at": row.created_at.isoformat(),
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
                "decided_at": decision.decided_at.isoformat(),
                "reason": decision.reason,
            }
            if decision.modified_finding:
                finding.update(decision.modified_finding)
    pending = [item["finding_id"] for item in findings if item["finding_id"] not in by_id]
    if not findings and not any(item.finding_id == "__review_complete__" for item in decisions):
        pending = ["__review_complete__"]
    return {
        "review_task_id": review_task_id,
        "run_id": run_id,
        "snapshot_hash": row.snapshot_hash,
        "status": row.status,
        "findings": findings,
        "pending_finding_ids": pending,
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
