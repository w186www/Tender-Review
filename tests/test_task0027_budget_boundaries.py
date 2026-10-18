"""DEC-007 ceiling boundaries: batch count, cumulative budget and retained reservations.

Every provider interaction here uses an explicit synthetic transport; no test opens a
socket, reads a credential or reaches a paid supplier.
"""

import hashlib
import json
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
from bidding_compliance.model_gateway.errors import ModelGatewayError
from bidding_compliance.services.real_ai_runtime import verify_ledger_continuity
from bidding_compliance.services.real_embedding_runtime import (
    EMBEDDING_INPUT_PRICE_PER_MILLION,
    ScopedEmbeddingGuard,
    real_embedding_settings,
)

SCOPE = "c" * 64
EMBEDDING_CEILING = Decimal("0.10")
LLM_CEILING = Decimal("0.25")


def dec007_ledger(tmp_path: Path) -> Dec005BudgetLedger:
    return Dec005BudgetLedger(
        tmp_path / "dec007-budget.sqlite3",
        scope_sha256=SCOPE,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )


def request_hash(number: int) -> str:
    """A distinct, well-formed 64-lowercase-hex request digest per attempt."""
    return hashlib.sha256(f"dec007-attempt-{number}".encode()).hexdigest()


def test_two_thousand_embedding_batches_are_allowed_and_two_thousand_and_one_refused(
    tmp_path,
):
    ledger = dec007_ledger(tmp_path)
    for number in range(2000):
        reservation = ledger.reserve_external(
            kind="embedding", request_hash=request_hash(number), ceiling=EMBEDDING_CEILING
        )
        ledger.settle_external(reservation, Decimal("0.0002"))
    summary = ledger.summary()
    assert summary["embedding_batches"] == 2000
    assert summary["limits"]["embedding_batches"] == 2000
    assert summary["unsettled_requests"] == 0
    # 2000 settled batches cost a fraction of the ceiling: the count is the binding limit.
    assert Decimal(summary["charged_or_reserved_cny"]) < Decimal("1")

    with pytest.raises(ModelGatewayError, match="count exhausted"):
        ledger.reserve_external(
            kind="embedding", request_hash=request_hash(2000), ceiling=EMBEDDING_CEILING
        )
    assert ledger.summary()["embedding_batches"] == 2000


def test_two_thousand_llm_calls_are_allowed_and_two_thousand_and_one_refused(tmp_path):
    ledger = dec007_ledger(tmp_path)
    for number in range(2000):
        reservation = ledger.reserve_external(
            kind="llm", request_hash=request_hash(number), ceiling=LLM_CEILING
        )
        ledger.settle_external(reservation, Decimal("0.0005"))
    assert ledger.summary()["llm_calls"] == 2000
    with pytest.raises(ModelGatewayError, match="count exhausted"):
        ledger.reserve_external(
            kind="llm", request_hash=request_hash(2000), ceiling=LLM_CEILING
        )


def test_spent_two_hundred_yuan_refuses_new_requests_despite_remaining_batch_headroom(
    tmp_path,
):
    ledger = dec007_ledger(tmp_path)
    for number in range(800):  # 800 x ¥0.25 = the full ¥200 ceiling
        reservation = ledger.reserve_external(
            kind="llm", request_hash=request_hash(number), ceiling=LLM_CEILING
        )
        ledger.settle_external(reservation, LLM_CEILING)
    summary = ledger.summary()
    assert summary["llm_calls"] == 800 and summary["limits"]["llm_calls"] == 2000
    assert summary["embedding_batches"] == 0
    assert summary["limits"]["embedding_batches"] == 2000
    assert Decimal(summary["charged_or_reserved_cny"]) == Decimal("200")

    with pytest.raises(ModelGatewayError, match="budget exhausted"):
        ledger.reserve_external(
            kind="embedding", request_hash=request_hash(500), ceiling=EMBEDDING_CEILING
        )
    with pytest.raises(ModelGatewayError, match="budget exhausted"):
        ledger.reserve_external(kind="llm", request_hash=request_hash(501), ceiling=LLM_CEILING)
    assert Decimal(ledger.summary()["charged_or_reserved_cny"]) == Decimal("200")


class FailingTransport(httpx.BaseTransport):
    """First attempt: transport failure. Second: a response with unknown usage."""

    def __init__(self, dimensions: int = 1024) -> None:
        self.calls: list[list[str]] = []
        self.dimensions = dimensions

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(list(body["input"]))
        if len(self.calls) == 1:
            raise httpx.ConnectError("synthetic transport failure")
        # A well-formed response that reports no usage at all: the provider must treat the
        # consumed tokens as unknown and fail closed instead of settling a guess.
        return httpx.Response(
            200,
            json={
                "id": "synthetic-request",
                "model": body["model"],
                "object": "list",
                "data": [
                    {"index": position, "object": "embedding", "embedding": [0.0] * self.dimensions}
                    for position in range(len(body["input"]))
                ],
            },
        )


def test_failed_and_unknown_usage_keep_their_reservation_and_are_never_resent(tmp_path):
    ledger = dec007_ledger(tmp_path)
    guard = ScopedEmbeddingGuard(ledger)
    transport = FailingTransport()
    provider = DashScopeEmbeddingProvider(
        real_embedding_settings(api_key="example-synthetic-credential", workspace_id="synthetic"),
        client=httpx.Client(transport=transport, trust_env=False),
        guard=guard,
        audit_sink=MetadataAuditSink(tmp_path / "embedding-audit.jsonl"),
        input_price_per_million=EMBEDDING_INPUT_PRICE_PER_MILLION,
    )
    text = "合成法规条款文本，仅用于预留在途测试。"
    guard.approve([text])

    with pytest.raises(EmbeddingProviderUnavailable):
        provider.embed([text])
    assert len(transport.calls) == 1  # exactly one attempt: never an automatic resend
    with pytest.raises(EmbeddingProtocolError):
        provider.embed([text])
    assert len(transport.calls) == 2

    summary = ledger.summary()
    assert summary["embedding_batches"] == 2
    assert summary["unsettled_requests"] == 2
    # Both attempts keep their full ceiling reserved instead of being refunded.
    assert Decimal(summary["charged_or_reserved_cny"]) == Decimal("0.20")

    # A reservation that was never issued cannot be settled into the ledger either.
    with pytest.raises(ModelGatewayError, match="already settled"):
        ledger.settle_external("0" * 32, Decimal("0.0001"))


def test_a_missing_ledger_next_to_a_non_empty_audit_trail_is_refused(tmp_path):
    ledger = dec007_ledger(tmp_path)
    ledger.reserve_external(
        kind="embedding", request_hash=request_hash(1), ceiling=EMBEDDING_CEILING
    )
    audit = tmp_path / "embedding-audit.jsonl"
    MetadataAuditSink(audit)(
        {
            "event": "embedding.request_reserved",
            "request_hash": request_hash(1),
            "reservation_id": "f" * 32,
        }
    )
    # The ledger file is gone (deleted or replaced) while the audit trail proves earlier
    # usage: a "first initialization" would silently restore the whole DEC-007 quota.
    deleted = tmp_path / "elsewhere" / "dec007-budget.sqlite3"
    with pytest.raises(RuntimeError, match="refusing to restore supplier quota"):
        verify_ledger_continuity(deleted, audit)
