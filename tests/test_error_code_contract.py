"""Runtime error codes and fallback cannot escape the versioned OpenAPI catalog."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from verify_contracts import ROOT, load_contracts, load_openapi, validator_for_contract

from bidding_compliance.api.errors import ERRORS, error_response
from bidding_compliance.api.schemas import ErrorCode, ErrorResponse


def test_error_code_catalog_matches_contract():
    api, errors = load_openapi(ROOT)
    assert not errors
    declared = set(api["components"]["schemas"]["ErrorCode"]["enum"])
    assert declared == {code.value for code in ErrorCode}
    assert declared == {entry[0].value for entry in ERRORS.values()} | {"HTTP_ERROR"}


@pytest.mark.parametrize("status", [*ERRORS, 499, 503])
def test_each_runtime_error_and_fallback_matches_contract(status):
    response = error_response(status)
    documents, registry, errors = load_contracts(ROOT)
    api, api_errors = load_openapi(ROOT)
    assert not errors + api_errors
    validator_for_contract(
        ROOT, "contracts/openapi.yaml#/components/schemas/Error", documents, registry, api
    ).validate(json.loads(response.body))


def test_unknown_error_code_is_rejected_by_response_model():
    with pytest.raises(ValidationError):
        ErrorResponse(code="UNDECLARED_CODE", message="test", request_id=str(uuid4()))
