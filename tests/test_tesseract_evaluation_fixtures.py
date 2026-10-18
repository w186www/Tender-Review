"""OCR evaluation inputs are generated, scanned PDFs without embedded source text."""

import hashlib

from evaluate_tesseract_ocr import (
    make_fixture_pdf,
    make_policy,
    ordered_ocr_page_text,
    select_font,
)
from pypdf import PdfReader

from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.quality import quality_issues
from bidding_compliance.ingestion.schemas import Fragment, OCRRuntimeIdentity


def test_synthetic_scanned_fixtures_cover_layout_and_low_quality(tmp_path):
    font = select_font(None)
    scanned, metadata = make_fixture_pdf(tmp_path, font)
    blank, blank_metadata = make_fixture_pdf(tmp_path, font, blank=True)

    scanned_reader = PdfReader(scanned, strict=True)
    blank_reader = PdfReader(blank, strict=True)
    assert len(scanned_reader.pages) == metadata["page_count"] == 3
    assert len(blank_reader.pages) == blank_metadata["page_count"] == 1
    assert all(not page.extract_text() for page in scanned_reader.pages)
    assert all(not page.extract_text() for page in blank_reader.pages)
    assert "125600.00" in metadata["critical_tokens"]
    assert len(metadata["table_cells"]) >= 12
    assert metadata["repeat_text"] == "资格审查合格后进入详细评审。"
    assert metadata["repeat_text_occurrences_expected"] == 2


def test_ocr_runtime_identity_is_stable_and_hash_bound():
    values = {
        "engine_version": "tesseract 5.3.0",
        "model_ids": ("chi_sim", "eng"),
        "model_sha256": {"chi_sim": "a" * 64, "eng": "b" * 64},
        "parameters": {"language": "chi_sim+eng", "omp_thread_limit": 1},
    }
    first = OCRRuntimeIdentity.create(**values)
    second = OCRRuntimeIdentity.create(**values)
    round_trip = OCRRuntimeIdentity.create(**first.model_dump(mode="json"))
    assert first == second
    assert first == round_trip


def test_ocr_evaluation_uses_the_approved_ingestion_policy_unchanged():
    assert make_policy() == load_policy()


def test_ocr_text_reconstruction_preserves_visual_lines_and_columns():
    words = ("甲", "乙", "丙", "丁", "戊", "己")
    positions = ((0, 10), (20, 11), (40, 12), (140, 10), (160, 11), (180, 12))
    fragments = [
        Fragment(
            locator=f"pdf/page/1/ocr/word/{index}",
            page=1,
            bbox=[float(x), float(y), float(x + 10), float(y + 10)],
            coordinate_system="pdf_points",
            kind="ocr",
            text=word,
            text_sha256=hashlib.sha256(word.encode()).hexdigest(),
            source="ocr",
        )
        for index, (word, (x, y)) in enumerate(zip(words, positions, strict=True), 1)
    ]
    observed, _ = ordered_ocr_page_text(fragments)
    assert observed == "甲乙丙丁戊己"


def _ocr_fragment(text, *, page=1, table=None, row=None, column=None, confidence=0.95):
    return Fragment(
        locator=f"pdf/page/{page}/ocr/{table}-{row}-{column}/{hashlib.sha256(text.encode()).hexdigest()[:8]}",
        page=page,
        bbox=[0, 0, 100, 100],
        coordinate_system="pdf_points",
        kind="table_cell" if table is not None else "ocr",
        section="synthetic",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source="ocr",
        confidence=confidence,
        table=table,
        row=row,
        column=column,
    )


def test_known_synthetic_ocr_failure_classes_are_routed_to_manual_review():
    """The TASK-0018 fixture's known weak areas become explicit quality signals."""
    repeat = "资格审查合格后进入详细评审。"
    fragments = [
        _ocr_fragment("投标报价 125600.00 元", confidence=0.70),
        _ocr_fragment("重复页眉", page=1),
        _ocr_fragment(repeat, page=1),
        _ocr_fragment("资格", table=1, row=0, column=0),
        _ocr_fragment("要求", table=1, row=0, column=1),
        _ocr_fragment("备注", table=1, row=0, column=2),
        _ocr_fragment("仅剩一格", table=1, row=1, column=0),
        _ocr_fragment(repeat, page=2),
    ]
    issues = set(quality_issues(fragments, load_policy()))
    assert {"LOW_CONFIDENCE_NUMERIC", "DUPLICATE_TEXT", "TABLE_STRUCTURE_GAP"} <= issues
