"""DEC-007 offline prebuild of the complete authorized legal vector index.

Building the authorized batches of the full corpus (about 312 requests) belongs in an
explicit operator step, not in the first review request of a demo. This script plans the
batches exactly as the online path does (same clause order, same provider ceilings, same
pre-authorization), builds or resumes the durable SQLite index, and reports the counts.

Usage on the authorized host (real, paid supplier requests; the server authorization and
credentials must already be present in the environment):

    DEC007_AUTHORIZATION_ID=DEC-007-2026-10-16 \
    DASHSCOPE_API_KEY=... BAILIAN_WORKSPACE_ID=... \
    python scripts/prebuild_legal_vectors.py --publication-id <id> --revision-id <id>

The publication and revision identifiers are the active ones from the legal corpus state:
`deploy/demo_init.py` prints the publication, and both are readable from the database with

    docker compose exec postgres psql -U postgres -d bidding_compliance -c \
        "select publication_id, revision_id from legal_publication \
         order by sequence desc limit 1"

Alternatively pass ``--from-manifest <vector-manifest.json>`` from an earlier run in the
same private root. A completed index of the same selection is reused without a supplier
request, so the online path serves queries from the prebuilt index. ``--dry-run`` plans and
reports locally: no credentials, no ledger, no index file and no supplier request.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import httpx  # noqa: E402

from bidding_compliance.legal.contracts import LegalIndex, LegalManifest  # noqa: E402
from bidding_compliance.legal.corpus import ingest, read_bounded  # noqa: E402
from bidding_compliance.legal.embedding_provider import DashScopeEmbeddingProvider  # noqa: E402
from bidding_compliance.legal.vector_index import SQLiteVectorIndex  # noqa: E402
from bidding_compliance.model_gateway.authorized_runtime import (  # noqa: E402
    FULL_CAPABILITY_AUTHORIZATION_ID,
    Dec005BudgetLedger,
    MetadataAuditSink,
)
from bidding_compliance.services.real_ai_runtime import (  # noqa: E402
    resolve_real_runtime_authorization,
)
from bidding_compliance.services.real_embedding_runtime import (  # noqa: E402
    EMBEDDING_INPUT_PRICE_PER_MILLION,
    ScopedEmbeddingGuard,
    authorized_vector_plan,
    build_authorized_vector_index,
    real_embedding_settings,
)

DEFAULT_PRIVATE_ROOT = ROOT / ".verification/private/TASK-0023"
INDEX_FILE = "legal-vectors.sqlite3"
MANIFEST_FILE = "vector-manifest.json"


def load_legal_index(corpus_root: Path, manifest_name: str) -> LegalIndex:
    manifest = LegalManifest.model_validate_json(read_bounded(corpus_root, manifest_name))
    return ingest(corpus_root, manifest)


def planned_counts(index: LegalIndex, provider: DashScopeEmbeddingProvider) -> dict[str, object]:
    plan = authorized_vector_plan(
        index,
        max_items=provider.max_batch_items,
        max_item_bytes=provider.settings.max_text_utf8_bytes,
        max_batch_bytes=provider.settings.max_batch_utf8_bytes,
    )
    return {
        "source_clause_count": len(index.clauses),
        "authorized_clause_count": plan.item_count,
        "planned_batch_count": len(plan.batches),
        "excluded_overlong_clause_count": len(plan.excluded),
        "max_items_per_batch": provider.max_batch_items,
        "max_item_utf8_bytes": provider.settings.max_text_utf8_bytes,
        "max_batch_utf8_bytes": provider.settings.max_batch_utf8_bytes,
    }


def identifiers(args: argparse.Namespace) -> tuple[str, str]:
    if args.from_manifest is not None:
        if args.publication_id or args.revision_id:
            raise SystemExit("--from-manifest cannot be combined with explicit identifiers")
        try:
            payload = json.loads(args.from_manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"cannot read --from-manifest: {exc}") from exc
        publication_id = payload.get("publication_id") if isinstance(payload, dict) else None
        revision_id = payload.get("revision_id") if isinstance(payload, dict) else None
        if not isinstance(publication_id, str) or not isinstance(revision_id, str):
            raise SystemExit("--from-manifest does not hold a publication and revision id")
        return publication_id, revision_id
    if not args.publication_id or not args.revision_id:
        raise SystemExit("an active publication and revision id are required to build the index")
    return args.publication_id, args.revision_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, default=ROOT)
    parser.add_argument("--manifest", default="config/legal/manifest.json")
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--publication-id", default="")
    parser.add_argument("--revision-id", default="")
    parser.add_argument("--from-manifest", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="plan locally, never spend")
    args = parser.parse_args()

    index = load_legal_index(args.corpus_root, args.manifest)
    if args.dry_run:
        provider = DashScopeEmbeddingProvider(
            real_embedding_settings(
                api_key="", workspace_id="prebuild-dry-run", enabled=False
            )
        )
        print(json.dumps(planned_counts(index, provider), ensure_ascii=False, indent=2))
        return 0

    resolution = resolve_real_runtime_authorization(os.environ, private_root=args.private_root)
    if resolution.authorization_id != FULL_CAPABILITY_AUTHORIZATION_ID:
        raise SystemExit("the full-corpus prebuild requires the DEC-007 authorization")
    credential = os.environ.get("DASHSCOPE_API_KEY", "")
    workspace_id = os.environ.get("BAILIAN_WORKSPACE_ID", "")
    if not credential.strip() or not workspace_id.strip():
        raise SystemExit("the real embedding prebuild requires server-side credentials")
    publication_id, revision_id = identifiers(args)
    budget = Dec005BudgetLedger(
        resolution.ledger_path,
        scope_sha256=resolution.scope_sha256,
        authorization_id=resolution.authorization_id,
    )
    guard = ScopedEmbeddingGuard(budget)
    settings = real_embedding_settings(api_key=credential, workspace_id=workspace_id)
    provider = DashScopeEmbeddingProvider(
        settings,
        client=httpx.Client(trust_env=False, follow_redirects=False, timeout=20),
        guard=guard,
        audit_sink=MetadataAuditSink(args.private_root / "embedding-audit.jsonl"),
        input_price_per_million=EMBEDDING_INPUT_PRICE_PER_MILLION,
    )
    store = SQLiteVectorIndex(args.private_root / INDEX_FILE)
    plan = planned_counts(index, provider)
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    manifest, batch_plan = build_authorized_vector_index(
        index=index,
        provider=provider,
        guard=guard,
        store=store,
        publication_id=publication_id,
        revision_id=revision_id,
    )
    (args.private_root / MANIFEST_FILE).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "authorization_id": resolution.authorization_id,
                "ledger_path": str(resolution.ledger_path),
                "approved_batch_count": len(batch_plan.batches),
                "manifest": manifest.model_dump(mode="json"),
                "budget": budget.summary(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
