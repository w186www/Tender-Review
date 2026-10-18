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
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_identity_projects import create, sign_in
from test_identity_projects import system as shared_system
from test_ingestion import upload
from verify_contracts import ROOT, load_contracts, load_openapi, validator_for_contract

from bidding_compliance.core.config import Settings
from bidding_compliance.model_gateway.authorization import AuthorizationPolicy
from bidding_compliance.model_gateway.authorized_runtime import (
    FULL_CAPABILITY_AUTHORIZATION_ID,
)
from bidding_compliance.model_gateway.contracts import DataPolicy
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.persistence.models import (
    AuditEvent,
    Document,
    DocumentContextVersion,
    ReviewEngineRun,
    ReviewTask,
)
from bidding_compliance.services.real_ai_runtime import (
    AuthorizedRealReviewEngine,
    AuthorizedTenderMinimizer,
    FileAuthorizationRegistry,
    real_ai_policy,
    resolve_authorized_documents,
    resolve_real_runtime_authorization,
)

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
    return f"/api/v1/projects/{project_id}/documents/{document_id}/external-authorization"


def set_valid_project_context(client, project_id, headers):
    current = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    fields = (
        "name",
        "procurement_type",
        "project_type",
        "region",
        "industry",
        "budget_amount",
        "applicable_system",
        "procurement_method",
        "buyer_type",
        "subject_type",
        "legal_frameworks",
    )
    body = {key: current[key] for key in fields}
    body.update(
        {
            "region": "安徽省滁州市",
            "procurement_method": "tender",
            "buyer_type": "government_entity",
            "subject_type": "works",
            "legal_frameworks": ["tendering", "government_procurement"],
            "expected_version": current["version"],
        }
    )
    saved = client.put(f"/api/v1/projects/{project_id}", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    return {key: body[key] for key in fields}


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
    denied = client.post(url, headers=auditor, json={"reason": "审计员无权登记", "confirmed": True})
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


def test_the_confirmation_of_the_uploaded_file_is_what_lets_that_file_leave_the_host(
    system, tmp_path
):
    """Upload -> refused egress -> API confirmation -> allowed egress, for one real hash.

    The hash the reviewer confirms is not a constant in this test: it is the SHA-256 the
    API itself resolved for the uploaded document, and the very same running-process
    assembly the assemblies pass (`RealRuntimeAuthorization.allowed_document_source`) is
    what flips from refusing to allowing that one file. The second uploaded document is
    never confirmed and must stay local-only.
    """
    client, engine, _, _ = system
    registry_path = tmp_path / "authorization-registry.jsonl"
    ledger_path = tmp_path / "dec007-budget.sqlite3"
    client.app.state.external_authorization_registry = FileAuthorizationRegistry(registry_path)
    resolution = resolve_real_runtime_authorization(
        {
            "DEC007_AUTHORIZATION_ID": FULL_CAPABILITY_AUTHORIZATION_ID,
            "DEC007_AUTHORIZATION_REGISTRY": str(registry_path),
            "DEC007_LEDGER_PATH": str(ledger_path),
        },
        private_root=tmp_path,
    )
    headers = sign_in(system)
    project, uploaded = upload(system)
    document = uploaded.json()
    _, unconfirmed = upload(system)
    other = unconfirmed.json()
    assert other["sha256"] != document["sha256"]

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite:///" + (tmp_path / "egress.db").as_posix(),
    )
    review_engine = AuthorizedRealReviewEngine(
        settings=settings,
        session_factory=sessionmaker(make_engine(settings), expire_on_commit=False),
        gateway=None,
        model_policy=real_ai_policy(),
        legal_root=tmp_path,
        authorization=AuthorizationPolicy(
            trusted_calls={}, tenant_providers={}, provider_data_policies={}
        ),
        allowed_document_sha256=resolution.allowed_document_source,
    )

    # 1) Nothing is authorized yet: the uploaded file may not be processed externally.
    assert review_engine.allowed_document_sha256 == frozenset()
    with pytest.raises(PermissionError):
        review_engine._require_authorized_documents({document["sha256"]})
    with pytest.raises(PermissionError):
        review_engine._require_authorized_documents({other["sha256"]})

    # 2) The reviewer confirms that one file through the API.
    recorded = client.post(
        endpoint(project, document["document_id"]),
        headers=headers,
        json={"reason": "演示用合成样本，已确认有权处理", "confirmed": True},
    )
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["sha256"] == document["sha256"]

    # 3) The already-running assembly now authorizes exactly that hash -- and nothing else.
    assert review_engine.allowed_document_sha256 == frozenset({document["sha256"]})
    review_engine._require_authorized_documents({document["sha256"]})
    with pytest.raises(PermissionError):
        review_engine._require_authorized_documents({other["sha256"]})
    with pytest.raises(PermissionError):
        review_engine._require_authorized_documents({document["sha256"], other["sha256"]})

    # 4) The last gate before the wire: the minimizer emits the confirmed file's minimized
    #    fragment and refuses the unconfirmed one.
    minimizer = AuthorizedTenderMinimizer(resolution.allowed_document_source)
    section = {"section_key": "s000000c000", "text": "合成资格条件原文。", "document_sha256": ""}
    section["document_sha256"] = document["sha256"]
    assert minimizer({"discovery_sections": [section]}, DataPolicy.CONFIDENTIAL) == {
        "discovery_sections": [{"section_key": "s000000c000", "text": "合成资格条件原文。"}]
    }
    section["document_sha256"] = other["sha256"]
    with pytest.raises(ValueError, match="outside authorized scope"):
        minimizer({"discovery_sections": [section]}, DataPolicy.CONFIDENTIAL)

    # 5) The registry holds exactly one audited row, and the allowlist is exactly one hash:
    #    there is no "allow everything" switch and no implicit approval.
    lines = registry_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert set(row) == REGISTRY_FIELDS
    assert row["reason"] == "演示用合成样本，已确认有权处理"
    assert row["approved_by"] == "reviewer"
    assert row["approved_at"] and row["action"] == "approve"
    reloaded = FileAuthorizationRegistry(registry_path)
    assert reloaded.allowed_sha256() == frozenset({document["sha256"]})
    assert resolve_authorized_documents(registry=reloaded, environment_hashes=()) == frozenset(
        {document["sha256"]}
    )
    different_tenant_registry = FileAuthorizationRegistry(tmp_path / "other-registry.jsonl")
    assert different_tenant_registry.allowed_sha256() == frozenset()

    # 6) No budget ledger was created for this file, and the tenant audit trail names the
    #    actor and the resource.
    assert not ledger_path.exists()
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


