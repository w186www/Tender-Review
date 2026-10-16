"""Read-only identity check for the recorded TASK-0027 DEC-007 round.

The phase-one round left its state on the ``modelstate`` volume, whose mount point inside the
container is ``/app/.verification/private`` (the volume root): the DEC-007 budget ledger, its
model audit trail, the per-file authorization registry, the prebuilt vector index and its
manifest. Before the official API (``scripts/task0023_real_ai_app.py``) or a controlled round
(``scripts/task0027_real_ai_validation_app.py``) touches that volume, an operator must be able
to see -- without writing anything -- that the whole identity set is one consistent set:

* the DEC-007 authorization identity and the ledger scope the ledger file itself records,
  re-computed from the *configured* registry path (the scope binds that path, so a different
  path is a different scope and would refuse the existing ledger);
* the private root, ledger, model audit and per-file registry paths of the running assembly;
* the legal publication and revision of the prebuilt index, cross-checked against the index
  manifest in the same volume and -- when a database URL is given -- against the current row
  of ``legal_publication``;
* the vector index build id, its item/source counts, its coverage and its per-item vector
  cache links, cross-checked against the frozen corpus snapshot hash.

Every read is read-only: the ledger and the index store are opened with SQLite ``mode=ro``
(a missing file is reported, never created), the JSON artifacts are only read, and no
supplier, socket or docker call is made. Exit codes: 0 every identity is consistent, 2 at
least one required identity is absent or inconsistent (stop and report).

Usage inside a one-off container on the deployed host (same volume, same image)::

    $D run --rm --no-deps api python scripts/task0027_identity_check.py \
        --expected-scope a3d2e9d0... \
        --publication-id 977826ab-948a-4681-9001-4866c7da3bc2 \
        --revision-id fa2407bb-1dff-4da8-b828-bcc846df76ad \
        --build-id c7344cac...

``--print-scope`` prints only the identity paths and the scope the current configuration
binds, without reading the ledger; it is what a host uses to confirm that the deployment's
configuration reproduces the recorded scope before any plan is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import task0027_ledger_baseline as ledger_baseline  # noqa: E402

from bidding_compliance.legal.contracts import LegalIndex, LegalManifest  # noqa: E402
from bidding_compliance.legal.corpus import index_hash, ingest, read_bounded  # noqa: E402
from bidding_compliance.legal.hashing import canonical_hash  # noqa: E402
from bidding_compliance.legal.vector_index import VectorIndexManifest  # noqa: E402
from bidding_compliance.model_gateway.authorized_runtime import (  # noqa: E402
    FULL_CAPABILITY_AUTHORIZATION_ID,
)
from bidding_compliance.services.real_ai_runtime import (  # noqa: E402
    RealRuntimeAuthorization,
    resolve_real_runtime_authorization,
    verify_ledger_continuity,
)

# The one private root of the server assemblies: the modelstate volume root inside the
# container (``docker-compose.demo.yml`` mounts ``modelstate:/app/.verification/private``).
PRIVATE_ROOT = ROOT / ".verification" / "private"
INDEX_FILE = "legal-vectors.sqlite3"
PREBUILT_MANIFEST_FILE = "vector-manifest.json"
LEGAL_MANIFEST = "config/legal/manifest.json"
# The frozen corpus the recorded round measured: 3120 clauses, 3112 of them embeddable.
# A corpus change must be re-measured, never silently accepted.
EXPECTED_ITEM_COUNT = 3112
EXPECTED_SOURCE_ITEM_COUNT = 3120
MANIFEST_SIZE_LIMIT = 1_000_000
IDENTITY_PASSED = "identity check passed"


class IdentityMismatch(RuntimeError):
    """A required identity is absent or does not agree with the recorded one."""


def digest_of(path: Path) -> str:
    """SHA-256 of a file, read in chunks; never writes and never loads it whole."""
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def file_facts(path: Path) -> dict[str, Any]:
    """Existence, size and hash of an artifact (absent files are reported, not created)."""
    if not path.is_file():
        return {"path": str(path), "present": False}
    return {
        "path": str(path),
        "present": True,
        "size_bytes": path.stat().st_size,
        "sha256": digest_of(path),
    }


def check_authorization(
    environment: Mapping[str, str], *, private_root: Path
) -> tuple[RealRuntimeAuthorization, str]:
    """Resolve the assembly identity and require the DEC-007 authorization and registry."""
    resolution = resolve_real_runtime_authorization(dict(environment), private_root=private_root)
    if resolution.authorization_id != FULL_CAPABILITY_AUTHORIZATION_ID:
        raise IdentityMismatch(
            "the assembly does not resolve to the DEC-007 authorization "
            f"({FULL_CAPABILITY_AUTHORIZATION_ID}); got {resolution.authorization_id!r}"
        )
    if resolution.registry_path is None:
        raise IdentityMismatch(
            "the DEC-007 authorization has no per-file registry path; the ledger scope of the "
            "recorded round binds one"
        )
    return resolution, resolution.scope_sha256


def check_ledger_and_audit(
    resolution: RealRuntimeAuthorization, *, expected_scope: str
) -> tuple[dict[str, Any], str]:
    """The ledger's own recorded scope, its counters and the audit-trail continuity link."""
    if not resolution.ledger_path.is_file():
        raise IdentityMismatch(
            f"the DEC-007 ledger is absent at {resolution.ledger_path}; stop and report "
            "instead of initialising a fresh quota"
        )
    facts = ledger_baseline.read_ledger_facts(
        resolution.ledger_path, authorization_id=resolution.authorization_id
    )
    recorded_scope = (facts.scope_sha256 or "").strip()
    if not recorded_scope:
        raise IdentityMismatch(
            "the DEC-007 ledger records no scope for this authorization; the recorded round "
            "always binds one"
        )
    if recorded_scope != resolution.scope_sha256:
        raise IdentityMismatch(
            "the ledger belongs to a different authorization scope than the current "
            f"configuration binds (ledger {recorded_scope}, configuration "
            f"{resolution.scope_sha256}); the authorization, tenant, environment allowlist or "
            "registry path changed"
        )
    if recorded_scope != expected_scope:
        raise IdentityMismatch(
            "the ledger scope is not the recorded one: ledger "
            f"{recorded_scope}, expected {expected_scope}"
        )
    audit = file_facts(resolution.model_audit_path)
    if not audit["present"]:
        raise IdentityMismatch(
            f"the model audit trail is absent at {resolution.model_audit_path}; the recorded "
            "round has one and the ledger/audit continuity link depends on it"
        )
    # Same guard the serving assembly runs: an existing audit trail next to an empty ledger
    # is treated as a rolled-back quota, not as a first initialization.
    verify_ledger_continuity(resolution.ledger_path, resolution.model_audit_path)
    return facts.as_payload(), recorded_scope


