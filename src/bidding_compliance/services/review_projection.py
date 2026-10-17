"""Coverage, unknown-call and duplicate-finding projections for review outputs."""

from __future__ import annotations

import json
from typing import Any

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_EVIDENCE_ORDER = {
    "insufficient_evidence": 0,
    "candidate": 1,
    "suspected": 2,
    "confirmed": 3,
}


def merge_duplicate_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge findings that point at the exact same original excerpt.

    The discovery artifact keeps every original candidate; this projection only decides
    what the reviewer sees. Findings on different locators are never merged, even when
    their titles look similar, because that would require a semantic judgement the server
    cannot make deterministically. A merged finding keeps the union of rule/model sources,
    rule IDs, document evidence, legal references and conflict records.
    """
    groups: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for finding in findings:
        excerpt = finding.get("source_excerpt") or {}
        group_key = (
            finding.get("category"),
            excerpt.get("source_hash"),
            excerpt.get("locator"),
            excerpt.get("quote"),
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
        result["sources"] = sorted(
            {source for item in group for source in item.get("sources", [])}
        )
        result["rule_ids"] = sorted(
            {rule for item in group for rule in item.get("rule_ids", [])}
        )
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
                    reference.get("selected_by_model")
                    and not previous.get("selected_by_model")
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
    unprocessed_sections = sum(
        int(item.get("section_count", 0) or 0)
        for item in batches or []
        if isinstance(item, dict) and item.get("status") in {"saturated", "partial"}
    )
    partial = saturated_batches > 0 or partial_batches > 0
    reasons: list[str] = []
    if saturated_batches:
        reasons.append("discovery_saturated")
    if partial_batches:
        reasons.append("discovery_partial")
    if unknown_count:
        reasons.append("model_call_outcome_unknown")
    return {
        "completion_status": "partial" if partial or unknown_count else "complete",
        "coverage_status": "partial" if partial else "complete",
        "unprocessed_units": unprocessed_sections,
        "truncated": saturated_batches > 0,
        "saturated": saturated_batches > 0,
        "reason_codes": reasons or ["discovery_complete"],
        "unknown_model_call_count": unknown_count,
    }
