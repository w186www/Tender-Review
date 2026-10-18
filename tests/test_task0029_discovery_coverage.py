"""TASK-0029 U08 preparation: per-batch saturation and coverage visibility."""

from __future__ import annotations

from test_semantic_batching import located_sections

from bidding_compliance.services import llm_candidate_discovery as llm


def one_batch():
    items = located_sections(3)
    mapping = {items[0].document.document_id: list(items)}
    batches = llm.plan_discovery(mapping)
    assert len(batches) == 1
    return batches[0]


def test_a_batch_at_the_per_call_cap_is_marked_saturated_not_complete():
    batch = one_batch()
    record = llm.batch_coverage(batch, llm.SATURATION_FINDING_LIMIT, 0)
    assert record["saturated"] is True
    assert record["status"] == "saturated"
    assert record["section_count"] == 3
    summary = llm.coverage_summary([record], section_count=3)
    assert summary["status"] == "partial"
    assert summary["saturated_batches"] == 1
    assert summary["saturated_batch_indices"] == [batch.index]
    assert summary["saturated_sections"] == 3
    assert summary["submitted_sections"] == 3
    assert summary["unsubmitted_sections"] == 0
    assert summary["truncated_batches"] == 0
    assert summary["accepted_candidates"] == llm.SATURATION_FINDING_LIMIT


def test_a_batch_with_a_rejected_candidate_is_partial_even_below_the_cap():
    batch = one_batch()
    record = llm.batch_coverage(batch, 1, 1)
    assert record["saturated"] is False
    assert record["status"] == "partial"
    summary = llm.coverage_summary([record], section_count=3)
    assert summary["status"] == "partial"
    assert summary["rejected_sections"] == 3
    assert summary["saturated_sections"] == 0
    assert summary["rejected_candidates"] == 1


def test_all_accepted_batches_below_the_cap_are_complete():
    batch = one_batch()
    record = llm.batch_coverage(batch, 2, 0)
    assert record["status"] == "completed"
    summary = llm.coverage_summary([record], section_count=3)
    assert summary["status"] == "complete"
    assert summary["completed_batches"] == 1
    assert summary["partial_batches"] == 0
    assert summary["saturated_batches"] == 0


def test_coverage_deduplicates_parent_child_units_and_counts_candidate_recovery():
    batch = one_batch()
    source_hash = llm.source_unit_hash(batch.sections[0].located)
    parent = llm.batch_coverage(batch, 0, 1, subdivided=True)
    parent.update(
        response_hash="response-parent",
        rejection_summaries=[
            {
                "reason": "quote_missing_or_ambiguous",
                "candidate_identity_hash": "candidate-a",
                "candidate_family_hash": "family-a",
                "source_unit_hash": source_hash,
            },
            {
                "reason": "quote_missing_or_ambiguous",
                "candidate_identity_hash": "candidate-a",
                "candidate_family_hash": "family-a",
                "source_unit_hash": source_hash,
            },
        ],
    )
    child = llm.batch_coverage(
        llm.DiscoveryBatch(10, batch.sections[:1], parent_index=batch.index, depth=1),
        1,
        0,
    )
    child.update(
        response_hash="response-child",
        accepted_candidate_family_hashes=["family-a"],
    )

    summary = llm.coverage_summary([parent, child], section_count=4)

    assert summary["submitted_sections"] == 3
    assert summary["unsubmitted_sections"] == 0
    assert summary["rejected_candidate_attempts"] == 2
    assert summary["rejected_candidate_count"] == 1
    assert summary["rejected_source_unit_count"] == 1
    assert summary["rejection_reason_counts"] == {"quote_missing_or_ambiguous": 1}
    assert summary["recovered_candidate_families"] == 1
    assert summary["unrecovered_candidate_families"] == 0
    assert summary["recovered_source_unit_count"] == 1


def test_failed_subdivision_attempt_and_truncation_are_separate_and_deduplicated():
    batch = one_batch()
    failed_parent = llm.batch_coverage(batch, 0, 0, subdivided=True)
    failed_parent.update(failure_code="timeout", response_hash=None)
    child = llm.batch_coverage(
        llm.DiscoveryBatch(10, batch.sections[:1], parent_index=batch.index, depth=1),
        1,
        0,
    )
    child.update(response_hash="response-child", finish_reason="length")
    child2 = llm.batch_coverage(
        llm.DiscoveryBatch(11, batch.sections[1:], parent_index=batch.index, depth=1),
        1,
        0,
    )
    child2.update(response_hash="response-child-2", finish_reason="stop")

    summary = llm.coverage_summary([failed_parent, child, child2], section_count=3)

    assert summary["failed_batch_attempts"] == 1
    assert summary["failed_batches"] == 0
    assert summary["failed_sections"] == 0
    assert summary["truncated_batches"] == 1
    assert summary["submitted_sections"] == 3
    assert summary["unsubmitted_sections"] == 0


def test_subdivision_splits_at_section_boundaries_and_respects_depth_and_size():
    batch = one_batch()
    children = llm.subdivide_batch(batch, 10)
    assert [child.index for child in children] == [10, 11]
    assert [len(child.sections) for child in children] == [1, 2]
    assert all(
        child.parent_index == batch.index and child.depth == 1 for child in children
    )
    deep = llm.DiscoveryBatch(
        20, batch.sections, parent_index=0, depth=llm.MAX_SUBDIVISION_DEPTH
    )
    assert llm.subdivide_batch(deep, 30) == ()
    single = llm.DiscoveryBatch(21, batch.sections[:1])
    halves = llm.subdivide_batch(single, 30)
    assert [child.index for child in halves] == [30, 31]
    assert all(child.depth == 1 and child.parent_index == 21 for child in halves)
    left, right = (child.sections[0] for child in halves)
    original = single.sections[0]
    assert left.start == original.start
    assert left.end == right.start
    assert right.end == original.end
    assert left.located is right.located is original.located
    assert llm.source_unit_hash(left.located) == llm.source_unit_hash(right.located)
    assert left.section_key != right.section_key
    assert left.section_key.startswith("s900030c")

    too_short = llm.DiscoveryBatch(
        22,
        (
            llm.DiscoverySection(
                "s000000c000",
                original.located,
                original.start,
                original.start + 7,
                original.safe_source_text,
            ),
        ),
    )
    assert llm.subdivide_batch(too_short, 32) == ()
