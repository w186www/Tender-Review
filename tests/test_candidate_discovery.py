"""Service boundary tests for authorization and immutable input pinning."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.domain.rules.models import DiscoveryDocumentRequest
from bidding_compliance.ingestion.schemas import Fragment
from bidding_compliance.persistence.database import make_engine, migrate
from bidding_compliance.persistence.models import (
    AuthSession,
    Document,
    DocumentContextVersion,
    DocumentSection,
    Project,
    Tenant,
    User,
)
from bidding_compliance.services import candidate_discovery


def test_service_requires_identity_and_reads_only_pinned_confirmed_content(monkeypatch):
    text = "投标人必须在本市注册。"
    fragment = Fragment(
        locator="paragraph:0",
        coordinate_system="ooxml",
        kind="paragraph",
        section="资格要求",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source="native",
    )
    calls = []
    principal = Principal("tenant-a", "reviewer", "reviewer", Role.REVIEWER, "session-a")
    document_sha = "a" * 64

    monkeypatch.setattr(
        candidate_discovery, "require_identity", lambda *_: calls.append("identity")
    )
    monkeypatch.setattr(
        candidate_discovery, "set_tenant", lambda _session, tenant: calls.append(("tenant", tenant))
    )
    monkeypatch.setattr(
        candidate_discovery,
        "find_project",
        lambda *_: SimpleNamespace(context={"region": "示例市"}, version=3),
    )
    monkeypatch.setattr(
        candidate_discovery.documents,
        "find_document",
        lambda *_: SimpleNamespace(
            status="ready",
            sha256=document_sha,
            parse_version=2,
            context_version=4,
            document_id="document-a",
            parse_provenance=None,
        ),
    )
    monkeypatch.setattr(
        candidate_discovery.documents,
        "context",
        lambda *_: SimpleNamespace(confirmed=True, version=4),
    )
    monkeypatch.setattr(
        candidate_discovery.documents,
        "sections",
        lambda *_: SimpleNamespace(
            parse_version=2,
            items=[
                SimpleNamespace(
                    source_hash=document_sha,
                    effective=fragment,
                    section_id="section-a",
                    revision=1,
                )
            ],
        ),
    )

    result = candidate_discovery.discover_for_project(
        object(),
        principal,
        "project-a",
        (
            DiscoveryDocumentRequest(
                document_id="document-a",
                raw_source_sha256=document_sha,
                parse_version=2,
                context_version=4,
            ),
        ),
        ("qualification_review",),
    )
    assert calls == ["identity", ("tenant", "tenant-a")]
    assert result.input_snapshot.documents[0].fragment_count == 1
    assert len(result.candidates) == 1
    assert result.candidates[0].source_excerpts[0].quote == text


def test_service_rejects_a_stale_document_before_reading_its_context(monkeypatch):
    principal = Principal("tenant-a", "reviewer", "reviewer", Role.REVIEWER, "session-a")
    monkeypatch.setattr(candidate_discovery, "require_identity", lambda *_: None)
    monkeypatch.setattr(candidate_discovery, "set_tenant", lambda *_: None)
    monkeypatch.setattr(
        candidate_discovery,
        "find_project",
        lambda *_: SimpleNamespace(context={}, version=1),
    )
    monkeypatch.setattr(
        candidate_discovery.documents,
        "find_document",
        lambda *_: SimpleNamespace(
            status="ready",
            sha256="a" * 64,
            parse_version=2,
            context_version=1,
            document_id="document-a",
        ),
    )
    monkeypatch.setattr(
        candidate_discovery.documents,
        "context",
        lambda *_: pytest.fail("stale request must be rejected before context read"),
    )
    with pytest.raises(FileExistsError, match="version changed"):
        candidate_discovery.discover_for_project(
            object(),
            principal,
            "project-a",
            (
                DiscoveryDocumentRequest(
                    document_id="document-a",
                    raw_source_sha256="b" * 64,
                    parse_version=2,
                    context_version=1,
                ),
            ),
            ("qualification_review",),
        )


def test_service_fails_closed_when_identity_is_revoked(monkeypatch):
    principal = Principal("tenant-a", "reviewer", "reviewer", Role.REVIEWER, "revoked")

    def revoked(*_):
        raise PermissionError("identity unavailable")

    monkeypatch.setattr(candidate_discovery, "require_identity", revoked)
    monkeypatch.setattr(
        candidate_discovery,
        "find_project",
        lambda *_: pytest.fail("revoked identity must not reach project reads"),
    )
    with pytest.raises(PermissionError, match="identity unavailable"):
        candidate_discovery.discover_for_project(
            object(),
            principal,
            "project-a",
            (
                DiscoveryDocumentRequest(
                    document_id="document-a",
                    raw_source_sha256="a" * 64,
                    parse_version=1,
                    context_version=1,
                ),
            ),
            ("qualification_review",),
        )


def test_confirmed_database_document_runs_through_real_service_and_all_skills(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite:///" + (tmp_path / "discovery.db").as_posix(),
        auth_signing_key=str(uuid4()) + str(uuid4()),
    )
    engine = make_engine(settings)
    migrate(engine)
    project = "project-discovery"
    session_id = "session-discovery"
    now = datetime.now(UTC)
    source = b"synthetic immutable source bytes"
    source_sha = hashlib.sha256(source).hexdigest()
    text = "投标人必须在本市注册。"
    fragment = Fragment(
        locator="paragraph:0",
        coordinate_system="ooxml",
        kind="paragraph",
        section="资格要求",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source="native",
    )
    with Session(engine) as db:
        db.add(Tenant(tenant_id="tenant-discovery", name="Synthetic", active=True))
        db.add(Tenant(tenant_id="tenant-other", name="Other", active=True))
        db.flush()
        db.add(
            User(
                tenant_id="tenant-discovery",
                user_id="reviewer-discovery",
                username="reviewer-discovery",
                password_hash=hashlib.sha256(b"synthetic only").hexdigest(),
                role="reviewer",
                active=True,
            )
        )
        db.flush()
        db.add(
            User(
                tenant_id="tenant-other",
                user_id="reviewer-other",
                username="reviewer-other",
                password_hash=hashlib.sha256(b"synthetic other credential").hexdigest(),
                role="reviewer",
                active=True,
            )
        )
        db.flush()
        db.add(
            AuthSession(
                tenant_id="tenant-discovery",
                session_id=session_id,
                user_id="reviewer-discovery",
                expires_at=now + timedelta(minutes=5),
                revoked=False,
            )
        )
        db.add(
            AuthSession(
                tenant_id="tenant-other",
                session_id="session-other",
                user_id="reviewer-other",
                expires_at=now + timedelta(minutes=5),
                revoked=False,
            )
        )
        db.add(
            Project(
                tenant_id="tenant-discovery",
                project_id=project,
                version=1,
                context={"region": "示例市"},
                created_by="reviewer-discovery",
                created_at=now,
            )
        )
        db.flush()
        principal = Principal(
            "tenant-discovery",
            "reviewer-discovery",
            "reviewer-discovery",
            Role.REVIEWER,
            session_id,
        )
        db.add(
            Document(
                tenant_id=principal.tenant_id,
                document_id="document-discovery",
                project_id=project,
                status="ready",
                sha256=source_sha,
                object_ref="unused-test-object",
                file_format="docx",
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size_bytes=len(source),
                parse_version=1,
                context_version=1,
                issues=[],
            )
        )
        db.add(
            DocumentSection(
                tenant_id=principal.tenant_id,
                document_id="document-discovery",
                section_id="section-discovery",
                ordinal=0,
                automatic=fragment.model_dump(mode="json"),
                revision=1,
            )
        )
        db.add(
            DocumentContextVersion(
                tenant_id=principal.tenant_id,
                document_id="document-discovery",
                version=1,
                payload={
                    "document_id": "document-discovery",
                    "version": 1,
                    "candidates": [],
                    "confirmed": True,
                },
                changed_by=principal.user_id,
                changed_at=datetime.now(UTC),
            )
        )
        db.flush()
        result = candidate_discovery.discover_for_project(
            db,
            principal,
            project,
            (
                DiscoveryDocumentRequest(
                    document_id="document-discovery",
                    raw_source_sha256=source_sha,
                    parse_version=1,
                    context_version=1,
                ),
            ),
        )
        auth_session = db.get(AuthSession, (principal.tenant_id, principal.session_id))
        assert auth_session is not None
        auth_session.revoked = True
        db.flush()
        with pytest.raises(PermissionError):
            candidate_discovery.discover_for_project(
                db,
                principal,
                project,
                (
                    DiscoveryDocumentRequest(
                        document_id="document-discovery",
                        raw_source_sha256=source_sha,
                        parse_version=1,
                        context_version=1,
                    ),
                ),
            )
        other_principal = Principal(
            "tenant-other", "reviewer-other", "reviewer-other", Role.REVIEWER, "session-other"
        )
        with pytest.raises(LookupError, match="unavailable"):
            candidate_discovery.discover_for_project(
                db,
                other_principal,
                project,
                (
                    DiscoveryDocumentRequest(
                        document_id="document-discovery",
                        raw_source_sha256=source_sha,
                        parse_version=1,
                        context_version=1,
                    ),
                ),
            )
    assert result.status == "completed"
    assert len(result.candidates) == 1
    assert len(result.skill_coverages) == 5
    assert len(result.retrieval_topics) == 5
    candidate = result.candidates[0]
    assert candidate.source_excerpts[0].document_sha256 == source_sha
    assert candidate.source_excerpts[0].quote_sha256 == hashlib.sha256(text.encode()).hexdigest()
    engine.dispose()
