"""REST adapters over the existing immutable legal revision/publication lifecycle."""

import json
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bidding_compliance.core.dates import as_utc
from bidding_compliance.legal.contracts import LegalManifest
from bidding_compliance.legal.management_contracts import (
    OPERATIONS,
    OperatorCapabilities,
    PublicationRequest,
    RevisionRequest,
    VerificationSource,
)
from bidding_compliance.persistence.models import (
    LegalCorpusRevision,
    LegalCorpusState,
    LegalOperatorGrant,
    LegalPublication,
)
from bidding_compliance.services import legal_management
from bidding_compliance.services.legal import require_identity

from .configuration_schemas import (
    LegalDraftRequest,
    LegalManagementResponse,
    LegalPublicationItem,
    LegalRevisionItem,
    LegalVersionSummary,
)
from .projects import DB, User
from .schemas import ErrorResponse

ROOT = Path(__file__).resolve().parents[3]
router = APIRouter(
    prefix="/api/v1/admin/legal",
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 500)},
)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(403, detail="当前账号没有法规发布授权")
    if isinstance(exc, LookupError):
        return HTTPException(404, detail="法规修订或发布版本不存在")
    if isinstance(exc, (FileExistsError, IntegrityError)):
        return HTTPException(409, detail="法规版本已变化，请刷新后重试")
    if isinstance(exc, ValueError):
        terms = ("stale", "changed", "conflict", "concurrent", "sequence")
        status = 409 if any(term in str(exc).casefold() for term in terms) else 422
        return HTTPException(status, detail="法规版本参数无效或状态冲突")
    return HTTPException(500, detail="法规版本服务暂时不可用")


@router.get("", response_model=LegalManagementResponse, operation_id="getLegalManagement")
def get_legal_management(principal: User, session: DB) -> LegalManagementResponse:
    try:
        require_identity(session, principal)
        state = session.get(LegalCorpusState, 1, populate_existing=True)
        if state is None:
            raise HTTPException(503, detail="法规生命周期迁移尚未执行")
        grant = session.get(
            LegalOperatorGrant,
            (principal.tenant_id, principal.user_id),
            populate_existing=True,
        )
        capabilities: list[str] = []
        if grant and grant.active:
            value = OperatorCapabilities.model_validate(
                {"active": grant.active, "capabilities": grant.capabilities}
            )
            capabilities = sorted(set(value.capabilities) & OPERATIONS)

        revisions = list(
            session.scalars(
                select(LegalCorpusRevision)
                .order_by(LegalCorpusRevision.draft_sequence.desc())
                .limit(50)
            )
        )
        revision_items = []
        for row in revisions:
            bundle = legal_management.validated_revision(row)
            revision_items.append(
                LegalRevisionItem(
                    revision_id=row.revision_id,
                    draft_sequence=row.draft_sequence,
                    parent_id=row.parent_id,
                    operation=cast(Literal["ingest", "verify"], row.operation),
                    content_hash=row.content_hash,
                    index_hash=row.index_hash,
                    reason=row.reason,
                    actor_id=row.actor_id,
                    created_at=as_utc(row.created_at),
                    versions=[
                        LegalVersionSummary(
                            law_id=item.law_id,
                            title=item.title,
                            version=item.version,
                            verification=item.verification,
                            verified_through=item.verified_through,
                            end_status=item.end_status,
                        )
                        for item in bundle.index.manifest.versions
                    ],
                )
            )
        publications = list(
            session.scalars(
                select(LegalPublication).order_by(LegalPublication.sequence.desc()).limit(50)
            )
        )
        publication_items = [
            LegalPublicationItem(
                publication_id=row.publication_id,
                sequence=row.sequence,
                previous_id=row.previous_id,
                target_id=row.target_id,
                revision_id=row.revision_id,
                operation=cast(Literal["publish", "disable", "rollback"], row.operation),
                reason=row.reason,
                actor_id=row.actor_id,
                created_at=as_utc(row.created_at),
            )
            for row in publications
        ]
        return LegalManagementResponse(
            sequence=state.sequence,
            publication_id=state.publication_id,
            draft_sequence=state.draft_sequence,
            draft_revision_id=state.draft_revision_id,
            capabilities=capabilities,
            revisions=revision_items,
            publications=publication_items,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/drafts",
    response_model=LegalManagementResponse,
    status_code=201,
    operation_id="createLegalDraft",
)
def create_legal_draft(
    body: LegalDraftRequest, principal: User, session: DB
) -> LegalManagementResponse:
    try:
        manifest = LegalManifest.model_validate_json(
            (ROOT / "config/legal/manifest.json").read_bytes()
        )
        raw_proofs = json.loads((ROOT / "config/legal/verification-sources.json").read_bytes())
        proofs = tuple(VerificationSource.model_validate(item) for item in raw_proofs)
        legal_management.create_revision(
            session,
            principal,
            ROOT,
            manifest,
            RevisionRequest(
                request_id=body.request_id,
                expected_draft_sequence=body.expected_draft_sequence,
                reason=body.reason,
                verification_sources=proofs,
            ),
        )
        session.expire_all()
        return get_legal_management(principal, session)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/publications",
    response_model=LegalManagementResponse,
    operation_id="changeLegalPublication",
)
def change_legal_publication(
    body: PublicationRequest, principal: User, session: DB
) -> LegalManagementResponse:
    try:
        legal_management.publish(session, principal, body)
        session.expire_all()
        return get_legal_management(principal, session)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc
