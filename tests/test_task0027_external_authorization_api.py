"""TASK-0027: the reviewer's per-file external-processing confirmation (API level).

The endpoint is the workbench half of the DEC-007 per-file authorization: an authenticated
reviewer confirms *one uploaded document* and the append-only registry row records the file
SHA-256, the document identity, the reason, the timestamp and the actor -- the same file the
operator CLI writes and the egress gate re-reads. These tests use the real migrated database,
the real authenticated API and the real registry class; no supplier is reachable and no
ledger file is created by any of them.

The route is deliberately absent from this round's frozen OpenAPI contract
(``contracts/**`` is not modified), so the response is asserted by its exact field set and
values rather than through ``validator_for_contract``; the shared ``Error`` envelope is
still validated against the contract.
"""

import json
import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_identity_projects import create, sign_in
from test_identity_projects import system as shared_system
from test_ingestion import upload
from verify_contracts import ROOT, load_contracts, load_openapi, validator_for_contract

from bidding_compliance.persistence.models import AuditEvent
from bidding_compliance.services.real_ai_runtime import FileAuthorizationRegistry

system = shared_system
REGISTRY_FIELDS = {"action", "sha256", "document_id", "reason", "approved_at", "approved_by"}


def validate(name, data):
    documents, registry, errors = load_contracts(ROOT)
    api, api_errors = load_openapi(ROOT)
    assert not errors + api_errors
    validator_for_contract(
        ROOT, "contracts/openapi.yaml#/components/schemas/" + name, documents, registry, api
    ).validate(data)


def endpoint(project_id, document_id):
    return (
        f"/api/v1/projects/{project_id}/documents/{document_id}/external-authorization"
    )


def test_the_endpoint_is_unavailable_when_no_real_authorization_is_assembled(system):
    """Offline assemblies have no per-file registry: the confirmation fails closed (503)."""
    client, _, _, _ = system
    headers = sign_in(system)
    project, uploaded = upload(system)
    document = uploaded.json()
    response = client.post(
        endpoint(project, document["document_id"]),
        headers=headers,
        json={"reason": "面试演示合成样本", "confirmed": True},
    )
    assert response.status_code == 503, response.text
    validate("Error", response.json())


def test_reviewer_confirms_one_file_and_the_audit_row_records_it(system, tmp_path):
    client, engine, _, _ = system
    registry_path = tmp_path / "authorization-registry.jsonl"
    registry = FileAuthorizationRegistry(registry_path)
    client.app.state.external_authorization_registry = registry
    assert not registry_path.exists()  # an empty registry never creates the file

    headers = sign_in(system)
    project, uploaded = upload(system)
    document = uploaded.json()
    url = endpoint(project, document["document_id"])

    # The declaration is server-validated: no confirmation, no record.
    missing = client.post(url, headers=headers, json={"reason": "缺少确认"})
    assert missing.status_code == 422, missing.text
    false_confirmed = client.post(
        url, headers=headers, json={"reason": "确认值不是 true", "confirmed": False}
    )
    assert false_confirmed.status_code == 422, false_confirmed.text
    extra = client.post(
        url,
        headers=headers,
        json={"reason": "多字段", "confirmed": True, "sha256": "a" * 64},
    )
    assert extra.status_code == 422, extra.text  # the caller cannot supply a hash
    empty = client.post(url, headers=headers, json={"reason": "", "confirmed": True})
    assert empty.status_code == 422, empty.text

    # Only a reviewer (the role that may write projects) can record the confirmation.
    auditor = sign_in(system, role="auditor")
    denied = client.post(
        url, headers=auditor, json={"reason": "审计员无权登记", "confirmed": True}
    )
    assert denied.status_code == 403, denied.text
    assert not registry_path.exists()

    recorded = client.post(
        url, headers=headers, json={"reason": "面试演示合成样本", "confirmed": True}
    )
    assert recorded.status_code == 201, recorded.text
    payload = recorded.json()
    assert set(payload) == {"document_id", "sha256", "action", "approved_at", "approved_by"}
    assert payload["document_id"] == document["document_id"]
    assert payload["sha256"] == document["sha256"]
    assert payload["action"] == "approve"
    assert payload["approved_by"] == "reviewer"
    assert re.fullmatch(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", payload["approved_at"])

    # The append-only trail holds exactly one validated row for this very file.
    lines = registry_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert set(row) == REGISTRY_FIELDS
    assert row["action"] == "approve"
    assert row["sha256"] == document["sha256"]
    assert row["document_id"] == document["document_id"]
    assert row["approved_by"] == "reviewer"
    reloaded = FileAuthorizationRegistry(registry_path)
    assert reloaded.allowed_sha256() == frozenset({document["sha256"]})

    # A second, unconfirmed document is still absent: there is no "allow everything" path.
    _, other = upload(system)
    assert other.json()["sha256"] != document["sha256"]
    assert other.json()["sha256"] not in reloaded.allowed_sha256()

    # The tenant audit trail records who confirmed what, and the response never carries it.
    with Session(engine) as db:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "document.external_authorization_approved"
                )
            )
        )
    assert len(events) == 1
    assert events[0].actor_id == "reviewer"
    assert events[0].resource_id == document["document_id"]
    # The response never leaks the registry location or any other file's hash.
    assert str(registry_path) not in json.dumps(payload)
    assert other.json()["sha256"] not in json.dumps(payload)


def test_the_confirmation_does_not_touch_any_budget_ledger(system, tmp_path):
    """Approving a file is an authorization record, never a quota event."""
    client, _, settings, _ = system
    registry_path = tmp_path / "authorization-registry.jsonl"
    client.app.state.external_authorization_registry = FileAuthorizationRegistry(registry_path)
    headers = sign_in(system)
    project, uploaded = upload(system)
    document = uploaded.json()
    assert (
        client.post(
            endpoint(project, document["document_id"]),
            headers=headers,
            json={"reason": "台账不被触碰", "confirmed": True},
        ).status_code
        == 201
    )
    # No DEC ledger was created or modified anywhere by the endpoint.
    assert list(tmp_path.glob("*budget*.sqlite3")) == []
    assert not (tmp_path / "dec007-budget.sqlite3").exists()
    assert (tmp_path / "authorization-registry.jsonl").exists()
    assert settings.app_env == "test"


def test_a_forged_or_missing_document_never_gets_authorized(system, tmp_path):
    client, _, _, _ = system
    registry_path = tmp_path / "authorization-registry.jsonl"
    client.app.state.external_authorization_registry = FileAuthorizationRegistry(registry_path)
    headers = sign_in(system)
    project = create(client, headers).json()["project_id"]
    unknown = client.post(
        endpoint(project, str(uuid4())),
        headers=headers,
        json={"reason": "不存在的文档", "confirmed": True},
    )
    assert unknown.status_code == 404, unknown.text
    assert not registry_path.exists()
