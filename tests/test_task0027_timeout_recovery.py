"""TASK-0027/U04: queue submission is durable and idempotent across API restarts.

The frontend aborts ``POST /projects/{id}/reviews`` after 120 seconds
(``src/frontend/src/api/client.ts``). The backend keeps executing the persisted run and the
project page's task list (``GET /projects/{id}/reviews``) is the recovery path. These tests
prove, on the real HTTP route, the real service layer and the real tables:

1. a client that times out mid-request still finds the persisted task afterwards, with its
   real status (``running`` -> ``result_published``) and the same identity;
2. a repeated submission with the same idempotency key returns the same task, invokes the
   executor exactly once and adds no ledger record (a second document set under the same
   key is a 409 conflict, still with no second execution);
3. a new key is a new task (control: the suppression is the key, not a global block).

The executor double persists the same queued ReviewTask + ReviewEngineRun rows the real
ReviewEngine writes. The API does not invoke worker execution; a process restart can read the
pending row without replaying a model call. PostgreSQL worker claim, checkpoint recovery and
lease fencing are covered by the deployment-path U04 check.

Everything is loopback/local: the one real socket is the in-process Uvicorn server below.
No supplier, credential or external service is involved.
"""

from __future__ import annotations

import asyncio
import hashlib
import socket
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bidding_compliance.api import create_app
from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Role
from bidding_compliance.model_gateway.authorized_runtime import (
    FULL_CAPABILITY_AUTHORIZATION_ID,
    Dec005BudgetLedger,
)
from bidding_compliance.model_gateway.contracts import DataPolicy, ModelPolicy
from bidding_compliance.persistence.database import make_engine, migrate
from bidding_compliance.persistence.models import (
    AuditEvent,
    Document,
    DocumentContextVersion,
    Project,
    ReviewEngineRun,
    ReviewTask,
    Tenant,
    User,
)
from bidding_compliance.services.identity import PASSWORDS
from bidding_compliance.services.review_persistence import cancel_review as persist_cancel

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_CLIENT = ROOT / "src/frontend/src/api/client.ts"
FRONTEND_NOTICE = ROOT / "src/frontend/src/utils.ts"
PROFILE = "task0027-timeout-recovery"
LEDGER_SCOPE = "7" * 64


def policy() -> ModelPolicy:
    return ModelPolicy(
        profile=PROFILE,
        timeout_seconds=5.0,
        max_attempts=2,
        max_input_tokens=20_000,
        max_output_tokens=4_000,
        data_policy=DataPolicy.CONFIDENTIAL,
    )


