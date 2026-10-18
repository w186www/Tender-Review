"""Bounded exhaustive discovery planning and independent exact-source validation.

Only the ModelGateway performs external calls. Document identities and locator maps
stay local; an equal-character redaction permits validating returned quotes without
accepting model-generated locators, hashes, rule identities or legal conclusions.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from bidding_compliance.domain.rules.models import (
    CandidateFinding,
    CandidateSource,
    Category,
    DiscoveryResult,
    LocatedFragment,
    ModelCandidateProvenance,
    SourceExcerpt,
    candidate_source_identity,
)
from bidding_compliance.model_gateway.contracts import ModelRequest, ModelResponse

TASK0023_DISCOVERY_PROMPT_VERSION = "task0023-discovery-v1"
MAX_DISCOVERY_BATCHES = 28
# The response schema and prompt cap one batch at three findings. That is a per-call
# bound, not a product coverage bound: a batch that returns the cap is marked saturated
# and reported as partial, so a later bounded subdivision can rescan it.
SATURATION_FINDING_LIMIT = 3
# Bounded subdivision: a saturated batch may be split at section boundaries, but only
# within a fixed depth and a fixed number of additional calls. Hitting either bound
# leaves the batch visibly saturated/partial; it never claims complete coverage.
MAX_SUBDIVISION_DEPTH = 3
# Four saturated parents can each produce two children (8) and their saturated
# children need one more bounded split (8 more); sixteen extra batches is the measured
# ceiling for a 1,155-section real tender without allowing unbounded rescanning.
MAX_SUBDIVISION_BATCHES = 16


def batch_coverage(
    batch: DiscoveryBatch,
    accepted_count: int,
    rejected_count: int,
    *,
    subdivided: bool = False,
) -> dict[str, Any]:
    """Per-batch coverage record; saturation is visible instead of being called complete."""
    saturated = accepted_count >= SATURATION_FINDING_LIMIT
    if subdivided:
        status = "subdivided"
    elif saturated:
        status = "saturated"
    elif rejected_count:
        status = "partial"
    else:
        status = "completed"
    return {
        "batch_index": batch.index,
        "parent_index": batch.parent_index,
        "depth": batch.depth,
        "batch_input_hash": batch.input_hash,
        "section_count": len(batch.sections),
        "source_unit_hashes": sorted(
            {source_unit_hash(item.located) for item in batch.sections}
        ),
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "saturated": saturated,
        "subdivided": subdivided,
        "status": status,
    }


def coverage_summary(
    batches: Sequence[dict[str, Any]],
    *,
    section_count: int,
) -> dict[str, Any]:
    """Aggregate plan coverage; subdivision is neutral only when its children complete."""
    saturated = [item for item in batches if item.get("status") == "saturated"]
    failed = [item for item in batches if item.get("status") == "failed"]
    partial = [
        item
        for item in batches
        if item.get("status") in {"saturated", "partial", "failed"}
    ]
    subdivided = [item for item in batches if item.get("status") == "subdivided"]
    all_source_units = {
        str(source_hash)
        for item in batches
        for source_hash in item.get("source_unit_hashes", [])
        if isinstance(source_hash, str)
    }
    saturated_source_units = {
        str(source_hash)
        for item in batches
        if item.get("status") == "saturated"
        for source_hash in item.get("source_unit_hashes", [])
        if isinstance(source_hash, str)
    }
    rejected_sections = sum(
        int(item.get("section_count", 0) or 0)
        for item in batches
        if item.get("status") == "partial"
    )
    submitted_source_units = {
        str(source_hash)
        for item in batches
        if item.get("response_hash") is not None
        or (
            item.get("status") in {"completed", "partial", "saturated"}
            and not item.get("failure_code")
        )
        for source_hash in item.get("source_unit_hashes", [])
        if isinstance(source_hash, str)
    }
    failed_source_units = {
        str(source_hash)
        for item in failed
        for source_hash in item.get("source_unit_hashes", [])
        if isinstance(source_hash, str)
    }
    failed_sections = len(failed_source_units)
    submitted_sections = len(submitted_source_units)
    unsubmitted_source_units = all_source_units - submitted_source_units - failed_source_units
    unsubmitted_sections = len(unsubmitted_source_units)
    unprocessed_sections = len(failed_source_units | unsubmitted_source_units)
    rejection_rows = [
        rejection
        for item in batches
        for rejection in item.get("rejection_summaries", [])
        if isinstance(rejection, dict)
    ]
    rejection_keys = {
        str(item["candidate_identity_hash"])
        for item in rejection_rows
        if isinstance(item.get("candidate_identity_hash"), str)
    }
    rejection_reason_keys: dict[str, set[str]] = {}
    rejection_source_units: set[str] = set()
    rejection_family_units: dict[str, str] = {}
    rejection_family_first_batch: dict[str, int] = {}
    for item in batches:
        batch_index = int(item.get("batch_index", 0))
        for rejection in item.get("rejection_summaries", []):
            if not isinstance(rejection, dict):
                continue
            candidate_key = rejection.get("candidate_identity_hash")
            reason = rejection.get("reason")
            if isinstance(candidate_key, str) and isinstance(reason, str):
                rejection_reason_keys.setdefault(reason, set()).add(candidate_key)
            source_hash = rejection.get("source_unit_hash")
            if isinstance(source_hash, str):
                rejection_source_units.add(source_hash)
            family_hash = rejection.get("candidate_family_hash")
            if isinstance(family_hash, str):
                rejection_family_first_batch[family_hash] = min(
                    batch_index,
                    rejection_family_first_batch.get(family_hash, batch_index),
                )
                if isinstance(source_hash, str):
                    rejection_family_units[family_hash] = source_hash
    accepted_family_first_batch: dict[str, int] = {}
    for item in batches:
        batch_index = int(item.get("batch_index", 0))
        for family_hash in item.get("accepted_candidate_family_hashes", []):
            if isinstance(family_hash, str):
                accepted_family_first_batch[family_hash] = min(
                    batch_index,
                    accepted_family_first_batch.get(family_hash, batch_index),
                )
    recovered_families = {
        family_hash
        for family_hash, rejected_batch in rejection_family_first_batch.items()
        if accepted_family_first_batch.get(family_hash, rejected_batch) > rejected_batch
    }
    rejected_families = set(rejection_family_first_batch)
    recovered_source_units = {
        rejection_family_units[family_hash]
        for family_hash in recovered_families
        if family_hash in rejection_family_units
    }
    truncated = {
        str(item.get("batch_input_hash", item.get("batch_index")))
        for item in batches
        if item.get("response_hash") is not None
        and item.get("finish_reason") in {"length", "max_tokens"}
    }
    failed_attempts = {
        str(item.get("batch_input_hash", item.get("batch_index")))
        for item in batches
        if item.get("failure_code")
    }
    return {
        "status": "partial" if partial else "complete",
        "batch_count": len(batches),
        "section_count": section_count,
        "source_unit_count": len(all_source_units),
        "completed_batches": sum(item.get("status") == "completed" for item in batches),
        "partial_batches": sum(item.get("status") == "partial" for item in batches),
        "subdivided_batches": len(subdivided),
        "subdivision_calls": sum(
            item.get("parent_index") is not None for item in batches
        ),
        "saturated_batches": len(saturated),
        "saturated_batch_indices": [item["batch_index"] for item in saturated],
        "saturated_sections": len(saturated_source_units),
        "rejected_sections": rejected_sections,
        "failed_sections": failed_sections,
        "submitted_sections": submitted_sections,
        "unsubmitted_sections": unsubmitted_sections,
        "unprocessed_sections": unprocessed_sections,
        "truncated_batches": len(truncated),
        "truncated_batch_indices": [
            int(item["batch_index"])
            for item in batches
            if str(item.get("batch_input_hash", item.get("batch_index"))) in truncated
        ],
        "failed_batch_attempts": len(failed_attempts),
        "failed_batches": len(failed),
        "failed_batch_indices": [item["batch_index"] for item in failed],
        "failed_batch_codes": sorted(
            {
                str(item.get("failure_code"))
                for item in failed
                if item.get("failure_code")
            }
        ),
        "accepted_candidates": sum(int(item.get("accepted_count", 0)) for item in batches),
        "rejected_candidates": sum(int(item.get("rejected_count", 0)) for item in batches),
        "rejected_candidate_attempts": len(rejection_rows),
        "rejected_candidate_count": len(rejection_keys),
        "rejected_source_unit_count": len(rejection_source_units),
        "rejection_reason_counts": {
            reason: len(candidate_keys)
            for reason, candidate_keys in sorted(rejection_reason_keys.items())
        },
        "recovered_candidate_families": len(recovered_families),
        "unrecovered_candidate_families": len(rejected_families - recovered_families),
        "recovered_source_unit_count": len(recovered_source_units),
    }


def source_unit_hash(item: LocatedFragment) -> str:
    """Hash a stable source-fragment identity without exposing tender text."""
    return _hash(
        {
            "document_version_ref": item.document.document_version_ref,
            "section_id": item.section_id,
            "section_revision": item.section_revision,
            "source_sha256": item.fragment.text_sha256,
        }
    )


def _candidate_family_hash(
    source_hash: str, category: str, description: str
) -> str:
    return _hash(
        {
            "source_unit_hash": source_hash,
            "category": category,
            "normalized_description": "".join(description.split()),
        }
    )


def candidate_family_hash(candidate: CandidateFinding) -> str:
    """Stable family key used only to measure later recovery of a rejected suggestion."""
    if not candidate.source_excerpts:
        return ""
    excerpt = candidate.source_excerpts[0]
    source_hash = _hash(
        {
            "document_version_ref": candidate.document_version_ref,
            "section_id": excerpt.section_id,
            "section_revision": excerpt.section_revision,
            "source_sha256": excerpt.quote_sha256,
        }
    )
    return _candidate_family_hash(source_hash, candidate.category, candidate.matched_reason)

# Batch capacity is deliberately set from the authorized input-token ceiling: the
# gateway rejects any request above 65,536 input tokens, and the per-batch finding
# limit is what bounds model output, so wider batches trade candidate count for calls.
MAX_BATCH_SOURCE_BYTES = 18000
MAX_BATCH_SECTIONS = 200
# The semantic request exposes this many top legal hits per candidate; the same bound is
# enforced when the model's selected evidence IDs are revalidated, so an ID the model was
# never shown cannot become a citation even if it exists elsewhere in the retrieval run.
MAX_LEGAL_CANDIDATES_PER_CANDIDATE = 6
ROOT = Path(__file__).resolve().parents[3]


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def discovery_schema(root: Path = ROOT) -> dict[str, Any]:
    value = json.loads(
        (root / "contracts/schemas/llm-candidate-discovery.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(value)
    return cast(dict[str, Any], value)


_PII = {
    "email": re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "mobile": re.compile(
        r"(?<!\d)(?:(?:\+?86|[（(]\+?86[）)])[ \t-]*)?1[3-9](?:[ \t-]*\d){9}(?!\d)"
    ),
    "landline": re.compile(
        r"(?<!\d)(?:(?:\+?86|[（(]\+?86[）)])[ \t-]*)?"
        r"(?:0\d{2,3}|[（(]0\d{2,3}[）)])[ \t-]*\d{3,4}[ \t-]*\d{4}"
        r"(?:[ \t-]*(?:转|分机|ext\.?|x)[ \t:：-]*\d{1,6})?(?!\d)",
        re.IGNORECASE,
    ),
    "service_phone": re.compile(r"(?<!\d)(?:400|800)[ \t-]*\d{3}[ \t-]*\d{4}(?!\d)"),
    "identity_number": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "long_account_number": re.compile(r"(?<!\d)\d(?:[ \t-]*\d){12,21}(?!\d)"),
}
_CONTACT = re.compile(
    r"((?:联\s*系\s*人|联络人|联系姓名|姓名|负责人|经办人)[ \t]*[:：][ \t]*)"
    r"([\u3400-\u9fff·]{2,6}|[A-Za-z][A-Za-z .'-]{1,60})(?=$|[，,；;。\s（(])"
)
_ACCOUNT = re.compile(
    r"((?:银行账[号户]|银行帐[号户]|收款账[号户]|开户账[号户]|账[号户]|帐[号户])"
    r"[ \t]*[:：][ \t]*)([A-Za-z0-9][A-Za-z0-9 \t-]{5,39})"
)
_LOCAL_PHONE = re.compile(
    r"((?:联系电话|联系方式|电话|手机|传真)[ \t]*[:：][ \t]*)"
    r"([0-9][0-9 \t-]{6,29})(?!\d)"
)
_REQUIREMENT = re.compile(r"^(?:应|须|需|必须|具有|具备|提供|不得|不应|要求|至少|负责|承担|参加)")


def redact_discovery_text(text: str) -> str:
    """Idempotent, equal-character masking shared with the trusted gateway minimizer."""
    for pattern in _PII.values():
        text = pattern.sub(lambda match: "*" * len(match.group()), text)
    text = _CONTACT.sub(
        lambda match: (
            match.group()
            if _REQUIREMENT.match(match.group(2))
            else match.group(1) + "*" * len(match.group(2))
        ),
        text,
    )
    text = _ACCOUNT.sub(lambda match: match.group(1) + "*" * len(match.group(2)), text)
    text = _LOCAL_PHONE.sub(lambda match: match.group(1) + "*" * len(match.group(2)), text)
    return text


def pii_preflight(text: str) -> dict[str, int]:
    """Content-free counts of recognizable PII left in an outbound minimized text.

    This detects the supported formats, not arbitrary unlabelled names. Planning also
    uses neighbouring field labels for isolated table values before producing text.
    """
    counts = {name: len(pattern.findall(text)) for name, pattern in _PII.items()}
    counts["contact_name"] = sum(
        not bool(_REQUIREMENT.match(match.group(2))) for match in _CONTACT.finditer(text)
    )
    counts["account_field"] = len(_ACCOUNT.findall(text))
    counts["labelled_phone"] = len(_LOCAL_PHONE.findall(text))
    return counts


def _locator_key(item: LocatedFragment) -> tuple[tuple[int, str | int], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", item.fragment.locator)
    )


def _field_kind(text: str) -> str | None:
    label = re.sub(r"[\s:：]+", "", text)
    if label in {"联系人", "联络人", "联系姓名", "姓名", "项目联系人", "负责人", "经办人"}:
        return "name"
    if label in {"联系电话", "联系方式", "电话", "手机", "移动电话", "传真", "电子邮箱", "邮箱"}:
        return "contact"
    if label in {"银行账号", "银行帐号", "收款账号", "开户账号", "账号", "帐号", "账户"}:
        return "account"
    return None


_DANGLING_LABEL = re.compile(
    r"((?:项目联系人|联系人|联络人|联系姓名|姓名|负责人|经办人|"
    r"联系电话|联系方式|电话|手机|移动电话|传真|电子邮箱|邮箱|"
    r"银行账号|银行帐号|收款账号|开户账号|账号|帐号|账户))[ \t]*[:：][ \t]*$"
)


def _dangling_field_kind(text: str) -> str | None:
    """A label whose value is in the next paragraph rather than on the same line."""
    match = _DANGLING_LABEL.search(text)
    return _field_kind(match.group(1)) if match else None


def _mask_value(text: str) -> str:
    return "".join("\n" if char == "\n" else "*" for char in text)


def _plausible_cross_paragraph_value(text: str) -> bool:
    value = text.strip()
    return (
        bool(value)
        and len(value) <= 100
        and _field_kind(value) is None
        and not _REQUIREMENT.match(value)
    )


def _located_safe_texts(
    items: Sequence[LocatedFragment],
) -> tuple[tuple[LocatedFragment, str], ...]:
    ordered = sorted(items, key=_locator_key)
    result: list[tuple[LocatedFragment, str]] = []
    previous: LocatedFragment | None = None
    for item in ordered:
        safe_text = redact_discovery_text(item.fragment.text)
        if previous is not None:
            before, current = previous.fragment, item.fragment
            adjacent_cells = (
                before.kind == current.kind == "table_cell"
                and before.table == current.table
                and before.row == current.row
                and before.column is not None
                and current.column == before.column + 1
            )
            if adjacent_cells:
                kind = _field_kind(before.text)
                plausible_name = (
                    bool(current.text.strip())
                    and len(current.text.strip()) <= 100
                    and not _REQUIREMENT.match(current.text.strip())
                )
                if kind in {"contact", "account"} or (kind == "name" and plausible_name):
                    safe_text = _mask_value(current.text)
            else:
                # A label at the end of one paragraph and its value in the next paragraph
                # is a common Word/OCR layout. Mask the value there too, not only when the
                # pair happens to share a table row.
                cross_paragraph = (
                    before.kind == current.kind
                    and before.kind in {"paragraph", "ocr"}
                    and before.section == current.section
                    and _dangling_field_kind(before.text) is not None
                    and _plausible_cross_paragraph_value(current.text)
                )
                if cross_paragraph:
                    safe_text = _mask_value(current.text)
        result.append((item, safe_text))
        previous = item
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DiscoverySection:
    section_key: str
    located: LocatedFragment
    start: int
    end: int
    safe_source_text: str | None = None

    @property
    def text(self) -> str:
        return self.located.fragment.text[self.start : self.end]

    @property
    def safe_text(self) -> str:
        # Redact before slicing so a phone/email split across a chunk boundary is masked.
        safe = self.safe_source_text
        if safe is None:
            safe = redact_discovery_text(self.located.fragment.text)
        return safe[self.start : self.end]

    def request_payload(self) -> dict[str, str]:
        return {
            "section_key": self.section_key,
            "text": self.safe_text,
            "document_sha256": self.located.document.raw_source_sha256,
        }

    def coverage(self) -> dict[str, Any]:
        item = self.located
        return {
            "section_key": self.section_key,
            "document_id": item.document.document_id,
            "document_version_ref": item.document.document_version_ref,
            "section_id": item.section_id,
            "section_revision": item.section_revision,
            "locator": item.fragment.locator,
            "page": item.fragment.page,
            "section": item.fragment.section,
            "kind": item.fragment.kind,
            "table": item.fragment.table,
            "row": item.fragment.row,
            "column": item.fragment.column,
            "source_sha256": item.fragment.text_sha256,
            "char_start": self.start,
            "char_end": self.end,
            "sent_text_sha256": hashlib.sha256(self.safe_text.encode()).hexdigest(),
        }


@dataclass(frozen=True, slots=True)
class DiscoveryBatch:
    index: int
    sections: tuple[DiscoverySection, ...]
    parent_index: int | None = None
    depth: int = 0

    def payload(self) -> dict[str, Any]:
        return {"discovery_sections": [item.request_payload() for item in self.sections]}

    @property
    def input_hash(self) -> str:
        return _hash(self.payload())


def subdivide_batch(batch: DiscoveryBatch, next_index: int) -> tuple[DiscoveryBatch, ...]:
    """Split saturated or failed input, including long single sections, within fixed budgets."""
    if not batch.sections or batch.depth >= MAX_SUBDIVISION_DEPTH:
        return ()
    if len(batch.sections) >= 2:
        midpoint = len(batch.sections) // 2
        left_sections = batch.sections[:midpoint]
        right_sections = batch.sections[midpoint:]
    else:
        section = batch.sections[0]
        if section.end - section.start < 8:
            return ()
        text = section.text
        midpoint = len(text) // 2
        lower, upper = 4, len(text) - 4
        boundaries = [
            index + 1
            for index, character in enumerate(text)
            if character in "。！？；;\n" and lower <= index + 1 <= upper
        ]
        split_at = (
            min(boundaries, key=lambda value: abs(value - midpoint)) if boundaries else midpoint
        )
        split_at = min(max(split_at, lower), upper)
        left_sections = (
            DiscoverySection(
                section_key=f"s{900000 + next_index:06d}c000",
                located=section.located,
                start=section.start,
                end=section.start + split_at,
                safe_source_text=section.safe_source_text,
            ),
        )
        right_sections = (
            DiscoverySection(
                section_key=f"s{900001 + next_index:06d}c000",
                located=section.located,
                start=section.start + split_at,
                end=section.end,
                safe_source_text=section.safe_source_text,
            ),
        )
    return (
        DiscoveryBatch(
            next_index,
            left_sections,
            parent_index=batch.index,
            depth=batch.depth + 1,
        ),
        DiscoveryBatch(
            next_index + 1,
            right_sections,
            parent_index=batch.index,
            depth=batch.depth + 1,
        ),
    )


def source_excerpt(item: LocatedFragment) -> SourceExcerpt:
    """Build source identity from trusted storage, never from model fields."""
    fragment = item.fragment
    if hashlib.sha256(fragment.text.encode()).hexdigest() != fragment.text_sha256:
        raise ValueError("discovery source fragment hash mismatch")
    return SourceExcerpt(
        document_id=item.document.document_id,
        document_sha256=item.document.raw_source_sha256,
        section_id=item.section_id,
        section_revision=item.section_revision,
        locator=fragment.locator,
        page=fragment.page,
        bbox=(
            cast(tuple[float, float, float, float], tuple(fragment.bbox))
            if fragment.bbox is not None
            else None
        ),
        coordinate_system=fragment.coordinate_system,
        quote=fragment.text,
        quote_sha256=fragment.text_sha256,
    )


def plan_discovery(
    located_by_document: Mapping[str, Sequence[LocatedFragment]],
) -> tuple[DiscoveryBatch, ...]:
    """Plan every nonempty fragment before any call; exceeding capacity fails closed."""
    batches: list[DiscoveryBatch] = []
    pending: list[DiscoverySection] = []
    pending_bytes = 0
    section_index = 0
    for document_id in sorted(located_by_document):
        for located, safe_text in _located_safe_texts(located_by_document[document_id]):
            text = located.fragment.text
            if not text.strip():
                continue
            source_excerpt(located)  # Validate all full citations before the first paid request.
            start = 0
            chunk_index = 0
            while start < len(text):
                end = start
                byte_count = 0
                while end < len(text):
                    size = len(text[end].encode("utf-8"))
                    if byte_count + size > MAX_BATCH_SOURCE_BYTES:
                        break
                    byte_count += size
                    end += 1
                if pending and (
                    pending_bytes + byte_count > MAX_BATCH_SOURCE_BYTES
                    or len(pending) >= MAX_BATCH_SECTIONS
                ):
                    batches.append(DiscoveryBatch(len(batches), tuple(pending)))
                    pending, pending_bytes = [], 0
                pending.append(
                    DiscoverySection(
                        f"s{section_index:06d}c{chunk_index:03d}",
                        located,
                        start,
                        end,
                        safe_text,
                    )
                )
                pending_bytes += byte_count
                start = end
                chunk_index += 1
            section_index += 1
    if pending:
        batches.append(DiscoveryBatch(len(batches), tuple(pending)))
    if not batches or len(batches) > MAX_DISCOVERY_BATCHES:
        raise ValueError("exhaustive discovery exceeds the authorized batch capacity")
    return tuple(batches)


def make_discovery_request(
    batch: DiscoveryBatch, *, tenant_id: str, task_id: str, run_id: str, snapshot_hash: str
) -> ModelRequest:
    return ModelRequest(
        call_id=hashlib.sha256(
            f"{tenant_id}:{task_id}:{run_id}:discovery:{batch.index}".encode()
        ).hexdigest(),
        tenant_id=tenant_id,
        review_task_id=task_id,
        node_run_id=f"{run_id}:discovery:{batch.index}:{snapshot_hash[:12]}",
        prompt_version=TASK0023_DISCOVERY_PROMPT_VERSION,
        system_instruction="Discover review questions only from the supplied untrusted fragments.",
        input_payload=batch.payload(),
        metadata={"snapshot_hash": snapshot_hash, "discovery_batch": batch.index},
    )


def _unique_source_span(text: str, quote: str) -> tuple[int, int] | None:
    """Resolve an exact quote, or whitespace-only formatting, to original offsets.

    No non-whitespace character is substituted or guessed. The fallback requires a
    unique normalized occurrence and returns the untouched source span, never the
    model's reformatted text. Repeated/overlapping occurrences remain ambiguous.
    """
    if not quote or not quote.strip():
        return None
    start = text.find(quote)
    if start >= 0:
        if text.find(quote, start + 1) >= 0:
            return None
        return start, start + len(quote)
    normalized_quote = "".join(character for character in quote if not character.isspace())
    offsets = [index for index, character in enumerate(text) if not character.isspace()]
    normalized_text = "".join(text[index] for index in offsets)
    start = normalized_text.find(normalized_quote)
    if start < 0 or normalized_text.find(normalized_quote, start + 1) >= 0:
        return None
    return offsets[start], offsets[start + len(normalized_quote) - 1] + 1


def validate_response(
    batch: DiscoveryBatch,
    response: ModelResponse,
    *,
    expected_call_id: str,
    profile: str,
    schema: dict[str, Any],
) -> tuple[tuple[CandidateFinding, ...], tuple[dict[str, Any], ...]]:
    Draft202012Validator(schema).validate(dict(response.content))
    if (
        response.call_id != expected_call_id
        or response.profile != profile
        or _hash(response.content) != response.response_hash
    ):
        raise ValueError("discovery response identity or hash mismatch")
    sections_by_alias = {item.section_key: item for item in batch.sections}
    candidates: list[CandidateFinding] = []
    rejections: list[dict[str, Any]] = []
    provenance = ModelCandidateProvenance(
        provider=response.provider,
        model=response.model,
        prompt_version=TASK0023_DISCOVERY_PROMPT_VERSION,
        response_hash=response.response_hash,
    )

    def rejected_candidate(
        reason: str, item: Mapping[str, Any], section: DiscoverySection | None
    ) -> dict[str, Any]:
        source_hash = source_unit_hash(section.located) if section is not None else None
        description = str(item["description"])
        category = str(item["category"])
        identity_hash = _hash(
            {
                "source_unit_hash": source_hash,
                "section_key": item["section_key"],
                "category": category,
                "normalized_description": "".join(description.split()),
                "quote_sha256": hashlib.sha256(str(item["quote"]).encode()).hexdigest(),
            }
        )
        return {
            "reason": reason,
            "candidate_identity_hash": identity_hash,
            "candidate_family_hash": (
                _candidate_family_hash(source_hash, category, description)
                if source_hash is not None
                else None
            ),
            "source_unit_hash": source_hash,
        }

    for item in response.content["findings"]:
        section = sections_by_alias.get(item["section_key"])
        if section is None:
            rejections.append(rejected_candidate("unknown_section", item, None))
            continue
        quote = item["quote"]
        safe = section.safe_text
        source_span = _unique_source_span(safe, quote)
        if source_span is None:
            rejections.append(
                rejected_candidate("quote_missing_or_ambiguous", item, section)
            )
            continue
        local_start, local_end = source_span
        absolute_start = section.start + local_start
        matched_quote = safe[local_start:local_end]
        original_quote = section.located.fragment.text[
            absolute_start : section.start + local_end
        ]
        # Safe string equality proves exact original offsets even where PII was masked.
        if len(original_quote) != len(matched_quote) or any(
            sent != original and sent != "*"
            for sent, original in zip(matched_quote, original_quote, strict=True)
        ):
            rejections.append(rejected_candidate("quote_mapping_invalid", item, section))
            continue
        excerpt = source_excerpt(section.located)
        category = cast(Category, item["category"])
        key = _hash(
            {
                "document_version_ref": section.located.document.document_version_ref,
                "category": category,
                "section_id": section.located.section_id,
                "quote_sha256": hashlib.sha256(original_quote.encode()).hexdigest(),
                "char_start": absolute_start,
                "problem_sha256": hashlib.sha256(
                    "".join(item["description"].split()).encode()
                ).hexdigest(),
            }
        )
        source = CandidateSource(
            origin="model",
            model_provenance=provenance,
            source_excerpts=(excerpt,),
            matched_reason=item["description"],
        )
        candidate_id = _hash(
            {
                "deduplication_key": key,
                "provenance": [candidate_source_identity(source)],
            }
        )
        candidates.append(
            CandidateFinding(
                candidate_id=candidate_id,
                origin="model",
                category=category,
                document_version_ref=section.located.document.document_version_ref,
                problem_key="llm_review_question",
                deduplication_key=key,
                source_excerpts=(excerpt,),
                matched_reason=item["description"],
                provenance=(source,),
            )
        )
    return tuple(candidates), tuple(rejections)


def merge_model_candidates(
    discovery: DiscoveryResult,
    model_candidates: Sequence[CandidateFinding],
) -> DiscoveryResult:
    """Fuse exact duplicate issues without manufacturing Skill coverage or legal status."""
    candidates = list(discovery.candidates)
    by_id = {item.candidate_id: index for index, item in enumerate(candidates)}

    def duplicate_key(candidate: CandidateFinding) -> tuple[object, ...]:
        return (
            candidate.category,
            candidate.document_version_ref,
            tuple(sorted(item.quote_sha256 for item in candidate.source_excerpts)),
            "".join(candidate.matched_reason.split()),
        )

    by_duplicate = {duplicate_key(item): index for index, item in enumerate(candidates)}
    for candidate in model_candidates:
        index = by_id.get(candidate.candidate_id)
        if index is None:
            index = by_duplicate.get(duplicate_key(candidate))
        if index is None:
            index = len(candidates)
            candidates.append(candidate)
            by_id[candidate.candidate_id] = index
            by_duplicate[duplicate_key(candidate)] = index
            continue
        previous = candidates[index]
        sources = tuple(dict.fromkeys((*previous.provenance, *candidate.provenance)))
        identity = {
            "deduplication_key": previous.deduplication_key,
            "provenance": sorted({candidate_source_identity(source) for source in sources}),
        }
        payload = previous.model_dump(mode="python")
        payload.update(candidate_id=_hash(identity), provenance=sources)
        candidates[index] = CandidateFinding.model_validate(payload)
    payload = discovery.model_dump(mode="json", exclude={"result_sha256"})
    payload["candidates"] = [
        item.model_dump(mode="json")
        for item in sorted(candidates, key=lambda item: item.candidate_id)
    ]
    payload["result_sha256"] = _hash(payload)
    return DiscoveryResult.model_validate_json(json.dumps(payload, ensure_ascii=False))
