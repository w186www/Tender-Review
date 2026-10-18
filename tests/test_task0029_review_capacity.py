"""TASK-0029 U06 review capacity pre-check and correction/version invalidation."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_identity_projects import sign_in
from test_identity_projects import system as shared_system
from test_ingestion import process, project_context_body, upload

from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import (
    Document,
    DocumentContextVersion,
    DocumentSection,
    ReviewEngineRun,
)
from bidding_compliance.services import identity, review_management

system = shared_system


def set_valid_project_context(client, project, headers):
    current = client.get(f"/api/v1/projects/{project}", headers=headers).json()
    keys = (
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
    body = {key: current[key] for key in keys}
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
    updated = client.put(f"/api/v1/projects/{project}", headers=headers, json=body)
    assert updated.status_code == 200, updated.text
    return {key: body[key] for key in keys}


def principal(system):
    _, engine, settings, password = system
    with Session(engine) as session:
        token = identity.login(session, settings, "a", "reviewer", password)
        return identity.authenticate(session, settings, token)


def test_review_capacity_is_rejected_before_a_run_is_created(system):
    client, engine, _, _ = system
    project, uploaded = upload(system)
    document = uploaded.json()["document_id"]
    headers = sign_in(system)
    project_context = set_valid_project_context(client, project, headers)
    with Session(engine) as session:
        set_tenant(session, "a")
        row = session.get(Document, ("a", document))
        row.status = "ready"
        row.parse_version = 1
        row.context_version = 1
        session.add(
            DocumentSection(
                tenant_id="a",
                document_id=document,
                section_id="oversized",
                ordinal=1,
                automatic={"text": "x" * 600_000, "locator": "pdf/page/1"},
                revision=1,
            )
        )
        session.add(
            DocumentContextVersion(
                tenant_id="a",
                document_id=document,
                version=1,
                payload={
                    "document_id": document,
                    "version": 1,
                    "candidates": [],
                    "manual": project_context,
                    "confirmed": True,
                    "reason": "synthetic context confirmation",
                },
                changed_by="reviewer",
                changed_at=datetime.now(UTC),
            )
        )
        session.commit()
    who = principal(system)
    with Session(engine) as session:
        with pytest.raises(ValueError, match="discovery capacity"):
            review_management.document_requests(session, who, project, [document])
    with Session(engine) as session:
        set_tenant(session, "a")
        assert session.scalar(select(func.count()).select_from(ReviewEngineRun)) == 0


def test_capacity_precheck_accepts_a_normal_parsed_document(system):
    client, engine, _, _ = system
    project, uploaded = upload(system)
    document = uploaded.json()["document_id"]
    assert process(system, document).status == "needs_confirmation"
    headers = sign_in(system)
    set_valid_project_context(client, project, headers)
    path = f"/api/v1/projects/{project}/documents/{document}"
    confirmed = client.post(
        path + "/context",
        headers=headers,
        json={
            "expected_version": 1,
            "reason": "合成上下文确认",
            "context": project_context_body(client, project, headers),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "ready"
    who = principal(system)
    with Session(engine) as session:
        requests = review_management.document_requests(session, who, project, [document])
    assert len(requests) == 1
    assert requests[0].document_id == document


def test_correction_after_ready_invalidates_context_and_blocks_the_old_review(system):
    client, engine, _, _ = system
    project, uploaded = upload(system)
    document = uploaded.json()["document_id"]
    assert process(system, document).status == "needs_confirmation"
    headers = sign_in(system)
    set_valid_project_context(client, project, headers)
    path = f"/api/v1/projects/{project}/documents/{document}"
    confirmed = client.post(
        path + "/context",
        headers=headers,
        json={
            "expected_version": 1,
            "reason": "合成上下文确认",
            "context": project_context_body(client, project, headers),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "ready"
    ready = confirmed.json()

    sections = client.get(path + "/sections", headers=headers).json()
    first = sections["items"][0]
    corrected = client.post(
        path + "/corrections",
        headers=headers,
        json={
            "expected_parse_version": ready["parse_version"],
            "reason": "人工修订后旧上下文必须失效",
            "corrections": [
                {
                    "section_id": first["section_id"],
                    "text": "人工修订后的有效文本，用于验证修订会使旧上下文失效。",
                }
            ],
        },
    )
    assert corrected.status_code == 200, corrected.text
    repaired = corrected.json()
    assert repaired["parse_version"] == ready["parse_version"] + 1
    assert repaired["context_version"] == ready["context_version"] + 1
    assert repaired["status"] == "needs_confirmation"

    current_context = client.get(path + "/context", headers=headers)
    assert current_context.status_code == 200
    assert current_context.json()["version"] == repaired["context_version"]
    assert current_context.json()["confirmed"] is False

    class RefusingEngine:
        model_policy = SimpleNamespace(profile="offline-deterministic")

        def create_run(self, *_args, **_kwargs):
            raise AssertionError("a document with an invalidated context must not create a run")

    client.app.state.review_engine = RefusingEngine()
    refused = client.post(
        f"/api/v1/projects/{project}/reviews",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"document_ids": [document]},
    )
    assert refused.status_code == 422, refused.text
    with Session(engine) as session:
        set_tenant(session, "a")
        assert session.scalar(select(func.count()).select_from(ReviewEngineRun)) == 0
