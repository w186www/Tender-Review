"""Internal provider-neutral result shared after protocol parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts import ModelUsage


@dataclass(frozen=True, slots=True)
class ProviderResult:
    content: dict[str, Any]
    usage: ModelUsage
    latency_ms: int
    finish_reason: str | None
