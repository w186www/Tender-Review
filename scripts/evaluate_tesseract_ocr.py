"""Measure the real, restricted Tesseract parser using generated synthetic scans."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.ports import IngestionError
from bidding_compliance.ingestion.sandbox import DockerParser
from bidding_compliance.ingestion.schemas import Fragment, IngestionPolicy

ROOT = Path(__file__).resolve().parents[1]
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
IMAGE_WIDTH = 1400
IMAGE_HEIGHT = 1980
SCALE = IMAGE_WIDTH / PAGE_WIDTH
FONT_CANDIDATES = (
    Path(os.environ.get("TASK0018_CJK_FONT", "C:/Windows/Fonts/simsun.ttc")),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, 1):
        current = [i]
        for j, char_right in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (char_left != char_right),
                )
            )
        previous = current
    return previous[-1]


def select_font(path: Path | None) -> Path:
    for candidate in (path, *FONT_CANDIDATES):
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "No CJK font found. Install a licensed local CJK font or set TASK0018_CJK_FONT."
    )


def _draw_page(
    font: ImageFont.FreeTypeFont, lines: list[tuple[int, int, str]], *, blank=False
) -> Image.Image:
    image = Image.new("L", (IMAGE_WIDTH, IMAGE_HEIGHT), 255)
    if not blank:
        draw = ImageDraw.Draw(image)
        for x, y, text in lines:
            draw.text((x, y), text, font=font, fill=0)
    return image


def make_fixture_pdf(
    folder: Path, font_path: Path, *, blank: bool = False
) -> tuple[Path, dict[str, object]]:
    folder.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(font_path), 38)
    pages = [
        _draw_page(
            font,
            [
                (100, 100, "投标文件评审要求"),
                (100, 210, "第一章 资格审查"),
                (100, 310, "投标人须提交营业执照。"),
                (100, 400, "并提供有效资质证书。"),
                (100, 490, "投标保证金：5000元。"),
                (100, 580, "到账日期：2026年11月1日。"),
                (100, 670, "最高限价：125600.00元。"),
                (100, 760, "第二十六条资格审查合格。"),
                (750, 210, "第二章 商务评审"),
                (750, 310, "服务期限：90日历天。"),
                (750, 420, "投标有效期：120日。"),
                (750, 530, "签约后10日内提交保证金。"),
                (750, 640, "本页为双栏版式。"),
            ],
        ),
        _draw_page(
            font,
            [
                (100, 100, "评审因素与关键数值表"),
                (100, 260, "条款号       项目名称       金额(元)       最低得分"),
                (100, 390, "第一条       履约保证金     5000           5"),
                (100, 520, "第二条       最高限价       125600.00      10"),
                (100, 650, "第三条       服务期限       90日           8"),
                (100, 780, "合计          三项           130600.00      23"),
            ],
        ),
        _draw_page(
            font,
            [
                (100, 230, "重复条款：资格审查合格后进入详细评审。"),
                (100, 350, "第十七条 递交时间不得晚于2026年11月1日。"),
                (100, 1080, "重复条款：资格审查合格后进入详细评审。"),
                (100, 1200, "第十八条 保证金数额为5000元整。"),
            ],
        ),
    ]
    if blank:
        pages = [_draw_page(font, [], blank=True)]
    pdf_path = folder / ("low-quality-blank.pdf" if blank else "synthetic-scanned-tender.pdf")
    temp_images: list[Path] = []
    writer = canvas.Canvas(str(pdf_path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT), pageCompression=1)
    for index, image in enumerate(pages, 1):
        image_path = folder / f"page-{index}.png"
        image.save(image_path, format="PNG", optimize=False)
        temp_images.append(image_path)
        writer.drawImage(ImageReader(str(image_path)), 0, 0, width=PAGE_WIDTH, height=PAGE_HEIGHT)
        writer.showPage()
    writer.save()
    metadata: dict[str, object] = {
        "fixture_type": "blank_low_quality"
        if blank
        else "multi_column_table_numbers_repeated_text",
        "font_file_name": font_path.name,
        "font_sha256": sha256(font_path.read_bytes()),
        "page_count": len(pages),
        "pdf_sha256": sha256(pdf_path.read_bytes()),
        "ground_truth": []
        if blank
        else [
            (
                "投标文件评审要求第一章资格审查投标人须提交营业执照。并提供有效资质证书。"
                "投标保证金：5000元。到账日期：2026年11月1日。最高限价：125600.00元。"
                "第二十六条资格审查合格。第二章商务评审服务期限：90日历天。"
                "投标有效期：120日。签约后10日内提交保证金。本页为双栏版式。"
            ),
            (
                "评审因素与关键数值表条款号项目名称金额(元)最低得分第一条履约保证金5000 5"
                "第二条最高限价125600.00 10第三条服务期限90日 8合计三项130600.00 23"
            ),
            "重复条款：资格审查合格后进入详细评审。第十七条递交时间不得晚于2026年11月1日。重复条款：资格审查合格后进入详细评审。第十八条保证金数额为5000元整。",
        ],
        "critical_tokens": [
            "5000元",
            "2026年11月1日",
            "125600.00",
            "第二十六条",
            "第十七条",
            "第十八条",
        ],
        "table_cells": [
            "第一条",
            "履约保证金",
            "5000",
            "5",
            "第二条",
            "最高限价",
            "125600.00",
            "10",
            "第三条",
            "服务期限",
            "90日",
            "8",
            "130600.00",
            "23",
        ],
        "repeat_text": "资格审查合格后进入详细评审。",
        "repeat_text_occurrences_expected": 2,
    }
    return pdf_path, metadata


def make_policy() -> IngestionPolicy:
    """Use the checked-in ingestion policy; the evaluator never weakens its gates."""
    return load_policy()


def ocr_line_groups(fragments: list[Fragment]) -> list[list[Fragment]]:
    """Reassemble word boxes into visual lines without sorting boxes as characters."""
    lines: list[list[Fragment]] = []
    for fragment in sorted(
        fragments,
        key=lambda item: (
            (item.bbox[1] + item.bbox[3]) / 2 if item.bbox else 0,
            item.bbox[0] if item.bbox else 0,
        ),
    ):
        if fragment.bbox is None:
            continue
        center_y = (fragment.bbox[1] + fragment.bbox[3]) / 2
        matching = next(
            (
                line
                for line in reversed(lines)
                if line[0].bbox is not None
                and abs(center_y - (line[0].bbox[1] + line[0].bbox[3]) / 2) <= 10
            ),
            None,
        )
        if matching is None:
            lines.append([fragment])
        else:
            matching.append(fragment)
    return [
        sorted(line, key=lambda item: item.bbox[0] if item.bbox else 0) for line in lines
    ]


def ordered_ocr_page_text(fragments: list[Fragment]) -> tuple[str, list[list[Fragment]]]:
    """Order a page row-wise, or column-wise when a clear gutter separates columns."""
    usable = [item for item in fragments if item.text and item.bbox is not None]
    centers = sorted(
        (
            ((item.bbox[0] + item.bbox[2]) / 2, item)
            for item in usable
            if item.bbox is not None
        ),
        key=lambda pair: pair[0],
    )
    gaps = [
        (centers[index + 1][0] - centers[index][0], index + 1)
        for index in range(len(centers) - 1)
    ]
    columns: list[list[Fragment]] = [usable]
    if gaps:
        gap, split = max(gaps, key=lambda item: item[0])
        if gap >= 80 and split >= 3 and len(centers) - split >= 3:
            left = [item for _, item in centers[:split]]
            right = [item for _, item in centers[split:]]
            columns = [left, right]
    groups = [line for column in columns for line in ocr_line_groups(column)]
    return "".join(item.text for line in groups for item in line), groups


def evaluate(parser: DockerParser, pdf: Path, metadata: dict[str, object]) -> dict[str, object]:
    started = time.perf_counter()
    error_code = None
    try:
        parsed, metrics = parser.parse_with_metrics(pdf.read_bytes(), "pdf", make_policy())
    except IngestionError as exc:
        parsed = None
        metrics = exc.metrics
        error_code = exc.code
    elapsed = (time.perf_counter() - started) * 1000
    if parsed is None:
        return {
            "fixture_type": metadata["fixture_type"],
            "pdf_sha256": metadata["pdf_sha256"],
            "error": error_code,
            "wall_latency_ms": elapsed,
            "parser_metrics": metrics.model_dump(mode="json") if metrics else None,
            "failed_closed": True,
        }
    valid_locators = [
        fragment.page is not None
        and fragment.bbox is not None
        and fragment.coordinate_system == "pdf_points"
        and fragment.locator.startswith(f"pdf/page/{fragment.page}/")
        and fragment.bbox[0] <= fragment.bbox[2]
        and fragment.bbox[1] <= fragment.bbox[3]
        and fragment.bbox[2] <= PAGE_WIDTH + 1
        and fragment.bbox[3] <= PAGE_HEIGHT + 1
        for fragment in parsed.fragments
        if fragment.source == "ocr" and fragment.text
    ]
    page_lines = {
        page: ordered_ocr_page_text(
            [
                item
                for item in parsed.fragments
                if item.page == page and item.source == "ocr"
            ]
        )[1]
        for page in range(1, int(metadata["page_count"]) + 1)
    }
    page_text = {
        page: normalized("".join(item.text for line in lines for item in line))
        for page, lines in page_lines.items()
    }
    truth = metadata["ground_truth"]
    cer = None
    critical = {}
    table = {}
    repeat_count = None
    repeat_y_positions: list[float] = []
    if truth:
        expected = "".join(normalized(str(line)) for line in truth)
        observed = "".join(page_text.values())
        cer = edit_distance(expected, observed) / max(1, len(expected))
        observed_all = "".join(page_text.values())
        critical = {
            token: normalized(token) in observed_all for token in metadata["critical_tokens"]
        }
        table = {cell: normalized(cell) in page_text[2] for cell in metadata["table_cells"]}
        repeated = normalized(str(metadata["repeat_text"]))
        for line in page_lines[3]:
            if repeated in normalized("".join(item.text for item in line)):
                repeat_y_positions.append(round(line[0].bbox[1], 2))
        repeat_count = len(repeat_y_positions)
    else:
        expected = ""
        critical = {}
        table = {}
    expected_pages = {
        "第二十六条": 1,
        "第一条": 2,
        "第二条": 2,
        "第三条": 2,
        "第十七条": 3,
        "第十八条": 3,
    }
    if not truth:
        expected_pages = {}
    marker_pages = {
        marker: page for marker, page in expected_pages.items() if marker in page_text.get(page, "")
    }
    return {
        "fixture_type": metadata["fixture_type"],
        "pdf_sha256": metadata["pdf_sha256"],
        "page_count": parsed.page_count,
        "ocr_fragment_count": sum(f.source == "ocr" and bool(f.text) for f in parsed.fragments),
        "quality": parsed.quality,
        "issues": parsed.issues,
        "character_error_rate": cer,
        "critical_tokens": {
            "correct": sum(critical.values()),
            "total": len(critical),
            "details": critical,
        },
        "table_cell_completeness": {
            "correct": sum(table.values()),
            "total": len(table),
            "details": table,
        },
        "page_marker_hits": marker_pages,
        "page_marker_total": len(expected_pages),
        "valid_page_locator_ratio": sum(valid_locators) / len(valid_locators)
        if valid_locators
        else 1.0,
        "mean_ocr_confidence": (
            sum(
                fragment.confidence or 0
                for fragment in parsed.fragments
                if fragment.source == "ocr"
            )
            / max(1, sum(fragment.source == "ocr" for fragment in parsed.fragments))
        ),
        "repeated_text_occurrences_located": repeat_count,
        "repeated_text_occurrences_expected": metadata.get(
            "repeat_text_occurrences_expected", 0
        )
        if truth
        else None,
        "repeated_text_y_positions_pdf_points": repeat_y_positions,
        "wall_latency_ms": elapsed,
        "parser_metrics": metrics.model_dump(mode="json") if metrics else None,
        "ocr_runtime": parsed.ocr_runtime.model_dump(mode="json") if parsed.ocr_runtime else None,
        "expected_low_quality_downgrade": metadata["fixture_type"] == "blank_low_quality",
        "low_quality_downgrade_observed": parsed.quality == "requires_review"
        if metadata["fixture_type"] == "blank_low_quality"
        else None,
        "synthetic_benchmark_alert": bool(
            cer is not None
            and (cer > 0.2 or (critical and sum(critical.values()) / len(critical) < 0.9))
        ),
        "failed_closed": False,
    }


def main() -> int:
    parser_cli = argparse.ArgumentParser()
    parser_cli.add_argument("--image", default=os.environ.get("PARSER_VERIFY_IMAGE"))
    parser_cli.add_argument("--font", type=Path)
    parser_cli.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evals/ocr/results/tesseract-baseline-20261015.json",
    )
    args = parser_cli.parse_args()
    if not args.image:
        raise SystemExit(
            "Set PARSER_VERIFY_IMAGE to the already-built immutable parser image digest."
        )
    if args.output.exists():
        raise SystemExit("Refusing to overwrite an existing OCR evaluation artifact.")
    font_path = select_font(args.font)
    image_digest = re.fullmatch(r"sha256:([a-f0-9]{64})", args.image)
    if not image_digest:
        raise SystemExit("The parser image must be pinned by sha256 digest.")
    image = DockerParser(args.image)
    fixtures = ROOT / ".verification" / "task0018-ocr" / args.output.stem
    cases = []
    for blank in (False, True):
        fixture_folder = fixtures / ("blank" if blank else "main")
        pdf, metadata = make_fixture_pdf(fixture_folder, font_path, blank=blank)
        cases.append(evaluate(image, pdf, metadata))
    malformed_folder = fixtures / "malformed"
    malformed_folder.mkdir(parents=True, exist_ok=True)
    malformed = malformed_folder / "synthetic-invalid.pdf"
    malformed.write_bytes(
        b"synthetic non-PDF input; generated locally for failure-close evaluation"
    )
    cases.append(
        evaluate(
            image,
            malformed,
            {
                "fixture_type": "malformed_synthetic_pdf",
                "pdf_sha256": sha256(malformed.read_bytes()),
            },
        )
    )
    report = {
        "schema_version": "task0018.tesseract-ocr-report.v1",
        "run": {
            "parser_image_sha256": image_digest.group(1),
            "font_sha256": sha256(font_path.read_bytes()),
            "ingestion_policy_sha256": sha256((ROOT / "config/ingestion.yaml").read_bytes()),
            "network_calls": False,
            "provider_calls": False,
            "fixtures_generated": True,
        },
        "cases": cases,
        "observed_timeouts": sum(case.get("error") == "PARSE_TIMEOUT" for case in cases),
        "observed_parser_failures": sum(case.get("error") is not None for case in cases),
        "observed_low_quality_downgrades": sum(
            case.get("low_quality_downgrade_observed") is True for case in cases
        ),
        "limitations": [
            (
                "OCR quality measurements are only from synthetic fixtures and do not estimate "
                "real tender-document quality."
            ),
            "PaddleOCR is not installed, downloaded, benchmarked, or selected.",
        ],
    }
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(json.dumps({"report": str(args.output), "cases": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
