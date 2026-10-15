"""DEC-007 authorized embedding runtime: full-corpus index and batch-bound guard."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import httpx
from pydantic import SecretStr

from bidding_compliance.legal.contracts import LegalClause, LegalIndex
from bidding_compliance.legal.dense_retrieval import DenseHybridRetriever
from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    DashScopeEmbeddingSettings,
)
from bidding_compliance.legal.vector_index import (
    BatchPlan,
    SQLiteVectorIndex,
    VectorIndexManifest,
    plan_batches,
)
from bidding_compliance.model_gateway.authorized_runtime import (
    Dec005BudgetLedger,
    MetadataAuditSink,
)
from bidding_compliance.services.llm_candidate_discovery import redact_discovery_text

LOGGER = logging.getLogger(__name__)

EMBEDDING_MODEL_ID = "text-embedding-v4"
EMBEDDING_DIMENSIONS = 1024
EMBEDDING_INPUT_PRICE_PER_MILLION = Decimal("0.5")
# Every clause at least this long is embeddable; the per-item ceiling stays the provider's
# own setting, so the pre-authorized batches and the provider's request limits agree.
MIN_CLAUSE_UTF8_BYTES = 4


class ScopedEmbeddingGuard:
    """Exact-digest gate in front of every embedding request and the budget ledger.

    The guard approves the canonical request payloads of the authorized corpus batches and
    of redacted query texts. The provider only passes the request digest back, so the guard
    keeps its strict membership check unchanged: text that was never approved cannot reach
    the supplier, and no approval is inferred from a changed or reordered payload.
    """

    def __init__(self, budget: Dec005BudgetLedger) -> None:
        self.budget = budget
        self.allowed_hashes: set[str] = set()

    def approve(self, texts: Sequence[str]) -> None:
        payload = {
            "model": EMBEDDING_MODEL_ID,
            "input": list(texts),
            "dimensions": EMBEDDING_DIMENSIONS,
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


def clause_order(clause: LegalClause) -> tuple[str, str, str]:
    """The one deterministic clause order the plan and the durable build both follow."""
    return (clause.law_id, clause.version, clause.clause_id)


def real_embedding_settings(
    *, api_key: str, workspace_id: str, enabled: bool = True
) -> DashScopeEmbeddingSettings:
    """The one settings object the online runtime and the offline prebuild both use."""
    credential = SecretStr(api_key) if enabled else None
    return DashScopeEmbeddingSettings(
        enabled=enabled,
        region="beijing",
        workspace_id=workspace_id,
        model_id=EMBEDDING_MODEL_ID,
        dimensions=EMBEDDING_DIMENSIONS,
        timeout_seconds=20,
        api_key=credential,
    )


def authorized_vector_plan(
    index: LegalIndex,
    *,
    max_items: int,
    max_item_bytes: int,
    max_batch_bytes: int,
) -> BatchPlan:
    """Every embeddable clause of the frozen snapshot, as deterministic authorized batches.

    The whole corpus is covered instead of an arbitrary leading slice: each clause long
    enough to embed enters the plan, and clauses above the per-item ceiling are reported in
    ``BatchPlan.excluded`` (they stay retrievable through BM25) so the caller can surface
    the count instead of silently dropping them.
    """
    embeddable = sorted(
        (
            clause
            for clause in index.clauses
            if len(clause.quote.encode("utf-8")) >= MIN_CLAUSE_UTF8_BYTES
        ),
        key=clause_order,
    )
    return plan_batches(
        embeddable,
        max_items=max_items,
        max_item_bytes=max_item_bytes,
        max_batch_bytes=max_batch_bytes,
    )


def approve_plan_batches(guard: ScopedEmbeddingGuard, plan: BatchPlan) -> int:
    """Pre-authorize exactly the batches a full-batch build will send; returns the count."""
    for batch in plan.batches:
        guard.approve([clause.quote for clause in batch])
    return len(plan.batches)


def build_authorized_vector_index(
    *,
    index: LegalIndex,
    provider: DashScopeEmbeddingProvider,
    guard: ScopedEmbeddingGuard,
    store: SQLiteVectorIndex,
    publication_id: str,
    revision_id: str,
) -> tuple[VectorIndexManifest, BatchPlan]:
    """Plan, pre-authorize and build (or reuse) the complete authorized vector index.

    Batch membership follows from the clause order and the provider ceilings alone, so the
    approved request digests are exactly the ones this build sends. An already complete
    build of the same selection is reused without approving or sending anything, which is
    what lets the online path serve queries from an index the operator prebuilt offline.
    """
    settings = provider.settings
    plan = authorized_vector_plan(
        index,
        max_items=provider.max_batch_items,
        max_item_bytes=settings.max_text_utf8_bytes,
        max_batch_bytes=settings.max_batch_utf8_bytes,
    )
    if not plan.clause_ids:
        raise ValueError("legal snapshot has no authorized embeddable clause")
    build_id = store.planned_build_id(
        index,
        provider,
        publication_id=publication_id,
        revision_id=revision_id,
        clause_ids=plan.clause_ids,
    )
    try:
        return store.manifest(build_id), plan
    except LookupError:
        pass
    approve_plan_batches(guard, plan)
    manifest = store.build(
        index,
        provider,
        publication_id=publication_id,
        revision_id=revision_id,
        clause_ids=plan.clause_ids,
        send_full_batches=True,
        max_item_bytes=settings.max_text_utf8_bytes,
        max_batch_bytes=settings.max_batch_utf8_bytes,
    )
    return manifest, plan


class AuthorizedRetrieverFactory:
    """Callable retriever factory owning one authorized embedding runtime and index."""

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str,
        budget: Dec005BudgetLedger,
        private_root: Path,
        client: httpx.Client | None = None,
    ) -> None:
        self.private_root = private_root
        self.guard = ScopedEmbeddingGuard(budget)
        self.settings = real_embedding_settings(api_key=api_key, workspace_id=workspace_id)
        self.client = client or httpx.Client(trust_env=False, follow_redirects=False, timeout=20)
        self.provider = DashScopeEmbeddingProvider(
            self.settings,
            client=self.client,
            guard=self.guard,
            audit_sink=MetadataAuditSink(private_root / "embedding-audit.jsonl"),
            input_price_per_million=EMBEDDING_INPUT_PRICE_PER_MILLION,
        )
        self.store = SQLiteVectorIndex(private_root / "legal-vectors.sqlite3")
        self.manifests: dict[tuple[str, str], str] = {}

    def safe_query(self, text: str) -> str:
        value = redact_discovery_text(text)
        self.guard.approve([value])
        return value

    def __call__(
        self, index: LegalIndex, publication_id: str, revision_id: str
    ) -> DenseHybridRetriever:
        identity = (publication_id, revision_id)
        if identity not in self.manifests:
            manifest, plan = build_authorized_vector_index(
                index=index,
                provider=self.provider,
                guard=self.guard,
                store=self.store,
                publication_id=publication_id,
                revision_id=revision_id,
            )
            if manifest.embedding_identity.parameters.get("execution_mode") != "online":
                raise ValueError("real retrieval cannot reuse contract-test vectors")
            LOGGER.info(
                "vector index ready",
                extra={
                    "event": "vector_index_ready",
                    "batches": len(plan.batches),
                    "excluded_clause_count": len(plan.excluded),
                },
            )
            (self.private_root / "vector-manifest.json").write_text(
                manifest.model_dump_json(indent=2), encoding="utf-8"
            )
            self.manifests[identity] = manifest.build_id
        return DenseHybridRetriever(
            index,
            provider=self.provider,
            vector_index=self.store,
            build_id=self.manifests[identity],
            publication_id=publication_id,
            revision_id=revision_id,
            query_minimizer=self.safe_query,
        )


def create_real_retriever_factory(
    *,
    api_key: str,
    workspace_id: str,
    budget: Dec005BudgetLedger,
    private_root: Path,
    client: httpx.Client | None = None,
) -> Callable[[LegalIndex, str, str], DenseHybridRetriever]:
    """Authorized dense retriever factory for the server assembly."""
    return AuthorizedRetrieverFactory(
        api_key=api_key,
        workspace_id=workspace_id,
        budget=budget,
        private_root=private_root,
        client=client,
    )
