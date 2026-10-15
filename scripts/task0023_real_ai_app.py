"""Authorized real-model app assembly: the authenticated review endpoints use real Qwen.

The assembly starts only under an explicit server authorization (DEC-007 through
``DEC007_AUTHORIZATION_ID``, or the legacy DEC-005/006 identity). Every document it may
send is read from the operator's static environment allowlist plus the append-only
per-file registry; nothing is authorized implicitly and the process exits non-zero rather
than degrading to a different authorization or to a mock gateway.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from bidding_compliance.api import create_app
from bidding_compliance.core.config import Settings
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
PRIVATE = ROOT / ".verification/private/TASK-0023"

resolution = resolve_real_runtime_authorization(os.environ, private_root=PRIVATE)
key = os.environ.get("DASHSCOPE_API_KEY", "")
workspace = os.environ.get("BAILIAN_WORKSPACE_ID", "")
gateway, authorization, budget = create_dec005_gateway(
    api_key=key,
    workspace_id=workspace,
    tenant_id="tenant-a",
    allowed_document_sha256=resolution.allowed_documents,
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
    allowed_document_sha256=resolution.allowed_documents,
    retriever_factory=create_real_retriever_factory(
        api_key=key,
        workspace_id=workspace,
        budget=budget,
        private_root=PRIVATE,
    ),
)
app = create_app(settings, review_engine=review_engine)
app.state.review_prompt_version = SEMANTIC_PROMPT_VERSION
app.state.external_budget = budget
app.state.authorization_id = resolution.authorization_id
app.state.authorized_document_count = len(resolution.allowed_documents)
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
