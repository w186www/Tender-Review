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

Boundary of this design (option A, agreed 2026-10-16)
-----------------------------------------------------
The ledger file carries counters only; the ceilings are per-process parameters. A different
process that opens the *same* ledger with the wider authorization ceilings is therefore
technically possible, and this module does not claim a cross-process global tightening
lock. What this round guarantees is: the counters are shared and cumulative in one file, the
serving assemblies of this round cannot be widened, and the operator confirms before
starting that the public API is still ``offline`` and that no other authorized-real process
holds the DEC-007 ledger (the file-aware checks below can only see finished or in-flight
requests, not a live idle process). Only one real-model validation instance may run.

Usage inside a one-off container built under its own image tag (never ``:demo``)::

    IMAGE_TAG=task0027-validation $D build api
    $D run --rm --no-deps api python scripts/task0027_ledger_baseline.py
    $D run --rm --no-deps -p 127.0.0.1:8123:8000 api \
        python scripts/task0027_real_ai_validation_app.py --online-api-offline-verified

See ``deploy/README-demo.md`` ("本轮受控验证") for the ordered operator steps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import httpx  # noqa: E402
import task0027_ledger_baseline as ledger_baseline  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from bidding_compliance.api import create_app  # noqa: E402
from bidding_compliance.core.config import Settings  # noqa: E402
from bidding_compliance.legal.contracts import LegalIndex, LegalManifest  # noqa: E402
from bidding_compliance.legal.corpus import ingest, read_bounded  # noqa: E402
from bidding_compliance.legal.embedding_provider import DashScopeEmbeddingProvider  # noqa: E402
from bidding_compliance.legal.vector_index import SQLiteVectorIndex  # noqa: E402
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
    create_real_retriever_factory,
    real_embedding_settings,
    require_prebuilt_vector_index,
)

# The one private root the server assemblies use inside the read-write modelstate volume:
# ledger, model audit, per-file registry and the prebuilt vector index all live here.
PRIVATE_ROOT = ROOT / ".verification" / "private" / "TASK-0023"
LEGAL_MANIFEST = "config/legal/manifest.json"
INDEX_FILE = "legal-vectors.sqlite3"
ONLINE_API_URL_VARIABLE = "DEC007_ONLINE_API_URL"
DEFAULT_ONLINE_API_URL = "http://api:8000"
HEALTH_PATH = "/api/v1/health"

# This round's hard ceilings, fixed in the trusted server-side assembly (see the module
# docstring). Changing them is a reviewed code change, never an operator configuration.
ROUND_LLM_LIMIT = 4
ROUND_EMBEDDING_LIMIT = 322
ROUND_TOTAL_CNY = Decimal("2")

# The commands whose result the operator confirms with --online-api-offline-verified.
OPERATOR_OFFLINE_COMMANDS = (
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
    ledger: Mapping[str, Any]
    approved_documents: Mapping[str, Any]
    online_api: Mapping[str, Any]
    vector_index: str

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
            "ledger": dict(self.ledger),
            "approved_documents": dict(self.approved_documents),
            "online_api": dict(self.online_api),
            "vector_index": self.vector_index,
        }


@dataclass(frozen=True, slots=True)
class PreflightOutcome:
    report: PreflightReport
    resolution: RealRuntimeAuthorization


