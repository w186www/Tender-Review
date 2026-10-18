"""Isolated parser implementation. Production entrypoint runs in the restricted image only."""

import base64
import csv
import hashlib
import io
import json
import logging
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

import pdfplumber
import pypdfium2 as pdfium  # type: ignore[import-untyped]
from defusedxml import ElementTree as SafeXML
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from .ports import IngestionError
from .quality import digest, quality
from .schemas import (
    FileFormat,
    Fragment,
    IngestionPolicy,
    OCRRuntimeIdentity,
    OCRWordRecord,
    ParsedDocument,
    ParserExecutionMetrics,
    ParserRequest,
    ParserResponse,
)


class OCR(Protocol):
    def recognize(self, image: Image.Image) -> list[dict[str, Any]]: ...


class TesseractOCR:
    def runtime_identity(self) -> OCRRuntimeIdentity:
        try:
            result = subprocess.run(
                ["/usr/bin/tesseract", "--version"],
                capture_output=True,
                check=False,
                timeout=5,
                env={"OMP_THREAD_LIMIT": "1"},
            )
            if result.returncode != 0:
                raise IngestionError("PARSE_FAILED")
            version = result.stdout.decode("utf-8").splitlines()[0].strip()
            data_dirs = sorted(Path("/usr/share/tesseract-ocr").glob("*/tessdata"))
            hashes: dict[str, str] = {}
            for model in ("chi_sim", "eng"):
                path = next(
                    (
                        folder / f"{model}.traineddata"
                        for folder in data_dirs
                        if (folder / f"{model}.traineddata").is_file()
                    ),
                    None,
                )
                if path is None:
                    raise IngestionError("PARSE_FAILED")
                hashes[model] = hashlib.sha256(path.read_bytes()).hexdigest()
            return OCRRuntimeIdentity.create(
                engine_version=version,
                model_ids=("chi_sim", "eng"),
                model_sha256=hashes,
                parameters={
                    "language": "chi_sim+eng",
                    "tesseract_config": "tsv",
                    "omp_thread_limit": 1,
                    "ocr_timeout_seconds": 25,
                },
            )
        except (OSError, subprocess.TimeoutExpired, UnicodeError, IndexError) as exc:
            raise IngestionError("PARSE_FAILED") from exc

    def recognize(self, image: Image.Image) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="ocr-") as folder:
            path = Path(folder) / "page.png"
            image.save(path, format="PNG")
            try:
                result = subprocess.run(  # noqa: S603 - fixed binary inside the isolated container
                    ["/usr/bin/tesseract", str(path), "stdout", "-l", "chi_sim+eng", "tsv"],
                    capture_output=True,
                    check=False,
                    timeout=25,
                    env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                )
            except subprocess.TimeoutExpired as exc:
                raise IngestionError("PARSE_TIMEOUT") from exc
            except OSError as exc:
                raise IngestionError("PARSE_FAILED") from exc
            if result.returncode != 0 or len(result.stdout) > 2000000:
                raise IngestionError("PARSE_FAILED")
            rows = csv.DictReader(io.StringIO(result.stdout.decode("utf-8")), delimiter="\t")
            recognized: list[dict[str, Any]] = []
            for row in rows:
                text = row["text"].strip()
                raw_confidence = float(row["conf"])
                if not text or raw_confidence < 0:
                    continue
                left, top = int(row["left"]), int(row["top"])
                width, height = int(row["width"]), int(row["height"])
                recognized.append(
                    {
                        "text": text,
                        "confidence": raw_confidence / 100,
                        "bbox": [left, top, left + width, top + height],
                        "level": int(row["level"]),
                        "page_num": int(row["page_num"]),
                        "block_num": int(row["block_num"]),
                        "par_num": int(row["par_num"]),
                        "line_num": int(row["line_num"]),
                        "word_num": int(row["word_num"]),
                        "raw_left": left,
                        "raw_top": top,
                        "raw_width": width,
                        "raw_height": height,
                        "raw_confidence": raw_confidence,
                    }
                )
            return recognized


