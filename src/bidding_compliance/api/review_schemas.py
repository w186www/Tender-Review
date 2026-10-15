"""Closed request/response contracts for manual review and report APIs."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DecisionRequest(Closed):
    decision: Literal["accept", "modify", "reject", "confirm_no_findings"]
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


class CitationLocation(Closed):
    document_id: str
    raw_source_sha256: str
    parse_version: int
    section_id: str
    section_revision: int
    locator: str
    page: int | None
    coordinate_system: Literal["pdf_points", "image_pixels", "ooxml"]
    bbox: list[float] | None
    quote: str
    quote_sha256: str


class ReviewCitations(Closed):
    items: list[CitationLocation]


class ReportMetadata(Closed):
    report_id: str
    report_content_id: str
    result_id: str
    format: Literal["docx", "pdf"]
    template_version: str
    snapshot_hash: str
    content_hash: str
    created_at: str


class CreateReviewRequest(Closed):
    document_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("document_ids")
    @classmethod
    def unique_documents(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("document_ids must be unique")
        return value


class ModelRuntime(Closed):
    execution_mode: Literal["real-qwen", "offline-deterministic", "unknown"]
    provider: str | None
    model: str | None
    response_received: bool
    model_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_cny: float
    skill_candidate_count: int
    model_candidate_count: int
    embedding_model: str | None
    vector_index_build_id: str | None


class ReviewTaskResponse(Closed):
    review_task_id: str
    project_id: str
    run_id: str
    status: Literal["queued", "running", "waiting_human", "result_published", "failed", "cancelled"]
    snapshot_hash: str
    retry_count: int
    failure_code: str | None
    result_id: str | None
    created_at: str
    model_runtime: ModelRuntime | None = None


class ReviewTaskList(Closed):
    items: list[ReviewTaskResponse]
    offset: int
    limit: int
    total: int


class PendingReviewItem(Closed):
    review_task_id: str
    run_id: str
    project_id: str
    snapshot_hash: str
    status: Literal["waiting_human"]
    created_at: str


class PendingReviewList(Closed):
    items: list[PendingReviewItem]
    offset: int
    limit: int


class ReportList(Closed):
    items: list[ReportMetadata]


class AuditEventResponse(Closed):
    event_id: str
    actor_id: str | None
    action: str
    resource_id: str | None
    request_id: str
    occurred_at: str


class AuditEventList(Closed):
    items: list[AuditEventResponse]
    offset: int
    limit: int
    total: int
