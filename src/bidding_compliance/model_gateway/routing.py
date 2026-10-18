"""Immutable server-owned profile route declarations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ModelTarget:
    provider: str
    model: str
    input_cost_per_million: Decimal
    output_cost_per_million: Decimal
    pricing_version: str
    max_cost_per_call: Decimal
    config_version: str = "route-v1"
    schema_supported: bool = True

    def __post_init__(self) -> None:
        if (
            not self.provider.strip()
            or not self.model.strip()
            or not self.pricing_version.strip()
            or not self.config_version.strip()
        ):
            raise ValueError("provider, model, route, and pricing versions must be configured")
        amounts = (
            self.input_cost_per_million,
            self.output_cost_per_million,
            self.max_cost_per_call,
        )
        if any(
            not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0
            for amount in amounts
        ):
            raise ValueError("finite positive prices and per-call ceiling are required")


@dataclass(frozen=True, slots=True)
class ProfileRouter:
    routes: Mapping[str, tuple[ModelTarget, ...]]
    fallback_allowed: frozenset[str] = frozenset()

    def candidates(self, profile: str) -> tuple[ModelTarget, ...]:
        configured = self.routes.get(profile, ())
        if profile not in self.fallback_allowed:
            return configured[:1]
        return configured
