"""Project legal-library adoption policy: identity, separation and citation annotation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from test_legal_retrieval import query, version

from bidding_compliance.legal.adoption import (
    AdoptionPolicy,
    binding_for,
    load_adoption_policy,
    load_rule_law_bindings,
)
from bidding_compliance.legal.contracts import LegalManifest
from bidding_compliance.legal.corpus import index_hash, ingest
from bidding_compliance.legal.retrieval import LegalRetriever

ROOT = Path(__file__).resolve().parents[1]


def test_repository_policy_freezes_the_manifest_and_never_claims_verification():
    policy = load_adoption_policy(ROOT)
    assert policy is not None
    assert policy.policy_id == "ADOPT-2026-10-18"
    assert policy.decision_ref == "DEC-009"
    assert policy.independent_legal_verification is False
    assert policy.version_count == 43
    assert policy.fragment_count == 3120
    assert policy.covers("a273f6b956365e42b7b72f9b", "2019年第三次修订")
    assert not policy.covers("not-a-law", "not-a-version")


def test_engineering_rule_law_bindings_are_source_checked_and_not_expert_claims():
    policy = load_adoption_policy(ROOT)
    assert policy is not None
    bindings = load_rule_law_bindings(ROOT, policy)
    assert len(bindings) == 11
    assert all(item.asserted_by == "engineering-config" for item in bindings)
    selected = binding_for(
        bindings,
        rule_ids={"TASK0007.QUAL.LOCAL-REGISTRATION"},
        law_id="a273f6b956365e42b7b72f9b",
        version="2019年第三次修订",
        article="第三十二条",
    )
    assert selected is not None
    assert selected.source_reviewed is True


def test_policy_fails_closed_when_the_manifest_bytes_change(tmp_path):
    config = tmp_path / "config/legal"
    config.mkdir(parents=True)
    shutil.copy(ROOT / "config/legal/adoption-policy.json", config)
    manifest = json.loads((ROOT / "config/legal/manifest.json").read_text(encoding="utf-8"))
    manifest["versions"][0]["title"] = "tampered"
    (config / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="manifest bytes"):
        load_adoption_policy(tmp_path)


def test_retriever_annotates_adopted_hits_without_reclassifying_citable_evidence(tmp_path):
    metadata = version(tmp_path)
    index = ingest(tmp_path, LegalManifest(versions=(metadata,)))
    policy = AdoptionPolicy(
        policy_id="ADOPT-TEST",
        decision_ref="DEC-TEST",
        adopted_on="2026-10-18",
        manifest_sha256="0" * 64,
        corpus_index_sha256=index_hash(index),
        version_count=1,
        fragment_count=2,
        independent_legal_verification=False,
        statement="test adoption",
        versions=frozenset({("synthetic", "1")}),
    )
    result = LegalRetriever(index, adoption_policy=policy).search(query())
    assert result.adoption_policy_id == "ADOPT-TEST"
    assert result.adopted_evidence == tuple(
        hit.evidence_id for hit in result.hits if hit.adoption_status == "project_adopted"
    )
    assert result.adopted_evidence
    assert all(
        hit.evidence.adoption_status == "project_adopted" for hit in result.hits
    )
    # The formal citable set remains exactly the verified/eligible hits.
    assert result.citable_evidence == tuple(
        hit.evidence_id for hit in result.hits if hit.eligible_for_confirmation
    )


def test_retriever_refuses_a_policy_for_a_different_snapshot(tmp_path):
    metadata = version(tmp_path)
    index = ingest(tmp_path, LegalManifest(versions=(metadata,)))
    policy = AdoptionPolicy(
        policy_id="ADOPT-TEST",
        decision_ref="DEC-TEST",
        adopted_on="2026-10-18",
        manifest_sha256="0" * 64,
        corpus_index_sha256="0" * 64,
        version_count=1,
        fragment_count=2,
        independent_legal_verification=False,
        statement="test adoption",
        versions=frozenset({("synthetic", "1")}),
    )
    with pytest.raises(ValueError, match="retrieval snapshot"):
        LegalRetriever(index, adoption_policy=policy)
