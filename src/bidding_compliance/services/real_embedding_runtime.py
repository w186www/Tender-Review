"""DEC-005 bounded corpus coverage with matching real corpus/query vectors."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from itertools import combinations
from pathlib import Path

import httpx
from pydantic import SecretStr

from bidding_compliance.legal.contracts import LegalIndex
from bidding_compliance.legal.dense_retrieval import DenseHybridRetriever
from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    DashScopeEmbeddingSettings,
)
from bidding_compliance.legal.vector_index import SQLiteVectorIndex
from bidding_compliance.model_gateway.authorized_runtime import (
    Dec005BudgetLedger,
    MetadataAuditSink,
)
from bidding_compliance.services.llm_candidate_discovery import redact_discovery_text


class ScopedEmbeddingGuard:
    def __init__(self, budget: Dec005BudgetLedger) -> None:
        self.budget = budget
        self.allowed_hashes: set[str] = set()

    def approve(self, texts: Sequence[str]) -> None:
        payload = {
            "model": "text-embedding-v4",
            "input": list(texts),
            "dimensions": 1024,
            "encoding_format": "float",
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.allowed_hashes.add(digest)

    def reserve_external(self, *, kind: str, request_hash: str, ceiling: Decimal) -> str:
        if kind != "embedding" or request_hash not in self.allowed_hashes:
            raise PermissionError("embedding request is outside the approved corpus/query scope")
        return self.budget.reserve_external(kind=kind, request_hash=request_hash, ceiling=ceiling)

    def settle_external(self, reservation: str, actual: Decimal) -> None:
        self.budget.settle_external(reservation, actual)


def create_real_retriever_factory(
    *,
    api_key: str,
    workspace_id: str,
    budget: Dec005BudgetLedger,
    private_root: Path,
) -> Callable[[LegalIndex, str, str], DenseHybridRetriever]:
    guard = ScopedEmbeddingGuard(budget)
    client = httpx.Client(trust_env=False, follow_redirects=False, timeout=20)
    credential = SecretStr(api_key)
    provider = DashScopeEmbeddingProvider(
        DashScopeEmbeddingSettings(
            enabled=True,
            region="beijing",
            workspace_id=workspace_id,
            model_id="text-embedding-v4",
            dimensions=1024,
            timeout_seconds=20,
            api_key=credential,
        ),
        client=client,
        guard=guard,
        audit_sink=MetadataAuditSink(private_root / "embedding-audit.jsonl"),
        input_price_per_million=Decimal("0.5"),
    )
    store = SQLiteVectorIndex(private_root / "legal-vectors.sqlite3")
    manifests: dict[tuple[str, str], str] = {}

    def safe_query(text: str) -> str:
        value = redact_discovery_text(text)
        guard.approve([value])
        return value

    def factory(index: LegalIndex, publication_id: str, revision_id: str) -> DenseHybridRetriever:
        identity = (publication_id, revision_id)
        if identity not in manifests:
            # A small initial complete subset; the full corpus remains available to BM25.
            chosen = sorted(
                (clause for clause in index.clauses if 4 <= len(clause.quote.encode()) <= 3000),
                key=lambda clause: (clause.law_id, clause.version, clause.clause_id),
            )[:10]
            if not chosen:
                raise ValueError("legal snapshot has no bounded authorized embedding subset")
            # Cached/resumed batches may contain any missing subset of these ten items.
            for size in range(1, len(chosen) + 1):
                for subset in combinations(chosen, size):
                    guard.approve([clause.quote for clause in subset])
            manifest = store.build(
                index,
                provider,
                publication_id=publication_id,
                revision_id=revision_id,
                clause_ids=[clause.clause_id for clause in chosen],
            )
            if manifest.embedding_identity.parameters.get("execution_mode") != "online":
                raise ValueError("real retrieval cannot reuse contract-test vectors")
            (private_root / "vector-manifest.json").write_text(
                manifest.model_dump_json(indent=2), encoding="utf-8"
            )
            manifests[identity] = manifest.build_id
        return DenseHybridRetriever(
            index,
            provider=provider,
            vector_index=store,
            build_id=manifests[identity],
            publication_id=publication_id,
            revision_id=revision_id,
            query_minimizer=safe_query,
        )

    return factory
