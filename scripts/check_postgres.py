"""Mandatory PostgreSQL CI gate: fresh disposable verification database only."""

import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from check_u05 import check_u05
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from bidding_compliance.api import create_app
from bidding_compliance.core.config import Settings
from bidding_compliance.legal.contracts import LegalManifest
from bidding_compliance.legal.corpus import ingest, resolve_evidence
from bidding_compliance.legal.retrieval import LegalRetriever
from bidding_compliance.persistence.database import make_engine, migrate, set_tenant
from bidding_compliance.persistence.models import (
    Base,
    Document,
    IngestionJob,
    LegalOperatorGrant,
    LegalRetrievalRun,
    Project,
    Tenant,
    User,
)
from bidding_compliance.services.identity import PASSWORDS, authenticate
from bidding_compliance.services.legal import read_run, retrieve_for_project
from bidding_compliance.services.legal_authorization import require_legal_operation


def main() -> None:
    url = make_url(os.environ["POSTGRES_VERIFY_URL"])
    if url.database != "task0004_verification" or url.get_backend_name() != "postgresql":
        raise RuntimeError("Only the disposable task0004_verification database is accepted")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=url.render_as_string(hide_password=False),
        auth_signing_key=str(uuid4()) + str(uuid4()),
        object_storage_root=Path(".verification") / ("pg-objects-" + uuid4().hex),
    )
    admin = make_engine(settings)
    if "tenant" in inspect(admin).get_table_names():
        raise RuntimeError("Verification database must be empty; never clear existing data")
    migrate(admin, "202610131300")
    password = str(uuid4())
    with Session(admin) as db:
        db.add_all(
            [
                Tenant(tenant_id="a", name="synthetic-a", active=True),
                Tenant(tenant_id="b", name="synthetic-b", active=True),
            ]
        )
        db.flush()
        hashed = PASSWORDS.hash(password)
        for tenant in ("a", "b"):
            for role in ("reviewer", "admin", "auditor"):
                db.add(
                    User(
                        tenant_id=tenant,
                        user_id=role,
                        username=role,
                        role=role,
                        password_hash=hashed,
                        active=True,
                    )
                )
        db.commit()
    migrate(admin)
    migrate(admin)
    with Session(admin) as db:
        db.add(
            LegalOperatorGrant(
                tenant_id="a", user_id="reviewer", active=True, capabilities=["ingest"]
            )
        )
        db.commit()
    with admin.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    runtime_password = str(uuid4())
    with admin.begin() as connection:
        # Password is an internally generated UUID, never external SQL input or a real secret.
        connection.exec_driver_sql(
            "CREATE ROLE task4_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '"
            + runtime_password
            + "'"
        )
        connection.execute(text("GRANT USAGE ON SCHEMA public TO task4_runtime"))
        connection.execute(text("GRANT SELECT ON tenant, app_user TO task4_runtime"))
        connection.execute(text("GRANT UPDATE(password_hash) ON app_user TO task4_runtime"))
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON auth_session, project TO task4_runtime")
        )
        connection.execute(text("GRANT SELECT, INSERT, UPDATE ON ingestion_job TO task4_runtime"))
        connection.execute(text("GRANT SELECT, INSERT ON legal_retrieval_run TO task4_runtime"))
        connection.execute(text("GRANT SELECT ON legal_operator_grant TO task4_runtime"))
        connection.execute(
            text(
                "GRANT SELECT, INSERT ON review_configuration_revision, "
                "review_configuration_event TO task4_runtime"
            )
        )
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON review_configuration_state TO task4_runtime")
        )
        connection.execute(
            text(
                "GRANT SELECT, INSERT ON document_section, section_revision, "
                "document_context_version TO task4_runtime"
            )
        )
        policies = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('ingestion_job','document_section','section_revision',"
                "'document_context_version','legal_retrieval_run',"
                "'review_configuration_revision','review_configuration_event',"
                "'review_configuration_state','model_execution_policy',"
                "'document_external_authorization','model_budget_account',"
                "'model_budget_reservation','ledger_import')"
            )
        ).all()
        assert len(policies) == 13 and all(p[1] and p[2] for p in policies)
        connection.execute(
            text(
                "GRANT SELECT, INSERT ON project_version, idempotency_record, "
                "document, review_task, audit_event TO task4_runtime"
            )
        )
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON review_engine_run TO task4_runtime")
        )
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON review_model_call TO task4_runtime")
        )
        connection.execute(
            text(
                "GRANT SELECT, INSERT ON review_artifact, review_decision, review_result "
                "TO task4_runtime"
            )
        )
        connection.execute(
            text("GRANT SELECT ON model_execution_policy TO task4_runtime")
        )
        connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE ON document_external_authorization "
                "TO task4_runtime"
            )
        )
        connection.execute(
            text("GRANT SELECT, UPDATE ON model_budget_account TO task4_runtime")
        )
        connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE ON model_budget_reservation TO task4_runtime"
            )
        )
        connection.execute(text("GRANT SELECT, INSERT ON ledger_import TO task4_runtime"))
        connection.execute(text("GRANT SELECT ON checkpoint_migrations TO task4_runtime"))
        connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_blobs, "
                "checkpoint_writes TO task4_runtime"
            )
        )
    runtime_settings = settings.model_copy(
        update={
            "database_url": settings.database_url.__class__(
                url.set(username="task4_runtime", password=runtime_password).render_as_string(
                    hide_password=False
                )
            )
        }
    )
    runtime = make_engine(runtime_settings)
    body = dict(
        name="synthetic",
        procurement_type="government",
        project_type="works",
        region="福建省福州市",
        procurement_method="tender",
        buyer_type="government_entity",
        subject_type="works",
    )
    with TestClient(create_app(runtime_settings)) as client:

        def login(tenant):
            response = client.post(
                "/api/v1/auth/token",
                json=dict(tenant_id=tenant, username="reviewer", password=password),
            )
            assert response.status_code == 200, response.text
            return {"Authorization": "Bearer " + response.json()["access_token"]}

        a, b = login("a"), login("b")
        headers = {**a, "Idempotency-Key": str(uuid4())}

        def create(_):
            return client.post("/api/v1/projects", headers=headers, json=body)

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(create, range(6)))
        assert all(r.status_code == 201 for r in responses), [r.status_code for r in responses]
        assert len({r.json()["project_id"] for r in responses}) == 1
        project = responses[0].json()
        path = "/api/v1/projects/" + project["project_id"]
        assert client.get(path, headers=b).status_code == 404
        assert client.get("/api/v1/projects", headers=b).json()["items"] == []

        def change(_):
            return client.put(path, headers=a, json={**body, "expected_version": 1})

        with ThreadPoolExecutor(max_workers=2) as pool:
            writes = list(pool.map(change, range(2)))
        assert sorted(r.status_code for r in writes) == [200, 409]
        assert len(client.get(path + "/versions", headers=a).json()["items"]) == 2
        buffer = io.BytesIO()
        sample = canvas.Canvas(buffer)
        sample.drawString(50, 700, "Synthetic PostgreSQL durable upload fixture.")
        sample.save()
        uploaded = client.post(
            path + "/documents",
            headers={**a, "Idempotency-Key": str(uuid4())},
            files={"file": ("synthetic.pdf", buffer.getvalue(), "application/pdf")},
        )
        assert uploaded.status_code == 202, uploaded.text
        document_id = uploaded.json()["document_id"]
        assert client.get(path + "/documents/" + document_id, headers=b).status_code == 404
        with Session(runtime) as db:
            set_tenant(db, "b")
            assert list(db.scalars(select(IngestionJob))) == []
            db.rollback()
            set_tenant(db, "a")
            jobs = list(db.scalars(select(IngestionJob)))
            assert len(jobs) == 1 and jobs[0].document_id == document_id
        root = Path(__file__).resolve().parents[1]
        manifest = LegalManifest.model_validate_json(
            (root / "config/legal/manifest.json").read_bytes()
        )
        retriever = LegalRetriever(ingest(root, manifest))
        with Session(runtime) as db:
            who = authenticate(db, runtime_settings, a["Authorization"].split(" ", 1)[1])
            result = retrieve_for_project(
                db,
                who,
                project["project_id"],
                retriever,
                text="投标保证金",
                review_date=date(2026, 10, 14),
            )
            assert result.hits and result.run_snapshot is not None
            assert result.query is not None
            assert result.citable_evidence == tuple(h.evidence_id for h in result.hits)
            for hit in result.hits:
                assert resolve_evidence(root, retriever.index, hit, result.query) == hit.quote
            run_id = result.run_snapshot.run_id
        with Session(runtime) as db:
            who = authenticate(db, runtime_settings, a["Authorization"].split(" ", 1)[1])
            assert read_run(db, who, run_id) == result
            require_legal_operation(db, who, "ingest")
            try:
                require_legal_operation(db, who, "publish")
            except PermissionError:
                pass
            else:
                raise AssertionError("Ingest capability escalated to global publication")
            require_legal_operation(db, who, "ingest")
            assert db.execute(
                text(
                    "SELECT has_table_privilege(current_user,'legal_operator_grant','INSERT'), "
                    "has_table_privilege(current_user,'legal_operator_grant','UPDATE'), "
                    "has_table_privilege(current_user,'legal_operator_grant','DELETE')"
                )
            ).one() == (False, False, False)
            try:
                db.execute(text("UPDATE legal_operator_grant SET active = true"))
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError("Runtime role changed its global legal grant")
            require_legal_operation(db, who, "ingest")
            assert db.execute(
                text(
                    "SELECT has_table_privilege(current_user,'legal_retrieval_run','UPDATE'), "
                    "has_table_privilege(current_user,'legal_retrieval_run','DELETE')"
                )
            ).one() == (False, False)
            set_tenant(db, "b")
            assert list(db.scalars(select(LegalRetrievalRun))) == []
            who_b = authenticate(db, runtime_settings, b["Authorization"].split(" ", 1)[1])
            try:
                read_run(db, who_b, run_id)
            except LookupError:
                pass
            else:
                raise AssertionError("Cross-tenant retrieval run leaked")
            db.add(
                LegalRetrievalRun(
                    tenant_id="a",
                    run_id=str(uuid4()),
                    project_id=project["project_id"],
                    actor_id="reviewer",
                    context_version=2,
                    request_snapshot={},
                    request_hash="0" * 64,
                    result={},
                    result_hash="0" * 64,
                    created_at=datetime.now(),
                )
            )
            try:
                db.flush()
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError("Retrieval RLS allowed a cross-tenant insert")
        assert client.post("/api/v1/auth/logout", headers=a).status_code == 200
        assert client.get(path, headers=a).status_code == 401
        with Session(runtime) as db:
            try:
                read_run(db, who, run_id)
            except PermissionError:
                pass
            else:
                raise AssertionError("Revoked session read retrieval run")

    # RLS must also prevent mistakes in raw queries, writes and pooled connection reuse.
    with Session(runtime) as db:
        assert list(db.scalars(select(Project))) == []
        set_tenant(db, "a")
        assert len(list(db.scalars(select(Project)))) == 1
        db.commit()
        assert list(db.scalars(select(Project))) == []
        set_tenant(db, "b")
        assert list(db.scalars(select(Project))) == []
        db.add(
            Project(
                tenant_id="a",
                project_id=str(uuid4()),
                context=body,
                version=1,
                created_by="reviewer",
                created_at=datetime.fromisoformat(project["created_at"]),
            )
        )
        try:
            db.flush()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("RLS allowed a cross-tenant insert")
    with Session(runtime) as db:
        set_tenant(db, "b")
        db.add(
            Document(
                tenant_id="b",
                document_id=str(uuid4()),
                project_id=project["project_id"],
                status="accepted",
                sha256="a" * 64,
                object_ref="fixture://synthetic",
            )
        )
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("Composite FK allowed a cross-tenant document")
    check_u05(
        admin=admin,
        runtime=runtime,
        runtime_settings=runtime_settings,
        password=password,
        project=project,
        document_id=document_id,
    )
    with Session(admin) as db:
        for table in (
            "project_version",
            "audit_event",
            "legal_retrieval_run",
            "document_external_authorization",
            "model_budget_reservation",
            "model_budget_account",
            "ledger_import",
        ):
            try:
                # Fixed table names only; trigger must reject even privileged history changes.
                db.execute(text("DELETE FROM " + table))  # noqa: S608
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError("Append-only trigger failed")
        try:
            db.execute(text("UPDATE legal_retrieval_run SET context_version = 9"))
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("Append-only update trigger failed")
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/v1/auth/token",
                json=dict(tenant_id="a", username="reviewer", password=password),
            ).status_code
            == 500
        )
    # Initial downgrade/upgrade is exercised only in this fresh disposable database.
    config = Config()
    config.set_main_option("path_separator", "os")
    root = Path(__file__).resolve().parents[1]
    config.set_main_option("script_location", str(root / "contracts/database"))
    config.set_main_option("version_locations", str(root / "contracts/database/migrations"))
    with admin.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    assert "project" not in inspect(admin).get_table_names()
    migrate(admin)
    runtime.dispose()
    admin.dispose()
    print(
        "PASS: PostgreSQL migration, API, RLS, tenant FKs, concurrency, retrieval runs and rollback"
    )


if __name__ == "__main__":
    main()
