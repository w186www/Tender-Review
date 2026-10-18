"""Version switches for new review runs; frozen legacy runs keep their contracts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SEMANTIC_EVIDENCE_PROMPT_VERSION = "task0029-semantic-evidence-v2"
FULLTEXT_V1_PROMPT_VERSION = "task0029-semantic-fulltext-v1"
DISCOVERY_EVIDENCE_PROMPT_VERSION = "task0029-discovery-evidence-v2"
LEGACY_DISCOVERY_PROMPT_VERSION = "task0023-discovery-v1"


def discovery_prompt_for(semantic_version: str) -> str:
    return (
        DISCOVERY_EVIDENCE_PROMPT_VERSION
        if semantic_version == SEMANTIC_EVIDENCE_PROMPT_VERSION
        else LEGACY_DISCOVERY_PROMPT_VERSION
    )


def issue_identity_key(value: Any) -> str | None:
    """A proposed mechanism identity; merging also requires verified source anchors."""
    if not isinstance(value, dict) or set(value) != {"subject", "mechanism", "condition"}:
        return None
    normalized = {}
    for name, text in value.items():
        if not isinstance(text, str) or not text.strip() or len(text) > 160:
            return None
        normalized[name] = re.sub(r"\s+", "", text).casefold()
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "issue-v2:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def candidate_anchor(candidate: Any) -> tuple[tuple[str, str, str, str], ...]:
    """A frozen fact anchor; category and model wording are deliberately excluded."""
    return tuple(
        sorted(
            {
                (excerpt.document_sha256, excerpt.section_id, excerpt.locator, excerpt.quote_sha256)
                for excerpt in candidate.source_excerpts
            }
        )
    )


def same_source_candidates(candidates: Any) -> dict[str, list[dict[str, str]]]:
    groups: dict[tuple[tuple[str, str, str, str], ...], list[Any]] = {}
    for candidate in candidates:
        groups.setdefault(candidate_anchor(candidate), []).append(candidate)
    return {
        candidate.candidate_id: [
            {
                "candidate_id": other.candidate_id,
                "category": other.category,
                "suspected_problem": other.matched_reason,
            }
            for other in sorted(group, key=lambda item: item.candidate_id)
        ]
        for group in groups.values()
        for candidate in group
    }
