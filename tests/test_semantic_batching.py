"""Batched semantic analysis: deterministic split, idempotent resume and fail-closed limits."""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from test_rules_skills import freeze

from bidding_compliance.domain.rules.engine import discover
from bidding_compliance.domain.rules.models import DocumentVersionRef, Fragment, LocatedFragment
from bidding_compliance.graph import review
from bidding_compliance.model_gateway.contracts import (
    ModelPolicy,
    ModelResponse,
    ModelUsage,
)
from bidding_compliance.model_gateway.errors import GatewayErrorCode, ModelGatewayError
from bidding_compliance.services import llm_candidate_discovery as llm
from bidding_compliance.services.real_ai_runtime import AuthorizedTenderMinimizer
from bidding_compliance.services.review_contracts import SEMANTIC_EVIDENCE_PROMPT_VERSION


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def located_sections(count: int) -> tuple[LocatedFragment, ...]:
    document = DocumentVersionRef(
        document_id="doc-a",
        raw_source_sha256="a" * 64,
        parse_version=1,
        context_version=1,
        fragments_sha256="b" * 64,
        document_version_ref="doc-version:sha256:" + "c" * 64,
        fragment_count=count,
    )
    items = []
    for index in range(count):
        text = f"第{index}条 合成条款文本，需要核验其合理性与程序。"
        items.append(
            LocatedFragment(
                document,
                f"section-{index:03d}",
                1,
                Fragment(
                    locator=f"paragraph:{index}",
                    page=None,
                    bbox=None,
                    coordinate_system="ooxml",
                    kind="paragraph",
                    section="正文",
                    text=text,
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    source="native",
                    confidence=None,
                    table=None,
                    row=None,
                    column=None,
                ),
            )
        )
    return tuple(items)


def model_candidates(count: int):
    """Real model candidates: validation derives every identity from trusted storage."""
    snapshot, mapping = freeze(located_sections(count))
    rules = discover(snapshot, mapping)
    (batch,) = llm.plan_discovery(mapping)
    request = llm.make_discovery_request(
        batch, tenant_id="tenant-a", task_id="task-a", run_id="run-a", snapshot_hash="f" * 64
    )
    accepted = []
    for start in range(0, count, 3):
        findings = [
            {
                "section_key": section.section_key,
                "quote": section.safe_text[:10],
                "category": "contract",
                "description": f"疑点 {section.section_key} 需要人工核验。",
            }
            for section in batch.sections[start : start + 3]
        ]
        content = {"schema_version": "v1alpha1", "findings": findings}
        response = ModelResponse(
            call_id=request.call_id,
            provider="unit-provider",
            model="unit-model",
            profile="unit",
            content=content,
            usage=ModelUsage(1, 1, 0.0),
            latency_ms=0,
            response_hash=digest(content),
            finish_reason="stop",
        )
        items, rejected = llm.validate_response(
            batch,
            response,
            expected_call_id=request.call_id,
            profile="unit",
            schema=llm.discovery_schema(),
        )
        assert not rejected, rejected
        accepted.extend(items)
    return llm.merge_model_candidates(rules, accepted)


def zero_candidate_result(discovery):
    """A valid discovery result with no candidates and zeroed skill counts."""
    empty = discovery.model_copy(
        update={
            "candidates": (),
            "skill_coverages": tuple(
                item.model_copy(update={"candidates_found": 0})
                for item in discovery.skill_coverages
            ),
        }
    )
    payload = empty.model_dump(mode="json", exclude={"result_sha256"})
    return empty.model_copy(update={"result_sha256": digest(payload)})


class FakeGateway:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness

    async def generate_structured(self, request, schema, policy):
        index = request.metadata["semantic_batch"]
        self.harness.calls.append((index, request.call_id))
        failure = self.harness.failures.get(index)
        if failure is not None:
            raise failure
        if self.harness.v2:
            self.harness.outbound.append(
                AuthorizedTenderMinimizer(frozenset({"a" * 64}))(
                    request.input_payload, policy.data_policy
                )
            )
        identifiers = [
            item["candidate_id"]
            for item in request.input_payload["document_candidates"]["candidates"]
        ]
        content = {
            "schema_version": "v1alpha1",
            "findings": [
                {
                    "candidate_id": identifier,
                    "assessment": "potential_issue",
                    "title": "待核验疑点",
                    "description": "需人工核对原文与适用法规。",
                    "severity": "medium",
                    "source_quote_sha256": [],
                    "legal_evidence_ids": [],
                    "recommendation": "由审查员核验。",
                    "reasoning_summary": "合成夹具。",
                }
                for identifier in identifiers
            ],
        }
        if self.harness.v2:
            content["schema_version"] = "v1alpha2"
            for finding in content["findings"]:
                raw = next(
                    item
                    for item in request.input_payload["document_candidates"]["candidates"]
                    if item["candidate_id"] == finding["candidate_id"]
                )
                hashes = sorted(
                    {
                        item["quote_sha256"]
                        for item in [
                            *raw["source_excerpts"],
                            *request.input_payload["candidate_related_document_evidence"][
                                finding["candidate_id"]
                            ],
                        ]
                    }
                )
                finding.update(
                    source_quote_sha256=hashes,
                    issue_identity={
                        "subject": "付款",
                        "mechanism": "条件不明",
                        "condition": "验收后",
                    },
                    duplicate_of_candidate_id=None,
                    context_review={
                        "reviewed_quote_sha256": hashes,
                        "counterevidence_quote_sha256": [],
                        "conclusion": "supported",
                    },
                    legal_assessments=[],
                )
        return ModelResponse(
            call_id=request.call_id,
            provider="unit-provider",
            model="unit-model",
            profile=policy.profile,
            content=content,
            usage=ModelUsage(10, 5, 0.001),
            latency_ms=1,
            response_hash=digest(content),
            finish_reason="stop",
        )