class RecordingExecutor:
    """The boundary the API calls: persists the run and spends one ledger reservation.

    ``hold`` keeps the request open so a client can time out while the server keeps working,
    which is exactly what the browser's 120-second abort does.
    """

    def __init__(
        self, session_factory: sessionmaker[Session], ledger_path: Path, *, hold: float = 0.0
    ) -> None:
        self.session_factory = session_factory
        self.ledger_path = ledger_path
        self.ledger = Dec005BudgetLedger(
            ledger_path,
            scope_sha256=LEDGER_SCOPE,
            authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
        )
        self.hold = hold
        self.starts = 0
        self.creations = 0
        self.model_policy = policy()

    def prompt_sha256(self, version: str) -> str:
        return "a" * 64

    def create_run(self, principal, request) -> dict[str, object]:
        self.creations += 1
        now = datetime.now(UTC)
        documents = [item.model_dump(mode="json") for item in request.document_requests]
        with self.session_factory() as session:
            session.add(
                ReviewTask(
                    tenant_id=principal.tenant_id,
                    review_task_id=request.review_task_id,
                    project_id=request.project_id,
                    run_id=request.run_id,
                    status="queued",
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
                    status="queued",
                    action="start",
                    scheduled_at=now,
                    lease_id=None,
                    lease_until=None,
                    execution_generation=0,
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
            "status": "queued",
        }

    async def start(self, principal, request) -> dict[str, object]:
        self.starts += 1
        # The one place a real review could spend money; a duplicate submission must never
        # reach this line a second time.
        reservation = self.ledger.reserve_external(
            kind="llm",
            request_hash=hashlib.sha256(
                f"{request.review_task_id}:{self.starts}".encode()
            ).hexdigest(),
            ceiling=Decimal("0.25"),
        )
        self.ledger.settle_external(reservation, Decimal("0.001"))
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
            # Same ordering the real engine uses: establish the FK target first.
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
        if self.hold:
            await asyncio.sleep(self.hold)
        with self.session_factory() as session:
            row = session.get(
                ReviewEngineRun, (principal.tenant_id, request.review_task_id, request.run_id)
            )
            assert row is not None
            row.status = "result_published"
            row.updated_at = datetime.now(UTC)
            session.commit()
        return {
            "review_task_id": request.review_task_id,
            "run_id": request.run_id,
            "status": "result_published",
        }

    def cancel(self, principal, review_task_id: str, run_id: str) -> None:
        with self.session_factory() as session:
            persist_cancel(session, principal, review_task_id, run_id)


class System:
    """One SQLite-backed API host with a signed-in reviewer and one ready document."""

    def __init__(self, tmp_path: Path, *, hold: float = 0.0) -> None:
        self.password = str(uuid4())
        self.settings = Settings(
            _env_file=None,
            app_env="test",
            database_url="sqlite:///" + (tmp_path / "recovery.db").as_posix(),
            auth_signing_key=str(uuid4()) + str(uuid4()),
            object_storage_root=tmp_path / "objects",
        )
        self.engine = make_engine(self.settings)
        migrate(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        with Session(self.engine) as db:
            db.add(Tenant(tenant_id="a", name="合成甲", active=True))
            db.flush()
            hashed = PASSWORDS.hash(self.password)
            for role in Role:
                db.add(
                    User(
                        tenant_id="a",
                        user_id=role.value,
                        username=role.value,
                        password_hash=hashed,
                        role=role.value,
                        active=True,
                    )
                )
            db.commit()
        self.executor = RecordingExecutor(
            self.session_factory, tmp_path / "dec007-budget.sqlite3", hold=hold
        )
        self.app = create_app(self.settings, review_engine=self.executor)

    def close(self) -> None:
        self.engine.dispose()

    def token(self, client: httpx.Client | TestClient) -> str:
        response = client.post(
            "/api/v1/auth/token",
            json={"tenant_id": "a", "username": "reviewer", "password": self.password},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    def project(self, client, headers) -> str:
        response = client.post(
            "/api/v1/projects",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={
                "name": "超时找回合成项目",
                "procurement_type": "government",
                "project_type": "works",
                "region": "安徽省滁州市",
                "applicable_system": "合成内部制度",
                "budget_amount": 1000.0,
                "procurement_method": "tender",
                "buyer_type": "government_entity",
                "subject_type": "works",
                "legal_frameworks": ["tendering", "government_procurement"],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["project_id"]

    def document(self, project_id: str) -> str:
        document_id = str(uuid4())
        with Session(self.engine) as db:
            project = db.get(Project, ("a", project_id))
            assert project is not None
            db.add(
                Document(
                    tenant_id="a",
                    document_id=document_id,
                    project_id=project_id,
                    status="ready",
                    sha256="d" * 64,
                    object_ref="fixture://task0027/timeout-recovery",
                    file_format="docx",
                    media_type=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    size_bytes=128,
                    parse_version=1,
                    context_version=1,
                    issues=[],
                )
            )
            db.flush()
            db.add(
                DocumentContextVersion(
                    tenant_id="a",
                    document_id=document_id,
                    version=1,
                    payload={
                        "document_id": document_id,
                        "version": 1,
                        "candidates": [],
                        "manual": project.context,
                        "confirmed": True,
                        "reason": "synthetic context confirmation",
                    },
                    changed_by="reviewer",
                    changed_at=datetime.now(UTC),
                )
            )
            db.commit()
        return document_id

    def ledger_bytes(self) -> bytes:
        return self.executor.ledger_path.read_bytes()

    def ledger_summary(self) -> dict[str, object]:
        return dict(self.executor.ledger.summary())

    def run_rows(self) -> list[ReviewEngineRun]:
        with Session(self.engine) as db:
            return list(db.scalars(select(ReviewEngineRun)))


@pytest.fixture
def system(tmp_path):
    system = System(tmp_path)
    try:
        yield system
    finally:
        system.close()


def task_identity(tenant_id: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"task0011:{tenant_id}:{key}"))


# ------------------------------------------------------------ the browser timeout constant
def test_the_browser_aborts_the_review_request_after_120_seconds():
    """The scenario under test is the frontend's own 120 s abort, not an invented timeout."""
    client_source = FRONTEND_CLIENT.read_text(encoding="utf-8")
    assert "controller.abort()" in client_source
    assert "120_000" in client_source
    notice_source = FRONTEND_NOTICE.read_text(encoding="utf-8")
    assert "120 秒" in notice_source
    assert "「审查任务」列表" in notice_source
    project_source = (ROOT / "src/frontend/src/pages/project.tsx").read_text(encoding="utf-8")
    assert "REVIEW_TIMEOUT_NOTICE" in project_source  # the timeout path explains recovery


# --------------------------------------------------- duplicate submissions never re-execute
def test_the_same_idempotency_key_returns_the_task_and_executes_once(system):
    with TestClient(system.app) as client:
        headers = {"Authorization": "Bearer " + system.token(client)}
        project_id = system.project(client, headers)
        document_id = system.document(project_id)
        key = str(uuid4())

        first = client.post(
            f"/api/v1/projects/{project_id}/reviews",
            headers={**headers, "Idempotency-Key": key},
            json={"document_ids": [document_id]},
        )
        assert first.status_code == 202, first.text
        expected_id = task_identity("a", key)
        assert first.json()["review_task_id"] == expected_id
        assert first.json()["status"] == "queued"
        assert system.executor.creations == 1
        assert system.executor.starts == 0
        ledger_after_first = system.ledger_bytes()
        summary_after_first = system.ledger_summary()
        assert summary_after_first["llm_calls"] == 0

        duplicate = client.post(
            f"/api/v1/projects/{project_id}/reviews",
            headers={**headers, "Idempotency-Key": key},
            json={"document_ids": [document_id]},
        )
        assert duplicate.status_code == 202, duplicate.text
        assert duplicate.json() == first.json()  # the persisted task, not a new one
        assert system.executor.creations == 1  # the persisted queue row was not duplicated
        assert system.executor.starts == 0
        assert len(system.run_rows()) == 1
        assert system.ledger_bytes() == ledger_after_first  # no new ledger record
        assert system.ledger_summary() == summary_after_first
        assert summary_after_first["llm_calls"] == 0

        listed = client.get(f"/api/v1/projects/{project_id}/reviews", headers=headers)
        assert listed.status_code == 200, listed.text
        assert [item["review_task_id"] for item in listed.json()["items"]] == [expected_id]
        assert listed.json()["items"][0]["status"] == "queued"

        single = client.get(f"/api/v1/reviews/{expected_id}", headers=headers)
        assert single.status_code == 200, single.text
        assert single.json() == first.json()


def test_cancel_review_is_idempotent_reviewer_only_and_audited_once(system):
    with TestClient(system.app) as client:
        reviewer_headers = {"Authorization": "Bearer " + system.token(client)}
        operator_login = client.post(
            "/api/v1/auth/token",
            json={"tenant_id": "a", "username": "operator", "password": system.password},
        )
        assert operator_login.status_code == 200, operator_login.text
        operator_headers = {"Authorization": "Bearer " + operator_login.json()["access_token"]}
        project_id = system.project(client, reviewer_headers)
        document_id = system.document(project_id)
        created = client.post(
            f"/api/v1/projects/{project_id}/reviews",
            headers={**reviewer_headers, "Idempotency-Key": str(uuid4())},
            json={"document_ids": [document_id]},
        )
        assert created.status_code == 202, created.text
        review_task_id = created.json()["review_task_id"]
        run_id = created.json()["run_id"]
        endpoint = f"/api/v1/review-tasks/{review_task_id}/runs/{run_id}/cancel"
        ledger_before = system.ledger_bytes()

        denied = client.post(endpoint, headers=operator_headers)
        assert denied.status_code == 403
        assert (
            client.get(f"/api/v1/reviews/{review_task_id}", headers=reviewer_headers).json()[
                "status"
            ]
            == "queued"
        )

        cancelled = client.post(endpoint, headers=reviewer_headers)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        repeated = client.post(endpoint, headers=reviewer_headers)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["status"] == "cancelled"
        assert system.ledger_bytes() == ledger_before
        assert system.executor.starts == 0

        with Session(system.engine) as session:
            run = session.scalar(
                select(ReviewEngineRun).where(
                    ReviewEngineRun.tenant_id == "a",
                    ReviewEngineRun.review_task_id == review_task_id,
                    ReviewEngineRun.run_id == run_id,
                )
            )
            task = session.get(ReviewTask, ("a", review_task_id))
            cancel_events = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == "a",
                        AuditEvent.action == "review.cancel",
                        AuditEvent.resource_id == review_task_id,
                    )
                )
            )
            assert run is not None and run.status == "cancelled"
            assert run.lease_id is None and run.lease_until is None
            assert task is not None and task.status == "cancelled"
            assert len(cancel_events) == 1


def test_the_same_key_with_a_different_document_set_is_a_conflict_and_executes_once(system):
    with TestClient(system.app) as client:
        headers = {"Authorization": "Bearer " + system.token(client)}
        project_id = system.project(client, headers)
        first_document = system.document(project_id)
        second_document = system.document(project_id)
        key = str(uuid4())

        accepted = client.post(
            f"/api/v1/projects/{project_id}/reviews",
            headers={**headers, "Idempotency-Key": key},
            json={"document_ids": [first_document]},
        )
        assert accepted.status_code == 202, accepted.text
        ledger_bytes = system.ledger_bytes()

        conflict = client.post(
            f"/api/v1/projects/{project_id}/reviews",
            headers={**headers, "Idempotency-Key": key},
            json={"document_ids": [second_document]},
        )
        assert conflict.status_code == 409, conflict.text
        assert system.executor.creations == 1
        assert system.executor.starts == 0
        assert len(system.run_rows()) == 1
        assert system.ledger_bytes() == ledger_bytes

        # A different key is a genuinely new task: the suppression is the key, not a block.
        other = client.post(
            f"/api/v1/projects/{project_id}/reviews",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"document_ids": [first_document]},
        )
        assert other.status_code == 202, other.text
        assert other.json()["review_task_id"] != accepted.json()["review_task_id"]
        assert system.executor.creations == 2
        assert system.executor.starts == 0


