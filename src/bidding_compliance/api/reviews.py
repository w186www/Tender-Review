"""Human review, immutable result publication and report export endpoints."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError

from bidding_compliance.core.dates import isoformat_utc
from bidding_compliance.core.tracing import get_request_id
from bidding_compliance.services import reports, review_management, review_persistence
from bidding_compliance.services.review_engine import ReviewRequest

from .projects import DB, User
from .review_schemas import (
    CitationLocation,
    CreateReviewRequest,
    DecisionRequest,
    DecisionResponse,
    PendingReviewItem,
    PendingReviewList,
    ReportList,
    ReportMetadata,
    ReviewCitations,
    ReviewFindings,
    ReviewHistory,
    ReviewTaskList,
    ReviewTaskResponse,
)
from .schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1",
    responses={
        status: {"model": ErrorResponse, "description": "统一安全错误"}
        for status in (400, 401, 403, 404, 409, 422, 500, 503)
    },
)


def _task_response(data: dict[str, Any]) -> ReviewTaskResponse:
    return ReviewTaskResponse.model_validate(
        {key: data[key] for key in ReviewTaskResponse.model_fields}
    )


@router.get(
    "/projects/{projectId}/reviews",
    response_model=ReviewTaskList,
    operation_id="listProjectReviews",
)
def project_reviews(
    projectId: str,
    principal: User,
    session: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ReviewTaskList:
    try:
        items, total = review_management.list_project_reviews(
            session, principal, projectId, offset=offset, limit=limit
        )
        return ReviewTaskList(
            items=[_task_response(item) for item in items],
            offset=offset,
            limit=limit,
            total=total,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/projects/{projectId}/reviews",
    status_code=202,
    response_model=ReviewTaskResponse,
    operation_id="createReview",
)
async def create_review(
    projectId: str,
    body: CreateReviewRequest,
    request: Request,
    principal: User,
    session: DB,
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ReviewTaskResponse:
    engine = getattr(request.app.state, "review_engine", None)
    if engine is None:
        raise HTTPException(503, detail="authorized review executor is unavailable")
    task_id = str(uuid5(NAMESPACE_URL, f"task0011:{principal.tenant_id}:{key}"))
    try:
        existing = review_management.get_run_by_identity(session, principal, task_id)
        if existing is not None:
            if (
                existing["project_id"] != projectId
                or sorted(existing["document_ids"]) != sorted(body.document_ids)
            ):
                raise FileExistsError("idempotency conflict")
            return _task_response(existing)
        doc_requests = review_management.document_requests(
            session, principal, projectId, body.document_ids
        )
        review = ReviewRequest(
            review_task_id=task_id,
            project_id=projectId,
            run_id=str(uuid5(NAMESPACE_URL, f"{task_id}:run")),
            document_requests=doc_requests,
            review_date=datetime.now(UTC).date(),
            prompt_version=getattr(request.app.state, "review_prompt_version", "task0011-ui-v1"),
            model_profile=engine.model_policy.profile,
        )
        engine.create_run(principal, review)
        session.expire_all()
        return _task_response(review_management.get_review_status(session, principal, task_id))
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.get(
    "/reviews/{reviewTaskId}",
    response_model=ReviewTaskResponse,
    operation_id="getReview",
)
def get_review(
    reviewTaskId: str, principal: User, session: DB
) -> ReviewTaskResponse:
    try:
        return _task_response(review_management.get_review_status(session, principal, reviewTaskId))
    except Exception as exc:
        raise _translate(exc) from exc


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        if "role" in str(exc) or "authorized" in str(exc):
            return HTTPException(403)
        return HTTPException(409)
    if isinstance(exc, LookupError):
        return HTTPException(404)
    if isinstance(exc, (FileExistsError, IntegrityError)):
        return HTTPException(409)
    if isinstance(exc, ValueError):
        conflict_terms = ("conflict", "eligible", "waiting", "status", "approved", "published")
        return HTTPException(409 if any(term in str(exc) for term in conflict_terms) else 422)
    return HTTPException(500)


def _decision_response(row: Any) -> DecisionResponse:
    return DecisionResponse(
        decision_id=row.decision_id,
        review_task_id=row.review_task_id,
        run_id=row.run_id,
        finding_id=row.finding_id,
        decision=row.decision,
        before_state=row.before_state or {},
        after_state=row.after_state or {},
        reason=row.reason,
        reviewer_id=row.reviewer_id,
        request_id=row.request_id,
        request_trace_id=row.request_trace_id,
        decided_at=isoformat_utc(row.decided_at),
    )


@router.get(
    "/review-tasks/pending",
    response_model=PendingReviewList,
    operation_id="listPendingReviews",
)
def pending_reviews(
    principal: User,
    session: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PendingReviewList:
    try:
        items = review_management.list_waiting(session, principal, offset=offset, limit=limit)
        return PendingReviewList(
            items=[PendingReviewItem.model_validate(item) for item in items],
            offset=offset,
            limit=limit,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get(
    "/review-tasks/{reviewTaskId}/runs/{runId}/findings",
    response_model=ReviewFindings,
    operation_id="getReviewFindings",
)
def findings(reviewTaskId: str, runId: str, principal: User, session: DB) -> ReviewFindings:
    try:
        return ReviewFindings.model_validate(
            review_management.get_findings(session, principal, reviewTaskId, runId)
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get(
    "/review-tasks/{reviewTaskId}/runs/{runId}/findings/{findingId}",
    operation_id="getReviewFinding",
)
def finding(
    reviewTaskId: str,
    runId: str,
    findingId: str,
    principal: User,
    session: DB,
) -> dict[str, Any]:
    try:
        data = review_management.get_findings(session, principal, reviewTaskId, runId)
        item = next((entry for entry in data["findings"] if entry["finding_id"] == findingId), None)
        if item is None:
            raise LookupError("finding unavailable")
        return {
            "review_task_id": reviewTaskId,
            "run_id": runId,
            "snapshot_hash": data["snapshot_hash"],
            "finding": item,
        }
    except Exception as exc:
        raise _translate(exc) from exc


@router.get(
    "/review-tasks/{reviewTaskId}/runs/{runId}/findings/{findingId}/citations",
    response_model=ReviewCitations,
    operation_id="resolveReviewFindingCitations",
)
def finding_citations(
    reviewTaskId: str,
    runId: str,
    findingId: str,
    principal: User,
    session: DB,
) -> ReviewCitations:
    try:
        locations = reports.resolve_review_finding_citations(
            session,
            principal,
            review_task_id=reviewTaskId,
            run_id=runId,
            finding_id=findingId,
        )
        return ReviewCitations(
            items=[CitationLocation.model_validate(item) for item in locations]
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/review-tasks/{reviewTaskId}/runs/{runId}/findings/{findingId}/decisions",
    response_model=DecisionResponse,
    operation_id="submitReviewDecision",
)
def decide(
    reviewTaskId: str,
    runId: str,
    findingId: str,
    body: DecisionRequest,
    principal: User,
    session: DB,
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> DecisionResponse:
    try:
        row = review_persistence.submit_decision(
            session,
            principal,
            review_task_id=reviewTaskId,
            run_id=runId,
            finding_id=findingId,
            decision=body.decision,
            request_id=hashlib.sha256(key.encode()).hexdigest(),
            reason=body.reason,
            modified_finding=body.modified_finding,
            expected_snapshot_hash=body.expected_snapshot_hash,
            request_trace_id=get_request_id(),
        )
        return _decision_response(row)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get(
    "/review-tasks/{reviewTaskId}/runs/{runId}/history",
    response_model=ReviewHistory,
    operation_id="getReviewHistory",
)
def history(reviewTaskId: str, runId: str, principal: User, session: DB) -> ReviewHistory:
    try:
        rows = review_management.get_history(session, principal, reviewTaskId, runId)
        return ReviewHistory(
            review_task_id=reviewTaskId,
            run_id=runId,
            decisions=[_decision_response(row) for row in rows],
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/review-tasks/{reviewTaskId}/runs/{runId}/publish",
    operation_id="publishReviewResult",
)
def publish(reviewTaskId: str, runId: str, principal: User, session: DB) -> dict[str, str]:
    try:
        result = review_management.publish_review(session, principal, reviewTaskId, runId)
        return {"result_id": result.result_id, "content_hash": result.content_hash}
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/review-tasks/{reviewTaskId}/runs/{runId}/resume",
    response_model=ReviewTaskResponse,
    operation_id="resumeReviewRun",
)
async def resume(
    reviewTaskId: str,
    runId: str,
    request: Request,
    principal: User,
    session: DB,
) -> ReviewTaskResponse:
    try:
        review_management.authorize_review_control(
            session, principal, reviewTaskId, runId, "resume"
        )
        engine = getattr(request.app.state, "review_engine", None)
        if engine is None:
            raise HTTPException(503, detail="review execution worker is unavailable")
        engine.schedule_resume(principal, reviewTaskId, runId)
        session.expire_all()
        return _task_response(
            review_management.get_review_status(session, principal, reviewTaskId)
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/review-tasks/{reviewTaskId}/runs/{runId}/retry",
    response_model=ReviewTaskResponse,
    operation_id="retryReviewRun",
)
async def retry(
    reviewTaskId: str,
    runId: str,
    request: Request,
    principal: User,
    session: DB,
) -> ReviewTaskResponse:
    try:
        review_management.authorize_review_control(
            session, principal, reviewTaskId, runId, "retry"
        )
        engine = getattr(request.app.state, "review_engine", None)
        if engine is None:
            raise HTTPException(503, detail="review execution worker is unavailable")
        engine.schedule_retry(principal, reviewTaskId, runId)
        session.expire_all()
        return _task_response(
            review_management.get_review_status(session, principal, reviewTaskId)
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/review-tasks/{reviewTaskId}/runs/{runId}/cancel",
    response_model=ReviewTaskResponse,
    operation_id="cancelReviewRun",
)
async def cancel(
    reviewTaskId: str,
    runId: str,
    request: Request,
    principal: User,
    session: DB,
) -> ReviewTaskResponse:
    try:
        review_management.authorize_review_control(
            session, principal, reviewTaskId, runId, "cancel"
        )
        engine = getattr(request.app.state, "review_engine", None)
        if engine is None:
            raise HTTPException(503, detail="review execution worker is unavailable")
        engine.cancel(principal, reviewTaskId, runId)
        session.expire_all()
        return _task_response(
            review_management.get_review_status(session, principal, reviewTaskId)
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/review-results/{resultId}/reports/{outputFormat}",
    response_model=ReportMetadata,
    operation_id="createReviewReport",
)
def create_report(
    resultId: str,
    outputFormat: str,
    principal: User,
    session: DB,
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ReportMetadata:
    try:
        row = reports.create_report(
            session,
            principal,
            result_id=resultId,
            output_format=outputFormat,
            idempotency_key=key,
        )
        return ReportMetadata(
            report_id=row.report_id,
            report_content_id=row.report_content_id,
            result_id=row.result_id,
            format=cast(Literal["docx", "pdf"], row.format),
            template_version=row.template_version,
            snapshot_hash=row.snapshot_hash,
            content_hash=row.content_hash,
            created_at=isoformat_utc(row.created_at),
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/reports/{reportId}/content", operation_id="exportReviewReport")
def download_report(reportId: str, principal: User, session: DB) -> Response:
    try:
        row = reports.export_report(session, principal, reportId)
    except Exception as exc:
        raise _translate(exc) from exc
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if row.format == "docx"
        else "application/pdf"
    )
    return Response(
        content=row.content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="review-{row.report_id}.{row.format}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "ETag": f'"{row.content_hash}"',
        },
    )


@router.get(
    "/review-results/{resultId}/reports",
    response_model=ReportList,
    operation_id="listReviewReports",
)
def list_reports(resultId: str, principal: User, session: DB) -> ReportList:
    try:
        rows = reports.list_reports(session, principal, resultId)
        return ReportList(
            items=[
                ReportMetadata(
                    report_id=row.report_id,
                    report_content_id=row.report_content_id,
                    result_id=row.result_id,
                    format=cast(Literal["docx", "pdf"], row.format),
                    template_version=row.template_version,
                    snapshot_hash=row.snapshot_hash,
                    content_hash=row.content_hash,
                    created_at=isoformat_utc(row.created_at),
                )
                for row in rows
            ]
        )
    except Exception as exc:
        raise _translate(exc) from exc
