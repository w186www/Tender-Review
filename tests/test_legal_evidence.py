"""D03/D07: formal references must identify reproducible, internally consistent artifacts."""

from copy import deepcopy

import pytest
from generate_legal_contracts import ROOT
from pydantic import ValidationError
from test_legal_retrieval import query, version
from verify_contracts import load_contracts, load_openapi, validator_for_contract

from bidding_compliance.legal.contracts import LegalManifest, RetrievalResult
from bidding_compliance.legal.corpus import ingest, resolve_evidence
from bidding_compliance.legal.retrieval import LegalRetriever


def schema_validator(name):
    docs, registry, errors = load_contracts(ROOT)
    api, api_errors = load_openapi(ROOT)
    assert not errors + api_errors
    return validator_for_contract(
        ROOT, f"contracts/schemas/{name}.schema.json", docs, registry, api,
    )


def result(root, **changes):
    index = ingest(root, LegalManifest(versions=(version(root, **changes),)))
    return index, LegalRetriever(index).search(query(include_references=True))


@pytest.mark.parametrize("authority,kind", [("law", "law"), ("policy", "policy")])
def test_formal_reference_resolves_same_hashed_artifact(tmp_path, authority, kind):
    index, retrieved = result(tmp_path, authority=authority)
    hit = retrieved.hits[0]
    evidence = hit.evidence
    schema_validator("evidence").validate(evidence.model_dump(mode="json"))
    schema_validator("legal-result").validate(retrieved.model_dump(mode="json"))
    assert evidence.kind == kind
    assert evidence.source_uri == "artifact://legal-text/" + hit.text_hash
    assert evidence.source_hash == index.manifest.versions[0].text_hash
    assert evidence.source_uri != hit.source_uri
    assert resolve_evidence(tmp_path, index, hit, retrieved.query) == hit.quote
    assert retrieved.citable_evidence == tuple(h.evidence_id for h in retrieved.hits)
    (tmp_path / "law.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        resolve_evidence(tmp_path, index, hit, retrieved.query)


@pytest.mark.parametrize("change", [
    {"reason": "unverified", "version_status": "unverified"},
    {"eligible_for_confirmation": False},
    {"version_status": "verified_historical"},
    {"effective_from": None},
    {"article": None},
    {"quote_hash": "0" * 64},
    {"locator": "law.txt#chars=0:1"},
])
def test_contradictory_hit_rejected_by_service(tmp_path, change):
    _, retrieved = result(tmp_path)
    payload = retrieved.model_dump(mode="json")
    payload["hits"][0].update(change)
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate(payload)


@pytest.mark.parametrize("change", [
    {"reason": "unverified", "version_status": "unverified"},
    {"eligible_for_confirmation": False},
    {"version_status": "verified_historical"},
    {"effective_from": None},
    {"article": None},
    {"evidence": {"arbitrary": "not an EvidenceRef"}},
])
def test_structural_contradictions_rejected_by_formal_schema(tmp_path, change):
    _, retrieved = result(tmp_path)
    payload = retrieved.model_dump(mode="json")
    payload["hits"][0].update(change)
    assert list(schema_validator("legal-result").iter_errors(payload))


@pytest.mark.parametrize("field,value", [
    ("source_uri", "https://example.gov.cn/law"),
    ("source_hash", "0" * 64), ("quote", "altered"), ("title", "other"),
    ("evidence_id", "missing"), ("locator", "chars=0:1"),
    ("jurisdiction", "CN/广东"), ("version_status", "unverified"),
    ("kind", "document"), ("page", 1),
])
def test_formal_reference_cannot_change_its_association(tmp_path, field, value):
    _, retrieved = result(tmp_path)
    payload = retrieved.model_dump(mode="json")
    payload["hits"][0]["evidence"][field] = value
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate(payload)


@pytest.mark.parametrize("change", ["missing", "dangling", "duplicate", "duplicate_hit"])
def test_citable_collection_has_exact_unique_eligible_identities(tmp_path, change):
    _, retrieved = result(tmp_path)
    payload = retrieved.model_dump(mode="json")
    if change == "missing":
        payload["citable_evidence"] = []
    elif change == "dangling":
        payload["citable_evidence"] = ["missing"]
    elif change == "duplicate":
        payload["citable_evidence"].append(payload["citable_evidence"][0])
    else:
        payload["hits"].append(deepcopy(payload["hits"][0]))
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate(payload)


def test_unverified_reference_never_enters_citable_collection(tmp_path):
    index, retrieved = result(tmp_path, verification="unverified", verified_through=None)
    assert retrieved.hits and not retrieved.citable_evidence
    for hit in retrieved.hits:
        assert hit.evidence.version_status == "unverified"
        assert resolve_evidence(tmp_path, index, hit, retrieved.query) == hit.quote
    payload = retrieved.model_dump(mode="json")
    payload["citable_evidence"] = [payload["hits"][0]["evidence_id"]]
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate(payload)


def test_reference_lookup_uses_frozen_index_not_caller_locator(tmp_path):
    index, retrieved = result(tmp_path)
    hit = retrieved.hits[0]
    tampered = hit.model_copy(update={"locator": "../outside.txt#" + hit.evidence.locator})
    with pytest.raises(ValueError, match="frozen legal index"):
        resolve_evidence(tmp_path, index, tampered, retrieved.query)


def test_confirmable_evidence_must_be_in_query_date_interval(tmp_path):
    _, retrieved = result(tmp_path)
    payload = retrieved.model_dump(mode="json")
    payload["query"]["review_date"] = "2019-12-31"
    with pytest.raises(ValidationError, match="review date interval"):
        RetrievalResult.model_validate(payload)


def test_old_result_is_explicitly_incompatible(tmp_path):
    _, retrieved = result(tmp_path)
    payload = retrieved.model_dump(mode="json")
    payload["schema_version"] = "v1alpha2"
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate(payload)
    assert list(schema_validator("legal-result").iter_errors(payload))


@pytest.mark.parametrize("scope", [
    {"review_date": "2026-10-15"}, {"region": "CN/广东"},
    {"procurement_type": "enterprise"}, {"project_type": "goods"},
])
def test_reference_resolution_rechecks_frozen_applicability(tmp_path, scope):
    index, retrieved = result(tmp_path)
    with pytest.raises(ValueError, match="frozen legal applicability"):
        resolve_evidence(tmp_path, index, retrieved.hits[0], query(**scope))


def test_old_unverified_evidence_cannot_be_promoted_by_editing_flags(tmp_path):
    index, retrieved = result(tmp_path, verification="unverified", verified_through=None)
    payload = retrieved.model_dump(mode="json")
    for hit in payload["hits"]:
        hit.update(
            reason="valid", version_status="verified_current", eligible_for_confirmation=True,
        )
        hit["evidence"]["version_status"] = "verified_current"
    payload["citable_evidence"] = [hit["evidence_id"] for hit in payload["hits"]]
    forged = RetrievalResult.model_validate(payload)
    with pytest.raises(ValueError, match="frozen legal applicability"):
        resolve_evidence(tmp_path, index, forged.hits[0], forged.query)


def test_real_official_html_and_cleaned_text_have_distinct_correct_artifacts():
    manifest = LegalManifest.model_validate_json((ROOT / "config/legal/manifest.json").read_bytes())
    index = ingest(ROOT, manifest)
    retrieved = LegalRetriever(index).search(query())
    assert retrieved.citable_evidence
    for hit in retrieved.hits:
        assert hit.evidence.source_hash == hit.text_hash
        assert hit.evidence.source_hash != hit.source_hash
        schema_validator("evidence").validate(hit.evidence.model_dump(mode="json"))
        assert resolve_evidence(ROOT, index, hit, retrieved.query) == hit.quote
