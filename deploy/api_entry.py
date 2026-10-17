"""Serve the existing authenticated API with the repository's own review executor.

This module is packaging, not business logic. It contains no review behaviour of its own;
it only decides which of the repository's existing, already-authorized app assemblies is
served, and it refuses to start rather than silently degrading to a different one.

DEPLOY_REVIEW_MODE values
-------------------------
offline          (default) scripts/task0011_e2e_app.py assembly: the real LangGraph review
                 pipeline with the repository's deterministic OfflineReviewGateway. No
                 supplier request is possible. Results are protocol-conformance output,
                 never a semantic judgement, and the workbench is built with the matching
                 "离线确定性演示" notice.
authorized-real  scripts/task0023_real_ai_app.py assembly: the same pipeline with the
                 Bailian Qwen gateway. It starts only when the independent model
                 authorization variables are present and the budget ledger still has
                 headroom; otherwise this process exits non-zero.
product-postgres scripts/task0028_product_app.py assembly: the product-mode authority is
                 PostgreSQL only (tenant policy, per-file authorization, budget). It
                 refuses the legacy SQLite ledger configuration and exits non-zero when
                 the policy/account or supplier credentials are missing.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import uvicorn  # noqa: E402

from bidding_compliance.core.logging import configure_logging  # noqa: E402

MODE = os.environ.get("DEPLOY_REVIEW_MODE", "offline").strip().lower()

if MODE == "offline":
    import task0011_e2e_app as assembly  # noqa: E402
elif MODE == "authorized-real":
    import task0023_real_ai_app as assembly  # noqa: E402
elif MODE == "product-postgres":
    import task0028_product_app as assembly  # noqa: E402
else:
    print(
        f"unknown DEPLOY_REVIEW_MODE {MODE!r}; expected 'offline', 'authorized-real' "
        "or 'product-postgres'",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main() -> int:
    configure_logging(os.environ.get("APP_LOG_LEVEL", "INFO"))
    # "server_starting" is one of the allowlisted events of core/logging.py, so this line
    # survives the repository's deliberately content-free JSON formatter.
    logging.getLogger("bidding_compliance").info("server_starting")
    app = assembly.app
    app.state.deploy_review_mode = MODE
    # The JSON formatter drops unlisted messages by design, so operator-critical context
    # goes to stderr where it is visible in `docker compose logs`.
    if MODE == "offline":
        print(
            "review mode: offline (deterministic protocol gateway; no supplier request is "
            "possible and the findings are not a semantic review)",
            file=sys.stderr,
            flush=True,
        )
    elif MODE == "authorized-real":
        print(
            "review mode: authorized-real (supplier calls limited to the authorized "
            "document hashes and the remaining ledger ceiling)",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(
            "review mode: product-postgres (PostgreSQL tenant policy, per-file "
            "authorization and budget are the only authority)",
            file=sys.stderr,
            flush=True,
        )
    uvicorn.run(
        app,
        host=os.environ.get("APP_HOST", "0.0.0.0"),  # noqa: S104 - container must listen on all interfaces
        port=int(os.environ.get("APP_PORT", "8000")),
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
