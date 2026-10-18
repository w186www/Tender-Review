"""File APIs share the authenticated tenant principal; all parsing runs in a worker."""

import logging
from typing import Annotated, cast

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from bidding_compliance.core.config import Settings
from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.ports import IngestionError
from bidding_compliance.ingestion.schemas import (
    ContextConfirmation,
    DocumentContext,
    DocumentList,
    DocumentResponse,
    QualityCorrection,
    SectionsResponse,
)
from bidding_compliance.ingestion.storage import make_store
from bidding_compliance.services import documents, execution_authorization, reports
from bidding_compliance.services.identity import audit

from .projects import DB, User
from .schemas import (
    ErrorResponse,
    ExternalAuthorizationRecord,
    ExternalAuthorizationRequest,
    ExternalAuthorizationRevocationRequest,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{projectId}/documents",
    responses={
        status: {"model": ErrorResponse, "description": "统一安全错误"}
        for status in (400, 401, 403, 404, 409, 413, 415, 422, 500)
    },
)


@router.get("", response_model=DocumentList, operation_id="listProjectDocuments")
def list_project_documents(
    projectId: str,
    principal: User,
    session: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DocumentList:
    try:
        items, total = documents.list_documents(
            session, principal, projectId, offset=offset, limit=limit
        )
        return DocumentList(items=items, offset=offset, limit=limit, total=total)
    except (PermissionError, LookupError) as exc:
        raise translate(exc) from exc


def translate(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(403)
    if isinstance(error, LookupError):
        return HTTPException(404)
    if isinstance(error, FileExistsError):
        return HTTPException(409)
    if isinstance(error, IngestionError):
        return HTTPException(
            413 if error.code == "SIZE_LIMIT" else 415 if error.code == "TYPE_MISMATCH" else 500
        )
    if isinstance(error, ValueError):
        return HTTPException(422)
    return HTTPException(500)


@router.post("", status_code=202, response_model=DocumentResponse, operation_id="uploadDocument")
async def upload(
    projectId: str,
    request: Request,
    principal: User,
    session: DB,
    file: Annotated[UploadFile, File()],
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> DocumentResponse:
    policy = load_policy()
    try:
        form = await request.form()
        if len(form.multi_items()) != 1:
            raise HTTPException(422)
        payload = await file.read(policy.max_upload_bytes + 1)
        return await run_in_threadpool(
            documents.upload,
            session,
            principal,
            projectId,
            file.filename or "",
            file.content_type or "",
            payload,
            key,
            make_store(cast(Settings, request.app.state.settings)),
            policy,
        )
    except (PermissionError, LookupError, FileExistsError, ValueError, IngestionError) as exc:
        raise translate(exc) from exc
    finally:
        await file.close()


@router.get("/{documentId}", response_model=DocumentResponse, operation_id="getDocument")
def get_document(projectId: str, documentId: str, principal: User, session: DB) -> DocumentResponse:
    try:
        return documents.response(
            documents.find_document(session, principal, projectId, documentId)
        )
    except LookupError as exc:
        raise translate(exc) from exc


@router.get(
    "/{documentId}/sections", response_model=SectionsResponse, operation_id="getDocumentSections"
)
def get_sections(projectId: str, documentId: str, principal: User, session: DB) -> SectionsResponse:
    try:
        return documents.sections(session, principal, projectId, documentId)
    except (LookupError, FileExistsError) as exc:
        raise translate(exc) from exc


@router.get(
    "/{documentId}/context", response_model=DocumentContext, operation_id="getDocumentContext"
)
def get_context(projectId: str, documentId: str, principal: User, session: DB) -> DocumentContext:
    try:
        return documents.context(session, principal, projectId, documentId)
    except (LookupError, FileExistsError) as exc:
        raise translate(exc) from exc


@router.post(
    "/{documentId}/context", response_model=DocumentResponse, operation_id="confirmDocumentContext"
)
def confirm_context(
    projectId: str, documentId: str, body: ContextConfirmation, principal: User, session: DB
) -> DocumentResponse:
    try:
        return documents.confirm_context(session, principal, projectId, documentId, body)
    except (PermissionError, LookupError, FileExistsError) as exc:
        raise translate(exc) from exc


@router.post(
    "/{documentId}/corrections", response_model=DocumentResponse, operation_id="correctDocumentText"
)
def corrections(
    projectId: str, documentId: str, body: QualityCorrection, principal: User, session: DB
) -> DocumentResponse:
    try:
        return documents.correct_text(
            session, principal, projectId, documentId, body, load_policy()
        )
    except (PermissionError, LookupError, FileExistsError, ValueError, IngestionError) as exc:
        raise translate(exc) from exc


@router.post(
    "/{documentId}/external-authorization",
    status_code=201,
    response_model=ExternalAuthorizationRecord,
    response_model_exclude_none=True,
    operation_id="authorizeDocumentExternalProcessing",
)
def authorize_external_processing(
    projectId: str,
    documentId: str,
    body: ExternalAuthorizationRequest,
    request: Request,
    principal: User,
    session: DB,
) -> ExternalAuthorizationRecord:
    """Record one reviewer's explicit confirmation that a single uploaded file may be sent.

    Product mode writes the version-bound authorization and its audit event in one
    PostgreSQL transaction; the running egress gate re-reads it before every outbound
    request. The legacy local validation assembly keeps its append-only registry, but every
    optional product field is rejected there so a caller cannot mistake a registry row for
    a policy-bound production authorization. The endpoint never accepts a file hash or
    content from the caller: the server resolves the hash and parse version for *this*
    authenticated document.
    """
    product_mode = getattr(request.app.state, "external_authorization_mode", None) == "postgres"
    registry = getattr(request.app.state, "external_authorization_registry", None)
    if not product_mode and registry is None:
        # Offline deployments have no external-processing authorization: fail closed
        # instead of pretending the confirmation was recorded somewhere.
        raise HTTPException(503, detail="external processing authorization is unavailable")
    if product_mode:
        purpose = body.purpose or getattr(
            request.app.state, "external_authorization_purpose", None
        )
        provider = body.provider or getattr(
            request.app.state, "external_authorization_provider", None
        )
        if purpose is None or provider is None:
            raise HTTPException(503, detail="external authorization policy is unavailable")
        try:
            row = execution_authorization.approve_document(
                session,
                principal,
                projectId,
                documentId,
                reason=body.reason,
                purpose=purpose,
                provider=provider,
                expires_at=body.expires_at,
            )
        except (PermissionError, LookupError, FileExistsError, ValueError) as exc:
            raise translate(exc) from exc
        return ExternalAuthorizationRecord.model_validate(
            execution_authorization.authorization_response(row)
        )
    if body.purpose is not None or body.provider is not None or body.expires_at is not None:
        raise HTTPException(
            422,
            detail="purpose, provider and expiry require the PostgreSQL product authorization",
        )
    assert registry is not None
    try:
        documents.require_reviewer(session, principal)
        document = documents.find_document(session, principal, projectId, documentId)
        record = registry.approve(
            sha256=document.sha256,
            document_id=document.document_id,
            reason=body.reason,
            approved_by=principal.user_id,
        )
        # The append is not transactional. If the audit commit fails, immediately append a
        # revoke so the registry does not keep an effective approval without an audit row.
        try:
            audit(
                session,
                principal.tenant_id,
                principal.user_id,
                "document.external_authorization_approved",
                document.document_id,
            )
            session.commit()
        except Exception:
            session.rollback()
            try:
                registry.revoke(
                    sha256=document.sha256,
                    document_id=document.document_id,
                    reason="authorization audit commit failed",
                    approved_by=principal.user_id,
                )
            except Exception:
                LOGGER.warning("authorization_compensation_failed")
            raise
    except (PermissionError, LookupError, FileExistsError, ValueError) as exc:
        raise translate(exc) from exc
    return ExternalAuthorizationRecord.model_validate(
        {
            "document_id": record["document_id"],
            "sha256": record["sha256"],
            "action": record["action"],
            "approved_at": record["approved_at"],
            "approved_by": record["approved_by"],
        }
    )


@router.post(
    "/{documentId}/external-authorization/revoke",
    response_model=ExternalAuthorizationRecord,
    response_model_exclude_none=True,
    operation_id="revokeDocumentExternalProcessing",
)
def revoke_external_processing(
    projectId: str,
    documentId: str,
    body: ExternalAuthorizationRevocationRequest,
    request: Request,
    principal: User,
    session: DB,
) -> ExternalAuthorizationRecord:
    """Revoke one file's approval; the next egress decision observes the revocation."""
    product_mode = getattr(request.app.state, "external_authorization_mode", None) == "postgres"
    registry = getattr(request.app.state, "external_authorization_registry", None)
    if not product_mode and registry is None:
        raise HTTPException(503, detail="external processing authorization is unavailable")
    if product_mode:
        purpose = body.purpose or getattr(
            request.app.state, "external_authorization_purpose", None
        )
        provider = body.provider or getattr(
            request.app.state, "external_authorization_provider", None
        )
        if purpose is None or provider is None:
            raise HTTPException(503, detail="external authorization policy is unavailable")
        try:
            row = execution_authorization.revoke_document(
                session,
                principal,
                projectId,
                documentId,
                reason=body.reason,
                purpose=purpose,
                provider=provider,
            )
        except (PermissionError, LookupError, FileExistsError, ValueError) as exc:
            raise translate(exc) from exc
        return ExternalAuthorizationRecord.model_validate(
            execution_authorization.authorization_response(row)
        )
    if body.purpose is not None or body.provider is not None:
        raise HTTPException(
            422,
            detail="purpose and provider require the PostgreSQL product authorization",
        )
    assert registry is not None
    try:
        documents.require_reviewer(session, principal)
        document = documents.find_document(session, principal, projectId, documentId)
        record = registry.revoke(
            sha256=document.sha256,
            document_id=document.document_id,
            reason=body.reason,
            approved_by=principal.user_id,
        )
        try:
            audit(
                session,
                principal.tenant_id,
                principal.user_id,
                "document.external_authorization_revoked",
                document.document_id,
            )
            session.commit()
        except Exception:
            session.rollback()
            try:
                registry.approve(
                    sha256=document.sha256,
                    document_id=document.document_id,
                    reason="authorization audit commit failed",
                    approved_by=principal.user_id,
                )
            except Exception:
                LOGGER.warning("authorization_compensation_failed")
            raise
    except (PermissionError, LookupError, FileExistsError, ValueError) as exc:
        raise translate(exc) from exc
    return ExternalAuthorizationRecord.model_validate(
        {
            "document_id": record["document_id"],
            "sha256": record["sha256"],
            "action": record["action"],
            "approved_at": record["approved_at"],
            "approved_by": record["approved_by"],
            "revoked_at": record["approved_at"],
            "revoked_by": record["approved_by"],
            "revocation_reason": record["reason"],
        }
    )


@router.get("/{documentId}/original", response_class=Response, operation_id="downloadDocument")
def original(
    projectId: str, documentId: str, request: Request, principal: User, session: DB
) -> Response:
    try:
        document = documents.find_document(session, principal, projectId, documentId)
        if document.file_format not in {"pdf", "docx", "png", "jpeg"}:
            raise IngestionError("HASH_MISMATCH")
        payload = documents.download(
            session,
            principal,
            projectId,
            documentId,
            make_store(cast(Settings, request.app.state.settings)),
            load_policy(),
        )
    except (LookupError, FileExistsError, IngestionError) as exc:
        raise translate(exc) from exc
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="document-{documentId}.{document.file_format}"'
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{documentId}/sections/{sectionId}/revisions/{revision}",
    operation_id="resolveDocumentCitation",
)
def resolve_citation(
    projectId: str,
    documentId: str,
    sectionId: str,
    revision: int,
    sourceHash: str,
    principal: User,
    session: DB,
) -> dict[str, object]:
    try:
        return reports.citation_fragment(
            session,
            principal,
            project_id=projectId,
            document_id=documentId,
            section_id=sectionId,
            revision=revision,
            source_hash=sourceHash,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise translate(exc) from exc
