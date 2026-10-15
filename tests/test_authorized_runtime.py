"""Authorization counters and money are durable and fail closed before networking."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest

from bidding_compliance.model_gateway.authorized_runtime import (
    Dec005BudgetLedger,
    MetadataAuditSink,
)
from bidding_compliance.model_gateway.errors import ModelGatewayError


def ledger(tmp_path: Path, **kwargs: object) -> Dec005BudgetLedger:
    return Dec005BudgetLedger(tmp_path / "budget.sqlite", scope_sha256="a" * 64, **kwargs)


def test_restart_never_resets_calls_or_pending_cost(tmp_path: Path) -> None:
    first = ledger(tmp_path, llm_limit=1)
    first.reserve("tenant", "task", Decimal("0.01"))
    second = ledger(tmp_path, llm_limit=1)
    assert second.summary()["llm_calls"] == 1
    assert second.summary()["charged_or_reserved_cny"] == "0.25"
    with pytest.raises(ModelGatewayError):
        second.reserve("tenant", "task", Decimal("0.01"))


def test_budget_spans_embedding_and_llm(tmp_path: Path) -> None:
    budget = ledger(tmp_path, total_cny=Decimal("0.30"))
    budget.reserve("tenant", "task", Decimal("0.01"))
    with pytest.raises(ModelGatewayError):
        budget.reserve_external(kind="embedding", request_hash="b" * 64, ceiling=Decimal("0.10"))
    assert budget.summary()["embedding_batches"] == 0


def test_embedding_counter_and_actual_charge(tmp_path: Path) -> None:
    budget = ledger(tmp_path, embedding_limit=1)
    item = budget.reserve_external(kind="embedding", request_hash="b" * 64, ceiling=Decimal("0.10"))
    budget.settle_external(item, Decimal("0.0005"))
    assert budget.summary()["charged_or_reserved_cny"] == "0.0005"
    with pytest.raises(ModelGatewayError):
        budget.reserve_external(kind="embedding", request_hash="b" * 64, ceiling=Decimal("0.10"))


def test_concurrent_reservation_is_atomic(tmp_path: Path) -> None:
    budget = ledger(tmp_path, llm_limit=3)

    def attempt(_: int) -> bool:
        try:
            budget.reserve("tenant", "task", Decimal("0.01"))
            return True
        except ModelGatewayError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(12))) == 3
    assert budget.summary()["llm_calls"] == 3


def test_scope_cannot_change_on_existing_ledger(tmp_path: Path) -> None:
    ledger(tmp_path)
    with pytest.raises(ValueError, match="different scope"):
        Dec005BudgetLedger(tmp_path / "budget.sqlite", scope_sha256="b" * 64)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"llm_limit": 31},
        {"embedding_limit": 201},
        {"total_cny": Decimal("20.01")},
    ],
)
def test_hard_limits_cannot_be_expanded(tmp_path: Path, kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ledger(tmp_path, **kwargs)


def test_unknown_or_failed_usage_consumes_full_ceiling(tmp_path: Path) -> None:
    budget = ledger(tmp_path)
    reservation = budget.reserve("tenant", "task", Decimal("0.01"))
    budget.consume_reservation(reservation)
    assert budget.summary()["charged_or_reserved_cny"] == "0.25"
    with pytest.raises(ModelGatewayError):
        budget.settle(reservation, Decimal(0))


def test_audit_rejects_document_and_credentials(tmp_path: Path) -> None:
    audit = MetadataAuditSink(tmp_path / "audit.jsonl")
    for event in ({"text": "private"}, {"api_key": "secret"}, {"response": {}}):
        with pytest.raises(ValueError):
            audit(event)
    assert (tmp_path / "audit.jsonl").read_bytes() == b""
    audit({"provider": "bailian", "model": "qwen3.8-flash", "input_tokens": 12})
    assert '"input_tokens": 12' in (tmp_path / "audit.jsonl").read_text()
