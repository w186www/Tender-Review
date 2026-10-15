"""TASK-0023 guard/coverage tests; synthetic transports never contact a provider."""

import json
import sqlite3
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_legal_runs import principal, system  # noqa: F401
from test_legal_vector_index import SyntheticProvider, make_index, make_query

from bidding_compliance.domain.runtime_provenance import ReviewRuntimeProvenance
from bidding_compliance.legal.contracts import RetrievalResult, RetrievalRuntimeSnapshot
from bidding_compliance.legal.dense_retrieval import DenseHybridRetriever
from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    DashScopeEmbeddingSettings,
    EmbeddingAuthorizationError,
    EmbeddingProtocolError,
    EmbeddingTimeout,
)
from bidding_compliance.legal.vector_index import SQLiteVectorIndex, VectorIndexManifest
from bidding_compliance.persistence.models import Project
from bidding_compliance.services.legal import retrieve_for_project


def settings(**overrides):
    credential = SecretStr("example-synthetic-credential")
    return DashScopeEmbeddingSettings(
        enabled=True,
        region="beijing",
        workspace_id="synthetic-workspace",
        model_id="text-embedding-v4",
        dimensions=1024,
        api_key=credential,
        **overrides,
    )


class Guard:
    def __init__(self, *, reject=False, allowed_hash=None):
        self.reject = reject
        self.allowed_hash = allowed_hash
        self.reservations = []
        self.settlements = []

    def reserve_external(self, *, kind, request_hash, ceiling):
        if self.reject or (self.allowed_hash is not None and request_hash != self.allowed_hash):
            raise PermissionError("authorization scope or budget denied")
        self.reservations.append((kind, request_hash, ceiling))
        return "synthetic-reservation"

    def settle_external(self, reservation, actual):
        self.settlements.append((reservation, actual))


class SyntheticTransport(httpx.BaseTransport):
    """Exercises the guarded non-Mock branch without using sockets."""

    def __init__(self, *, status=200, timeout=False, invalid=False):
        self.calls = []
        self.status = status
        self.timeout = timeout
        self.invalid = invalid

    def handle_request(self, request):
        self.calls.append(request)
        if self.timeout:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        body = json.loads(request.content)
        return httpx.Response(
            self.status,
            json={
                "id": "synthetic-request",
                "model": body["model"],
                "object": "list",
                "usage": {"total_tokens": 1},
                "data": [
                    {
                        "index": i,
                        "object": "embedding",
                        "embedding": [0.5] * (body["dimensions"] - int(self.invalid)),
                    }
                    for i in range(len(body["input"]))
                ],
            },
            headers={"location": "https://example.invalid"},
        )


def provider(client, guard, audit):
    return DashScopeEmbeddingProvider(
        settings(),
        client=client,
        guard=guard,
        audit_sink=audit.append,
        input_price_per_million=Decimal("1"),
    )


def test_guarded_embedding_returns_1024_dimensions_and_sanitized_usage_audit():
    transport, guard, audit = SyntheticTransport(), Guard(), []
    with httpx.Client(transport=transport, trust_env=False) as client:
        vectors = provider(client, guard, audit).embed(["合成授权文本"])
    assert len(vectors) == 1 and len(vectors[0]) == 1024
    assert len(transport.calls) == len(guard.reservations) == 1
    assert guard.reservations[0][0] == "embedding"
    assert guard.reservations[0][2] == Decimal("0.10")
    assert guard.settlements == [("synthetic-reservation", Decimal("0.000001"))]
    assert audit[-1]["total_tokens"] == 1
    assert audit[-1]["request_id"] == "synthetic-request"
    assert len(audit[-1]["response_hash"]) == 64
    serialized = json.dumps(audit, ensure_ascii=False)
    assert "合成授权文本" not in serialized and "synthetic-credential" not in serialized


def test_mock_contract_vectors_cannot_share_the_live_vector_identity():
    with httpx.Client(transport=httpx.MockTransport(lambda request: None)) as mock_client:
        mock_provider = DashScopeEmbeddingProvider(settings(), client=mock_client)
        with httpx.Client(transport=SyntheticTransport(), trust_env=False) as live_client:
            guarded_provider = provider(live_client, Guard(), [])
            assert mock_provider.execution_mode == "mock_contract"
            assert guarded_provider.execution_mode == "online"
            assert (
                mock_provider.identity.identity_sha256 != guarded_provider.identity.identity_sha256
            )


