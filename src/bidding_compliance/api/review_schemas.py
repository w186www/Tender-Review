"""Closed request/response contracts for manual review and report APIs."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DecisionRequest(Closed):
    decision: Literal["accept", "modify", "reject"]
    expected_snapshot_hash: str = Field(pattern="^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=2000)
    modified_finding: dict[str, Any] | None = None


class DecisionResponse(Closed):
    decision_id: str
    review_task_id: str
    run_id: str
    finding_id: str
    decision: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    reason: str
    reviewer_id: str
    request_id: str
    request_trace_id: str | None
    decided_at: str


class ReviewFindings(Closed):
    review_task_id: str
    run_id: str
    snapshot_hash: str
    status: str
    findings: list[dict[str, Any]]
    pending_finding_ids: list[str]


class ReviewHistory(Closed):
    review_task_id: str
    run_id: str
    decisions: list[DecisionResponse]


class ReportMetadata(Closed):
    report_id: str
    report_content_id: str
    result_id: str
    format: Literal["docx", "pdf"]
    template_version: str
    snapshot_hash: str
    content_hash: str
    created_at: str
