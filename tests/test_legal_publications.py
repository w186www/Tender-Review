"""D02/D05: immutable revisions, public snapshots, CAS, idempotency and rollback are real."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_legal_retrieval import version
from test_legal_runs import principal
from test_legal_runs import system as base_fixture

from bidding_compliance.legal.contracts import LegalManifest, LegalVersion
from bidding_compliance.legal.management_contracts import (
    CorpusBundle,
    PublicationRequest,
    RevisionRequest,
    VerificationSource,
)
from bidding_compliance.persistence.models import (
    AuditEvent,
    AuthSession,
    LegalCorpusRevision,
    LegalCorpusState,
    LegalLawIdentity,
    LegalOperatorGrant,
    LegalPublication,
    LegalRetrievalRun,
)
from bidding_compliance.services import legal
from bidding_compliance.services import legal_management as management

_base_system = base_fixture


@pytest.fixture
def system(_base_system, tmp_path):
    engine, _, _ = _base_system
    with Session(engine) as db:
        for tenant in ("a", "b"):
            db.add(
                LegalOperatorGrant(
                    tenant_id=tenant,
                    user_id="u",
                    active=True,
                    capabilities=["ingest", "verify", "publish", "disable", "rollback"],
                )
            )
        db.commit()
    public = tmp_path / "knowledge/legal"
    public.mkdir(parents=True)
    metadata = version(public)
    metadata = LegalVersion.model_validate(
        {
            **metadata.model_dump(),
            "text_path": "knowledge/legal/law.txt",
            "source_snapshot_path": "knowledge/legal/law.txt",
        }
    )
    return engine, tmp_path, metadata


def request(metadata, sequence=0, **changes):
    proof = VerificationSource(
        law_id=metadata.law_id,
        version=metadata.version,
        source_uri=metadata.source_uri,
        path=metadata.source_snapshot_path,
        source_hash=metadata.source_hash,
        captured_on=metadata.captured_on,
    )
    return RevisionRequest(
        **{
            "request_id": str(uuid4()),
            "expected_draft_sequence": sequence,
            "reason": "synthetic test verification",
            "verification_sources": (proof,),
            **changes,
        }
    )


def revision(db, root, metadata, sequence=0, **changes):
    return management.create_revision(
        db,
        principal(),
        root,
        LegalManifest(versions=(metadata,)),
        request(metadata, sequence, **changes),
    )


def publish_request(revision_id, draft_sequence=1, sequence=0, **changes):
    return PublicationRequest(
        **{
            "request_id": str(uuid4()),
            "expected_sequence": sequence,
            "expected_draft_sequence": draft_sequence,
            "operation": "publish",
            "revision_id": revision_id,
            "reason": "synthetic publication",
            **changes,
        }
    )


def test_same_text_verification_changes_create_new_immutable_revision(system):
    engine, root, metadata = system
    with Session(engine) as db:
        first = revision(db, root, metadata)
        second = revision(
            db, root, metadata.model_copy(update={"verification_note": "new review"}), 1
        )
        assert first.revision_id != second.revision_id
        assert second.parent_id == first.revision_id
        assert first.content_hash != second.content_hash
        assert first.bundle["index"]["manifest"]["versions"][0]["text_hash"] == metadata.text_hash
        assert len(list(db.scalars(select(LegalCorpusRevision)))) == 2


def test_source_change_cannot_escape_stable_identity_or_version_conflict(system):
    engine, root, metadata = system
    with Session(engine) as db:
        first = revision(db, root, metadata)
        changed = metadata.model_copy(update={"source_uri": "https://other.gov.cn/law"})
        second = revision(db, root, changed, 1)
        assert second.parent_id == first.revision_id
        with pytest.raises(ValueError, match="identity"):
            revision(db, root, changed.model_copy(update={"law_id": "changed-identity"}), 2)
        with pytest.raises(ValidationError):
            LegalManifest(versions=(metadata, changed.model_copy(update={"version": "2"})))


def test_idempotent_revision_and_publication_do_not_duplicate_side_effects(system):
    engine, root, metadata = system
    with Session(engine) as db:
        req = request(metadata)
        first = management.create_revision(
            db, principal(), root, LegalManifest(versions=(metadata,)), req
        )
        again = management.create_revision(
            db, principal(), root, LegalManifest(versions=(metadata,)), req
        )
        assert first.revision_id == again.revision_id
        pub_req = publish_request(first.revision_id)
        pub = management.publish(db, principal(), pub_req)
        assert management.publish(db, principal(), pub_req).publication_id == pub.publication_id
        assert len(list(db.scalars(select(LegalPublication)))) == 1
        assert len(list(db.scalars(select(AuditEvent)))) == 2
        with pytest.raises(FileExistsError, match="idempotency"):
            management.publish(db, principal(), pub_req.model_copy(update={"reason": "changed"}))


def test_concurrent_verification_has_one_cas_winner_and_no_orphans(system):
    engine, root, metadata = system

    def create(_):
        with Session(engine) as db:
            try:
                row = revision(db, root, metadata)
                return row.revision_id
            except FileExistsError:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(create, range(2)))
    assert sum(x is not None for x in winners) == 1
    with Session(engine) as db:
        assert db.get(LegalCorpusState, 1).draft_sequence == 1
        assert len(list(db.scalars(select(LegalCorpusRevision)))) == 1
        assert len(list(db.scalars(select(AuditEvent)))) == 1


def test_concurrent_publication_and_rollback_have_one_winner(system):
    engine, root, metadata = system
    with Session(engine) as db:
        row = revision(db, root, metadata)
        target = management.publish(db, principal(), publish_request(row.revision_id))
        target_id = target.publication_id
        second = revision(db, root, metadata.model_copy(update={"verification_note": "review2"}), 1)
        second_id = second.revision_id

    def change(operation):
        with Session(engine) as db:
            req = (
                publish_request(second_id, 2, 1)
                if operation == "publish"
                else PublicationRequest(
                    request_id=str(uuid4()),
                    expected_sequence=1,
                    operation="rollback",
                    target_publication_id=target_id,
                    reason="synthetic rollback",
                )
            )
            try:
                return management.publish(db, principal(), req).publication_id
            except FileExistsError:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(change, ("publish", "rollback")))
    assert sum(x is not None for x in result) == 1
    with Session(engine) as db:
        assert db.get(LegalCorpusState, 1).sequence == 2
        assert len(list(db.scalars(select(LegalPublication)))) == 2
        assert len(list(db.scalars(select(AuditEvent)))) == 4


@pytest.mark.parametrize("operation", ["revision", "publication"])
def test_audit_failure_rolls_back_state_history_and_identity_registry(
    system, monkeypatch, operation
):
    engine, root, metadata = system
    with Session(engine) as db:
        row = revision(db, root, metadata) if operation == "publication" else None
        previous_events = len(list(db.scalars(select(AuditEvent))))

        def fail(*args):
            raise RuntimeError("synthetic audit failure")

        monkeypatch.setattr(management, "audit", fail)
        with pytest.raises(RuntimeError, match="audit failure"):
            if row:
                management.publish(db, principal(), publish_request(row.revision_id))
            else:
                revision(db, root, metadata)
        assert len(list(db.scalars(select(AuditEvent)))) == previous_events
        state = db.get(LegalCorpusState, 1)
        assert state.sequence == 0
        assert state.draft_sequence == (1 if row else 0)
        assert len(list(db.scalars(select(LegalLawIdentity)))) == (1 if row else 0)


def test_disable_and_rollback_create_new_history_and_old_runs_remain_readable(system):
    engine, root, metadata = system
    with Session(engine) as db:
        row = revision(db, root, metadata)
        pub = management.publish(db, principal(), publish_request(row.revision_id))
        publication_id = pub.publication_id
        result = management.retrieve_published_for_project(
            db, principal(), "p", text="投标保证金", review_date=date(2026, 10, 14)
        )
        run = db.get(LegalRetrievalRun, ("a", result.run_snapshot.run_id))
        assert run.request_snapshot["publication_id"] == publication_id
        # Mutable repository source changes cannot alter published artifacts or previous output.
        (root / metadata.text_path).write_bytes(b"mutable repository changed")
        assert (
            management.resolve_published_evidence(
                db, principal(), publication_id, result.hits[0], result.query
            )
            == result.hits[0].quote
        )
        disabled = management.publish(
            db,
            principal(),
            PublicationRequest(
                request_id=str(uuid4()),
                expected_sequence=1,
                operation="disable",
                reason="synthetic",
            ),
        )
        assert disabled.revision_id is None
        with pytest.raises(LookupError):
            management.retrieve_published_for_project(
                db, principal(), "p", text="投标保证金", review_date=date(2026, 10, 14)
            )
        assert legal.read_run(db, principal(), result.run_snapshot.run_id) == result
        restored = management.publish(
            db,
            principal(),
            PublicationRequest(
                request_id=str(uuid4()),
                expected_sequence=2,
                operation="rollback",
                target_publication_id=publication_id,
                reason="synthetic restore",
            ),
        )
        assert restored.publication_id != publication_id and restored.revision_id == row.revision_id
        assert restored.target_id == publication_id
        assert (
            management.read_publication(db, principal())[0].publication_id
            == restored.publication_id
        )


@pytest.mark.parametrize("table", [LegalCorpusRevision, LegalPublication, LegalLawIdentity])
def test_global_history_is_append_only_even_for_db_owner(system, table):
    engine, root, metadata = system
    with Session(engine) as db:
        row = revision(db, root, metadata)
        management.publish(db, principal(), publish_request(row.revision_id))
        with pytest.raises(IntegrityError, match="append-only"):
            db.execute(delete(table))
        db.rollback()
        assert db.get(LegalCorpusState, 1).sequence == 1


def test_revoke_between_reading_source_and_writing_cannot_commit(system, monkeypatch):
    engine, root, metadata = system
    original = management.capture_bundle

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        with Session(engine) as admin:
            admin.get(AuthSession, ("a", "s")).revoked = True
            admin.commit()
        return result

    monkeypatch.setattr(management, "capture_bundle", revoke)
    with Session(engine) as db:
        with pytest.raises(PermissionError):
            revision(db, root, metadata)
        assert list(db.scalars(select(LegalCorpusRevision))) == []


def test_public_corpus_read_does_not_leak_other_tenant_project_runs(system):
    engine, root, metadata = system
    with Session(engine) as db:
        row = revision(db, root, metadata)
        pub = management.publish(db, principal(), publish_request(row.revision_id))
        assert management.read_publication(db, principal("b"), pub.publication_id)[1]
        result = management.retrieve_published_for_project(
            db, principal(), "p", text="投标保证金", review_date=date(2026, 10, 14)
        )
        with pytest.raises(LookupError):
            legal.read_run(db, principal("b"), result.run_snapshot.run_id)


def test_incomplete_sources_future_verification_and_private_paths_are_rejected(system):
    engine, root, metadata = system
    with Session(engine) as db:
        with pytest.raises(ValueError, match="verification source"):
            revision(db, root, metadata, verification_sources=())
        with pytest.raises(ValueError, match="future"):
            revision(db, root, metadata.model_copy(update={"verified_through": date(9999, 1, 1)}))
        with pytest.raises(ValueError, match="public legal"):
            revision(db, root, metadata.model_copy(update={"text_path": ".env"}))
        assert db.get(LegalCorpusState, 1).draft_sequence == 0


def test_frozen_revision_tamper_and_unjournaled_state_transition_rejected(system):
    engine, root, metadata = system
    with Session(engine) as db:
        row = revision(db, root, metadata)
        data = deepcopy(row.bundle)
        data["artifacts"][0]["sha256"] = "0" * 64
        with pytest.raises(ValidationError):
            CorpusBundle.model_validate(data)
        with pytest.raises(IntegrityError, match="transition"):
            db.execute(update(LegalCorpusState).values(sequence=9))
        db.rollback()


@pytest.mark.parametrize(
    "uri",
    [
        "https://evil.example?fake.gov.cn/path",
        "https://user:secret@official.gov.cn/path",
        "https://official.gov.cn/path#unverified",
    ],
)
def test_verification_uri_cannot_fake_official_origin(system, uri):
    _, _, metadata = system
    proof = request(metadata).verification_sources[0]
    with pytest.raises(ValidationError):
        VerificationSource.model_validate({**proof.model_dump(), "source_uri": uri})


def test_revision_idempotency_rejects_changed_verification(system):
    engine, root, metadata = system
    with Session(engine) as db:
        request_id = str(uuid4())
        first = revision(db, root, metadata, request_id=request_id)
        same = revision(db, root, metadata, request_id=request_id)
        assert same.revision_id == first.revision_id
        with pytest.raises(FileExistsError, match="idempotency"):
            revision(
                db,
                root,
                metadata.model_copy(update={"verification_note": "changed"}),
                request_id=request_id,
            )
        assert db.get(LegalCorpusState, 1).draft_sequence == 1
