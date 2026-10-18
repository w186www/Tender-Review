"""Deterministic reducers for parallel LangGraph workers."""

from __future__ import annotations


def merge_sorted_unique(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Merge concurrently returned references without order-sensitive duplicates."""
    values = (*(left or []), *(right or []))
    return sorted(set(values))
