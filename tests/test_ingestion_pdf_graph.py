"""TASK-0029: bookmark reference chains are not inline PDF object nesting."""

import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from bidding_compliance.ingestion.parser import inspect_pdf
from bidding_compliance.ingestion.policy import load_policy
from bidding_compliance.ingestion.ports import IngestionError


def payload(writer):
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def bookmarked_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    for index in range(120):
        writer.add_outline_item(f"Synthetic section {index}", 0)
    return writer


def test_long_bookmark_sibling_chain_is_valid():
    inspect_pdf(payload(bookmarked_pdf()), load_policy())


@pytest.mark.parametrize("key", ["/JavaScript", "/Launch", "/EmbeddedFiles", "/AA"])
def test_long_reference_chain_does_not_hide_active_content(key):
    writer = bookmarked_pdf()
    value = DictionaryObject({NameObject(key): TextStringObject("synthetic")})
    for _ in range(120):
        value = DictionaryObject({NameObject("/Next"): writer._add_object(value)})
    writer.root_object[NameObject("/SyntheticChain")] = writer._add_object(value)
    with pytest.raises(IngestionError) as caught:
        inspect_pdf(payload(writer), load_policy())
    assert caught.value.code == "MALICIOUS_CONTENT"


def test_deep_inline_object_still_rejected():
    writer = bookmarked_pdf()
    value = NumberObject(1)
    for _ in range(60):
        value = ArrayObject([value])
    writer.root_object[NameObject("/SyntheticNested")] = value
    with pytest.raises(IngestionError) as caught:
        inspect_pdf(payload(writer), load_policy())
    assert caught.value.code == "INVALID_FILE"


def test_object_work_limit_still_rejected():
    writer = bookmarked_pdf()
    writer.root_object[NameObject("/SyntheticWide")] = ArrayObject(
        NumberObject(index) for index in range(50001)
    )
    with pytest.raises(IngestionError) as caught:
        inspect_pdf(payload(writer), load_policy())
    assert caught.value.code == "INVALID_FILE"