def test_embedding_missing_key_or_unapproved_request_never_reaches_transport():
    transport, audit = SyntheticTransport(), []
    with httpx.Client(transport=transport, trust_env=False) as client:
        no_key = settings().model_copy(update={"api_key": None})
        gateway = DashScopeEmbeddingProvider(
            no_key,
            client=client,
            guard=Guard(),
            audit_sink=audit.append,
            input_price_per_million=Decimal("1"),
        )
        with pytest.raises(EmbeddingAuthorizationError):
            gateway.embed(["合成授权文本"])
        with pytest.raises(PermissionError):
            provider(client, Guard(reject=True), audit).embed(["合成授权文本"])
        with pytest.raises(PermissionError):
            provider(client, Guard(allowed_hash="0" * 64), audit).embed(["未知范围文本"])
    assert not transport.calls and not audit


@pytest.mark.parametrize(
    "transport,exception",
    [
        (SyntheticTransport(timeout=True), EmbeddingTimeout),
        (SyntheticTransport(invalid=True), EmbeddingProtocolError),
        (SyntheticTransport(status=302), EmbeddingProtocolError),
    ],
)
def test_embedding_failure_keeps_full_reservation_and_never_retries(transport, exception):
    guard, audit = Guard(), []
    with httpx.Client(transport=transport, trust_env=False) as client:
        with pytest.raises(exception):
            provider(client, guard, audit).embed(["合成授权文本"])
    assert len(transport.calls) == len(guard.reservations) == 1
    assert not guard.settlements
    assert audit[-1]["event"] == "embedding.request_failed"
    assert audit[-1]["reserved_cost_cny"] == "0.10"


def test_embedding_utf8_ceiling_and_budget_quote_reject_before_reservation():
    guard, audit, transport = Guard(), [], SyntheticTransport()
    with httpx.Client(transport=transport, trust_env=False) as client:
        with pytest.raises(EmbeddingProtocolError):
            provider(client, guard, audit).embed(["合" * 3000])
        expensive = DashScopeEmbeddingProvider(
            settings(),
            client=client,
            guard=guard,
            audit_sink=audit.append,
            input_price_per_million=Decimal("1000000"),
        )
        with pytest.raises(RuntimeError, match="EMBEDDING_BUDGET_EXCEEDED"):
            expensive.embed(["合成"])
    assert not transport.calls and not guard.reservations


def test_live_embedding_cannot_run_without_audit_or_explicit_pricing():
    with httpx.Client(transport=SyntheticTransport(), trust_env=False) as client:
        with pytest.raises(ValueError, match="guard and audit"):
            DashScopeEmbeddingProvider(settings(), client=client, guard=Guard())
        with pytest.raises(ValueError, match="explicit positive pricing"):
            DashScopeEmbeddingProvider(
                settings(), client=client, guard=Guard(), audit_sink=lambda event: None
            )
    # A nominal mock primary transport cannot hide a real mounted route.
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected mock request")),
        mounts={"https://": SyntheticTransport()},
        trust_env=False,
    ) as client:
        with pytest.raises(ValueError, match="guard and audit"):
            DashScopeEmbeddingProvider(settings(), client=client)


def dense_runtime(tmp_path, *, subset=True):
    index = make_index(tmp_path)
    adapter = SyntheticProvider(dimensions=1024)
    store = SQLiteVectorIndex(tmp_path / "vectors.sqlite")
    selected = [index.clauses[0].clause_id] if subset else None
    manifest = store.build(
        index, adapter, publication_id="pub-a", revision_id="rev-a", clause_ids=selected
    )
    retriever = DenseHybridRetriever(
        index,
        provider=adapter,
        vector_index=store,
        build_id=manifest.build_id,
        publication_id="pub-a",
        revision_id="rev-a",
    )
    return retriever, store, adapter, manifest


def test_complete_subset_preserves_full_snapshot_and_declares_coverage(tmp_path):
    retriever, store, adapter, manifest = dense_runtime(tmp_path)
    assert manifest.item_count == 1 and manifest.source_item_count == 2
    assert manifest.legal_snapshot_sha256 == retriever.snapshot_hash
    assert len(store.indexed_clause_ids(manifest.build_id)) == 1
    other = store.build(
        retriever.index,
        adapter,
        publication_id="pub-a",
        revision_id="rev-a",
        clause_ids=[retriever.index.clauses[1].clause_id],
    )
    assert other.build_id != manifest.build_id
    with pytest.raises(ValueError, match="frozen source clause"):
        store.build(
            retriever.index,
            adapter,
            publication_id="pub-a",
            revision_id="rev-a",
            clause_ids=["f" * 64],
        )


