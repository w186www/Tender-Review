"""Independent source and legal-artifact checks for model-linked findings."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.domain.rules.models import CandidateFinding, SourceExcerpt
from bidding_compliance.legal.contracts import LegalHit, RetrievalResult
from bidding_compliance.persistence.models import LegalRetrievalRun
from bidding_compliance.services import documents
from bidding_compliance.services.legal import read_run
from bidding_compliance.services.legal_management import resolve_published_evidence
from bidding_compliance.services.review_persistence import canonical_json


def evidence_identity(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def has_confirmable_legal_support(hits: Sequence[LegalHit], *, invalid: bool = False) -> bool:
    return bool(hits) and not invalid and all(
        hit.eligible_for_confirmation
        and hit.version_status == "verified_current"
        and bool(hit.article)
        for hit in hits
    )


def evidence_status_for_support(*, document_valid: bool, legal_valid: bool) -> str:
    if not document_valid or not legal_valid:
        return "insufficient_evidence"
    # A reviewed rule-to-law binding is not approved, so evidence alone cannot confirm.
    return "suspected"


def verify_document_excerpt(
    session: Session,
    principal: Principal,
    *,
    project_id: str,
    candidate: CandidateFinding,
    excerpt: SourceExcerpt,
    expected_document_refs: dict[str, str],
) -> dict[str, Any] | None:
    """Re-read the current pinned section and prove the exact text locator and hashes."""
    try:
        document = documents.find_document(session, principal, project_id, excerpt.document_id)
        if document.status != "ready" or document.sha256 != excerpt.document_sha256:
            return None
        section_index = documents.sections(session, principal, project_id, excerpt.document_id)
        if section_index.parse_version != document.parse_version:
            return None
        matching = [item for item in section_index.items if item.section_id == excerpt.section_id]
        if len(matching) != 1:
            return None
        section = matching[0]
        fragment = section.effective
        bbox = tuple(fragment.bbox) if fragment.bbox is not None else None
        if (
            section.revision != excerpt.section_revision
            or section.source_hash != excerpt.document_sha256
            or fragment.locator != excerpt.locator
            or fragment.page != excerpt.page
            or fragment.coordinate_system != excerpt.coordinate_system
            or bbox != excerpt.bbox
        ):
            # The explicit comparisons below avoid accepting partial locator matches.
            return None
        if (
            fragment.text != excerpt.quote
            or hashlib.sha256(fragment.text.encode("utf-8")).hexdigest() != excerpt.quote_sha256
            or expected_document_refs.get(excerpt.document_id) != candidate.document_version_ref
        ):
            return None
        return {
            "evidence_id": evidence_identity(
                {
                    "document_id": excerpt.document_id,
                    "document_sha256": excerpt.document_sha256,
                    "section_id": excerpt.section_id,
                    "section_revision": excerpt.section_revision,
                    "locator": excerpt.locator,
                    "quote_sha256": excerpt.quote_sha256,
                    "candidate_id": candidate.candidate_id,
                }
            ),
            "kind": "document",
            "title": "投标文件原文",
            "article": None,
            "quote": excerpt.quote,
            "source_uri": f"artifact://document/{excerpt.document_sha256}",
            "source_hash": excerpt.document_sha256,
            "page": excerpt.page,
            "locator": excerpt.locator,
            "effective_from": None,
            "effective_to": None,
            "version_status": "unverified",
            "jurisdiction": None,
        }
    except (LookupError, FileExistsError, ValueError):
        return None


def verify_legal_hit(
    session: Session,
    principal: Principal,
    *,
    publication_id: str,
    revision_id: str,
    result_payload: dict[str, Any],
    hit_payload: dict[str, Any],
) -> tuple[LegalHit | None, str | None]:
    """Revalidate the saved retrieval run, publication, applicability and legal bytes."""
    try:
        result = RetrievalResult.model_validate(result_payload)
        hit = LegalHit.model_validate(hit_payload)
        if result.query is None or result.run_snapshot is None:
            return None, None
        run_id = result.run_snapshot.run_id
        reread = read_run(session, principal, run_id)
        if reread != result:
            return None, None
        record = session.get(LegalRetrievalRun, (principal.tenant_id, run_id))
        if record is None or (
            record.request_snapshot.get("publication_id") != publication_id
            or record.request_snapshot.get("revision_id") != revision_id
        ):
            return None, None
        quote = resolve_published_evidence(session, principal, publication_id, hit, result.query)
        if quote != hit.quote:
            return None, None
        return hit, quote
    except (LookupError, ValueError, KeyError):
        return None, None
