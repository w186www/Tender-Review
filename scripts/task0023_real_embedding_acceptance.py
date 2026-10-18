"""DEC-005 gated acceptance: real text-embedding-v4 subset, SQLite index and RRF fusion.

Default mode spends at most two supplier batches: one for the authorized legal subset and
one cached query vector. The evaluation context uses the verified legal version and its
verification horizon date to make the dense path observable; it proves the fusion
mechanism only and never claims that the real tender project is governed by that law.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from bidding_compliance.legal.contracts import LegalIndex, LegalManifest, RetrievalQuery
from bidding_compliance.legal.corpus import ingest, read_bounded
from bidding_compliance.legal.dense_retrieval import DenseHybridRetriever
from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    DashScopeEmbeddingSettings,
)
from bidding_compliance.legal.vector_index import SQLiteVectorIndex
from bidding_compliance.model_gateway.authorized_runtime import (
    AUTHORIZATION_ID,
    Dec005BudgetLedger,
    MetadataAuditSink,
)
from bidding_compliance.services.llm_candidate_discovery import redact_discovery_text
from bidding_compliance.services.real_ai_runtime import create_dec005_gateway
from bidding_compliance.services.real_embedding_runtime import ScopedEmbeddingGuard
from scripts.task0023_real_ai_acceptance import (
    TENDER_DOCUMENT_SHA256,
    synthetic_docx_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".verification/private/TASK-0023"
SUBSET_SIZE = 10
PUBLICATION_ID = "dec005-eval-publication"
REVISION_ID = "dec005-eval-revision-1"
QUERY_TEXT = "工程建设项目招标投标保证金收取比例、履约保证金退还期限与投标有效期规定"
REVIEW_DATE = date(2026, 10, 14)
SCOPE_NOTE = (
    "授权样本为天津地铁11号线DOCX与登记合成样本；本评测上下文使用已核验法规版本的"
    "核验截止日，仅用于使神经检索与融合路径可观察，不代表真实项目适用该法规，"
    "也不改变真实项目的 CONTEXT_INVALID 判定。"
)


def synthetic_document_sha256() -> str:
    return hashlib.sha256(synthetic_docx_bytes()).hexdigest()


def load_legal_index() -> LegalIndex:
    manifest = LegalManifest.model_validate_json(
        read_bounded(ROOT, "config/legal/manifest.json")
    )
    return ingest(ROOT, manifest)


def verified_subset(index: LegalIndex) -> list[Any]:
    verified = {item.law_id for item in index.manifest.versions if item.verification == "verified"}
    if not verified:
        raise SystemExit("no verified legal version is available for an authorized subset")
    chosen = sorted(
        (
            clause
            for clause in index.clauses
            if clause.law_id in verified and 4 <= len(clause.quote.encode()) <= 3000
        ),
        key=lambda clause: (clause.law_id, clause.version, clause.clause_id),
    )[:SUBSET_SIZE]
    if len(chosen) != SUBSET_SIZE:
        raise SystemExit("verified legal subset is smaller than the authorized coverage")
    return chosen


def vector_stats(vector: list[float] | tuple[float, ...]) -> dict[str, Any]:
    import math

    return {
        "dimension": len(vector),
        "non_zero": sum(1 for item in vector if item != 0.0),
        "finite": all(math.isfinite(item) for item in vector),
        "norm": round(math.sqrt(sum(item * item for item in vector)), 6),
    }


def build_retriever(
    index: LegalIndex, chosen: list[Any], credential: str, workspace_id: str
) -> tuple[DenseHybridRetriever, DashScopeEmbeddingProvider, Dec005BudgetLedger, Any]:
    # Reuse the production assembly so the durable ledger scope stays identical to it.
    _, _, ledger = create_dec005_gateway(
        api_key=credential,
        workspace_id=workspace_id,
        tenant_id="tenant-a",
        allowed_document_sha256=frozenset(
            {TENDER_DOCUMENT_SHA256, synthetic_document_sha256()}
        ),
        ledger_path=PRIVATE / "dec005-budget.sqlite3",
        audit_path=PRIVATE / "embedding-gateway-audit.jsonl",
    )
    guard = ScopedEmbeddingGuard(ledger)
    secret_str = SecretStr(credential)
    provider = DashScopeEmbeddingProvider(
        DashScopeEmbeddingSettings(
            enabled=True,
            region="beijing",
            workspace_id=workspace_id,
            model_id="text-embedding-v4",
            dimensions=1024,
            timeout_seconds=20,
            api_key=secret_str,
        ),
        client=httpx.Client(trust_env=False, follow_redirects=False, timeout=20),
        guard=guard,
        audit_sink=MetadataAuditSink(PRIVATE / "embedding-audit.jsonl"),
        input_price_per_million=Decimal("0.5"),
    )
    store = SQLiteVectorIndex(PRIVATE / "legal-vectors.sqlite3")
    for size in range(1, len(chosen) + 1):
        for subset in combinations(chosen, size):
            guard.approve([clause.quote for clause in subset])
    manifest = store.build(
        index,
        provider,
        publication_id=PUBLICATION_ID,
        revision_id=REVISION_ID,
        clause_ids=[clause.clause_id for clause in chosen],
    )
    if manifest.embedding_identity.parameters.get("execution_mode") != "online":
        raise SystemExit("real retrieval cannot reuse contract-test vectors")

    def safe_query(text: str) -> str:
        value = redact_discovery_text(text)
        guard.approve([value])
        return value

    retriever = DenseHybridRetriever(
        index,
        provider=provider,
        vector_index=store,
        build_id=manifest.build_id,
        publication_id=PUBLICATION_ID,
        revision_id=REVISION_ID,
        query_minimizer=safe_query,
    )
    return retriever, provider, ledger, store


def evaluation_query() -> RetrievalQuery:
    return RetrievalQuery(
        text=QUERY_TEXT,
        review_date=REVIEW_DATE,
        limit=10,
        region="CN",
        procurement_type="enterprise",
        project_type="works",
        procurement_method="tender",
        buyer_type="enterprise",
        subject_type="works",
        legal_frameworks=("tendering",),
    )


def run_acceptance() -> dict[str, Any]:
    if os.environ.get("DEC005_AUTHORIZATION_ID") != AUTHORIZATION_ID:
        raise SystemExit("DEC-005 real Embedding is disabled without its server authorization")
    credential = os.environ.get("DASHSCOPE_API_KEY", "")
    workspace_id = os.environ.get("BAILIAN_WORKSPACE_ID", "")
    if not credential.strip() or not workspace_id.strip():
        raise SystemExit("real Embedding requires server-side credentials")
    index = load_legal_index()
    chosen = verified_subset(index)
    retriever, provider, ledger, store = build_retriever(index, chosen, credential, workspace_id)
    before = ledger.summary()
    first = retriever.search(evaluation_query())
    after_first = ledger.summary()
    # Second identical search must be served from the durable query cache.
    second = retriever.search(evaluation_query())
    after_second = ledger.summary()
    query_vector = store.embed_query(provider, QUERY_TEXT)
    manifest = store.manifest(retriever.build_id)
    chosen_quote_hashes = [clause.quote_hash for clause in chosen]
    return {
        "authorization_id": AUTHORIZATION_ID,
        "scope_note": SCOPE_NOTE,
        "corpus": {
            "source_clause_count": len(index.clauses),
            "indexed_clause_count": manifest.item_count,
            "coverage_ratio": f"{manifest.item_count}/{len(index.clauses)}",
            "legal_snapshot_sha256": manifest.legal_snapshot_sha256,
            "publication_id": manifest.publication_id,
            "revision_id": manifest.revision_id,
            "build_id": manifest.build_id,
            "build_version": manifest.build_version,
            "dimension": manifest.embedding_identity.dimensions,
            "embedding_identity_sha256": manifest.embedding_identity.identity_sha256,
            "embedding_mode": manifest.embedding_identity.parameters.get("execution_mode"),
            "embedding_model": manifest.embedding_identity.model_id,
            "indexed_clause_ids": [clause.clause_id for clause in chosen],
            "indexed_quote_hashes": chosen_quote_hashes,
            "identity_matches_dense_runtime": (
                manifest.embedding_identity == provider.identity
                and retriever.manifest == manifest
            ),
        },
        "query_vector": vector_stats(query_vector),
        "first_search": {
            "retrieval_version": first.retrieval_version,
            "snapshot_hash": first.snapshot_hash,
            "hit_count": len(first.hits),
            "citable_evidence_count": len(first.citable_evidence),
            "ranking_trace": [item.model_dump(mode="json") for item in first.ranking_trace],
            "top_hits": [
                {
                    "evidence_id": hit.evidence_id,
                    "law_id": hit.law_id,
                    "version": hit.version,
                    "article": hit.article,
                    "score": hit.score,
                    "eligible_for_confirmation": hit.eligible_for_confirmation,
                    "reason": hit.reason,
                }
                for hit in first.hits[:5]
            ],
            "excluded_count": len(first.excluded),
        },
        "dense_observation": {
            "vector_ranked_hits": [
                item.clause_id for item in first.ranking_trace if item.vector_rank is not None
            ],
            "bm25_ranked_hits": [
                item.clause_id for item in first.ranking_trace if item.bm25_rank is not None
            ],
        },
        "cache_reuse": {
            "identical_search_results": (
                first.model_dump(mode="json") == second.model_dump(mode="json")
            ),
            "embedding_batches_before": before["embedding_batches"],
            "embedding_batches_after_first": after_first["embedding_batches"],
            "embedding_batches_after_second": after_second["embedding_batches"],
            "batches_added_total": after_second["embedding_batches"] - before["embedding_batches"],
            "cost_cny": after_second["charged_or_reserved_cny"],
        },
        "budget": {
            "before": before,
            "after": after_second,
            "limits": after_second["limits"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="local corpus planning only")
    args = parser.parse_args()
    if args.dry_run:
        index = load_legal_index()
        chosen = verified_subset(index)
        print(
            json.dumps(
                {
                    "source_clause_count": len(index.clauses),
                    "subset_size": len(chosen),
                    "articles": [clause.article for clause in chosen],
                    "query": evaluation_query().model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    result = run_acceptance()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    evidence = PRIVATE / "real-embedding-acceptance.json"
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:3500])
    print(f"evidence written: {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
