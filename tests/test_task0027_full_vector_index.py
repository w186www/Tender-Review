"""DEC-007 full-corpus vector index: batch-bound authorization, resume, reuse.

Every supplier interaction here uses an explicit synthetic transport or a counting
synthetic provider; no test opens a socket or reads a real credential.
"""

import hashlib
import json
import logging
import sqlite3
import struct
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from bidding_compliance.legal.contracts import LegalClause, LegalManifest, LegalVersion
from bidding_compliance.legal.corpus import digest, ingest
from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    DashScopeEmbeddingSettings,
    EmbeddingProtocolError,
    EmbeddingProviderUnavailable,
)
from bidding_compliance.legal.vector_index import (
    MAX_BATCH_UTF8_BYTES,
    MAX_ITEM_UTF8_BYTES,
    SQLiteVectorIndex,
    plan_batches,
)
from bidding_compliance.model_gateway.authorized_runtime import (
    FULL_CAPABILITY_AUTHORIZATION_ID,
    Dec005BudgetLedger,
    MetadataAuditSink,
)
from bidding_compliance.services.llm_candidate_discovery import redact_discovery_text
from bidding_compliance.services.real_embedding_runtime import (
    EMBEDDING_INPUT_PRICE_PER_MILLION,
    ScopedEmbeddingGuard,
    approve_plan_batches,
    authorized_vector_plan,
    build_authorized_vector_index,
    clause_order,
    create_real_retriever_factory,
    real_embedding_settings,
)

ARTICLES = (
    "第一条",
    "第二条",
    "第三条",
    "第四条",
    "第五条",
    "第六条",
    "第七条",
    "第八条",
    "第九条",
    "第十条",
    "第十一条",
    "第十二条",
    "第十三条",
)


def make_snapshot(root: Path, count: int, *, overlong_chars: int = 0):
    """Synthetic snapshot with ``count`` short articles and one optional over-long one."""
    articles = list(ARTICLES[:count])
    text = "合成法规\n" + "".join(
        f"{article} 合成采购规则第{number}项，仅用于离线测试。\n"
        for number, article in enumerate(articles, start=1)
    )
    if overlong_chars:
        articles.append("第十三条")
        text += "第十三条 " + "合" * overlong_chars + "\n"
    source = root / f"synthetic-{count}-{overlong_chars}.txt"
    source.write_text(text, encoding="utf-8", newline="\n")
    version = LegalVersion.model_validate(
        {
            "law_id": "synthetic-law",
            "title": "合成法规",
            "version": "rev-1",
            "text_path": source.name,
            "text_hash": digest(source.read_bytes()),
            "source_uri": "https://example.gov.cn/synthetic",
            "source_snapshot_path": source.name,
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
            "expected_articles": articles,
            "applicability": {
                "procurement_methods": ["tender", "non_tender"],
                "buyer_types": ["government_entity", "enterprise", "other"],
                "subject_types": ["works", "goods", "services"],
                "legal_frameworks": ["tendering", "government_procurement"],
            },
        }
    )
    return ingest(root, LegalManifest(versions=(version,)))


def ordered_clauses(index) -> list[LegalClause]:
    return sorted(index.clauses, key=clause_order)


def standalone_clause(name: str, quote: str) -> LegalClause:
    return LegalClause(
        clause_id=hashlib.sha256(name.encode()).hexdigest(),
        law_id="synthetic-law",
        version="rev-1",
        article=None,
        start=0,
        end=len(quote),
        quote=quote,
        quote_hash=hashlib.sha256(quote.encode()).hexdigest(),
    )


class CountingTransport(httpx.BaseTransport):
    """Synthetic supplier: records every request body and can fail one attempt."""

    def __init__(self, *, tag: float = 1.0, fail_on_call: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.tag = tag
        self.fail_on_call = fail_on_call

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        values = body["input"]
        self.calls.append(list(values))
        if self.fail_on_call == len(self.calls):
            return httpx.Response(503, json={"error": "synthetic supplier failure"})
        tokens = len(values)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-request",
                "model": body["model"],
                "object": "list",
                "usage": {"total_tokens": tokens, "prompt_tokens": tokens},
                "data": [
                    {
                        "index": position,
                        "object": "embedding",
                        "embedding": [self.tag, float(position)]
                        + [0.0] * (body["dimensions"] - 2),
                    }
                    for position in range(len(values))
                ],
            },
        )


