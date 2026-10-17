"""TASK-0029 U06 structural quality signals beyond the average OCR confidence."""

from __future__ import annotations

import hashlib

from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.quality import quality, quality_issues
from bidding_compliance.ingestion.schemas import Fragment


def fragment(
    text: str,
    *,
    page: int = 1,
    kind: str = "ocr",
    source: str = "ocr",
    confidence: float | None = 0.95,
    table: int | None = None,
    row: int | None = None,
    column: int | None = None,
) -> Fragment:
    return Fragment(
        locator=f"pdf/page/{page}/{kind}/{table}-{row}-{column}/{hashlib.sha256(text.encode()).hexdigest()[:8]}",
        page=page,
        bbox=[0, 0, 100, 100],
        coordinate_system="pdf_points",
        kind=kind,
        section="synthetic",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source=source,
        confidence=confidence,
        table=table,
        row=row,
        column=column,
    )


def test_clean_multi_page_document_passes():
    items = [
        fragment("第一章 资格审查要求，投标人应当具备独立法人资格。", page=1),
        fragment("第二章 技术要求，设备应满足采购文件列明的参数。", page=2),
    ]
    assert quality_issues(items, load_policy()) == []
    assert quality(items, load_policy())


def test_duplicate_text_is_flagged_even_when_average_confidence_is_high():
    repeated = "投标人应当按照采购文件要求提交资格审查材料并保证内容真实有效。"
    items = [fragment(repeated, page=1), fragment(repeated, page=1)]
    assert "DUPLICATE_TEXT" in quality_issues(items, load_policy())


def test_missing_page_coverage_is_flagged():
    items = [
        fragment("第一页有正文内容，包含资格条件和评审办法。", page=1),
        fragment("第三页有正文内容，但第二页没有产生任何片段。", page=3),
    ]
    issues = quality_issues(items, load_policy())
    assert "PAGE_COVERAGE_GAP" in issues


def test_reading_order_regression_is_flagged():
    items = [
        fragment("第二页内容先出现。", page=2),
        fragment("第一页内容后出现，顺序异常。", page=1),
    ]
    assert "READING_ORDER_GAP" in quality_issues(items, load_policy())


def test_table_row_width_gap_is_flagged():
    items = [
        fragment("资格", page=1, kind="table_cell", table=1, row=0, column=0),
        fragment("要求", page=1, kind="table_cell", table=1, row=0, column=1),
        fragment("备注", page=1, kind="table_cell", table=1, row=0, column=2),
        fragment("仅剩一格", page=1, kind="table_cell", table=1, row=1, column=0),
    ]
    assert "TABLE_STRUCTURE_GAP" in quality_issues(items, load_policy())


def test_low_confidence_numeric_ocr_is_flagged_beyond_the_average():
    items = [
        fragment("投标报价为 125600.00 元。", page=1, confidence=0.70),
        fragment("投标人应当提交完整的资格审查材料。", page=1, confidence=0.95),
    ]
    issues = quality_issues(items, load_policy())
    assert "LOW_CONFIDENCE_NUMERIC" in issues
    # The old average-only gate would have passed this document (0.825 >= 0.65).
    assert (0.70 + 0.95) / 2 >= load_policy().min_ocr_confidence


def test_invalid_calendar_date_is_flagged_and_valid_date_is_not():
    invalid = [fragment("投标截止时间为2026年2月30日。", page=1)]
    valid = [fragment("投标截止时间为2026年2月28日。", page=1)]
    assert "INVALID_DATE" in quality_issues(invalid, load_policy())
    assert "INVALID_DATE" not in quality_issues(valid, load_policy())


def test_existing_low_quality_failures_remain_failures():
    assert not quality([fragment("短", page=1)], load_policy())
    assert not quality([fragment("(cid:12)" * 20, page=1)], load_policy())
    assert not quality([fragment("正常文字", page=1, confidence=0.1)], load_policy())
