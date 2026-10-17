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
            return [
                dict(
                    text=row["text"],
                    confidence=float(row["conf"]) / 100,
                    bbox=[
                        int(row["left"]),
                        int(row["top"]),
                        int(row["left"]) + int(row["width"]),
                        int(row["top"]) + int(row["height"]),
                    ],
                )
                for row in rows
                if row["text"].strip() and float(row["conf"]) >= 0
            ]


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

    def walk(value: Any, depth: int = 0) -> None:
        nonlocal count
        count += 1
        if count > 50000 or depth > 50:
            raise IngestionError("INVALID_FILE")
        if isinstance(value, IndirectObject):
            identity = (value.idnum, value.generation)
            if identity in seen:
                return
            seen.add(identity)
            walk(value.get_object(), depth + 1)
        elif isinstance(value, DictionaryObject):
            if forbidden.intersection(str(k) for k in value) or str(value.get("/S")) in forbidden:
                raise IngestionError("MALICIOUS_CONTENT")
            if str(value.get("/Type")) == "/EmbeddedFile":
                raise IngestionError("MALICIOUS_CONTENT")
            for item in value.values():
                walk(item, depth + 1)
        elif isinstance(value, ArrayObject):
            for item in value:
                walk(item, depth + 1)

    walk(reader.trailer)


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
    return [
        Fragment(
            locator=locator + "/word/" + str(index),
            page=page,
            bbox=[float(v) / scale for v in word["bbox"]],
            coordinate_system=coordinate,
            kind="ocr",
            text=word["text"],
            text_sha256=digest(word["text"]),
            source="ocr",
            confidence=word["confidence"],
        )
        for index, word in enumerate(words, 1)
    ]


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
                            if bounds is not None and text:
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
    if (
        len(fragments) > policy.max_fragments
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