class Harness:
    """Minimal graph harness: only the three artifacts the semantic node reads."""

    def __init__(
        self,
        *,
        candidates: int,
        failures=None,
        zero_candidates: bool = False,
        v2: bool = False,
        related=None,
    ) -> None:
        self.v2 = v2
        self.related = related or []
        self.outbound = []
        self.context = (
            {
                "region": "安徽省滁州市",
                "procurement_type": "enterprise",
                "project_type": "工程",
                "procurement_method": "公开招标",
                "buyer_type": "企业",
                "subject_type": "施工",
                "legal_frameworks": ["tendering"],
            }
            if v2
            else {"procurement_type": "enterprise"}
        )
        self.calls: list[tuple[int, str]] = []
        self.failures = failures or {}
        self.saved: list[SimpleNamespace] = []
        self.nodes: dict = {}
        discovery = model_candidates(1) if zero_candidates else model_candidates(candidates)
        if zero_candidates:
            discovery = zero_candidate_result(discovery)
        assert len(discovery.candidates) == (0 if zero_candidates else candidates)
        self.artifacts = {
            "discovery:ref": discovery.model_dump(mode="json"),
            "retrieval:ref": {
                "publication_id": "publication-a",
                "revision_id": "revision-a",
                "results": [
                    {"work_item_id": item.candidate_id, "result": {"hits": []}}
                    for item in discovery.candidates
                ],
            },
            "context:ref": {
                "context_sha256": "e" * 64,
                "context": self.context,
            },
        }

    def node(self, monkeypatch):
        harness = self

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def scalars(self, statement):
                kind = statement._where_criteria[-1].right.value
                return [item for item in harness.saved if item.kind == kind]

            def get(self, *_):
                return SimpleNamespace(status="running")

            def commit(self):
                pass

        def store(session, tenant, task, run_id, kind, content):
            reference = kind + ":" + digest(content)
            harness.artifacts[reference] = content
            if not any(item.kind == kind for item in harness.saved):
                harness.saved.append(
                    SimpleNamespace(
                        kind=kind,
                        content=content,
                        content_hash=digest(content),
                        reference=reference,
                    )
                )
            return reference

        class Graph:
            def add_node(self, name, action, **_):
                harness.nodes[name] = action

            def add_edge(self, *_):
                pass

            def add_conditional_edges(self, *_):
                pass

            def compile(self, **_):
                return harness.nodes

        monkeypatch.setattr(review, "StateGraph", lambda *_: Graph())
        monkeypatch.setattr(review, "_load_run", lambda *_: run_row())
        monkeypatch.setattr(
            review,
            "_snapshot_inputs",
            lambda *_: (
                {
                    "document_requests": [{"raw_source_sha256": "a" * 64}],
                    "input_snapshot": {"documents": []},
                    "model_profile": "unit",
                    "prompt_version": SEMANTIC_EVIDENCE_PROMPT_VERSION if harness.v2 else "unit",
                    "project_context_sha256": "e" * 64,
                    "model_policy": {"profile": "unit"},
                },
                harness.context,
            ),
        )
        monkeypatch.setattr(
            review, "read_artifact", lambda _s, _t, ref, **_: harness.artifacts[ref]
        )
        monkeypatch.setattr(
            review, "related_document_context", lambda *_, **__: list(harness.related)
        )
        monkeypatch.setattr(review, "put_artifact", store)
        review.build_review_graph(
            session_factory=Session,
            principal=SimpleNamespace(tenant_id="tenant-a", user_id="u"),
            gateway=FakeGateway(harness),
            model_policy=ModelPolicy("unit", 5, max_input_tokens=32768, max_output_tokens=4096),
            checkpointer=object(),
            enable_llm_discovery=True,
        )
        state = review.initial_state(
            tenant_id="tenant-a",
            project_id="project-a",
            review_task_id="task-a",
            run_id="run-a",
            document_refs=[],
        )
        state.update(
            status="running",
            discovery_ref="discovery:ref",
            retrieval_results_ref="retrieval:ref",
            project_context_ref="context:ref",
        )
        return harness.nodes["semantic_analysis"](state)

    def kinds(self) -> set[str]:
        return {item.kind for item in self.saved}

    def payload(self, kind: str = "model_analysis") -> dict:
        for item in self.saved:
            if item.kind == kind:
                return item.content
        raise AssertionError(f"artifact {kind} was not stored")


