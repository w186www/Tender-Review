"""Regression cases for the v1alpha2 boundary contracts (FR-009, FR-010)."""

from pathlib import Path

import pytest
from generate_state import check_state
from verify_contracts import load_contracts, load_openapi, load_yaml, validator_for_contract

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = load_yaml(ROOT / "contracts/examples/manifest.yaml")["fixtures"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=[case["id"] for case in FIXTURES])
def test_boundary_examples(fixture):
    documents, registry, errors = load_contracts(ROOT)
    api, api_errors = load_openapi(ROOT)
    assert not errors + api_errors
    validator = validator_for_contract(ROOT, fixture["schema"], documents, registry, api)
    assert validator.is_valid(fixture["data"]) == fixture["expected_valid"]


def test_generated_state_is_current():
    assert check_state(ROOT)


def test_original_project_composition_regression():
    """The previous closed request Schema made every normal response invalid."""
    documents, registry, _ = load_contracts(ROOT)
    api, errors = load_openapi(ROOT)
    assert not errors
    api["components"]["schemas"]["Project"]["allOf"][0]["$ref"] = (
        "#/components/schemas/ProjectCreate"
    )
    response = next(case["data"] for case in FIXTURES if case["id"] == "project-response-valid")
    validator = validator_for_contract(
        ROOT, "contracts/openapi.yaml#/components/schemas/Project", documents, registry, api
    )
    assert not validator.is_valid(response)


def test_human_acceptance_preserves_insufficient_evidence():
    data = next(case["data"] for case in FIXTURES if case["id"] == "risk-human-accept-insufficient")
    assert data["review_status"] == "accepted"
    assert data["evidence_status"] == "insufficient_evidence"
