"""The only LLM interface that business code may depend on."""

from __future__ import annotations

from typing import Protocol

from .contracts import JsonObject, ModelPolicy, ModelRequest, ModelResponse


class ModelGateway(Protocol):
    """Provider adapters implement this protocol and the conformance suite."""

    async def generate_structured(
        self,
        request: ModelRequest,
        output_schema: JsonObject,
        policy: ModelPolicy,
    ) -> ModelResponse:
        """Generate and validate a structured result under an explicit policy."""
        ...
