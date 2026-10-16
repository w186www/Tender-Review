"""Read-only vector-index plan and snapshot-delta check for the DEC-007 rounds.

Two questions the operator must answer without touching the volume, the ledger or a supplier:

1. *Which build id does this frozen corpus produce for that publication/revision?* The build
   identity is a pure function of the embedding identity, the legal snapshot hash, the
   publication/revision and the coverage of the authorized plan, so it can be recomputed
   locally. Recomputing the recorded phase-one build id from the recorded publication and
   revision is what makes the recorded index identity checkable before the volume is read.
2. *Does a new legal snapshot change any clause text?* The durable vector cache is keyed by
   (embedding identity, law_id, version, clause_id, text_sha256). If every clause of the new
   snapshot keeps its id and text hash, the rebuild of a new build id is served entirely from
   the cache: no clause text leaves the host and no embedding batch is spent. The delta report
   proves that per clause instead of asserting it.

Everything here is local and read-only: the corpus is only ingested, no SQLite file is
created, no ledger is opened, no provider request can happen. ``--expect-build-id`` turns the
recomputation into a check (exit code 2 on any difference).

Usage::

    # the recorded phase-one identity, from the frozen corpus (read-only)
    python scripts/task0027_index_plan.py \
        --publication-id 977826ab-948a-4681-9001-4866c7da3bc2 \
        --revision-id fa2407bb-1dff-4da8-b828-bcc846df76ad \
        --expect-build-id c7344cac...

    # what a re-verified snapshot changes (baseline = the previously committed manifest)
    git show <commit>:config/legal/manifest.json > .verification/baseline-manifest.json
    python scripts/task0027_index_plan.py \
        --baseline-manifest .verification/baseline-manifest.json \
        --publication-id <new publication> --revision-id <new revision>
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

from bidding_compliance.legal.contracts import LegalIndex, LegalManifest  # noqa: E402
from bidding_compliance.legal.corpus import ingest, read_bounded  # noqa: E402
from bidding_compliance.legal.embedding_provider import DashScopeEmbeddingProvider  # noqa: E402
from bidding_compliance.legal.hashing import canonical_hash  # noqa: E402
from bidding_compliance.legal.vector_index import (  # noqa: E402
    VectorIndexManifest,
    plan_batches,
)
from bidding_compliance.services.real_embedding_runtime import (  # noqa: E402
    authorized_vector_plan,
    real_embedding_settings,
)

DEFAULT_MANIFEST = "config/legal/manifest.json"


def embedding_provider(workspace_id: str = "index-plan") -> DashScopeEmbeddingProvider:
    """The online embedding identity with egress made impossible, not merely unused.

    ``MockTransport`` would flip the provider to its contract-test mode and change the
    identity, so the client carries a transport that raises on every request instead: the
    identity is the online one and any accidental request fails inside this process before a
    socket is opened. Nothing in this script ever calls ``embed``.
    """
    return DashScopeEmbeddingProvider(
        real_embedding_settings(
            api_key="example-index-plan-never-sent", workspace_id=workspace_id
        ),
        client=httpx.Client(transport=_RefusingTransport(), trust_env=False),
        guard=_NoEgress(),
        audit_sink=lambda event: None,
        input_price_per_million=Decimal("0.5"),
    )


class _RefusingTransport(httpx.BaseTransport):
    """Refuses every request in-process; no socket is ever opened by this script."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError("the index plan never issues a supplier request")


class _NoEgress:
    """Refuses every reservation: planning may inspect, never spend."""

    def reserve_external(self, *, kind: str, request_hash: str, ceiling: object) -> str:
        raise AssertionError("the index plan never reserves a supplier request")

    def settle_external(self, reservation: str, actual: object) -> None:
        raise AssertionError("the index plan never settles a supplier request")


def planned_identity(
    index: LegalIndex,
    provider: DashScopeEmbeddingProvider,
    *,
    publication_id: str,
    revision_id: str,
) -> dict[str, Any]:
    """The plan of the authorized corpus plus the build id it would produce.

    The build identity formula is the one ``SQLiteVectorIndex.planned_build_id`` applies
    (``tests/test_task0027_index_plan.py`` pins the two against each other); it is recomputed
    here so that no index file has to be opened, created or written.
    """
    settings = provider.settings
    plan = authorized_vector_plan(
        index,
        max_items=provider.max_batch_items,
        max_item_bytes=settings.max_text_utf8_bytes,
        max_batch_bytes=settings.max_batch_utf8_bytes,
    )
    coverage_sha = canonical_hash(sorted(plan.clause_ids))
    snapshot_sha = _snapshot_hash(index)
    build_id = VectorIndexManifest.build_identity(
        provider.identity, snapshot_sha, publication_id, revision_id, coverage_sha
    )
    return {
        "legal_snapshot_sha256": snapshot_sha,
        "publication_id": publication_id,
        "revision_id": revision_id,
        "embedding_identity_sha256": provider.identity.identity_sha256,
        "embedding_execution_mode": provider.identity.parameters.get("execution_mode"),
        "source_clause_count": len(index.clauses),
        "authorized_clause_count": plan.item_count,
        "excluded_overlong_clause_count": len(plan.excluded),
        "planned_batch_count": len(plan.batches),
        "max_items_per_batch": provider.max_batch_items,
        "max_item_utf8_bytes": settings.max_text_utf8_bytes,
        "max_batch_utf8_bytes": settings.max_batch_utf8_bytes,
        "coverage_sha256": coverage_sha,
        "build_id": build_id,
    }


