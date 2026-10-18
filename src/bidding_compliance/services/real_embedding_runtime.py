"""DEC-007 authorized embedding runtime: full-corpus index and batch-bound guard.

Two operations share one durable store, one embedding identity and the single DEC-007
budget ledger, and they are deliberately not interchangeable:

* the operator prebuild (``scripts/prebuild_legal_vectors.py``) plans and builds/resumes
  the full authorized index offline;
* the serving API only ever reuses an index that prebuild already wrote
  (:func:`require_prebuilt_vector_index`). A missing, partial or integrity-failed index
  refuses the run instead of embedding hundreds of batches synchronously.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import httpx
from pydantic import SecretStr

from bidding_compliance.legal.adoption import AdoptionPolicy
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
from bidding_compliance.model_gateway.authorized_runtime import MetadataAuditSink
from bidding_compliance.model_gateway.budget import ExternalBudgetLedger
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

    def __init__(self, budget: ExternalBudgetLedger) -> None:
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


def require_prebuilt_vector_index(
    *,
    index: LegalIndex,
    provider: DashScopeEmbeddingProvider,
    store: SQLiteVectorIndex,
    publication_id: str,
    revision_id: str,
) -> tuple[VectorIndexManifest, BatchPlan]:
    """Refuse real retrieval unless the operator prebuilt this exact index.

    The serving API runs this before a review is frozen: the planned build identity of the
    current corpus, embedding identity, publication and revision must already exist as a
    complete, integrity-verified index in the same durable store the maintenance command
    (``scripts/prebuild_legal_vectors.py``) wrote. The check is purely local: it approves
    nothing for egress, touches no budget reservation and can never start a provider call,
    so a missing or damaged index fails the run instead of launching hundreds of paid
    embedding batches on the interviewer's first click.

    A mismatch in any part of the identity is a refusal, never a silent rebuild: the
    embedding identity is bound into the build id, and publication/revision plus the full
    clause coverage are re-verified against the manifest that was found.
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
        manifest = store.manifest(build_id)
    except LookupError as exc:
        raise RuntimeError(
            "the authorized vector index for this embedding identity, publication and "
            "revision is not prebuilt; run scripts/prebuild_legal_vectors.py before "
            "serving real retrieval"
        ) from exc
    if manifest.embedding_identity.identity_sha256 != provider.identity.identity_sha256:
        raise ValueError("prebuilt vector index uses a different embedding identity")
    if (manifest.publication_id, manifest.revision_id) != (publication_id, revision_id):
        raise ValueError("prebuilt vector index belongs to a different legal publication")
    if manifest.embedding_identity.parameters.get("execution_mode") != "online":
        raise ValueError("real retrieval cannot reuse contract-test vectors")
    covered = store.indexed_clause_ids(build_id)
    if covered != frozenset(plan.clause_ids) or manifest.item_count != len(plan.clause_ids):
        raise ValueError("prebuilt vector index coverage is incomplete for the frozen corpus")
    return manifest, plan


class AuthorizedRetrieverFactory:
    """Callable retriever factory owning one authorized embedding runtime and index.

    ``allow_build`` is the explicit split between the two operations: the serving API
    passes ``False`` and only ever reuses an index the operator prebuilt, while the
    offline maintenance path (which builds and resumes the index directly through
    ``build_authorized_vector_index``) is the only place that may spend build batches.
    """

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str,
        budget: ExternalBudgetLedger,
        private_root: Path,
        client: httpx.Client | None = None,
        allow_build: bool = False,
        adoption_policy: AdoptionPolicy | None = None,
    ) -> None:
        self.private_root = private_root
        self.adoption_policy = adoption_policy
        self.allow_build = allow_build
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
            if self.allow_build:
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
            else:
                manifest, plan = require_prebuilt_vector_index(
                    index=index,
                    provider=self.provider,
                    store=self.store,
                    publication_id=publication_id,
                    revision_id=revision_id,
                )
            LOGGER.info(
                "vector index ready",
                extra={
                    "event": "vector_index_ready",
                    "batches": len(plan.batches),
                    "excluded_clause_count": len(plan.excluded),
                    "prebuilt": not self.allow_build,
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
            adoption_policy=self.adoption_policy,
        )


def create_real_retriever_factory(
    *,
    api_key: str,
    workspace_id: str,
    budget: ExternalBudgetLedger,
    private_root: Path,
    client: httpx.Client | None = None,
    allow_build: bool = False,
    adoption_policy: AdoptionPolicy | None = None,
) -> Callable[[LegalIndex, str, str], DenseHybridRetriever]:
    """Authorized dense retriever factory for the server assembly.

    The default refuses to build anything: absent an explicitly prebuilt index the caller
    gets an error, never a synchronous full-corpus embedding run.
    """
    return AuthorizedRetrieverFactory(
        api_key=api_key,
        workspace_id=workspace_id,
        budget=budget,
        private_root=private_root,
        client=client,
        allow_build=allow_build,
        adoption_policy=adoption_policy,
    )
