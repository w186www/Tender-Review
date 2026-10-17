"""One-shot deployment initialisation, reusing the repository's own domain code.

This is orchestration only: it calls the same migration, identity, storage and scanner
implementations the isolated acceptance harness uses (scripts/run_task0011_e2e.py), so the
deployed database, RLS role and starting legal publication are the ones the application
already expects. It contains no duplicated business logic.

Phases
------
storage   wait for PostgreSQL, migrate, create/refresh the non-superuser runtime role,
          seed the tenant and accounts, create the object bucket, wait for a fresh
          ClamAV database.
legal     through the running API with admin credentials, publish the initial legal
          snapshot if the tenant has no active publication yet.

Both phases are idempotent and never delete existing data.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from pathlib import Path

import boto3
import httpx
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bidding_compliance.core.config import Settings  # noqa: E402
from bidding_compliance.domain.identity import Role  # noqa: E402
from bidding_compliance.ingestion.ports import IngestionError  # noqa: E402
from bidding_compliance.ingestion.scanner import ClamAVScanner  # noqa: E402
from bidding_compliance.persistence.database import make_engine, migrate  # noqa: E402
from bidding_compliance.persistence.models import (  # noqa: E402
    LegalOperatorGrant,
    User,
)
from bidding_compliance.services.identity import PASSWORDS  # noqa: E402

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
CAPABILITIES = ["ingest", "verify", "publish", "disable", "rollback"]

# Table privileges for the application role. Kept identical to the reviewed harness list
# in scripts/run_task0011_e2e.py so the deployment does not silently widen or narrow it.
GRANTS = (
    "SELECT ON tenant, app_user, legal_operator_grant, legal_corpus_state, "
    "legal_corpus_revision, legal_publication, legal_law_identity",
    "UPDATE(password_hash) ON app_user",
    "SELECT, INSERT, UPDATE ON auth_session, project",
    "SELECT, INSERT, UPDATE ON ingestion_job",
    "SELECT, INSERT ON legal_retrieval_run",
    "SELECT, INSERT, UPDATE ON legal_corpus_state",
    "SELECT, INSERT ON legal_corpus_revision, legal_publication, legal_law_identity, audit_event",
    "SELECT, INSERT ON project_version, idempotency_record, document, review_task",
    "UPDATE ON document",
    "UPDATE ON review_task",
    "SELECT, INSERT ON document_section, section_revision, document_context_version",
    "UPDATE (revision) ON document_section",
    "SELECT, INSERT, UPDATE ON review_engine_run",
    "SELECT, INSERT ON review_artifact, review_decision, review_result, "
    "review_report_content, review_report",
    "SELECT, INSERT ON review_configuration_revision, review_configuration_event",
    "SELECT, INSERT, UPDATE ON review_configuration_state",
    "SELECT ON checkpoint_migrations",
    "SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_blobs, checkpoint_writes",
)


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing required environment variable {name}")
    return value


def settings_for(database_url: str) -> Settings:
    return Settings(_env_file=None, app_env=os.environ.get("APP_ENV", "staging"), database_url=database_url)


def wait_for_postgres(admin: Settings, deadline_seconds: int = 120) -> None:
    engine = make_engine(admin)
    deadline = time.monotonic() + deadline_seconds
    try:
        while True:
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                return
            except Exception as exc:  # noqa: BLE001 - readiness probe during startup only
                if time.monotonic() >= deadline:
                    raise SystemExit(f"PostgreSQL did not become ready: {type(exc).__name__}")
                time.sleep(2)
    finally:
        engine.dispose()


def ensure_runtime_role(admin: Settings, role: str, password: str) -> str:
    if not IDENTIFIER.fullmatch(role):
        raise SystemExit("DEMO_DB_RUNTIME_USER must be a plain lowercase PostgreSQL identifier")
    engine = make_engine(admin)
    try:
        with engine.begin() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
            )
            if exists:
                connection.exec_driver_sql(
                    f'ALTER ROLE "{role}" WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '
                    + literal(password)
                )
                outcome = "updated"
            else:
                connection.exec_driver_sql(
                    f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '
                    + literal(password)
                )
                outcome = "created"
            connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            for grant in GRANTS:
                connection.exec_driver_sql(f'GRANT {grant} TO "{role}"')
            bypass = connection.scalar(
                text(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = :role"
                ),
                {"role": role},
            )
            if bypass:
                raise SystemExit("refusing to run: the application role can bypass row security")
    finally:
        engine.dispose()
    return outcome


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def seed_accounts(admin: Settings, tenant_id: str, accounts: list[tuple[str, str, str]]) -> list[str]:
    """accounts: (username, role, password). Existing accounts keep their password."""
    engine = make_engine(admin)
    created: list[str] = []
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tenant (tenant_id, name, active) VALUES (:tenant, :name, true) "
                    "ON CONFLICT (tenant_id) DO NOTHING"
                ),
                {"tenant": tenant_id, "name": os.environ.get("DEMO_TENANT_NAME", tenant_id)},
            )
        with Session(engine) as session:
            session.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id}
            )
            for username, role, password in accounts:
                existing = session.get(User, (tenant_id, username))
                if existing is None:
                    session.add(
                        User(
                            tenant_id=tenant_id,
                            user_id=username,
                            username=username,
                            role=Role(role).value,
                            password_hash=PASSWORDS.hash(password),
                            active=True,
                        )
                    )
                    created.append(username)
            grant = session.get(LegalOperatorGrant, (tenant_id, "admin"))
            if grant is None:
                session.add(
                    LegalOperatorGrant(
                        tenant_id=tenant_id,
                        user_id="admin",
                        active=True,
                        capabilities=CAPABILITIES,
                    )
                )
            session.commit()
    finally:
        engine.dispose()
    return created


def ensure_bucket(settings: Settings) -> str:
    if (
        settings.object_storage_endpoint is None
        or settings.object_storage_access_id is None
        or settings.object_storage_access_secret is None
    ):
        raise SystemExit("object storage configuration is incomplete")
    client = boto3.client(
        "s3",
        endpoint_url=str(settings.object_storage_endpoint),
        region_name="us-east-1",
        aws_access_key_id=settings.object_storage_access_id.get_secret_value(),
        aws_secret_access_key=settings.object_storage_access_secret.get_secret_value(),
        config=BotoConfig(
            connect_timeout=5, read_timeout=10, retries={"max_attempts": 1},
            s3={"addressing_style": "path"},
        ),
    )
    deadline = time.monotonic() + 120
    while True:
        try:
            client.head_bucket(Bucket=settings.object_storage_bucket)
            return "present"
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchBucket", "NotFound"}:
                break
            if time.monotonic() >= deadline:
                raise SystemExit(f"object storage did not become ready: {code or exc}")
            time.sleep(2)
        except Exception as exc:  # noqa: BLE001 - readiness probe during startup only
            if time.monotonic() >= deadline:
                raise SystemExit(f"object storage did not become ready: {type(exc).__name__}")
            time.sleep(2)
    client.create_bucket(Bucket=settings.object_storage_bucket)
    return "created"


def wait_for_scanner(settings: Settings, deadline_seconds: int = 600) -> None:
    scanner = ClamAVScanner(settings)
    deadline = time.monotonic() + deadline_seconds
    last = "unavailable"
    while time.monotonic() < deadline:
        try:
            scanner.scan(b"Deployment readiness probe; no document content.")
            return
        except IngestionError as exc:
            last = exc.code
            # A stale database is a configuration problem, not a race with startup.
            if exc.code == "SCANNER_STALE":
                raise SystemExit(
                    "ClamAV virus database is stale; allow signature updates before uploading"
                ) from exc
            time.sleep(3)
    raise SystemExit(f"ClamAV did not become ready within the deadline (last state: {last})")


def phase_storage(admin: Settings, runtime_role: str, runtime_password: str) -> None:
    tenant_id = required("DEMO_TENANT")
    wait_for_postgres(admin)
    engine = make_engine(admin)
    try:
        migrate(engine)
    finally:
        engine.dispose()
    print("migrations: up to date", flush=True)

    print(f"runtime role: {ensure_runtime_role(admin, runtime_role, runtime_password)}", flush=True)

    accounts = [
        ("admin", "admin", required("DEMO_ADMIN_PASSWORD")),
        ("reviewer", "reviewer", required("DEMO_REVIEWER_PASSWORD")),
        ("auditor", "auditor", required("DEMO_AUDITOR_PASSWORD")),
    ]
    created = seed_accounts(admin, tenant_id, accounts)
    print(f"accounts created: {', '.join(created) if created else 'none (already present)'}", flush=True)

    # The bucket is created with the configured credential; the application then uses the
    # same credential, exactly as the reviewed harness does.
    app_settings = settings_for(required("DATABASE_URL"))
    print(f"bucket: {ensure_bucket(app_settings)}", flush=True)
    wait_for_scanner(app_settings)
    print("ClamAV: ready with a valid virus database", flush=True)


def phase_legal(api_url: str) -> None:
    tenant_id = required("DEMO_TENANT")
    username = required("DEMO_ADMIN_USERNAME")
    password = required("DEMO_ADMIN_PASSWORD")
    with httpx.Client(base_url=api_url, timeout=300, trust_env=False) as client:
        login = client.post(
            "/api/v1/auth/token",
            json={"tenant_id": tenant_id, "username": username, "password": password},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        state = client.get("/api/v1/admin/legal", headers=headers)
        state.raise_for_status()
        current = state.json()
        if current.get("publication_id"):
            print(
                f"legal publication: already active ({current['publication_id']})",
                flush=True,
            )
            return
        draft = client.post(
            "/api/v1/admin/legal/drafts",
            headers=headers,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_draft_sequence": current.get("draft_sequence", 0),
                "reason": "部署初始化：启用仓库内已核验状态的法规快照",
            },
        )
        draft.raise_for_status()
        payload = draft.json()
        revision_id = payload["draft_revision_id"]
        if not revision_id:
            raise SystemExit("legal bootstrap did not create a revision")
        publication = client.post(
            "/api/v1/admin/legal/publications",
            headers=headers,
            json={
                "request_id": str(uuid.uuid4()),
                "expected_sequence": payload["sequence"],
                "expected_draft_sequence": payload["draft_sequence"],
                "operation": "publish",
                "revision_id": revision_id,
                "reason": "部署初始化：启用初始法规快照",
            },
        )
        publication.raise_for_status()
        final = publication.json()
        if not final.get("publication_id"):
            raise SystemExit("legal bootstrap did not publish a revision")
        print(f"legal publication: {final['publication_id']}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["storage", "legal"])
    args = parser.parse_args()

    admin = settings_for(required("ADMIN_DATABASE_URL"))
    if args.phase == "storage":
        phase_storage(
            admin,
            required("DEMO_DB_RUNTIME_USER"),
            required("DEMO_DB_RUNTIME_PASSWORD"),
        )
    else:
        phase_legal(os.environ.get("DEMO_API_URL", "http://api:8000"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
