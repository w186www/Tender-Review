"""TASK0009-001: independently recheck source and legal support before risk fusion."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_legal_retrieval import query, version

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.domain.rules.models import (
    CandidateFinding,
    CandidateSource,
    SourceExcerpt,
)
from bidding_compliance.ingestion.schemas import Fragment
from bidding_compliance.legal.contracts import LegalManifest, RetrievalResult, RunSnapshot
from bidding_compliance.legal.corpus import ingest
from bidding_compliance.legal.retrieval import LegalRetriever
from bidding_compliance.persistence.models import LegalRetrievalRun
from bidding_compliance.services import evidence_checker


def _source_candidate() -> tuple[CandidateFinding, SourceExcerpt, Fragment, str]:
    text = "投标人必须在本市注册。"
    document_sha = "a" * 64
    document_id = "synthetic-doc"
    section_id = "synthetic-section"
    document_ref = "doc-version:sha256:" + "b" * 64
    excerpt = SourceExcerpt(
        document_id=document_id,
        document_sha256=document_sha,
        section_id=section_id,
        section_revision=1,
        locator="paragraph:0",
        coordinate_system="ooxml",
        quote=text,
        quote_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    provenance = CandidateSource(
        skill_id="qualification_review",
        skill_version="1.0.0",
        rule_id="local_registration_restriction",
        rule_version="1.0.0",
        source_excerpts=(excerpt,),
        matched_reason="synthetic deterministic match",
    )
    deduplication_key = "c" * 64
    identity = {
        "deduplication_key": deduplication_key,
        "provenance": [
            ("qualification_review", "1.0.0", "local_registration_restriction", "1.0.0")
        ],
    }
    candidate_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    candidate = CandidateFinding(
        candidate_id=candidate_id,
        category="qualification",
        skill_id="qualification_review",
        skill_version="1.0.0",
        rule_id="local_registration_restriction",
        rule_version="1.0.0",
        document_version_ref=document_ref,
        problem_key="local_registration_restriction",
        deduplication_key=deduplication_key,
        source_excerpts=(excerpt,),
        matched_reason="synthetic deterministic match",
        provenance=(provenance,),
    )
    fragment = Fragment(
        locator=excerpt.locator,
        coordinate_system="ooxml",
        kind="paragraph",
        section="资格要求",
        text=text,
        text_sha256=excerpt.quote_sha256,
        source="native",
    )
    return candidate, excerpt, fragment, document_ref


def _principal() -> Principal:
    return Principal("tenant-a", "reviewer-a", "reviewer-a", Role.REVIEWER, "session-a")


def test_document_excerpt_is_rechecked_against_exact_version_and_locator(monkeypatch):
    candidate, excerpt, fragment, document_ref = _source_candidate()
    monkeypatch.setattr(
        evidence_checker.documents,
        "find_document",
        lambda *_: SimpleNamespace(status="ready", sha256=excerpt.document_sha256, parse_version=1),
    )
    monkeypatch.setattr(
        evidence_checker.documents,
        "sections",
        lambda *_: SimpleNamespace(
            parse_version=1,
            items=[
                SimpleNamespace(
                    section_id=excerpt.section_id,
                    revision=excerpt.section_revision,
                    source_hash=excerpt.document_sha256,
                    effective=fragment,
                )
            ],
        ),
    )

    result = evidence_checker.verify_document_excerpt(
        object(),
        _principal(),
        project_id="project-a",
        candidate=candidate,
        excerpt=excerpt,
        expected_document_refs={excerpt.document_id: document_ref},
    )

    assert result is not None
    assert result["kind"] == "document"
    assert result["quote"] == excerpt.quote
    assert result["source_hash"] == excerpt.document_sha256


@pytest.mark.parametrize(
    "failure",
    ["document_status", "document_hash", "section_revision", "locator", "quote", "snapshot_ref"],
)
def test_invalid_document_version_or_location_is_rejected(monkeypatch, failure):
    candidate, excerpt, fragment, document_ref = _source_candidate()
    document = SimpleNamespace(status="ready", sha256=excerpt.document_sha256, parse_version=1)
    section = SimpleNamespace(
        section_id=excerpt.section_id,
        revision=excerpt.section_revision,
        source_hash=excerpt.document_sha256,
        effective=fragment,
    )
    selected_excerpt = excerpt
    expected_refs = {excerpt.document_id: document_ref}
    if failure == "document_status":
        document.status = "failed"
    elif failure == "document_hash":
        document.sha256 = "d" * 64
    elif failure == "section_revision":
        section.revision += 1
    elif failure == "locator":
        section.effective = fragment.model_copy(update={"locator": "paragraph:1"})
    elif failure == "quote":
        selected_excerpt = excerpt.model_copy(update={"quote": "替换后的原文"})
    else:
        expected_refs = {excerpt.document_id: "doc-version:sha256:" + "e" * 64}
    monkeypatch.setattr(evidence_checker.documents, "find_document", lambda *_: document)
    monkeypatch.setattr(
        evidence_checker.documents,
        "sections",
        lambda *_: SimpleNamespace(parse_version=1, items=[section]),
    )

    assert (
        evidence_checker.verify_document_excerpt(
            object(),
            _principal(),
            project_id="project-a",
            candidate=candidate,
            excerpt=selected_excerpt,
            expected_document_refs=expected_refs,
        )
        is None
    )


def test_legal_hit_is_rechecked_against_saved_run_publication_and_source(
    tmp_path, monkeypatch
):
    index = ingest(tmp_path, LegalManifest(versions=(version(tmp_path),)))
    retrieved = LegalRetriever(index).search(query(include_references=True))
    hit = retrieved.hits[0]
    snapshot = RunSnapshot(
        run_id=str(uuid4()),
        tenant_id="tenant-a",
        project_id="project-a",
        actor_id="reviewer-a",
        context_version=1,
        context_hash="d" * 64,
        request_hash="e" * 64,
        review_date=retrieved.query.review_date,
        created_at=datetime.now(UTC),
    )
    frozen_result = RetrievalResult(**{**retrieved.model_dump(), "run_snapshot": snapshot})

    class SessionStub:
        def get(self, model, _key):
            assert model is LegalRetrievalRun
            return SimpleNamespace(
                request_snapshot={"publication_id": "publication-a", "revision_id": "revision-a"}
            )

    monkeypatch.setattr(evidence_checker, "read_run", lambda *_: frozen_result)
    monkeypatch.setattr(
        evidence_checker, "resolve_published_evidence", lambda *_: hit.quote
    )

    verified, quote = evidence_checker.verify_legal_hit(
        SessionStub(),
        _principal(),
        publication_id="publication-a",
        revision_id="revision-a",
        result_payload=frozen_result.model_dump(mode="json"),
        hit_payload=hit.model_dump(mode="json"),
    )

    assert verified == hit
    assert quote == hit.quote
    assert evidence_checker.has_confirmable_legal_support([verified])


def test_unverified_or_missing_law_cannot_be_confirmable(tmp_path):
    index = ingest(
        tmp_path,
        LegalManifest(
            versions=(version(tmp_path, verification="unverified", verified_through=None),)
        ),
    )
    retrieved = LegalRetriever(index).search(query(include_references=True))

    assert retrieved.hits
    assert all(hit.version_status == "unverified" for hit in retrieved.hits)
    assert not evidence_checker.has_confirmable_legal_support(retrieved.hits)
    assert not evidence_checker.has_confirmable_legal_support([])


@pytest.mark.parametrize(
    "document_valid,legal_valid,expected",
    [
        (False, False, "insufficient_evidence"),
        (False, True, "insufficient_evidence"),
        (True, False, "insufficient_evidence"),
        # A verified citation is not enough without an approved rule-to-law binding.
        (True, True, "suspected"),
    ],
)
def test_evidence_status_never_confirms_without_independent_binding(
    document_valid, legal_valid, expected
):
    assert (
        evidence_checker.evidence_status_for_support(
            document_valid=document_valid,
            legal_valid=legal_valid,
        )
        == expected
    )
