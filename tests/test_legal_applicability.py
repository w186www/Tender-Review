"""D04: complete trusted contexts and independent/overlapping legal frameworks."""

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session
from test_legal_retrieval import query, search, version
from test_legal_runs import principal, retrieve
from test_legal_runs import system as legal_system

from bidding_compliance.legal.contracts import LegalManifest, LegalVersion, RetrievalResult
from bidding_compliance.legal.corpus import ingest, resolve_evidence
from bidding_compliance.legal.retrieval import LegalRetriever
from bidding_compliance.persistence.models import Project
from bidding_compliance.services import legal

system = legal_system


def scope(**changes):
    return {
        "procurement_methods": ["tender", "non_tender"],
        "buyer_types": ["government_entity", "enterprise", "other"],
        "subject_types": ["works", "goods", "services", "works_related_goods"],
        "legal_frameworks": ["tendering", "government_procurement"],
        **changes,
    }


@pytest.mark.parametrize(
    "change,frameworks",
    [
        ({}, ("tendering", "government_procurement")),
        ({"procurement_method": "non_tender"}, ("government_procurement",)),
        ({"project_type": "goods"}, ("government_procurement",)),
        (
            {"project_type": "goods", "subject_type": "works_related_goods"},
            ("tendering", "government_procurement"),
        ),
        ({"procurement_type": "enterprise", "project_type": "goods"}, ("tendering",)),
    ],
)
def test_confirmed_context_framework_mapping(change, frameworks):
    assert query(**change).legal_frameworks == frameworks


@pytest.mark.parametrize(
    "changes",
    [
        {"procurement_method": "unknown"},
        {"buyer_type": "unknown"},
        {"subject_type": "unknown"},
        {"project_type": "goods", "subject_type": "works"},
        {"procurement_type": "government", "buyer_type": "enterprise"},
        {"procurement_method": "non_tender", "legal_frameworks": ["tendering"]},
        {"procurement_type": "enterprise", "procurement_method": "non_tender"},
        {"procurement_type": "other"},
        {"procurement_type": "other", "legal_frameworks": ["tendering", "tendering"]},
    ],
)
def test_unknown_or_conflicting_context_cannot_be_inferred(changes):
    with pytest.raises(ValidationError):
        query(**changes)


@pytest.mark.parametrize("field", ["procurement_method", "buyer_type", "subject_type"])
def test_legacy_project_requests_supplement_without_embedding(system, field):
    engine, retriever, adapter = system
    with Session(engine) as db:
        project = db.get(Project, ("a", "p"))
        context = dict(project.context)
        context.pop(field)
        project.context = context
        db.commit()
        result = retrieve(db, retriever)
        assert result.status == "context_incomplete" and not result.citable_evidence
        assert result.context_error == "CONTEXT_INVALID"
        assert adapter.calls == 0
        assert legal.read_run(db, principal(), result.run_snapshot.run_id) == result


def test_government_works_non_tender_does_not_use_tendering_evidence(tmp_path):
    metadata = version(tmp_path, applicability=scope(legal_frameworks=["tendering"]))
    assert search(tmp_path, metadata).citable_evidence
    result = search(tmp_path, metadata, query(procurement_method="non_tender"))
    assert not result.hits
    assert any("framework_mismatch" in x.reasons for x in result.excluded)


def test_cross_framework_results_remain_separate_and_reproducible(tmp_path):
    first_root, second_root = tmp_path / "tender", tmp_path / "policy"
    first_root.mkdir()
    second_root.mkdir()
    first = version(first_root, applicability=scope(legal_frameworks=["tendering"]))
    second = version(
        second_root,
        law_id="synthetic-policy",
        title="合成政策",
        authority="policy",
        applicability=scope(legal_frameworks=["government_procurement"]),
    )
    versions = []
    for name, metadata in (("tender", first), ("policy", second)):
        versions.append(
            LegalVersion.model_validate(
                {
                    **metadata.model_dump(),
                    "text_path": name + "/law.txt",
                    "source_snapshot_path": name + "/law.txt",
                }
            )
        )
    index = ingest(tmp_path, LegalManifest(versions=tuple(versions)))
    result = LegalRetriever(index).search(query())
    assert {h.law_id for h in result.hits} == {"synthetic", "synthetic-policy"}
    assert {h.applicable_frameworks for h in result.hits} == {
        ("tendering",),
        ("government_procurement",),
    }
    for hit in result.hits:
        assert resolve_evidence(tmp_path, index, hit, result.query) == hit.quote


def test_article_scope_intersects_parent_and_preserves_unrelated_articles(tmp_path):
    metadata = version(
        tmp_path,
        applicability=scope(),
        clause_scopes=[
            {
                "article": "第一条",
                "note": "synthetic non-tender Guangdong clause only",
                "scope": scope(procurement_methods=["non_tender"], jurisdictions=["CN/广东"]),
            }
        ],
    )
    result = search(tmp_path, metadata, query(text="合成"))
    assert {h.article for h in result.hits} == {"第二条"}
    assert any(x.article == "第一条" and "method_mismatch" in x.reasons for x in result.excluded)
    assert any(
        x.article == "第一条" and "jurisdiction_mismatch" in x.reasons for x in result.excluded
    )


def test_unknown_other_can_only_use_explicit_confirmed_framework(tmp_path):
    request = query(procurement_type="other", legal_frameworks=["tendering"])
    metadata = version(tmp_path, procurement_types=["other"], applicability=scope())
    assert search(tmp_path, metadata, request).hits


def test_missing_applicability_is_reference_not_confirmable(tmp_path):
    metadata = version(tmp_path, applicability=None)
    assert not search(tmp_path, metadata).hits
    reference = search(tmp_path, metadata, query(include_references=True))
    assert reference.hits and not reference.citable_evidence
    assert {h.reason for h in reference.hits} == {"applicability_unverified"}


@pytest.mark.parametrize("frameworks", [["government_procurement"], ["tendering", "tendering"]])
def test_result_cannot_claim_unrelated_or_duplicate_frameworks(tmp_path, frameworks):
    metadata = version(tmp_path, procurement_types=["enterprise"])
    result = search(tmp_path, metadata, query(procurement_type="enterprise"))
    payload = result.model_dump(mode="json")
    payload["hits"][0]["applicable_frameworks"] = frameworks
    with pytest.raises(ValidationError, match="framework/query"):
        RetrievalResult.model_validate(payload)
