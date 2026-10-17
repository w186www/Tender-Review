"""Coverage and unknown-call projections shared by review APIs and immutable reports."""

from __future__ import annotations

from typing import Any


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