def check_registry(resolution: RealRuntimeAuthorization) -> dict[str, Any]:
    """The per-file authorization registry the ledger scope binds, read-only."""
    registry_path = resolution.registry_path
    assert registry_path is not None
    facts = file_facts(registry_path)
    if not facts["present"]:
        raise IdentityMismatch(
            f"the per-file authorization registry is absent at {registry_path}; the ledger "
            "scope binds this path, so an empty or missing file means the recorded approvals "
            "are gone"
        )
    allowed = resolution.allowed_documents
    facts["approved_documents"] = sorted(allowed)
    facts["approved_document_count"] = len(allowed)
    facts["environment_documents"] = sorted(resolution.environment_documents)
    return facts


def frozen_snapshot(corpus_root: Path) -> tuple[LegalIndex, str]:
    try:
        manifest = LegalManifest.model_validate_json(read_bounded(corpus_root, LEGAL_MANIFEST))
        index = ingest(corpus_root, manifest)
    except (OSError, ValueError) as exc:
        raise IdentityMismatch(f"the frozen legal corpus cannot be loaded: {exc}") from exc
    return index, index_hash(index)


def check_vector_index(
    *,
    private_root: Path,
    corpus_root: Path,
    publication_id: str,
    revision_id: str,
    build_id: str,
    expected_item_count: int,
    expected_source_item_count: int,
) -> dict[str, Any]:
    """The prebuilt index identity, its store row, its coverage and its cache links."""
    manifest_path = private_root / PREBUILT_MANIFEST_FILE
    if not manifest_path.is_file():
        raise IdentityMismatch(
            f"the prebuilt index manifest is absent at {manifest_path}; run "
            "scripts/prebuild_legal_vectors.py before the round"
        )
    raw = manifest_path.read_bytes()
    if len(raw) > MANIFEST_SIZE_LIMIT:
        raise IdentityMismatch("the prebuilt index manifest exceeds the size limit")
    try:
        manifest = VectorIndexManifest.model_validate_json(raw)
    except ValueError as exc:
        raise IdentityMismatch(
            f"the prebuilt index manifest is not a valid manifest: {exc}"
        ) from exc

    index, snapshot_sha256 = frozen_snapshot(corpus_root)
    source_item_count = len(index.clauses)
    if (manifest.publication_id, manifest.revision_id) != (publication_id, revision_id):
        raise IdentityMismatch(
            "the prebuilt index belongs to publication/revision "
            f"({manifest.publication_id}, {manifest.revision_id}), not to the recorded "
            f"({publication_id}, {revision_id})"
        )
    if manifest.build_id != build_id:
        raise IdentityMismatch(
            f"the prebuilt index build id is {manifest.build_id}, not the recorded {build_id}"
        )
    if manifest.legal_snapshot_sha256 != snapshot_sha256:
        raise IdentityMismatch(
            "the prebuilt index was built from a different legal snapshot than the frozen "
            f"corpus (index {manifest.legal_snapshot_sha256}, corpus {snapshot_sha256})"
        )
    if manifest.item_count != expected_item_count:
        raise IdentityMismatch(
            f"the prebuilt index holds {manifest.item_count} items, the frozen corpus "
            f"expects {expected_item_count}"
        )
    if manifest.source_item_count != source_item_count or source_item_count != (
        expected_source_item_count
    ):
        raise IdentityMismatch(
            f"the prebuilt index source_item_count is {manifest.source_item_count}, the frozen "
            f"corpus holds {source_item_count} and the recorded value is "
            f"{expected_source_item_count}"
        )
    if manifest.embedding_identity.parameters.get("execution_mode") != "online":
        raise IdentityMismatch(
            "the prebuilt index does not carry the online embedding identity of the recorded "
            "round (contract-test vectors cannot serve real retrieval)"
        )

    store = check_index_store(
        private_root / INDEX_FILE,
        build_id=build_id,
        manifest=manifest,
        expected_item_count=expected_item_count,
    )
    return {
        "manifest": file_facts(manifest_path),
        "publication_id": manifest.publication_id,
        "revision_id": manifest.revision_id,
        "build_id": manifest.build_id,
        "item_count": manifest.item_count,
        "source_item_count": manifest.source_item_count,
        "legal_snapshot_sha256": manifest.legal_snapshot_sha256,
        "embedding_identity_sha256": manifest.embedding_identity.identity_sha256,
        "embedding_execution_mode": manifest.embedding_identity.parameters.get("execution_mode"),
        **store,
    }


