"""DEC-005 gated acceptance: one minimal real Qwen discovery call over a synthetic sample.

Default mode performs exactly one paid request through the ordinary ModelGatewayService and
BailianQwenChatAdapter, then records metadata-only evidence (plus the authorized synthetic
excerpt) in the ignored private tree. ``--dry-run`` exercises every local precondition
without contacting the supplier. There is no mock fallback in either mode.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from bidding_compliance.domain.rules.engine import discover
from bidding_compliance.domain.rules.models import (
    DiscoveryInputSnapshot,
    DocumentVersionRef,
    Fragment,
    LocatedFragment,
)
from bidding_compliance.model_gateway.contracts import DataPolicy
from bidding_compliance.services import llm_candidate_discovery as llm
from bidding_compliance.services.llm_candidate_discovery import (
    pii_preflight,
    redact_discovery_text,
)
from bidding_compliance.services.real_ai_runtime import (
    AuthorizedTenderMinimizer,
    create_dec005_gateway,
    real_ai_policy,
)

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".verification/private/TASK-0023"
AUTHORIZATION_ID = "DEC-005-2026-10-15"
TENDER_DOCUMENT_SHA256 = "b1ea60ee828d7be418b01391cf3a6a25875f005cf2752be4ad9c594c16e65763"
SYNTHETIC_FILENAME = "task0023-synthetic-discovery-sample.docx"
SYNTHETIC_DOCUMENT_ID = "doc-synthetic-discovery"
TENANT_ID = "tenant-a"
PROJECT_ID = "project-synthetic-discovery"
REVIEW_TASK_ID = "review-task-synthetic-discovery"
RUN_ID = "run-synthetic-discovery-v1"
PROJECT_CONTEXT_SHA256 = "c" * 64
SNAPSHOT_HASH = "d" * 64
PAID_REQUESTS_PER_RUN = 1

# Deterministic synthetic sections: ordinary context, one reviewable contract term and
# masked contact data. They must not satisfy any deterministic skill rule.
SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "第一部分 样本说明",
        "本文件为合成评测样本，不含真实项目信息，仅用于验证系统的独立风险发现能力。",
    ),
    (
        "第一部分 采购需求",
        "本项目采购网络安全等级保护测评服务，服务内容包括差距分析、整改建议和复测。",
    ),
    (
        "第二部分 合同主要条款",
        "中标供应商应在合同签订前向采购人指定账户缴纳履约保证金，金额为合同总价的百分之三十。",
    ),
    (
        "第二部分 合同主要条款",
        "履约保证金在项目竣工验收合格满三年且无任何质量异议后无息退还。",
    ),
    (
        "第二部分 合同主要条款",
        "采购人有权在项目实施期间单方面调整服务范围与工作量，供应商不得据此提出费用调整或工期顺延要求。",
    ),
    (
        "第三部分 联系方式",
        "联系人：张三，联系电话：13800138000，电子邮箱：zhangsan@example.com。",
    ),
)

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)
_DOCUMENT_PREFIX = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
)
_DOCUMENT_SUFFIX = "<w:sectPr/></w:body></w:document>"
_FIXED_TIMESTAMP = (2026, 10, 15, 0, 0, 0)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def synthetic_docx_bytes() -> bytes:
    """Deterministic OOXML package so the approved sample keeps one stable identity."""
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        for _, text in SECTIONS
    )
    parts = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _RELS,
        "word/document.xml": _DOCUMENT_PREFIX + body + _DOCUMENT_SUFFIX,
    }
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            info = ZipInfo(name, date_time=_FIXED_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()


def fragment(index: int, section: str, text: str) -> Fragment:
    return Fragment(
        locator=f"paragraph:{index}",
        page=None,
        bbox=None,
        coordinate_system="ooxml",
        kind="paragraph",
        section=section,
        text=text,
        text_sha256=sha256_text(text),
        source="native",
        confidence=None,
        table=None,
        row=None,
        column=None,
    )


def synthetic_document(raw_sha256: str) -> tuple[DiscoveryInputSnapshot, dict[str, Any]]:
    entries = [
        (f"section-{index:03d}", fragment(index, section, text))
        for index, (section, text) in enumerate(SECTIONS)
    ]
    fragments_sha256 = hashlib.sha256(
        canonical(
            [
                {
                    "section_id": section_id,
                    "section_revision": 1,
                    "fragment": item.model_dump(mode="json"),
                }
                for section_id, item in entries
            ]
        )
    ).hexdigest()
    version_hash = hashlib.sha256(
        canonical(
            {
                "tenant_id": TENANT_ID,
                "project_id": PROJECT_ID,
                "document_id": SYNTHETIC_DOCUMENT_ID,
                "raw_source_sha256": raw_sha256,
                "parse_version": 1,
                "context_version": 1,
                "fragments_sha256": fragments_sha256,
            }
        )
    ).hexdigest()
    document = DocumentVersionRef(
        document_id=SYNTHETIC_DOCUMENT_ID,
        raw_source_sha256=raw_sha256,
        parse_version=1,
        context_version=1,
        fragments_sha256=fragments_sha256,
        document_version_ref="doc-version:sha256:" + version_hash,
        fragment_count=len(entries),
    )
    located = {
        SYNTHETIC_DOCUMENT_ID: tuple(
            LocatedFragment(document, section_id, 1, item) for section_id, item in entries
        )
    }
    project_ref = hashlib.sha256(
        canonical(
            {
                "tenant_id": TENANT_ID,
                "project_id": PROJECT_ID,
                "version": 1,
                "context_sha256": PROJECT_CONTEXT_SHA256,
            }
        )
    ).hexdigest()
    snapshot = DiscoveryInputSnapshot(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        project_version=1,
        project_context_sha256=PROJECT_CONTEXT_SHA256,
        project_context_ref="project-version:sha256:" + project_ref,
        documents=(document,),
    )
    return snapshot, located


def write_sample(raw: bytes) -> Path:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    path = PRIVATE / SYNTHETIC_FILENAME
    if path.exists():
        if path.read_bytes() != raw:
            raise SystemExit("existing synthetic sample differs from the deterministic identity")
        return path
    path.write_bytes(raw)
    return path


def local_preconditions() -> dict[str, Any]:
    raw = synthetic_docx_bytes()
    synthetic_sha = hashlib.sha256(raw).hexdigest()
    path = write_sample(raw)
    snapshot, located = synthetic_document(synthetic_sha)
    discovery = discover(snapshot, located)
    if discovery.candidates:
        raise SystemExit("synthetic sample unexpectedly satisfies a deterministic skill rule")
    batches = llm.plan_discovery(located)
    minimizer = AuthorizedTenderMinimizer(frozenset({synthetic_sha, TENDER_DOCUMENT_SHA256}))
    sent = [
        section["text"]
        for batch in batches
        for section in minimizer(batch.payload(), DataPolicy.CONFIDENTIAL)["discovery_sections"]
    ]
    leaked = {
        "mobile": any("13800138000" in text for text in sent),
        "email": any("zhangsan@example.com" in text for text in sent),
        "contact_name": any("张三" in text for text in sent),
    }
    if any(leaked.values()):
        raise SystemExit(f"outbound synthetic text still carries contact data: {leaked}")
    residual = {name: sum(pii_preflight(text)[name] for text in sent) for name in pii_preflight("")}
    if any(residual.values()):
        raise SystemExit(f"outbound synthetic text failed the privacy preflight: {residual}")
    sent_payloads = [item for batch in batches for item in batch.payload()["discovery_sections"]]
    return {
        "sample_path": str(path),
        "sample_sha256": synthetic_sha,
        "sample_bytes": len(raw),
        "allowed_document_sha256": sorted({synthetic_sha, TENDER_DOCUMENT_SHA256}),
        "skill_candidate_count": len(discovery.candidates),
        "skill_coverages": [item.model_dump(mode="json") for item in discovery.skill_coverages],
        "batch_count": len(batches),
        "batch_source_bytes": sorted(
            {len(item["text"].encode("utf-8")) for item in sent_payloads}
        ),
        "sent_section_keys": sorted(item["section_key"] for item in sent_payloads),
        "redacted_preview": sorted({redact_discovery_text(text) for _, text in SECTIONS})[-1],
        "leaked_contact_fields": leaked,
        "residual_pii_counts": residual,
        "document_version_ref": located[SYNTHETIC_DOCUMENT_ID][0].document.document_version_ref,
    }


async def run_acceptance() -> dict[str, Any]:
    if os.environ.get("DEC005_AUTHORIZATION_ID") != AUTHORIZATION_ID:
        raise SystemExit("DEC-005 real AI is disabled without its explicit server authorization")
    preconditions = local_preconditions()
    synthetic_sha = str(preconditions["sample_sha256"])
    credential = os.environ.get("DASHSCOPE_API_KEY", "")
    workspace = os.environ.get("BAILIAN_WORKSPACE_ID", "")
    if not credential.strip() or not workspace.strip():
        raise SystemExit("real AI requires server-side DASHSCOPE_API_KEY and BAILIAN_WORKSPACE_ID")

    _, located = synthetic_document(synthetic_sha)
    batches = llm.plan_discovery(located)
    if len(batches) != 1:
        raise SystemExit(f"minimal acceptance expects one batch, planned {len(batches)}")
    batch = batches[0]
    schema = llm.discovery_schema()
    policy = replace(real_ai_policy(), max_attempts=1, max_output_tokens=2048)
    gateway, authorization, ledger = create_dec005_gateway(
        api_key=credential,
        workspace_id=workspace,
        tenant_id=TENANT_ID,
        allowed_document_sha256=frozenset({synthetic_sha, TENDER_DOCUMENT_SHA256}),
        ledger_path=PRIVATE / "dec005-budget.sqlite3",
        audit_path=PRIVATE / "model-audit.jsonl",
    )
    before = ledger.summary()
    request = llm.make_discovery_request(
        batch,
        tenant_id=TENANT_ID,
        task_id=REVIEW_TASK_ID,
        run_id=RUN_ID,
        snapshot_hash=SNAPSHOT_HASH,
    )
    authorization.trusted_calls[request.call_id] = (
        TENANT_ID,
        REVIEW_TASK_ID,
        request.node_run_id,
    )
    response = await gateway.generate_structured(request, schema, policy)
    accepted, rejected = llm.validate_response(
        batch,
        response,
        expected_call_id=request.call_id,
        profile=policy.profile,
        schema=schema,
    )
    after = ledger.summary()
    return {
        "authorization_id": AUTHORIZATION_ID,
        "sample": preconditions,
        "request": {
            "call_id": request.call_id,
            "node_run_id": request.node_run_id,
            "prompt_version": request.prompt_version,
            "prompt_sha256": gateway.prompt_sha256(request.prompt_version),
            "batch_input_hash": batch.input_hash,
        },
        "response": {
            "provider": response.provider,
            "model": response.model,
            "profile": response.profile,
            "finish_reason": response.finish_reason,
            "response_hash": response.response_hash,
            "latency_ms": response.latency_ms,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cost_cny": str(response.usage.estimated_cost),
            },
            "content": dict(response.content),
        },
        "validation": {
            "accepted_count": len(accepted),
            "rejected": list(rejected),
            "candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "origin": item.origin,
                    "category": item.category,
                    "document_version_ref": item.document_version_ref,
                    "deduplication_key": item.deduplication_key,
                    "matched_reason": item.matched_reason,
                    "source_excerpts": [
                        {
                            "quote": excerpt.quote,
                            "quote_sha256": excerpt.quote_sha256,
                            "document_sha256": excerpt.document_sha256,
                            "locator": excerpt.locator,
                            "section_id": excerpt.section_id,
                        }
                        for excerpt in item.source_excerpts
                    ],
                    "provenance": [
                        source.model_dump(mode="json") for source in item.provenance
                    ],
                }
                for item in accepted
            ],
        },
        "budget": {
            "before": before,
            "after": after,
            "reservations_this_run": after["llm_calls"] - before["llm_calls"],
            "paid_requests": PAID_REQUESTS_PER_RUN,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="local preconditions only")
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps(local_preconditions(), ensure_ascii=False, indent=2))
        return 0
    result = asyncio.run(run_acceptance())
    PRIVATE.mkdir(parents=True, exist_ok=True)
    evidence = PRIVATE / "real-ai-acceptance.json"
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {key: value for key, value in result.items() if key != "sample"}
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:4000])
    print(f"evidence written: {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
