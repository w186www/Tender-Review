"""D1 first-version support scope: formats, size, pages and OCR page limits."""

from __future__ import annotations

import io

import pytest
from docx import Document as WordDocument
from PIL import Image
from reportlab.pdfgen import canvas

from bidding_compliance.ingestion.parser import parse
from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.ports import IngestionError


class RecognizedOCR:
    def recognize(self, image):
        return [
            {
                "text": "合成扫描件资格要求：投标人应当具备相应资质。",
                "confidence": 0.99,
                "bbox": [0, 0, 100, 20],
            }
        ]


class EmptyOCR:
    def recognize(self, image):
        return []


def pdf_pages(count: int, text: str = "") -> bytes:
    stream = io.BytesIO()
    document = canvas.Canvas(stream)
    for index in range(count):
        if text:
            document.drawString(50, 700, f"{text} 第{index + 1}页")
        document.showPage()
    document.save()
    return stream.getvalue()


def docx_payload() -> bytes:
    stream = io.BytesIO()
    document = WordDocument()
    document.add_paragraph("政府采购工程招标文件：投标人资格要求与合同条款合成样本。")
    document.save(stream)
    return stream.getvalue()


def image_payload(format: str) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (640, 480), "white").save(stream, format=format)
    return stream.getvalue()


def test_policy_matches_the_approved_first_version_scope():
    policy = load_policy()
    assert policy.max_upload_bytes == 10 * 1024 * 1024
    assert policy.max_pages == 300
    assert policy.max_ocr_pages == 30


@pytest.mark.parametrize(
    ("format", "factory"),
    [
        ("pdf", lambda: pdf_pages(1, "合成招标文件资格要求")),
        ("docx", docx_payload),
        ("png", lambda: image_payload("PNG")),
        ("jpeg", lambda: image_payload("JPEG")),
    ],
    ids=["pdf", "docx", "png", "jpeg"],
)
def test_supported_formats_are_parsed(format, factory):
    parsed = parse(factory(), format, load_policy(), ocr=RecognizedOCR())
    assert parsed.format == format
    assert parsed.fragments
    assert parsed.quality == "passed"


def test_over_ten_mebibytes_is_rejected_before_parsing():
    with pytest.raises(IngestionError, match="SIZE_LIMIT"):
        parse(b"x" * (10 * 1024 * 1024 + 1), "pdf", load_policy(), ocr=EmptyOCR())


def test_more_than_300_pages_is_rejected():
    with pytest.raises(IngestionError, match="PAGE_LIMIT"):
        parse(pdf_pages(301, "合成招标文件"), "pdf", load_policy(), ocr=EmptyOCR())


def test_more_than_30_ocr_pages_is_rejected():
    with pytest.raises(IngestionError, match="OCR_LIMIT"):
        parse(pdf_pages(31), "pdf", load_policy(), ocr=RecognizedOCR())


def test_unreliable_text_requires_manual_review_instead_of_passing():
    parsed = parse(pdf_pages(1, "短"), "pdf", load_policy(), ocr=EmptyOCR())
    assert parsed.quality == "requires_review"
    assert "LOW_QUALITY" in parsed.issues


def test_image_without_recognized_text_requires_manual_review():
    parsed = parse(image_payload("PNG"), "png", load_policy(), ocr=EmptyOCR())
    assert parsed.quality == "requires_review"
    assert "LOW_QUALITY" in parsed.issues
