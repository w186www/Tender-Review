"""Durable scoped file intake and manual decisions; never loads the native parser."""

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.ingestion.ports import IngestionError, ObjectStore
from bidding_compliance.ingestion.quality import digest, quality
from bidding_compliance.ingestion.schemas import (
    ContextCandidate,
    ContextConfirmation,
    DocumentContext,
    DocumentResponse,
    Fragment,
    IngestionPolicy,
    QualityCorrection,
    SectionResponse,
    SectionsResponse,
)
from bidding_compliance.ingestion.storage import object_key
from bidding_compliance.ingestion.validation import validate_upload
from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import (
    Document,
    DocumentContextVersion,
    DocumentSection,
    IngestionJob,
    SectionRevision,
)
from bidding_compliance.services.identity import audit
from bidding_compliance.services.projects import find_project


def require_reviewer(session: Session, principal: Principal) -> None:
    set_tenant(session, principal.tenant_id)
    if not principal.can_write_project():
        audit(session, principal.tenant_id, principal.user_id, "document.denied")
        session.commit()
        raise PermissionError("document write forbidden")


def response(document: Document) -> DocumentResponse:
    return DocumentResponse.model_validate(
        dict(
            document_id=document.document_id,
            project_id=document.project_id,
            file_format=document.file_format,
            status=document.status,
            sha256=document.sha256,
            media_type=document.media_type,
            size_bytes=document.size_bytes,
            context_version=document.context_version,
            parse_version=document.parse_version,
            issues=document.issues,
        )
    )


