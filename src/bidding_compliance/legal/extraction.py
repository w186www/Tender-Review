"""Deterministic origin maps. Native PDF implementation is for the isolated image/test runner."""

import html
import io
import re
from html.parser import HTMLParser
from typing import Any, Protocol

import pdfplumber

from bidding_compliance.ingestion.parser import inspect_pdf
from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.schemas import IngestionPolicy

from .contracts import SourceExclusion, SourceExtractionResult, SourceSpan


class PDFExtractor(Protocol):
    def extract(self, payload: bytes) -> SourceExtractionResult: ...


class MappedHTML(HTMLParser):
    def __init__(self, raw: str, offset: int) -> None:
        super().__init__(convert_charrefs=False)
        self.raw, self.base_start = raw, offset
        self.line_starts = [0]
        self.line_starts.extend(i + 1 for i, char in enumerate(raw) if char == "\n")
        self.active = False
        self.parts: list[tuple[str, int, int, str]] = []
        self.paragraphs: list[list[tuple[str, int, int, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "h2"}:
            if self.active:
                raise ValueError("nested law paragraphs")
            self.active, self.parts = True, []
        elif self.active and tag in {"script", "style", "iframe", "object"}:
            raise ValueError("active content in legal text")

    def add(self, data: str, raw_length: int, kind: str) -> None:
        if self.active:
            line, column = self.getpos()
            start = self.line_starts[line - 1] + column
            self.parts.append(
                (
                    data,
                    self.base_start + start,
                    self.base_start + start + raw_length,
                    kind,
                )
            )

    def handle_data(self, data: str) -> None:
        self.add(data, len(data), "html_text")

    def handle_entityref(self, name: str) -> None:
        raw = "&" + name + ";"
        self.add(html.unescape(raw), len(raw), "html_entity")

    def handle_charref(self, name: str) -> None:
        raw = "&#" + name + ";"
        self.add(html.unescape(raw), len(raw), "html_entity")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "h2"} and self.active:
            if self.parts:
                self.paragraphs.append(self.parts)
            self.active = False


def extract_html(payload: bytes, header: str) -> tuple[str, tuple[SourceSpan, ...]]:
    raw = payload.decode("utf-8")
    marker = '<div class="law-chapter">'
    if raw.count(marker) != 1 or "</main>" not in raw:
        raise ValueError("official page structure changed")
    begin = raw.index(marker) + len(marker)
    end = raw.index("</main>", begin)
    parser = MappedHTML(raw[begin:end], begin)
    parser.feed(raw[begin:end])
    parser.close()
    offsets = [0]
    for char in raw:
        offsets.append(offsets[-1] + len(char.encode("utf-8")))
    text = header
    spans: list[SourceSpan] = []
    if header:
        spans.append(SourceSpan(start=0, end=len(header), kind="header"))
    for paragraph in parser.paragraphs:
        whole = "".join(p[0] for p in paragraph)
        left, right = len(whole) - len(whole.lstrip()), len(whole.rstrip())
        consumed = 0
        for data, start, stop, kind in paragraph:
            low, high = max(0, left - consumed), min(len(data), right - consumed)
            consumed += len(data)
            if low >= high:
                continue
            fragment = data[low:high]
            if kind == "html_text":
                start, stop = start + low, start + high
            spans.append(
                SourceSpan(
                    start=len(text),
                    end=len(text) + len(fragment),
                    kind="html_text" if kind == "html_text" else "html_entity",
                    byte_start=offsets[start],
                    byte_end=offsets[stop],
                )
            )
            text += fragment
        if left < right:
            spans.append(SourceSpan(start=len(text), end=len(text) + 1, kind="separator"))
            text += "\n"
    if not parser.paragraphs or len(text) <= len(header) or len(text) > 500000:
        raise ValueError("empty or oversized legal HTML")
    return text, tuple(spans)


def extract_pdf_native(
    payload: bytes,
    policy: IngestionPolicy | None = None,
) -> SourceExtractionResult:
    if len(payload) > 2_000_000 or not payload.startswith(b"%PDF-"):
        raise ValueError("bounded PDF signature required")
    inspect_pdf(payload, policy or load_policy())
    text = ""
    spans: list[SourceSpan] = []
    excluded: list[SourceExclusion] = []
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        if len(pdf.pages) > 100:
            raise ValueError("PDF page budget exceeded")
        for page_number, page in enumerate(pdf.pages, 1):
            if any(
                (i["x1"] - i["x0"]) * (i["bottom"] - i["top"]) > (page.width * page.height * 0.2)
                for i in page.images
            ):
                raise ValueError("PDF image body requires reviewed OCR origin mapping")
            if page.images and not any(c["text"].strip() for c in page.chars):
                raise ValueError("PDF contains an unmapped scanned page; reviewed OCR required")
            words: list[dict[str, Any]] = page.extract_words(return_chars=True)
            glyphs = [c for word in words for c in word["chars"]]

            # Prove coverage instead of accepting a nonzero extraction.
            def key(c: dict[str, Any]) -> tuple[Any, ...]:
                return c["text"], c["x0"], c["top"], c["x1"], c["bottom"]

            if sorted(key(c) for c in glyphs) != sorted(
                key(c) for c in page.chars if c["text"].strip()
            ):
                raise ValueError("PDF glyph coverage mismatch")
            previous_top: float | None = None
            for word in words:
                if word["top"] > page.height - 35 and re.fullmatch(r"[-—]?\d+[-—]?", word["text"]):
                    excluded.append(
                        SourceExclusion(
                            page=page_number,
                            bbox=(word["x0"], word["top"], word["x1"], word["bottom"]),
                            text=word["text"],
                            reason="page_number",
                        )
                    )
                    continue
                if text:
                    separator = (
                        "\n" if previous_top is None or abs(word["top"] - previous_top) > 3 else " "
                    )
                    spans.append(
                        SourceSpan(
                            start=len(text),
                            end=len(text) + 1,
                            kind="separator",
                        )
                    )
                    text += separator
                for char in word["chars"]:
                    value = str(char["text"])
                    if "(cid:" in value or "\ufffd" in value or len(text) + len(value) > 100000:
                        raise ValueError("unsupported or oversized PDF text")
                    spans.append(
                        SourceSpan(
                            start=len(text),
                            end=len(text) + len(value),
                            kind="pdf_glyph",
                            page=page_number,
                            bbox=(char["x0"], char["top"], char["x1"], char["bottom"]),
                        )
                    )
                    text += value
                previous_top = word["top"]
    if not text:
        raise ValueError("PDF needs reviewed OCR, not an empty legal extraction")
    return SourceExtractionResult(text=text, spans=tuple(spans), raw_exclusions=tuple(excluded))