# ------------------------------------------------------------------ the real HTTP timeout
class _Server(threading.Thread):
    def __init__(self, app, port: int) -> None:
        super().__init__(daemon=True)
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )

    def run(self) -> None:
        with asyncio.Runner() as runner:
            runner.run(self.server.serve())

    def stop(self) -> None:
        self.server.should_exit = True
        self.join(timeout=10)


def _free_port() -> int:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def test_queue_submission_survives_api_restart_without_starting_model_execution(tmp_path):
    """The real HTTP route commits a queue row and returns before worker execution."""
    system = System(tmp_path, hold=1.5)
    port = _free_port()
    server = _Server(system.app, port)
    server.start()
    restarted = None
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        with httpx.Client(base_url=base, trust_env=False, timeout=0.25) as setup:
            while time.monotonic() < deadline:
                try:
                    if setup.get("/api/v1/health", timeout=1.0).status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(0.1)
            else:
                raise AssertionError("the in-process server did not become healthy")
            token = system.token(setup)
            headers = {"Authorization": f"Bearer {token}"}
            project_id = system.project(setup, headers)
            document_id = system.document(project_id)
            key = str(uuid4())

            accepted = setup.post(
                f"/api/v1/projects/{project_id}/reviews",
                headers={**headers, "Idempotency-Key": key},
                json={"document_ids": [document_id]},
            )
            assert accepted.status_code == 202, accepted.text
            assert accepted.json()["status"] == "queued"
            assert system.executor.creations == 1
            assert system.executor.starts == 0
            assert system.ledger_summary()["llm_calls"] == 0

            # The persisted queue row remains readable after the API process restarts.
            server.stop()
            server = _Server(system.app, _free_port())
            server.start()
            base = f"http://127.0.0.1:{server.server.config.port}"
            restarted = httpx.Client(base_url=base, trust_env=False, timeout=0.25)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if restarted.get("/api/v1/health", timeout=1.0).status_code == 200:
                        break
                except httpx.TransportError:
                    time.sleep(0.1)
            else:
                raise AssertionError("the restarted in-process server did not become healthy")

            task_id = task_identity("a", key)
            listed = restarted.get(
                f"/api/v1/projects/{project_id}/reviews", headers=headers, timeout=5.0
            )
            assert listed.status_code == 200, listed.text
            items = {item["review_task_id"]: item for item in listed.json()["items"]}
            assert task_id in items, listed.text
            assert items[task_id]["status"] == "queued"
            assert system.executor.creations == 1
            assert system.executor.starts == 0

            # Duplicate submission returns the same pending row after restart.
            duplicate = restarted.post(
                f"/api/v1/projects/{project_id}/reviews",
                headers={**headers, "Idempotency-Key": key},
                json={"document_ids": [document_id]},
                timeout=5.0,
            )
            assert duplicate.status_code == 202, duplicate.text
            assert duplicate.json()["review_task_id"] == task_id
            assert duplicate.json()["status"] == "queued"
            assert system.executor.creations == 1
            assert system.executor.starts == 0
    finally:
        if restarted is not None:
            restarted.close()
        server.stop()
        system.close()
