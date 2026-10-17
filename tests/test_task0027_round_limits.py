"""DEC-007 controlled round: the tightened ceilings are a hard gate, not an estimate.

The round under test is the one the operator runs before the first paid call:
``llm_limit=4``, ``embedding_limit=322`` (312 batches are already recorded) and
``total_cny=2`` cumulative, including the 0.1035070 CNY settled prebuild and the two LLM
reservations of the recorded phase-one round (the phase-two baseline is 2/312/0.1062161 in
``scripts/task0027_ledger_baseline.py``). Every supplier interaction below uses an explicit
synthetic transport; no test opens a socket, reads a credential or reaches a paid supplier.

Boundary of the agreed option A (2026-10-16): the ledger *file* stores counters, and the
ceilings are per-process parameters, so the file alone cannot stop a different process that
opens it with the wider authorization ceilings. The tests record that boundary explicitly
(test_option_a_boundary...) and prove the parts this round does guarantee: one shared,
cumulative counter file; a serving assembly that cannot be widened; and a hard refusal
before any supplier request.
"""

import asyncio
import hashlib
import json
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    EmbeddingProtocolError,
    EmbeddingProviderUnavailable,
)
from bidding_compliance.model_gateway.authorized_runtime import (
    FULL_CAPABILITY_AUTHORIZATION_ID,
    Dec005BudgetLedger,
    MetadataAuditSink,
)
from bidding_compliance.model_gateway.contracts import ModelRequest
from bidding_compliance.model_gateway.errors import ModelGatewayError
from bidding_compliance.services.llm_candidate_discovery import discovery_schema
from bidding_compliance.services.real_ai_runtime import (
    DISCOVERY_PROMPT_VERSION,
    create_dec005_gateway,
    real_ai_policy,
)
from bidding_compliance.services.real_embedding_runtime import (
    EMBEDDING_INPUT_PRICE_PER_MILLION,
    ScopedEmbeddingGuard,
    real_embedding_settings,
)

SCOPE = "a" * 64
LLM_CEILING = Decimal("0.25")
EMBEDDING_CEILING = Decimal("0.10")
ROUND_LLM_LIMIT = 4
ROUND_EMBEDDING_LIMIT = 322
ROUND_TOTAL_CNY = Decimal("2")
DOCUMENT = "a" * 64
# The recorded prebuild: 311 batches at 0.0003318 plus one at 0.0003172 == 0.1035070 CNY.
HISTORIC_BATCHES = 312
HISTORIC_SETTLED_CNY = Decimal("0.1035070")


def request_hash(number: int) -> str:
    """A distinct, well-formed 64-lowercase-hex request digest per attempt."""
    return hashlib.sha256(f"dec007-round-{number}".encode()).hexdigest()


def round_ledger(path: Path) -> Dec005BudgetLedger:
    """The ledger exactly as the controlled validation assembly constructs it."""
    return Dec005BudgetLedger(
        path,
        scope_sha256=SCOPE,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
        llm_limit=ROUND_LLM_LIMIT,
        embedding_limit=ROUND_EMBEDDING_LIMIT,
        total_cny=ROUND_TOTAL_CNY,
    )


def wide_ledger(path: Path) -> Dec005BudgetLedger:
    """The DEC-007 authorization ceilings (2000/2000/CNY 200) as the prebuild used them."""
    return Dec005BudgetLedger(
        path, scope_sha256=SCOPE, authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID
    )


def settle_embedding_batches(ledger: Dec005BudgetLedger, count: int, actual: Decimal) -> None:
    for number in range(count):
        reservation = ledger.reserve_external(
            kind="embedding", request_hash=request_hash(number), ceiling=EMBEDDING_CEILING
        )
        ledger.settle_external(reservation, actual)


def seed_prebuild(ledger: Dec005BudgetLedger) -> None:
    """The historical prebuild rows, settled so they total exactly 0.1035070 CNY."""
    per_batch = Decimal("0.0003318")
    settle_embedding_batches(ledger, HISTORIC_BATCHES - 1, per_batch)
    remainder = HISTORIC_SETTLED_CNY - per_batch * (HISTORIC_BATCHES - 1)
    reservation = ledger.reserve_external(
        kind="embedding",
        request_hash=request_hash(HISTORIC_BATCHES - 1),
        ceiling=EMBEDDING_CEILING,
    )
    ledger.settle_external(reservation, remainder)


def discovery_request(call_id: str) -> ModelRequest:
    return ModelRequest(
        call_id=call_id,
        tenant_id="tenant-a",
        review_task_id="review-task",
        node_run_id=f"{call_id}-node",
        prompt_version=DISCOVERY_PROMPT_VERSION,
        system_instruction="client-supplied instructions must be ignored",
        input_payload={
            "discovery_sections": [
                {
                    "section_key": "s000000c000",
                    "document_sha256": DOCUMENT,
                    "text": "合成条款疑点，仅用于本轮上限门禁测试。",
                }
            ]
        },
    )