def check_index_store(
    store_path: Path,
    *,
    build_id: str,
    manifest: VectorIndexManifest,
    expected_item_count: int,
) -> dict[str, Any]:
    """Verify the durable store read-only: build row, item count, coverage, cache links."""
    if not store_path.is_file():
        raise IdentityMismatch(f"the prebuilt vector index store is absent at {store_path}")
    try:
        with sqlite3.connect(f"file:{store_path}?mode=ro", uri=True, timeout=5) as connection:
            build = connection.execute(
                "SELECT build_id, identity_sha256, legal_snapshot_sha256, publication_id, "
                "revision_id, status, item_count, source_item_count, coverage_sha256, "
                "manifest_sha256 FROM vector_build WHERE build_id=?",
                (build_id,),
            ).fetchone()
            if build is None:
                raise IdentityMismatch(
                    "the prebuilt vector index store does not hold the recorded build"
                )
            clause_rows = connection.execute(
                "SELECT clause_id FROM vector_index_item WHERE build_id=? ORDER BY clause_id",
                (build_id,),
            ).fetchall()
            orphaned = connection.execute(
                "SELECT COUNT(*) FROM vector_index_item AS item "
                "LEFT JOIN vector_cache AS cache ON cache.identity_sha256=? "
                "AND cache.law_id=item.law_id AND cache.legal_version=item.legal_version "
                "AND cache.clause_id=item.clause_id AND cache.text_sha256=item.text_sha256 "
                "AND cache.vector_sha256=item.vector_sha256 "
                "WHERE item.build_id=? AND cache.vector_sha256 IS NULL",
                (manifest.embedding_identity.identity_sha256, build_id),
            ).fetchone()
    except sqlite3.Error as exc:
        raise IdentityMismatch(f"the prebuilt vector index store is unreadable: {exc}") from exc
    expected_row = (
        manifest.build_id,
        manifest.embedding_identity.identity_sha256,
        manifest.legal_snapshot_sha256,
        manifest.publication_id,
        manifest.revision_id,
        "complete",
        manifest.item_count,
        manifest.source_item_count,
        manifest.coverage_sha256,
        manifest.manifest_sha256,
    )
    if tuple(build) != expected_row:
        raise IdentityMismatch(
            "the vector index store row disagrees with the manifest on identity, "
            "publication/revision, completeness, coverage or counts"
        )
    clause_ids = [row[0] for row in clause_rows]
    if len(clause_ids) != manifest.item_count or len(clause_ids) != expected_item_count:
        raise IdentityMismatch(
            f"the vector index store holds {len(clause_ids)} items while the recorded index "
            f"has {manifest.item_count} (expected {expected_item_count})"
        )
    if manifest.coverage_sha256 is None or canonical_hash(sorted(clause_ids)) != (
        manifest.coverage_sha256
    ):
        raise IdentityMismatch("the vector index coverage hash does not match its items")
    if orphaned is None or orphaned[0] != 0:
        raise IdentityMismatch(
            "the vector index has items without an intact cached vector; the durable vectors "
            "of the recorded round are incomplete"
        )
    return {
        "store": file_facts(store_path),
        "item_rows": len(clause_ids),
        "coverage_sha256": manifest.coverage_sha256,
        "items_without_cached_vector": 0,
    }


