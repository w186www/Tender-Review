"""TASK-0028 U05 privacy boundaries: table cells, adjacent cells and cross-paragraph values."""

from __future__ import annotations

import hashlib
import json
import logging

import pytest

from bidding_compliance.core.diagnostics import DiagnosticFormatter
from bidding_compliance.core.logging import JsonFormatter
from bidding_compliance.domain.rules.models import DocumentVersionRef, Fragment, LocatedFragment
from bidding_compliance.model_gateway.contracts import DataPolicy
from bidding_compliance.services import llm_candidate_discovery as llm
from bidding_compliance.services.real_ai_runtime import AuthorizedTenderMinimizer

DOCUMENT = DocumentVersionRef(
    document_id="doc-u05",
    raw_source_sha256="a" * 64,
    parse_version=1,
    context_version=1,
    fragments_sha256="b" * 64,
    document_version_ref="doc-version:sha256:" + "c" * 64,
    fragment_count=8,
)


def located(
    locator: str,
    text: str,
    *,
    kind: str = "paragraph",
    table: int | None = None,
    row: int | None = None,
    column: int | None = None,
) -> LocatedFragment:
    return LocatedFragment(
        DOCUMENT,
        "section-1",
        1,
        Fragment(
            locator=locator,
            page=None,
            bbox=None,
            coordinate_system="ooxml",
            kind=kind,
            section="投标人须知",
            text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            source="native",
            confidence=None,
            table=table,
            row=row,
            column=column,
        ),
    )


def items() -> tuple[LocatedFragment, ...]:
    return (
        located("paragraph:0", "投标人联系人："),
        located("paragraph:1", "张三"),
        located("paragraph:2", "联系电话：138 0013 8000"),
        located("paragraph:3", "电子邮箱：bidder@example.com"),
        located("table:1:0:0", "银行账号", kind="table_cell", table=1, row=0, column=0),
        located("table:1:0:1", "6222020202020202020", kind="table_cell", table=1, row=0, column=1),
        located("paragraph:4", "联系人："),
        located("paragraph:5", "应当具备独立法人资格"),
    )


def safe_map() -> dict[str, str]:
    return {
        item.fragment.locator: safe
        for item, safe in llm._located_safe_texts(items())
    }


def test_cross_paragraph_and_adjacent_table_values_are_masked():
    safe = safe_map()
    assert safe["paragraph:1"] == "**"  # dangling 联系人 label in the previous paragraph
    assert "138" not in safe["paragraph:2"]
    assert "bidder@" not in safe["paragraph:3"]
    assert "6222020202020202020" not in safe["table:1:0:1"]
    assert set(safe["table:1:0:1"]) == {"*"}
    for text in safe.values():
        assert all(count == 0 for count in llm.pii_preflight(text).values())
    # A requirement after a dangling label is not a value and must not be over-masked.
    assert "应当具备独立法人资格" in safe["paragraph:5"]


def test_adjacent_table_cell_with_a_non_requirement_value_is_masked():
    safe = safe_map()
    assert safe["table:1:0:0"] == "银行账号"
    assert safe["table:1:0:1"] != "6222020202020202020"


def test_diagnostic_and_json_logs_never_echo_messages_or_bodies():
    secret = "sk-abcdefghijklmnop1234"  # noqa: S105 - synthetic test secret
    try:
        raise RuntimeError(f"provider failed for {secret} raw document text")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "bidding_compliance.diagnostics",
            logging.ERROR,
            __file__,
            1,
            "request_exception",
            (),
            sys.exc_info(),
        )
        diagnostic = DiagnosticFormatter().format(record)
        assert secret not in diagnostic
        assert "raw document text" not in diagnostic
        assert "RuntimeError" in diagnostic

    json_record = logging.LogRecord(
        "bidding_compliance",
        logging.INFO,
        __file__,
        1,
        f"document body {secret}",
        (),
        None,
    )
    json_record.document_text = "raw body"
    formatted = JsonFormatter().format(json_record)
    assert secret not in formatted
    assert "raw body" not in formatted
    assert json.loads(formatted)["event"] == "service_log"


def test_outbound_minimizer_rejects_secret_material_without_echoing_it():
    minimizer = AuthorizedTenderMinimizer(frozenset({"a" * 64}))
    secret = "sk-abcdefghijklmnop1234"  # noqa: S105 - synthetic test secret
    with pytest.raises(ValueError) as exc:
        minimizer(
            {
                "discovery_sections": [
                    {
                        "section_key": "s1",
                        "text": f"供应商密钥 {secret}",
                        "document_sha256": "a" * 64,
                    }
                ]
            },
            DataPolicy.CONFIDENTIAL,
        )
    assert secret not in str(exc.value)


def test_outbound_minimizer_masks_supported_pii_before_returning():
    minimizer = AuthorizedTenderMinimizer(frozenset({"a" * 64}))
    payload = minimizer(
        {
            "discovery_sections": [
                {
                    "section_key": "s1",
                    "text": "联系人：张三 联系电话：13800138000 邮箱：a@example.com",
                    "document_sha256": "a" * 64,
                }
            ]
        },
        DataPolicy.CONFIDENTIAL,
    )
    text = payload["discovery_sections"][0]["text"]
    assert "张三" not in text
    assert "13800138000" not in text
    assert "a@example.com" not in text
    assert all(count == 0 for count in llm.pii_preflight(text).values())