def test_starting_a_review_of_an_unconfirmed_file_is_refused_with_403(system, tmp_path):
    """The workbench must be able to tell "not authorized" apart from "state changed".

    The review endpoint refuses a run whose document is not in the authorization before any
    gateway work; the refusal has to surface as 403 (an authorization answer the page can
    explain) instead of the generic 409 "the data changed underneath you".
    """
    client, engine, _, _ = system
    registry_path = tmp_path / "authorization-registry.jsonl"
    client.app.state.external_authorization_registry = FileAuthorizationRegistry(registry_path)
    resolution = resolve_real_runtime_authorization(
        {
            "DEC007_AUTHORIZATION_ID": FULL_CAPABILITY_AUTHORIZATION_ID,
            "DEC007_AUTHORIZATION_REGISTRY": str(registry_path),
            "DEC007_LEDGER_PATH": str(tmp_path / "dec007-budget.sqlite3"),
        },
        private_root=tmp_path,
    )
    headers = sign_in(system)
    project, uploaded = upload(system)
    document = uploaded.json()
    authoritative_context = set_valid_project_context(client, project, headers)
    # A ready document: only the external-processing authorization is missing.
    with Session(engine) as db:
        row = db.get(Document, ("a", document["document_id"]))
        row.status, row.parse_version, row.context_version = "ready", 1, 1
        db.add(
            DocumentContextVersion(
                tenant_id="a",
                document_id=document["document_id"],
                version=1,
                payload={
                    "document_id": document["document_id"],
                    "version": 1,
                    "candidates": [],
                    "manual": authoritative_context,
                    "confirmed": True,
                    "reason": "synthetic context confirmation",
                },
                changed_by="reviewer",
                changed_at=datetime.now(UTC),
            )
        )
        db.commit()

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite:///" + (tmp_path / "refusal.db").as_posix(),
    )
    client.app.state.review_engine = AuthorizedRealReviewEngine(
        settings=settings,
        session_factory=sessionmaker(make_engine(settings), expire_on_commit=False),
        gateway=None,
        model_policy=real_ai_policy(),
        legal_root=tmp_path,
        authorization=AuthorizationPolicy(
            trusted_calls={}, tenant_providers={}, provider_data_policies={}
        ),
        allowed_document_sha256=resolution.allowed_document_source,
    )
    refused = client.post(
        f"/api/v1/projects/{project}/reviews",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"document_ids": [document["document_id"]]},
    )
    assert refused.status_code == 403, refused.text
    validate("Error", refused.json())
    # Nothing was frozen, nothing was queued: the refusal happened before any gateway work.
    with Session(engine) as db:
        assert list(db.scalars(select(ReviewEngineRun))) == []
        assert list(db.scalars(select(ReviewTask))) == []
    assert not registry_path.exists()

    # Confirming the file is what makes the same request acceptable to the engine gate.
    assert (
        client.post(
            endpoint(project, document["document_id"]),
            headers=headers,
            json={"reason": "登记后再发起审查", "confirmed": True},
        ).status_code
        == 201
    )
    client.app.state.review_engine._require_authorized_documents({document["sha256"]})
