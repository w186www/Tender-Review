"""Isolated one-shot assembly for the TASK-0027 controlled real-model round.

Why this assembly exists
------------------------
``scripts/task0023_real_ai_app.py`` (``DEPLOY_REVIEW_MODE=authorized-real``) runs the
DEC-007 envelope exactly as authorized: LLM 300 calls / Embedding 800 batches / CNY 30. The
controlled round before the first paid call must spend far less, so this assembly is the
*same* server runtime -- same publication and revision, same embedding identity, same
authorization scope, same ``modelstate`` private root, same prebuilt-index requirement -- with
three ceilings tightened in code:

    LLM 4 calls, Embedding 322 batches (312 are already recorded), cumulative CNY 2
    (including the 0.1035070 CNY already settled)

They are cumulative ceilings on the shared DEC-007 ledger, not additional allowances, and
they live here as module constants: there is deliberately no environment variable, CLI
option or request field that can raise them, so neither an operator, an API caller nor a
demo account can widen this round. ``assert_round_limits_bounded`` additionally refuses an
assembly whose constants are not strictly tighter than ``AUTHORIZATION_LIMITS[DEC-007]``,
which stays 300/800/CNY 30.

Two operations, deliberately not fused
--------------------------------------
``--preflight`` performs every local/read-only precondition check and prints a JSON report;
it reserves nothing, writes nothing and can never reach a supplier. Serving the app runs the
same preflight first and exits non-zero instead of starting when a check fails.

Mandatory inputs (no default exists)
------------------------------------
``--publication-id`` and ``--revision-id`` are mandatory. The preflight compares them -- and
the prebuilt index manifest's ``legal_snapshot_sha256``, ``embedding_identity.identity_sha256``,
``item_count`` (3112 for the frozen corpus) and ``source_item_count`` (3120) -- with the
manifest the prebuild wrote into the ``modelstate`` volume (``vector-manifest.json``), and
with the frozen corpus and the embedding identity of this assembly. The matching build must
also be present and complete in the index store. Only then does the preflight print one
assertable line, ``prebuilt index verified build_id=... item_count=...``; a missing id, a
different publication/revision, a different snapshot, a different embedding identity or a
different count refuses the round instead of degrading to a "not pinned" run.

``--online-api-offline-verified`` keeps its meaning as the operator's confirmation, but it is
no longer sufficient by itself: the preflight additionally requires a *fresh* host evidence
document with ``verdict: "ok"`` produced by ``deploy/verify_api_offline_mode.sh``
(``--host-offline-evidence <path>``, at most ``--host-offline-evidence-max-age-seconds`` old,
default 600s), whose api container id and compose project match the current deployment
(``DEC007_API_CONTAINER_ID`` / ``--api-container-id`` and ``DEPLOY_COMPOSE_PROJECT`` /
``--compose-project``). A missing, stale, ``unknown`` or ``untrusted`` evidence document, or
a flag without any evidence, refuses the round.

Boundary of this design (option A, agreed 2026-10-16)
-----------------------------------------------------
The ledger file carries counters only; the ceilings are per-process parameters. A different
process that opens the *same* ledger with the wider authorization ceilings is therefore
technically possible, and this module does not claim a cross-process global tightening
lock. What this round guarantees is: the counters are shared and cumulative in one file, the
serving assemblies of this round cannot be widened, and the operator confirms before
starting that the public API is still ``offline`` and that no other authorized-real process
holds the DEC-007 ledger. The confirmation is now backed by machine-checked host evidence
(freshness, effective ``DEPLOY_REVIEW_MODE`` of the running api container, image/entrypoint,
absence of a second authorized-real instance, matching container id and project), but that
evidence is content, not a signature: whoever may run the host script may also write such a
file, so the operator stays trusted. Only one real-model validation instance may run.

Usage inside a one-off container built under its own image tag (never ``:demo``)::

    IMAGE_TAG=task0027-validation $D build api
    $D run --rm --no-deps api python scripts/task0027_ledger_baseline.py
    $D run --rm --no-deps api python deploy/verify_api_offline_mode.py --help   # host side
    $D run --rm --no-deps -v <evidence-dir>:/evidence:ro api \
        python scripts/task0027_real_ai_validation_app.py --preflight \
        --publication-id <id> --revision-id <id> --online-api-offline-verified \
        --host-offline-evidence /evidence/api-offline-<timestamp>.json

See ``deploy/README-demo.md`` ("本轮受控验证") for the ordered operator steps.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "src"), str(ROOT / "deploy")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import httpx  # noqa: E402
import task0027_ledger_baseline as ledger_baseline  # noqa: E402
import verify_api_offline_mode as host_evidence  # noqa: E402  (stdlib-only host helper)
from sqlalchemy.orm import sessionmaker  # noqa: E402

from bidding_compliance.api import create_app  # noqa: E402
from bidding_compliance.core.config import Settings  # noqa: E402
from bidding_compliance.legal.contracts import LegalIndex, LegalManifest  # noqa: E402
from bidding_compliance.legal.corpus import index_hash, ingest, read_bounded  # noqa: E402
from bidding_compliance.legal.embedding_provider import DashScopeEmbeddingProvider  # noqa: E402
from bidding_compliance.legal.hashing import canonical_hash  # noqa: E402
from bidding_compliance.legal.vector_index import VectorIndexManifest  # noqa: E402
from bidding_compliance.model_gateway.authorized_runtime import (  # noqa: E402
    AUTHORIZATION_LIMITS,
    FULL_CAPABILITY_AUTHORIZATION_ID,
)
from bidding_compliance.persistence.database import make_engine  # noqa: E402
from bidding_compliance.services.real_ai_runtime import (  # noqa: E402
    REAL_RUNTIME_TENANT_ID,
    SEMANTIC_PROMPT_VERSION,
    AuthorizedRealReviewEngine,
    RealRuntimeAuthorization,
    create_dec005_gateway,
    real_ai_policy,
    resolve_real_runtime_authorization,
)
from bidding_compliance.services.real_embedding_runtime import (  # noqa: E402
    EMBEDDING_INPUT_PRICE_PER_MILLION,
    authorized_vector_plan,
    create_real_retriever_factory,
    real_embedding_settings,
)

# The one private root the server assemblies use inside the read-write modelstate volume:
# ledger, model audit, per-file registry and the prebuilt vector index all live here.
# Inside the container this is ``/app/.verification/private``, the modelstate volume root
# (``docker-compose.demo.yml`` mounts ``modelstate:/app/.verification/private``), which is
# where the recorded phase-one round keeps its ledger, registry and index. It is the same
# root ``scripts/task0023_real_ai_app.py`` uses, so the official API and this round read the
# identical files and the identical ledger scope.
PRIVATE_ROOT = ROOT / ".verification" / "private"
LEGAL_MANIFEST = "config/legal/manifest.json"
INDEX_FILE = "legal-vectors.sqlite3"
# The index manifest the prebuild wrote into the same volume: the signed-in-content record of
# which publication, revision, snapshot, embedding identity and counts the index holds.
PREBUILT_MANIFEST_FILE = "vector-manifest.json"
# The frozen authorized corpus: 3120 clauses, 3112 of them within the per-item byte ceiling.
# A different corpus is a corpus change and must be re-measured, never silently accepted.
EXPECTED_PREBUILT_ITEM_COUNT = 3112
EXPECTED_PREBUILT_SOURCE_ITEM_COUNT = 3120
PREBUILT_INDEX_VERIFIED = "prebuilt index verified"
ONLINE_API_URL_VARIABLE = "DEC007_ONLINE_API_URL"
DEFAULT_ONLINE_API_URL = "http://api:8000"
HEALTH_PATH = "/api/v1/health"
# Where the current deployment identity comes from: the operator reads the api container id
# from the host and the project name is injected by docker-compose.demo.yml.
API_CONTAINER_ID_VARIABLE = "DEC007_API_CONTAINER_ID"
COMPOSE_PROJECT_VARIABLE = "DEPLOY_COMPOSE_PROJECT"
HOST_OFFLINE_EVIDENCE_VARIABLE = "DEC007_HOST_OFFLINE_EVIDENCE"
HOST_OFFLINE_EVIDENCE_MAX_AGE_VARIABLE = "DEC007_HOST_OFFLINE_EVIDENCE_MAX_AGE_SECONDS"
HOST_OFFLINE_EVIDENCE_DEFAULT_MAX_AGE_SECONDS = 600
HOST_OFFLINE_EVIDENCE_MAX_AGE_CEILING_SECONDS = 3600
MANIFEST_SIZE_LIMIT = 1_000_000

# This round's hard ceilings, fixed in the trusted server-side assembly (see the module
# docstring). Changing them is a reviewed code change, never an operator configuration.
ROUND_LLM_LIMIT = 4
ROUND_EMBEDDING_LIMIT = 322
ROUND_TOTAL_CNY = Decimal("2")

# The commands whose result the operator confirms with --online-api-offline-verified, now
# backed by the evidence file deploy/verify_api_offline_mode.sh writes.
OPERATOR_OFFLINE_COMMANDS = (
    "bash deploy/verify_api_offline_mode.sh --evidence-dir /opt/tender-review-private/evidence"
    "   # verdict must be: ok",
    "docker compose --env-file deploy/.env -f docker-compose.demo.yml exec api "
    "printenv DEPLOY_REVIEW_MODE   # must print: offline",
    "docker compose --env-file deploy/.env -f docker-compose.demo.yml ps   "
    "# no second DEC-007 instance",
)


class PreflightFailed(RuntimeError):
    """A precondition of the controlled round is not met; never continue to a call."""


@dataclass(frozen=True, slots=True)
class RoundLimits:
    """This round's ceilings; cumulative on the shared DEC-007 ledger."""

    llm_limit: int
    embedding_limit: int
    total_cny: Decimal


