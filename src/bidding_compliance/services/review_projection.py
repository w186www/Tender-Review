"""Coverage, unknown-call and duplicate-finding projections for review outputs."""

from __future__ import annotations

import json
import re
from typing import Any

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_EVIDENCE_ORDER = {
    "insufficient_evidence": 0,
    "candidate": 1,
    "suspected": 2,
    "confirmed": 3,
}


def should_suppress_model_no_issue(assessment: str | None, origins: set[str]) -> bool:
    """Suppress an AI-only candidate when its semantic assessment says no issue."""
    return assessment == "no_issue" and not (origins & {"rule", "skill"})


def _same_issue_family(finding: dict[str, Any]) -> str | None:
    """Return a narrow family only for known semantic duplicates on one excerpt.

    The caller still groups by document hash, locator, quote and category. These
    families therefore cannot collapse different passages or different issue types
    merely because they happen to share a table cell.
    """
    narrative = " ".join(
        str(finding.get(key, "")) for key in ("title", "description", "recommendation")
    )
    text = narrative
    excerpt = finding.get("source_excerpt") or {}
    if isinstance(excerpt, dict):
        text += " " + str(excerpt.get("quote", ""))
    text = text.casefold()
    category = finding.get("category")
    compact_text = re.sub(r"\s+", "", text)
    compact_narrative = re.sub(r"\s+", "", narrative.casefold())
    if (
        category in {"qualification", "evaluation", "procedure"}
        and "联系人" in compact_narrative
        and any(term in compact_narrative for term in ("联系电话", "电话"))
        and "相同" in compact_narrative
        and any(term in compact_narrative for term in ("否决", "无效标", "资格限制"))
    ):
        return "qualification-identical-contact-phone-rejection"
    if (
        category in {"procedure", "contract"}
        and "串通投标" in compact_narrative
        and any(
            term in compact_narrative
            for term in ("非第一中标候选人", "非第一候选人", "第一中标候选人以外")
        )
        and any(
            term in compact_narrative for term in ("无实质影响", "不影响中标结果", "不影响中标")
        )
    ):
        return "procedure-nonfirst-collusion-effect"
    if (
        category == "procedure"
        and any(term in compact_narrative for term in ("最高投标限价", "最高限价"))
        and any(term in compact_narrative for term in ("发布", "公布"))
        and any(term in compact_narrative for term in ("开标", "投标截止", "异议"))
    ):
        return "procedure-price-limit-publication-time"
    if (
        category == "technical"
        and "品牌" in compact_narrative
        and any(
            term in compact_narrative
            for term in (
                "品牌锁定",
                "强制使用推荐品牌",
                "强制选用推荐品牌",
                "自主权受限",
                "仍须改用推荐品牌",
            )
        )
        and any(term in compact_text for term in ("不调价", "价格不予调整"))
    ):
        return "technical-brand-post-award-lock"
    if (
        category == "procedure"
        and "暂估价" in compact_text
        and "第2种方式" in compact_text
        and "方式" in compact_narrative
        and any(term in compact_narrative for term in ("不明", "未定义", "指代", "定义不清"))
        and "主体" not in compact_narrative
    ):
        return "procedure-estimated-price-confirmation-method"
    if category == "procedure" and "公示" in text and "期限" in text:
        return "procedure-publicity-period"
    if (
        category == "qualification"
        and any(term in text for term in ("信用分", "信用评分"))
        and any(term in text for term in ("最低档", "查不到", "没有信用分"))
    ):
        return "qualification-missing-credit-score"
    if (
        category == "qualification"
        and any(term in text for term in ("发改委", "发展和改革委员会", "监管部门"))
        and any(term in text for term in ("管辖", "执法", "处理", "投诉", "职权"))
    ):
        return "qualification-enforcement-jurisdiction"
    if (
        category == "qualification"
        and "项目经理" in text
        and any(term in text for term in ("未完工", "未完成", "多标段", "其他项目"))
    ):
        return "qualification-project-manager-unfinished-projects"
    if (
        category == "qualification"
        and "调查" in text
        and "配合" in text
        and any(term in text for term in ("举证", "期限", "处理"))
    ):
        return "qualification-investigation-cooperation"
    if (
        category == "contract"
        and any(term in text for term in ("项目经理", "关键人员", "人员变更"))
        and any(term in text for term in ("变更", "更换"))
        and any(term in text for term in ("违约金", "违约责任", "处罚"))
    ):
        return "contract-personnel-change-liability"
    if (
        category == "procedure"
        and any(term in text for term in ("文件冲突", "同一事项", "组成文件"))
        and any(term in text for term in ("编排顺序", "后者", "优先顺序"))
    ):
        return "procedure-document-precedence"
    if category == "evaluation" and any(term in text for term in ("j值", "j=", "j＝")):
        return "evaluation-j-parameter"
    if (
        category == "evaluation"
        and "k值" in text
        and any(term in text for term in ("抽取", "抽签", "隨機", "随机"))
    ):
        return "evaluation-k-draw-process"
    if category == "technical" and any(term in text for term in ("主观", "客观", "量化", "裁量")):
        return "technical-brand-review-criteria"
    if category == "technical" and any(term in text for term in ("默认", "视为接受")):
        return "technical-brand-response-default"
    return None