class PositionalProvider:
    """Deterministic dense provider whose vectors name the producer and the batch slot."""

    def __init__(self, *, tag: float = 1.0, max_batch_items: int = 2) -> None:
        self.identity = DashScopeEmbeddingSettings(
            region="beijing",
            workspace_id="synthetic",
            model_id="text-embedding-v4",
            dimensions=64,
        ).identity()
        self.max_batch_items = max_batch_items
        self.tag = tag
        self.calls: list[list[str]] = []
        self.fail_on_call: int | None = None

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("synthetic interruption")
        return [[self.tag, float(position)] + [0.0] * 62 for position, _ in enumerate(texts)]


def guarded_runtime(tmp_path: Path, *, fail_on_call: int | None = None):
    ledger = Dec005BudgetLedger(
        tmp_path / "budget.sqlite3",
        scope_sha256="a" * 64,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    guard = ScopedEmbeddingGuard(ledger)
    transport = CountingTransport(fail_on_call=fail_on_call)
    provider = DashScopeEmbeddingProvider(
        real_embedding_settings(api_key="example-synthetic-credential", workspace_id="synthetic"),
        client=httpx.Client(transport=transport, trust_env=False),
        guard=guard,
        audit_sink=MetadataAuditSink(tmp_path / "embedding-audit.jsonl"),
        input_price_per_million=EMBEDDING_INPUT_PRICE_PER_MILLION,
    )
    return ledger, guard, transport, provider


def cached_vectors(path: Path) -> dict[str, tuple[float, float]]:
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT clause_id, vector_bytes FROM vector_cache").fetchall()
    return {clause_id: struct.unpack("<2f", bytes(raw)[:8]) for clause_id, raw in rows}


def guard_digest(texts: list[str]) -> str:
    payload = {
        "model": "text-embedding-v4",
        "input": list(texts),
        "dimensions": 1024,
        "encoding_format": "float",
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_unapproved_batch_hash_is_refused_before_transport(tmp_path):
    ledger, guard, transport, provider = guarded_runtime(tmp_path)
    with pytest.raises(PermissionError, match="approved corpus/query scope"):
        provider.embed(["未获批准的语料文本"])
    with pytest.raises(PermissionError):
        guard.reserve_external(kind="embedding", request_hash="0" * 64, ceiling=Decimal("0.10"))
    assert not transport.calls and not guard.allowed_hashes
    assert ledger.summary()["embedding_batches"] == 0


def test_changed_text_or_order_in_an_approved_batch_is_refused(tmp_path):
    index = make_snapshot(tmp_path, 4)
    _ledger, guard, transport, provider = guarded_runtime(tmp_path)
    plan = authorized_vector_plan(
        index,
        max_items=2,
        max_item_bytes=MAX_ITEM_UTF8_BYTES,
        max_batch_bytes=MAX_BATCH_UTF8_BYTES,
    )
    assert approve_plan_batches(guard, plan) == 2
    approved = [clause.quote for clause in plan.batches[0]]

    with pytest.raises(PermissionError):
        provider.embed([approved[0] + "（改动）", approved[1]])
    with pytest.raises(PermissionError):
        provider.embed(list(reversed(approved)))
    assert not transport.calls

    vectors = provider.embed(approved)
    assert len(vectors) == 2 and len(transport.calls) == 1
    assert transport.calls[0] == approved


def test_plan_batches_excludes_overlong_items_and_respects_both_ceilings():
    clauses = [standalone_clause(f"clause-{index}", "a" * 10) for index in range(5)]
    oversized = standalone_clause("clause-oversized", "合" * 10)  # 30 UTF-8 bytes
    huge = standalone_clause("clause-huge", "合" * 3000)  # 9000 UTF-8 bytes

    plan = plan_batches(
        [*clauses, oversized], max_items=3, max_item_bytes=15, max_batch_bytes=25
    )
    assert [[clause.clause_id for clause in batch] for batch in plan.batches] == [
        [clauses[0].clause_id, clauses[1].clause_id],
        [clauses[2].clause_id, clauses[3].clause_id],
        [clauses[4].clause_id],
    ]
    assert [clause.clause_id for clause in plan.excluded] == [oversized.clause_id]
    assert plan.item_count == 5 and len(plan.clause_ids) == 5
    assert all(sum(len(item.quote.encode()) for item in batch) <= 25 for batch in plan.batches)
    assert plan == plan_batches(
        [*clauses, oversized], max_items=3, max_item_bytes=15, max_batch_bytes=25
    )

    counted = plan_batches(
        clauses,
        max_items=2,
        max_item_bytes=MAX_ITEM_UTF8_BYTES,
        max_batch_bytes=MAX_BATCH_UTF8_BYTES,
    )
    assert [len(batch) for batch in counted.batches] == [2, 2, 1]
    provider_plan = plan_batches(
        [*clauses, huge],
        max_items=10,
        max_item_bytes=MAX_ITEM_UTF8_BYTES,
        max_batch_bytes=MAX_BATCH_UTF8_BYTES,
    )
    assert [clause.clause_id for clause in provider_plan.excluded] == [huge.clause_id]
    assert provider_plan.item_count == 5 and len(provider_plan.batches) == 1

    for bounds in (
        {"max_items": 0, "max_item_bytes": 8192, "max_batch_bytes": 32768},
        {"max_items": 10, "max_item_bytes": 0, "max_batch_bytes": 32768},
        {"max_items": 10, "max_item_bytes": 8192, "max_batch_bytes": 0},
        {"max_items": 10, "max_item_bytes": 8192, "max_batch_bytes": 4096},
    ):
        with pytest.raises(ValueError):
            plan_batches(clauses, **bounds)


def test_oversize_item_and_oversize_batch_are_refused_without_a_request(tmp_path):
    ledger, guard, transport, provider = guarded_runtime(tmp_path)
    with pytest.raises(EmbeddingProtocolError):
        provider.embed(["合" * 3000])  # 9000 bytes for one clause
    with pytest.raises(EmbeddingProtocolError):
        provider.embed(["合" * 2600] * 5)  # 39000 bytes in one request
    with pytest.raises(PermissionError):
        guard.reserve_external(
            kind="embedding",
            request_hash=guard_digest(["合" * 2600] * 5),
            ceiling=Decimal("0.10"),
        )
    assert not transport.calls and not guard.allowed_hashes
    assert ledger.summary()["embedding_batches"] == 0


def test_partial_cache_resume_binds_every_vector_to_its_own_clause(tmp_path):
    index = make_snapshot(tmp_path, 6)
    store = SQLiteVectorIndex(tmp_path / "legal-vectors.sqlite3")
    first = PositionalProvider(tag=1.0, max_batch_items=2)
    first.fail_on_call = 2
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        store.build(
            index, first, publication_id="pub-a", revision_id="rev-a", send_full_batches=True
        )
    assert [len(call) for call in first.calls] == [2, 2]

    resumed = PositionalProvider(tag=9.0, max_batch_items=2)
    manifest = store.build(
        index, resumed, publication_id="pub-a", revision_id="rev-a", send_full_batches=True
    )
    assert [len(call) for call in resumed.calls] == [2, 2]
    assert manifest.item_count == 6

    plan = plan_batches(
        ordered_clauses(index),
        max_items=2,
        max_item_bytes=MAX_ITEM_UTF8_BYTES,
        max_batch_bytes=MAX_BATCH_UTF8_BYTES,
    )
    expected = {
        clause.clause_id: (1.0 if batch_index == 0 else 9.0, float(position))
        for batch_index, batch in enumerate(plan.batches)
        for position, clause in enumerate(batch)
    }
    assert len(expected) == 6
    assert cached_vectors(store.path) == expected
    assert store.indexed_clause_ids(manifest.build_id) == frozenset(expected)


def test_full_cache_hit_reuses_the_plan_without_any_provider_call(tmp_path):
    index = make_snapshot(tmp_path, 3)
    store = SQLiteVectorIndex(tmp_path / "legal-vectors.sqlite3")
    built = PositionalProvider(tag=1.0, max_batch_items=2)
    manifest = store.build(
        index, built, publication_id="pub-a", revision_id="rev-a", send_full_batches=True
    )
    assert [len(call) for call in built.calls] == [2, 1]
    before = cached_vectors(store.path)

    reused = PositionalProvider(tag=9.0, max_batch_items=2)
    same = store.build(
        index, reused, publication_id="pub-a", revision_id="rev-a", send_full_batches=True
    )
    assert same == manifest and reused.calls == []

    other = store.build(
        index, reused, publication_id="pub-b", revision_id="rev-b", send_full_batches=True
    )
    assert other.build_id != manifest.build_id and other.item_count == 3
    assert reused.calls == []
    assert cached_vectors(store.path) == before


def test_interrupted_build_resumes_to_a_valid_manifest_and_charges_attempts_only(tmp_path):
    index = make_snapshot(tmp_path, 12)
    store = SQLiteVectorIndex(tmp_path / "legal-vectors.sqlite3")
    ledger, guard, transport, provider = guarded_runtime(tmp_path, fail_on_call=2)
    clause_ids = [clause.clause_id for clause in ordered_clauses(index)]
    build_id = store.planned_build_id(
        index, provider, publication_id="pub-a", revision_id="rev-a", clause_ids=clause_ids
    )

    with pytest.raises(EmbeddingProviderUnavailable):
        build_authorized_vector_index(
            index=index,
            provider=provider,
            guard=guard,
            store=store,
            publication_id="pub-a",
            revision_id="rev-a",
        )
    failed = ledger.summary()
    assert failed["embedding_batches"] == 2 and failed["unsettled_requests"] == 1
    assert failed["charged_or_reserved_cny"] == str(
        Decimal("0.10") + Decimal(10) * Decimal("0.5") / Decimal(1_000_000)
    )
    with pytest.raises(LookupError):
        store.manifest(build_id)

    transport.fail_on_call = None
    manifest, plan = build_authorized_vector_index(
        index=index,
        provider=provider,
        guard=guard,
        store=store,
        publication_id="pub-a",
        revision_id="rev-a",
    )
    assert manifest.build_id == build_id and manifest.item_count == 12
    assert len(plan.batches) == 2
    assert store.manifest(build_id) == manifest
    assert store.indexed_clause_ids(build_id) == frozenset(clause_ids)
    resumed = ledger.summary()
    # The failed attempt keeps its full ceiling and stays visibly unsettled; the retried
    # batches are charged their real usage.
    assert resumed["embedding_batches"] == 3 and resumed["unsettled_requests"] == 1
    assert resumed["charged_or_reserved_cny"] == str(
        Decimal("0.10") + Decimal(12) * Decimal("0.5") / Decimal(1_000_000)
    )


def test_online_factory_reuses_a_prebuilt_index_without_a_supplier_request(tmp_path):
    index = make_snapshot(tmp_path, 4)
    private_root = tmp_path / "private"
    ledger, guard, prebuild_transport, provider = guarded_runtime(tmp_path)
    prebuilt, plan = build_authorized_vector_index(
        index=index,
        provider=provider,
        guard=guard,
        store=SQLiteVectorIndex(private_root / "legal-vectors.sqlite3"),
        publication_id="pub-a",
        revision_id="rev-a",
    )
    assert len(prebuild_transport.calls) == 1
    assert prebuilt.item_count == 4 and len(plan.batches) == 1

    online_transport = CountingTransport()
    factory = create_real_retriever_factory(
        api_key="example-synthetic-credential",
        workspace_id="synthetic",
        budget=ledger,
        private_root=private_root,
        client=httpx.Client(transport=online_transport, trust_env=False),
    )
    retriever = factory(index, "pub-a", "rev-a")
    assert online_transport.calls == []
    assert retriever.build_id == prebuilt.build_id
    assert len(retriever.coverage) == 4
    assert (private_root / "vector-manifest.json").is_file()

    second = factory(index, "pub-a", "rev-a")
    assert second.build_id == prebuilt.build_id and online_transport.calls == []


def serving_factory(tmp_path, private_root, ledger):
    """The API assembly: an explicitly empty-index-refusing factory plus its transport."""
    transport = CountingTransport()
    factory = create_real_retriever_factory(
        api_key="example-synthetic-credential",
        workspace_id="synthetic",
        budget=ledger,
        private_root=private_root,
        client=httpx.Client(transport=transport, trust_env=False),
    )
    assert factory.allow_build is False  # serving never builds; the CLI path does
    return factory, transport


def test_serving_api_refuses_a_missing_index_without_any_provider_call(tmp_path):
    index = make_snapshot(tmp_path, 4)
    ledger, _guard, _transport, _provider = guarded_runtime(tmp_path)
    factory, transport = serving_factory(tmp_path, tmp_path / "private", ledger)

    with pytest.raises(RuntimeError, match="not prebuilt"):
        factory(index, "pub-a", "rev-a")
    assert transport.calls == []
    assert ledger.summary()["embedding_batches"] == 0
    assert not (tmp_path / "private" / "vector-manifest.json").exists()


def test_serving_api_refuses_an_unfinished_or_damaged_index(tmp_path):
    index = make_snapshot(tmp_path, 4)
    private_root = tmp_path / "private"
    ledger, guard, _transport, provider = guarded_runtime(tmp_path)
    store_path = private_root / "legal-vectors.sqlite3"
    built, _plan = build_authorized_vector_index(
        index=index,
        provider=provider,
        guard=guard,
        store=SQLiteVectorIndex(store_path),
        publication_id="pub-a",
        revision_id="rev-a",
    )
    first, first_transport = serving_factory(tmp_path, private_root, ledger)
    assert first(index, "pub-a", "rev-a").build_id == built.build_id
    assert first_transport.calls == []

    def rewrite(statement: str, parameters: tuple[object, ...] = ()) -> None:
        with sqlite3.connect(store_path) as db:
            db.execute(statement, parameters)

    # An index that is still being built is not what a serving API may reuse.
    rewrite(
        "UPDATE vector_build SET status='building' WHERE build_id = ?", (built.build_id,)
    )
    unfinished, unfinished_transport = serving_factory(tmp_path, private_root, ledger)
    with pytest.raises(RuntimeError, match="not prebuilt"):
        unfinished(index, "pub-a", "rev-a")
    assert unfinished_transport.calls == []
    rewrite(
        "UPDATE vector_build SET status='complete' WHERE build_id = ?", (built.build_id,)
    )

    # A cached vector that no longer matches its recorded checksum fails the integrity
    # check; the API refuses instead of repairing (or re-embedding) the damaged row.
    with sqlite3.connect(store_path) as db:
        (clause_id,) = db.execute("SELECT clause_id FROM vector_cache LIMIT 1").fetchone()
    rewrite(
        "UPDATE vector_cache SET vector_bytes = zeroblob(length(vector_bytes)) "
        "WHERE clause_id = ?",
        (clause_id,),
    )
    damaged, damaged_transport = serving_factory(tmp_path, private_root, ledger)
    with pytest.raises(ValueError, match="checksum mismatch"):
        damaged(index, "pub-a", "rev-a")
    assert damaged_transport.calls == []

    # A cache entry that disappeared leaves the build incomplete.
    rewrite("DELETE FROM vector_cache WHERE clause_id = ?", (clause_id,))
    incomplete, incomplete_transport = serving_factory(tmp_path, private_root, ledger)
    with pytest.raises(ValueError, match="missing for an index item|coverage"):
        incomplete(index, "pub-a", "rev-a")
    assert incomplete_transport.calls == []
    assert ledger.summary()["embedding_batches"] == 1  # only the prebuild batch


def test_serving_api_requires_the_prebuilt_publication_revision_identity_and_volume(tmp_path):
    index = make_snapshot(tmp_path, 4)
    private_root = tmp_path / "private"
    ledger, guard, _transport, provider = guarded_runtime(tmp_path)
    build_authorized_vector_index(
        index=index,
        provider=provider,
        guard=guard,
        store=SQLiteVectorIndex(private_root / "legal-vectors.sqlite3"),
        publication_id="pub-a",
        revision_id="rev-a",
    )

    # A different publication/revision is a different build identity: never a silent reuse.
    publication, publication_transport = serving_factory(tmp_path, private_root, ledger)
    for publication_id, revision_id in (("pub-b", "rev-a"), ("pub-a", "rev-b")):
        with pytest.raises(RuntimeError, match="not prebuilt"):
            publication(index, publication_id, revision_id)
    assert publication_transport.calls == []

    # A different modelstate volume holds no index at all.
    other_volume, volume_transport = serving_factory(tmp_path, tmp_path / "other-volume", ledger)
    with pytest.raises(RuntimeError, match="not prebuilt"):
        other_volume(index, "pub-a", "rev-a")
    assert volume_transport.calls == []

    # The budget ledger is the same durable file, and only that scope may continue it.
    reopened = Dec005BudgetLedger(
        tmp_path / "budget.sqlite3", scope_sha256="a" * 64,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    assert reopened.summary()["embedding_batches"] == 1
    with pytest.raises(ValueError, match="different scope"):
        Dec005BudgetLedger(
            tmp_path / "budget.sqlite3", scope_sha256="e" * 64,
            authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
        )


def test_serving_api_refuses_an_index_built_by_a_different_embedding_identity(tmp_path):
    """Any identity difference changes the build id, so the serving lookup finds nothing.

    Here the stored index was produced by a contract-test (mock transport) provider while
    the serving provider runs online: the two identities have different
    ``identity_sha256`` values and the same publication may never be served from the other
    identity's vectors.
    """
    index = make_snapshot(tmp_path, 4)
    private_root = tmp_path / "private"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-request",
                "model": body["model"],
                "object": "list",
                "usage": {
                    "total_tokens": len(body["input"]),
                    "prompt_tokens": len(body["input"]),
                },
                "data": [
                    {
                        "index": position,
                        "object": "embedding",
                        "embedding": [0.0] * body["dimensions"],
                    }
                    for position in range(len(body["input"]))
                ],
            },
        )

    ledger, _guard, _transport, _provider = guarded_runtime(tmp_path)
    contract_provider = DashScopeEmbeddingProvider(
        real_embedding_settings(api_key="example-synthetic-credential", workspace_id="synthetic"),
        client=httpx.Client(transport=httpx.MockTransport(mock_handler), trust_env=False),
    )
    assert contract_provider.execution_mode == "mock_contract"
    store = SQLiteVectorIndex(private_root / "legal-vectors.sqlite3")
    build_authorized_vector_index(
        index=index,
        provider=contract_provider,
        guard=ScopedEmbeddingGuard(ledger),
        store=store,
        publication_id="pub-a",
        revision_id="rev-a",
    )
    with sqlite3.connect(store.path) as db:
        record = db.execute("SELECT identity_json FROM vector_build").fetchall()
    assert len(record) == 1
    assert json.loads(record[0][0])["parameters"]["execution_mode"] == "mock_contract"

    factory, transport = serving_factory(tmp_path, private_root, ledger)
    assert factory.provider.identity.dimensions == 1024
    assert factory.provider.execution_mode == "online"
    with pytest.raises(RuntimeError, match="not prebuilt"):
        factory(index, "pub-a", "rev-a")
    assert transport.calls == []


def test_maintenance_command_plans_the_full_corpus_locally(tmp_path, capsys, monkeypatch):
    """The CLI still owns the build: its local plan covers the frozen corpus."""
    import prebuild_legal_vectors

    monkeypatch.setattr(
        sys, "argv", ["prebuild_legal_vectors.py", "--dry-run", "--private-root", str(tmp_path)]
    )
    assert prebuild_legal_vectors.main() == 0
    counts = json.loads(capsys.readouterr().out)
    # The versioned corpus (knowledge/legal, config/legal) is a frozen snapshot: 3120
    # clauses, 3112 embeddable, 8 over the per-item ceiling. A change here is a corpus
    # change and must be re-measured, not silently accepted.
    assert counts["source_clause_count"] == 3120
    assert counts["authorized_clause_count"] == 3112
    assert counts["excluded_overlong_clause_count"] == 8
    assert counts["planned_batch_count"] == 312
    assert counts["max_items_per_batch"] == 10
    assert counts["max_item_utf8_bytes"] == 8192
    assert counts["max_batch_utf8_bytes"] == 32768
    assert not (tmp_path / "legal-vectors.sqlite3").exists()


def test_overlong_clause_is_reported_and_never_leaves_the_host(tmp_path):
    index = make_snapshot(tmp_path, 3, overlong_chars=2800)
    ledger, guard, transport, provider = guarded_runtime(tmp_path)
    store = SQLiteVectorIndex(tmp_path / "legal-vectors.sqlite3")
    manifest, plan = build_authorized_vector_index(
        index=index,
        provider=provider,
        guard=guard,
        store=store,
        publication_id="pub-a",
        revision_id="rev-a",
    )
    assert len(plan.excluded) == 1
    assert manifest.item_count == 3 and manifest.source_item_count == 4
    assert plan.excluded[0].clause_id not in store.indexed_clause_ids(manifest.build_id)
    assert sum(len(call) for call in transport.calls) == 3
    assert all("合" * 100 not in text for call in transport.calls for text in call)
    assert ledger.summary()["embedding_batches"] == 1


def test_runtime_reports_the_excluded_overlong_clause_count(tmp_path, caplog):
    index = make_snapshot(tmp_path, 3, overlong_chars=2800)
    ledger, _guard, _transport, _provider = guarded_runtime(tmp_path)
    # The maintenance path may build; the reporting of excluded clauses is the same.
    factory = create_real_retriever_factory(
        api_key="example-synthetic-credential",
        workspace_id="synthetic",
        budget=ledger,
        private_root=tmp_path / "private",
        client=httpx.Client(transport=CountingTransport(), trust_env=False),
        allow_build=True,
    )
    name = "bidding_compliance.services.real_embedding_runtime"
    with caplog.at_level(logging.INFO, logger=name):
        factory(index, "pub-a", "rev-a")
    record = next(item for item in caplog.records if item.getMessage() == "vector index ready")
    assert (record.batches, record.excluded_clause_count) == (1, 1)


def test_unapproved_query_text_and_its_approved_redaction_are_distinguished(tmp_path):
    ledger, guard, transport, provider = guarded_runtime(tmp_path)
    raw = "投标保证金比例。联系人：张三，电话：022-12345678"
    approved = redact_discovery_text(raw)
    assert approved != raw
    guard.approve([approved])
    with pytest.raises(PermissionError):
        provider.embed([raw])
    assert not transport.calls
    assert provider.embed([approved])
    assert transport.calls == [[approved]]
    assert ledger.summary()["embedding_batches"] == 1


def test_legacy_send_subset_behaviour_is_unchanged(tmp_path):
    index = make_snapshot(tmp_path, 4)
    store = SQLiteVectorIndex(tmp_path / "legal-vectors.sqlite3")
    legacy = PositionalProvider(tag=1.0, max_batch_items=2)
    store.build(index, legacy, publication_id="pub-a", revision_id="rev-a")
    assert [len(call) for call in legacy.calls] == [2, 2]

    first, second = ordered_clauses(index)[:2]

    def drop_first_cache_row() -> None:
        with sqlite3.connect(store.path) as db:
            db.execute("DELETE FROM vector_cache WHERE clause_id=?", (first.clause_id,))

    drop_first_cache_row()
    subset = PositionalProvider(tag=2.0, max_batch_items=2)
    store.build(index, subset, publication_id="pub-b", revision_id="rev-b")
    assert subset.calls == [[first.quote]]

    drop_first_cache_row()
    full = PositionalProvider(tag=3.0, max_batch_items=2)
    store.build(index, full, publication_id="pub-c", revision_id="rev-c", send_full_batches=True)
    assert full.calls == [[first.quote, second.quote]]
