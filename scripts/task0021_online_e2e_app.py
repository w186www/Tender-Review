"""TASK-0021-only online API app; fail closed unless the operator enabled the gate."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from bidding_compliance.api import create_app  # noqa: E402
from bidding_compliance.core.config import Settings  # noqa: E402
from bidding_compliance.persistence.database import make_engine  # noqa: E402
from scripts.task0021_online_runtime import (  # noqa: E402
    PROMPT_VERSION,
    Task0021OnlineReviewEngine,
    create_online_gateway,
    online_policy,
)

if os.environ.get("TASK0021_ONLINE_APPROVED") != "1":
    raise RuntimeError("TASK-0021 online mode is disabled until its approved runner is used")

credential = os.environ.get("DASHSCOPE_API_KEY")
workspace_id = os.environ.get("BAILIAN_WORKSPACE_ID")
fixture_sha256 = os.environ.get("TASK0021_ALLOWED_SYNTHETIC_DOC_SHA256")
audit_path_raw = os.environ.get("TASK0021_MODEL_AUDIT_PATH")
if not credential or not workspace_id or not fixture_sha256 or not audit_path_raw:
    raise RuntimeError("TASK-0021 online runtime configuration is incomplete")

settings = Settings(_env_file=None)
database = make_engine(settings)
session_factory = sessionmaker(database, expire_on_commit=False)
gateway, authorization = create_online_gateway(
    api_key=credential,
    workspace_id=workspace_id,
    allowed_document_sha256=fixture_sha256,
    audit_path=Path(audit_path_raw),
)
review_engine = Task0021OnlineReviewEngine(
    settings=settings,
    session_factory=session_factory,
    gateway=gateway,
    model_policy=online_policy(),
    legal_root=ROOT,
    authorization=authorization,
)
app = create_app(settings, review_engine=review_engine)
app.state.review_prompt_version = PROMPT_VERSION
