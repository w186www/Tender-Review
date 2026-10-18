"""Independent source and legal-artifact checks for model-linked findings."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.domain.rules.models import CandidateFinding, SourceExcerpt
from bidding_compliance.legal.contracts import LegalHit, RetrievalResult
from bidding_compliance.persistence.models import LegalRetrievalRun
from bidding_compliance.services import documents
from bidding_compliance.services.legal import read_run
from bidding_compliance.services.legal_management import resolve_published_evidence
from bidding_compliance.services.review_persistence import canonical_json

_RELATED_CONTEXT_LIMIT = 6
_RELATED_CONTEXT_TOTAL_CHARACTERS = 10_000
_CATEGORY_CONTEXT_CUES = {
    "qualification": ("资格", "资质", "业绩", "注册", "社保", "人员", "本地", "地区"),
    "technical": ("品牌", "其他品牌", "同等性能", "同等档次", "替代", "技术参数", "型号"),
    "evaluation": ("评分", "分值", "评分标准", "评审", "加分", "扣分", "总分"),
    "contract": ("合同", "付款", "价款", "结算", "违约", "履约", "质保", "保证金"),
    "procedure": ("公告", "投标", "开标", "截止", "中标", "公示", "工作日", "天", "小时"),
}
_CLAIM_ANCHORS = {
    "machine_identifier": ("机器码", "加密锁号", "加密锁", "锁号", "序列号", "硬件码"),
    "contact_identifier": ("联系人", "联系电话", "电话", "手机号", "联系方式", "通讯录"),
    "brand": ("品牌", "品牌型号", "制造商", "厂商", "产品型号"),
    "deadline": (
        "期限", "截止", "开标时间", "投标时间", "工作日", "日历日", "小时",
        "公示期", "公示期限", "天内", "日内", "日历天",
    ),
    "scoring": (
        "评分", "分值", "评分标准", "加分", "扣分", "总分", "基准价",
        "偏差率", "不得分", "最低档", "j值", "k值",
    ),
    # Avoid the generic word "资格": model descriptions often mention qualification
    # review even when the actual asserted fact concerns a different subject (for
    # example machine-code identifiers). These anchors name concrete qualification
    # evidence or restrictions instead.
    "qualification": (
        "资格条件", "资格要求", "资质要求", "企业资质", "业绩要求", "注册证书",
        "社保证明", "本地注册", "本地企业", "地域限制", "人员资格",
    ),
    "amount": ("金额", "预算", "报价", "合同价款", "保证金", "元"),
}
_ACTIONABLE_RECOMMENDATIONS = {
    "qualification": (
        "对照资格条件、适用依据及证明材料，删除与履约无关的地域或主体限制，"
        "并明确每项资格条件对应的依据。"
    ),
    "technical": (
        "对照技术需求正文与品牌响应表；如参数实际锁定单一品牌，补充同等性能替代条款、"
        "等效证明要求和一致的验收口径。"
    ),
    "evaluation": (
        "逐项对照评标办法与评分表，补齐缺项、分值和计算方式，并复核分项总分及评分对象一致。"
    ),
    "contract": (
        "对照合同条款格式，明确价款、付款节点、违约责任和质保期限，"
        "删除待定占位并与采购要求保持一致。"
    ),
    "procedure": (
        "对照公告、投标须知和时间安排表，逐项核对文件获取、投标截止与开标日期时刻，"
        "并写明间隔及计算口径。"
    ),
}
_UNSUPPORTED_NORMATIVE_CLAIM = re.compile(
    r"(?:法规|法律|法定|规定|要求).{0,16}(?:通常|一般|至少|不得少于|应当|必须|更短|更长)"
)


def _normalized_search_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def claim_evidence_mismatch(claim: str, source_quotes: Sequence[str]) -> tuple[str, ...]:
    """Flag concrete subject types asserted by a finding but absent from its evidence set."""
    normalized_claim = _normalized_search_text(claim)
    normalized_source = _normalized_search_text(" ".join(source_quotes))
    return tuple(
        group
        for group, anchors in _CLAIM_ANCHORS.items()
        if any(anchor in normalized_claim for anchor in anchors)
        and not any(anchor in normalized_source for anchor in anchors)
    )


def model_source_quotes_are_verified(
    source_quote_hashes: Sequence[str], verified_quote_hashes: set[str]
) -> bool:
    """Accept model citations only when every hash resolves to a revalidated document quote."""
    return bool(source_quote_hashes) and set(source_quote_hashes).issubset(verified_quote_hashes)


def actionable_recommendation(category: str, recommendation: str) -> str:
    """Replace a generic review-only recommendation with a category-specific edit/check."""
    normalized = _normalized_search_text(recommendation)
    generic = (
        "人工核验",
        "人工复核",
        "审查员核对",
        "进一步核实",
        "建议核实",
        "请核实",
    )
    if (
        not recommendation.strip()
        or len(normalized) < 14
        or any(item in normalized for item in generic)
    ):
        return _ACTIONABLE_RECOMMENDATIONS.get(
            category, "对照原文位置和本次审查范围，补充具体核验项及拟修改内容。"
        )
    return recommendation


def has_unsupported_normative_claim(value: str) -> bool:
    return bool(_UNSUPPORTED_NORMATIVE_CLAIM.search(value))


def _related_context_score(text: str, category: str, candidate_terms: tuple[str, ...]) -> int:
    normalized = _normalized_search_text(text)
    score = sum(4 for cue in _CATEGORY_CONTEXT_CUES.get(category, ()) if cue in normalized)
    score += sum(1 for term in candidate_terms if term and term in normalized)
    return score


def related_document_context(
    session: Session,
    principal: Principal,
    *,
    project_id: str,
    candidate: CandidateFinding,
    expected_documents: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find bounded, exact excerpts elsewhere in each candidate's frozen source document."""
    from bidding_compliance.ingestion.schemas import Fragment
    from bidding_compliance.persistence.models import DocumentSection, SectionRevision

    from .documents import find_document

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    remaining = _RELATED_CONTEXT_TOTAL_CHARACTERS
    for source in candidate.source_excerpts:
        if source.document_id in seen:
            continue
        seen.add(source.document_id)
        expected = expected_documents.get(source.document_id)
        if expected is None:
            raise ValueError("related context document is outside the frozen snapshot")
        document = find_document(session, principal, project_id, source.document_id)
        if (
            document.status != "ready"
            or document.sha256 != expected.get("raw_source_sha256")
            or document.sha256 != source.document_sha256
            or document.parse_version != expected.get("parse_version")
            or document.context_version != expected.get("context_version")
        ):
            raise ValueError("related context source differs from the frozen document version")
        rows = list(
            session.scalars(
                select(DocumentSection)
                .where(
                    DocumentSection.tenant_id == principal.tenant_id,
                    DocumentSection.document_id == source.document_id,
                )
                .order_by(DocumentSection.ordinal)
            )
        )
        fragments: list[tuple[DocumentSection, Any]] = []
        for row in rows:
            revision = session.get(
                SectionRevision,
                (principal.tenant_id, source.document_id, row.section_id, row.revision),
            )
            fragment = Fragment.model_validate(revision.payload if revision else row.automatic)
            if hashlib.sha256(fragment.text.encode("utf-8")).hexdigest() != fragment.text_sha256:
                raise ValueError("related context fragment hash mismatch")
            fragments.append((row, fragment))
        source_ids = {
            item.section_id
            for item in candidate.source_excerpts
            if item.document_id == source.document_id
        }
        source_ordinals = {row.ordinal for row, _ in fragments if row.section_id in source_ids}
        text_terms = [candidate.problem_key, candidate.matched_reason]
        text_terms.extend(
            item.quote
            for item in candidate.source_excerpts
            if item.document_id == source.document_id
        )
        compact_terms = _normalized_search_text(" ".join(text_terms))
        candidate_terms = tuple(
            dict.fromkeys(
                term
                for term in (
                    *re.findall(r"[\u4e00-\u9fff]{2,6}", compact_terms),
                    *re.findall(r"[a-z0-9_-]{3,}", compact_terms),
                )
                if len(term) >= 2
            )
        )
        ranked: list[tuple[int, int, DocumentSection, Any]] = []
        for row, fragment in fragments:
            if (
                row.section_id in source_ids
                or not fragment.text.strip()
                or len(fragment.text) > 3000
            ):
                continue
            score = _related_context_score(
                fragment.text + fragment.section, candidate.category, candidate_terms
            )
            distance = min(
                (abs(row.ordinal - ordinal) for ordinal in source_ordinals), default=9999
            )
            if distance <= 2:
                score += 2
            if score > 0:
                ranked.append((score, -distance, row, fragment))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2].ordinal, item[2].section_id))
        for _, _, row, fragment in ranked:
            if len(selected) >= _RELATED_CONTEXT_LIMIT or remaining <= 0:
                break
            if len(fragment.text) > remaining:
                continue
            quote_hash = hashlib.sha256(fragment.text.encode("utf-8")).hexdigest()
            identity = {
                "document_id": document.document_id,
                "document_sha256": document.sha256,
                "section_id": row.section_id,
                "section_revision": row.revision,
                "locator": fragment.locator,
                "page": fragment.page,
                "quote_sha256": quote_hash,
            }
            selected.append(
                {
                    "evidence_id": evidence_identity(identity),
                    **identity,
                    "title": "全文交叉核对原文（非单独风险结论）",
                    "quote": fragment.text,
                    "coordinate_system": fragment.coordinate_system,
                }
            )
            remaining -= len(fragment.text)
    return selected


