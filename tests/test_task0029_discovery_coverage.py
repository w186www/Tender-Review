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
    assert summary["accepted_candidates"] == llm.SATURATION_FINDING_LIMIT


def test_a_batch_with_a_rejected_candidate_is_partial_even_below_the_cap():
    batch = one_batch()
    record = llm.batch_coverage(batch, 1, 1)
    assert record["saturated"] is False
    assert record["status"] == "partial"
    summary = llm.coverage_summary([record], section_count=3)
    assert summary["status"] == "partial"
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
    assert llm.subdivide_batch(single, 30) == ()
