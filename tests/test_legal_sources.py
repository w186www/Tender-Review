"""D07: bytes, Unicode/entities, PDF glyphs, exclusions and complete article coverage."""

import html
import io
from pathlib import Path

import pdfplumber
import pytest
from PIL import Image
from pypdf import PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from test_legal_retrieval import query, version

from bidding_compliance.legal.contracts import LegalManifest, LegalVersion
from bidding_compliance.legal.corpus import (
    ARTICLE,
    digest,
    evidence_origins,
    ingest,
    map_source,
    split_clauses,
)
from bidding_compliance.legal.extraction import extract_html, extract_pdf_native
from bidding_compliance.legal.retrieval import LegalRetriever
from bidding_compliance.legal.source_sandbox import DockerPDFExtractor

ROOT = Path(__file__).resolve().parents[1]


def html_corpus(root, body, header="合成法规\n"):
    metadata = version(root)
    raw = ('<main><div class="law-chapter">' + body + "</div></main>").encode()
    text, spans = extract_html(raw, header)
    (root / "source.html").write_bytes(raw)
    (root / "law.txt").write_bytes(text.encode())
    metadata = LegalVersion.model_validate(
        {
            **metadata.model_dump(),
            "source_snapshot_path": "source.html",
            "source_hash": digest(raw),
            "source_format": "moj_html",
            "text_hash": digest(text.encode()),
            "extraction_header": header,
        }
    )
    return metadata, raw, text, spans


def test_html_entities_inline_tags_trim_and_unicode_have_byte_origins(tmp_path):
    metadata, source, text, spans = html_corpus(
        tmp_path,
        "<p>　第一条 合成&amp;保证金<span>😀</span>&#x4e2d;。 </p>"
        "<h2>第二章 测试</h2><p>第二条 合成品牌限制。</p>",
    )
    index = ingest(tmp_path, LegalManifest(versions=(metadata,)))
    assert len(index.clauses) == 2
    for span in spans:
        if span.kind in {"html_text", "html_entity"}:
            decoded = source[span.byte_start : span.byte_end].decode()
            if span.kind == "html_entity":
                decoded = html.unescape(decoded)
            assert decoded == text[span.start : span.end]
    result = LegalRetriever(index).search(query())
    origins = evidence_origins(tmp_path, index, result.hits[0], result.query)
    assert sum(p.end - p.start for p in origins) == len(result.hits[0].quote)
    assert any(p.kind == "html_entity" for p in origins)
    assert not any(p.kind == "header" for p in origins)
    assert any(x.reason == "chapter" for x in index.text_exclusions)


@pytest.mark.parametrize(
    "body",
    [
        "<p>第一条 <script>malicious()</script></p>",
        "<p><p>第一条 invalid</p></p>",
    ],
)
def test_html_active_or_nested_body_fails_closed(body):
    with pytest.raises(ValueError):
        extract_html(('<main><div class="law-chapter">' + body + "</main>").encode(), "")


def test_cleaned_text_tamper_and_generated_clause_cannot_be_verified(tmp_path):
    metadata, source, text, _ = html_corpus(
        tmp_path,
        "<p>第一条 合成保证金。</p><p>第二条 合成品牌。</p>",
    )
    with pytest.raises(ValueError, match="reproduce"):
        map_source((text + "altered").encode(), source, metadata)
    metadata, _, _, _ = html_corpus(tmp_path, "<p>第二条 合成品牌。</p>", "第一条 伪造保证金。\n")
    with pytest.raises(ValueError, match="generated header"):
        ingest(tmp_path, LegalManifest(versions=(metadata,)))


