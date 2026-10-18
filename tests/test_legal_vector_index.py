"""SQLite vector cache tests use deterministic synthetic vectors only."""

from pathlib import Path

import pytest

from bidding_compliance.legal.contracts import LegalManifest, LegalVersion, RetrievalQuery
from bidding_compliance.legal.corpus import digest, ingest
from bidding_compliance.legal.embedding_provider import DashScopeEmbeddingSettings
from bidding_compliance.legal.vector_index import SQLiteVectorIndex


class SyntheticProvider:
    def __init__(self, *, dimensions: int = 64, model_id: str = "text-embedding-v4") -> None:
        self.identity = DashScopeEmbeddingSettings(
            region="beijing",
            workspace_id="synthetic",
            model_id=model_id,
            dimensions=dimensions,
        ).identity()
        self.max_batch_items = 2
        self.calls: list[list[str]] = []
        self.fail_on_call: int | None = None

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("synthetic interruption")
        return [
            [1.0, float(index)] + [0.0] * (self.identity.dimensions - 2)
            for index, _text in enumerate(texts)
        ]


def make_index(root: Path, revision: str = "rev-1", extra_clause: bool = False):
    text = "合成法规\n第一条 合成采购保证金规则。\n第二条 合成采购期限规则。\n"
    if extra_clause:
        text += "第三条 合成采购范围规则。\n"
    source = root / "law.txt"
    source.write_text(text, encoding="utf-8", newline="\n")
    version = LegalVersion.model_validate(
        {
            "law_id": "synthetic-law",
            "title": "合成法规",
            "version": revision,
            "text_path": "law.txt",
            "text_hash": digest(source.read_bytes()),
            "source_uri": "https://example.gov.cn/synthetic",
            "source_snapshot_path": "law.txt",
            "source_hash": digest(source.read_bytes()),
            "captured_on": "2026-10-14",
            "verification": "verified",
            "verified_through": "2026-10-14",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "end_status": "confirmed_open",
            "jurisdictions": ["CN/福建"],
            "procurement_types": ["government"],
            "project_types": ["works"],
            "authority": "regulation",
            "verification_note": "仅用于工程测试的合成法规，不是真实法律依据。",
            "expected_articles": ["第一条", "第二条"] + (["第三条"] if extra_clause else []),
            "applicability": {
                "procurement_methods": ["tender", "non_tender"],
                "buyer_types": ["government_entity", "enterprise", "other"],
                "subject_types": ["works", "goods", "services"],
                "legal_frameworks": ["tendering", "government_procurement"],
            },
        }
    )
    return ingest(root, LegalManifest(versions=(version,)))


def make_query(**overrides):
    return RetrievalQuery.model_validate(
        {
            "text": "合成采购保证金",
            "review_date": "2026-10-14",
            "region": "CN/福建/福州",
            "procurement_type": "government",
            "project_type": "works",
            "procurement_method": "tender",
            "buyer_type": "government_entity",
            "subject_type": "works",
            **overrides,
        }
    )


def query_vector(dimensions: int = 64) -> list[float]:
    return [1.0] + [0.0] * (dimensions - 1)


def test_build_is_durable_idempotent_and_resumes(tmp_path):
    index = make_index(tmp_path)
    store = SQLiteVectorIndex(tmp_path / "vectors.sqlite")
    interrupted = SyntheticProvider()
    interrupted.max_batch_items = 1
    interrupted.fail_on_call = 2
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        store.build(index, interrupted, publication_id="pub-a", revision_id="rev-a")
    assert len(interrupted.calls) == 2

    resumed = SyntheticProvider()
    resumed.max_batch_items = 1
    manifest = store.build(index, resumed, publication_id="pub-a", revision_id="rev-a")
    assert manifest.item_count == len(index.clauses) == 2
    assert len(resumed.calls) == 1 and sum(map(len, resumed.calls)) == 1
    assert store.build(index, resumed, publication_id="pub-a", revision_id="rev-a") == manifest
    assert len(resumed.calls) == 1

    raw_database = (tmp_path / "vectors.sqlite").read_bytes()
    assert b"\xe5\x90\x88\xe6\x88\x90\xe6\xb3\x95\xe8\xa7\x84" not in raw_database


def test_vectors_are_revision_and_identity_bound_and_search_filters_first(tmp_path):
    index = make_index(tmp_path)
    store = SQLiteVectorIndex(tmp_path / "vectors.sqlite")
    provider = SyntheticProvider()
    manifest = store.build(index, provider, publication_id="pub-a", revision_id="rev-a")
    hit = store.search_candidates(
        manifest.build_id,
        query_vector(),
        query_identity=provider.identity,
        legal_index=index,
        query=make_query(),
        publication_id="pub-a",
        revision_id="rev-a",
    )
    assert hit and all(item.clause_id in {c.clause_id for c in index.clauses} for item in hit)
    assert (
        store.search_candidates(
            manifest.build_id,
            query_vector(),
            query_identity=provider.identity,
            legal_index=index,
            query=make_query(region="CN/广东"),
            publication_id="pub-a",
            revision_id="rev-a",
        )
        == ()
    )
    with pytest.raises(ValueError, match="different embedding identities"):
        other = SyntheticProvider(dimensions=256, model_id="qwen3.7-text-embedding")
        store.search_candidates(
            manifest.build_id,
            query_vector(),
            query_identity=other.identity,
            legal_index=index,
            query=make_query(),
            publication_id="pub-a",
            revision_id="rev-a",
        )
    with pytest.raises(ValueError, match="different legal publication"):
        store.search_candidates(
            manifest.build_id,
            query_vector(),
            query_identity=provider.identity,
            legal_index=index,
            query=make_query(),
            publication_id="pub-a",
            revision_id="rev-b",
        )


