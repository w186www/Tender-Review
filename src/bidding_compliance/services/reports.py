"""Snapshot-bound report creation, citation validation and authorized export."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.persistence.models import (
    Document,
    DocumentSection,
    ReviewArtifact,
    ReviewEngineRun,
    ReviewReport,
    ReviewReportContent,
    ReviewResult,
    SectionRevision,
)
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.projects import find_project
from bidding_compliance.services.reporting import render_docx, render_pdf
from bidding_compliance.services.review_persistence import (
    RESULT_PENDING_ID,
    canonical_json,
    content_hash,
)

TEMPLATE_VERSION = "task0010-v1"
MAX_REPORT_BYTES = 20_000_000


def _source_locations(
    session: Session,
    principal: Principal,
    result: ReviewResult,
    run: ReviewEngineRun,
    finding: dict[str, Any],
) -> list[dict[str, Any]]:
    discovery_row = session.scalar(
        select(ReviewArtifact).where(
            ReviewArtifact.tenant_id == principal.tenant_id,
            ReviewArtifact.review_task_id == result.review_task_id,
            ReviewArtifact.run_id == result.run_id,
            ReviewArtifact.kind == "candidate_discovery",
        )
    )
    if discovery_row is None or content_hash(discovery_row.content) != discovery_row.content_hash:
        raise ValueError("frozen source locator artifact is unavailable")
    discovery = discovery_row.content
    if discovery.get("status") == "failed_skill":
        raise ValueError("failed candidate discovery cannot support a formal report")
    candidate = None
    for entry in discovery.get("candidates", []):
        expected_id = hashlib.sha256(
            f"{principal.tenant_id}:{result.review_task_id}:{result.run_id}:{entry['candidate_id']}".encode()
        ).hexdigest()
        if expected_id == finding["finding_id"]:
            candidate = entry
            break
    if candidate is None:
        raise ValueError("finding does not bind to the frozen source candidate")
    snapshot_docs = {
        item["document_id"]: item for item in run.snapshot["input_snapshot"]["documents"]
    }
    evidence_by_source = {
        (item.get("source_hash"), item.get("page"), item.get("locator"), item.get("quote"))
        for item in finding.get("evidence", [])
        if item.get("kind") == "document"
    }
    result_locations: list[dict[str, Any]] = []
    for source in candidate.get("source_excerpts", []):
        identity = (
            source["document_sha256"],
            source.get("page"),
            source["locator"],
            source["quote"],
        )
        if identity not in evidence_by_source:
            raise ValueError("published document evidence differs from its frozen source excerpt")
        expected_doc = snapshot_docs.get(source["document_id"])
        document = session.scalar(
            select(Document).where(
                Document.tenant_id == principal.tenant_id,
                Document.project_id == result.content["project_id"],
                Document.document_id == source["document_id"],
            )
        )
        if (
            expected_doc is None
            or document is None
            or document.sha256 != source["document_sha256"]
            or expected_doc["raw_source_sha256"] != document.sha256
        ):
            raise ValueError("source document version is unavailable or mismatched")
        section = session.get(
            DocumentSection,
            (principal.tenant_id, source["document_id"], source["section_id"]),
        )
        if section is None:
            raise ValueError("source fragment is unavailable")
        revision = source["section_revision"]
        if revision == 0:
            fragment = section.automatic
        else:
            historical = session.get(
                SectionRevision,
                (principal.tenant_id, source["document_id"], source["section_id"], revision),
            )
            if historical is None and section.revision == revision:
                # Legacy ingestion rows may record revision 1 before a manual revision exists;
                # the established document service treats the automatic fragment as effective.
                fragment = section.automatic
            elif historical is None:
                raise ValueError("source fragment revision is unavailable")
            else:
                fragment = historical.payload
        quote = fragment.get("text")
        if (
            quote != source["quote"]
            or hashlib.sha256(quote.encode("utf-8")).hexdigest() != source["quote_sha256"]
            or fragment.get("locator") != source["locator"]
            or fragment.get("page") != source.get("page")
            or fragment.get("coordinate_system") != source["coordinate_system"]
        ):
            raise ValueError("source location could not be verified against its immutable fragment")
        result_locations.append(
            {
                "document_id": source["document_id"],
                "raw_source_sha256": source["document_sha256"],
                "parse_version": expected_doc["parse_version"],
                "section_id": source["section_id"],
                "section_revision": revision,
                "locator": source["locator"],
                "page": source.get("page"),
                "coordinate_system": source["coordinate_system"],
                "bbox": source.get("bbox"),
                "quote": quote,
                "quote_sha256": source["quote_sha256"],
            }
        )
    if not result_locations:
        raise ValueError("formal report requires a verifiable original document citation")
    return result_locations


def report_payload(
    session: Session,
    principal: Principal,
    result: ReviewResult,
    *,
    report_content_id: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if content_hash(result.content) != result.content_hash:
        raise ValueError("published result content hash mismatch")
    run = session.get(
        ReviewEngineRun,
        (principal.tenant_id, result.review_task_id, result.run_id),
    )
    if (
        run is None
        or run.snapshot_hash != result.snapshot_hash
        or content_hash(run.snapshot) != run.snapshot_hash
    ):
        raise ValueError("published result input snapshot is unavailable")
    find_project(session, principal, result.content["project_id"])
    findings = []
    for original in result.content["findings"]:
        item = json.loads(canonical_json(original))
        if item.get("evidence_status") == "confirmed":
            raise ValueError("current legal evidence policy does not permit confirmed findings")
        if item["finding_id"] != RESULT_PENDING_ID:
            item["citations"] = _source_locations(session, principal, result, run, item)
        findings.append(item)
    project_context = session.scalar(
        select(ReviewArtifact).where(
            ReviewArtifact.tenant_id == principal.tenant_id,
            ReviewArtifact.review_task_id == result.review_task_id,
            ReviewArtifact.run_id == result.run_id,
            ReviewArtifact.kind == "project_context",
        )
    )
    frozen_project_name = None
    if project_context is not None:
        if content_hash(project_context.content) != project_context.content_hash:
            raise ValueError("frozen project context hash mismatch")
        if project_context.content.get("context_sha256") != run.snapshot.get(
            "project_context_sha256"
        ):
            raise ValueError("frozen project context does not match the review input snapshot")
        frozen_project_name = project_context.content.get("context", {}).get("name")
    return {
        "schema_version": "task0010-report.v1",
        "tenant_id": principal.tenant_id,
        "project_id": result.content["project_id"],
        "project_name": frozen_project_name,
        "review_task_id": result.review_task_id,
        "run_id": result.run_id,
        "result_id": result.result_id,
        "snapshot_hash": result.snapshot_hash,
        "report_id": report_content_id or str(uuid4()),
        "template_version": TEMPLATE_VERSION,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "input_snapshot": run.snapshot["input_snapshot"],
        "findings": findings,
    }


def create_report(
    session: Session,
    principal: Principal,
    *,
    result_id: str,
    output_format: str,
    idempotency_key: str,
) -> ReviewReport:
    require_identity(session, principal)
    if principal.role is not Role.REVIEWER:
        audit(session, principal.tenant_id, principal.user_id, "report.generate_denied", result_id)
        session.commit()
        raise PermissionError("report generation requires reviewer role")
    if output_format not in {"docx", "pdf"}:
        raise ValueError("unsupported report format")
    if not 16 <= len(idempotency_key) <= 200:
        raise ValueError("valid report idempotency key is required")
    result = session.get(ReviewResult, (principal.tenant_id, result_id), populate_existing=True)
    if result is None:
        audit(session, principal.tenant_id, principal.user_id, "report.not_visible", result_id)
        session.commit()
        raise LookupError("report result unavailable")
    find_project(session, principal, result.content["project_id"])
    existing = session.scalar(
        select(ReviewReport).where(
            ReviewReport.tenant_id == principal.tenant_id,
            ReviewReport.result_id == result_id,
            ReviewReport.format == output_format,
            ReviewReport.template_version == TEMPLATE_VERSION,
        )
    )
    if existing is not None:
        audit(session, principal.tenant_id, principal.user_id, "report.reused", existing.report_id)
        session.commit()
        return existing
    content_record = session.scalar(
        select(ReviewReportContent).where(
            ReviewReportContent.tenant_id == principal.tenant_id,
            ReviewReportContent.result_id == result_id,
            ReviewReportContent.template_version == TEMPLATE_VERSION,
        )
    )
    if content_record is None:
        content_id = str(uuid4())
        content_created_at = datetime.now(UTC)
        try:
            structured = report_payload(
                session,
                principal,
                result,
                report_content_id=content_id,
                generated_at=content_created_at,
            )
            if len(canonical_json(structured).encode("utf-8")) > MAX_REPORT_BYTES:
                raise ValueError("structured report content exceeds its storage limit")
            content_record = ReviewReportContent(
                tenant_id=principal.tenant_id,
                report_content_id=content_id,
                result_id=result_id,
                template_version=TEMPLATE_VERSION,
                snapshot_hash=result.snapshot_hash,
                content_hash=content_hash(structured),
                content=structured,
                actor_id=principal.user_id,
                created_at=content_created_at,
            )
            session.add(content_record)
            audit(session, principal.tenant_id, principal.user_id, "report.requested", result_id)
            session.commit()
            # PostgreSQL clears transaction-local identity settings at commit.
            # Revalidate before writing the rendered artifact and its audit event.
            require_identity(session, principal)
        except IntegrityError:
            session.rollback()
            require_identity(session, principal)
            content_record = session.scalar(
                select(ReviewReportContent).where(
                    ReviewReportContent.tenant_id == principal.tenant_id,
                    ReviewReportContent.result_id == result_id,
                    ReviewReportContent.template_version == TEMPLATE_VERSION,
                )
            )
            if content_record is None:
                raise
        except Exception:
            session.rollback()
            require_identity(session, principal)
            audit(
                session, principal.tenant_id, principal.user_id, "report.render_failed", result_id
            )
            session.commit()
            raise
    if (
        content_record is None
        or content_hash(content_record.content) != content_record.content_hash
        or content_record.snapshot_hash != result.snapshot_hash
    ):
        raise ValueError("structured report content is unavailable or has changed")
    payload = content_record.content
    try:
        encoded = render_docx(payload) if output_format == "docx" else render_pdf(payload)
    except Exception:
        session.rollback()
        require_identity(session, principal)
        audit(session, principal.tenant_id, principal.user_id, "report.render_failed", result_id)
        session.commit()
        raise
    if not encoded or len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("rendered report is empty or exceeds its storage limit")
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    row = ReviewReport(
        tenant_id=principal.tenant_id,
        report_id=str(uuid4()),
        result_id=result_id,
        report_content_id=content_record.report_content_id,
        format=output_format,
        template_version=TEMPLATE_VERSION,
        idempotency_key=key_hash,
        snapshot_hash=result.snapshot_hash,
        content_hash=hashlib.sha256(encoded).hexdigest(),
        content=encoded,
        actor_id=principal.user_id,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    audit(session, principal.tenant_id, principal.user_id, "report.generated", row.report_id)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        require_identity(session, principal)
        previous = session.scalar(
            select(ReviewReport).where(
                ReviewReport.tenant_id == principal.tenant_id,
                ReviewReport.result_id == result_id,
                ReviewReport.format == output_format,
                ReviewReport.template_version == TEMPLATE_VERSION,
            )
        )
        if previous is None:
            raise
        return previous
    return row


def export_report(session: Session, principal: Principal, report_id: str) -> ReviewReport:
    require_identity(session, principal)
    if principal.role not in {Role.REVIEWER, Role.AUDITOR}:
        audit(session, principal.tenant_id, principal.user_id, "report.export_denied", report_id)
        session.commit()
        raise PermissionError("report export is not authorized")
    row = session.get(ReviewReport, (principal.tenant_id, report_id), populate_existing=True)
    if row is None:
        audit(session, principal.tenant_id, principal.user_id, "report.not_visible", report_id)
        session.commit()
        raise LookupError("report unavailable")
    result = session.get(ReviewResult, (principal.tenant_id, row.result_id))
    if result is None:
        raise LookupError("report result unavailable")
    find_project(session, principal, result.content["project_id"])
    if (
        hashlib.sha256(row.content).hexdigest() != row.content_hash
        or row.snapshot_hash != result.snapshot_hash
    ):
        raise ValueError("report artifact hash or result provenance mismatch")
    audit(session, principal.tenant_id, principal.user_id, "report.exported", row.report_id)
    session.commit()
    return row


def citation_fragment(
    session: Session,
    principal: Principal,
    *,
    project_id: str,
    document_id: str,
    section_id: str,
    revision: int,
    source_hash: str,
) -> dict[str, Any]:
    require_identity(session, principal)
    document = session.scalar(
        select(Document).where(
            Document.tenant_id == principal.tenant_id,
            Document.project_id == project_id,
            Document.document_id == document_id,
        )
    )
    if document is None or document.sha256 != source_hash:
        raise LookupError("citation unavailable")
    find_project(session, principal, project_id)
    section = session.get(DocumentSection, (principal.tenant_id, document_id, section_id))
    if section is None:
        raise LookupError("citation unavailable")
    if revision == 0:
        fragment: dict[str, Any] = section.automatic
    else:
        row = session.get(SectionRevision, (principal.tenant_id, document_id, section_id, revision))
        if row is None and section.revision == revision:
            fragment = section.automatic
        elif row is None:
            raise LookupError("citation unavailable")
        else:
            fragment = row.payload
    return {
        "document_id": document_id,
        "source_hash": source_hash,
        "section_id": section_id,
        "revision": revision,
        "fragment": fragment,
    }
