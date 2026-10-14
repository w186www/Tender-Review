"""Real PostgreSQL lifecycle/RLS/concurrency/failure integration; disposable DB only."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from check_review_engine import verify_review_engine
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.legal.contracts import LegalManifest
from bidding_compliance.legal.management_contracts import (
    PublicationRequest,
    RevisionRequest,
    VerificationSource,
)
from bidding_compliance.persistence.database import make_engine, set_tenant
from bidding_compliance.persistence.models import (
    LegalCorpusState,
    LegalOperatorGrant,
    LegalPublication,
    Project,
    Tenant,
    User,
)
from bidding_compliance.services.identity import PASSWORDS, authenticate, login
from bidding_compliance.services.legal import read_run
from bidding_compliance.services.legal_management import (
    create_revision,
    publish,
    read_publication,
    resolve_published_evidence,
    retrieve_published_for_project,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    url = make_url(os.environ["POSTGRES_VERIFY_URL"])
    if url.database != "task0004_verification" or url.get_backend_name() != "postgresql":
        raise RuntimeError("Only the disposable verification database is accepted")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=url.render_as_string(hide_password=False),
        auth_signing_key=str(uuid4()) + str(uuid4()),
    )
    admin = make_engine(settings)
    password, runtime_password = str(uuid4()), str(uuid4())
    with Session(admin) as db:
        assert not list(db.scalars(select(Tenant))), (
            "Run after the original PostgreSQL rollback check"
        )
        assert db.get(LegalCorpusState, 1).sequence == 0
        for tenant in ("legal-a", "legal-b"):
            db.add(Tenant(tenant_id=tenant, name="synthetic", active=True))
        db.flush()
        for tenant in ("legal-a", "legal-b"):
            db.add(
                User(
                    tenant_id=tenant,
                    user_id="u",
                    username="u",
                    active=True,
                    role="reviewer" if tenant == "legal-a" else "admin",
                    password_hash=PASSWORDS.hash(password),
                )
            )
        db.flush()
        db.add(
            LegalOperatorGrant(
                tenant_id="legal-a",
                user_id="u",
                active=True,
                capabilities=["ingest", "verify", "publish", "disable", "rollback"],
            )
        )
        for tenant in ("legal-a", "legal-b"):
            db.add(
                Project(
                    tenant_id=tenant,
                    project_id="p",
                    version=1,
                    created_by="u",
                    created_at=datetime.now(UTC),
                    context=dict(
                        name="synthetic",
                        procurement_type="government",
                        project_type="works",
                        region="福建省福州市",
                        procurement_method="tender",
                        buyer_type="government_entity",
                        subject_type="works",
                    ),
                )
            )
        db.commit()
    with admin.begin() as conn:
        conn.exec_driver_sql(
            "CREATE ROLE task6_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '"
            + runtime_password
            + "'"
        )
        conn.execute(text("GRANT USAGE ON SCHEMA public TO task6_runtime"))
        conn.execute(
            text(
                "GRANT SELECT ON tenant, app_user, project, legal_operator_grant, "
                "legal_corpus_state, legal_corpus_revision, legal_publication, "
                "legal_law_identity TO task6_runtime"
            )
        )
        conn.execute(text("GRANT UPDATE(password_hash) ON app_user TO task6_runtime"))
        conn.execute(text("GRANT SELECT,INSERT,UPDATE ON auth_session TO task6_runtime"))
        conn.execute(
            text(
                "GRANT SELECT,INSERT ON audit_event, legal_retrieval_run, "
                "legal_corpus_revision, legal_publication, legal_law_identity TO task6_runtime"
            )
        )
        conn.execute(text("GRANT UPDATE ON legal_corpus_state TO task6_runtime"))
        conn.execute(
            text(
                "GRANT SELECT ON document, document_section, section_revision, "
                "document_context_version TO task6_runtime"
            )
        )
        conn.execute(text("GRANT SELECT, INSERT, UPDATE ON review_task TO task6_runtime"))
        conn.execute(text("GRANT SELECT, INSERT, UPDATE ON review_engine_run TO task6_runtime"))
        conn.execute(
            text(
                "GRANT SELECT, INSERT ON review_artifact, review_decision, review_result "
                "TO task6_runtime"
            )
        )
        conn.execute(text("GRANT SELECT ON checkpoint_migrations TO task6_runtime"))
        conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_blobs, "
                "checkpoint_writes TO task6_runtime"
            )
        )
        flags = conn.execute(
            text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('legal_operator_grant','legal_corpus_state',"
                "'legal_corpus_revision',"
                "'legal_publication','legal_law_identity')"
            )
        ).all()
        assert len(flags) == 5 and all(row == (True, True) for row in flags)
    runtime_settings = settings.model_copy(
        update={
            "database_url": settings.database_url.__class__(
                url.set(username="task6_runtime", password=runtime_password).render_as_string(
                    hide_password=False
                )
            )
        }
    )
    runtime = make_engine(runtime_settings)
    tokens = {}
    for tenant in ("legal-a", "legal-b"):
        with Session(runtime) as db:
            tokens[tenant] = login(db, runtime_settings, tenant, "u", password)

    def actor(db, tenant="legal-a"):
        return authenticate(db, runtime_settings, tokens[tenant])

    manifest = LegalManifest.model_validate_json((ROOT / "config/legal/manifest.json").read_bytes())
    import json

    proofs = tuple(
        VerificationSource.model_validate(x)
        for x in json.loads((ROOT / "config/legal/verification-sources.json").read_bytes())
    )

    def verify(_):
        with Session(runtime) as db:
            try:
                row = create_revision(
                    db,
                    actor(db),
                    ROOT,
                    manifest,
                    RevisionRequest(
                        request_id=str(uuid4()),
                        expected_draft_sequence=0,
                        reason="integration verification",
                        verification_sources=proofs,
                    ),
                )
                return row.revision_id
            except FileExistsError:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        revisions = list(pool.map(verify, range(2)))
    assert sum(x is not None for x in revisions) == 1
    first_revision = next(x for x in revisions if x)
    with Session(runtime) as db:
        req = PublicationRequest(
            request_id=str(uuid4()),
            expected_sequence=0,
            operation="publish",
            revision_id=first_revision,
            expected_draft_sequence=1,
            reason="integration publish",
        )
        who = actor(db)
        first = publish(db, who, req)
        first_id = first.publication_id
        assert publish(db, who, req).publication_id == first_id
        result = retrieve_published_for_project(
            db, who, "p", text="投标保证金", review_date=date(2026, 10, 14)
        )
        assert result.hits and result.run_snapshot is not None
        assert (
            resolve_published_evidence(db, who, first_id, result.hits[0], result.query)
            == result.hits[0].quote
        )
        second = create_revision(
            db,
            who,
            ROOT,
            manifest,
            RevisionRequest(
                request_id=str(uuid4()),
                expected_draft_sequence=1,
                reason="second verification of identical text",
                verification_sources=proofs,
            ),
        )
        second_id = second.revision_id
        assert second_id != first_revision
        other = actor(db, "legal-b")
        try:
            publish(
                db,
                other,
                PublicationRequest(
                    request_id=str(uuid4()),
                    expected_sequence=1,
                    operation="disable",
                    reason="tenant admin must not disable global corpus",
                ),
            )
        except PermissionError:
            pass
        else:
            raise AssertionError("Tenant admin obtained global legal operation")
        set_tenant(db, "legal-b")
        db.execute(text("SELECT set_config('app.user_id','u',true)"))
        assert (
            db.execute(text("UPDATE legal_corpus_state SET sequence=9 WHERE singleton=1")).rowcount
            == 0
        )
        db.rollback()
        assert read_publication(db, other, first_id)[1].index
        try:
            read_run(db, other, result.run_snapshot.run_id)
        except LookupError:
            pass
        else:
            raise AssertionError("Cross-tenant project retrieval leaked")

    def compete(operation):
        with Session(runtime) as db:
            request = PublicationRequest(
                request_id=str(uuid4()),
                expected_sequence=1,
                operation=operation,
                reason="integration concurrent lifecycle",
                revision_id=second_id if operation == "publish" else None,
                expected_draft_sequence=2 if operation == "publish" else None,
                target_publication_id=first_id if operation == "rollback" else None,
            )
            try:
                return publish(db, actor(db), request).publication_id
            except FileExistsError:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, ("publish", "rollback")))
    assert sum(x is not None for x in results) == 1
    with Session(runtime) as db:
        assert db.get(LegalCorpusState, 1).sequence == 2
        assert len(list(db.scalars(select(LegalPublication)))) == 2
    # Make the audit fail after staging history/current; all changes must be rolled back.
    with admin.begin() as conn:
        conn.execute(text("REVOKE INSERT ON audit_event FROM task6_runtime"))
    with Session(runtime) as db:
        try:
            publish(
                db,
                actor(db),
                PublicationRequest(
                    request_id=str(uuid4()),
                    expected_sequence=2,
                    operation="disable",
                    reason="forced database audit failure",
                ),
            )
        except DBAPIError:
            pass
        else:
            raise AssertionError("Publication succeeded without atomic audit")
        assert db.get(LegalCorpusState, 1).sequence == 2
        assert len(list(db.scalars(select(LegalPublication)))) == 2
    with admin.begin() as conn:
        conn.execute(text("GRANT INSERT ON audit_event TO task6_runtime"))
    with Session(runtime) as db:
        who = actor(db)
        disabled = publish(
            db,
            who,
            PublicationRequest(
                request_id=str(uuid4()),
                expected_sequence=2,
                operation="disable",
                reason="integration disable",
            ),
        )
        assert disabled.revision_id is None
        try:
            read_publication(db, who)
        except LookupError:
            pass
        else:
            raise AssertionError("Disabled current corpus still served")
        restored = publish(
            db,
            who,
            PublicationRequest(
                request_id=str(uuid4()),
                expected_sequence=3,
                operation="rollback",
                target_publication_id=first_id,
                reason="integration restore",
            ),
        )
        assert restored.sequence == 4 and restored.publication_id != first_id
        assert read_run(db, who, result.run_snapshot.run_id) == result
    verify_review_engine(admin, runtime, runtime_settings, who, ROOT)
    with Session(admin) as db:
        for table in ("legal_corpus_revision", "legal_publication", "legal_law_identity"):
            try:
                db.execute(text("DELETE FROM " + table))  # noqa: S608 - fixed names only
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError("Global history trigger allowed privileged mutation")
        db.get(LegalOperatorGrant, ("legal-a", "u")).active = False
        db.commit()
    with Session(runtime) as db:
        try:
            publish(
                db,
                actor(db),
                PublicationRequest(
                    request_id=str(uuid4()),
                    expected_sequence=4,
                    operation="disable",
                    reason="revoked global grant",
                ),
            )
        except PermissionError:
            pass
        else:
            raise AssertionError("Revoked operator still published")
    runtime.dispose()
    admin.dispose()
    print(
        "PASS: real PostgreSQL legal revision/publication CAS, RLS, idempotency, audit rollback, "
        "disable/restore, history, cross-tenant and live grant revocation"
    )


if __name__ == "__main__":
    main()
