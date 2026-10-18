"""Snapshot-bound report creation, citation validation and authorized export."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.legal.adoption import load_adoption_policy
from bidding_compliance.persistence.models import (
    Document,
    DocumentSection,
    ReviewArtifact,
    ReviewDecision,
    ReviewEngineRun,
    ReviewModelCall,
    ReviewReport,
    ReviewReportContent,
    ReviewResult,
    SectionRevision,
)
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity
from bidding_compliance.services.projects import find_project
from bidding_compliance.services.reporting import render_docx, render_pdf
from bidding_compliance.services.review_management import _runtime_projection
from bidding_compliance.services.review_persistence import (
    RESULT_PENDING_ID,
    authorized_run,
    canonical_json,
    content_hash,
    read_artifact,
)
from bidding_compliance.services.review_projection import project_product_execution

TEMPLATE_VERSION = "task0010-v3.4"
ROOT = Path(__file__).resolve().parents[3]
MAX_REPORT_BYTES = 20_000_000


def _source_locations(
    session: Session,
    principal: Principal,
    result: ReviewResult,
    run: ReviewEngineRun,
    finding: dict[str, Any],
) -> list[dict[str, Any]]:
    return _resolve_source_locations(
        session,
        principal,
        project_id=result.content["project_id"],
        review_task_id=result.review_task_id,
        run_id=result.run_id,
        snapshot=run.snapshot,
        finding=finding,
    )


def _resolve_source_locations(
    session: Session,
    principal: Principal,
    *,
    project_id: str,
    review_task_id: str,
    run_id: str,
    snapshot: dict[str, Any],
    finding: dict[str, Any],
) -> list[dict[str, Any]]:
    discovery_row = _optional_run_artifact(
        session,
        principal,
        review_task_id=review_task_id,
        run_id=run_id,
        kind="candidate_discovery",
    )
    if discovery_row is None or content_hash(discovery_row.content) != discovery_row.content_hash:
        raise ValueError("frozen source locator artifact is unavailable")
    discovery = discovery_row.content
    if discovery.get("status") == "failed_skill":
        raise ValueError("failed candidate discovery cannot support a formal report")
    candidate = None
    for entry in discovery.get("candidates", []):
        expected_id = hashlib.sha256(
            f"{principal.tenant_id}:{review_task_id}:{run_id}:{entry['candidate_id']}".encode()
        ).hexdigest()
        if expected_id == finding["finding_id"]:
            candidate = entry
            break
    if candidate is None:
        raise ValueError("finding does not bind to the frozen source candidate")
    snapshot_docs = {item["document_id"]: item for item in snapshot["input_snapshot"]["documents"]}
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
                Document.project_id == project_id,
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
    primary_identities = {
        (item["raw_source_sha256"], item.get("page"), item["locator"], item["quote"])
        for item in result_locations
    }
    resolved_related: set[tuple[str, str, int, str, str]] = set()
    for reference in finding.get("evidence", []):
        if reference.get("kind") != "document":
            continue
        identity = (
            reference.get("source_hash"),
            reference.get("page"),
            reference.get("locator"),
            reference.get("quote"),
        )
        if identity in primary_identities:
            continue
        uri = reference.get("source_uri", "")
        prefix = "artifact://related-document/"
        if not isinstance(uri, str) or not uri.startswith(prefix):
            raise ValueError(
                "supporting document evidence is not bound to a frozen source location"
            )
        parts = uri[len(prefix) :].split("/")
        if len(parts) != 4:
            raise ValueError("related document evidence locator is malformed")
        document_id, source_hash, section_id, revision_text = parts
        if (
            not source_hash
            or source_hash != reference.get("source_hash")
            or not revision_text.isdigit()
            or document_id not in snapshot_docs
        ):
            raise ValueError("related document evidence identity is invalid")
        revision_number = int(revision_text)
        expected_doc = snapshot_docs[document_id]
        document = session.scalar(
            select(Document).where(
                Document.tenant_id == principal.tenant_id,
                Document.project_id == project_id,
                Document.document_id == document_id,
            )
        )
        if (
            document is None
            or document.sha256 != source_hash
            or document.sha256 != expected_doc["raw_source_sha256"]
        ):
            raise ValueError("related evidence source differs from the frozen input")
        section = session.get(
            DocumentSection,
            (principal.tenant_id, document_id, section_id),
        )
        if section is None or section.revision != revision_number:
            raise ValueError("related evidence fragment revision is unavailable")
        if revision_number == 0:
            fragment = section.automatic
        else:
            historical = session.get(
                SectionRevision,
                (principal.tenant_id, document_id, section_id, revision_number),
            )
            if historical is None and section.revision == revision_number:
                # As with primary citations, revision 1 is the automatic fragment unless a
                # manual revision row exists. Later revisions remain append-only.
                fragment = section.automatic
            elif historical is None:
                raise ValueError("related evidence fragment revision is unavailable")
            else:
                fragment = historical.payload
        quote = fragment.get("text")
        quote_hash = hashlib.sha256(str(quote).encode("utf-8")).hexdigest()
        if (
            quote != reference.get("quote")
            or fragment.get("locator") != reference.get("locator")
            or fragment.get("page") != reference.get("page")
        ):
            raise ValueError("related evidence quote does not match its source fragment")
        reference_identity = {
            "document_id": document_id,
            "document_sha256": source_hash,
            "section_id": section_id,
            "section_revision": revision_number,
            "locator": reference.get("locator"),
            "page": reference.get("page"),
            "quote_sha256": quote_hash,
        }
        expected_evidence_id = hashlib.sha256(
            canonical_json(reference_identity).encode("utf-8")
        ).hexdigest()
        if reference.get("evidence_id") != expected_evidence_id:
            raise ValueError("related evidence identity hash is invalid")
        related_identity = (
            document_id,
            section_id,
            revision_number,
            reference.get("locator"),
            quote_hash,
        )
        if related_identity in resolved_related:
            continue
        resolved_related.add(related_identity)
        result_locations.append(
            {
                "document_id": document_id,
                "raw_source_sha256": source_hash,
                "parse_version": expected_doc["parse_version"],
                "section_id": section_id,
                "section_revision": revision_number,
                "locator": reference["locator"],
                "page": reference.get("page"),
                "coordinate_system": fragment.get("coordinate_system"),
                "bbox": fragment.get("bbox"),
                "quote": quote,
                "quote_sha256": quote_hash,
            }
        )
    return result_locations


def _optional_run_artifact(
    session: Session,
    principal: Principal,
    *,
    review_task_id: str,
    run_id: str,
    kind: str,
) -> ReviewArtifact | None:
    artifacts = list(
        session.scalars(
            select(ReviewArtifact).where(
                ReviewArtifact.tenant_id == principal.tenant_id,
                ReviewArtifact.review_task_id == review_task_id,
                ReviewArtifact.run_id == run_id,
                ReviewArtifact.kind == kind,
            )
        )
    )
    if len(artifacts) > 1:
        raise ValueError(f"verified {kind} artifact is ambiguous")
    if not artifacts:
        return None
    artifact = artifacts[0]
    if artifact is None or content_hash(artifact.content) != artifact.content_hash:
        raise ValueError(f"verified {kind} artifact is unavailable or changed")
    return artifact


def _verified_run_artifact(
    session: Session, principal: Principal, result: ReviewResult, kind: str
) -> ReviewArtifact:
    artifact = _optional_run_artifact(
        session,
        principal,
        review_task_id=result.review_task_id,
        run_id=result.run_id,
        kind=kind,
    )
    if artifact is None:
        raise ValueError(f"verified {kind} artifact is unavailable or changed")
    return artifact


def _related_analysis_context(
    session: Session, principal: Principal, result: ReviewResult, model_content: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """Follow the exact analysis reference; never guess among same-kind artifacts."""
    reference = model_content.get("related_document_evidence_ref")
    if reference is None:
        return None, None  # Historical/zero-candidate analyses did not record a context.
    if not isinstance(reference, str):
        raise ValueError("report related-document context reference is invalid")
    content = read_artifact(
        session,
        principal.tenant_id,
        reference,
        review_task_id=result.review_task_id,
        run_id=result.run_id,
    )
    if content.get("snapshot_hash") != result.snapshot_hash:
        raise ValueError("report related-document context snapshot mismatch")
    return content, content_hash(content)


def _product_execution(
    session: Session,
    principal: Principal,
    result: ReviewResult,
) -> dict[str, Any]:
    """Project run coverage and unknown-call facts into the immutable report.

    Model discovery records one coverage block per run. A saturated or partial batch, or a
    dispatched call whose outcome is unknown, means the review cannot be reported as a
    complete assessment. Deterministic-only runs have no model discovery artifact and are
    reported as not applicable rather than silently upgraded to complete model coverage.
    """
    unknown = session.scalar(
        select(func.count())
        .select_from(ReviewModelCall)
        .where(
            ReviewModelCall.tenant_id == principal.tenant_id,
            ReviewModelCall.review_task_id == result.review_task_id,
            ReviewModelCall.run_id == result.run_id,
            ReviewModelCall.state == "unknown",
        )
    )
    unknown_count = int(unknown or 0)
    discovery = _optional_run_artifact(
        session,
        principal,
        review_task_id=result.review_task_id,
        run_id=result.run_id,
        kind="llm_candidate_discovery",
    )
    if discovery is None:
        # Older real-model runs predate the persisted coverage block. If the run actually
        # produced model candidates, unknown coverage must not be reported as "not
        # applicable"; a deterministic-only run legitimately has no model coverage plan.
        run = session.get(
            ReviewEngineRun,
            (principal.tenant_id, result.review_task_id, result.run_id),
        )
        model_candidates = 0
        if run is not None:
            model_candidates = int(_runtime_projection(session, run)["model_candidate_count"])
        if model_candidates > 0:
            return {
                "completion_status": "partial",
                "coverage_status": "unknown",
                "unprocessed_units": 0,
                "truncated": False,
                "saturated": False,
                "reason_codes": ["coverage_not_recorded"],
                "unknown_model_call_count": unknown_count,
            }
        return project_product_execution(None, unknown_model_call_count=unknown_count)
    if content_hash(discovery.content) != discovery.content_hash:
        raise ValueError("verified model discovery artifact is unavailable or changed")
    coverage = discovery.content.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("model discovery coverage is unavailable")
    batches = discovery.content.get("batches")
    return project_product_execution(
        coverage,
        unknown_model_call_count=unknown_count,
        batches=batches if isinstance(batches, list) else None,
    )


def _assessment_scope(
    session: Session,
    principal: Principal,
    result: ReviewResult,
    *,
    project_context: ReviewArtifact,
) -> dict[str, Any]:
    discovery = _verified_run_artifact(session, principal, result, "candidate_discovery")
    retrieval = _verified_run_artifact(session, principal, result, "legal_retrieval")
    model = _verified_run_artifact(session, principal, result, "model_analysis")
    if content_hash(project_context.content) != project_context.content_hash:
        raise ValueError("frozen project context hash mismatch")

    discovery_content = discovery.content
    skill_coverage = [
        {
            "skill_id": item.get("skill_id", "unknown"),
            "status": item.get("status", "unknown"),
            "candidate_count": item.get("candidates_found", 0),
            "evaluated_rule_count": len(item.get("evaluated_rules", [])),
            "reason": item.get("reason"),
        }
        for item in discovery_content.get("skill_coverages", [])
    ]
    retrieval_status_counts: dict[str, int] = {}
    context_error_counts: dict[str, int] = {}
    retrieval_hit_count = 0
    citable_count = 0
    algorithms: set[str] = set()
    for item in retrieval.content.get("results", []):
        payload = item.get("result", {})
        status = payload.get("status", "unknown")
        retrieval_status_counts[status] = retrieval_status_counts.get(status, 0) + 1
        context_error = payload.get("context_error")
        if context_error:
            context_error_counts[context_error] = context_error_counts.get(context_error, 0) + 1
        retrieval_hit_count += len(payload.get("hits", []))
        citable_count += len(payload.get("citable_evidence", []))
        runtime = (payload.get("run_snapshot") or {}).get("runtime") or {}
        algorithm = runtime.get("algorithm")
        if isinstance(algorithm, str):
            algorithms.add(algorithm)

    context = project_context.content.get("context", {})
    frameworks = context.get("legal_frameworks", []) if isinstance(context, dict) else []
    framework_confirmed = isinstance(frameworks, list) and bool(frameworks)
    no_findings_decision = session.scalar(
        select(ReviewDecision).where(
            ReviewDecision.tenant_id == principal.tenant_id,
            ReviewDecision.review_task_id == result.review_task_id,
            ReviewDecision.run_id == result.run_id,
            ReviewDecision.finding_id == RESULT_PENDING_ID,
        )
    )
    if (
        no_findings_decision is not None
        and no_findings_decision.snapshot_hash != result.snapshot_hash
    ):
        raise ValueError("human confirmation does not match the published result snapshot")
    adopted_references: set[str] = set()
    configured_bindings = 0
    for finding in result.content.get("findings", []):
        for reference in finding.get("legal_references", []):
            if reference.get("adoption_status") == "project_adopted":
                identity = reference.get("evidence_id") or reference.get("title")
                if identity is not None:
                    adopted_references.add(str(identity))
            if reference.get("rule_law_binding_id"):
                configured_bindings += 1
    adoption_policy = load_adoption_policy(ROOT)
    adoption_projection = (
        {
            "policy_id": adoption_policy.policy_id,
            "decision_ref": adoption_policy.decision_ref,
            "adopted_on": adoption_policy.adopted_on,
            "independent_legal_verification": False,
            "version_count": adoption_policy.version_count,
            "fragment_count": adoption_policy.fragment_count,
            "corpus_index_sha256": adoption_policy.corpus_index_sha256,
            "manifest_sha256": adoption_policy.manifest_sha256,
            "statement": adoption_policy.statement,
        }
        if adoption_policy is not None
        else None
    )
    model_content = model.content
    run = session.get(
        ReviewEngineRun,
        (
            principal.tenant_id,
            result.review_task_id,
            result.run_id,
        ),
    )
    if run is None or content_hash(run.snapshot) != result.snapshot_hash:
        raise ValueError("report runtime does not match its frozen result")
    runtime = _runtime_projection(session, run)
    retrieval_runtime = run.snapshot.get("runtime_provenance", {}).get("retrieval", {})
    related, related_hash = _related_analysis_context(session, principal, result, model_content)
    omitted_context = 0
    if related is not None:
        omitted = related.get("omitted_for_input_capacity", {})
        if not isinstance(omitted, dict) or any(
            type(count) is not int or count < 0 for count in omitted.values()
        ):
            raise ValueError("report omitted-context counts are invalid")
        omitted_context = sum(omitted.values())
    return {
        "candidate_discovery_status": discovery_content.get("status", "unknown"),
        "candidate_count": len(discovery_content.get("candidates", [])),
        "skill_candidate_count": runtime["skill_candidate_count"],
        "model_candidate_count": runtime["model_candidate_count"],
        "model_execution_mode": runtime["execution_mode"],
        "model_calls": runtime["model_calls"],
        "model_input_tokens": runtime["input_tokens"],
        "model_output_tokens": runtime["output_tokens"],
        "model_cost_cny": runtime["estimated_cost_cny"],
        "vector_index_item_count": retrieval_runtime.get("vector_index_item_count", 0) or 0,
        "vector_source_item_count": retrieval_runtime.get("vector_source_item_count", 0) or 0,
        "model_context_capacity_omitted_excerpts": omitted_context,
        "skill_coverage": skill_coverage,
        "legal_framework_confirmed": framework_confirmed,
        "retrieval_status_counts": retrieval_status_counts,
        "retrieval_context_errors": context_error_counts,
        "retrieval_hit_count": retrieval_hit_count,
        "citable_legal_evidence_count": citable_count,
        "adopted_legal_reference_count": len(adopted_references),
        "configured_rule_law_binding_count": configured_bindings,
        "legal_adoption_policy": adoption_projection,
        "retrieval_algorithms": sorted(algorithms),
        "model_provider": model_content.get("provider", "unknown"),
        "model_name": model_content.get("model", "unknown"),
        "no_findings_confirmation": (
            no_findings_decision.decision if no_findings_decision is not None else None
        ),
        "source_artifact_hashes": {
            "candidate_discovery": discovery.content_hash,
            "legal_retrieval": retrieval.content_hash,
            "model_analysis": model.content_hash,
            "project_context": project_context.content_hash,
            **({"semantic_document_context": related_hash} if related_hash is not None else {}),
        },
    }


def resolve_review_finding_citations(
    session: Session,
    principal: Principal,
    *,
    review_task_id: str,
    run_id: str,
    finding_id: str,
) -> list[dict[str, Any]]:
    require_identity(session, principal)
    if principal.role not in {Role.REVIEWER, Role.AUDITOR}:
        audit(session, principal.tenant_id, principal.user_id, "review.citation_denied", finding_id)
        session.commit()
        raise PermissionError("review citation is not authorized")
    run = authorized_run(session, principal, review_task_id, run_id)
    if content_hash(run.snapshot) != run.snapshot_hash:
        raise ValueError("review input snapshot hash mismatch")
    artifact = session.scalar(
        select(ReviewArtifact).where(
            ReviewArtifact.tenant_id == principal.tenant_id,
            ReviewArtifact.review_task_id == review_task_id,
            ReviewArtifact.run_id == run_id,
            ReviewArtifact.kind == "merged_findings",
        )
    )
    if artifact is None or content_hash(artifact.content) != artifact.content_hash:
        raise ValueError("review findings artifact is unavailable or changed")
    finding = next(
        (
            item
            for item in artifact.content.get("findings", [])
            if item.get("finding_id") == finding_id
        ),
        None,
    )
    if finding is None:
        raise LookupError("finding is unavailable")
    locations = _resolve_source_locations(
        session,
        principal,
        project_id=run.project_id,
        review_task_id=review_task_id,
        run_id=run_id,
        snapshot=run.snapshot,
        finding=finding,
    )
    audit(session, principal.tenant_id, principal.user_id, "review.citation_resolved", finding_id)
    session.commit()
    return locations


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
    project_context = _verified_run_artifact(session, principal, result, "project_context")
    if project_context.content.get("context_sha256") != run.snapshot.get("project_context_sha256"):
        raise ValueError("frozen project context does not match the review input snapshot")
    frozen_project_name = project_context.content.get("context", {}).get("name")
    scope = _assessment_scope(session, principal, result, project_context=project_context)
    scope["product_execution"] = _product_execution(session, principal, result)
    return {
        "schema_version": "task0010-report.v3",
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
        "assessment_scope": scope,
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


def list_reports(session: Session, principal: Principal, result_id: str) -> list[ReviewReport]:
    require_identity(session, principal)
    if principal.role not in {Role.REVIEWER, Role.AUDITOR}:
        audit(session, principal.tenant_id, principal.user_id, "report.list_denied", result_id)
        session.commit()
        raise PermissionError("report list is not authorized")
    result = session.get(ReviewResult, (principal.tenant_id, result_id))
    if result is None:
        audit(session, principal.tenant_id, principal.user_id, "report.not_visible", result_id)
        session.commit()
        raise LookupError("report result unavailable")
    find_project(session, principal, result.content["project_id"])
    rows = list(
        session.scalars(
            select(ReviewReport)
            .where(
                ReviewReport.tenant_id == principal.tenant_id,
                ReviewReport.result_id == result_id,
            )
            .order_by(ReviewReport.created_at, ReviewReport.report_id)
        )
    )
    audit(session, principal.tenant_id, principal.user_id, "report.listed", result_id)
    session.commit()
    return rows


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