def llm_transport() -> tuple[list[dict[str, object]], httpx.MockTransport]:
    """Synthetic supplier answering with a schema-valid, empty discovery result.

    ``MockTransport`` serves both the sync and the async client of the adapter, exactly as
    the repository's other gateway tests do.
    """
    calls: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"schema_version": "v1alpha1", "findings": []})
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )

    return calls, httpx.MockTransport(handle)


class EmbeddingTransport(httpx.BaseTransport):
    """Synthetic supplier for query/payload embeddings; records every request body."""

    def __init__(
        self,
        *,
        fail_on_call: int | None = None,
        omit_usage_on_call: int | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.fail_on_call = fail_on_call
        self.omit_usage_on_call = omit_usage_on_call

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        values = body["input"]
        self.calls.append(list(values))
        if self.fail_on_call == len(self.calls):
            raise httpx.ConnectError("synthetic transport failure")
        payload: dict[str, object] = {
            "id": "synthetic-request",
            "model": body["model"],
            "object": "list",
            "data": [
                {
                    "index": position,
                    "object": "embedding",
                    "embedding": [0.0] * body["dimensions"],
                }
                for position in range(len(values))
            ],
        }
        if self.omit_usage_on_call != len(self.calls):
            payload["usage"] = {"total_tokens": len(values), "prompt_tokens": len(values)}
        return httpx.Response(200, json=payload)


def round_gateway(tmp_path: Path, transport: httpx.BaseTransport):
    """The real gateway assembled with this round's tightened ceilings."""
    return create_dec005_gateway(
        api_key="example-synthetic-credential",
        workspace_id="synthetic-workspace",
        tenant_id="tenant-a",
        allowed_document_sha256=frozenset({DOCUMENT}),
        ledger_path=tmp_path / "dec007-budget.sqlite3",
        audit_path=tmp_path / "dec007-model-audit.jsonl",
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
        llm_limit=ROUND_LLM_LIMIT,
        embedding_limit=ROUND_EMBEDDING_LIMIT,
        total_cny=ROUND_TOTAL_CNY,
        transport=transport,
    )


def guarded_embedding_runtime(tmp_path: Path, ledger: Dec005BudgetLedger, transport):
    guard = ScopedEmbeddingGuard(ledger)
    provider = DashScopeEmbeddingProvider(
        real_embedding_settings(
            api_key="example-synthetic-credential", workspace_id="synthetic-workspace"
        ),
        client=httpx.Client(transport=transport, trust_env=False),
        guard=guard,
        audit_sink=MetadataAuditSink(tmp_path / "embedding-audit.jsonl"),
        input_price_per_million=EMBEDDING_INPUT_PRICE_PER_MILLION,
    )
    return guard, provider


def call_gateway(gateway, authorization, attempt: int):
    call_id = f"round-call-{attempt}"
    authorization.trusted_calls[call_id] = (
        "tenant-a",
        "review-task",
        f"{call_id}-node",
    )
    return asyncio.run(
        gateway.generate_structured(
            discovery_request(call_id), discovery_schema(), real_ai_policy()
        )
    )


# --------------------------------------------------------------------------- 1 and 6
def test_four_llm_requests_are_allowed_and_the_fifth_is_refused_before_any_transport(tmp_path):
    calls, transport = llm_transport()
    gateway, authorization, ledger = round_gateway(tmp_path, transport)
    # The assembly really carried the round ceilings into the ledger (not the authorization's).
    assert (ledger.llm_limit, ledger.embedding_limit, ledger.total_cny) == (
        ROUND_LLM_LIMIT,
        ROUND_EMBEDDING_LIMIT,
        ROUND_TOTAL_CNY,
    )
    for attempt in range(ROUND_LLM_LIMIT):
        assert call_gateway(gateway, authorization, attempt).provider == "bailian"
    assert len(calls) == 4
    assert ledger.summary()["llm_calls"] == 4

    with pytest.raises(ModelGatewayError, match="count exhausted"):
        call_gateway(gateway, authorization, ROUND_LLM_LIMIT)
    # The gate fires inside the reservation, so the fifth request never reached the supplier.
    assert len(calls) == 4
    assert ledger.summary()["llm_calls"] == 4


# --------------------------------------------------------------------------- 2 (and 6)
def test_eleventh_new_embedding_batch_is_refused_at_322_cumulative(tmp_path):
    path = tmp_path / "dec007-budget.sqlite3"
    seed_prebuild(wide_ledger(path))
    ledger = round_ledger(path)
    transport = EmbeddingTransport()
    guard, provider = guarded_embedding_runtime(tmp_path, ledger, transport)
    assert ledger.summary()["embedding_batches"] == HISTORIC_BATCHES

    for number in range(ROUND_EMBEDDING_LIMIT - HISTORIC_BATCHES):
        text = f"合成查询文本 {number}"
        guard.approve([text])
        assert len(provider.embed([text])) == 1
    assert len(transport.calls) == 10
    assert ledger.summary()["embedding_batches"] == ROUND_EMBEDDING_LIMIT

    text = "第 11 次新增查询文本"
    guard.approve([text])
    with pytest.raises(ModelGatewayError, match="count exhausted"):
        provider.embed([text])
    assert len(transport.calls) == 10  # refused before the transport, not after
    assert ledger.summary()["embedding_batches"] == ROUND_EMBEDDING_LIMIT


# --------------------------------------------------------------------------- 3
def test_cumulative_two_yuan_refuses_even_while_the_counts_still_have_headroom(tmp_path):
    path = tmp_path / "dec007-budget.sqlite3"
    # 300 already settled batches at 0.0065 each: 1.95 CNY of the 2 CNY cumulative ceiling.
    settle_embedding_batches(wide_ledger(path), 300, Decimal("0.0065"))
    ledger = round_ledger(path)
    summary = ledger.summary()
    assert summary["llm_calls"] == 0 and summary["embedding_batches"] == 300
    assert summary["limits"] == {"llm_calls": 4, "embedding_batches": 322, "total_cny": "2"}
    assert Decimal(summary["charged_or_reserved_cny"]) == Decimal("1.95")

    # Both kinds still have count headroom (0 < 4, 300 < 322) and both are refused on money.
    with pytest.raises(ModelGatewayError, match="budget exhausted"):
        ledger.reserve_external(kind="llm", request_hash=request_hash(900), ceiling=LLM_CEILING)
    with pytest.raises(ModelGatewayError, match="budget exhausted"):
        ledger.reserve_external(
            kind="embedding", request_hash=request_hash(901), ceiling=EMBEDDING_CEILING
        )
    assert Decimal(ledger.summary()["charged_or_reserved_cny"]) == Decimal("1.95")


def test_the_cumulative_ceiling_is_inclusive_and_binds_before_the_embedding_count(tmp_path):
    path = tmp_path / "dec007-budget.sqlite3"
    settle_embedding_batches(wide_ledger(path), 300, Decimal("0.006"))  # 1.80 CNY spent
    ledger = round_ledger(path)

    for number in range(2):  # 1.80 -> 1.90 -> 2.00, exactly the ceiling
        ledger.reserve_external(
            kind="embedding", request_hash=request_hash(number), ceiling=EMBEDDING_CEILING
        )
    assert Decimal(ledger.summary()["charged_or_reserved_cny"]) == ROUND_TOTAL_CNY
    assert ledger.summary()["embedding_batches"] == 302  # 20 batches of count headroom remain

    with pytest.raises(ModelGatewayError, match="budget exhausted"):
        ledger.reserve_external(
            kind="embedding", request_hash=request_hash(9), ceiling=EMBEDDING_CEILING
        )
    assert ledger.summary()["embedding_batches"] == 302


# --------------------------------------------------------------------------- 4
def test_failed_and_unknown_usage_reservations_consume_the_round_quota_without_a_resend(tmp_path):
    path = tmp_path / "dec007-budget.sqlite3"
    seed_prebuild(wide_ledger(path))
    ledger = round_ledger(path)
    # Attempt 1 fails on the wire, attempt 2 answers with no usage at all: both consume
    # quota and neither is resent automatically.
    transport = EmbeddingTransport(fail_on_call=1, omit_usage_on_call=2)
    guard, provider = guarded_embedding_runtime(tmp_path, ledger, transport)

    failing = "失败请求的合成查询文本"
    guard.approve([failing])
    with pytest.raises(EmbeddingProviderUnavailable):
        provider.embed([failing])
    assert len(transport.calls) == 1  # exactly one attempt: never an automatic resend

    unknown = "用量未知请求的合成查询文本"
    guard.approve([unknown])
    with pytest.raises(EmbeddingProtocolError):
        provider.embed([unknown])
    assert len(transport.calls) == 2

    summary = ledger.summary()
    # Both attempts keep their full ceiling, stay unsettled and stay counted against 322.
    assert summary["embedding_batches"] == HISTORIC_BATCHES + 2
    assert summary["unsettled_requests"] == 2
    assert Decimal(summary["charged_or_reserved_cny"]) == (
        HISTORIC_SETTLED_CNY + 2 * EMBEDDING_CEILING
    )
    # The two retained reservations are quota: only 8 of the 10 remaining batches fit.
    for number in range(8):
        text = f"补足配额的合成查询文本 {number}"
        guard.approve([text])
        provider.embed([text])
    assert ledger.summary()["embedding_batches"] == ROUND_EMBEDDING_LIMIT
    assert len(transport.calls) == 10

    guard.approve(["超出配额的合成查询文本"])
    with pytest.raises(ModelGatewayError, match="count exhausted"):
        provider.embed(["超出配额的合成查询文本"])
    assert len(transport.calls) == 10
    assert ledger.summary()["embedding_batches"] == ROUND_EMBEDDING_LIMIT


def test_counters_survive_new_instances_and_failures_in_one_shared_file(tmp_path):
    path = tmp_path / "dec007-budget.sqlite3"
    first = round_ledger(path)
    settled = first.reserve_external(kind="llm", request_hash=request_hash(1), ceiling=LLM_CEILING)
    first.settle_external(settled, Decimal("0.001"))
    retained = first.reserve_external(kind="llm", request_hash=request_hash(2), ceiling=LLM_CEILING)
    # A failed request with unknown usage keeps its full reservation (the ledger is never
    # refunded by itself and nothing is resent automatically).
    first.settle_external(retained, LLM_CEILING)

    second = round_ledger(path)  # a new instance: a restart of the validation assembly
    summary = second.summary()
    assert summary["llm_calls"] == 2 and summary["unsettled_requests"] == 0
    assert Decimal(summary["charged_or_reserved_cny"]) == Decimal("0.251")

    for number in (3, 4):
        second.reserve_external(kind="llm", request_hash=request_hash(number), ceiling=LLM_CEILING)
    with pytest.raises(ModelGatewayError, match="count exhausted"):
        second.reserve_external(kind="llm", request_hash=request_hash(5), ceiling=LLM_CEILING)

    third = round_ledger(path)  # reopening never resets the shared counters
    assert third.summary()["llm_calls"] == 4
    # 0.001 settled + 0.25 retained at its ceiling + two unsettled reservations at 0.25.
    assert Decimal(third.summary()["charged_or_reserved_cny"]) == Decimal("0.751")
    assert third.summary()["unsettled_requests"] == 2


def test_the_last_llm_slot_is_granted_to_exactly_one_of_two_instances(tmp_path):
    path = tmp_path / "dec007-budget.sqlite3"
    first = round_ledger(path)
    for number in range(3):
        first.reserve_external(kind="llm", request_hash=request_hash(number), ceiling=LLM_CEILING)
    second = round_ledger(path)  # two processes opening the same ledger file

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt(ledger: Dec005BudgetLedger, number: int) -> None:
        barrier.wait()
        try:
            ledger.reserve_external(
                kind="llm", request_hash=request_hash(100 + number), ceiling=LLM_CEILING
            )
        except ModelGatewayError as exc:
            outcomes.append(f"refused:{exc.code.value}")
        else:
            outcomes.append("granted")

    threads = [
        threading.Thread(target=attempt, args=(ledger, number))
        for number, ledger in enumerate((first, second))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["granted", "refused:budget_exceeded"]
    assert first.summary()["llm_calls"] == 4  # atomic: the ceiling is never exceeded


# --------------------------------------------------------------------------- 5
def test_option_a_boundary_wide_and_tight_instances_share_one_counter_file(tmp_path):
    """Recorded boundary of the agreed option A: the file counts, the instance limits.

    A process that opens the same ledger with the authorization ceilings is not stopped by
    the file itself -- only by the operator rule and by the serving assemblies of this round
    (see tests/test_task0027_validation_entry.py). The counters, however, are one shared,
    cumulative series, and the tightened ceilings are never written into the ledger.
    """
    path = tmp_path / "dec007-budget.sqlite3"
    tight = round_ledger(path)
    for number in range(ROUND_LLM_LIMIT):
        tight.reserve_external(kind="llm", request_hash=request_hash(number), ceiling=LLM_CEILING)
    with pytest.raises(ModelGatewayError, match="count exhausted"):
        tight.reserve_external(kind="llm", request_hash=request_hash(50), ceiling=LLM_CEILING)

    wide = wide_ledger(path)
    assert (wide.llm_limit, wide.embedding_limit, wide.total_cny) == (
        2000,
        2000,
        Decimal("200"),
    )
    assert wide.summary()["llm_calls"] == 4  # one shared series, never reset per instance
    wide.reserve_external(kind="llm", request_hash=request_hash(51), ceiling=LLM_CEILING)
    assert wide.summary()["llm_calls"] == 5

    # Nothing of the round is persisted: no ceiling row, no extra table, no rewritten file.
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert tables == {"authorization", "requests"}
    assert wide.summary()["limits"] == {
        "llm_calls": 2000,
        "embedding_batches": 2000,
        "total_cny": "200",
    }
