"""TASK-0006 corrective acceptance: administrative contexts and durable provenance."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_legal_retrieval import query, version

from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.legal.contracts import LegalManifest, RetrievalResult
from bidding_compliance.legal.corpus import ingest
from bidding_compliance.legal.hashing import canonical_hash
from bidding_compliance.legal.regions import normalize_region
from bidding_compliance.legal.retrieval import CharacterEmbedding, LegalRetriever
from bidding_compliance.persistence.database import make_engine, migrate
from bidding_compliance.persistence.models import (
    AuditEvent,
    AuthSession,
    Base,
    LegalRetrievalRun,
    Project,
    Tenant,
    User,
)
from bidding_compliance.services import legal


@pytest.fixture
def system(tmp_path):
    engine = make_engine(Settings(
        _env_file=None, app_env="test", database_url="sqlite:///" + str(tmp_path / "runs.db"),
    ))
    # Verify a real incremental upgrade instead of creating ORM tables.
    migrate(engine, "202610131300")
    with Session(engine) as db:
        now = datetime.now(UTC)
        for tenant in ("a", "b"):
            db.add(Tenant(tenant_id=tenant, name=tenant, active=True))
        db.flush()
        for tenant in ("a", "b"):
            db.add(User(tenant_id=tenant, user_id="u", username="u", role="reviewer",
                        password_hash=str(uuid4()), active=True))
        db.flush()
        for tenant in ("a", "b"):
            db.add(AuthSession(tenant_id=tenant, user_id="u", session_id="s",
                               expires_at=now + timedelta(hours=1), revoked=False))
            db.add(Project(tenant_id=tenant, project_id="p", version=1, created_by="u",
                           created_at=now, context=dict(region="福建省福州市",
                           procurement_type="government", project_type="works", name=tenant)))
        db.commit()
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    index = ingest(tmp_path, LegalManifest(versions=(version(tmp_path),)))

    class Counting(CharacterEmbedding):
        calls = 0

        def encode(self, texts):
            self.calls += 1
            return super().encode(texts)

    adapter = Counting()
    yield engine, LegalRetriever(index, adapter), adapter
    engine.dispose()


def principal(tenant="a"):
    return Principal(tenant, "u", "u", Role.REVIEWER, "s")


def retrieve(db, retriever, day=date(2026, 10, 14)):
    return legal.retrieve_for_project(db, principal(), "p", retriever,
                                      text="投标保证金", review_date=day)


@pytest.mark.parametrize("region,expected", [
    ("CN", "CN"), ("福建省", "CN/福建"), ("福建省福州市", "CN/福建/福州"),
    ("CN/福建省/福州市", "CN/福建/福州"), ("CN/福建/福州", "CN/福建/福州"),
    ("广州", "CN/广东/广州"), ("广西壮族自治区", "CN/广西"),
])
def test_registered_region_normalization(region, expected):
    assert normalize_region(region) == expected
    assert query(region=region).region == expected


@pytest.mark.parametrize("region", [
    "", "福建省外", "CN/不存在", "CN/广东/福州", "CN/福建/福州/鼓楼", "CN/福建/未知市",
])
def test_unknown_regions_fail_explicitly(region):
    with pytest.raises(ValueError, match="REGION_UNMAPPED"):
        normalize_region(region)
    with pytest.raises(ValidationError):
        query(region=region)


@pytest.mark.parametrize("region", ["无法映射", "CN/广东/福州", None])
def test_invalid_project_region_persisted_without_embedding(system, region):
    engine, retriever, adapter = system
    with Session(engine) as db:
        project = db.get(Project, ("a", "p"))
        project.context = {**project.context, "region": region}
        db.commit()
        result = retrieve(db, retriever)
        assert result.status == "context_incomplete" and result.context_error == "REGION_UNMAPPED"
        assert result.query is None and not result.hits
        assert result.excluded[0].reasons == ("context_incomplete",)
        assert adapter.calls == 0
        assert legal.read_run(db, principal(), result.run_snapshot.run_id) == result
        assert len(list(db.scalars(select(AuditEvent)))) == 1


def test_two_dates_and_context_change_are_frozen_across_sessions(system):
    engine, retriever, _ = system
    with Session(engine) as db:
        first = retrieve(db, retriever)
        second = retrieve(db, retriever, date(2026, 10, 15))
        assert first.hits and not second.hits
        assert first.run_snapshot.run_id != second.run_snapshot.run_id
        project = db.get(Project, ("a", "p"))
        project.context = {**project.context, "region": "广东省"}
        project.version = 2
        db.commit()
        third = retrieve(db, retriever)
        assert third.query.region == "CN/广东" and not third.hits
    with Session(engine) as db:
        assert legal.read_run(db, principal(), first.run_snapshot.run_id) == first
        assert legal.read_run(db, principal(), second.run_snapshot.run_id) == second
        row = db.get(LegalRetrievalRun, ("a", first.run_snapshot.run_id))
        assert row.request_snapshot["context"]["region"] == "福建省福州市"
        assert row.request_snapshot["context_version"] == 1
        assert row.request_snapshot["review_date_source"] == "explicit_actor_input"
        assert row.request_snapshot["actor_id"] == "u"
        assert canonical_hash(row.request_snapshot) == row.request_hash
        assert canonical_hash(row.result) == row.result_hash


def test_run_read_cross_tenant_and_revocation(system):
    engine, retriever, adapter = system
    with Session(engine) as db:
        result = retrieve(db, retriever)
        run_id = result.run_snapshot.run_id
        with pytest.raises(LookupError):
            legal.read_run(db, principal("b"), run_id)
        auth = db.get(AuthSession, ("a", "s"))
        auth.revoked = True
        db.commit()
        with pytest.raises(PermissionError):
            legal.read_run(db, principal(), run_id)
        with pytest.raises(PermissionError):
            retrieve(db, retriever)
        assert adapter.calls == 1


@pytest.mark.parametrize("action", ["update", "delete"])
def test_runtime_history_is_append_only(system, action):
    engine, retriever, _ = system
    with Session(engine) as db:
        result = retrieve(db, retriever)
        statement = update(LegalRetrievalRun).values(context_version=9) if action == "update" else (
            delete(LegalRetrievalRun)
        )
        with pytest.raises(IntegrityError, match="append-only"):
            db.execute(statement)
        db.rollback()
        assert legal.read_run(db, principal(), result.run_snapshot.run_id) == result


@pytest.mark.parametrize("part", ["request", "result", "association"])
def test_read_integrity_checks_reject_tampered_snapshots(system, part):
    engine, retriever, _ = system
    with Session(engine) as db:
        result = retrieve(db, retriever)
        row = db.get(LegalRetrievalRun, ("a", result.run_snapshot.run_id))
        if part == "request":
            row.request_snapshot = deepcopy(row.request_snapshot)
            row.request_snapshot["context"]["name"] = "altered"
        elif part == "result":
            row.result = deepcopy(row.result)
            row.result["hits"][0]["quote"] = "altered"
        else:
            # Even recomputed digests cannot silently bind a new date to the old query.
            row.request_snapshot = deepcopy(row.request_snapshot)
            row.request_snapshot["request"]["review_date"] = "2026-10-13"
            row.request_hash = canonical_hash(row.request_snapshot)
            row.result = deepcopy(row.result)
            row.result["run_snapshot"]["request_hash"] = row.request_hash
            row.result_hash = canonical_hash(row.result)
        with pytest.raises(ValueError, match="mismatch"):
            legal.validate_run(row)
        db.rollback()


def test_run_and_audit_are_atomic(system, monkeypatch):
    engine, retriever, _ = system

    def failing_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(legal, "audit", failing_audit)
    with Session(engine) as db:
        with pytest.raises(RuntimeError, match="audit failure"):
            retrieve(db, retriever)
        assert list(db.scalars(select(LegalRetrievalRun))) == []
        assert list(db.scalars(select(AuditEvent))) == []


@pytest.mark.parametrize("day,expected_reason", [
    ("2019-12-31", "not_yet_effective"), ("2026-10-14", "expired"),
    ("2026-10-15", "expired"),
])
def test_excluded_time_boundaries(tmp_path, day, expected_reason):
    index = ingest(tmp_path, LegalManifest(versions=(version(
        tmp_path, effective_to="2026-10-14",
    ),)))
    result = LegalRetriever(index).search(query(review_date=day))
    assert not result.hits
    assert expected_reason in result.excluded[0].reasons


def test_start_and_pre_end_are_current_not_historical(tmp_path):
    index = ingest(tmp_path, LegalManifest(versions=(version(
        tmp_path, effective_to="2026-10-14",
    ),)))
    for day in ("2020-01-01", "2026-10-13"):
        result = LegalRetriever(index).search(query(review_date=day))
        assert result.hits[0].version_status == "verified_current"


def test_excluded_scope_and_unverified_are_both_visible(tmp_path):
    index = ingest(tmp_path, LegalManifest(versions=(version(
        tmp_path, verification="unverified", verified_through=None,
    ),)))
    result = LegalRetriever(index).search(query(region="CN/广东", procurement_type="enterprise"))
    assert not result.hits
    assert set(result.excluded[0].reasons) == {
        "jurisdiction_mismatch", "procurement_mismatch", "unverified",
    }


@pytest.mark.parametrize("change", [
    {"context_error": "CONTEXT_INVALID"},
    {"status": "context_incomplete", "context_error": "REGION_UNMAPPED"},
    {"schema_version": "v1alpha1"},
])
def test_result_contradictions_and_old_version_rejected(tmp_path, change):
    index = ingest(tmp_path, LegalManifest(versions=(version(tmp_path),)))
    payload = LegalRetriever(index).search(query()).model_dump(mode="json")
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate({**payload, **change})