def check_database_publication(database_url: str) -> dict[str, Any]:
    """The current ``legal_publication`` row, read-only, when a database URL is given.

    PostgreSQL (the deployment) additionally runs the query in a read-only transaction; other
    dialects are only read through their own connection (the tests use SQLite).
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            row = connection.execute(
                text(
                    "SELECT publication_id, revision_id, sequence FROM legal_publication "
                    "ORDER BY sequence DESC LIMIT 1"
                )
            ).fetchone()
    finally:
        engine.dispose()
    if row is None:
        raise IdentityMismatch("the database holds no legal publication row")
    return {
        "publication_id": row[0],
        "revision_id": row[1],
        "sequence": int(row[2]),
    }


@dataclass(frozen=True, slots=True)
class IdentityReport:
    """Everything the read-only check observed; printed as JSON for the operator's record."""

    private_root: str
    authorization_id: str
    scope_sha256: str
    ledger_path: str
    model_audit_path: str
    registry_path: str
    ledger: Mapping[str, Any]
    registry: Mapping[str, Any]
    vector_index: Mapping[str, Any]
    database_publication: Mapping[str, Any] | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "private_root": self.private_root,
            "authorization_id": self.authorization_id,
            "scope_sha256": self.scope_sha256,
            "ledger_path": self.ledger_path,
            "model_audit_path": self.model_audit_path,
            "registry_path": self.registry_path,
            "ledger": dict(self.ledger),
            "registry": dict(self.registry),
            "vector_index": dict(self.vector_index),
            "database_publication": (
                None if self.database_publication is None else dict(self.database_publication)
            ),
        }

    @property
    def line(self) -> str:
        index = self.vector_index
        return (
            f"{IDENTITY_PASSED}: scope={self.scope_sha256} "
            f"publication={index['publication_id']} revision={index['revision_id']} "
            f"build_id={index['build_id']} item_count={index['item_count']} "
            f"source_item_count={index['source_item_count']}"
        )


