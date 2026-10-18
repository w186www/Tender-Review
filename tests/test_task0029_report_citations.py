"""TASK-0029 report citations recheck bounded full-document context excerpts."""

import hashlib
from collections import deque
from types import SimpleNamespace

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.ingestion.schemas import Fragment
from bidding_compliance.persistence.models import DocumentSection, SectionRevision
from bidding_compliance.services import evidence_checker, reports
from bidding_compliance.services.evidence_checker import evidence_identity
from bidding_compliance.services.review_persistence import content_hash


def _fragment(text: str, locator: str, section: str) -> Fragment:
    return Fragment(
        locator=locator,
        coordinate_system="ooxml",
        kind="paragraph",
        section=section,
        text=text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        source="native",
    )


def test_related_context_is_rechecked_and_resolved_to_report_citation(monkeypatch):
    tenant_id = "tenant-a"
    project_id = "project-a"
    task_id = "task-a"
    run_id = "run-a"
    document_id = "document-a"
    document_sha = "a" * 64
    candidate_id = "b" * 64
    source = _fragment("技术需求应允许同等性能产品参与。", "paragraph:1", "技术需求")
    related = _fragment("品牌响应表仅列出指定型号。", "paragraph:2", "品牌响应表")
    source_row = SimpleNamespace(
        section_id="source-section", revision=1, automatic=source.model_dump()
    )
    related_row = SimpleNamespace(
        section_id="related-section", revision=1, automatic=related.model_dump()
    )
    sections = {
        "source-section": source_row,
        "related-section": related_row,
    }
    document = SimpleNamespace(
        document_id=document_id,
        project_id=project_id,
        status="ready",
        sha256=document_sha,
        parse_version=1,
        context_version=1,
    )

    class RelatedSession:
        def scalars(self, _statement):
            return iter([related_row])

        def get(self, model, key):
            if model is SectionRevision:
                return None
            if model is DocumentSection:
                return sections.get(key[-1])
            raise AssertionError(model)

    session = RelatedSession()
    principal = Principal(tenant_id, "reviewer-a", "reviewer", Role.REVIEWER, "session-a")
    monkeypatch.setattr(evidence_checker.documents, "find_document", lambda *_: document)
    related_identity = {
        "document_id": document_id,
        "document_sha256": document_sha,
        "section_id": "related-section",
        "section_revision": 1,
        "locator": related.locator,
        "page": None,
        "quote_sha256": related.text_sha256,
    }
    evidence_item = {
        "evidence_id": evidence_identity(related_identity),
        **related_identity,
        "title": "全文交叉核对原文（上下文，不单独风险结论）",
        "quote": related.text,
    }
    verified = evidence_checker.verify_related_document_evidence(
        session,
        principal,
        project_id=project_id,
        item=evidence_item,
        expected_documents={
            document_id: {
                "raw_source_sha256": document_sha,
                "parse_version": 1,
                "context_version": 1,
            }
        },
    )
    assert verified is not None
    assert verified["quote"] == related.text
    assert (
        evidence_checker.verify_related_document_evidence(
            session,
            principal,
            project_id=project_id,
            item={**evidence_item, "quote": "被替换的文本"},
            expected_documents={
                document_id: {
                    "raw_source_sha256": document_sha,
                    "parse_version": 1,
                    "context_version": 1,
                }
            },
        )
        is None
    )

    source_excerpt = {
        "document_id": document_id,
        "document_sha256": document_sha,
        "section_id": "source-section",
        "section_revision": 1,
        "locator": source.locator,
        "page": None,
        "bbox": None,
        "coordinate_system": "ooxml",
        "quote": source.text,
        "quote_sha256": source.text_sha256,
    }
    discovery = {
        "candidates": [{"candidate_id": candidate_id, "source_excerpts": [source_excerpt]}]
    }
    artifact = SimpleNamespace(
        content=discovery,
        content_hash=content_hash(discovery),
    )

    class ReportSession(RelatedSession):
        def __init__(self):
            self.scalar_values = deque([artifact, document, document])

        def scalar(self, _statement):
            return self.scalar_values.popleft()

    finding_id = hashlib.sha256(
        f"{tenant_id}:{task_id}:{run_id}:{candidate_id}".encode()
    ).hexdigest()
    locations = reports._resolve_source_locations(
        ReportSession(),
        principal,
        project_id=project_id,
        review_task_id=task_id,
        run_id=run_id,
        snapshot={
            "input_snapshot": {
                "documents": [
                    {
                        "document_id": document_id,
                        "raw_source_sha256": document_sha,
                        "parse_version": 1,
                        "context_version": 1,
                    }
                ]
            }
        },
        finding={
            "finding_id": finding_id,
            "evidence": [
                {
                    "kind": "document",
                    "source_hash": document_sha,
                    "page": None,
                    "locator": source.locator,
                    "quote": source.text,
                },
                verified,
            ],
        },
    )
    assert [item["quote"] for item in locations] == [source.text, related.text]
    assert locations[1]["section_id"] == "related-section"
    assert locations[1]["raw_source_sha256"] == document_sha