def test_directory_excluded_duplicate_heading_rejected_and_long_article_complete(tmp_path):
    metadata = version(tmp_path)
    text = "第一条 保证金......1\n第二条 品牌......2\n第一章 总则\n第一条 " + "甲" * 9000
    text += "\n第二条 合成品牌。\n"
    (tmp_path / "law.txt").write_bytes(text.encode())
    metadata = metadata.model_copy(
        update={"text_hash": digest(text.encode()), "source_hash": digest(text.encode())}
    )
    index = ingest(tmp_path, LegalManifest(versions=(metadata,)))
    assert len(index.clauses) == 3
    first = [c.quote for c in index.clauses if c.article == "第一条"]
    assert "".join(first) == "第一条 " + "甲" * 9000
    assert all("......" not in c.quote for c in index.clauses)
    assert any(x.reason in {"preamble", "toc"} for x in index.text_exclusions)
    with pytest.raises(ValueError, match="duplicate"):
        split_clauses("第一条 正文\n第一条 重复标题\n第二条 正文", metadata)
    with pytest.raises(ValueError, match="coverage"):
        ingest(
            tmp_path,
            LegalManifest(
                versions=(
                    metadata.model_copy(
                        update={
                            "expected_articles": ("第一条", "第二条", "第三条"),
                        }
                    ),
                )
            ),
        )


def synthetic_pdf():
    buffer = io.BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf = canvas.Canvas(buffer)
    pdf.setFont("STSong-Light", 12)
    pdf.drawString(40, 750, "第一条 合成投标保证金规定。")
    pdf.drawString(40, 725, "第二条 合成品牌规定。")
    pdf.drawString(300, 20, "1")
    pdf.save()
    return buffer.getvalue()


def test_actual_pdf_glyphs_and_page_number_have_separate_coverage(tmp_path):
    raw = synthetic_pdf()
    result = extract_pdf_native(raw)
    assert len(list(ARTICLE.finditer(result.text))) == 2
    assert result.raw_exclusions and result.raw_exclusions[0].text == "1"
    assert not result.text.endswith("1")
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for span in result.spans:
            if span.kind == "pdf_glyph":
                chars = [
                    c
                    for c in pdf.pages[span.page - 1].chars
                    if (
                        c["x0"],
                        c["top"],
                        c["x1"],
                        c["bottom"],
                    )
                    == span.bbox
                ]
                assert "".join(c["text"] for c in chars) == result.text[span.start : span.end]


def test_real_official_pdf_extracts_all_84_articles_with_page_boxes():
    raw = (ROOT / "knowledge/legal/snapshots/ordinance-2019-validation.pdf").read_bytes()
    result = extract_pdf_native(raw)
    assert len(list(ARTICLE.finditer(result.text))) == 84
    assert {p.page for p in result.spans if p.kind == "pdf_glyph"} == set(range(1, 16))
    assert all(p.bbox for p in result.spans if p.kind == "pdf_glyph")


def test_pdf_untrusted_active_content_and_mutable_image_rejected():
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    pdf.add_js("app.alert('synthetic');")
    buffer = io.BytesIO()
    pdf.write(buffer)
    with pytest.raises(Exception, match="MALICIOUS_CONTENT"):
        extract_pdf_native(buffer.getvalue())
    with pytest.raises(ValueError, match="fixed parser image"):
        DockerPDFExtractor("latest")


def test_real_html_every_returned_character_has_original_origin():
    manifest = LegalManifest.model_validate_json((ROOT / "config/legal/manifest.json").read_bytes())
    index = ingest(ROOT, manifest)
    result = LegalRetriever(index).search(query())
    for hit in result.hits:
        origins = evidence_origins(ROOT, index, hit, result.query)
        assert origins[0].start == int(hit.locator.split("=")[1].split(":")[0])
        assert sum(p.end - p.start for p in origins) == len(hit.quote)
        assert all(p.kind != "header" for p in origins)


def test_text_header_cannot_hide_an_unmapped_scanned_pdf_body():
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(40, 750, "A text header does not prove the scanned body is mapped")
    image = Image.new("RGB", (100, 100), "white")
    pdf.drawImage(ImageReader(image), 40, 100, width=500, height=600)
    pdf.save()
    with pytest.raises(ValueError, match="reviewed OCR"):
        extract_pdf_native(buffer.getvalue())