def run_row():
    return SimpleNamespace(
        status="running",
        review_task_id="task-a",
        run_id="run-a",
        project_id="project-a",
        snapshot_hash="f" * 64,
        snapshot={"document_requests": []},
        publication_id="publication-a",
        revision_id="revision-a",
        retry_count=0,
    )


def test_batches_are_ordered_by_candidate_id_and_split_deterministically():
    items = tuple(SimpleNamespace(candidate_id=f"id-{index:02d}") for index in range(12))
    forward = review._semantic_batches(items)
    backward = review._semantic_batches(tuple(reversed(items)))
    assert [len(batch) for batch in forward] == [8, 4]
    assert [tuple(item.candidate_id for item in batch) for batch in forward] == [
        tuple(item.candidate_id for item in batch) for batch in backward
    ]


def test_single_batch_keeps_the_historical_call_identity():
    call_id, suffix = review._semantic_call_parts("t", "k", "r", single=True, index=0)
    assert suffix == "semantic"
    assert call_id == hashlib.sha256(b"t:k:r:semantic").hexdigest()
    assert review._semantic_batch_kind(0, single=True) == "semantic_analysis_batch_0"

    batched_id, batched_suffix = review._semantic_call_parts("t", "k", "r", single=False, index=3)
    assert batched_suffix == "semantic:3"
    assert batched_id == hashlib.sha256(b"t:k:r:semantic:3").hexdigest()
    assert review._semantic_batch_kind(3, single=False) == "semantic_analysis_batch_3"


def test_single_batch_matches_the_legacy_artifact_shape(monkeypatch):
    harness = Harness(candidates=3)
    result = asyncio.run(harness.node(monkeypatch))
    assert result["model_findings_ref"]
    assert [index for index, _ in harness.calls] == [0]
    payload = harness.payload()
    assert payload["prompt_version"] == "unit"
    assert "semantic_batches" not in payload
    assert len(payload["content"]["findings"]) == 3
    assert payload["usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "estimated_cost": 0.001,
    }


def test_many_candidates_split_into_cached_batches_and_aggregate(monkeypatch):
    harness = Harness(candidates=19)
    result = asyncio.run(harness.node(monkeypatch))
    assert result["model_findings_ref"]
    assert [index for index, _ in harness.calls] == [0, 1, 2]
    payload = harness.payload()
    assert len(payload["content"]["findings"]) == 19
    assert [item["batch_index"] for item in payload["semantic_batches"]] == [0, 1, 2]
    assert payload["usage"]["input_tokens"] == 30
    assert payload["usage"]["output_tokens"] == 15
    assert abs(payload["usage"]["estimated_cost"] - 0.003) < 1e-9
    assert harness.kinds() >= {
        "semantic_analysis_batch_0",
        "semantic_analysis_batch_1",
        "semantic_analysis_batch_2",
    }


def test_resume_reuses_accepted_batches_and_retries_only_the_failure(monkeypatch):
    harness = Harness(
        candidates=19,
        failures={
            1: ModelGatewayError(GatewayErrorCode.TIMEOUT, "unit batch timeout", retryable=True)
        },
    )
    first = asyncio.run(harness.node(monkeypatch))
    assert first["status"] == "failed"
    assert first["errors"][0]["code"] == "timeout"
    assert first["errors"][0]["retryable"] is True
    assert [index for index, _ in harness.calls] == [0, 1]
    assert "semantic_analysis_batch_0" in harness.kinds()
    assert "model_analysis" not in harness.kinds()

    harness.failures = {}
    harness.calls.clear()
    second = asyncio.run(harness.node(monkeypatch))
    assert second["model_findings_ref"]
    # Batch 0 is served from its recorded artifact; only batches 1 and 2 are requested.
    assert [index for index, _ in harness.calls] == [1, 2]
    assert len(harness.payload()["content"]["findings"]) == 19