def probe_online_api(base_url: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Read-only health probe of the public stack; a failure means "state unknown, stop"."""
    owns_client = client is None
    probe = client or httpx.Client(trust_env=False, follow_redirects=False, timeout=5)
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


def _credential(environment: Mapping[str, str], name: str) -> str:
    value = (environment.get(name) or "").strip()
    if not value:
        raise PreflightFailed(
            f"{name} is required for the controlled round; without it no supplier call is possible"
        )
    return value


def _vector_index_state(
    *,
    environment: Mapping[str, str],
    private_root: Path,
    publication_id: str,
    revision_id: str,
) -> str:
    """Verify, without any supplier request, that the prebuilt index exists for this corpus."""
    if not (publication_id and revision_id):
        return (
            "not pinned in this preflight; pass --publication-id/--revision-id to verify it "
            "here, otherwise serving still refuses to build (allow_build=False)"
        )
    manifest = LegalManifest.model_validate_json(read_bounded(ROOT, LEGAL_MANIFEST))
    index: LegalIndex = ingest(ROOT, manifest)
    key = _credential(environment, "DASHSCOPE_API_KEY")
    workspace = _credential(environment, "BAILIAN_WORKSPACE_ID")
    provider = DashScopeEmbeddingProvider(
        real_embedding_settings(api_key=key, workspace_id=workspace)
    )
    try:
        found, _plan = require_prebuilt_vector_index(
            index=index,
            provider=provider,
            store=SQLiteVectorIndex(private_root / INDEX_FILE),
            publication_id=publication_id,
            revision_id=revision_id,
        )
    except (RuntimeError, ValueError) as exc:
        raise PreflightFailed(f"the prebuilt vector index check failed: {exc}") from exc
    return (
        f"prebuilt index verified: build_id={found.build_id} items={found.item_count} "
        f"publication={publication_id} revision={revision_id}"
    )


def run_preflight(
    *,
    environment: Mapping[str, str],
    private_root: Path = PRIVATE_ROOT,
    online_api_url: str | None = None,
    online_api_offline_verified: bool = False,
    publication_id: str = "",
    revision_id: str = "",
    client: httpx.Client | None = None,
) -> PreflightOutcome:
    """Every precondition of the round, all local or read-only, before any supplier call.

    Refuses (``PreflightFailed``) instead of degrading: a missing ledger, a ledger whose
    counters or scope differ from the recorded baseline, an unreachable public API, a
    missing operator confirmation or a missing prebuilt index all stop the round.
    """
    limits = assert_round_limits_bounded(round_limits())
    explicit = (environment.get("DEC007_AUTHORIZATION_ID") or "").strip()
    if explicit != FULL_CAPABILITY_AUTHORIZATION_ID:
        raise PreflightFailed(
            "the controlled round runs under the DEC-007 authorization "
            f"({FULL_CAPABILITY_AUTHORIZATION_ID}); DEC007_AUTHORIZATION_ID is {explicit!r}"
        )
    _credential(environment, "DASHSCOPE_API_KEY")
    _credential(environment, "BAILIAN_WORKSPACE_ID")
    resolution = resolve_real_runtime_authorization(environment, private_root=private_root)

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

    target_url = (
        online_api_url
        or environment.get(ONLINE_API_URL_VARIABLE, "").strip()
        or DEFAULT_ONLINE_API_URL
    )
    online_api = probe_online_api(target_url, client=client)
    if not online_api_offline_verified:
        raise PreflightFailed(
            "operator confirmation missing: verify that the public API is still offline and "
            "that no other authorized-real process uses the DEC-007 ledger, then pass "
            "--online-api-offline-verified. Commands: " + " | ".join(OPERATOR_OFFLINE_COMMANDS)
        )

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
        ledger=facts.as_payload(),
        approved_documents={"count": len(approved), "sha256": sorted(approved)},
        online_api=online_api,
        vector_index=_vector_index_state(
            environment=environment,
            private_root=private_root,
            publication_id=publication_id,
            revision_id=revision_id,
        ),
    )
    return PreflightOutcome(report=report, resolution=resolution)


def build_app(
    *,
    environment: Mapping[str, str],
    private_root: Path = PRIVATE_ROOT,
    transport: httpx.AsyncBaseTransport | None = None,
    client: httpx.Client | None = None,
    online_api_url: str | None = None,
    online_api_offline_verified: bool = False,
    publication_id: str = "",
    revision_id: str = "",
) -> tuple[Any, PreflightOutcome]:
    """The serving assembly: the online runtime with this round's tightened ceilings.

    ``allow_build`` is fixed to False here: the round reuses the prebuilt index in the
    shared modelstate volume and refuses a review (zero supplier calls, zero ledger
    consumption) when it is missing, instead of embedding the corpus synchronously.
    """
    outcome = run_preflight(
        environment=environment,
        private_root=private_root,
        online_api_url=online_api_url,
        online_api_offline_verified=online_api_offline_verified,
        publication_id=publication_id,
        revision_id=revision_id,
        client=client,
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
            private_root=private_root,
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
    """Only preflight controls exist: there is no option that can widen the ceilings."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="run every check, print the report and exit; serve nothing, reserve nothing",
    )
    parser.add_argument(
        "--online-api-offline-verified",
        action="store_true",
        help="operator confirmation that the public API is offline and no other "
        "authorized-real process uses the DEC-007 ledger",
    )
    parser.add_argument("--online-api-url", default=None, help="health probe target")
    parser.add_argument(
        "--publication-id", default="", help="legal publication of the prebuilt index"
    )
    parser.add_argument("--revision-id", default="", help="legal revision of the prebuilt index")
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
            )
            print(
                json.dumps(
                    outcome.report.as_payload(), ensure_ascii=False, indent=2, sort_keys=True
                )
            )
            print("PASS: preflight complete; nothing was reserved, sent or written.")
            return 0
        app, outcome = build_app(
            environment=environment,
            online_api_url=args.online_api_url,
            online_api_offline_verified=args.online_api_offline_verified,
            publication_id=args.publication_id,
            revision_id=args.revision_id,
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
