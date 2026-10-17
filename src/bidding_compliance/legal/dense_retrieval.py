"""BM25 plus snapshot-bound dense candidates; legal eligibility stays deterministic."""

from collections.abc import Callable

from .adoption import AdoptionPolicy
from .contracts import (
    LegalClause,
    LegalIndex,
    LegalVersion,
    Reason,
    RetrievalQuery,
    RetrievalRuntimeSnapshot,
)
from .retrieval import LegalRetriever, clause_exclusions, confirmation_reason
from .vector_index import DenseEmbeddingProvider, SQLiteVectorIndex


class DenseHybridRetriever(LegalRetriever):
    """Explicit dense runtime: no online error silently switches to CharacterEmbedding.

    Only indexed, confirmed applicable clauses participate in neural ranking. BM25
    can still return explicitly marked references from the full frozen corpus.
    """

    retrieval_version = "bm25-dense-cosine-rrf-1"

    def __init__(
        self,
        index: LegalIndex,
        *,
        provider: DenseEmbeddingProvider,
        vector_index: SQLiteVectorIndex,
        build_id: str,
        publication_id: str,
        revision_id: str,
        query_minimizer: Callable[[str], str] | None = None,
        adoption_policy: AdoptionPolicy | None = None,
    ) -> None:
        super().__init__(index, adoption_policy=adoption_policy)
        self.provider = provider
        self.vector_index = vector_index
        self.build_id = build_id
        self.publication_id = publication_id
        self.revision_id = revision_id
        self.query_minimizer = query_minimizer
        self.manifest = vector_index.manifest(build_id)
        if self.manifest.legal_snapshot_sha256 != self.snapshot_hash:
            raise ValueError("dense retrieval snapshot differs from vector index")
        if (self.manifest.publication_id, self.manifest.revision_id) != (
            publication_id, revision_id
        ):
            raise ValueError("dense retrieval publication differs from vector index")
        if self.manifest.embedding_identity != provider.identity:
            raise ValueError("dense query and corpus provider identities differ")
        self.coverage = vector_index.indexed_clause_ids(build_id)

    def runtime_snapshot(self, top_k: int) -> RetrievalRuntimeSnapshot:
        return RetrievalRuntimeSnapshot(
            algorithm="bm25-dense-cosine-rrf-1",
            top_k=top_k,
            embedding_identity=self.provider.identity,
            vector_index_build_id=self.build_id,
            vector_index_item_count=self.manifest.item_count,
            vector_source_item_count=len(self.index.clauses),
        )

    def _vector_ranking(
        self, query: RetrievalQuery, eligible: list[tuple[LegalClause, LegalVersion, Reason]]
    ) -> list[tuple[str, float]]:
        if self.vector_index.manifest(self.build_id) != self.manifest:
            raise ValueError("dense vector artifact changed after runtime selection")
        # Do not externalize even the query when the deterministic filter yields
        # no indexed, verified applicable law. Incomplete contexts are rejected
        # by the project service before this method can run.
        if not any(
            clause.clause_id in self.coverage
            and not clause_exclusions(version, clause.article, query)
            and confirmation_reason(version, clause.article, query) == "valid"
            for clause, version, _ in eligible
        ):
            return []
        text = self.query_minimizer(query.text) if self.query_minimizer else query.text
        vector = self.vector_index.embed_query(self.provider, text)
        return [
            (hit.clause_id, hit.score)
            for hit in self.vector_index.search_candidates(
                self.build_id,
                vector,
                query_identity=self.provider.identity,
                legal_index=self.index,
                query=query,
                publication_id=self.publication_id,
                revision_id=self.revision_id,
                top_k=len(self.coverage),
            )
        ]
