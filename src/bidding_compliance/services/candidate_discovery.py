"""Tenant-authorized deterministic candidate discovery over confirmed documents."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.domain.rules.engine import SKILLS, discover
from bidding_compliance.domain.rules.models import (
    DiscoveryDocumentRequest,
    DiscoveryInputSnapshot,
    DiscoveryResult,
    DocumentVersionRef,
    LocatedFragment,
    SkillId,
)
from bidding_compliance.ingestion.schemas import Fragment
from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.services import documents
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.projects import find_project


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def discover_for_project(
    session: Session,
    principal: Principal,
    project_id: str,
    requested_documents: tuple[DiscoveryDocumentRequest, ...],
    skill_ids: tuple[SkillId, ...] = tuple(SKILLS),
) -> DiscoveryResult:
    """Run fixed skills against explicitly pinned, ready, confirmed document versions."""
    snapshot, located_by_document = snapshot_for_project(
        session, principal, project_id, requested_documents
    )
    return discover(snapshot, located_by_document, skill_ids)


def snapshot_for_project(
    session: Session,
    principal: Principal,
    project_id: str,
    requested_documents: tuple[DiscoveryDocumentRequest, ...],
) -> tuple[DiscoveryInputSnapshot, dict[str, tuple[LocatedFragment, ...]]]:
    """Load and hash confirmed inputs without running a Skill; used to freeze a run first."""
    require_identity(session, principal)
    set_tenant(session, principal.tenant_id)
    project = find_project(session, principal, project_id)
    if not requested_documents or len(requested_documents) > 100:
        raise ValueError("one to one hundred documents are required")
    if len({item.document_id for item in requested_documents}) != len(requested_documents):
        raise ValueError("duplicate document request")

    project_context = dict(project.context)
    project_context_hash = _canonical_hash(project_context)
    project_ref_hash = _canonical_hash(
        {
            "tenant_id": principal.tenant_id,
            "project_id": project_id,
            "version": project.version,
            "context_sha256": project_context_hash,
        }
    )
    document_refs: list[DocumentVersionRef] = []
    located_by_document: dict[str, tuple[LocatedFragment, ...]] = {}
    for expected in sorted(requested_documents, key=lambda item: item.document_id):
        record = documents.find_document(session, principal, project_id, expected.document_id)
        if record.status != "ready":
            raise FileExistsError("document is not ready for deterministic review")
        if (
            record.sha256 != expected.raw_source_sha256
            or record.parse_version != expected.parse_version
            or record.context_version != expected.context_version
        ):
            raise FileExistsError("document version changed; refresh the discovery request")
        context = documents.context(session, principal, project_id, record.document_id)
        if not context.confirmed or context.version != record.context_version:
            raise FileExistsError("document context is not confirmed at the current version")
        sections = documents.sections(session, principal, project_id, record.document_id)
        if sections.parse_version != record.parse_version or not sections.items:
            raise FileExistsError("document parsed sections are unavailable or stale")
        effective_fragments: list[tuple[str, int, Fragment]] = []
        for section in sections.items:
            fragment = section.effective
            if section.source_hash != record.sha256:
                raise ValueError("stored source hash does not match document")
            if hashlib.sha256(fragment.text.encode("utf-8")).hexdigest() != fragment.text_sha256:
                raise ValueError("effective fragment hash mismatch")
            effective_fragments.append(
                (
                    section.section_id,
                    section.revision,
                    Fragment.model_validate(fragment.model_dump()),
                )
            )
        if not effective_fragments:
            raise FileExistsError("document has no effective parsed fragments")
        effective_fragments.sort(key=lambda item: (item[0], item[2].locator))
        fragment_payload = [
            {
                "section_id": section_id,
                "section_revision": revision,
                "fragment": fragment.model_dump(mode="json"),
            }
            for section_id, revision, fragment in effective_fragments
        ]
        fragments_hash = _canonical_hash(fragment_payload)
        version_payload = {
            "tenant_id": principal.tenant_id,
            "project_id": project_id,
            "document_id": record.document_id,
            "raw_source_sha256": record.sha256,
            "parse_version": record.parse_version,
            "context_version": record.context_version,
            "fragments_sha256": fragments_hash,
        }
        document_version_ref = "doc-version:sha256:" + _canonical_hash(version_payload)
        doc_ref = DocumentVersionRef(
            document_id=record.document_id,
            raw_source_sha256=record.sha256,
            parse_version=record.parse_version,
            context_version=record.context_version,
            fragments_sha256=fragments_hash,
            document_version_ref=document_version_ref,
            fragment_count=len(effective_fragments),
        )
        document_refs.append(doc_ref)
        located_by_document[record.document_id] = tuple(
            LocatedFragment(
                document=doc_ref,
                section_id=section_id,
                section_revision=revision,
                fragment=fragment,
            )
            for section_id, revision, fragment in effective_fragments
        )
    snapshot = DiscoveryInputSnapshot(
        tenant_id=principal.tenant_id,
        project_id=project_id,
        project_version=project.version,
        project_context_sha256=project_context_hash,
        project_context_ref="project-version:sha256:" + project_ref_hash,
        documents=tuple(document_refs),
    )
    return snapshot, located_by_document
