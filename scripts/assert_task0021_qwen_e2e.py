"""Read-only proof that one real Qwen response fed the published synthetic review."""

from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.persistence.models import ReviewArtifact, ReviewEngineRun
from bidding_compliance.services.review_persistence import content_hash

ROOT = Path(__file__).resolve().parents[1]


def _verify(args: argparse.Namespace) -> dict[str, object]:
    database_url = os.environ.get("E2E_ADMIN_DATABASE_URL")
    if not database_url:
        raise RuntimeError("isolated review database is unavailable")
    audit_path = Path(args.audit_path).resolve()
    if not audit_path.is_relative_to((ROOT / ".verification").resolve()):
        raise ValueError("Qwen audit path is outside the verification output")
    audit_bytes = audit_path.read_bytes()
    if len(audit_bytes) > 32_768:
        raise ValueError("Qwen audit metadata exceeds its size limit")
    audit = [json.loads(line) for line in audit_bytes.splitlines() if line]
    if len(audit) != 1:
        raise AssertionError("the online demo must produce exactly one model audit event")
    event = audit[0]
    if set(event) != {
        "call_id",
        "tenant_id",
        "review_task_id",
        "node_run_id",
        "provider",
        "model",
        "profile",
        "prompt_version",
        "model_config_version",
        "pricing_version",
        "response_hash",
        "input_tokens",
        "output_tokens",
        "usage_source",
        "estimated_cost",
        "latency_ms",
        "retries",
        "fallback_path",
        "failure_category",
    }:
        raise AssertionError("Qwen audit record contains unexpected fields")
    if (
        event["provider"] != "bailian"
        or event["model"] != "qwen3.8-flash"
        or event["failure_category"] is not None
        or event["response_hash"] is None
        or event["usage_source"] != "provider_reported"
        or event["retries"] != 0
        or event["fallback_path"] != []
        or type(event["input_tokens"]) is not int
        or not 0 <= event["input_tokens"] <= 8192
        or type(event["output_tokens"]) is not int
        or not 0 <= event["output_tokens"] <= 1024
        or Decimal(event["estimated_cost"]) > Decimal("0.10")
    ):
        raise AssertionError("Qwen audit does not prove one bounded successful request")

    engine = make_engine(Settings(_env_file=None, database_url=database_url))
    try:
        with Session(engine) as session:
            run = session.get(
                ReviewEngineRun, (args.tenant, args.task, args.run_id), populate_existing=True
            )
            if run is None or run.status != "result_published":
                raise AssertionError("the synthetic online review has not been published")
            rows = list(
                session.scalars(
                    select(ReviewArtifact).where(
                        ReviewArtifact.tenant_id == args.tenant,
                        ReviewArtifact.review_task_id == args.task,
                        ReviewArtifact.run_id == args.run_id,
                        ReviewArtifact.kind.in_(
                            ("model_analysis", "merged_findings", "legal_retrieval")
                        ),
                    )
                )
            )
            by_kind = {row.kind: row for row in rows}
            model_row = by_kind.get("model_analysis")
            merged_row = by_kind.get("merged_findings")
            legal_row = by_kind.get("legal_retrieval")
            if model_row is None or merged_row is None or legal_row is None:
                raise AssertionError("model, local RAG, or merged review artifact is missing")
            for row in (model_row, merged_row, legal_row):
                if content_hash(row.content) != row.content_hash:
                    raise AssertionError("a review artifact failed its stored content hash")
            model = model_row.content
            if (
                model.get("provider") != "bailian"
                or model.get("model") != "qwen3.8-flash"
                or model.get("response_hash") != event["response_hash"]
            ):
                raise AssertionError("persisted model analysis does not match the Qwen audit")
            model_findings = model.get("content", {}).get("findings")
            merged = merged_row.content
            if (
                not isinstance(model_findings, list)
                or not model_findings
                or merged.get("model_findings_ref")
                != f"artifact://review/{model_row.artifact_id}/{model_row.content_hash}"
            ):
                raise AssertionError("Qwen output was not linked into the merged review")
            if any(item.get("legal_evidence_ids") != [] for item in model_findings):
                raise AssertionError("model output introduced an unprovided law citation")
            merged_findings = merged.get("findings", [])
            model_used = any(
                "model" in finding.get("sources", [])
                and any(
                    finding.get("title") == candidate.get("title")
                    and finding.get("description") == candidate.get("description")
                    for candidate in model_findings
                )
                for finding in merged_findings
            )
            if not model_used:
                raise AssertionError("real Qwen response did not contribute to a merged finding")
            if not legal_row.content.get("results"):
                raise AssertionError("the local legal RAG stage did not run")
            return {
                "provider": event["provider"],
                "model": event["model"],
                "response_hash": event["response_hash"],
                "input_tokens": event["input_tokens"],
                "output_tokens": event["output_tokens"],
                "estimated_cost_cny": event["estimated_cost"],
                "model_finding_count": len(model_findings),
                "merged_finding_count": len(merged_findings),
                "local_legal_retrieval_result_count": len(legal_row.content["results"]),
                "audit_event_count": len(audit),
            }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("assert-qwen",))
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--audit-path", required=True)
    args = parser.parse_args()
    result = _verify(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
