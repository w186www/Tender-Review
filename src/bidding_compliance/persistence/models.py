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
            "status IN ('quarantined','accepted','rejected','parsing','ready','failed')"
        ),
        CheckConstraint("length(sha256) = 64"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64))
    object_ref: Mapped[str] = mapped_column(String(1000))


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
