from __future__ import annotations

import unittest

from bidding_compliance.model_gateway import ModelPolicy, ModelRequest, ModelUsage


class ModelGatewayContractTests(unittest.TestCase):
    """TASK-0003: boundary validation only; AC-010 awaits two provider adapters."""

    def test_policy_rejects_unbounded_retry(self) -> None:
        with self.assertRaises(ValueError):
            ModelPolicy(profile="review", timeout_seconds=30, max_attempts=10)

    def test_request_requires_trace_identifiers(self) -> None:
        with self.assertRaises(ValueError):
            ModelRequest(
                call_id="",
                tenant_id="tenant-1",
                review_task_id="review-1",
                node_run_id="node-1",
                prompt_version="v1",
                system_instruction="Return JSON.",
                input_payload={},
            )

    def test_usage_rejects_negative_tokens(self) -> None:
        with self.assertRaises(ValueError):
            ModelUsage(input_tokens=-1, output_tokens=2)


if __name__ == "__main__":
    unittest.main()