def inspect_pdf(payload: bytes, policy: IngestionPolicy) -> None:
    reader = PdfReader(io.BytesIO(payload), strict=True)
    if reader.is_encrypted:
        raise IngestionError("ENCRYPTED_FILE")
    if len(reader.pages) > policy.max_pages:
        raise IngestionError("PAGE_LIMIT")
    forbidden = {
        "/JavaScript",
        "/JS",
        "/Launch",
        "/EmbeddedFiles",
        "/EmbeddedFile",
        "/RichMedia",
        "/XFA",
        "/OpenAction",
        "/AA",
        "/GoToR",
        "/SubmitForm",
        "/ImportData",
    }
    seen: set[tuple[int, int]] = set()
    count = 0
    pending: list[tuple[Any, int]] = [(reader.trailer, 0)]
    while pending:
        value, depth = pending.pop()
        count += 1
        if count > 50000 or depth > 50:
            raise IngestionError("INVALID_FILE")
        if isinstance(value, IndirectObject):
            identity = (value.idnum, value.generation)
            if identity in seen:
                continue
            seen.add(identity)
            # An indirect reference links objects; it is not inline nesting.
            # Long bookmark sibling/page links are normal in supported PDFs.
            # Keep a global work bound and a per-object inline depth bound.
            pending.append((value.get_object(), 0))
        elif isinstance(value, DictionaryObject):
            if forbidden.intersection(str(k) for k in value) or str(value.get("/S")) in forbidden:
                raise IngestionError("MALICIOUS_CONTENT")
            if str(value.get("/Type")) == "/EmbeddedFile":
                raise IngestionError("MALICIOUS_CONTENT")
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, ArrayObject):
            pending.extend((item, depth + 1) for item in value)


