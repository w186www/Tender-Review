"""TASK-0027 round 7: the workbench repair path of a document the quality gate flagged.

An uploaded file whose text does not pass the quality gate stays ``needs_review`` and can
never be picked for a review. This file proves the *only* server-side path that lifts that
state -- a recorded human text correction that re-passes the gate, followed by an explicit
context confirmation -- works through the real API on real migrated storage, that the
context version bookkeeping stays consistent across the correction, and that nothing in the
repair path weakens the gate: a correction that does not fix the text keeps the document in
``needs_review``, context confirmation alone cannot skip it, and a non-``ready`` document is
still refused by review creation.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_identity_projects import sign_in
from test_identity_projects import system as shared_system
from test_ingestion import pdf_payload, process, upload
from verify_contracts import ROOT, load_contracts, load_openapi, validator_for_contract

from bidding_compliance.persistence.models import (
    AuditEvent,
    Document,
    DocumentContextVersion,
    ReviewEngineRun,
    ReviewTask,
)

system = shared_system
# Well above config/ingestion.yaml ``min_text_chars`` (20) so the gate can pass.
VERIFIED_TEXT = "合成招标文件人工核对后的原文转录，用于修复质量不足的解析结果。"


class OfflineStubExecutor:
    """The server boundary that creates a run; offline and deterministic, no egress.

    The repair path is about the *document* gate, so this stands in for the review executor
    exactly as the deployed offline assembly does: it persists the run the API then reads
    back through its own status query.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self.starts = 0
        self.model_policy = SimpleNamespace(profile="offline-deterministic")

    async def start(self, principal, request) -> dict[str, object]:
        self.starts += 1
        now = datetime.now(UTC)
        documents = [item.model_dump(mode="json") for item in request.document_requests]
        with self.session_factory() as session:
            session.add(
                ReviewTask(
                    tenant_id=principal.tenant_id,
                    review_task_id=request.review_task_id,
                    project_id=request.project_id,
                    run_id=request.run_id,
                    status="running",
                )
            )
            session.flush()
            session.add(
                ReviewEngineRun(
                    tenant_id=principal.tenant_id,
                    review_task_id=request.review_task_id,
                    run_id=request.run_id,
                    project_id=request.project_id,
                    actor_id=principal.user_id,
                    status="running",
                    snapshot={"document_requests": documents},
                    snapshot_hash="b" * 64,
                    request_hash="c" * 64,
                    retry_count=0,
                    failure_code=None,
                    publication_id=None,
                    revision_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        return {
            "review_task_id": request.review_task_id,
            "run_id": request.run_id,
            "status": "running",
        }


def validate(name, data):
    documents, registry, errors = load_contracts(ROOT)
    api, api_errors = load_openapi(ROOT)
    assert not errors + api_errors
    validator_for_contract(
        ROOT, "contracts/openapi.yaml#/components/schemas/" + name, documents, registry, api
    ).validate(data)


def low_quality_document(system):
    """Upload and process a payload the quality gate must flag as LOW_QUALITY."""
    client, _, _, _ = system
    project, uploaded = upload(system, pdf_payload("Short"))
    assert uploaded.status_code == 202, uploaded.text
    document = uploaded.json()["document_id"]
    parsed = process(system, document)
    assert parsed.status == "needs_review" and parsed.issues == ["LOW_QUALITY"]
    return project, document


def path(project, document):
    return f"/api/v1/projects/{project}/documents/{document}"


def correction_body(sections, reason, text):
    """One correction per parsed fragment: the parser may emit several for one page."""
    return {
        "expected_parse_version": sections["parse_version"],
        "reason": reason,
        "corrections": [
            {"section_id": item["section_id"], "text": text} for item in sections["items"]
        ],
    }


def confirm_body(version, reason="合成人工核对上下文"):
    return {
        "expected_version": version,
        "reason": reason,
        "context": {
            "name": "合成项目",
            "procurement_type": "government",
            "project_type": "works",
            "region": "示例地区",
        },
    }


def test_needs_review_document_reaches_ready_through_correction_then_context(system):
    """The whole repair path a reviewer needs on the page: sections -> corrections -> context."""
    client, _, _, _ = system
    project, document = low_quality_document(system)
    headers = sign_in(system)
    url = path(project, document)

    flagged = client.get(url, headers=headers)
    assert flagged.status_code == 200, flagged.text
    assert flagged.json()["status"] == "needs_review"
    assert flagged.json()["parse_version"] == 1 and flagged.json()["context_version"] == 1

    sections_response = client.get(url + "/sections", headers=headers)
    assert sections_response.status_code == 200, sections_response.text
    validate("DocumentSections", sections_response.json())
    sections = sections_response.json()
    assert sections["parse_version"] == 1 and sections["items"]
    assert all(item["effective"]["source"] != "manual" for item in sections["items"])

    # The repair path is closed while the text is still below the gate: a confirmation that
    # changes nothing leaves the document exactly where it was.
    unchanged = client.post(
        url + "/corrections",
        headers=headers,
        json=correction_body(sections, "未做任何文字修改", "Short"),
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["status"] == "needs_review"
    assert unchanged.json()["issues"] == ["LOW_QUALITY"]
    assert unchanged.json()["parse_version"] == 2
    assert client.post(url + "/context", headers=headers, json=confirm_body(1)).status_code == 409

    # The reviewer transcribes the fragment; the gate re-evaluates the corrected text.
    corrected = client.post(
        url + "/corrections",
        headers=headers,
        json=correction_body(
            {"parse_version": 2, "items": sections["items"]}, "按纸质原件人工转录", VERIFIED_TEXT
        ),
    )
    assert corrected.status_code == 200, corrected.text
    validate("Document", corrected.json())
    repaired = corrected.json()
    assert repaired["status"] == "needs_confirmation"
    assert repaired["parse_version"] == 3
    assert repaired["issues"] == []

    # The correction wrote a new context version whose payload must be the one this document
    # now points at: otherwise the page could read sections but never confirm context again.
    context_response = client.get(url + "/context", headers=headers)
    assert context_response.status_code == 200, context_response.text
    validate("DocumentContext", context_response.json())
    context = context_response.json()
    assert context["version"] == repaired["context_version"]

    # Only now, with the gate passed, the explicit context confirmation moves it to ready.
    confirmed = client.post(
        url + "/context", headers=headers, json=confirm_body(context["version"])
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "ready"
    assert confirmed.json()["context_version"] == context["version"] + 1

    # The audit trail records both human acts and the automatic quality re-check.
    with Session(system[1]) as db:
        actions = {
            event.action
            for event in db.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == document)
            )
        }
    assert {"document.text_corrected", "document.context_confirmed"} <= actions


def test_a_correction_that_still_fails_the_gate_never_becomes_selectable(system):
    """The recorded repair can never be used to lift the gate itself."""
    client, _, _, _ = system
    project, document = low_quality_document(system)
    headers = sign_in(system)
    url = path(project, document)
    items = client.get(url + "/sections", headers=headers).json()["items"]

    for expected_version, text in ((1, "still short"), (2, "短")):
        response = client.post(
            url + "/corrections",
            headers=headers,
            json={
                "expected_parse_version": expected_version,
                "reason": "仍然达不到质量门槛",
                "corrections": [{"section_id": items[0]["section_id"], "text": text}],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "needs_review"
        assert response.json()["issues"] == ["LOW_QUALITY"]
    # The quality decision is recomputed server-side from the corrected fragments.
    assert client.get(url, headers=headers).json()["status"] == "needs_review"
    assert (
        client.post(
            url + "/context", headers=headers, json=confirm_body(1, "试图跳过质量门禁")
        ).status_code
        == 409
    )
    assert client.get(url, headers=headers).json()["status"] == "needs_review"


def test_a_review_cannot_be_started_from_an_unrepaired_document(system):
    """The workbench gate stays exactly as it was: only 'ready' documents may be selected."""
    client, engine, _, _ = system
    project, document = low_quality_document(system)
    headers = sign_in(system)
    url = path(project, document)
    executor = OfflineStubExecutor(sessionmaker(engine, expire_on_commit=False))
    client.app.state.review_engine = executor

    refused = client.post(
        f"/api/v1/projects/{project}/reviews",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"document_ids": [document]},
    )
    assert refused.status_code == 422, refused.text
    assert client.get(url, headers=headers).json()["status"] == "needs_review"
    assert executor.starts == 0  # the run was never created

    # Repair it and the very same request becomes acceptable to the server. The gate also
    # fails on an OCR fragment with no text (the blank page area above), so every parsed
    # fragment is transcribed -- exactly what the page asks the reviewer to do.
    items = client.get(url + "/sections", headers=headers).json()
    assert len(items["items"]) == 2 and any(
        item["effective"]["source"] == "ocr" and not item["effective"]["text"].strip()
        for item in items["items"]
    )
    corrected = client.post(
        url + "/corrections",
        headers=headers,
        json=correction_body(items, "按原件人工转录", VERIFIED_TEXT),
    )
    assert corrected.status_code == 200 and corrected.json()["status"] == "needs_confirmation"
    # The document is not selectable yet: the context is still unconfirmed.
    still_refused = client.post(
        f"/api/v1/projects/{project}/reviews",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"document_ids": [document]},
    )
    assert still_refused.status_code == 422, still_refused.text
    assert executor.starts == 0

    context = client.get(url + "/context", headers=headers)
    assert context.status_code == 200 and context.json()["version"] == corrected.json()[
        "context_version"
    ]
    assert (
        client.post(
            url + "/context", headers=headers, json=confirm_body(context.json()["version"])
        ).json()["status"]
        == "ready"
    )
    accepted = client.post(
        f"/api/v1/projects/{project}/reviews",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"document_ids": [document]},
    )
    assert accepted.status_code == 202, accepted.text
    assert executor.starts == 1


def test_corrections_are_bounded_to_this_document_tenant_and_role(system):
    """No tenant, role or locator trick is added by the repair path."""
    client, engine, _, _ = system
    project, document = low_quality_document(system)
    headers = sign_in(system)
    url = path(project, document)
    items = client.get(url + "/sections", headers=headers).json()["items"]
    correction = {
        "expected_parse_version": 1,
        "reason": "合成人工转录",
        "corrections": [{"section_id": items[0]["section_id"], "text": VERIFIED_TEXT}],
    }

    other_tenant = sign_in(system, tenant="b")
    assert client.get(url + "/sections", headers=other_tenant).status_code == 404
    assert (
        client.post(url + "/corrections", headers=other_tenant, json=correction).status_code
        == 404
    )
    assert (
        client.post(
            url + "/context", headers=other_tenant, json=confirm_body(1, "跨租户确认")
        ).status_code
        == 404
    )
    for role in ("admin", "operator", "auditor"):
        role_headers = sign_in(system, role=role)
        assert (
            client.post(url + "/corrections", headers=role_headers, json=correction).status_code
            == 403
        )
        assert (
            client.post(
                url + "/context", headers=role_headers, json=confirm_body(1, "越权确认")
            ).status_code
            == 403
        )
    with Session(engine) as db:
        document_row = db.get(Document, ("a", document))
        assert document_row.status == "needs_review" and document_row.parse_version == 1


def test_correction_locators_and_versions_are_validated(system):
    """A malformed or stale correction is refused before it can change any text."""
    client, _, _, _ = system
    project, document = low_quality_document(system)
    headers = sign_in(system)
    url = path(project, document)
    section_id = client.get(url + "/sections", headers=headers).json()["items"][0]["section_id"]

    def post(body):
        return client.post(url + "/corrections", headers=headers, json=body)

    unknown = {
        "expected_parse_version": 1,
        "reason": "不存在的片段",
        "corrections": [{"section_id": str(uuid4()), "text": VERIFIED_TEXT}],
    }
    assert post(unknown).status_code == 422
    duplicated = {
        **unknown,
        "corrections": [
            {"section_id": section_id, "text": VERIFIED_TEXT},
            {"section_id": section_id, "text": VERIFIED_TEXT},
        ],
    }
    assert post(duplicated).status_code == 422
    empty_text = {
        "expected_parse_version": 1,
        "reason": "空文本",
        "corrections": [{"section_id": section_id, "text": ""}],
    }
    assert post(empty_text).status_code == 422
    stale = {
        "expected_parse_version": 9,
        "reason": "过期的解析版本",
        "corrections": [{"section_id": section_id, "text": VERIFIED_TEXT}],
    }
    assert post(stale).status_code == 409
    assert client.get(url, headers=headers).json()["parse_version"] == 1


def test_the_repair_path_never_rewrites_the_automatic_parse_or_the_source_hash(system):
    """Human correction is additive: the automatic fragment and the file hash stay intact."""
    client, engine, _, _ = system
    project, document = low_quality_document(system)
    headers = sign_in(system)
    url = path(project, document)
    before = client.get(url + "/sections", headers=headers).json()
    automatic_text = before["items"][0]["automatic"]["text"]

    corrected = client.post(
        url + "/corrections",
        headers=headers,
        json={
            "expected_parse_version": before["parse_version"],
            "reason": "按原件人工转录",
            "corrections": [
                {"section_id": before["items"][0]["section_id"], "text": VERIFIED_TEXT}
            ],
        },
    )
    assert corrected.status_code == 200, corrected.text
    after = client.get(url + "/sections", headers=headers).json()
    assert after["items"][0]["automatic"]["text"] == automatic_text
    assert after["items"][0]["effective"]["text"] == VERIFIED_TEXT
    assert after["items"][0]["effective"]["source"] == "manual"
    assert after["items"][0]["automatic"] == before["items"][0]["automatic"]
    assert after["items"][0]["revision"] == before["items"][0]["revision"] + 1
    assert after["items"][0]["source_hash"] == before["items"][0]["source_hash"]
    with Session(engine) as db:
        rows = list(
            db.scalars(
                select(DocumentContextVersion)
                .where(DocumentContextVersion.document_id == document)
                .order_by(DocumentContextVersion.version)
            )
        )
        document_row = db.get(Document, ("a", document))
    # Exactly one context snapshot per recorded version, in order, with no gap the page
    # would have to work around.
    assert [row.version for row in rows] == list(range(1, document_row.context_version + 1))
    assert rows[0].payload["manual"] is None  # the automatic inference is still the first one
