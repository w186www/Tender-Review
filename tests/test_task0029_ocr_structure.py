"""TASK-0029 U06: preserve word evidence while reconstructing OCR line paragraphs."""

from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from bidding_compliance.ingestion.parser import check_limits, ocr_fragments
from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.ports import IngestionError
from bidding_compliance.ingestion.quality import quality_issues
from bidding_compliance.ingestion.schemas import Fragment, OCRWordRecord


def word(
    text: str,
    confidence: float,
    *,
    word_num: int,
    line_num: int = 1,
) -> OCRWordRecord:
    return OCRWordRecord(
        text=text,
        confidence=confidence,
        bbox=[float(word_num * 10), 10.0, float(word_num * 10 + 8), 20.0],
        level=5,
        page_num=1,
        tsv_page_num=1,
        block_num=1,
        par_num=1,
        line_num=line_num,
        word_num=word_num,
        raw_left=word_num * 10,
        raw_top=10,
        raw_width=8,
        raw_height=10,
        raw_confidence=confidence * 100,
    )


class TSVWords:
    def recognize(self, _image: Image.Image) -> list[dict[str, object]]:
        return [
            {
                "text": "第1条",
                "confidence": 0.96,
                "bbox": [10, 20, 50, 40],
                "level": 5,
                "page_num": 1,
                "block_num": 2,
                "par_num": 3,
                "line_num": 1,
                "word_num": 1,
                "raw_left": 10,
                "raw_top": 20,
                "raw_width": 40,
                "raw_height": 20,
                "raw_confidence": 96.0,
            },
            {
                "text": "资格条件",
                "confidence": 0.92,
                "bbox": [55, 20, 100, 40],
                "level": 5,
                "page_num": 1,
                "block_num": 2,
                "par_num": 3,
                "line_num": 1,
                "word_num": 2,
                "raw_left": 55,
                "raw_top": 20,
                "raw_width": 45,
                "raw_height": 20,
                "raw_confidence": 92.0,
            },
            {
                "text": "第二行",
                "confidence": 0.94,
                "bbox": [10, 45, 40, 65],
                "level": 5,
                "page_num": 1,
                "block_num": 2,
                "par_num": 3,
                "line_num": 2,
                "word_num": 1,
                "raw_left": 10,
                "raw_top": 45,
                "raw_width": 30,
                "raw_height": 20,
                "raw_confidence": 94.0,
            },
        ]


def test_ocr_words_rebuild_paragraphs_and_retain_tsv_geometry():
    fragments = ocr_fragments(
        Image.new("RGB", (100, 100)),
        page=7,
        coordinate="pdf_points",
        scale=2,
        ocr=TSVWords(),
        locator="pdf/page/7/ocr",
    )

    assert len(fragments) == 1
    fragment = fragments[0]
    assert fragment.text == "第1条资格条件\n第二行"
    assert fragment.text_sha256 == hashlib.sha256(fragment.text.encode()).hexdigest()
    assert fragment.locator == "pdf/page/7/ocr/block/2/paragraph/3/part/1"
    assert fragment.page == 7
    assert fragment.bbox == [5.0, 10.0, 50.0, 32.5]
    assert [record.text for record in fragment.ocr_words] == ["第1条", "资格条件", "第二行"]
    assert [record.line_num for record in fragment.ocr_words] == [1, 1, 2]
    assert [record.page_num for record in fragment.ocr_words] == [7, 7, 7]
    assert fragment.ocr_words[0].tsv_page_num == 1
    assert fragment.ocr_words[0].bbox == [5.0, 10.0, 25.0, 20.0]
    assert fragment.ocr_words[0].raw_left == 10
    assert fragment.ocr_words[0].raw_confidence == 96.0


def test_numeric_confidence_uses_the_numeric_word_not_paragraph_average():
    items = [
        fragment("正文含金额125600.00元", confidence=0.825).model_copy(
            # A weak nonnumeric word must not combine with a strong amount to raise a false alarm.
            update={
                "ocr_words": [
                    word("正文", 0.70, word_num=1),
                    word("125600.00", 0.95, word_num=2),
                    word("元", 0.85, word_num=3),
                ]
            },
        )
    ]
    assert "LOW_CONFIDENCE_NUMERIC" not in quality_issues(items, load_policy())

    items[0] = items[0].model_copy(
        update={
            "ocr_words": [
                word("正文", 0.98, word_num=1),
                word("125600.00", 0.70, word_num=2),
                word("元", 0.98, word_num=3),
            ]
        }
    )
    assert sum(record.confidence for record in items[0].ocr_words) / 3 > 0.8
    assert "LOW_CONFIDENCE_NUMERIC" in quality_issues(items, load_policy())


