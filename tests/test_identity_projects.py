"""TASK0004-001/002: real migrated storage, trusted identities and tenant/RBAC isolation."""

import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from verify_contracts import ROOT, load_contracts, load_openapi, validator_for_contract

from bidding_compliance.api import create_app
from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Role
from bidding_compliance.persistence.database import make_engine, migrate, set_tenant
from bidding_compliance.persistence.models import (
    AuditEvent,
    Base,
    Document,
    Project,
    Tenant,
    User,
)
from bidding_compliance.services.identity import PASSWORDS

BODY = dict(
    name="合成项目",
    procurement_type="government",
    project_type="works",
    region="示例",
    applicable_system="合成内部制度",
    budget_amount=1200.50,
)


def validate(name, data):
    documents, registry, errors = load_contracts(ROOT)
    api, api_errors = load_openapi(ROOT)
    assert not errors + api_errors
    validator_for_contract(
        ROOT, "contracts/openapi.yaml#/components/schemas/" + name, documents, registry, api
    ).validate(data)


@pytest.fixture
def system(tmp_path):
    password = str(uuid4())
    key = str(uuid4()) + str(uuid4())
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite:///" + (tmp_path / "identity.db").as_posix(),
        auth_signing_key=key,
        object_storage_root=tmp_path / "objects",
    )
    engine = make_engine(settings)
    migrate(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Tenant(tenant_id="a", name="合成甲", active=True),
                Tenant(tenant_id="b", name="合成乙", active=True),
            ]
        )
        db.flush()
        hashed = PASSWORDS.hash(password)
        for tenant in ("a", "b"):
            for role in Role:
                db.add(
                    User(
                        tenant_id=tenant,
                        user_id=role.value,
                        username=role.value,
                        password_hash=hashed,
                        role=role.value,
                        active=True,
                    )
                )
        db.commit()
    with TestClient(create_app(settings)) as client:
        yield client, engine, settings, password
    engine.dispose()


def sign_in(system, tenant="a", role="reviewer"):
    client, _, _, password = system
    response = client.post(
        "/api/v1/auth/token", json=dict(tenant_id=tenant, username=role, password=password)
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    validate("AccessToken", response.json())
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def create(client, headers, **body):
    return client.post(
        "/api/v1/projects",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**BODY, **body},
    )


def test_migration_is_repeatable_and_matches_frozen_orm(system):
    _, engine, _, _ = system
    migrate(engine)
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        changes = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert changes == []