def test_dense_ranking_is_traceable_and_query_cache_survives_reopen(tmp_path):
    retriever, store, adapter, manifest = dense_runtime(tmp_path)
    result = retriever.search(make_query())
    assert result.retrieval_version == "bm25-dense-cosine-rrf-1"
    assert len(adapter.calls) == 2  # one document batch and one query batch
    assert result.ranking_trace and result.citable_evidence
    assert any(item.vector_rank is not None for item in result.ranking_trace)
    assert all(
        trace.fused_score == hit.score
        for trace, hit in zip(result.ranking_trace, result.hits, strict=True)
    )
    assert retriever.search(make_query()) == result
    reopened = SQLiteVectorIndex(store.path)
    reopened.embed_query(adapter, make_query().text)
    assert len(adapter.calls) == 2
    runtime = retriever.runtime_snapshot(10)
    assert runtime.vector_index_item_count == 1 and runtime.vector_source_item_count == 2
    provenance = ReviewRuntimeProvenance(
        parser_documents=(),
        embedding_identity=adapter.identity,
        vector_index_build_id=manifest.build_id,
        retrieval=runtime,
        prompt_version="synthetic",
        prompt_sha256="a" * 64,
        model_profile="synthetic",
        model_config_revision_id="code-default",
        model_config_sha256="b" * 64,
    )
    assert ReviewRuntimeProvenance.model_validate_json(provenance.model_dump_json()) == provenance


@pytest.mark.parametrize(
    "changes",
    [
        {"region": "CN/广东"},
        {"review_date": "2026-10-15"},
    ],
)
def test_dense_filters_precede_query_embedding(tmp_path, changes):
    retriever, _store, adapter, _manifest = dense_runtime(tmp_path)
    before = len(adapter.calls)
    result = retriever.search(make_query(include_references=True, **changes))
    assert len(adapter.calls) == before
    assert not result.citable_evidence
    assert not any(trace.vector_rank is not None for trace in result.ranking_trace)


def test_query_cache_corruption_fails_closed_without_repaying(tmp_path):
    retriever, store, adapter, _manifest = dense_runtime(tmp_path)
    retriever.search(make_query())
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE vector_query_cache SET vector_sha256=?", ("f" * 64,))
    with pytest.raises(ValueError, match="query vector cache checksum"):
        retriever.search(make_query())
    assert len(adapter.calls) == 2


def test_full_manifest_remains_compatible_without_new_optional_coverage_fields(tmp_path):
    _retriever, _store, _adapter, manifest = dense_runtime(tmp_path, subset=False)
    old_payload = manifest.model_dump(mode="json", exclude={"source_item_count", "coverage_sha256"})
    assert VectorIndexManifest.model_validate(old_payload) == manifest


def test_incomplete_project_context_retains_dense_runtime_without_embedding(system):  # noqa: F811
    engine, baseline, _adapter = system
    identity = DashScopeEmbeddingSettings(
        region="beijing", workspace_id="synthetic", model_id="text-embedding-v4", dimensions=1024
    ).identity()
    runtime = RetrievalRuntimeSnapshot(
        algorithm="bm25-dense-cosine-rrf-1",
        top_k=10,
        embedding_identity=identity,
        vector_index_build_id="f" * 64,
        vector_index_item_count=1,
        vector_source_item_count=2,
    )
    baseline.runtime_snapshot = lambda top_k: runtime
    baseline.search = lambda query: pytest.fail("invalid context reached retrieval")
    with Session(engine) as db:
        db.execute(update(Project).where(Project.tenant_id == "a").values(context={}))
        db.commit()
        result = retrieve_for_project(
            db, principal(), "p", baseline, text="合成文本", review_date=make_query().review_date
        )
    assert result.status == "context_incomplete"
    assert result.retrieval_version == runtime.algorithm
    assert result.run_snapshot.runtime == runtime
    assert RetrievalResult.model_validate_json(result.model_dump_json()) == result


def test_dense_runtime_rejects_missing_or_mismatched_index_identity():
    identity = DashScopeEmbeddingSettings(
        region="beijing", workspace_id="synthetic", model_id="text-embedding-v4", dimensions=1024
    ).identity()
    with pytest.raises(ValidationError, match="bound vector identity"):
        RetrievalRuntimeSnapshot(
            algorithm="bm25-dense-cosine-rrf-1", top_k=10, embedding_identity=identity
        )
