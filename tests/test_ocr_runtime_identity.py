import json

import pytest
from pydantic import ValidationError

from bidding_compliance.domain.runtime_provenance import FrozenParserIdentity
from bidding_compliance.ingestion.schemas import OCRRuntimeIdentity


def _identity() -> OCRRuntimeIdentity:
    return OCRRuntimeIdentity.create(
        engine_version="5.3.0",
        model_ids=("chi_sim", "eng"),
        model_sha256={"chi_sim": "c" * 64, "eng": "d" * 64},
        parameters={"language": "chi_sim+eng", "omp_thread_limit": 1},
        parser_image_sha256="e" * 64,
    )


def _json_payload(identity: OCRRuntimeIdentity) -> dict[str, object]:
    return json.loads(json.dumps(identity.model_dump(mode="json")))


def test_ocr_runtime_identity_json_array_round_trip_preserves_original_hash():
    identity = _identity()
    payload = _json_payload(identity)

    assert payload["model_ids"] == ["chi_sim", "eng"]
    restored = OCRRuntimeIdentity.model_validate(payload)

    assert restored == identity
    assert restored.model_ids == ("chi_sim", "eng")
    assert restored.identity_sha256 == identity.identity_sha256


def test_ocr_runtime_identity_keeps_strict_model_id_item_types():
    payload = _json_payload(_identity())
    payload["model_ids"] = ["chi_sim", 7]

    with pytest.raises(ValidationError) as exc_info:
        OCRRuntimeIdentity.model_validate(payload)

    assert any(error["type"] == "string_type" for error in exc_info.value.errors())


def test_ocr_runtime_identity_rejects_wrong_engine_identity():
    payload = _json_payload(_identity())
    payload["engine_id"] = "different-engine"

    with pytest.raises(ValidationError) as exc_info:
        OCRRuntimeIdentity.model_validate(payload)

    assert any(error["type"] == "literal_error" for error in exc_info.value.errors())


def test_ocr_runtime_identity_rejects_changed_content_with_original_hash():
    payload = _json_payload(_identity())
    payload["model_sha256"]["chi_sim"] = "f" * 64  # type: ignore[index]
    original_identity_hash = payload["identity_sha256"]

    with pytest.raises(ValidationError, match="OCR runtime identity hash mismatch"):
        OCRRuntimeIdentity.model_validate(payload)

    assert payload["identity_sha256"] == original_identity_hash


def test_ocr_runtime_identity_rejects_changed_identity_hash():
    payload = _json_payload(_identity())
    payload["identity_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="OCR runtime identity hash mismatch"):
        OCRRuntimeIdentity.model_validate(payload)


def test_frozen_parser_identity_rejects_provenance_hash_mismatch():
    identity = _identity()

    with pytest.raises(ValidationError, match="parser identity hash mismatch"):
        FrozenParserIdentity(
            document_id="synthetic-document",
            identity=identity,
            identity_sha256="f" * 64,
        )
