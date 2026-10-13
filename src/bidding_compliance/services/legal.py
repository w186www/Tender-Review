"""Server-side project authorization before legal retrieval or embedding execution."""

import json
from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.legal.contracts import (
    Excluded,
    RetrievalInput,
    RetrievalQuery,
    RetrievalResult,
    RunSnapshot,
)
from bidding_compliance.legal.hashing import canonical_hash
from bidding_compliance.legal.retrieval import LegalRetriever
from bidding_compliance.persistence.database import require_runtime_role, set_tenant
from bidding_compliance.persistence.models import AuthSession, LegalRetrievalRun, Tenant, User
from bidding_compliance.services.identity import audit
from bidding_compliance.services.projects import find_project


def require_identity(session: Session, principal: Principal) -> None:
    require_runtime_role(session)
    set_tenant(session, principal.tenant_id)
    tenant = session.get(Tenant, principal.tenant_id, populate_existing=True)
    user = session.get(User, (principal.tenant_id, principal.user_id), populate_existing=True)
    auth = session.get(
        AuthSession, (principal.tenant_id, principal.session_id), populate_existing=True
    )
    if (
        tenant is None or not tenant.active or user is None or not user.active
        or user.role != principal.role.value or auth is None or auth.revoked
        or auth.user_id != principal.user_id
        or auth.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
    ):
        raise PermissionError("legal retrieval identity unavailable")


def retrieve_for_project(
    session: Session, principal: Principal, project_id: str, retriever: LegalRetriever,
    *, text: str, review_date: date, include_references: bool = False, limit: int = 10,
) -> RetrievalResult:
    require_identity(session, principal)
    project = find_project(session, principal, project_id)
    session.refresh(project)
    context = json.loads(json.dumps(project.context, allow_nan=False))
    context_version = project.version
    request = RetrievalInput(
        text=text, review_date=review_date, include_references=include_references, limit=limit,
    )
    try:
        query = RetrievalQuery(
            **request.model_dump(), region=context.get("region"),
            procurement_type=context.get("procurement_type"),
            project_type=context.get("project_type"),
        )
    except ValidationError as exc:
        query = None
        error: Literal["REGION_UNMAPPED", "CONTEXT_INVALID"] = "REGION_UNMAPPED" if any(
            x["loc"] == ("region",) for x in exc.errors()
        ) else "CONTEXT_INVALID"
        result = RetrievalResult(
            snapshot_hash=retriever.snapshot_hash, query=None, hits=(),
            status="context_incomplete", context_error=error,
            excluded=(Excluded(reasons=("context_incomplete",)),),
        )
    else:
        assert query is not None
        result = retriever.search(query)
    run_id = str(uuid4())
    now = datetime.now(UTC)
    frozen = {
        "schema_version": "v1alpha2", "run_id": run_id, "tenant_id": principal.tenant_id,
        "project_id": project_id, "actor_id": principal.user_id,
        "context_version": context_version, "context": context,
        "context_hash": canonical_hash(context), "request": request.model_dump(mode="json"),
        "query": query.model_dump(mode="json") if query else None,
        "review_date_source": "explicit_actor_input", "created_at": now.isoformat(),
        "snapshot_hash": result.snapshot_hash, "retrieval_version": result.retrieval_version,
        "normalization_version": result.normalization_version,
    }
    snapshot = RunSnapshot(
        run_id=run_id, tenant_id=principal.tenant_id, project_id=project_id,
        actor_id=principal.user_id, context_version=context_version,
        context_hash=frozen["context_hash"], request_hash=canonical_hash(frozen),
        review_date=request.review_date, created_at=now,
    )
    result = RetrievalResult(**{**result.model_dump(), "run_snapshot": snapshot})
    payload = result.model_dump(mode="json")
    record = LegalRetrievalRun(
        tenant_id=principal.tenant_id, run_id=run_id, project_id=project_id,
        actor_id=principal.user_id, context_version=context_version,
        request_snapshot=frozen, request_hash=snapshot.request_hash,
        result=payload, result_hash=canonical_hash(payload), created_at=now,
    )
    try:
        session.add(record)
        audit(session, principal.tenant_id, principal.user_id, "legal.retrieval", run_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return result


def validate_run(record: LegalRetrievalRun) -> RetrievalResult:
    frozen = record.request_snapshot
    if (
        canonical_hash(frozen) != record.request_hash
        or canonical_hash(record.result) != record.result_hash
        or canonical_hash(frozen["context"]) != frozen["context_hash"]
    ):
        raise ValueError("retrieval run hash mismatch")
    result = RetrievalResult.model_validate(record.result)
    snapshot = result.run_snapshot
    if snapshot is None:
        raise ValueError("project retrieval requires a run snapshot")
    expected = {
        "run_id": record.run_id, "tenant_id": record.tenant_id, "project_id": record.project_id,
        "actor_id": record.actor_id, "context_version": record.context_version,
        "context_hash": frozen["context_hash"], "request_hash": record.request_hash,
        "review_date": frozen["request"]["review_date"],
        "review_date_source": frozen["review_date_source"], "created_at": frozen["created_at"],
    }
    if snapshot != RunSnapshot.model_validate(expected):
        raise ValueError("retrieval run provenance mismatch")
    query = result.query.model_dump(mode="json") if result.query else None
    if query != frozen["query"] or any(
        frozen[key] != expected[key] for key in (
            "run_id", "tenant_id", "project_id", "actor_id", "context_version",
        )
    ) or any(frozen[key] != getattr(result, key) for key in (
        "snapshot_hash", "retrieval_version", "normalization_version",
    )):
        raise ValueError("retrieval run input/result mismatch")
    if result.query:
        reconstructed = RetrievalQuery(
            **frozen["request"], region=frozen["context"].get("region"),
            procurement_type=frozen["context"].get("procurement_type"),
            project_type=frozen["context"].get("project_type"),
        )
        if reconstructed != result.query:
            raise ValueError("retrieval query/context mismatch")
    return result


def read_run(session: Session, principal: Principal, run_id: str) -> RetrievalResult:
    require_identity(session, principal)
    record = session.get(
        LegalRetrievalRun, (principal.tenant_id, run_id), populate_existing=True,
    )
    if record is None:
        raise LookupError("resource unavailable")
    find_project(session, principal, record.project_id)
    return validate_run(record)
