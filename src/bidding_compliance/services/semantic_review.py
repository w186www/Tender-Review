"""Check model support relationships without manufacturing facts or legal authority."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .review_contracts import candidate_anchor, issue_identity_key


def review_support_errors(
    model: Mapping[str, Any], *, document_hashes: set[str], legal_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    if issue_identity_key(model.get("issue_identity")) is None:
        errors.append("issue_identity_missing")
    review = model.get("context_review")
    if not isinstance(review, dict):
        errors.append("context_review_missing")
    else:
        reviewed = set(review.get("reviewed_quote_sha256", []))
        counter = set(review.get("counterevidence_quote_sha256", []))
        if not reviewed or reviewed != document_hashes or not counter.issubset(reviewed):
            errors.append("context_review_incomplete_or_invalid")
        if (
            review.get("conclusion") == "unresolved"
            and model.get("assessment") == "potential_issue"
        ):
            errors.append("unresolved_context_assertion")
        if review.get("conclusion") == "contradicted" and model.get("assessment") != "no_issue":
            errors.append("counterevidence_not_resolved")
        if model.get("assessment") == "no_issue" and review.get("conclusion") != "contradicted":
            errors.append("no_issue_context_not_contradicted")
        if review.get("conclusion") == "unresolved" and model.get("assessment") != "uncertain":
            errors.append("unresolved_context_not_uncertain")
    assessments = model.get("legal_assessments")
    if not isinstance(assessments, list):
        errors.append("legal_assessments_missing")
    else:
        by_id = {entry.get("evidence_id"): entry for entry in assessments}
        if len(by_id) != len(assessments) or set(by_id) != legal_ids:
            errors.append("legal_assessments_incomplete_or_invalid")
        supported = {
            identifier
            for identifier, entry in by_id.items()
            if entry.get("relation") in {"supports", "conflicts"}
        }
        if supported != set(model.get("legal_evidence_ids", [])):
            errors.append("legal_selection_relation_mismatch")
        if (
            any(entry.get("relation") == "conflicts" for entry in by_id.values())
            and model.get("assessment") == "potential_issue"
        ):
            errors.append("legal_counterevidence_unresolved")
    return errors


def duplicate_identity_errors(
    candidate: Any,
    model: Mapping[str, Any],
    *,
    candidates: Mapping[str, Any],
    models: Mapping[str, Any],
) -> list[str]:
    target_id = model.get("duplicate_of_candidate_id")
    if target_id is None:
        return []
    target = candidates.get(target_id)
    target_model = models.get(target_id)
    if (
        target is None
        or target_model is None
        or target_id == candidate.candidate_id
        or candidate_anchor(candidate) != candidate_anchor(target)
        or issue_identity_key(model.get("issue_identity")) is None
        or issue_identity_key(model.get("issue_identity"))
        != issue_identity_key(target_model.get("issue_identity"))
    ):
        return ["duplicate_identity_or_source_mismatch"]
    # Resolve links only to a representative that does not itself point elsewhere.
    # Cycles/chains never authorize merging otherwise distinct findings.
    if target_model.get("duplicate_of_candidate_id") is not None:
        return ["duplicate_representative_not_terminal"]
    return []


def unresolved_conditional_claim(text: str, quotes: Sequence[str]) -> bool:
    """Flag blanket assertions despite allowances, respecting sentence-local scope.

    This is a review conflict, not a declaration that the clause is lawful. It
    operates on condition operators rather than document-specific risk families.
    """
    allowance = any(
        not re.search(r"(?:不|未|没有|并非|不得|禁止|不予)$", quote[: match.start()])
        for quote in quotes
        for match in re.finditer(r"允许|可选用|可以使用|除外|不受.{0,8}限制", quote)
    )
    if not allowance:
        return False
    for sentence in re.split(r"[。；;！？!?\n]+", text):
        for absolute in re.finditer(
            r"一律|全面禁止|禁止使用|不得使用|仅允许|排斥竞争|指定唯一", sentence
        ):
            prefix = sentence[: absolute.start()]
            clause = re.split(r"[，,]", prefix)[-1]
            if re.search(
                r"(?:不存在|未发现|不构成|不能认定|并非|不属于|"
                r"不应(?:当)?(?:概括|认定|视为|表述|写成)?|"
                r"不能(?:直接)?(?:概括|认定|视为|表述|写成))[^，,]{0,24}$",
                clause,
            ):
                continue
            if re.search(
                r"(?:只有|仅在|若|如果|当|在)[^，,]{1,40}"
                r"(?:时|条件下|情形下|情况下)[，,]?[^，,]{0,16}$",
                prefix,
            ):
                continue
            return True
    return False


def conditional_recommendation(text: str, *, support_unresolved: bool) -> str:
    if support_unresolved and re.search(r"删除|立即|必须|改为|暂停|补办|应当", text):
        return (
            "以下仅为条件性处理建议，须先确认原文问题及适用依据成立，不能直接作为修改指令：" + text
        )[:4000]
    return text