def test_changed_legal_revision_gets_a_distinct_vector_build(tmp_path):
    store = SQLiteVectorIndex(tmp_path / "vectors.sqlite")
    provider = SyntheticProvider()
    first = store.build(make_index(tmp_path), provider, publication_id="pub-a", revision_id="rev-a")
    second = store.build(
        make_index(tmp_path, revision="rev-2", extra_clause=True),
        provider,
        publication_id="pub-a",
        revision_id="rev-b",
    )
    assert second.build_id != first.build_id
    assert second.revision_id == "rev-b" and second.item_count == 3
    with pytest.raises(ValueError, match="different legal snapshot"):
        store.search_candidates(
            second.build_id,
            query_vector(),
            query_identity=provider.identity,
            legal_index=make_index(tmp_path),
            query=make_query(),
            publication_id="pub-a",
            revision_id="rev-b",
        )


def test_dimension_mismatch_and_manifest_tamper_fail_closed(tmp_path):
    index = make_index(tmp_path)
    store = SQLiteVectorIndex(tmp_path / "vectors.sqlite")
    provider = SyntheticProvider(dimensions=256)
    manifest = store.build(index, provider, publication_id="pub-a", revision_id="rev-a")
    with pytest.raises(ValueError, match="invalid dimensions"):
        store.search_candidates(
            manifest.build_id,
            query_vector(64),
            query_identity=provider.identity,
            legal_index=index,
            query=make_query(),
            publication_id="pub-a",
            revision_id="rev-a",
        )
    import sqlite3

    with sqlite3.connect(tmp_path / "vectors.sqlite") as db:
        db.execute(
            "UPDATE vector_build SET manifest_sha256=? WHERE build_id=?",
            ("0" * 64, manifest.build_id),
        )
    with pytest.raises(ValueError, match="integrity mismatch"):
        store.manifest(manifest.build_id)


@pytest.mark.parametrize("corruption", ["bytes", "missing"])
def test_completed_build_rejects_corrupt_or_missing_cache_rows(tmp_path, corruption):
    import sqlite3

    index = make_index(tmp_path)
    store = SQLiteVectorIndex(tmp_path / "vectors.sqlite")
    provider = SyntheticProvider()
    manifest = store.build(index, provider, publication_id="pub-a", revision_id="rev-a")
    with sqlite3.connect(tmp_path / "vectors.sqlite") as db:
        row = db.execute(
            "SELECT clause_id, vector_bytes FROM vector_cache LIMIT 1"
        ).fetchone()
        if row is None:
            raise AssertionError("test build did not create a vector cache row")
        if corruption == "bytes":
            raw = bytes(row[1])
            db.execute(
                "UPDATE vector_cache SET vector_bytes=? WHERE clause_id=?",
                (bytes([raw[0] ^ 1]) + raw[1:], row[0]),
            )
        else:
            db.execute("DELETE FROM vector_cache WHERE clause_id=?", (row[0],))

    with pytest.raises(ValueError, match="vector cache"):
        store.manifest(manifest.build_id)
    with pytest.raises(ValueError, match="vector cache"):
        store.build(index, provider, publication_id="pub-a", revision_id="rev-a")
    with pytest.raises(ValueError, match="vector cache"):
        store.search_candidates(
            manifest.build_id,
            query_vector(),
            query_identity=provider.identity,
            legal_index=index,
            query=make_query(),
            publication_id="pub-a",
            revision_id="rev-a",
        )


def test_resume_rejects_corrupted_checkpoint_cache(tmp_path):
    import sqlite3

    index = make_index(tmp_path)
    store = SQLiteVectorIndex(tmp_path / "vectors.sqlite")
    interrupted = SyntheticProvider()
    interrupted.max_batch_items = 1
    interrupted.fail_on_call = 2
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        store.build(index, interrupted, publication_id="pub-a", revision_id="rev-a")

    with sqlite3.connect(tmp_path / "vectors.sqlite") as db:
        row = db.execute(
            "SELECT clause_id, vector_bytes FROM vector_cache LIMIT 1"
        ).fetchone()
        if row is None:
            raise AssertionError("interrupted build did not persist its first checkpoint")
        raw = bytes(row[1])
        db.execute(
            "UPDATE vector_cache SET vector_bytes=? WHERE clause_id=?",
            (bytes([raw[0] ^ 1]) + raw[1:], row[0]),
        )

    resumed = SyntheticProvider()
    resumed.max_batch_items = 1
    with pytest.raises(ValueError, match="cached vector checksum mismatch"):
        store.build(index, resumed, publication_id="pub-a", revision_id="rev-a")
    assert resumed.calls == []


def test_manifest_has_checksums_and_never_contains_source_text(tmp_path):
    index = make_index(tmp_path)
    manifest = SQLiteVectorIndex(tmp_path / "vectors.sqlite").build(
        index, SyntheticProvider(), publication_id="pub-a", revision_id="rev-a"
    )
    assert len(manifest.items_sha256) == 64
    assert len(manifest.manifest_sha256) == 64
    assert "合成采购保证金规则" not in manifest.model_dump_json()
