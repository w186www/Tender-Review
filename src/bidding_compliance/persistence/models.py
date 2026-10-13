"""Core persistence contracts. No relationships silently load unscoped business data."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
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
            ["tenant_id", "project_id"], ["project.tenant_id", "project.project_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_id"], ["app_user.tenant_id", "app_user.user_id"],
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
