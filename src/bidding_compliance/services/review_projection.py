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
        str(finding.get(key, ""))
        for key in ("title", "description", "recommendation")
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
    if category == "technical" and any(
        term in text for term in ("主观", "客观", "量化", "裁量")
    ):
        return "technical-brand-review-criteria"
    if category == "technical" and any(term in text for term in ("默认", "视为接受")):
        return "technical-brand-response-default"
    if (
        category == "technical"
        and "品牌" in text
        and any(term in text for term in ("自主权受限", "品牌锁定", "价格不予调整"))
        and any(term in text for term in ("中标后", "未通过", "不调价"))
    ):
        return "technical-brand-post-award-lock"
    return None


def _apply_family_summary(finding: dict[str, Any], family: str | None) -> None:
    """Make the merged reviewer-facing wording state the shared, supported issue."""
    summaries = {
        "procedure-publicity-period": (
            "公示期限存在一日与三日表述差异",
            "本处写明公示期限为1日，文件内关联条款另写“公示发布次日起3日”。"
            "两处是否针对不同阶段和公示对象尚未说明；现有证据不足以确定应采用哪一期限。",
            "核对两处条款分别对应的公示对象、阶段和起止计算方式；若适用阶段不同，"
            "在条文中明确区分；若针对同一事项，则统一表述并按适用法规原文复核。",
        ),
        "qualification-investigation-cooperation": (
            "配合调查及限期举证要求不够明确",
            "条款要求投标人在“规定的期限内”举证，并对未配合情形作出处理，"
            "但此处未明确期限起算点、送达方式及具体后果，可能造成执行口径不一致。",
            "明确调查通知的送达方式、期限起算点、举证材料范围及不配合的处理依据；"
            "只写入经招标人确认并与适用规则一致的时限和后果。",
        ),
        "qualification-missing-credit-score": (
            "信用分缺失时按最低档计分的处理需补充分情形规则",
            "文件规定查询不到信用分或投标人没有信用分时按最低档计分，"
            "但未区分无信用记录、查询故障或数据错误，也未写明纠错机会。",
            "分别明确无信用记录、系统无法查询和信用数据异议的处理方式、"
            "证明材料及复核期限，并确保评分表与资格、评审条款一致。",
        ),
        "qualification-enforcement-jurisdiction": (
            "投诉或调查处理部门及管辖依据需明确",
            "同一原文对涉嫌虚假材料、调查处理或投诉监督的机构表述，"
            "需要与本项目的行政监督职责和地域管辖对应核对。",
            "按采购项目类型和所在地核对行政监督部门及其法定职责；"
            "分别写明异议、投诉和违法线索处理渠道，并删除职责依据不明的机构表述。",
        ),
        "qualification-project-manager-unfinished-projects": (
            "项目经理未完工项目限制的范围需明确",
            "条款限制拟派项目经理在其他未完工项目任职，但未清楚界定本项目其他标段、"
            "不同项目类别及已获准变更等情形的适用范围。",
            "明确“其他未完工项目”的认定口径、是否包括本项目其他标段及可适用的例外，"
            "并列明核验材料和判断时点。",
        ),
        "contract-personnel-change-liability": (
            "项目经理变更条件与违约责任的衔接需明确",
            "同一合同条款涉及项目经理变更和违约处理，需说明客观变更事由、审批要求"
            "与违约责任之间的对应关系，避免将获准变更和违约情形混为一谈。",
            "列明可申请变更的事由、审批程序、替代人员条件及各自责任；"
            "明确仅在何种未履约情形下承担违约责任，并与被引用的主管部门文件保持一致。",
        ),
        "procedure-document-precedence": (
            "同一事项在招标文件中的冲突优先顺序需明确",
            "文件规定同一事项不一致时以编排顺序在后者为准，但未说明该规则与合同组成文件"
            "的专门顺序及澄清、补遗文件之间如何衔接。",
            "统一招标文件正文、合同组成文件以及澄清或补遗的适用顺序；"
            "写明适用对象和优先规则，避免仅以排版先后决定实质条款。",
        ),
        "evaluation-j-parameter": (
            "J值的设定依据与评分影响需明确",
            "评分条款允许招标人按项目情况自行设定J值，并规定触发后的商务标得分结果；"
            "设定范围、依据和计算影响需要在投标前明确。",
            "公布J值的取值范围、计算公式、适用条件及对商务标得分的影响，"
            "并核对其与评分表总分及其他报价评分项的一致性。",
        ),
        "evaluation-k-draw-process": (
            "K值抽取及计算过程需明确",
            "条款约定招标人在线抽取K值并据此计算F值，需让投标人能够确认抽取规则"
            "及其与评标基准价公式的对应关系。",
            "明确K值取值区间、抽取时点、参与人员、记录或见证方式及F值计算公式，"
            "并在评标办法中保持一致。",
        ),
        "technical-brand-post-award-lock": (
            "替代品牌未通过评审后的中标后处理需明确",
            "条款允许投标人提供替代品牌，但评审未通过后要求中标人改用推荐品牌且合同价格不调整。"
            "该处理发生在评标后的履约阶段，价格与责任如何衔接需要在投标前说清。",
            "在招标文件中明确替代品牌的客观评审标准、未通过时的合同处理和价格承担方式；"
            "不要把评标后才确定的品牌变更成本留给中标人自行承担。",
        ),
    }
    summary = summaries.get(family or "")
    if summary is not None:
        finding["title"], finding["description"], finding["recommendation"] = summary


def merge_duplicate_findings(
    findings: list[dict[str, Any]], *, issue_keys: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Merge the same issue on the exact same excerpt, preserving distinct same-paragraph risks.

    The discovery artifact keeps every original candidate; this projection only decides
    what the reviewer sees. Findings on different locators or with different stable
    problem keys are never merged. A merged finding keeps the union of rule/model sources,
    rule IDs, document evidence, legal references and conflict records.
    """
    stable_issue_keys = issue_keys or {}
    groups: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for finding in findings:
        excerpt = finding.get("source_excerpt") or {}
        family = _same_issue_family(finding)
        issue_key = (
            f"family:{family}"
            if family is not None
            else stable_issue_keys.get(str(finding.get("finding_id", "")))
        )
        if issue_key is None:
            title = re.sub(r"^待核验[：:]", "", str(finding.get("title", "")))
            issue_key = re.sub(r"[^\w\u4e00-\u9fff]", "", title).casefold()
        if not issue_key:
            issue_key = str(finding.get("finding_id", ""))
        group_key = (
            finding.get("category"),
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
        for item in group:
            current = score(item)
            if best is None or best_score is None or current > best_score:
                best = item
                best_score = current
        assert best is not None
        result: dict[str, Any] = dict(best)
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
        for item in group:
            for reference in item.get("evidence", []):
                identity = reference.get("evidence_id") or reference.get("source_hash")
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
            result["conflicts"] = conflicts
        result["review_status"] = "pending"
        _apply_family_summary(result, _same_issue_family(result))
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
