"""Isolated real FastAPI host with the repository's authorized offline gateway."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_review_engine import OfflineReviewGateway, _policy  # noqa: E402

from bidding_compliance.api import create_app  # noqa: E402
from bidding_compliance.core.config import Settings  # noqa: E402
from bidding_compliance.model_gateway.contracts import ModelPolicy, ModelRequest, ModelResponse  # noqa: E402
from bidding_compliance.model_gateway.errors import GatewayErrorCode, ModelGatewayError  # noqa: E402
from bidding_compliance.persistence.database import make_engine  # noqa: E402
from bidding_compliance.services.review_engine import ReviewEngine  # noqa: E402

settings = Settings(_env_file=None)
review_database = make_engine(settings)
review_factory = sessionmaker(review_database, expire_on_commit=False)


async def _test_gate(
    stage: str, task_id: str, run_id: str, call_id: str | None = None
) -> bool:
    directory = os.environ.get("TASK0028_E2E_GATE_DIR")
    if not directory:
        return False
    root = Path(directory)
    armed = root / "armed.json"
    if not armed.is_file():
        return False
    try:
        request = json.loads(armed.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if request.get("stage") != stage or request.get("task_id") not in {"*", task_id}:
        return False
    claimed = root / f"claimed-{stage}.json"
    try:
        armed.replace(claimed)
    except FileNotFoundError:
        return False
    marker = {
        "stage": stage,
        "task_id": task_id,
        "run_id": run_id,
        "call_id": call_id,
        "process_id": os.getpid(),
    }
    (root / f"entered-{stage}.json").write_text(
        json.dumps(marker, sort_keys=True), encoding="utf-8"
    )
    release = root / f"release-{stage}"
    deadline = asyncio.get_running_loop().time() + 300
    while not release.exists():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"synthetic deployment gate timed out: {stage}")
        await asyncio.sleep(0.05)
    release.unlink(missing_ok=True)
    return True


class GateableOfflineReviewGateway:
    """Synthetic provider adapter with an opt-in local crash/recovery gate."""

    def __init__(self) -> None:
        self.delegate = OfflineReviewGateway()

    def prompt_sha256(self, prompt_version: str) -> str:
        return self.delegate.prompt_sha256(prompt_version)

    async def generate_structured(
        self, request: ModelRequest, output_schema: dict[str, Any], policy: ModelPolicy
    ) -> ModelResponse:
        await _test_gate(
            "model-call",
            request.review_task_id,
            "",
            request.call_id,
        )
        directory = os.environ.get("TASK0028_E2E_GATE_DIR")
        if directory:
            pending = Path(directory) / "fail-first-pending"
            consumed = Path(directory) / "fail-first-consumed"
            try:
                pending.replace(consumed)
            except FileNotFoundError:
                pass
            else:
                raise ModelGatewayError(
                    GatewayErrorCode.TIMEOUT,
                    "synthetic transient provider timeout",
                    retryable=True,
                )
        return await self.delegate.generate_structured(request, output_schema, policy)


class E2EReviewEngine(ReviewEngine):
    async def start(self, principal: Any, request: Any) -> dict[str, Any]:
        try:
            return await super().start(principal, request)
        except Exception:
            logging.getLogger(__name__).exception("Isolated offline ReviewEngine execution failed")
            raise

    async def _invoke_claim(self, principal: Any, row: Any) -> dict[str, Any]:
        cancel_gated = await _test_gate("cancel", row.review_task_id, row.run_id)
        gated = await _test_gate(
            "pre-invoke", row.review_task_id, row.run_id
        )
        try:
            return await super()._invoke_claim(principal, row)
        except Exception:
            if cancel_gated or gated:
                directory = os.environ.get("TASK0028_E2E_GATE_DIR")
                if directory:
                    result_name = (
                        "cancel-worker-rejected.json"
                        if cancel_gated
                        else "stale-worker-rejected.json"
                    )
                    (Path(directory) / result_name).write_text(
                        json.dumps(
                            {
                                "task_id": row.review_task_id,
                                "run_id": row.run_id,
                                "process_id": os.getpid(),
                            },
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
            logging.getLogger(__name__).exception(
                "Isolated offline review-worker execution failed"
            )
            raise


review_engine = E2EReviewEngine(
    settings=settings,
    session_factory=review_factory,
    gateway=GateableOfflineReviewGateway(),
    model_policy=_policy(),
    legal_root=ROOT,
)
app = create_app(settings, review_engine=review_engine)
