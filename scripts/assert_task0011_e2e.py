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
    ReviewArtifact,
    ReviewConfigurationEvent,
    ReviewConfigurationRevision,
    ReviewDecision,
    ReviewEngineRun,
    ReviewModelCall,
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
            assert run.action == "resume"
            assert run.execution_generation >= 2
            assert run.lease_id is None and run.lease_until is None
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
            model_calls = list(
                session.scalars(
                    select(ReviewModelCall).where(
                        ReviewModelCall.tenant_id == args.tenant,
                        ReviewModelCall.review_task_id == args.task,
                        ReviewModelCall.run_id == args.run_id,
                    )
                )
            )
            if os.environ.get("E2E_EXPECT_PROVIDER") == "bailian":
                unknown_calls = []
                successful_calls = [item for item in model_calls if item.state == "succeeded"]
                assert successful_calls and len(successful_calls) == len(model_calls)
                assert all(
                    item.response_ref is not None
                    and item.response_hash is not None
                    and item.execution_generation == 1
                    for item in successful_calls
                )
                assert run.retry_count == 0
            else:
                unknown_calls = [item for item in model_calls if item.state == "unknown"]
                successful_calls = [item for item in model_calls if item.state == "succeeded"]
                assert len(unknown_calls) == 1
                assert successful_calls
                assert all(
                    item.response_ref is not None
                    and item.response_hash is not None
                    and item.execution_generation >= 2
                    for item in successful_calls
                )
                assert all(
                    item.response_ref is None
                    and item.response_hash is None
                    and item.execution_generation == 1
                    for item in unknown_calls
                )
                assert run.retry_count == 1
            for item in successful_calls:
                artifact_id = item.response_ref.removeprefix("artifact://review/").split("/")[0]
                response_artifact = session.get(ReviewArtifact, (args.tenant, artifact_id))
                assert (
                    response_artifact is not None
                    and response_artifact.kind == "model_call_response"
                    and content_hash(response_artifact.content) == response_artifact.content_hash
                    and response_artifact.content.get("call_id") == item.call_id
                    and response_artifact.content.get("request_hash") == item.request_hash
                    and content_hash(response_artifact.content.get("response"))
                    == item.response_hash
                )
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
                "review_action": run.action,
                "execution_generation": run.execution_generation,
                "retry_count": run.retry_count,
                "lease_cleared": run.lease_id is None and run.lease_until is None,
                "model_call_count": len(model_calls),
                "model_call_states": sorted({item.state for item in model_calls}),
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


def assert_unknown_after_worker_restart(args: argparse.Namespace) -> dict[str, object]:
    engine = _engine()
    try:
        with Session(engine) as session:
            run = session.get(ReviewEngineRun, (args.tenant, args.task, args.run_id))
            task = session.get(ReviewTask, (args.tenant, args.task))
            calls = list(
                session.scalars(
                    select(ReviewModelCall).where(
                        ReviewModelCall.tenant_id == args.tenant,
                        ReviewModelCall.review_task_id == args.task,
                        ReviewModelCall.run_id == args.run_id,
                    )
                )
            )
            assert run is not None and task is not None
            assert run.status == task.status == "failed"
            assert run.failure_code == "model_call_outcome_unknown"
            assert run.execution_generation == 1
            assert len(calls) == 1 and calls[0].state == "unknown"
            assert calls[0].response_ref is None and calls[0].response_hash is None
            assert calls[0].execution_generation == 1
            return {
                "review_task_id": run.review_task_id,
                "run_id": run.run_id,
                "status": run.status,
                "failure_code": run.failure_code,
                "execution_generation": run.execution_generation,
                "model_call_count": len(calls),
                "model_call_state": calls[0].state,
                "response_absent": calls[0].response_ref is None
                and calls[0].response_hash is None,
            }
    finally:
        engine.dispose()


def assert_lease_takeover(args: argparse.Namespace) -> dict[str, object]:
    engine = _engine()
    try:
        with Session(engine) as session:
            run = session.get(ReviewEngineRun, (args.tenant, args.task, args.run_id))
            task = session.get(ReviewTask, (args.tenant, args.task))
            calls = list(
                session.scalars(
                    select(ReviewModelCall).where(
                        ReviewModelCall.tenant_id == args.tenant,
                        ReviewModelCall.review_task_id == args.task,
                        ReviewModelCall.run_id == args.run_id,
                    )
                )
            )
            assert run is not None and task is not None
            assert run.status == task.status == "waiting_human"
            assert run.execution_generation == 2
            assert run.lease_id is None and run.lease_until is None
            assert calls and all(
                item.state == "succeeded"
                and item.execution_generation == 2
                and item.response_ref is not None
                and item.response_hash is not None
                for item in calls
            )
            return {
                "review_task_id": run.review_task_id,
                "run_id": run.run_id,
                "status": run.status,
                "execution_generation": run.execution_generation,
                "lease_cleared": run.lease_id is None and run.lease_until is None,
                "model_call_count": len(calls),
                "model_call_states": sorted({item.state for item in calls}),
            }
    finally:
        engine.dispose()


def assert_cancelled(args: argparse.Namespace) -> dict[str, object]:
    engine = _engine()
    try:
        with Session(engine) as session:
            run = session.get(ReviewEngineRun, (args.tenant, args.task, args.run_id))
            task = session.get(ReviewTask, (args.tenant, args.task))
            calls = list(
                session.scalars(
                    select(ReviewModelCall).where(
                        ReviewModelCall.tenant_id == args.tenant,
                        ReviewModelCall.review_task_id == args.task,
                        ReviewModelCall.run_id == args.run_id,
                    )
                )
            )
            cancel_events = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == args.tenant,
                        AuditEvent.resource_id == args.task,
                        AuditEvent.action == "review.cancel",
                    )
                )
            )
            assert run is not None and task is not None
            assert run.status == task.status == "cancelled"
            assert run.execution_generation == 1
            assert run.lease_id is None and run.lease_until is None
            assert not calls
            assert len(cancel_events) == 1
            return {
                "review_task_id": run.review_task_id,
                "run_id": run.run_id,
                "status": run.status,
                "execution_generation": run.execution_generation,
                "lease_cleared": run.lease_id is None and run.lease_until is None,
                "model_call_count": len(calls),
                "cancel_audit_count": len(cancel_events),
            }
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
    unknown = subparsers.add_parser("assert-unknown")
    unknown.add_argument("--tenant", required=True)
    unknown.add_argument("--task", required=True)
    unknown.add_argument("--run-id", required=True)
    unknown.set_defaults(handler=assert_unknown_after_worker_restart)
    takeover = subparsers.add_parser("assert-lease-takeover")
    takeover.add_argument("--tenant", required=True)
    takeover.add_argument("--task", required=True)
    takeover.add_argument("--run-id", required=True)
    takeover.set_defaults(handler=assert_lease_takeover)
    cancelled = subparsers.add_parser("assert-cancelled")
    cancelled.add_argument("--tenant", required=True)
    cancelled.add_argument("--task", required=True)
    cancelled.add_argument("--run-id", required=True)
    cancelled.set_defaults(handler=assert_cancelled)
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