def test_project_lifecycle_contract_version_history_and_stale_write(system):
    client, _, _, _ = system
    headers = sign_in(system)
    response = create(client, headers)
    assert response.status_code == 201, response.text
    original = response.json()
    validate("Project", original)
    url = "/api/v1/projects/" + original["project_id"]
    assert client.get(url, headers=headers).json() == original
    update_response = client.put(
        url, headers=headers, json={**BODY, "name": "更新项目", "expected_version": 1}
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["version"] == 2
    validate("Project", update_response.json())
    stale = client.put(url, headers=headers, json={**BODY, "expected_version": 1})
    assert stale.status_code == 409
    history = client.get(url + "/versions", headers=headers).json()
    validate("ProjectHistory", history)
    assert [v["version"] for v in history["items"]] == [1, 2]
    assert history["items"][0] == original
    listing = client.get("/api/v1/projects?limit=1", headers=headers).json()
    validate("ProjectList", listing)
    assert listing["items"][0]["name"] == "更新项目"


def test_cross_tenant_read_update_history_list_and_forged_header(system):
    client, _, _, _ = system
    a, b = sign_in(system), sign_in(system, tenant="b")
    project = create(client, a).json()
    url = "/api/v1/projects/" + project["project_id"]
    b["X-Tenant-ID"] = "a"
    for path in (url, url + "/versions"):
        response = client.get(path, headers=b)
        assert response.status_code == 404
        validate("Error", response.json())
    assert client.put(url, headers=b, json={**BODY, "expected_version": 1}).status_code == 404
    assert client.get("/api/v1/projects", headers=b).json()["items"] == []
    assert create(client, b, tenant_id="a").status_code == 422
    assert create(client, b).json()["tenant_id"] == "b"


@pytest.mark.parametrize("role", ["admin", "auditor", "operator"])
def test_role_matrix_rejects_project_creation_and_update(system, role):
    client, engine, _, _ = system
    project = create(client, sign_in(system)).json()
    headers = sign_in(system, role=role)
    assert create(client, headers).status_code == 403
    assert client.get("/api/v1/projects", headers=headers).status_code == 200
    url = "/api/v1/projects/" + project["project_id"]
    assert client.put(url, headers=headers, json={**BODY, "expected_version": 1}).status_code == 403
    with Session(engine) as db:
        assert (
            len(list(db.scalars(select(AuditEvent).where(AuditEvent.action == "project.denied"))))
            == 2
        )


def test_idempotency_replay_conflict_and_snapshot_after_update(system):
    client, engine, _, _ = system
    headers = {**sign_in(system), "Idempotency-Key": str(uuid4())}
    first = client.post("/api/v1/projects", headers=headers, json=BODY)
    second = client.post("/api/v1/projects", headers=headers, json=BODY)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert (
        client.post(
            "/api/v1/projects", headers=headers, json={**BODY, "name": "changed"}
        ).status_code
        == 409
    )
    url = "/api/v1/projects/" + first.json()["project_id"]
    assert (
        client.put(
            url, headers=headers, json={**BODY, "name": "changed", "expected_version": 1}
        ).status_code
        == 200
    )
    assert client.post("/api/v1/projects", headers=headers, json=BODY).json() == first.json()
    with Session(engine) as db:
        assert len(list(db.scalars(select(Project)))) == 1


@pytest.mark.parametrize("kind", ["expired", "issuer", "audience", "signature", "missing", "none"])
def test_invalid_tokens_are_rejected_without_echo(system, kind):
    client, _, settings, _ = system
    valid = sign_in(system)["Authorization"].removeprefix("Bearer ")
    key = settings.auth_signing_key.get_secret_value()
    claims = jwt.decode(
        valid,
        key,
        algorithms=["HS256"],
        audience=settings.auth_audience,
        issuer=settings.auth_issuer,
    )
    if kind == "expired":
        claims["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    elif kind == "issuer":
        claims["iss"] = "unknown"
    elif kind == "audience":
        claims["aud"] = "unknown"
    elif kind == "missing":
        del claims["jti"]
    token = jwt.encode(
        claims,
        "" if kind == "none" else str(uuid4()) * 2 if kind == "signature" else key,
        algorithm="none" if kind == "none" else "HS256",
    )
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401
    assert token not in response.text
    validate("Error", response.json())


def test_logout_revokes_token_and_role_change_is_immediate(system):
    client, engine, _, _ = system
    headers = sign_in(system)
    me = client.get("/api/v1/auth/me", headers=headers)
    validate("Identity", me.json())
    with Session(engine) as db:
        db.execute(
            update(User)
            .where(User.tenant_id == "a", User.user_id == "reviewer")
            .values(role="auditor")
        )
        db.commit()
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "auditor"
    assert create(client, headers).status_code == 403
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("disable", ["user", "tenant"])
def test_disabled_identity_invalidates_existing_session(system, disable):
    client, engine, _, _ = system
    headers = sign_in(system)
    with Session(engine) as db:
        row = db.get(User, ("a", "reviewer")) if disable == "user" else db.get(Tenant, "a")
        row.active = False
        db.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    _, _, _, password = system
    assert (
        client.post(
            "/api/v1/auth/token", json=dict(tenant_id="a", username="reviewer", password=password)
        ).status_code
        == 401
    )


def test_credentials_and_token_do_not_enter_logs_or_errors(system, caplog, capsys):
    client, _, settings, password = system
    caplog.set_level(logging.INFO, logger="bidding_compliance")
    headers = sign_in(system)
    client.post(
        "/api/v1/auth/token",
        json=dict(tenant_id="a", username="reviewer", password=password + "wrong"),
    )
    invalid = client.post(
        "/api/v1/auth/token",
        json=dict(tenant_id="a", username="reviewer", password=password, extra=password),
    )
    assert invalid.status_code == 422
    captured = caplog.text + capsys.readouterr().err + invalid.text + repr(settings)
    assert password not in captured
    assert headers["Authorization"].removeprefix("Bearer ") not in captured
    assert settings.auth_signing_key.get_secret_value() not in captured


def test_composite_foreign_key_prevents_cross_tenant_document_and_history_is_append_only(system):
    client, engine, _, _ = system
    project = create(client, sign_in(system)).json()
    with Session(engine) as db:
        set_tenant(db, "b")
        db.add(
            Document(
                tenant_id="b",
                document_id=str(uuid4()),
                project_id=project["project_id"],
                status="accepted",
                sha256="a" * 64,
                object_ref="fixture://document",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text("DELETE FROM project_version WHERE tenant_id = 'a'"))


def test_missing_key_fail_closed_and_production_rejects_sqlite(system):
    _, _, settings, _ = system
    no_key = settings.model_copy(update={"auth_signing_key": None})
    with TestClient(create_app(no_key)) as client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.post(
            "/api/v1/auth/token",
            json=dict(tenant_id="a", username="reviewer", password=str(uuid4())),
        )
        assert response.status_code == 500
        validate("Error", response.json())
    with pytest.raises(RuntimeError, match="SQLite"):
        make_engine(settings.model_copy(update={"app_env": "production"}))


def test_anonymous_and_input_boundaries(system):
    client, _, _, _ = system
    assert client.get("/api/v1/projects").status_code == 401
    headers = sign_in(system)
    assert client.post("/api/v1/projects", headers=headers, json=BODY).status_code == 422
    assert create(client, headers, budget_amount=-1).status_code == 422
    assert create(client, headers, role="admin").status_code == 422
    assert client.get("/api/v1/projects?limit=101", headers=headers).status_code == 422
    assert client.get("/api/v1/projects?offset=-1", headers=headers).status_code == 422
    assert json.loads(client.get("/api/v1/auth/me", headers=headers).text)["tenant_id"] == "a"


def test_signed_role_and_tenant_claims_cannot_override_database_identity(system):
    client, _, settings, _ = system
    token = sign_in(system, role="auditor")["Authorization"].removeprefix("Bearer ")
    key = settings.auth_signing_key.get_secret_value()
    claims = jwt.decode(token, key, algorithms=["HS256"], audience=settings.auth_audience)
    claims["role"] = "reviewer"
    forged = jwt.encode(claims, key, algorithm="HS256")
    assert create(client, {"Authorization": "Bearer " + forged}).status_code == 403
    claims["tenant_id"] = "b"
    forged = jwt.encode(claims, key, algorithm="HS256")
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + forged}).status_code
        == 401
    )