def list_documents(
    session: Session,
    principal: Principal,
    project: str,
    *,
    offset: int,
    limit: int,
) -> tuple[list[DocumentResponse], int]:
    find_project(session, principal, project)
    base = select(Document).where(
        Document.tenant_id == principal.tenant_id,
        Document.project_id == project,
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(
        base.order_by(Document.document_id).offset(offset).limit(limit)
    )
    return [response(row) for row in rows], total


def find_document(session: Session, principal: Principal, project: str, document: str) -> Document:
    set_tenant(session, principal.tenant_id)
    result = session.scalar(
        select(Document).where(
            Document.tenant_id == principal.tenant_id,
            Document.project_id == project,
            Document.document_id == document,
        )
    )
    if result is None:
        audit(session, principal.tenant_id, principal.user_id, "document.not_visible")
        session.commit()
        raise LookupError("document unavailable")
    return result


def upload(
    session: Session,
    principal: Principal,
    project: str,
    filename: str,
    media: str,
    payload: bytes,
    key: str,
    store: ObjectStore,
    policy: IngestionPolicy,
) -> DocumentResponse:
    require_reviewer(session, principal)
    find_project(session, principal, project)
    try:
        format = validate_upload(filename, media, payload, policy)
    except IngestionError:
        audit(session, principal.tenant_id, principal.user_id, "document.upload_rejected")
        session.commit()
        raise
    sha, key_hash = hashlib.sha256(payload).hexdigest(), digest(key)
    request_hash = digest(json.dumps([sha, filename, media], ensure_ascii=False))

    def existing_job() -> IngestionJob | None:
        return session.scalar(
            select(IngestionJob).where(
                IngestionJob.tenant_id == principal.tenant_id,
                IngestionJob.project_id == project,
                IngestionJob.submitted_by == principal.user_id,
                IngestionJob.key_hash == key_hash,
            )
        )

    existing = existing_job()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise FileExistsError("idempotency conflict")
        return response(find_document(session, principal, project, existing.document_id))
    identifier = str(uuid4())
    reference = object_key(principal.tenant_id, project, identifier)
    store.put(reference, payload)
    try:
        document = Document(
            tenant_id=principal.tenant_id,
            document_id=identifier,
            project_id=project,
            status="quarantined",
            sha256=sha,
            object_ref=reference,
            file_format=format,
            media_type=media,
            size_bytes=len(payload),
            parse_version=0,
            context_version=0,
            issues=[],
        )
        session.add(document)
        session.flush()
        session.add(
            IngestionJob(
                tenant_id=principal.tenant_id,
                project_id=project,
                document_id=identifier,
                submitted_by=principal.user_id,
                key_hash=key_hash,
                request_hash=request_hash,
                attempts=0,
                status="queued",
            )
        )
        audit(session, principal.tenant_id, principal.user_id, "document.uploaded", identifier)
        session.commit()
        return response(document)
    except IntegrityError as exc:
        session.rollback()
        store.delete(reference)
        set_tenant(session, principal.tenant_id)
        existing = existing_job()
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise FileExistsError("idempotency conflict") from exc
        return response(find_document(session, principal, project, existing.document_id))
    except Exception:
        session.rollback()
        store.delete(reference)
        raise


def download(
    session: Session,
    principal: Principal,
    project: str,
    document_id: str,
    store: ObjectStore,
    policy: IngestionPolicy,
) -> bytes:
    document = find_document(session, principal, project, document_id)
    if document.status not in {"needs_review", "needs_confirmation", "ready"}:
        raise FileExistsError("unsafe original cannot be downloaded")
    expected = object_key(principal.tenant_id, project, document_id)
    if document.object_ref != expected:
        raise IngestionError("HASH_MISMATCH")
    payload = store.get(expected, policy.max_upload_bytes)
    if hashlib.sha256(payload).hexdigest() != document.sha256:
        raise IngestionError("HASH_MISMATCH")
    audit(session, principal.tenant_id, principal.user_id, "document.downloaded", document_id)
    session.commit()
    return payload


def sections(
    session: Session, principal: Principal, project: str, document_id: str
) -> SectionsResponse:
    document = find_document(session, principal, project, document_id)
    if document.parse_version < 1:
        raise FileExistsError("document has not been parsed")
    rows = session.scalars(
        select(DocumentSection)
        .where(
            DocumentSection.tenant_id == principal.tenant_id,
            DocumentSection.document_id == document_id,
        )
        .order_by(DocumentSection.ordinal)
    )
    items = []
    for row in rows:
        revision = session.get(
            SectionRevision, (principal.tenant_id, document_id, row.section_id, row.revision)
        )
        automatic = Fragment.model_validate(row.automatic)
        effective = Fragment.model_validate(revision.payload) if revision else automatic
        items.append(
            SectionResponse(
                section_id=row.section_id,
                source_hash=document.sha256,
                automatic=automatic,
                effective=effective,
                revision=row.revision,
            )
        )
    return SectionsResponse(
        document_id=document_id, parse_version=document.parse_version, items=items
    )


def infer_context(document_id: str, items: list[SectionResponse]) -> DocumentContext:
    candidates: list[ContextCandidate] = []
    for item in items:
        text = item.effective.text
        if "政府采购" in text:
            candidates.append(
                ContextCandidate(
                    field="procurement_type",
                    value="government",
                    confidence=0.6,
                    section_id=item.section_id,
                )
            )
        if "工程" in text:
            candidates.append(
                ContextCandidate(
                    field="project_type", value="works", confidence=0.6, section_id=item.section_id
                )
            )
        match = re.search(r"(项目名称|项目地区|地区)[：:]\s*([^\n]{1,100})", text)
        if match:
            candidates.append(
                ContextCandidate(
                    field="name" if match[1] == "项目名称" else "region",
                    value=match[2].strip(),
                    confidence=0.6,
                    section_id=item.section_id,
                )
            )
        if len(candidates) >= 100:
            break
    return DocumentContext(
        document_id=document_id, version=1, candidates=candidates, confirmed=False
    )


def context(
    session: Session, principal: Principal, project: str, document_id: str
) -> DocumentContext:
    document = find_document(session, principal, project, document_id)
    record = session.get(
        DocumentContextVersion, (principal.tenant_id, document_id, document.context_version)
    )
    if record is None:
        raise FileExistsError("document context unavailable")
    return DocumentContext.model_validate(record.payload)


def confirm_context(
    session: Session,
    principal: Principal,
    project: str,
    document_id: str,
    decision: ContextConfirmation,
) -> DocumentResponse:
    require_reviewer(session, principal)
    document = find_document(session, principal, project, document_id)
    if document.status not in {"needs_confirmation", "ready"}:
        raise FileExistsError("quality or security gate is not passed")
    previous = context(session, principal, project, document_id)
    if previous.version != decision.expected_version:
        raise FileExistsError("context version conflict")
    updated = previous.model_copy(
        update={
            "version": previous.version + 1,
            "manual": decision.context,
            "confirmed": True,
            "reason": decision.reason,
        }
    )
    changed = session.execute(
        update(Document)
        .where(
            Document.tenant_id == principal.tenant_id,
            Document.document_id == document_id,
            Document.context_version == decision.expected_version,
            Document.status.in_(["needs_confirmation", "ready"]),
        )
        .values(context_version=updated.version, status="ready")
        .returning(Document.document_id)
    )
    if changed.scalar_one_or_none() is None:
        raise FileExistsError("context version conflict")
    session.add(
        DocumentContextVersion(
            tenant_id=principal.tenant_id,
            document_id=document_id,
            version=updated.version,
            payload=updated.model_dump(),
            changed_by=principal.user_id,
            changed_at=datetime.now(UTC),
        )
    )
    audit(
        session, principal.tenant_id, principal.user_id, "document.context_confirmed", document_id
    )
    session.commit()
    return response(document)


def correct_text(
    session: Session,
    principal: Principal,
    project: str,
    document_id: str,
    decision: QualityCorrection,
    policy: IngestionPolicy,
) -> DocumentResponse:
    require_reviewer(session, principal)
    document = find_document(session, principal, project, document_id)
    if document.status not in {"needs_review", "needs_confirmation", "ready"}:
        raise FileExistsError("unsafe or unparsed document")
    current = sections(session, principal, project, document_id)
    if current.parse_version != decision.expected_parse_version:
        raise FileExistsError("parse version conflict")
    ids = [c.section_id for c in decision.corrections]
    if len(set(ids)) != len(ids) or not set(ids) <= {s.section_id for s in current.items}:
        raise ValueError("correction locator invalid")
    changes = {c.section_id: c.text for c in decision.corrections}
    effective = [
        s.effective.model_copy(
            update={
                "text": changes[s.section_id],
                "text_sha256": digest(changes[s.section_id]),
                "source": "manual",
                "confidence": None,
            }
        )
        if s.section_id in changes
        else s.effective
        for s in current.items
    ]
    if sum(len(s.text) for s in effective) > policy.max_text_chars:
        raise IngestionError("TEXT_LIMIT")
    passed = quality(effective, policy)
    changed = session.execute(
        update(Document)
        .where(
            Document.tenant_id == principal.tenant_id,
            Document.document_id == document_id,
            Document.parse_version == decision.expected_parse_version,
            Document.context_version == document.context_version,
            Document.status.in_(["needs_review", "needs_confirmation", "ready"]),
        )
        .values(
            parse_version=decision.expected_parse_version + 1,
            context_version=document.context_version + 1,
            status="needs_confirmation" if passed else "needs_review",
            issues=[] if passed else ["LOW_QUALITY"],
        )
        .returning(Document.document_id)
    )
    if changed.scalar_one_or_none() is None:
        raise FileExistsError("parse version conflict")
    for item, fragment in zip(current.items, effective, strict=True):
        if item.section_id not in changes:
            continue
        row = session.get(DocumentSection, (principal.tenant_id, document_id, item.section_id))
        if row is None:
            raise LookupError("section unavailable")
        row.revision += 1
        session.add(
            SectionRevision(
                tenant_id=principal.tenant_id,
                document_id=document_id,
                section_id=row.section_id,
                revision=row.revision,
                payload=fragment.model_dump(),
                changed_by=principal.user_id,
                reason=decision.reason,
                changed_at=datetime.now(UTC),
            )
        )
    refreshed_items = [
        s.model_copy(update={"effective": f}) for s, f in zip(current.items, effective, strict=True)
    ]
    fresh = infer_context(document_id, refreshed_items).model_copy(
        update={"version": document.context_version}
    )
    session.add(
        DocumentContextVersion(
            tenant_id=principal.tenant_id,
            document_id=document_id,
            version=fresh.version,
            payload=fresh.model_dump(),
            changed_by=principal.user_id,
            changed_at=datetime.now(UTC),
        )
    )
    audit(session, principal.tenant_id, principal.user_id, "document.text_corrected", document_id)
    session.commit()
    return response(document)