def test_low_confidence_toc_section_numbers_do_not_trigger_numeric_gate():
    items = [
        ocr_fragment("目录", page=1, paragraph=1, words=[("目录", 0.99)]),
        *[
            toc_entry(
                page=1,
                paragraph=index + 2,
                number=f"{index}.",
                page_reference=str(index + 10),
                prefix_confidence=0.45,
            )
            for index in range(1, 4)
        ],
        *[
            toc_entry(
                page=2,
                paragraph=index + 1,
                number=f"{index + 3}.",
                page_reference=str(index + 20),
                prefix_confidence=0.45,
            )
            for index in range(6)
        ],
    ]

    assert "LOW_CONFIDENCE_NUMERIC" not in quality_issues(items, load_policy())


def test_repeated_toc_rows_are_recognized_when_heading_is_not_ocr_readable():
    items = [
        *[
            toc_entry(
                page=page,
                paragraph=index + 1,
                number=f"{index + (page - 1) * 12}.",
                page_reference=str(index + 10 + (page - 1) * 12),
                prefix_confidence=0.45,
            )
            for page in (1, 2)
            for index in range(12)
        ],
    ]

    assert "LOW_CONFIDENCE_NUMERIC" not in quality_issues(items, load_policy())


def test_repeated_numeric_table_rows_without_numbering_punctuation_still_gate():
    items = [
        toc_entry(
            page=page,
            paragraph=index + 1,
            number=str(index + (page - 1) * 12 + 1),
            page_reference=str(index + 10 + (page - 1) * 12),
            prefix_confidence=0.45,
        )
        for page in (1, 2)
        for index in range(12)
    ]

    assert "LOW_CONFIDENCE_NUMERIC" in quality_issues(items, load_policy())


def test_toc_exemption_does_not_cover_low_confidence_body_amount():
    items = [
        ocr_fragment("目录", page=1, paragraph=1, words=[("目录", 0.99)]),
        *[
            toc_entry(
                page=1,
                paragraph=index + 2,
                number=f"{index}.",
                page_reference=str(index + 10),
                prefix_confidence=0.45,
            )
            for index in range(1, 4)
        ],
        *[
            toc_entry(
                page=2,
                paragraph=index + 1,
                number=f"{index + 3}.",
                page_reference=str(index + 20),
                prefix_confidence=0.45,
            )
            for index in range(6)
        ],
        ocr_fragment(
            "保证金 5000 元",
            page=3,
            paragraph=1,
            words=[("保证金", 0.99), ("5000", 0.45), ("元", 0.99)],
        ),
    ]

    assert "LOW_CONFIDENCE_NUMERIC" in quality_issues(items, load_policy())


def test_ocr_word_records_still_count_toward_the_existing_fragment_budget():
    item = fragment("合并后的识别段落", confidence=0.9).model_copy(
        update={"ocr_words": [word("甲", 0.9, word_num=1), word("乙", 0.9, word_num=2)]},
    )
    policy = load_policy().model_copy(update={"max_fragments": 1})
    with pytest.raises(IngestionError, match="TEXT_LIMIT"):
        check_limits([item], policy)


def fragment(text: str, *, confidence: float) -> Fragment:
    return Fragment(
        locator="pdf/page/1/ocr/block/1/paragraph/1/part/1",
        page=1,
        bbox=[0, 0, 100, 30],
        coordinate_system="pdf_points",
        kind="ocr",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source="ocr",
        confidence=confidence,
    )


def ocr_fragment(
    text: str,
    *,
    page: int,
    paragraph: int,
    words: list[tuple[str, float]],
) -> Fragment:
    return Fragment(
        locator=f"pdf/page/{page}/ocr/block/1/paragraph/{paragraph}/part/1",
        page=page,
        bbox=[0, 0, 100, 30],
        coordinate_system="pdf_points",
        kind="ocr",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source="ocr",
        confidence=0.95,
        ocr_words=[
            word(text, confidence, word_num=index + 1).model_copy(
                update={"page_num": page, "tsv_page_num": page, "par_num": paragraph}
            )
            for index, (text, confidence) in enumerate(words)
        ],
    )


def toc_entry(
    *,
    page: int,
    paragraph: int,
    number: str,
    page_reference: str,
    prefix_confidence: float = 0.99,
) -> Fragment:
    words = [
        (number, prefix_confidence),
        ("招标文件", 0.99),
        (page_reference, 0.99),
    ]
    return ocr_fragment(
        " ".join(text for text, _ in words),
        page=page,
        paragraph=paragraph,
        words=words,
    )