def test_idempotency_key_is_scoped_to_tenant(system):
    client, _, _, _ = system
    key = str(uuid4())
    responses = [
        client.post(
            "/api/v1/projects",
            json=BODY,
            headers={**sign_in(system, tenant=tenant), "Idempotency-Key": key},
        )
        for tenant in ("a", "b")
    ]
    assert all(r.status_code == 201 for r in responses)
    assert {r.json()["tenant_id"] for r in responses} == {"a", "b"}
    assert len({r.json()["project_id"] for r in responses}) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("budget_amount", "1200"),
        ("budget_amount", True),
        ("expected_version", "1"),
        ("expected_version", True),
    ],
)
def test_numeric_request_fields_follow_json_contract(system, field, value):
    client, _, _, _ = system
    headers = sign_in(system)
    if field == "budget_amount":
        response = create(client, headers, budget_amount=value)
    else:
        project = create(client, headers).json()
        response = client.put(
            "/api/v1/projects/" + project["project_id"],
            headers=headers,
            json={**BODY, "expected_version": value},
        )
    assert response.status_code == 422


def test_invalid_database_driver_is_sanitized_at_both_cli_boundaries():
    sensitive = "synthetic" + uuid4().hex
    environment = os.environ.copy()
    environment.update(
        APP_ENV="test",
        DATABASE_URL=sensitive + "://synthetic",
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
    )
    for args in (["-m", "bidding_compliance.api"], ["scripts/manage_identity.py", "migrate"]):
        result = subprocess.run(  # noqa: S603 - fixed local CLIs; no shell or external executable
            [sys.executable, *args],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        assert result.returncode in (1, 2)
        assert sensitive not in result.stdout + result.stderr
