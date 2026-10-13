"""Model gateway boundary checks; these are not provider conformance acceptance."""

from dataclasses import asdict
from pathlib import Path

import pytest
from verify_contracts import load_contracts, validator_for_contract

from bidding_compliance.model_gateway import ModelPolicy, ModelResponse, ModelUsage

ROOT = Path(__file__).resolve().parents[1]


def response_data():
    return {
        "call_id": "call-1",
        "provider": "fixture",
        "model": "fixture-model",
        "profile": "review",
        "content": {},
        "usage": ModelUsage(10, 2),
        "latency_ms": 5,
        "response_hash": "a" * 64,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("call_id", ""),
        ("provider", ""),
        ("model", ""),
        ("profile", ""),
        ("response_hash", "z" * 64),
        ("latency_ms", -1),
        ("latency_ms", True),
    ],
)
def test_invalid_response_is_rejected(field, value):
    data = response_data()
    data[field] = value
    with pytest.raises(ValueError):
        ModelResponse(**data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_input_tokens", -1),
        ("max_output_tokens", 0),
        ("timeout_seconds", float("nan")),
        ("temperature", float("nan")),
    ],
)
def test_policy_rejects_invalid_budgets(field, value):
    data = {"profile": "review", "timeout_seconds": 30}
    data[field] = value
    with pytest.raises(ValueError):
        ModelPolicy(**data)


def test_valid_response_conforms_to_json_schema():
    response = ModelResponse(**response_data())
    docs, registry, errors = load_contracts(ROOT)
    assert not errors
    validator = validator_for_contract(
        ROOT, "contracts/schemas/model-response.schema.json", docs, registry, {}
    )
    validator.validate(asdict(response))
