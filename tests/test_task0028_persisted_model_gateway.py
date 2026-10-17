"""TASK-0028 local regression for durable model call persistence and fencing."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_legal_runs import system as base_system_fixture

from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.model_gateway.contracts import (
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from bidding_compliance.persistence.models import (
    ReviewEngineRun,
    ReviewModelCall,
    ReviewTask,
)
from bidding_compliance.services.persisted_model_gateway import PersistedModelGateway
from bidding_compliance.services.review_engine import ReviewEngine
from bidding_compliance.services.review_persistence import read_artifact

_base_system = base_system_fixture


class FakeGateway:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def prompt_sha256(self, prompt_version: str) -> str:
        assert prompt_version == "synthetic-prompt-v1"
        return "d" * 64

    async def generate_structured(self, request, output_schema, policy) -> ModelResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ModelResponse(
            call_id=request.call_id,
            provider="synthetic-provider",
            model="synthetic-model",
            profile=policy.profile,
            content={"decision": "candidate"},
            usage=ModelUsage(input_tokens=3, output_tokens=2, estimated_cost=0.0),
            latency_ms=1,
            response_hash="e" * 64,
        )


@pytest.fixture
def persisted_gateway_system(_base_system):
    engine, _, _ = _base_system
    run_id = str(uuid4())
    snapshot = {
        "document_requests": [{"raw_source_sha256": "f" * 64}],
    }
    with Session(engine) as session:
        session.add(
            ReviewTask(
                tenant_id="a",
                review_task_id="task-a",
                project_id="p",
                run_id=run_id,
                status="running",
            )
        )
        session.flush()
        session.add(
            ReviewEngineRun(
                tenant_id="a",
                review_task_id="task-a",
                run_id=run_id,
                project_id="p",
                actor_id="u",
                status="running",
                snapshot=snapshot,
                snapshot_hash="a" * 64,
                request_hash="b" * 64,
                retry_count=0,
                failure_code=None,
                publication_id=None,
                revision_id=None,
                action="start",
                scheduled_at=datetime.now(UTC),
                lease_id="current-lease",
                lease_until=datetime.now(UTC),
                execution_generation=2,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
        run = session.get(ReviewEngineRun, ("a", "task-a", run_id))
        assert run is not None

    principal = Principal("a", "u", "u", Role.REVIEWER, "s")
    worker_run = SimpleNamespace(
        tenant_id="a",
        review_task_id="task-a",
        run_id=run_id,
        actor_id="u",
        snapshot=snapshot,
        snapshot_hash="a" * 64,
        retry_count=0,
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    return engine, factory, principal, worker_run


def _request(
    call_id: str = "call-a",
    *,
    text: str = "synthetic input",
    tenant_id: str = "a",
    review_task_id: str = "task-a",
) -> ModelRequest:
    return ModelRequest(
        call_id=call_id,
        tenant_id=tenant_id,
        review_task_id=review_task_id,
        node_run_id="node-a",
        prompt_version="synthetic-prompt-v1",
        system_instruction="Analyze the synthetic example.",
        input_payload={"text": text},
    )


def _policy() -> ModelPolicy:
    return ModelPolicy(profile="synthetic-profile", timeout_seconds=5, max_attempts=1)


def _review_engine(factory: sessionmaker[Session]) -> ReviewEngine:
    return ReviewEngine(
        settings=Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+psycopg://local:local@localhost/review",
        ),
        session_factory=factory,
        gateway=FakeGateway(),
        model_policy=_policy(),
    )


def test_successful_response_is_saved_before_return_and_reused_after_restart(
    persisted_gateway_system,
):
    engine, factory, principal, run = persisted_gateway_system
    delegate = FakeGateway()
    request = _request()
    schema = {"type": "object", "required": ["decision"]}
    first_worker = PersistedModelGateway(
        delegate, session_factory=factory, principal=principal, run=run
    )

    first = asyncio.run(first_worker.generate_structured(request, schema, _policy()))

    with Session(engine) as session:
        call = session.get(ReviewModelCall, ("a", request.call_id))
        assert call is not None
        assert call.state == "succeeded"
        assert call.usage_status == "reported"
        assert call.response_ref is not None
        artifact = read_artifact(
            session,
            "a",
            call.response_ref,
            review_task_id="task-a",
            run_id=run.run_id,
        )
        assert artifact["call_id"] == request.call_id
        assert artifact["response"]["content"] == {"decision": "candidate"}

    restarted_worker = PersistedModelGateway(
        delegate, session_factory=factory, principal=principal, run=run
    )
    restored = asyncio.run(restarted_worker.generate_structured(request, schema, _policy()))

    assert restored == first
    assert delegate.calls == 1


def test_unknown_outcome_is_not_replayed_after_worker_restart(persisted_gateway_system):
    engine, factory, principal, run = persisted_gateway_system
    request = _request()
    schema = {"type": "object"}
    failing_delegate = FakeGateway(error=RuntimeError("synthetic transport interruption"))
    first_worker = PersistedModelGateway(
        failing_delegate, session_factory=factory, principal=principal, run=run
    )

    with pytest.raises(RuntimeError, match="synthetic transport interruption"):
        asyncio.run(first_worker.generate_structured(request, schema, _policy()))

    with Session(engine) as session:
        call = session.get(ReviewModelCall, ("a", request.call_id))
        assert call is not None
        assert call.state == "unknown"
        assert call.usage_status == "unknown"

    restarted_delegate = FakeGateway()
    restarted_worker = PersistedModelGateway(
        restarted_delegate, session_factory=factory, principal=principal, run=run
    )
    with pytest.raises(RuntimeError, match="not eligible for automatic replay"):
        asyncio.run(restarted_worker.generate_structured(request, schema, _policy()))
    assert restarted_delegate.calls == 0


def test_superseded_execution_identity_is_rejected_before_model_call(persisted_gateway_system):
    _, factory, _, run = persisted_gateway_system
    old_principal = Principal(
        "a",
        "u",
        "u",
        Role.REVIEWER,
        "",
        background_worker=True,
        execution_lease_id="old-lease",
        execution_generation=1,
    )
    delegate = FakeGateway()
    worker = PersistedModelGateway(
        delegate, session_factory=factory, principal=old_principal, run=run
    )

    with pytest.raises(FileExistsError, match="lease was superseded"):
        asyncio.run(worker.generate_structured(_request(), {"type": "object"}, _policy()))
    assert delegate.calls == 0


@pytest.mark.parametrize(
    ("tenant_id", "review_task_id"),
    [("b", "task-a"), ("a", "task-b")],
)
def test_model_call_cannot_cross_tenant_or_review_task(
    persisted_gateway_system, tenant_id, review_task_id
):
    engine, factory, principal, run = persisted_gateway_system
    delegate = FakeGateway()
    worker = PersistedModelGateway(
        delegate, session_factory=factory, principal=principal, run=run
    )

    with pytest.raises(ValueError, match="differs from its authorized review run"):
        asyncio.run(
            worker.generate_structured(
                _request(tenant_id=tenant_id, review_task_id=review_task_id),
                {"type": "object"},
                _policy(),
            )
        )

    with Session(engine) as session:
        assert session.get(ReviewModelCall, ("a", "call-a")) is None
    assert delegate.calls == 0


def test_expired_worker_claim_is_fenced_and_cancel_wins(persisted_gateway_system):
    engine, factory, _, _ = persisted_gateway_system
    review_engine = _review_engine(factory)

    claim = review_engine._claim_next(lease_seconds=60)

    assert claim is not None
    assert claim.status == "running"
    assert claim.execution_generation == 3
    assert claim.lease_id != "current-lease"
    worker_principal = review_engine._background_principal(claim)
    assert worker_principal.execution_lease_id == claim.lease_id
    assert worker_principal.execution_generation == claim.execution_generation
    assert review_engine._renew_lease(claim, lease_seconds=60)

    with Session(engine) as session:
        current = session.get(ReviewEngineRun, ("a", "task-a", claim.run_id))
        assert current is not None
        current.status = "cancelled"
        session.commit()
    review_engine._finish_claim(claim)

    with Session(engine) as session:
        current = session.get(ReviewEngineRun, ("a", "task-a", claim.run_id))
        assert current is not None
        assert current.status == "cancelled"
        assert current.lease_id is None
        assert current.lease_until is None


def test_expired_run_with_unresolved_call_fails_without_reclaim(persisted_gateway_system):
    engine, factory, _, run = persisted_gateway_system
    with Session(engine) as session:
        now = datetime.now(UTC)
        session.add(
            ReviewModelCall(
                tenant_id="a",
                call_id="unknown-call",
                review_task_id=run.review_task_id,
                run_id=run.run_id,
                actor_id="u",
                node_run_id="node-a",
                attempt=1,
                request_hash="c" * 64,
                document_hashes=["f" * 64],
                usage_status="unknown",
                state="dispatched",
                response_ref=None,
                response_hash=None,
                error_code=None,
                execution_generation=2,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    review_engine = _review_engine(factory)
    assert review_engine._claim_next(lease_seconds=60) is None

    with Session(engine) as session:
        current = session.get(ReviewEngineRun, ("a", run.review_task_id, run.run_id))
        call = session.get(ReviewModelCall, ("a", "unknown-call"))
        task = session.get(ReviewTask, ("a", run.review_task_id))
        assert current is not None and current.status == "failed"
        assert current.failure_code == "model_call_outcome_unknown"
        assert current.lease_id is None
        assert call is not None and call.state == "unknown"
        assert task is not None and task.status == "failed"
