"""Inspect disposable PostgreSQL outcomes created through the real browser/API path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.persistence.models import (
    AuditEvent,
    AuthSession,
    Document,
    Project,
    ReviewConfigurationEvent,
    ReviewConfigurationRevision,
    ReviewDecision,
    ReviewEngineRun,
    ReviewReport,
    ReviewReportContent,
    ReviewResult,
    ReviewTask,
    User,
)
from bidding_compliance.services.review_persistence import content_hash


def _engine():
    value = os.environ.get("E2E_ADMIN_DATABASE_URL")
    if not value:
        raise RuntimeError("isolated PostgreSQL verifier URL is missing")
    return make_engine(Settings(_env_file=None, database_url=value))


def _count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(ReviewEngineRun)) or 0)


def assert_flow(args: argparse.Namespace) -> dict[str, object]:
    engine = _engine()
    try:
        with Session(engine) as session:
            project = session.get(Project, (args.tenant, args.project))
            document = session.get(Document, (args.tenant, args.document))
            run = session.get(ReviewEngineRun, (args.tenant, args.task, args.run_id))
            task = session.get(ReviewTask, (args.tenant, args.task))
            assert project is not None and project.version >= 1
            assert document is not None and document.status == "ready"
            assert document.sha256 and document.size_bytes > 0
            assert run is not None and run.status == "result_published"
            assert task is not None
            snapshot = run.snapshot
            assert run.snapshot_hash == content_hash(snapshot)
            config_id = snapshot.get("configuration_revision_id")
            config_hash = snapshot.get("configuration_snapshot_hash")
            config_snapshot = snapshot.get("configuration_snapshot")
            assert isinstance(config_id, str) and isinstance(config_hash, str)
            assert isinstance(config_snapshot, dict)
            assert config_snapshot["legal_publication_id"] == snapshot["legal_publication_id"]
            release = session.get(ReviewConfigurationRevision, (args.tenant, config_id))
            assert release is not None and release.snapshot_hash == config_hash
            assert release.snapshot == config_snapshot
            assert (
                session.scalar(
                    select(ReviewConfigurationEvent.event_id).where(
                        ReviewConfigurationEvent.tenant_id == args.tenant,
                        ReviewConfigurationEvent.revision_id == config_id,
                        ReviewConfigurationEvent.operation.in_(("publish", "rollback")),
                    )
                )
                is not None
            )
            result = session.scalar(
                select(ReviewResult).where(
                    ReviewResult.tenant_id == args.tenant,
                    ReviewResult.review_task_id == args.task,
                    ReviewResult.run_id == args.run_id,
                )
            )
            assert result is not None and result.content_hash
            decisions = list(
                session.scalars(
                    select(ReviewDecision).where(
                        ReviewDecision.tenant_id == args.tenant,
                        ReviewDecision.review_task_id == args.task,
                        ReviewDecision.run_id == args.run_id,
                    )
                )
            )
            assert decisions and all(item.reason.strip() for item in decisions)
            report_content = session.scalar(
                select(ReviewReportContent).where(
                    ReviewReportContent.tenant_id == args.tenant,
                    ReviewReportContent.result_id == result.result_id,
                )
            )
            reports = list(
                session.scalars(
                    select(ReviewReport).where(
                        ReviewReport.tenant_id == args.tenant,
                        ReviewReport.result_id == result.result_id,
                    )
                )
            )
            assert report_content is not None and report_content.content_hash
            assert {item.format for item in reports} == {"docx", "pdf"}
            for report in reports:
                assert hashlib.sha256(report.content).hexdigest() == report.content_hash
                assert report.content.startswith(b"PK" if report.format == "docx" else b"%PDF-")
                assert report.snapshot_hash == run.snapshot_hash
            actions = set(
                session.scalars(
                    select(AuditEvent.action).where(
                        AuditEvent.tenant_id == args.tenant,
                        AuditEvent.actor_id == "reviewer",
                        AuditEvent.action.in_(
                            (
                                "document.uploaded",
                                "review.decision",
                                "report.generated",
                                "report.exported",
                            )
                        ),
                    )
                )
            )
            required = {
                "document.uploaded",
                "review.decision",
                "report.generated",
                "report.exported",
            }
            assert required <= actions, (
                f"missing persisted audit actions: {sorted(required - actions)}"
            )
            return {
                "project_id": project.project_id,
                "document_id": document.document_id,
                "document_status": document.status,
                "review_task_id": run.review_task_id,
                "review_task_record_status": task.status,
                "review_run_status": run.status,
                "snapshot_hash": run.snapshot_hash,
                "configuration_revision_id": config_id,
                "configuration_snapshot_hash": config_hash,
                "review_result_id": result.result_id,
                "decision_count": len(decisions),
                "report_formats": sorted(item.format for item in reports),
                "report_ids": sorted(item.report_id for item in reports),
                "audit_actions": sorted(required),
            }
    finally:
        engine.dispose()


def assert_audit_query(args: argparse.Namespace) -> dict[str, object]:
    engine = _engine()
    try:
        with Session(engine) as session:
            row = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == args.tenant,
                    AuditEvent.action == "audit.query",
                    AuditEvent.actor_id == args.actor,
                )
            )
            assert row is not None
            return {"audit_query_event_id": row.event_id, "actor_id": row.actor_id}
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    stats = subparsers.add_parser("stats")
    stats.set_defaults(handler=lambda _: _stats())
    flow = subparsers.add_parser("assert-flow")
    flow.add_argument("--tenant", required=True)
    flow.add_argument("--project", required=True)
    flow.add_argument("--document", required=True)
    flow.add_argument("--task", required=True)
    flow.add_argument("--run-id", required=True)
    flow.set_defaults(handler=assert_flow)
    audit = subparsers.add_parser("assert-audit")
    audit.add_argument("--tenant", required=True)
    audit.add_argument("--actor", required=True)
    audit.set_defaults(handler=assert_audit_query)
    revoke = subparsers.add_parser("revoke-user")
    revoke.add_argument("--tenant", required=True)
    revoke.add_argument("--user", required=True)
    revoke.set_defaults(handler=_revoke_user)
    args = parser.parse_args()
    result = args.handler(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _stats() -> dict[str, object]:
    engine = _engine()
    try:
        with Session(engine) as session:
            return {"review_run_count": _count(session)}
    finally:
        engine.dispose()


def _revoke_user(args: argparse.Namespace) -> dict[str, object]:
    engine = _engine()
    try:
        with Session(engine) as session:
            user = session.get(User, (args.tenant, args.user))
            assert user is not None
            user.active = False
            session.execute(
                update(AuthSession)
                .where(AuthSession.tenant_id == args.tenant, AuthSession.user_id == args.user)
                .values(revoked=True)
            )
            session.commit()
            return {
                "user_id": user.user_id,
                "active": user.active,
                "revoked_at": datetime.now(UTC).isoformat(),
            }
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
