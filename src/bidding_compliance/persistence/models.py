"""Core persistence contracts. No relationships silently load unscoped business data."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenant"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username"),
        CheckConstraint("role IN ('admin','reviewer','auditor','operator')"),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.tenant_id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthSession(Base):
    __tablename__ = "auth_session"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["app_user.tenant_id", "app_user.user_id"]),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base):
    __tablename__ = "project"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "created_by"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        CheckConstraint("version >= 1"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectVersion(Base):
    __tablename__ = "project_version"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.project_id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "changed_by"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        CheckConstraint("version >= 1"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_by: Mapped[str] = mapped_column(String(64))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["app_user.tenant_id", "app_user.user_id"]),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.project_id"]
        ),
        UniqueConstraint("tenant_id", "project_id", "document_id"),
        CheckConstraint(
            "status IN ('quarantined','accepted','rejected','parsing','needs_review',"
            "'needs_confirmation','ready','failed')",
            name="ck_document_status",
        ),
        CheckConstraint("length(sha256) = 64"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64))
    object_ref: Mapped[str] = mapped_column(String(1000))
    file_format: Mapped[str] = mapped_column(String(10), default="pdf", server_default="pdf")
    media_type: Mapped[str] = mapped_column(
        String(100), default="application/pdf", server_default="application/pdf"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parse_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    context_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    issues: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    parse_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_job"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "document_id"],
            ["document.tenant_id", "document.project_id", "document.document_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submitted_by"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        UniqueConstraint("tenant_id", "project_id", "submitted_by", "key_hash"),
        CheckConstraint("status IN ('queued','running','succeeded','failed')"),
        CheckConstraint("attempts >= 0 AND attempts <= 3"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64))
    submitted_by: Mapped[str] = mapped_column(String(64))
    key_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    lease_id: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentSection(Base):
    __tablename__ = "document_section"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["document.tenant_id", "document.document_id"]
        ),
        UniqueConstraint("tenant_id", "document_id", "ordinal"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    section_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    automatic: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)


class SectionRevision(Base):
    __tablename__ = "section_revision"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id", "section_id"],
            [
                "document_section.tenant_id",
                "document_section.document_id",
                "document_section.section_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "changed_by"], ["app_user.tenant_id", "app_user.user_id"]
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    section_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_by: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(1000))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentContextVersion(Base):
    __tablename__ = "document_context_version"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["document.tenant_id", "document.document_id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "changed_by"], ["app_user.tenant_id", "app_user.user_id"]
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_by: Mapped[str] = mapped_column(String(64))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewTask(Base):
    __tablename__ = "review_task"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.project_id"]
        ),
        CheckConstraint(
            "status IN ('queued','running','waiting_human','succeeded','failed','cancelled')"
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),)
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(36))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LegalRetrievalRun(Base):
    __tablename__ = "legal_retrieval_run"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["project.tenant_id", "project.project_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["app_user.tenant_id", "app_user.user_id"],
        ),
        CheckConstraint("context_version >= 1"),
        CheckConstraint("length(request_hash) = 64 AND length(result_hash) = 64"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    context_version: Mapped[int] = mapped_column(Integer)
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewEngineRun(Base):
    """Mutable lifecycle pointer to an immutable, hash-pinned review input snapshot."""

    __tablename__ = "review_engine_run"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "review_task_id"],
            ["review_task.tenant_id", "review_task.review_task_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "project_id"], ["project.tenant_id", "project.project_id"]
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]),
        CheckConstraint(
            "status IN ('queued','running','waiting_human','result_published','failed','cancelled')"
        ),
        CheckConstraint("length(snapshot_hash) = 64"),
        CheckConstraint("length(request_hash) = 64"),
        CheckConstraint("retry_count BETWEEN 0 AND 2"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    publication_id: Mapped[str | None] = mapped_column(String(36))
    revision_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewArtifact(Base):
    """Content-addressed, append-only storage; graph state contains only its reference."""

    __tablename__ = "review_artifact"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "review_task_id", "run_id"],
            [
                "review_engine_run.tenant_id",
                "review_engine_run.review_task_id",
                "review_engine_run.run_id",
            ],
        ),
        CheckConstraint("length(content_hash) = 64"),
        CheckConstraint("length(CAST(content AS TEXT)) <= 20000000"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_task_id: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewDecision(Base):
    """An authenticated human decision bound to an immutable run snapshot."""

    __tablename__ = "review_decision"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "review_task_id", "run_id"],
            [
                "review_engine_run.tenant_id",
                "review_engine_run.review_task_id",
                "review_engine_run.run_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        UniqueConstraint("tenant_id", "reviewer_id", "request_id"),
        UniqueConstraint("tenant_id", "review_task_id", "run_id", "finding_id"),
        CheckConstraint("decision IN ('accept','modify','reject','confirm_no_findings')"),
        CheckConstraint("length(snapshot_hash) = 64"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review_task_id: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(36))
    finding_id: Mapped[str] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(24))
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    modified_finding: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64))
    request_trace_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(String(2000))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewResult(Base):
    """Database-only immutable publication boundary with cross-process idempotency."""

    __tablename__ = "review_result"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "review_task_id", "run_id"],
            [
                "review_engine_run.tenant_id",
                "review_engine_run.review_task_id",
                "review_engine_run.run_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        UniqueConstraint("tenant_id", "review_task_id", "run_id", "snapshot_hash"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        CheckConstraint("length(snapshot_hash) = 64 AND length(content_hash) = 64"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review_task_id: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(36))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewReportContent(Base):
    """One immutable structured report version shared by all rendered formats."""

    __tablename__ = "review_report_content"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "result_id"], ["review_result.tenant_id", "review_result.result_id"]
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]),
        UniqueConstraint("tenant_id", "result_id", "template_version"),
        CheckConstraint("length(snapshot_hash) = 64 AND length(content_hash) = 64"),
        CheckConstraint("length(CAST(content AS TEXT)) <= 20000000"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_content_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36))
    template_version: Mapped[str] = mapped_column(String(32))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    actor_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewReport(Base):
    """Immutable, content-addressed Word/PDF products of one published result."""

    __tablename__ = "review_report"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "result_id"], ["review_result.tenant_id", "review_result.result_id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "report_content_id"],
            ["review_report_content.tenant_id", "review_report_content.report_content_id"],
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]),
        UniqueConstraint("tenant_id", "result_id", "format", "template_version"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        CheckConstraint("format IN ('docx','pdf')"),
        CheckConstraint("length(snapshot_hash) = 64 AND length(content_hash) = 64"),
        CheckConstraint("length(content) > 0 AND length(content) <= 20000000"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    result_id: Mapped[str] = mapped_column(String(36))
    report_content_id: Mapped[str] = mapped_column(String(36))
    format: Mapped[str] = mapped_column(String(8))
    template_version: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    actor_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# LangGraph's PostgreSQL checkpointer owns these tables at runtime. Keep them in
# the canonical metadata because the explicit Alembic migration creates them and
# schema-drift checks compare the database against Base.metadata.
_CHECKPOINT_JSON = JSON().with_variant(JSONB(), "postgresql")
Table(
    "checkpoint_migrations",
    Base.metadata,
    Column("v", Integer, primary_key=True, nullable=False),
)
Table(
    "checkpoints",
    Base.metadata,
    Column("thread_id", Text, primary_key=True, nullable=False),
    Column("checkpoint_ns", Text, primary_key=True, server_default="", nullable=False),
    Column("checkpoint_id", Text, primary_key=True, nullable=False),
    Column("parent_checkpoint_id", Text),
    Column("type", Text),
    Column("checkpoint", _CHECKPOINT_JSON, nullable=False),
    Column("metadata", _CHECKPOINT_JSON, server_default="{}", nullable=False),
    Index("checkpoints_thread_id_idx", "thread_id"),
)
Table(
    "checkpoint_blobs",
    Base.metadata,
    Column("thread_id", Text, primary_key=True, nullable=False),
    Column("checkpoint_ns", Text, primary_key=True, server_default="", nullable=False),
    Column("channel", Text, primary_key=True, nullable=False),
    Column("version", Text, primary_key=True, nullable=False),
    Column("type", Text, nullable=False),
    Column("blob", LargeBinary),
    Index("checkpoint_blobs_thread_id_idx", "thread_id"),
)
Table(
    "checkpoint_writes",
    Base.metadata,
    Column("thread_id", Text, primary_key=True, nullable=False),
    Column("checkpoint_ns", Text, primary_key=True, server_default="", nullable=False),
    Column("checkpoint_id", Text, primary_key=True, nullable=False),
    Column("task_id", Text, primary_key=True, nullable=False),
    Column("idx", Integer, primary_key=True, nullable=False),
    Column("channel", Text, nullable=False),
    Column("type", Text),
    Column("blob", LargeBinary, nullable=False),
    Column("task_path", Text, server_default="", nullable=False),
    Index("checkpoint_writes_thread_id_idx", "thread_id"),
)


class LegalOperatorGrant(Base):
    __tablename__ = "legal_operator_grant"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "user_id"], ["app_user.tenant_id", "app_user.user_id"]),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean)
    capabilities: Mapped[list[str]] = mapped_column(JSON)


class LegalCorpusRevision(Base):
    __tablename__ = "legal_corpus_revision"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_tenant", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        UniqueConstraint("draft_sequence"),
        UniqueConstraint("actor_tenant", "actor_id", "request_id"),
        CheckConstraint("draft_sequence >= 1"),
        CheckConstraint("operation IN ('ingest','verify')"),
        CheckConstraint(
            "length(content_hash) = 64 AND length(index_hash) = 64 AND length(request_hash) = 64"
        ),
    )
    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("legal_corpus_revision.revision_id"))
    draft_sequence: Mapped[int] = mapped_column(Integer)
    actor_tenant: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    index_hash: Mapped[str] = mapped_column(String(64))
    bundle: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LegalPublication(Base):
    __tablename__ = "legal_publication"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_tenant", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        UniqueConstraint("sequence"),
        UniqueConstraint("actor_tenant", "actor_id", "request_id"),
        CheckConstraint("sequence >= 1"),
        CheckConstraint("operation IN ('publish','disable','rollback')"),
        CheckConstraint("length(request_hash) = 64"),
        CheckConstraint(
            "(operation = 'disable' AND revision_id IS NULL) OR "
            "(operation != 'disable' AND revision_id IS NOT NULL)"
        ),
        CheckConstraint(
            "(operation = 'rollback' AND target_id IS NOT NULL) OR "
            "(operation != 'rollback' AND target_id IS NULL)"
        ),
    )
    publication_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[str | None] = mapped_column(ForeignKey("legal_publication.publication_id"))
    target_id: Mapped[str | None] = mapped_column(ForeignKey("legal_publication.publication_id"))
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("legal_corpus_revision.revision_id"))
    actor_tenant: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LegalCorpusState(Base):
    __tablename__ = "legal_corpus_state"
    __table_args__ = (CheckConstraint("singleton = 1 AND sequence >= 0 AND draft_sequence >= 0"),)
    singleton: Mapped[int] = mapped_column(Integer, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)
    publication_id: Mapped[str | None] = mapped_column(
        ForeignKey("legal_publication.publication_id")
    )
    draft_sequence: Mapped[int] = mapped_column(Integer)
    draft_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("legal_corpus_revision.revision_id")
    )


class ReviewConfigurationRevision(Base):
    """Immutable tenant-scoped release of existing legal/rule/skill/model identities."""

    __tablename__ = "review_configuration_revision"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]),
        ForeignKeyConstraint(
            ["tenant_id", "parent_revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        UniqueConstraint("tenant_id", "revision_sequence"),
        UniqueConstraint("tenant_id", "actor_id", "request_id"),
        CheckConstraint("revision_sequence >= 1"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64"),
        CheckConstraint("length(CAST(snapshot AS TEXT)) <= 1000000"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_sequence: Mapped[int] = mapped_column(Integer)
    parent_revision_id: Mapped[str | None] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewConfigurationEvent(Base):
    """Append-only lifecycle event; state pointers are changed only with a matching event."""

    __tablename__ = "review_configuration_event"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]),
        ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "previous_active_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "active_revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        UniqueConstraint("tenant_id", "sequence"),
        UniqueConstraint("tenant_id", "actor_id", "request_id"),
        CheckConstraint("sequence >= 1 AND expected_sequence >= 0"),
        CheckConstraint("operation IN ('draft','publish','disable','rollback')"),
        CheckConstraint("length(request_hash) = 64"),
        CheckConstraint("(operation IN ('disable','draft') OR active_revision_id IS NOT NULL)"),
        CheckConstraint(
            "(operation = 'disable' AND revision_id IS NULL) OR "
            "(operation != 'disable' AND revision_id IS NOT NULL)"
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(20))
    revision_id: Mapped[str | None] = mapped_column(String(36))
    previous_active_id: Mapped[str | None] = mapped_column(String(36))
    active_revision_id: Mapped[str | None] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    expected_sequence: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewConfigurationState(Base):
    """Mutable per-tenant CAS pointers to immutable configuration revisions/events."""

    __tablename__ = "review_configuration_state"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"]),
        ForeignKeyConstraint(
            ["tenant_id", "active_revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "draft_revision_id"],
            [
                "review_configuration_revision.tenant_id",
                "review_configuration_revision.revision_id",
            ],
        ),
        CheckConstraint("sequence >= 0 AND draft_sequence >= 0"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    active_revision_id: Mapped[str | None] = mapped_column(String(36))
    draft_sequence: Mapped[int] = mapped_column(Integer, default=0)
    draft_revision_id: Mapped[str | None] = mapped_column(String(36))


class LegalLawIdentity(Base):
    __tablename__ = "legal_law_identity"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_tenant", "actor_id"], ["app_user.tenant_id", "app_user.user_id"]
        ),
        CheckConstraint("operation IN ('ingest','verify')"),
    )
    title_key: Mapped[str] = mapped_column(String(500), primary_key=True)
    law_id: Mapped[str] = mapped_column(String(128))
    actor_tenant: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(20))
