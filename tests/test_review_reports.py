"""TASK0010 report rendering must preserve published evidence and Chinese text."""

from datetime import datetime
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from pypdf import PdfReader

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.services.reporting import render_docx, render_pdf
from bidding_compliance.services.review_persistence import _decision_projection


def _report() -> dict[str, object]:
    return {
        "schema_version": "task0010-report.v1",
        "tenant_id": "tenant-test",
        "project_id": "project-test",
        "project_name": "中文项目",
        "review_task_id": "task-test",
        "run_id": "run-test",
        "result_id": "result-test",
        "snapshot_hash": "a" * 64,
        "report_id": "report-test",
        "template_version": "task0010-v1",
        "generated_at": "2026-10-14T00:00:00+00:00",
        "input_snapshot": {
            "documents": [
                {
                    "document_id": "doc-old-version",
                    "raw_source_sha256": "b" * 64,
                    "parse_version": 1,
                    "context_version": 1,
                }
            ]
        },
        "findings": [
            {
                "finding_id": "finding-test",
                "category": "qualification",
                "title": "注册地要求需复核",
                "description": "招标文件要求供应商在本市注册。",
                "severity": "medium",
                "evidence_status": "suspected",
                "review_status": "accepted",
                "recommendation": "核实要求与项目需求的关联。",
                "human_review": {
                    "reviewer_id": "reviewer-test",
                    "decided_at": "2026-10-14T00:00:00+00:00",
                    "reason": "请结合项目实际复核。",
                },
                "evidence": [],
                "citations": [
                    {
                        "document_id": "doc-old-version",
                        "raw_source_sha256": "b" * 64,
                        "parse_version": 1,
                        "section_id": "section-7",
                        "section_revision": 1,
                        "locator": "paragraph:7",
                        "page": None,
                        "coordinate_system": "ooxml",
                        "quote": "供应商必须在本市注册。",
                        "quote_sha256": "c" * 64,
                    }
                ],
            }
        ],
    }


def test_task0010_word_and_pdf_are_real_parseable_chinese_reports() -> None:
    report = _report()
    docx_bytes = render_docx(report)  # type: ignore[arg-type]
    pdf_bytes = render_pdf(report)  # type: ignore[arg-type]
    assert docx_bytes.startswith(b"PK")
    assert pdf_bytes.startswith(b"%PDF-")
    with ZipFile(BytesIO(docx_bytes)) as archive:
        assert "word/document.xml" in archive.namelist()
        xml = archive.read("word/document.xml").decode("utf-8")
        assert "注册地要求需复核" in xml
        assert "doc-old-version" in xml
        assert "suspected" in xml
        assert "confirmed" not in xml
    parsed_docx = Document(BytesIO(docx_bytes))
    assert any(
        "中文项目" in cell.text
        for table in parsed_docx.tables
        for row in table.rows
        for cell in row.cells
    )
    parsed_pdf = PdfReader(BytesIO(pdf_bytes))
    assert len(parsed_pdf.pages) >= 1
    pdf_text = "\n".join(page.extract_text() or "" for page in parsed_pdf.pages)
    assert "招标文件合规审查报告" in pdf_text
    assert "suspected" in pdf_text
    assert "confirmed" not in pdf_text


@pytest.mark.parametrize(
    ("action", "expected_status"),
    (("accept", "accepted"), ("modify", "modified"), ("reject", "rejected")),
)
def test_task0010_human_projection_keeps_evidence_status_separate(
    action: str, expected_status: str
) -> None:
    principal = Principal("tenant-test", "reviewer-test", "reviewer", Role.REVIEWER, "session")
    source = {
        "finding_id": "finding-test",
        "evidence_status": "insufficient_evidence",
        "review_status": "pending",
        "title": "候选风险",
        "evidence": [],
    }
    modifications = {"title": "修改后的候选风险"} if action == "modify" else None
    projected = _decision_projection(
        source,
        action,
        modifications,
        principal,
        "已阅读并接受记录。",
        datetime.fromisoformat("2026-10-14T00:00:00+00:00"),
    )
    assert projected["review_status"] == expected_status
    assert projected["evidence_status"] == "insufficient_evidence"
    assert projected["human_review"]["reason"] == "已阅读并接受记录。"
