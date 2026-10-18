"""D01: known bounds, independent clause repeal and replacement are fail-closed."""

import pytest
from pydantic import ValidationError
from test_legal_retrieval import query, search, version

from bidding_compliance.legal.contracts import LegalManifest
from bidding_compliance.legal.corpus import ingest, resolve_evidence
from bidding_compliance.legal.retrieval import LegalRetriever


def effect(**changes):
    return dict(
        article="第一条", verification="verified", note="synthetic clause review", **changes,
    )


def test_unknown_end_is_not_an_open_verified_window(tmp_path):
    metadata = version(tmp_path, end_status="unknown")
    assert not search(tmp_path, metadata).hits
    reference = search(tmp_path, metadata, query(include_references=True))
    assert reference.hits and not reference.citable_evidence
    assert {h.reason for h in reference.hits} == {"unknown_end"}
    assert search(tmp_path, version(tmp_path, end_status="confirmed_open")).citable_evidence
    assert not search(tmp_path, version(tmp_path), query(review_date="2026-10-15")).hits


@pytest.mark.parametrize("changes", [
    {"end_status": "confirmed_end"},
    {"end_status": "unknown", "effective_to": "2026-10-14"},
    {"end_status": "confirmed_open", "effective_to": "2026-10-14"},
    {"clause_effects": [effect(end_status="confirmed_end")]},
    {"clause_effects": [effect(effective_to="2026-10-14")]},
    {"clause_effects": [effect(effective_from="2026-10-14", effective_to="2026-10-13",
                              end_status="confirmed_end")]},
    {"clause_effects": [effect(), effect()]},
])
def test_conflicting_window_metadata_is_rejected(tmp_path, changes):
    with pytest.raises(ValidationError):
        version(tmp_path, **changes)


@pytest.mark.parametrize("day,articles", [
    ("2019-12-31", set()), ("2020-01-01", {"第一条", "第二条"}),
    ("2026-10-13", {"第一条", "第二条"}),
    ("2026-10-14", {"第二条"}), ("2026-10-15", set()),
])
def test_partial_repeal_preserves_other_verified_articles(tmp_path, day, articles):
    metadata = version(tmp_path, clause_effects=[effect(
        effective_to="2026-10-14", end_status="confirmed_end",
    )])
    index = ingest(tmp_path, LegalManifest(versions=(metadata,)))
    request = query(text="合成", review_date=day)
    result = LegalRetriever(index).search(request)
    assert {hit.article for hit in result.hits} == articles
    for hit in result.hits:
        assert resolve_evidence(tmp_path, index, hit, request) == hit.quote
    if day == "2026-10-14":
        assert any(x.article == "第一条" and "expired" in x.reasons for x in result.excluded)
        reference = LegalRetriever(index).search(query(
            text="合成", review_date=day, include_references=True,
        ))
        assert "第一条" not in {h.article for h in reference.hits}


def test_unverified_clause_does_not_demote_other_verified_clauses(tmp_path):
    metadata = version(tmp_path, clause_effects=[dict(
        article="第一条", verification="unverified", end_status="unknown", note="pending review",
    )])
    result = search(tmp_path, metadata, query(text="合成"))
    assert {h.article for h in result.hits} == {"第二条"}
    reference = search(tmp_path, metadata, query(text="合成", include_references=True))
    assert len(reference.hits) == 2
    assert len(reference.citable_evidence) == 1


def test_effect_cannot_silently_refer_to_nonexistent_article(tmp_path):
    metadata = version(tmp_path, clause_effects=[dict(
        article="第三条", verification="verified", note="synthetic",
    )])
    with pytest.raises(ValueError, match="missing article"):
        ingest(tmp_path, LegalManifest(versions=(metadata,)))


def test_known_end_without_known_start_is_still_excluded_on_end_date(tmp_path):
    metadata = version(tmp_path, verification="unverified", verified_through=None,
                       effective_from=None, effective_to="2026-10-14")
    assert search(tmp_path, metadata, query(
        review_date="2026-10-13", include_references=True,
    )).hits
    assert not search(tmp_path, metadata, query(include_references=True)).hits


def test_version_replacement_has_no_double_citation_at_boundary(tmp_path):
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old = version(old_root, effective_to="2026-10-14").model_copy(update={
        "text_path": "old/law.txt", "source_snapshot_path": "old/law.txt",
    })
    new = version(new_root, version="2", effective_from="2026-10-14").model_copy(update={
        "text_path": "new/law.txt", "source_snapshot_path": "new/law.txt",
    })
    retriever = LegalRetriever(ingest(tmp_path, LegalManifest(versions=(old, new))))
    assert {h.version for h in retriever.search(query(review_date="2026-10-13")).hits} == {"1"}
    assert {h.version for h in retriever.search(query()).hits} == {"2"}
