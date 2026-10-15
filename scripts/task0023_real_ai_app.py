"""DEC-005 app assembly: the ordinary authenticated review endpoints use real Qwen."""

from __future__ import annotations

import os
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
)
from bidding_compliance.services.real_embedding_runtime import create_real_retriever_factory

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".verification/private/TASK-0023"
if os.environ.get("DEC005_AUTHORIZATION_ID") != "DEC-005-2026-10-15":
    raise RuntimeError("DEC-005 real AI is disabled without its explicit server authorization")

key = os.environ.get("DASHSCOPE_API_KEY", "")
workspace = os.environ.get("BAILIAN_WORKSPACE_ID", "")
allowed_sha = os.environ.get("DEC005_ALLOWED_DOCUMENT_SHA256", "")
allowed = frozenset({allowed_sha, os.environ.get("DEC005_ALLOWED_SYNTHETIC_SHA256", "")})
gateway, authorization, budget = create_dec005_gateway(
    api_key=key,
    workspace_id=workspace,
    tenant_id="tenant-a",
    allowed_document_sha256=allowed,
    ledger_path=PRIVATE / "dec005-budget.sqlite3",
    audit_path=PRIVATE / "model-audit.jsonl",
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
    allowed_document_sha256=allowed,
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
