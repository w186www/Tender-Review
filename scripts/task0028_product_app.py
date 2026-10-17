"""Product-mode app assembly: PostgreSQL authorization and budget are the only authority.

Startup fails closed unless the tenant policy, budget account and server-side supplier
credentials are all present. The legacy DEC-007/DEC-005 SQLite configuration is rejected
here so two independent quotas cannot coexist. No supplier request occurs at startup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from bidding_compliance.core.config import Settings
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.services.product_runtime import create_product_runtime

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".verification/private"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"product mode requires {name}", file=sys.stderr, flush=True)
        raise SystemExit(2)
    return value


if os.environ.get("DEC007_AUTHORIZATION_ID", "").strip() or os.environ.get(
    "DEC005_AUTHORIZATION_ID", ""
).strip():
    print(
        "product mode refuses the legacy DEC-005/DEC-007 ledger configuration; "
        "one PostgreSQL budget authority is required",
        file=sys.stderr,
        flush=True,
    )
    raise SystemExit(2)

tenant = _required("PRODUCT_TENANT_ID")
provider = _required("PRODUCT_PROVIDER")
purpose = os.environ.get("PRODUCT_PURPOSE", "external_review").strip()
budget_authorization = _required("PRODUCT_BUDGET_AUTHORIZATION_ID")
model = os.environ.get("PRODUCT_MODEL", "qwen3.8-flash").strip()
key = _required("DASHSCOPE_API_KEY")
workspace = _required("BAILIAN_WORKSPACE_ID")
settings = Settings(_env_file=None)
database = make_engine(settings)

runtime = create_product_runtime(
    settings=settings,
    database=database,
    tenant_id=tenant,
    provider=provider,
    purpose=purpose,
    model=model,
    api_key=key,
    workspace_id=workspace,
    budget_authorization_id=budget_authorization,
    private_root=PRIVATE,
    allow_vector_build=False,
)
app = runtime.app
app.state.deploy_review_mode = "product-postgres"
app.state.external_authorization_mode = "postgres"
app.state.external_authorization_purpose = purpose
app.state.external_authorization_provider = provider
app.state.product_tenant_id = tenant
review_engine = runtime.engine
# Operator-critical, non-secret context goes to stderr, outside the JSON formatter.
print(
    "review mode: product-postgres "
    f"tenant={tenant} provider={provider} purpose={purpose} "
    f"budget_authorization={budget_authorization} "
    f"budget_limit_cny={runtime.budget.verify_account()['limit_cny']} "
    f"reconciled_reserved={runtime.reconciliation['released']} "
    f"reconciled_unknown={runtime.reconciliation['unknown']}",
    file=sys.stderr,
    flush=True,
)
