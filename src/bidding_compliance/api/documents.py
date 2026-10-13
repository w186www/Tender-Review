"""File APIs share the authenticated tenant principal; all parsing runs in a worker."""

from typing import Annotated, cast

from fastapi import APIRouter, File, Header, HTTPException, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from bidding_compliance.core.config import Settings
from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.ports import IngestionError
from bidding_compliance.ingestion.schemas import (
    ContextConfirmation,
    DocumentContext,
    DocumentResponse,
    QualityCorrection,
    SectionsResponse,
)
from bidding_compliance.ingestion.storage import make_store
from bidding_compliance.services import documents

from .projects import DB, User
from .schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/projects/{projectId}/documents",
    responses={
        status: {"model": ErrorResponse, "description": "统一安全错误"}
        for status in (400, 401, 403, 404, 409, 413, 415, 422, 500)
    },
)


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