def run_identity_check(
    *,
    environment: Mapping[str, str],
    private_root: Path | None = None,
    corpus_root: Path | None = None,
    expected_scope: str = "",
    publication_id: str = "",
    revision_id: str = "",
    build_id: str = "",
    expected_item_count: int | None = None,
    expected_source_item_count: int | None = None,
    database_url: str | None = None,
) -> IdentityReport:
    """Every read-only identity comparison; the first disagreement raises."""
    for name, value in (
        ("--expected-scope", expected_scope),
        ("--publication-id", publication_id),
        ("--revision-id", revision_id),
        ("--build-id", build_id),
    ):
        if not value.strip():
            raise IdentityMismatch(
                f"{name} is required: the check compares the recorded identities, it never "
                "invents them"
            )
    if len(expected_scope) != 64 or any(
        character not in "0123456789abcdef" for character in expected_scope
    ):
        raise IdentityMismatch("--expected-scope must be 64 lowercase hex characters")
    root = private_root if private_root is not None else PRIVATE_ROOT
    corpus = corpus_root if corpus_root is not None else ROOT
    resolution, scope = check_authorization(environment, private_root=root)
    if scope != expected_scope:
        raise IdentityMismatch(
            "the configuration binds a different scope than the recorded one: configuration "
            f"{scope}, expected {expected_scope} (authorization, tenant, environment allowlist "
            "or registry path changed, and the scope binds the registry path)"
        )
    ledger, recorded_scope = check_ledger_and_audit(resolution, expected_scope=expected_scope)
    registry = check_registry(resolution)
    vector_index = check_vector_index(
        private_root=root,
        corpus_root=corpus,
        publication_id=publication_id,
        revision_id=revision_id,
        build_id=build_id,
        expected_item_count=(
            expected_item_count if expected_item_count is not None else EXPECTED_ITEM_COUNT
        ),
        expected_source_item_count=(
            expected_source_item_count
            if expected_source_item_count is not None
            else EXPECTED_SOURCE_ITEM_COUNT
        ),
    )
    publication = check_database_publication(database_url) if database_url else None
    if publication is not None and (
        publication["publication_id"],
        publication["revision_id"],
    ) != (vector_index["publication_id"], vector_index["revision_id"]):
        raise IdentityMismatch(
            "the current legal publication in the database is not the one the prebuilt index "
            f"belongs to (database {publication['publication_id']}/"
            f"{publication['revision_id']}, index {vector_index['publication_id']}/"
            f"{vector_index['revision_id']})"
        )
    assert recorded_scope == expected_scope
    return IdentityReport(
        private_root=str(root.resolve()),
        authorization_id=resolution.authorization_id,
        scope_sha256=scope,
        ledger_path=str(resolution.ledger_path),
        model_audit_path=str(resolution.model_audit_path),
        registry_path=str(resolution.registry_path),
        ledger=ledger,
        registry=registry,
        vector_index=vector_index,
        database_publication=publication,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--private-root", type=Path, default=PRIVATE_ROOT)
    parser.add_argument("--corpus-root", type=Path, default=ROOT)
    parser.add_argument(
        "--expected-scope", default="", help="recorded DEC-007 ledger scope (64 lowercase hex)"
    )
    parser.add_argument("--publication-id", default="", help="recorded legal publication id")
    parser.add_argument("--revision-id", default="", help="recorded legal revision id")
    parser.add_argument("--build-id", default="", help="recorded vector index build id")
    parser.add_argument("--expected-item-count", type=int, default=None)
    parser.add_argument("--expected-source-item-count", type=int, default=None)
    parser.add_argument(
        "--database-url",
        default=None,
        help="optional read-only cross-check against legal_publication "
        "(default: $DATABASE_URL when set)",
    )
    parser.add_argument(
        "--print-scope",
        action="store_true",
        help="only resolve and print the identity paths and scope; the ledger is not read",
    )
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environment = dict(os.environ)
    if args.print_scope:
        try:
            resolution, scope = check_authorization(environment, private_root=args.private_root)
        except (IdentityMismatch, ValueError) as exc:
            print(f"STOP: {exc}", file=sys.stderr, flush=True)
            return 2
        payload = {
            "mode": "scope-only",
            "ledger_read": False,
            "private_root": str(args.private_root.resolve()),
            "authorization_id": resolution.authorization_id,
            "ledger_path": str(resolution.ledger_path),
            "model_audit_path": str(resolution.model_audit_path),
            "registry_path": str(resolution.registry_path),
            "scope_sha256": scope,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        print(
            "scope-only: the ledger was NOT read; this is the scope the current configuration "
            "binds."
        )
        return 0
    database_url = args.database_url or os.environ.get("DATABASE_URL", "") or None
    try:
        report = run_identity_check(
            environment=environment,
            private_root=args.private_root,
            corpus_root=args.corpus_root,
            expected_scope=args.expected_scope,
            publication_id=args.publication_id,
            revision_id=args.revision_id,
            build_id=args.build_id,
            expected_item_count=args.expected_item_count,
            expected_source_item_count=args.expected_source_item_count,
            database_url=database_url,
        )
    except (IdentityMismatch, ValueError) as exc:
        print(f"STOP: {exc}", file=sys.stderr, flush=True)
        print(
            "Stop and report. Do not delete, replace, reset or rebuild the ledger, the "
            "registry or the index to make this check pass.",
            file=sys.stderr,
            flush=True,
        )
        return 2
    if args.json:
        print(json.dumps(report.as_payload(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"private_root: {report.private_root}")
        print(f"authorization: {report.authorization_id}")
        print(f"ledger: {report.ledger_path}")
        print(f"model_audit: {report.model_audit_path}")
        print(f"registry: {report.registry_path}")
        print(f"scope_sha256: {report.scope_sha256}")
        print(f"legal publication: {report.vector_index['publication_id']}")
        print(f"legal revision: {report.vector_index['revision_id']}")
        print(f"vector build_id: {report.vector_index['build_id']}")
        print(
            f"vector coverage: {report.vector_index['item_count']}/"
            f"{report.vector_index['source_item_count']}"
        )
    print(report.line)
    print(
        "note: this check covers identities only; run scripts/task0027_ledger_baseline.py for "
        "the recorded ledger counters."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
