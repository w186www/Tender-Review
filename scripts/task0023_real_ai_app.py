"""Authorized real-model app assembly: the authenticated review endpoints use real Qwen.

The assembly starts only under an explicit authorization (DEC-007 through
``DEC007_AUTHORIZATION_ID``, or the legacy DEC-005/006 identity) in a local development/test
environment. Production and staging use PostgreSQL product authority or offline mode; this
legacy SQLite ledger cannot reconcile later product consumption, revocation, or unknown calls.
Every document it may send is read from the operator's static environment allowlist plus the
append-only per-file registry; nothing is authorized implicitly and the process exits
non-zero rather than degrading to another authorization or a mock gateway.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from bidding_compliance.core.deployment_mode import validate_deployment_mode

try:
    validate_deployment_mode("authorized-real", os.environ.get("APP_ENV", "production"))
except RuntimeError as exc:
    print(str(exc), file=sys.stderr, flush=True)
    raise SystemExit(2) from exc

from sqlalchemy.orm import sessionmaker

from bidding_compliance.api import create_app
from bidding_compliance.core.config import Settings
from bidding_compliance.legal.adoption import load_adoption_policy
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.services.real_ai_runtime import (
    SEMANTIC_PROMPT_VERSION,
    AuthorizedRealReviewEngine,
    create_dec005_gateway,
    real_ai_policy,
    resolve_real_runtime_authorization,
)
from bidding_compliance.services.real_embedding_runtime import create_real_retriever_factory

ROOT = Path(__file__).resolve().parents[1]
# The one private root the server assembly uses: inside the container this is
# ``/app/.verification/private``, which is the modelstate volume root
# (``docker-compose.demo.yml`` mounts ``modelstate:/app/.verification/private``). The DEC-007
# ledger, its model audit trail, the per-file authorization registry and the prebuilt vector
# index all live directly in that root; the recorded phase-one data is exactly there, so the
# official API path must resolve to it instead of a TASK-0023 subdirectory that does not
# exist. Pointing at a different directory would both miss the existing ledger and fail the
# ledger scope check ("existing DEC ledger has a different scope"), whose only workaround
# would be deleting the ledger -- the quota reset DEC-007 forbids.
PRIVATE = ROOT / ".verification/private"

resolution = resolve_real_runtime_authorization(os.environ, private_root=PRIVATE)
key = os.environ.get("DASHSCOPE_API_KEY", "")
workspace = os.environ.get("BAILIAN_WORKSPACE_ID", "")
# One live document-authorization source for every egress decision of this process: the
# per-file registry is re-read when its file changes, so an operator revocation stops the
# next outbound request without an API restart.
document_source = resolution.allowed_document_source
gateway, authorization, budget = create_dec005_gateway(
    api_key=key,
    workspace_id=workspace,
    tenant_id=resolution.tenant_id,
    allowed_document_sha256=document_source,
    ledger_path=resolution.ledger_path,
    audit_path=resolution.model_audit_path,
    authorization_id=resolution.authorization_id,
    scope_documents=resolution.environment_documents,
    authorization_registry=resolution.registry_path,
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
        private_root=PRIVATE,
        # Serving never builds: the full-corpus index must already exist in the same
        # modelstate volume, written by scripts/prebuild_legal_vectors.py.
        allow_build=False,
        adoption_policy=load_adoption_policy(ROOT),
    ),
)
app = create_app(settings, review_engine=review_engine)
app.state.review_prompt_version = SEMANTIC_PROMPT_VERSION
app.state.external_budget = budget
app.state.authorization_id = resolution.authorization_id
app.state.authorized_document_count = len(resolution.allowed_documents)
# The per-file registry the reviewer's explicit confirmation endpoint appends to (same file
# the operator CLI writes and the egress gate re-reads): without it that endpoint is
# unavailable (503) and every unconfirmed file stays local-only.
app.state.external_authorization_registry = resolution.registry
# Operator-critical context goes to stderr, where the JSON formatter cannot hide it.
print(
    "real model authorization: "
    f"id={resolution.authorization_id} "
    f"documents={len(resolution.allowed_documents)} "
    f"registry={resolution.registry_path or 'none'} "
    f"ledger={resolution.ledger_path}",
    file=sys.stderr,
    flush=True,
)