def ocr_fragments(
    image: Image.Image,
    page: int,
    coordinate: Literal["pdf_points", "image_pixels"],
    scale: float,
    ocr: OCR,
    locator: str,
) -> list[Fragment]:
    words = ocr.recognize(image)
    if not words:
        return [
            Fragment(
                locator=locator + "/empty",
                page=page,
                bbox=[0, 0, image.width / scale, image.height / scale],
                coordinate_system=coordinate,
                kind="ocr",
                text="",
                text_sha256=digest(""),
                source="ocr",
                confidence=0,
            )
        ]
    normalized: list[dict[str, Any]] = []
    for index, word in enumerate(words, 1):
        raw_bbox = [float(value) for value in word["bbox"]]
        x0, y0, x1, y1 = raw_bbox
        confidence = float(word["confidence"])
        normalized.append(
            {
                "text": str(word["text"]),
                "confidence": confidence,
                "bbox": [x0 / scale, y0 / scale, x1 / scale, y1 / scale],
                "level": int(word.get("level", 5)),
                "page_num": page,
                "tsv_page_num": int(word.get("page_num", 1)),
                "block_num": int(word.get("block_num", 0)),
                "par_num": int(word.get("par_num", 0)),
                "line_num": int(word.get("line_num", 0)),
                "word_num": int(word.get("word_num", index)),
                "raw_left": int(word.get("raw_left", round(x0))),
                "raw_top": int(word.get("raw_top", round(y0))),
                "raw_width": int(word.get("raw_width", round(x1 - x0))),
                "raw_height": int(word.get("raw_height", round(y1 - y0))),
                "raw_confidence": float(word.get("raw_confidence", confidence * 100)),
            }
        )

    has_tsv_layout = all(
        all(key in word for key in ("block_num", "par_num", "line_num"))
        for word in words
    )
    if not has_tsv_layout:
        lines: list[list[dict[str, Any]]] = []
        for word in normalized:
            x0, y0, x1, y1 = word["bbox"]
            center_y = (y0 + y1) / 2
            height = max(1.0, y1 - y0)
            matching = next(
                (
                    line
                    for line in lines
                    if abs(line[0]["center_y"] - center_y)
                    <= max(height, line[0]["height"]) * 0.45
                ),
                None,
            )
            value = {"word": word, "center_y": center_y, "height": height, "x0": x0, "x1": x1}
            if matching is None:
                lines.append([value])
            else:
                matching.append(value)
        for line_num, line in enumerate(lines, 1):
            line.sort(key=lambda item: item["x0"])
            for word_num, item in enumerate(line, 1):
                word = item["word"]
                word.update(block_num=1, par_num=1, line_num=line_num, word_num=word_num)

    paragraphs: dict[tuple[int, int], dict[int, list[dict[str, Any]]]] = {}
    for word in normalized:
        paragraph = paragraphs.setdefault((word["block_num"], word["par_num"]), {})
        paragraph.setdefault(word["line_num"], []).append(word)

    def line_text(line: list[dict[str, Any]]) -> str:
        ordered = sorted(line, key=lambda item: item["word_num"])
        text = ""
        for word in ordered:
            value = word["text"]
            if text and not (_contains_cjk(text[-1]) or _contains_cjk(value[0])):
                text += " "
            text += value
        return text

    def split_long_line(line: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        parts: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for word in sorted(line, key=lambda item: item["word_num"]):
            candidate = current + [word]
            if current and len(line_text(candidate)) > 8000:
                parts.append(current)
                current = [word]
            else:
                current = candidate
        if current:
            parts.append(current)
        if any(len(line_text(part)) > 8000 for part in parts):
            raise IngestionError("OUTPUT_LIMIT")
        return parts

    fragments: list[Fragment] = []
    for (block_num, par_num), line_map in paragraphs.items():
        chunks: list[list[list[dict[str, Any]]]] = []
        current: list[list[dict[str, Any]]] = []
        current_length = 0
        for line_num in sorted(line_map):
            for line_part in split_long_line(line_map[line_num]):
                line_length = len(line_text(line_part))
                if current and current_length + 1 + line_length > 8000:
                    chunks.append(current)
                    current, current_length = [], 0
                current.append(line_part)
                current_length += line_length + (1 if len(current) > 1 else 0)
        if current:
            chunks.append(current)
        for part_index, line_parts in enumerate(chunks, 1):
            text = "\n".join(line_text(line) for line in line_parts)
            records = [
                OCRWordRecord.model_validate(
                    {
                        **word,
                        "page_num": page,
                    }
                )
                for line in line_parts
                for word in sorted(line, key=lambda item: item["word_num"])
            ]
            boxes = [record.bbox for record in records]
            fragment_bbox = [
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            ]
            fragments.append(
                Fragment(
                    locator=(
                        f"{locator}/block/{block_num}/paragraph/{par_num}/part/{part_index}"
                    ),
                    page=page,
                    bbox=fragment_bbox,
                    coordinate_system=coordinate,
                    kind="ocr",
                    text=text,
                    text_sha256=digest(text),
                    source="ocr",
                    confidence=sum(record.confidence for record in records) / len(records),
                    ocr_words=records,
                )
            )
    return fragments


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def parse_pdf(payload: bytes, policy: IngestionPolicy, ocr: OCR) -> tuple[list[Fragment], int]:
    inspect_pdf(payload, policy)
    fragments: list[Fragment] = []
    ocr_count = 0
    with pdfplumber.open(io.BytesIO(payload)) as document:
        rendered = None
        try:
            for index, page in enumerate(document.pages, 1):
                tables = page.find_tables()
                for t, table in enumerate(tables):
                    values = table.extract()
                    for r, row in enumerate(table.rows):
                        for c, bounds in enumerate(row.cells):
                            text = (values[r][c] or "") if values[r][c] is not None else ""
                            # Empty cells still carry the table's structure. Dropping them
                            # makes blank forms and merged rows look like missing columns.
                            if bounds is not None:
                                fragments.append(
                                    Fragment(
                                        locator=f"pdf/page/{index}/table/{t}/row/{r}/cell/{c}",
                                        page=index,
                                        bbox=list(bounds),
                                        coordinate_system="pdf_points",
                                        kind="table_cell",
                                        text=text,
                                        text_sha256=digest(text),
                                        source="native",
                                        table=t,
                                        row=r,
                                        column=c,
                                    )
                                )

                def outside_table(obj: dict[str, Any], bounds: list[Any] = tables) -> bool:
                    return not any(
                        obj.get("x0", -1) >= table.bbox[0]
                        and obj.get("x1", -1) <= table.bbox[2]
                        and obj.get("top", -1) >= table.bbox[1]
                        and obj.get("bottom", -1) <= table.bbox[3]
                        for table in bounds
                    )

                clean = page.filter(outside_table)
                lines = clean.extract_text_lines(return_chars=False)
                for line_index, line in enumerate(lines, 1):
                    text = line["text"]
                    fragments.append(
                        Fragment(
                            locator=f"pdf/page/{index}/line/{line_index}",
                            page=index,
                            bbox=[line["x0"], line["top"], line["x1"], line["bottom"]],
                            coordinate_system="pdf_points",
                            kind="paragraph",
                            text=text,
                            text_sha256=digest(text),
                            source="native",
                        )
                    )
                substantial_image = any(
                    (item["x1"] - item["x0"]) * (item["bottom"] - item["top"])
                    >= page.width * page.height / 10
                    for item in page.images
                )
                if (
                    len((page.extract_text() or "").strip()) < policy.min_text_chars
                    or substantial_image
                ):
                    ocr_count += 1
                    if ocr_count > policy.max_ocr_pages:
                        raise IngestionError("OCR_LIMIT")
                    if rendered is None:
                        rendered = pdfium.PdfDocument(payload)
                    render_page = rendered[index - 1]
                    try:
                        if page.width * page.height * 4 > policy.max_image_pixels:
                            raise IngestionError("IMAGE_LIMIT")
                        bitmap = render_page.render(scale=2)
                        try:
                            image = bitmap.to_pil()
                            fragments.extend(
                                ocr_fragments(
                                    image, index, "pdf_points", 2, ocr, f"pdf/page/{index}/ocr"
                                )
                            )
                        finally:
                            bitmap.close()
                    finally:
                        render_page.close()
                check_limits(fragments, policy)
            return fragments, len(document.pages)
        finally:
            if rendered is not None:
                rendered.close()


def parse_docx(payload: bytes, policy: IngestionPolicy) -> list[Fragment]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        if len(infos) > policy.max_zip_entries:
            raise IngestionError("ARCHIVE_LIMIT")
        total = 0
        names: set[str] = set()
        for info in infos:
            name = info.filename
            lower = name.lower()
            total += info.file_size
            if (
                name in names
                or info.orig_filename != name
                or "\\" in name
                or ":" in name
                or PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or stat.S_ISLNK(info.external_attr >> 16)
                or info.flag_bits & 1
            ):
                raise IngestionError("MALICIOUS_CONTENT")
            names.add(name)
            if total > policy.max_uncompressed_bytes or (
                info.file_size / max(1, info.compress_size) > policy.max_compression_ratio
            ):
                raise IngestionError("ARCHIVE_LIMIT")
            if (
                "vbaproject" in lower
                or lower.startswith("word/embeddings/")
                or lower.endswith((".exe", ".dll", ".js"))
            ):
                raise IngestionError("MALICIOUS_CONTENT")
        if not {"[Content_Types].xml", "word/document.xml", "_rels/.rels"} <= names:
            raise IngestionError("INVALID_FILE")
        for name in names:
            if name.endswith(".rels") or name == "[Content_Types].xml":
                tree = SafeXML.fromstring(archive.read(name), forbid_dtd=True)
                for node in tree.iter():
                    if node.attrib.get("TargetMode", "").lower() == "external":
                        raise IngestionError("MALICIOUS_CONTENT")
                    if "macroenabled" in node.attrib.get("ContentType", "").lower():
                        raise IngestionError("MALICIOUS_CONTENT")
        tree = SafeXML.fromstring(archive.read("word/document.xml"), forbid_dtd=True)
        body = tree.find("w:body", namespace)
        if body is None:
            raise IngestionError("INVALID_FILE")
        fragments: list[Fragment] = []
        covered_nodes: set[int] = set()
        section = ""
        for block_index, block in enumerate(body):
            if block.tag.endswith("}p"):
                covered_nodes.add(id(block))
                text = "".join(n.text or "" for n in block.iter() if n.tag.endswith("}t"))
                style = block.find("w:pPr/w:pStyle", namespace)
                if style is not None and "heading" in str(style.attrib).lower():
                    section = text[:300]
                if text:
                    fragments.append(
                        Fragment(
                            locator=f"ooxml/body/{block_index}/paragraph",
                            coordinate_system="ooxml",
                            kind="paragraph",
                            section=section,
                            text=text,
                            text_sha256=digest(text),
                            source="native",
                        )
                    )
            elif block.tag.endswith("}tbl"):
                for r, row in enumerate(block.findall("w:tr", namespace)):
                    for c, cell in enumerate(row.findall("w:tc", namespace)):
                        covered_nodes.update(id(p) for p in cell.findall("w:p", namespace))
                        text = "\n".join(
                            "".join(n.text or "" for n in para.iter() if n.tag.endswith("}t"))
                            for para in cell.findall("w:p", namespace)
                        )
                        fragments.append(
                            Fragment(
                                locator=f"ooxml/body/{block_index}/table/row/{r}/cell/{c}",
                                coordinate_system="ooxml",
                                kind="table_cell",
                                section=section,
                                text=text,
                                text_sha256=digest(text),
                                source="native",
                                table=block_index,
                                row=r,
                                column=c,
                            )
                        )
            check_limits(fragments, policy)
        drawings = list(tree.findall(".//w:drawing", namespace)) + list(
            tree.findall(".//w:pict", namespace)
        )
        for name in sorted(names):
            if (
                name.startswith("word/")
                and name.endswith(".xml")
                and any(part in name for part in ("header", "footer", "footnotes", "endnotes"))
            ):
                auxiliary = SafeXML.fromstring(archive.read(name), forbid_dtd=True)
                drawings.extend(auxiliary.findall(".//w:drawing", namespace))
                drawings.extend(auxiliary.findall(".//w:pict", namespace))
                for index, paragraph in enumerate(auxiliary.findall(".//w:p", namespace)):
                    text = "".join(n.text or "" for n in paragraph.iter() if n.tag.endswith("}t"))
                    if text:
                        fragments.append(
                            Fragment(
                                locator=f"ooxml/{name}/paragraph/{index}",
                                coordinate_system="ooxml",
                                kind="paragraph",
                                text=text,
                                text_sha256=digest(text),
                                source="native",
                            )
                        )
        # Text hidden in content controls/nested tables is retained with its exact XML path.
        paths: dict[int, str] = {}
        pending = [(body, "ooxml/word/document.xml/body")]
        while pending:
            node, location = pending.pop()
            paths[id(node)] = location
            pending.extend(
                (child, f"{location}/{child.tag.rsplit('}', 1)[-1]}[{i}]")
                for i, child in enumerate(node)
            )
        for paragraph in body.findall(".//w:p", namespace):
            text = "".join(n.text or "" for n in paragraph.iter() if n.tag.endswith("}t"))
            if text and id(paragraph) not in covered_nodes:
                fragments.append(
                    Fragment(
                        locator=paths[id(paragraph)],
                        coordinate_system="ooxml",
                        kind="paragraph",
                        text=text,
                        text_sha256=digest(text),
                        source="native",
                    )
                )
        # Embedded Word images cannot be silently omitted or assigned fictitious rendered pages.
        for index, _ in enumerate(drawings):
            fragments.append(
                Fragment(
                    locator=f"ooxml/embedded-image/{index}",
                    coordinate_system="ooxml",
                    kind="ocr",
                    text="",
                    text_sha256=digest(""),
                    source="ocr",
                    confidence=0,
                )
            )
        check_limits(fragments, policy)
        return fragments


def check_limits(fragments: list[Fragment], policy: IngestionPolicy) -> None:
    logical_units = sum(max(1, len(fragment.ocr_words)) for fragment in fragments)
    if (
        logical_units > policy.max_fragments
        or sum(len(f.text) for f in fragments) > policy.max_text_chars
    ):
        raise IngestionError("TEXT_LIMIT")


def parse(
    payload: bytes, format: FileFormat, policy: IngestionPolicy, ocr: OCR | None = None
) -> ParsedDocument:
    if not payload or len(payload) > policy.max_upload_bytes:
        raise IngestionError("SIZE_LIMIT")
    recognizer = ocr if ocr is not None else TesseractOCR()
    runtime_identity = (
        recognizer.runtime_identity() if isinstance(recognizer, TesseractOCR) else None
    )
    page_count = None
    if format == "pdf":
        fragments, page_count = parse_pdf(payload, policy, recognizer)
    elif format == "docx":
        fragments = parse_docx(payload, policy)
    else:
        Image.MAX_IMAGE_PIXELS = policy.max_image_pixels
        with Image.open(io.BytesIO(payload)) as image:
            if image.format != ("PNG" if format == "png" else "JPEG"):
                raise IngestionError("TYPE_MISMATCH")
            if (
                image.width * image.height > policy.max_image_pixels
                or getattr(image, "n_frames", 1) != 1
            ):
                raise IngestionError("IMAGE_LIMIT")
            fragments = ocr_fragments(
                image.convert("RGB"), 1, "image_pixels", 1, recognizer, "image/page/1/ocr"
            )
            page_count = 1
    check_limits(fragments, policy)
    passed = quality(fragments, policy)
    return ParsedDocument(
        source_hash=hashlib.sha256(payload).hexdigest(),
        format=format,
        page_count=page_count,
        fragments=fragments,
        quality="passed" if passed else "requires_review",
        issues=[] if passed else ["LOW_QUALITY"],
        ocr_runtime=runtime_identity,
    )


def main() -> None:
    import time

    try:
        import resource
    except (
        ImportError
    ):  # pragma: no cover - parser image is Linux; keep local unit harness portable
        resource = None  # type: ignore[assignment]

    started = time.perf_counter()
    logging.disable(logging.CRITICAL)
    try:
        raw = sys.stdin.buffer.read(15000001)
        if len(raw) > 15000000:
            raise IngestionError("SIZE_LIMIT")
        request = ParserRequest.model_validate_json(raw)
        payload = base64.b64decode(request.payload_base64, validate=True)
        result = parse(payload, request.format, request.policy)
        response = ParserResponse(result=result)
    except IngestionError as exc:
        response = ParserResponse(error=exc.code)
    except Exception:
        response = ParserResponse(error="INVALID_FILE")
    rss = None
    if resource is not None:
        try:
            getrusage = getattr(resource, "getrusage", None)
            usage_self = getattr(resource, "RUSAGE_SELF", None)
            if callable(getrusage) and usage_self is not None:
                rss = int(getrusage(usage_self).ru_maxrss) * 1024
        except (OSError, ValueError):
            rss = None
    cgroup_peak = None
    try:
        cgroup_peak = int(Path("/sys/fs/cgroup/memory.peak").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        pass
    metrics = ParserExecutionMetrics(
        elapsed_ms=max(0, round((time.perf_counter() - started) * 1000)),
        process_peak_rss_bytes=rss,
        container_memory_peak_bytes=cgroup_peak,
    )
    response = response.model_copy(update={"metrics": metrics})
    sys.stdout.write(json.dumps(response.model_dump(), ensure_ascii=False))


if __name__ == "__main__":
    main()