def _snapshot_hash(index: LegalIndex) -> str:
    from bidding_compliance.legal.corpus import index_hash

    return index_hash(index)


def clause_keys(index: LegalIndex) -> dict[str, str]:
    """``clause_id -> text_sha256`` for the durable cache key, over the whole corpus."""
    import hashlib

    return {
        clause.clause_id: hashlib.sha256(clause.quote.encode("utf-8")).hexdigest()
        for clause in index.clauses
    }


def snapshot_delta(
    baseline: LegalIndex,
    current: LegalIndex,
    *,
    provider: DashScopeEmbeddingProvider,
) -> dict[str, Any]:
    """Per-clause delta between two snapshots and the cache-reuse verdict for a rebuild."""
    before, after = clause_keys(baseline), clause_keys(current)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        clause_id for clause_id in set(before) & set(after) if before[clause_id] != after[clause_id]
    )
    # A rebuild queries the durable cache by the *new* corpus' keys. Every key that exists in
    # the baseline snapshot with the same text hash is a guaranteed cache hit; only the rest
    # would have to be embedded.
    new_plan = authorized_vector_plan(
        current,
        max_items=provider.max_batch_items,
        max_item_bytes=provider.settings.max_text_utf8_bytes,
        max_batch_bytes=provider.settings.max_batch_utf8_bytes,
    )
    misses = [key for key, text in after.items() if before.get(key) != text]
    planned = [key for key in new_plan.clause_ids if after.get(key) != before.get(key)]
    return {
        "baseline_source_clause_count": len(baseline.clauses),
        "current_source_clause_count": len(current.clauses),
        "baseline_snapshot_sha256": _snapshot_hash(baseline),
        "current_snapshot_sha256": _snapshot_hash(current),
        "added_clause_count": len(added),
        "removed_clause_count": len(removed),
        "changed_text_clause_count": len(changed),
        "cache_miss_clause_count": len(misses),
        "planned_cache_miss_clause_count": len(planned),
        "cache_reuse_complete": not planned,
        "estimated_new_embedding_batches": (
            0
            if not planned
            else len(
                plan_batches(
                    [clause for clause in current.clauses if clause.clause_id in set(planned)],
                    max_items=provider.max_batch_items,
                    max_item_bytes=provider.settings.max_text_utf8_bytes,
                    max_batch_bytes=provider.settings.max_batch_utf8_bytes,
                ).batches
            )
        ),
    }


def load_index(root: Path, manifest_name: str) -> LegalIndex:
    manifest = LegalManifest.model_validate_json(read_bounded(root, manifest_name))
    return ingest(root, manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus-root", type=Path, default=ROOT)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--baseline-manifest",
        type=Path,
        default=None,
        help="a previously committed manifest (e.g. `git show <commit>:...`) to diff against",
    )
    parser.add_argument("--publication-id", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument(
        "--expect-build-id", default="", help="refuse unless the planned build id equals this"
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.publication_id.strip() or not args.revision_id.strip():
        print("STOP: --publication-id and --revision-id are required", file=sys.stderr)
        return 2
    index = load_index(args.corpus_root, args.manifest)
    provider = embedding_provider()
    plan = planned_identity(
        index,
        provider,
        publication_id=args.publication_id,
        revision_id=args.revision_id,
    )
    report: dict[str, Any] = {"current": plan}
    if args.baseline_manifest is not None:
        baseline = load_index(args.corpus_root, str(args.baseline_manifest))
        report["baseline"] = planned_identity(
            baseline,
            provider,
            publication_id=args.publication_id,
            revision_id=args.revision_id,
        )
        report["delta"] = snapshot_delta(baseline, index, provider=provider)
    if args.expect_build_id and plan["build_id"] != args.expect_build_id:
        report["expected_build_id"] = args.expect_build_id
        report["build_id_matches"] = False
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        print(
            "STOP: the planned build id is "
            f"{plan['build_id']}, not the expected {args.expect_build_id}",
            file=sys.stderr,
        )
        return 2
    if args.expect_build_id:
        report["expected_build_id"] = args.expect_build_id
        report["build_id_matches"] = True
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"publication: {plan['publication_id']}  revision: {plan['revision_id']}")
        print(f"legal_snapshot_sha256: {plan['legal_snapshot_sha256']}")
        print(
            f"clauses: {plan['authorized_clause_count']}/{plan['source_clause_count']} "
            f"embeddable ({plan['excluded_overlong_clause_count']} overlong), "
            f"{plan['planned_batch_count']} batches"
        )
        print(
            f"embedding identity: {plan['embedding_identity_sha256']} "
            f"({plan['embedding_execution_mode']})"
        )
        print(f"planned build_id: {plan['build_id']}")
        if "delta" in report:
            delta = report["delta"]
            print(
                "delta vs baseline: "
                f"added={delta['added_clause_count']} removed={delta['removed_clause_count']} "
                f"changed_text={delta['changed_text_clause_count']} "
                f"planned_cache_misses={delta['planned_cache_miss_clause_count']} "
                f"new_batches={delta['estimated_new_embedding_batches']}"
            )
    if args.expect_build_id:
        reuse_complete = report.get("delta", {}).get("cache_reuse_complete", True)
        print(
            "PASS: the frozen corpus, the embedding identity and the publication/revision "
            "produce exactly the expected build id"
            + (
                "; the durable cache covers every planned clause (no new embedding batch)."
                if reuse_complete
                else "; WARNING: the durable cache does not cover every planned clause."
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