@pytest.mark.parametrize("count,v2", [(3, False), (19, False), (3, True), (9, True)])
def test_repeated_run_is_idempotent_and_costs_nothing(monkeypatch, count, v2):
    harness = Harness(candidates=count, v2=v2)
    asyncio.run(harness.node(monkeypatch))
    harness.calls.clear()
    asyncio.run(harness.node(monkeypatch))
    assert harness.calls == []


def test_provider_contract_failure_keeps_its_code_and_stores_no_aggregate(monkeypatch):
    harness = Harness(
        candidates=3,
        failures={0: ModelGatewayError(GatewayErrorCode.RESPONSE_INVALID, "unit contract failure")},
    )
    result = asyncio.run(harness.node(monkeypatch))
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "response_invalid"
    assert "model_analysis" not in harness.kinds()


def test_batch_capacity_stays_within_the_authorized_call_budget():
    assert review.MAX_SEMANTIC_BATCHES == review.MAX_CANDIDATES_FOR_REVIEW == 100
    legacy = tuple(SimpleNamespace(candidate_id=f"id-{i:03d}") for i in range(100))
    assert len(review._semantic_batches(legacy)) == 13


def test_cached_batch_refuses_changed_retrieval_inputs_before_any_new_call(monkeypatch):
    harness = Harness(candidates=3, v2=True)
    asyncio.run(harness.node(monkeypatch))
    harness.calls.clear()
    harness.artifacts["retrieval:ref"]["results"][0]["result"]["changed"] = True
    with pytest.raises(ValueError, match="cache provenance mismatch"):
        asyncio.run(harness.node(monkeypatch))
    assert harness.calls == []


def test_legacy_single_aggregate_is_not_mistaken_for_a_bound_batch(monkeypatch):
    harness = Harness(candidates=3)
    asyncio.run(harness.node(monkeypatch))
    harness.saved = [item for item in harness.saved if item.kind != "semantic_analysis_batch_0"]
    harness.calls.clear()
    with pytest.raises(ValueError, match="automatic replay is forbidden"):
        asyncio.run(harness.node(monkeypatch))
    assert harness.calls == []


def test_unknown_and_duplicate_model_references_are_flagged_for_review(monkeypatch):
    """Batched or not, an unusable model reference must never resolve silently."""
    from test_llm_candidate_discovery import graph_harness

    nodes, state, artifacts, _, _ = graph_harness(monkeypatch)
    discovered = asyncio.run(nodes["llm_candidate_discovery"](state))
    (candidate,) = artifacts[discovered["discovery_ref"]]["candidates"]
    source = candidate["source_excerpts"][0]
    entry = {
        "candidate_id": candidate["candidate_id"],
        "assessment": "potential_issue",
        "title": "付款疑点",
        "description": "需核验付款条件",
        "severity": "medium",
        "source_quote_sha256": [source["quote_sha256"]],
        "legal_evidence_ids": [],
        "recommendation": "由人工确认适用法律与付款条件",
        "reasoning_summary": "尚无法规证据",
    }
    artifacts["model"] = {
        "content": {"findings": [entry, dict(entry), {**entry, "candidate_id": "9" * 64}]}
    }
    artifacts["retrieval"] = {
        "results": [{"work_item_id": candidate["candidate_id"], "result": {"hits": []}}]
    }
    monkeypatch.setattr(
        review,
        "verify_document_excerpt",
        lambda *_a, **_k: {
            "evidence_id": "b" * 64,
            "kind": "document",
            "title": "招标原文",
            "quote": source["quote"],
            "source_uri": "artifact://document/" + "a" * 64,
            "source_hash": "a" * 64,
            "page": None,
            "locator": source["locator"],
            "version_status": "unverified",
        },
    )
    state.update(discovered, model_findings_ref="model", retrieval_results_ref="retrieval")
    merged = nodes["merge_findings"](state)
    (finding,) = artifacts[merged["rule_findings_ref"]]["findings"]
    assert "invalid_reference" in {item["assessment"] for item in finding.get("conflicts", [])}
    # An unusable model reference is never a conclusion: the candidate still needs review.
    assert finding["evidence_status"] == "insufficient_evidence"
    state.update(merged)
    checked = nodes["evidence_check"](state)
    assert checked["status"] == "waiting_human"
    assert checked["pending_review_ids"] == [finding["finding_id"]]


def test_zero_candidates_skip_paid_semantic_calls_and_store_empty_analysis(monkeypatch):
    harness = Harness(candidates=0, zero_candidates=True)
    result = asyncio.run(harness.node(monkeypatch))
    assert harness.calls == []
    assert result["model_findings_ref"]
    payload = harness.payload("model_analysis")
    assert payload["zero_candidate"] is True
    assert payload["content"] == {"schema_version": "v1alpha1", "findings": []}
    assert payload["usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost": 0.0,
    }