def verify_related_document_evidence(
    session: Session,
    principal: Principal,
    *,
    project_id: str,
    item: dict[str, Any],
    expected_documents: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Re-read an exact cross-section excerpt against the frozen source document version."""
    from bidding_compliance.ingestion.schemas import Fragment
    from bidding_compliance.persistence.models import DocumentSection, SectionRevision

    from .documents import find_document

    try:
        expected = expected_documents.get(item["document_id"])
        if expected is None:
            return None
        document = find_document(session, principal, project_id, item["document_id"])
        if (
            document.status != "ready"
            or document.sha256 != item["document_sha256"]
            or document.sha256 != expected.get("raw_source_sha256")
            or document.parse_version != expected.get("parse_version")
            or document.context_version != expected.get("context_version")
        ):
            return None
        section = session.get(
            DocumentSection,
            (principal.tenant_id, document.document_id, item["section_id"]),
        )
        if section is None or section.revision != item["section_revision"]:
            return None
        revision = session.get(
            SectionRevision,
            (principal.tenant_id, document.document_id, item["section_id"], section.revision),
        )
        fragment = Fragment.model_validate(revision.payload if revision else section.automatic)
        quote_hash = hashlib.sha256(fragment.text.encode("utf-8")).hexdigest()
        if (
            fragment.locator != item["locator"]
            or fragment.page != item["page"]
            or fragment.text != item["quote"]
            or quote_hash != item["quote_sha256"]
        ):
            return None
        return {
            "evidence_id": item["evidence_id"],
            "kind": "document",
            "title": item["title"],
            "article": None,
            "quote": item["quote"],
            "source_uri": (
                f"artifact://related-document/{document.document_id}/{document.sha256}/"
                f"{item['section_id']}/{item['section_revision']}"
            ),
            "source_hash": document.sha256,
            "page": fragment.page,
            "locator": fragment.locator,
            "effective_from": None,
            "effective_to": None,
            "version_status": "unverified",
            "jurisdiction": None,
        }
    except (KeyError, LookupError, ValueError):
        return None


def evidence_identity(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def has_confirmable_legal_support(hits: Sequence[LegalHit], *, invalid: bool = False) -> bool:
    return (
        bool(hits)
        and not invalid
        and all(
            hit.eligible_for_confirmation
            and hit.version_status == "verified_current"
            and bool(hit.article)
            for hit in hits
        )
    )


def evidence_status_for_support(*, document_valid: bool, legal_valid: bool) -> str:
    if not document_valid or not legal_valid:
        return "insufficient_evidence"
    # A reviewed rule-to-law binding is not approved, so evidence alone cannot confirm.
    return "suspected"


def verify_document_excerpt(
    session: Session,
    principal: Principal,
    *,
    project_id: str,
    candidate: CandidateFinding,
    excerpt: SourceExcerpt,
    expected_document_refs: dict[str, str],
) -> dict[str, Any] | None:
    """Re-read the current pinned section and prove the exact text locator and hashes."""
    try:
        document = documents.find_document(session, principal, project_id, excerpt.document_id)
        if document.status != "ready" or document.sha256 != excerpt.document_sha256:
            return None
        section_index = documents.sections(session, principal, project_id, excerpt.document_id)
        if section_index.parse_version != document.parse_version:
            return None
        matching = [item for item in section_index.items if item.section_id == excerpt.section_id]
        if len(matching) != 1:
            return None
        section = matching[0]
        fragment = section.effective
        bbox = tuple(fragment.bbox) if fragment.bbox is not None else None
        if (
            section.revision != excerpt.section_revision
            or section.source_hash != excerpt.document_sha256
            or fragment.locator != excerpt.locator
            or fragment.page != excerpt.page
            or fragment.coordinate_system != excerpt.coordinate_system
            or bbox != excerpt.bbox
        ):
            # The explicit comparisons below avoid accepting partial locator matches.
            return None
        if (
            fragment.text != excerpt.quote
            or hashlib.sha256(fragment.text.encode("utf-8")).hexdigest() != excerpt.quote_sha256
            or expected_document_refs.get(excerpt.document_id) != candidate.document_version_ref
        ):
            return None
        return {
            "evidence_id": evidence_identity(
                {
                    "document_id": excerpt.document_id,
                    "document_sha256": excerpt.document_sha256,
                    "section_id": excerpt.section_id,
                    "section_revision": excerpt.section_revision,
                    "locator": excerpt.locator,
                    "quote_sha256": excerpt.quote_sha256,
                    "candidate_id": candidate.candidate_id,
                }
            ),
            "kind": "document",
            "title": "投标文件原文",
            "article": None,
            "quote": excerpt.quote,
            "source_uri": f"artifact://document/{excerpt.document_sha256}",
            "source_hash": excerpt.document_sha256,
            "page": excerpt.page,
            "locator": excerpt.locator,
            "effective_from": None,
            "effective_to": None,
            "version_status": "unverified",
            "jurisdiction": None,
        }
    except (LookupError, FileExistsError, ValueError):
        return None


def verify_legal_hit(
    session: Session,
    principal: Principal,
    *,
    publication_id: str,
    revision_id: str,
    result_payload: dict[str, Any],
    hit_payload: dict[str, Any],
) -> tuple[LegalHit | None, str | None]:
    """Revalidate the saved retrieval run, publication, applicability and legal bytes."""
    try:
        result = RetrievalResult.model_validate(result_payload)
        hit = LegalHit.model_validate(hit_payload)
        if result.query is None or result.run_snapshot is None:
            return None, None
        run_id = result.run_snapshot.run_id
        reread = read_run(session, principal, run_id)
        if reread != result:
            return None, None
        record = session.get(LegalRetrievalRun, (principal.tenant_id, run_id))
        if record is None or (
            record.request_snapshot.get("publication_id") != publication_id
            or record.request_snapshot.get("revision_id") != revision_id
        ):
            return None, None
        quote = resolve_published_evidence(session, principal, publication_id, hit, result.query)
        if quote != hit.quote:
            return None, None
        return hit, quote
    except (LookupError, ValueError, KeyError):
        return None, None
