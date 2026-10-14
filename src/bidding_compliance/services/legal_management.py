"""Authorized, idempotent, atomic revision/publication lifecycle; no mutable snapshot lookups."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.legal.bundles import artifact_bytes, capture_bundle, validate_bundle
from bidding_compliance.legal.contracts import (
    LegalHit,
    LegalManifest,
    RetrievalQuery,
    RetrievalResult,
)
from bidding_compliance.legal.corpus import index_hash, resolve_evidence
from bidding_compliance.legal.extraction import PDFExtractor
from bidding_compliance.legal.hashing import canonical_hash
from bidding_compliance.legal.management_contracts import (
    CorpusBundle,
    PublicationRequest,
    RevisionRequest,
)
from bidding_compliance.legal.retrieval import LegalRetriever
from bidding_compliance.persistence.models import (
    LegalCorpusRevision,
    LegalCorpusState,
    LegalLawIdentity,
    LegalPublication,
)
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity, retrieve_for_project
from bidding_compliance.services.legal_authorization import require_legal_operation


def read_state(session: Session, principal: Principal) -> LegalCorpusState:
    require_identity(session, principal)
    state = session.get(LegalCorpusState, 1, populate_existing=True)
    if state is None:
        raise RuntimeError("legal lifecycle migration required")
    return state


def validated_revision(row: LegalCorpusRevision) -> CorpusBundle:
    if canonical_hash(row.bundle) != row.content_hash:
        raise ValueError("legal revision content hash mismatch")
    bundle = validate_bundle(CorpusBundle.model_validate(row.bundle))
    if index_hash(bundle.index) != row.index_hash:
        raise ValueError("legal revision index hash mismatch")
    return bundle


def create_revision(
    session: Session,
    principal: Principal,
    root: Path,
    manifest: LegalManifest,
    request: RevisionRequest,
    *,
    extractor: PDFExtractor | None = None,
) -> LegalCorpusRevision:
    manifest = LegalManifest.model_validate(manifest.model_dump())
    request = RevisionRequest.model_validate(request.model_dump())
    operation: Literal["verify", "ingest"] = (
        "verify" if any(v.verification == "verified" for v in manifest.versions) else "ingest"
    )
    require_legal_operation(session, principal, operation)
    today = (datetime.now(UTC) + timedelta(hours=8)).date()
    if any(
        v.captured_on > today or (v.verified_through and v.verified_through > today)
        for v in manifest.versions
    ) or any(s.captured_on > today for s in request.verification_sources):
        raise ValueError("future legal capture/verification cannot be asserted")
    bundle = capture_bundle(root, manifest, request.verification_sources, extractor)
    require_legal_operation(session, principal, operation)
    payload = bundle.model_dump(mode="json")
    content_hash = canonical_hash(payload)
    request_hash = canonical_hash(
        {"request": request.model_dump(mode="json"), "content_hash": content_hash}
    )
    existing = session.scalar(
        select(LegalCorpusRevision).where(
            LegalCorpusRevision.actor_tenant == principal.tenant_id,
            LegalCorpusRevision.actor_id == principal.user_id,
            LegalCorpusRevision.request_id == request.request_id,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise FileExistsError("legal revision idempotency conflict")
        validated_revision(existing)
        return existing
    state = read_state(session, principal)
    if state.draft_sequence != request.expected_draft_sequence:
        raise FileExistsError("stale legal draft sequence")
    parent = state.draft_revision_id
    if parent:
        previous = session.get(LegalCorpusRevision, parent)
        assert previous is not None
        previous_bundle = validated_revision(previous)
        known = {
            "".join(v.title.split()).casefold(): v.law_id
            for v in previous_bundle.index.manifest.versions
        }
        if any(
            known.get("".join(v.title.split()).casefold(), v.law_id) != v.law_id
            for v in manifest.versions
        ):
            raise ValueError("source change cannot replace stable legal identity")
    require_legal_operation(session, principal, operation)
    row = LegalCorpusRevision(
        revision_id=str(uuid4()),
        parent_id=parent,
        draft_sequence=request.expected_draft_sequence + 1,
        actor_tenant=principal.tenant_id,
        actor_id=principal.user_id,
        operation=operation,
        request_id=request.request_id,
        request_hash=request_hash,
        content_hash=content_hash,
        index_hash=index_hash(bundle.index),
        bundle=payload,
        reason=request.reason,
        created_at=datetime.now(UTC),
    )
    try:
        for version in manifest.versions:
            title_key = "".join(version.title.split()).casefold()
            identity = session.get(LegalLawIdentity, title_key)
            if identity and identity.law_id != version.law_id:
                raise ValueError("source change cannot replace registered legal identity")
            if identity is None:
                session.add(
                    LegalLawIdentity(
                        title_key=title_key,
                        law_id=version.law_id,
                        actor_tenant=principal.tenant_id,
                        actor_id=principal.user_id,
                        operation=operation,
                    )
                )
        session.add(row)
        session.flush()
        changed = session.scalar(
            update(LegalCorpusState)
            .where(
                LegalCorpusState.singleton == 1,
                LegalCorpusState.draft_sequence == request.expected_draft_sequence,
            )
            .values(draft_sequence=row.draft_sequence, draft_revision_id=row.revision_id)
            .returning(LegalCorpusState.singleton)
        )
        if changed != 1:
            raise FileExistsError("concurrent legal verification conflict")
        audit(
            session, principal.tenant_id, principal.user_id, "legal." + operation, row.revision_id
        )
        session.commit()
        return row
    except IntegrityError as exc:
        session.rollback()
        duplicate = session.scalar(
            select(LegalCorpusRevision).where(
                LegalCorpusRevision.actor_tenant == principal.tenant_id,
                LegalCorpusRevision.actor_id == principal.user_id,
                LegalCorpusRevision.request_id == request.request_id,
            )
        )
        if duplicate and duplicate.request_hash == request_hash:
            require_legal_operation(session, principal, operation)
            validated_revision(duplicate)
            return duplicate
        raise FileExistsError("concurrent legal verification conflict") from exc
    except Exception:
        session.rollback()
        raise


def publish(
    session: Session,
    principal: Principal,
    request: PublicationRequest,
) -> LegalPublication:
    request = PublicationRequest.model_validate(request.model_dump())
    require_legal_operation(session, principal, request.operation)
    request_hash = canonical_hash(request.model_dump(mode="json"))
    own_request = (
        LegalPublication.actor_tenant == principal.tenant_id,
        LegalPublication.actor_id == principal.user_id,
        LegalPublication.request_id == request.request_id,
    )
    existing = session.scalar(select(LegalPublication).where(*own_request))
    if existing:
        if existing.request_hash != request_hash:
            raise FileExistsError("legal publication idempotency conflict")
        return existing
    state = read_state(session, principal)
    if state.sequence != request.expected_sequence:
        raise FileExistsError("stale legal publication sequence")
    previous = state.publication_id
    revision_id = request.revision_id
    if request.operation == "rollback":
        target = session.get(LegalPublication, request.target_publication_id)
        if target is None or target.revision_id is None:
            raise LookupError("published rollback target unavailable")
        revision_id = target.revision_id
    if request.operation == "publish" and (
        state.draft_revision_id != revision_id
        or state.draft_sequence != request.expected_draft_sequence
    ):
        raise FileExistsError("stale legal verification revision")
    if revision_id:
        revision_row = session.get(LegalCorpusRevision, revision_id)
        if revision_row is None:
            raise LookupError("legal revision unavailable")
        validated_revision(revision_row)
    require_legal_operation(session, principal, request.operation)
    row = LegalPublication(
        publication_id=str(uuid4()),
        sequence=request.expected_sequence + 1,
        previous_id=previous,
        target_id=request.target_publication_id,
        revision_id=revision_id,
        actor_tenant=principal.tenant_id,
        actor_id=principal.user_id,
        operation=request.operation,
        request_id=request.request_id,
        request_hash=request_hash,
        reason=request.reason,
        created_at=datetime.now(UTC),
    )
    try:
        session.add(row)
        session.flush()
        conditions = [
            LegalCorpusState.singleton == 1,
            LegalCorpusState.sequence == request.expected_sequence,
        ]
        if request.operation == "publish":
            conditions.extend(
                [
                    LegalCorpusState.draft_sequence == request.expected_draft_sequence,
                    LegalCorpusState.draft_revision_id == revision_id,
                ]
            )
        changed = session.scalar(
            update(LegalCorpusState)
            .where(*conditions)
            .values(
                sequence=row.sequence,
                publication_id=row.publication_id,
            )
            .returning(LegalCorpusState.singleton)
        )
        if changed != 1:
            raise FileExistsError("concurrent legal publication conflict")
        audit(
            session,
            principal.tenant_id,
            principal.user_id,
            "legal." + request.operation,
            row.publication_id,
        )
        session.commit()
        return row
    except IntegrityError as exc:
        session.rollback()
        duplicate = session.scalar(select(LegalPublication).where(*own_request))
        if duplicate and duplicate.request_hash == request_hash:
            require_legal_operation(session, principal, request.operation)
            return duplicate
        raise FileExistsError("concurrent legal publication conflict") from exc
    except Exception:
        session.rollback()
        raise


def read_publication(
    session: Session,
    principal: Principal,
    publication_id: str | None = None,
) -> tuple[LegalPublication, CorpusBundle]:
    state = read_state(session, principal)
    chosen = publication_id or state.publication_id
    publication = session.get(LegalPublication, chosen) if chosen else None
    if publication is None or publication.revision_id is None:
        raise LookupError("no active legal publication")
    revision = session.get(LegalCorpusRevision, publication.revision_id)
    if revision is None:
        raise ValueError("publication revision missing")
    return publication, validated_revision(revision)


def retrieve_published_for_project(
    session: Session,
    principal: Principal,
    project_id: str,
    *,
    text: str,
    review_date: date,
    include_references: bool = False,
    limit: int = 10,
) -> RetrievalResult:
    publication, bundle = read_publication(session, principal)
    retriever = LegalRetriever(bundle.index)
    return retrieve_for_project(
        session,
        principal,
        project_id,
        retriever,
        text=text,
        review_date=review_date,
        include_references=include_references,
        limit=limit,
        publication_id=publication.publication_id,
        revision_id=publication.revision_id,
    )


def resolve_published_evidence(
    session: Session,
    principal: Principal,
    publication_id: str,
    hit: LegalHit,
    query: RetrievalQuery,
) -> str:
    _, bundle = read_publication(session, principal, publication_id)
    return resolve_evidence(
        Path("."), bundle.index, hit, query, reader=artifact_bytes(bundle).__getitem__
    )