def round_limits() -> RoundLimits:
    """The round ceilings as constants of this trusted assembly (no env, no argument)."""
    return RoundLimits(
        llm_limit=ROUND_LLM_LIMIT,
        embedding_limit=ROUND_EMBEDDING_LIMIT,
        total_cny=ROUND_TOTAL_CNY,
    )


def assert_round_limits_bounded(limits: RoundLimits) -> RoundLimits:
    """Refuse a round that is not strictly tighter than the DEC-007 authorization itself."""
    hard = AUTHORIZATION_LIMITS[FULL_CAPABILITY_AUTHORIZATION_ID]
    if (
        not 0 <= limits.llm_limit < hard["llm"]
        or not 0 <= limits.embedding_limit < hard["embedding"]
        or not 0 <= limits.total_cny < hard["cny"]
    ):
        raise ValueError(
            "the controlled round must stay strictly tighter than the DEC-007 authorization "
            f"({hard['llm']}/{hard['embedding']}/{hard['cny']})"
        )
    return limits


@dataclass(frozen=True, slots=True)
class PrebuiltIndexVerification:
    """The manifest identity of the prebuilt index this round is allowed to reuse."""

    manifest_path: str
    build_id: str
    item_count: int
    source_item_count: int
    publication_id: str
    revision_id: str
    legal_snapshot_sha256: str
    identity_sha256: str

    @property
    def line(self) -> str:
        """The one assertable line a passing preflight prints."""
        return (
            f"{PREBUILT_INDEX_VERIFIED} build_id={self.build_id} "
            f"item_count={self.item_count} source_item_count={self.source_item_count} "
            f"publication={self.publication_id} revision={self.revision_id}"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "manifest_path": self.manifest_path,
            "build_id": self.build_id,
            "item_count": self.item_count,
            "source_item_count": self.source_item_count,
            "publication_id": self.publication_id,
            "revision_id": self.revision_id,
            "legal_snapshot_sha256": self.legal_snapshot_sha256,
            "identity_sha256": self.identity_sha256,
            "line": self.line,
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Everything checked before the round may serve; printed as JSON for the audit."""

    authorization_id: str
    tenant_id: str
    ledger_path: str
    audit_path: str
    registry_path: str | None
    scope_sha256: str
    llm_limit: int
    embedding_limit: int
    total_cny: str
    operator_offline_confirmed: bool
    ledger: Mapping[str, Any]
    approved_documents: Mapping[str, Any]
    host_offline_evidence: Mapping[str, Any]
    prebuilt_index: Mapping[str, Any]
    online_api: Mapping[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "tenant_id": self.tenant_id,
            "ledger_path": self.ledger_path,
            "audit_path": self.audit_path,
            "registry_path": self.registry_path,
            "scope_sha256": self.scope_sha256,
            "round_limits": {
                "llm_limit": self.llm_limit,
                "embedding_limit": self.embedding_limit,
                "total_cny": self.total_cny,
            },
            "operator_offline_confirmed": self.operator_offline_confirmed,
            "ledger": dict(self.ledger),
            "approved_documents": dict(self.approved_documents),
            "host_offline_evidence": dict(self.host_offline_evidence),
            "prebuilt_index": dict(self.prebuilt_index),
            "online_api": dict(self.online_api),
        }


@dataclass(frozen=True, slots=True)
class PreflightOutcome:
    report: PreflightReport
    resolution: RealRuntimeAuthorization


def probe_online_api(base_url: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Read-only health probe of the public stack; a failure means "state unknown, stop"."""
    owns_client = client is None
    probe = client or make_probe_client()
    url = f"{base_url.rstrip('/')}{HEALTH_PATH}"
    try:
        response = probe.get(url)
        status = response.status_code
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise PreflightFailed(f"the public API health probe returned no JSON: {url}") from exc
    except httpx.HTTPError as exc:
        raise PreflightFailed(
            f"the public API is not reachable at {url}; its review mode cannot be confirmed"
        ) from exc
    finally:
        if owns_client:
            probe.close()
    if status != 200 or not isinstance(payload, dict) or payload.get("status") != "ok":
        raise PreflightFailed(f"the public API health probe failed: {url} -> {status} {payload!r}")
    return {"url": url, "status_code": status, "payload": payload}


def make_probe_client() -> httpx.Client:
    """The client the health probe uses; tests replace it with a synthetic transport."""
    return httpx.Client(trust_env=False, follow_redirects=False, timeout=5)


def _credential(environment: Mapping[str, str], name: str) -> str:
    value = (environment.get(name) or "").strip()
    if not value:
        raise PreflightFailed(
            f"{name} is required for the controlled round; without it no supplier call is possible"
        )
    return value


def _environment_reference(environment: Mapping[str, str], name: str, option: str) -> str:
    """A required current-deployment fact: explicit option first, environment second."""
    value = (environment.get(name) or "").strip()
    if not value:
        raise PreflightFailed(
            f"the current deployment identity is incomplete: pass {option} or set {name} "
            "(the value is read from the host, e.g. `docker compose ... ps -q api`)"
        )
    return value


class _NoEgressGuard:
    """Refuses every reservation: the preflight may inspect, never spend."""

    def reserve_external(self, *, kind: str, request_hash: str, ceiling: Decimal) -> str:
        raise PermissionError("the preflight never reserves a supplier request")

    def settle_external(self, reservation: str, actual: Decimal) -> None:
        raise PermissionError("the preflight never settles a supplier request")


def _embedding_provider(environment: Mapping[str, str]) -> tuple[DashScopeEmbeddingProvider, Any]:
    """The identity-carrying provider of this assembly, without any supplier request.

    Constructing it performs no I/O; every request would need both the no-egress guard and
    the client, so the preflight can only ever read ``identity``/``max_batch_items``.
    """
    key = _credential(environment, "DASHSCOPE_API_KEY")
    workspace = _credential(environment, "BAILIAN_WORKSPACE_ID")
    client = httpx.Client(trust_env=False, follow_redirects=False, timeout=20)
    provider = DashScopeEmbeddingProvider(
        real_embedding_settings(api_key=key, workspace_id=workspace),
        client=client,
        guard=_NoEgressGuard(),
        audit_sink=lambda event: None,
        input_price_per_million=EMBEDDING_INPUT_PRICE_PER_MILLION,
    )
    return provider, client


def _read_only_index_store(
    store_path: Path,
    *,
    manifest: Any,
    expected_coverage_sha256: str,
) -> None:
    """Verify the durable index store against the manifest, read-only.

    The store is opened with SQLite's ``mode=ro`` URI: the file is never created and never
    written, so a missing or damaged index is reported instead of being "repaired".
    """
    if not store_path.is_file():
        raise PreflightFailed(
            f"the prebuilt vector index store is absent at {store_path}; run "
            "scripts/prebuild_legal_vectors.py before the round"
        )
    try:
        with sqlite3.connect(f"file:{store_path}?mode=ro", uri=True, timeout=5) as connection:
            build = connection.execute(
                "SELECT build_id, identity_sha256, legal_snapshot_sha256, publication_id, "
                "revision_id, status, item_count, source_item_count, coverage_sha256, "
                "manifest_sha256 FROM vector_build WHERE build_id=?",
                (manifest.build_id,),
            ).fetchone()
            items = connection.execute(
                "SELECT COUNT(*) FROM vector_index_item WHERE build_id=?",
                (manifest.build_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise PreflightFailed(f"the prebuilt vector index store is unreadable: {exc}") from exc
    if build is None:
        raise PreflightFailed("the prebuilt vector index store does not hold this manifest build")
    expected = (
        manifest.build_id,
        manifest.embedding_identity.identity_sha256,
        manifest.legal_snapshot_sha256,
        manifest.publication_id,
        manifest.revision_id,
        "complete",
        manifest.item_count,
        manifest.source_item_count,
        expected_coverage_sha256,
        manifest.manifest_sha256,
    )
    if tuple(build) != expected:
        raise PreflightFailed(
            "the prebuilt vector index store disagrees with the manifest on identity, "
            "publication/revision, completeness, coverage or counts"
        )
    if items is None or items[0] != manifest.item_count:
        raise PreflightFailed(
            "the prebuilt vector index store does not hold every item of this manifest"
        )


def verify_prebuilt_index(
    *,
    environment: Mapping[str, str],
    private_root: Path,
    publication_id: str,
    revision_id: str,
    corpus_root: Path,
    expected_item_count: int | None = None,
    expected_source_item_count: int | None = None,
) -> PrebuiltIndexVerification:
    """Refuse the round unless the prebuilt index identity matches this deployment exactly.

    The passed publication/revision are compared with the values recorded in the index
    manifest inside the ``modelstate`` volume, and the manifest's snapshot hash, embedding
    identity, item count and source count are compared with the frozen corpus and with the
    counts this round pins. Any difference exits non-zero before a supplier request exists.
    """
    if not publication_id.strip() or not revision_id.strip():
        raise PreflightFailed(
            "--publication-id and --revision-id are required: the whole point of this round is "
            "that the reused index is pinned to one legal publication and revision. There is no "
            "default and no 'not pinned' mode."
        )
    item_ceiling = (
        expected_item_count if expected_item_count is not None else EXPECTED_PREBUILT_ITEM_COUNT
    )
    source_ceiling = (
        expected_source_item_count
        if expected_source_item_count is not None
        else EXPECTED_PREBUILT_SOURCE_ITEM_COUNT
    )
    manifest_path = private_root / PREBUILT_MANIFEST_FILE
    if not manifest_path.is_file():
        raise PreflightFailed(
            f"the prebuilt index manifest is absent at {manifest_path}; the online API reuses "
            "the index written by scripts/prebuild_legal_vectors.py and this round does not "
            "build one"
        )
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise PreflightFailed(f"the prebuilt index manifest is unreadable: {exc}") from exc
    if len(raw) > MANIFEST_SIZE_LIMIT:
        raise PreflightFailed("the prebuilt index manifest exceeds the size limit")
    try:
        manifest = VectorIndexManifest.model_validate_json(raw)
    except ValueError as exc:
        raise PreflightFailed(
            f"the prebuilt index manifest is not a valid manifest: {exc}"
        ) from exc

    try:
        legal_manifest = LegalManifest.model_validate_json(
            read_bounded(corpus_root, LEGAL_MANIFEST)
        )
        index: LegalIndex = ingest(corpus_root, legal_manifest)
    except (OSError, ValueError) as exc:
        raise PreflightFailed(f"the frozen legal corpus cannot be loaded: {exc}") from exc

    provider, client = _embedding_provider(environment)
    try:
        settings = provider.settings
        plan = authorized_vector_plan(
            index,
            max_items=provider.max_batch_items,
            max_item_bytes=settings.max_text_utf8_bytes,
            max_batch_bytes=settings.max_batch_utf8_bytes,
        )
        identity_sha256 = provider.identity.identity_sha256
    finally:
        client.close()
    if not plan.clause_ids:
        raise PreflightFailed("the frozen legal corpus has no embeddable clause")

    snapshot_sha256 = index_hash(index)
    source_item_count = len(index.clauses)
    if (manifest.publication_id, manifest.revision_id) != (publication_id, revision_id):
        raise PreflightFailed(
            "the prebuilt index belongs to publication/revision "
            f"({manifest.publication_id}, {manifest.revision_id}), not to the requested "
            f"({publication_id}, {revision_id})"
        )
    if manifest.legal_snapshot_sha256 != snapshot_sha256:
        raise PreflightFailed(
            "the prebuilt index was built from a different legal snapshot than the frozen "
            "corpus of this assembly"
        )
    if manifest.embedding_identity.identity_sha256 != identity_sha256:
        raise PreflightFailed(
            "the prebuilt index uses a different embedding identity than this assembly"
        )
    if manifest.item_count != plan.item_count or plan.item_count != item_ceiling:
        raise PreflightFailed(
            f"the prebuilt index item_count is {manifest.item_count}, the frozen corpus plans "
            f"{plan.item_count} and this round pins {item_ceiling}"
        )
    if (
        manifest.source_item_count != source_item_count
        or source_item_count != source_ceiling
    ):
        raise PreflightFailed(
            f"the prebuilt index source_item_count is {manifest.source_item_count}, the frozen "
            f"corpus holds {source_item_count} and this round pins {source_ceiling}"
        )
    _read_only_index_store(
        private_root / INDEX_FILE,
        manifest=manifest,
        expected_coverage_sha256=canonical_hash(sorted(plan.clause_ids)),
    )
    return PrebuiltIndexVerification(
        manifest_path=str(manifest_path),
        build_id=manifest.build_id,
        item_count=manifest.item_count,
        source_item_count=int(manifest.source_item_count or 0),
        publication_id=publication_id,
        revision_id=revision_id,
        legal_snapshot_sha256=manifest.legal_snapshot_sha256,
        identity_sha256=identity_sha256,
    )


def verify_host_offline_evidence(
    *,
    environment: Mapping[str, str],
    path: Path | str | None,
    max_age_seconds: int | None,
    api_container_id: str | None,
    compose_project: str | None,
    now: datetime | None = None,
) -> host_evidence.HostOfflineEvidence:
    """Require the fresh host evidence that the operator flag can no longer replace."""
    evidence_path = (
        path if path is not None else environment.get(HOST_OFFLINE_EVIDENCE_VARIABLE, "")
    )
    window = (
        max_age_seconds
        if max_age_seconds is not None
        else _evidence_window_from_environment(environment)
    )
    current_container = (
        api_container_id
        if api_container_id is not None
        else _environment_reference(environment, API_CONTAINER_ID_VARIABLE, "--api-container-id")
    )
    current_project = (
        compose_project
        if compose_project is not None
        else _environment_reference(environment, COMPOSE_PROJECT_VARIABLE, "--compose-project")
    )
    try:
        return host_evidence.load_evidence(
            evidence_path,
            max_age_seconds=window,
            expected_api_container_id=current_container,
            expected_compose_project=current_project,
            now=now,
        )
    except host_evidence.EvidenceRejected as exc:
        raise PreflightFailed(f"the host offline evidence is not acceptable: {exc}") from exc


def _evidence_window_from_environment(environment: Mapping[str, str]) -> int:
    raw = (environment.get(HOST_OFFLINE_EVIDENCE_MAX_AGE_VARIABLE) or "").strip()
    if not raw:
        return HOST_OFFLINE_EVIDENCE_DEFAULT_MAX_AGE_SECONDS
    try:
        window = int(raw)
    except ValueError as exc:
        raise PreflightFailed(
            f"{HOST_OFFLINE_EVIDENCE_MAX_AGE_VARIABLE} must be an integer number of seconds"
        ) from exc
    if not 60 <= window <= HOST_OFFLINE_EVIDENCE_MAX_AGE_CEILING_SECONDS:
        raise PreflightFailed(
            f"{HOST_OFFLINE_EVIDENCE_MAX_AGE_VARIABLE} must stay within 60.."
            f"{HOST_OFFLINE_EVIDENCE_MAX_AGE_CEILING_SECONDS} seconds"
        )
    return window


def run_preflight(
    *,
    environment: Mapping[str, str],
    private_root: Path | None = None,
    online_api_url: str | None = None,
    online_api_offline_verified: bool = False,
    publication_id: str = "",
    revision_id: str = "",
    client: httpx.Client | None = None,
    corpus_root: Path | None = None,
    expected_item_count: int | None = None,
    expected_source_item_count: int | None = None,
    host_offline_evidence: Path | str | None = None,
    host_offline_evidence_max_age_seconds: int | None = None,
    api_container_id: str | None = None,
    compose_project: str | None = None,
    now: datetime | None = None,
) -> PreflightOutcome:
    """Every precondition of the round, all local or read-only, before any supplier call.

    Refuses (``PreflightFailed``) instead of degrading: a missing ledger, a ledger whose
    counters or scope differ from the recorded baseline, a missing id, a prebuilt index of a
    different identity, an unreachable public API, a missing operator confirmation, missing,
    stale or untrusted host evidence all stop the round. All local checks run before the
    single read-only network probe, so a refusal never depends on the network.
    """
    root = private_root if private_root is not None else PRIVATE_ROOT
    corpus = corpus_root if corpus_root is not None else ROOT
    limits = assert_round_limits_bounded(round_limits())
    explicit = (environment.get("DEC007_AUTHORIZATION_ID") or "").strip()
    if explicit != FULL_CAPABILITY_AUTHORIZATION_ID:
        raise PreflightFailed(
            "the controlled round runs under the DEC-007 authorization "
            f"({FULL_CAPABILITY_AUTHORIZATION_ID}); DEC007_AUTHORIZATION_ID is {explicit!r}"
        )
    _credential(environment, "DASHSCOPE_API_KEY")
    _credential(environment, "BAILIAN_WORKSPACE_ID")
    resolution = resolve_real_runtime_authorization(environment, private_root=root)

    facts = ledger_baseline.read_ledger_facts(
        resolution.ledger_path, authorization_id=resolution.authorization_id
    )
    try:
        ledger_baseline.check_baseline(
            resolution.ledger_path,
            authorization_id=resolution.authorization_id,
            expected=ledger_baseline.ROUND_BASELINE,
        )
    except ledger_baseline.BaselineCheckFailed as exc:
        raise PreflightFailed(
            f"{exc}. Stop the round and report; do not delete, replace or reset the ledger."
        ) from exc
    if facts.scope_sha256 != resolution.scope_sha256:
        raise PreflightFailed(
            "the DEC-007 ledger belongs to a different authorization scope than this "
            "assembly (authorization, allowlist or registry path changed)"
        )

    if not online_api_offline_verified:
        raise PreflightFailed(
            "operator confirmation missing: verify that the public API is still offline and "
            "that no other authorized-real process uses the DEC-007 ledger, then pass "
            "--online-api-offline-verified. Commands: " + " | ".join(OPERATOR_OFFLINE_COMMANDS)
        )
    accepted_evidence = verify_host_offline_evidence(
        environment=environment,
        path=host_offline_evidence,
        max_age_seconds=host_offline_evidence_max_age_seconds,
        api_container_id=api_container_id,
        compose_project=compose_project,
        now=now,
    )
    index_verification = verify_prebuilt_index(
        environment=environment,
        private_root=root,
        publication_id=publication_id,
        revision_id=revision_id,
        corpus_root=corpus,
        expected_item_count=expected_item_count,
        expected_source_item_count=expected_source_item_count,
    )

    target_url = (
        online_api_url
        or environment.get(ONLINE_API_URL_VARIABLE, "").strip()
        or DEFAULT_ONLINE_API_URL
    )
    online_api = probe_online_api(target_url, client=client)

    approved = resolution.allowed_documents
    report = PreflightReport(
        authorization_id=resolution.authorization_id,
        tenant_id=REAL_RUNTIME_TENANT_ID,
        ledger_path=str(resolution.ledger_path),
        audit_path=str(resolution.model_audit_path),
        registry_path=str(resolution.registry_path) if resolution.registry_path else None,
        scope_sha256=resolution.scope_sha256,
        llm_limit=limits.llm_limit,
        embedding_limit=limits.embedding_limit,
        total_cny=str(limits.total_cny),
        operator_offline_confirmed=online_api_offline_verified,
        ledger=facts.as_payload(),
        approved_documents={"count": len(approved), "sha256": sorted(approved)},
        host_offline_evidence=accepted_evidence.as_payload(),
        prebuilt_index=index_verification.as_payload(),
        online_api=online_api,
    )
    return PreflightOutcome(report=report, resolution=resolution)


def build_app(
    *,
    environment: Mapping[str, str],
    private_root: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    client: httpx.Client | None = None,
    online_api_url: str | None = None,
    online_api_offline_verified: bool = False,
    publication_id: str = "",
    revision_id: str = "",
    host_offline_evidence: Path | str | None = None,
    host_offline_evidence_max_age_seconds: int | None = None,
    api_container_id: str | None = None,
    compose_project: str | None = None,
    corpus_root: Path | None = None,
    expected_item_count: int | None = None,
    expected_source_item_count: int | None = None,
) -> tuple[Any, PreflightOutcome]:
    """The serving assembly: the online runtime with this round's tightened ceilings.

    ``allow_build`` is fixed to False here: the round reuses the prebuilt index in the
    shared modelstate volume and refuses a review (zero supplier calls, zero ledger
    consumption) when it is missing, instead of embedding the corpus synchronously.
    """
    root = private_root if private_root is not None else PRIVATE_ROOT
    outcome = run_preflight(
        environment=environment,
        private_root=root,
        online_api_url=online_api_url,
        online_api_offline_verified=online_api_offline_verified,
        publication_id=publication_id,
        revision_id=revision_id,
        client=client,
        corpus_root=corpus_root,
        expected_item_count=expected_item_count,
        expected_source_item_count=expected_source_item_count,
        host_offline_evidence=host_offline_evidence,
        host_offline_evidence_max_age_seconds=host_offline_evidence_max_age_seconds,
        api_container_id=api_container_id,
        compose_project=compose_project,
    )
    key = _credential(environment, "DASHSCOPE_API_KEY")
    workspace = _credential(environment, "BAILIAN_WORKSPACE_ID")
    limits = assert_round_limits_bounded(round_limits())
    resolution = outcome.resolution
    document_source = resolution.allowed_document_source
    gateway, authorization, budget = create_dec005_gateway(
        api_key=key,
        workspace_id=workspace,
        tenant_id=REAL_RUNTIME_TENANT_ID,
        allowed_document_sha256=document_source,
        ledger_path=resolution.ledger_path,
        audit_path=resolution.model_audit_path,
        authorization_id=resolution.authorization_id,
        scope_documents=resolution.environment_documents,
        authorization_registry=resolution.registry_path,
        llm_limit=limits.llm_limit,
        embedding_limit=limits.embedding_limit,
        total_cny=limits.total_cny,
        transport=transport,
    )
    settings = Settings(_env_file=None)
    database = make_engine(settings)
    review_engine = AuthorizedRealReviewEngine(
        settings=settings,
        session_factory=sessionmaker(database, expire_on_commit=False),
        gateway=gateway,
        model_policy=real_ai_policy(),
        legal_root=ROOT,
        authorization=authorization,
        allowed_document_sha256=document_source,
        retriever_factory=create_real_retriever_factory(
            api_key=key,
            workspace_id=workspace,
            budget=budget,
            private_root=root,
            allow_build=False,
        ),
    )
    app = create_app(settings, review_engine=review_engine)
    app.state.deploy_review_mode = "task0027-validation"
    app.state.review_prompt_version = SEMANTIC_PROMPT_VERSION
    app.state.external_budget = budget
    app.state.authorization_id = resolution.authorization_id
    app.state.authorized_document_count = len(resolution.allowed_documents)
    return app, outcome


def build_parser() -> argparse.ArgumentParser:
    """Only preflight controls exist: there is no option that can widen the ceilings.

    ``--publication-id`` and ``--revision-id`` are mandatory: the reused index must be
    pinned to one legal publication and revision, and the preflight compares both with the
    index manifest in the ``modelstate`` volume. The current deployment identity and the
    host evidence complete the mandatory operator inputs.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="run every check, print the report and exit; serve nothing, reserve nothing",
    )
    parser.add_argument(
        "--publication-id",
        required=True,
        help="legal publication of the prebuilt index (no default exists)",
    )
    parser.add_argument(
        "--revision-id",
        required=True,
        help="legal revision of the prebuilt index (no default exists)",
    )
    parser.add_argument(
        "--online-api-offline-verified",
        action="store_true",
        help="operator confirmation that the public API is offline and no other "
        "authorized-real process uses the DEC-007 ledger (still required, no longer enough)",
    )
    parser.add_argument(
        "--host-offline-evidence",
        default=None,
        help="fresh host evidence JSON produced by deploy/verify_api_offline_mode.sh "
        "(default: $DEC007_HOST_OFFLINE_EVIDENCE)",
    )
    parser.add_argument(
        "--host-offline-evidence-max-age-seconds",
        type=int,
        default=None,
        help=f"freshness window of the evidence (default: "
        f"${HOST_OFFLINE_EVIDENCE_MAX_AGE_VARIABLE} or "
        f"{HOST_OFFLINE_EVIDENCE_DEFAULT_MAX_AGE_SECONDS})",
    )
    parser.add_argument(
        "--api-container-id",
        default=None,
        help="current api container id from the host (default: $DEC007_API_CONTAINER_ID)",
    )
    parser.add_argument(
        "--compose-project",
        default=None,
        help="current compose project (default: $DEPLOY_COMPOSE_PROJECT)",
    )
    parser.add_argument("--online-api-url", default=None, help="health probe target")
    parser.add_argument(
        "--host",
        # Inside the container the app must listen on every interface, otherwise docker
        # compose run -p cannot forward to it; only the *host* loopback port is published.
        default="0.0.0.0",  # noqa: S104 - one-off container, published on 127.0.0.1 only
        help="bind address of the validation API inside its one-off container",
    )
    parser.add_argument("--port", type=int, default=8000, help="bind port of the validation API")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environment = dict(os.environ)
    try:
        if args.preflight:
            outcome = run_preflight(
                environment=environment,
                online_api_url=args.online_api_url,
                online_api_offline_verified=args.online_api_offline_verified,
                publication_id=args.publication_id,
                revision_id=args.revision_id,
                host_offline_evidence=args.host_offline_evidence,
                host_offline_evidence_max_age_seconds=(
                    args.host_offline_evidence_max_age_seconds
                ),
                api_container_id=args.api_container_id,
                compose_project=args.compose_project,
            )
            print(
                json.dumps(
                    outcome.report.as_payload(), ensure_ascii=False, indent=2, sort_keys=True
                )
            )
            # One assertable line: the index identity was compared with the manifest.
            print(outcome.report.prebuilt_index["line"])
            print("PASS: preflight complete; nothing was reserved, sent or written.")
            return 0
        app, outcome = build_app(
            environment=environment,
            online_api_url=args.online_api_url,
            online_api_offline_verified=args.online_api_offline_verified,
            publication_id=args.publication_id,
            revision_id=args.revision_id,
            host_offline_evidence=args.host_offline_evidence,
            host_offline_evidence_max_age_seconds=args.host_offline_evidence_max_age_seconds,
            api_container_id=args.api_container_id,
            compose_project=args.compose_project,
        )
    except PreflightFailed as exc:
        print(f"STOP: {exc}", file=sys.stderr, flush=True)
        return 2
    report = outcome.report
    print(
        "controlled validation round: "
        f"authorization={report.authorization_id} llm<={report.llm_limit} "
        f"embedding<={report.embedding_limit} cumulative_cny<={report.total_cny} "
        f"ledger={report.ledger_path} registry={report.registry_path} "
        f"approved_documents={report.approved_documents['count']}",
        file=sys.stderr,
        flush=True,
    )
    print(report.prebuilt_index["line"], file=sys.stderr, flush=True)
    print(
        json.dumps(outcome.report.as_payload(), ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
    )
    import uvicorn

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