def merge_duplicate_findings(
    findings: list[dict[str, Any]],
    *,
    issue_keys: dict[str, str] | None = None,
    merge_audit: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge the same issue on the exact same excerpt, preserving distinct same-paragraph risks.

    The discovery artifact keeps every original candidate; this projection only decides
    what the reviewer sees. Findings on different locators or with different stable
    problem keys are never merged. A merged finding keeps the union of rule/model sources,
    rule IDs, document evidence, legal references and conflict records.
    """
    stable_issue_keys = issue_keys or {}
    groups: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    family_categories = {
        "qualification-identical-contact-phone-rejection": "qualification",
        "procedure-nonfirst-collusion-effect": "procedure",
    }
    for finding in findings:
        excerpt = finding.get("source_excerpt") or {}
        supplied_key = stable_issue_keys.get(str(finding.get("finding_id", "")))
        structured = bool(supplied_key and supplied_key.startswith(("issue-v2:", "unresolved-v2:")))
        family = None if structured else _same_issue_family(finding)
        issue_key = f"family:{family}" if family is not None else supplied_key
        if issue_key is None:
            title = re.sub(r"^待核验[：:]", "", str(finding.get("title", "")))
            issue_key = re.sub(r"[^\w\u4e00-\u9fff]", "", title).casefold()
        if not issue_key:
            issue_key = str(finding.get("finding_id", ""))
        group_category = (
            None
            if structured and supplied_key and supplied_key.startswith("issue-v2:")
            else family_categories[family]
            if family is not None and family in family_categories
            else finding.get("category")
        )
        group_key = (
            group_category,
            excerpt.get("source_hash"),
            excerpt.get("locator"),
            excerpt.get("quote"),
            issue_key,
        )
        groups.setdefault(group_key, []).append(finding)
    merged: list[dict[str, Any]] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue

        def score(item: dict[str, Any]) -> tuple[int, int, int, float]:
            return (
                1 if item.get("rule_ids") else 0,
                1 if "model" in item.get("sources", []) else 0,
                len(item.get("evidence", [])),
                float(item.get("confidence") or 0),
            )

        best: dict[str, Any] | None = None
        best_score: tuple[int, int, int, float] | None = None
        # Tie-breaking must not depend on database iteration or batch completion order.
        group = sorted(group, key=lambda item: str(item.get("finding_id", "")))
        for item in group:
            current = score(item)
            if best is None or best_score is None or current > best_score:
                best = item
                best_score = current
        assert best is not None
        result: dict[str, Any] = dict(best)
        result_key = stable_issue_keys.get(str(best.get("finding_id", "")), "")
        structured = result_key.startswith(("issue-v2:", "unresolved-v2:"))
        family = None if structured else _same_issue_family(best)
        if family is not None:
            result["category"] = family_categories.get(family, result.get("category"))
        result["sources"] = sorted({source for item in group for source in item.get("sources", [])})
        result["rule_ids"] = sorted({rule for item in group for rule in item.get("rule_ids", [])})
        result["severity"] = max(
            (item.get("severity", "low") for item in group),
            key=lambda value: _SEVERITY_ORDER.get(value, 0),
        )
        result["evidence_status"] = min(
            (item.get("evidence_status", "insufficient_evidence") for item in group),
            key=lambda value: _EVIDENCE_ORDER.get(value, 0),
        )
        evidence: dict[str, dict[str, Any]] = {}
        # Prefer the representative's citation identity when identical original
        # evidence was assigned different IDs by different discovery candidates.
        ordered_group = [best, *(item for item in group if item is not best)]
        for item in ordered_group:
            for reference in item.get("evidence", []):
                identity = (
                    json.dumps(
                        {
                            key: reference.get(key)
                            for key in ("kind", "source_hash", "locator", "page", "quote")
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if reference.get("kind") == "document"
                    else reference.get("evidence_id") or reference.get("source_hash")
                )
                if identity is not None:
                    evidence.setdefault(str(identity), reference)
        result["evidence"] = list(evidence.values())
        references: dict[str, dict[str, Any]] = {}
        for item in group:
            for reference in item.get("legal_references", []):
                identity = reference.get("evidence_id") or reference.get("title")
                if identity is None:
                    continue
                previous = references.get(str(identity))
                if previous is None or (
                    reference.get("selected_by_model") and not previous.get("selected_by_model")
                ):
                    references[str(identity)] = reference
        result["legal_references"] = list(references.values())
        conflicts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in group:
            for conflict in item.get("conflicts", []):
                encoded = json.dumps(conflict, ensure_ascii=False, sort_keys=True)
                if encoded not in seen:
                    seen.add(encoded)
                    conflicts.append(conflict)
        if conflicts:
            result["conflicts"] = conflicts[:20]
        if len({item.get("severity") for item in group}) > 1:
            result.setdefault("conflicts", [])
            result["conflicts"] = [
                *result["conflicts"][:19],
                {
                    "source": "model",
                    "assessment": "merged_severity_disagreement",
                    "summary": (
                        "同一问题的候选严重度不一致；保留最高候选等级供人工核查，不表示等级已确认。"
                    ),
                },
            ]
        if len({item.get("category") for item in group}) > 1:
            result.setdefault("conflicts", [])
            result["conflicts"] = [
                *result["conflicts"][:19],
                {
                    "source": "model",
                    "assessment": "merged_category_disagreement",
                    "summary": (
                        "同源同问题跨类别归并，保留代表项分类；原始分类和候选见运行投影归并记录。"
                    ),
                },
            ]
        result["review_status"] = "pending"
        if merge_audit is not None:
            merge_audit.append(
                {
                    "representative_finding_id": result.get("finding_id"),
                    "finding_ids": sorted(str(item.get("finding_id", "")) for item in group),
                    "issue_identity_key": result_key,
                    "categories": sorted({str(item.get("category", "")) for item in group}),
                    "severities": sorted({str(item.get("severity", "")) for item in group}),
                }
            )
        # Keep the base candidate's finding_id: the citation resolver binds a finding to
        # its frozen source candidate through this ID. Exact-excerpt duplicates share that
        # source, so the base mapping is sufficient for every merged evidence reference.
        merged.append(result)
    return merged


def project_product_execution(
    coverage: dict[str, Any] | None,
    *,
    unknown_model_call_count: int,
    batches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project a discovery coverage block without ever upgrading partial to complete."""
    unknown_count = max(0, unknown_model_call_count)
    if coverage is None:
        return {
            "completion_status": "partial" if unknown_count else "complete",
            "coverage_status": "not_applicable",
            "unprocessed_units": 0,
            "planned_units": 0,
            "analyzed_units": 0,
            "saturated_units": 0,
            "rejected_units": 0,
            "rejected_candidate_attempts": 0,
            "rejected_candidate_count": 0,
            "rejected_source_unit_count": 0,
            "rejection_reason_counts": {},
            "recovered_candidate_families": 0,
            "unrecovered_candidate_families": 0,
            "recovered_source_unit_count": 0,
            "failed_units": 0,
            "unsubmitted_units": 0,
            "truncated_batches": 0,
            "truncated": False,
            "saturated": False,
            "reason_codes": (
                ["model_call_outcome_unknown"]
                if unknown_count
                else ["deterministic_discovery_only"]
            ),
            "unknown_model_call_count": unknown_count,
        }
    saturated_batches = int(coverage.get("saturated_batches", 0))
    partial_batches = int(coverage.get("partial_batches", 0))
    failed_batches = int(coverage.get("failed_batches", 0))
    # Runs frozen before the coverage-field split only have per-batch records. Derive the
    # section counts from those batches instead of reporting every saturated section as
    # "unprocessed" or losing the saturation count.
    batch_rows = [item for item in batches or [] if isinstance(item, dict)]
    if batch_rows and all(isinstance(item.get("source_unit_hashes"), list) for item in batch_rows):
        from .llm_candidate_discovery import SATURATION_FINDING_LIMIT, coverage_summary

        normalized_batches = []
        for item in batch_rows:
            current = dict(item)
            if (
                item.get("response_hash") is not None
                and int(item.get("accepted_count", 0)) + int(item.get("rejected_count", 0))
                >= SATURATION_FINDING_LIMIT
                and not item.get("subdivision_children")
            ):
                current.update(status="saturated", saturated=True)
            normalized_batches.append(current)
        coverage = {
            **coverage,
            **coverage_summary(
                normalized_batches, section_count=int(coverage.get("section_count", 0))
            ),
        }
        saturated_batches = int(coverage["saturated_batches"])
        partial_batches = int(coverage["partial_batches"])
        failed_batches = int(coverage["failed_batches"])
    if "saturated_sections" in coverage:
        saturated_sections = int(coverage.get("saturated_sections", 0))
        rejected_sections = int(coverage.get("rejected_sections", 0))
        failed_sections = int(coverage.get("failed_sections", 0))
        submitted_sections = int(coverage.get("submitted_sections", 0))
        unsubmitted_sections = int(coverage.get("unsubmitted_sections", 0))
        truncated_batches = int(coverage.get("truncated_batches", 0))
    else:
        saturated_sections = sum(
            int(item.get("section_count", 0) or 0)
            for item in batch_rows
            if item.get("status") == "saturated"
        )
        rejected_sections = sum(
            int(item.get("section_count", 0) or 0)
            for item in batch_rows
            if item.get("status") == "partial"
        )
        failed_sections = sum(
            int(item.get("section_count", 0) or 0)
            for item in batch_rows
            if item.get("status") == "failed"
        )
        submitted_sections = sum(
            int(item.get("section_count", 0) or 0)
            for item in batch_rows
            if item.get("status") in {"completed", "partial", "saturated"}
        )
        total_sections = int(coverage.get("section_count", 0))
        unsubmitted_sections = max(0, total_sections - submitted_sections - failed_sections)
        truncated_batches = sum(
            item.get("finish_reason") in {"length", "max_tokens"}
            for item in batch_rows
            if item.get("status") in {"completed", "partial", "saturated"}
        )
    partial = saturated_batches > 0 or partial_batches > 0 or failed_batches > 0
    reasons: list[str] = []
    if saturated_batches:
        reasons.append("discovery_saturated")
    if partial_batches:
        reasons.append("discovery_partial")
    if failed_batches:
        reasons.append("discovery_failed")
    if int(coverage.get("failed_rescan_sections", 0)):
        reasons.append("discovery_rescan_failed")
    if truncated_batches:
        reasons.append("provider_output_truncated")
    if unknown_count:
        reasons.append("model_call_outcome_unknown")
    projected = {
        "completion_status": "partial" if partial or unknown_count else "complete",
        "coverage_status": "partial" if partial else "complete",
        "unprocessed_units": int(
            coverage.get("unprocessed_sections", failed_sections + unsubmitted_sections)
        ),
        "analyzed_units": submitted_sections,
        "saturated_units": saturated_sections,
        "rejected_units": rejected_sections,
        "failed_units": failed_sections,
        "failed_rescan_units": int(coverage.get("failed_rescan_sections", 0)),
        "unsubmitted_units": unsubmitted_sections,
        "truncated_batches": truncated_batches,
        "truncated": truncated_batches > 0,
        "saturated": saturated_batches > 0,
        "reason_codes": reasons or ["discovery_complete"],
        "unknown_model_call_count": unknown_count,
    }
    rejection_fields = (
        "rejected_candidate_attempts",
        "rejected_candidate_count",
        "rejected_source_unit_count",
        "rejection_reason_counts",
        "recovered_candidate_families",
        "unrecovered_candidate_families",
        "recovered_source_unit_count",
    )
    for field in rejection_fields:
        if field in coverage:
            projected[field] = coverage[field]
    if "source_unit_count" in coverage:
        projected["planned_units"] = int(coverage["source_unit_count"])
    return projected
