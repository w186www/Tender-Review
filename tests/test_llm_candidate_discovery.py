"""TASK-0023 independent discovery, immutable evidence and graph integration checks."""

import asyncio
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_rules_skills import freeze, located

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.domain.rules.engine import discover
from bidding_compliance.domain.rules.models import CandidateSource, DiscoveryResult
from bidding_compliance.graph import review
from bidding_compliance.model_gateway.contracts import ModelPolicy, ModelResponse, ModelUsage
from bidding_compliance.model_gateway.errors import GatewayErrorCode, ModelGatewayError
from bidding_compliance.services import evidence_checker
from bidding_compliance.services import llm_candidate_discovery as llm
from bidding_compliance.services.review_contracts import FULLTEXT_V1_PROMPT_VERSION


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def response_for(batch, *, quote=None, section_key=None, description="付款安排需进一步核验"):
    section = batch.sections[0]
    content = {
        "schema_version": "v1alpha1",
        "findings": [
            {
                "section_key": section_key or section.section_key,
                "quote": quote or section.safe_text[:12],
                "category": "contract",
                "description": description,
            }
        ],
    }
    request = llm.make_discovery_request(
        batch,
        tenant_id="tenant-a",
        task_id="task-a",
        run_id="run-a",
        snapshot_hash="a" * 64,
    )
    return ModelResponse(
        call_id=request.call_id,
        provider="unit-test-provider",
        model="unit-test-model",
        profile="test",
        content=content,
        usage=ModelUsage(8, 8, 0.0),
        latency_ms=0,
        response_hash=digest(content),
        finish_reason="stop",
    )


def validate(batch, response):
    return llm.validate_response(
        batch,
        response,
        expected_call_id=response_for(batch).call_id,
        profile="test",
        schema=llm.discovery_schema(),
    )


def test_zero_skill_candidates_still_produce_bound_model_candidate(monkeypatch):
    text = "采购款项在设备通过验收且收到发票后支付。"
    snapshot, mapping = freeze((located(text),))
    rules = discover(snapshot, mapping)
    assert rules.candidates == ()
    (batch,) = llm.plan_discovery(mapping)
    accepted, rejected = validate(batch, response_for(batch))
    assert rejected == ()
    merged = llm.merge_model_candidates(rules, accepted)
    (candidate,) = merged.candidates
    assert candidate.origin == "model"
    assert candidate.skill_id is None and candidate.rule_id is None
    assert all(item.candidates_found == 0 for item in merged.skill_coverages)
    (source,) = candidate.source_excerpts
    assert source.quote == text
    assert source.quote_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert llm.merge_model_candidates(merged, accepted).candidates == merged.candidates
    assert DiscoveryResult.model_validate_json(merged.model_dump_json()) == merged
    Draft202012Validator(
        json.loads(
            (llm.ROOT / "contracts/schemas/candidate-discovery-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
    ).validate(merged.model_dump(mode="json"))
    original = mapping["doc-a"][0]
    monkeypatch.setattr(
        evidence_checker.documents,
        "find_document",
        lambda *_: SimpleNamespace(
            status="ready",
            sha256=source.document_sha256,
            parse_version=1,
        ),
    )
    monkeypatch.setattr(
        evidence_checker.documents,
        "sections",
        lambda *_: SimpleNamespace(
            parse_version=1,
            items=[
                SimpleNamespace(
                    section_id=source.section_id,
                    revision=source.section_revision,
                    source_hash=source.document_sha256,
                    effective=original.fragment,
                )
            ],
        ),
    )
    assert (
        evidence_checker.verify_document_excerpt(
            object(),
            object(),
            project_id="project-a",
            candidate=candidate,
            excerpt=source,
            expected_document_refs={source.document_id: candidate.document_version_ref},
        )
        is not None
    )


def test_distinct_model_questions_on_one_excerpt_keep_distinct_problem_keys():
    text = "采购款项在设备通过验收且收到发票后支付。"
    snapshot, mapping = freeze((located(text),))
    rules = discover(snapshot, mapping)
    (batch,) = llm.plan_discovery(mapping)
    first, first_rejected = validate(
        batch,
        response_for(batch, description="付款条件是否与合同约定一致"),
    )
    second, second_rejected = validate(
        batch,
        response_for(batch, description="验收后付款节点是否明确"),
    )
    repeated, repeated_rejected = validate(
        batch,
        response_for(batch, description="付款条件是否与合同约定一致"),
    )

    assert not first_rejected + second_rejected + repeated_rejected
    assert first[0].source_excerpts[0].locator == second[0].source_excerpts[0].locator
    assert first[0].problem_key != second[0].problem_key
    assert first[0].problem_key == repeated[0].problem_key
    combined = llm.merge_model_candidates(rules, (*first, *second, *repeated))
    assert len(combined.candidates) == 2


@pytest.mark.parametrize(
    ("quote", "section_key", "reason"),
    [
        ("此段引文并不存在", None, "quote_missing_or_ambiguous"),
        ("收到发票后支付", "s999999c000", "unknown_section"),
        ("收到发票后支付", None, "quote_missing_or_ambiguous"),
    ],
)
def test_fabricated_unknown_and_ambiguous_references_are_rejected(quote, section_key, reason):
    _, mapping = freeze((located("收到发票后支付；收到发票后支付。"),))
    (batch,) = llm.plan_discovery(mapping)
    accepted, rejected = validate(batch, response_for(batch, quote=quote, section_key=section_key))
    assert not accepted
    assert len(rejected) == 1
    assert rejected[0]["reason"] == reason
    assert len(rejected[0]["candidate_identity_hash"]) == 64
    if reason == "unknown_section":
        assert rejected[0]["source_unit_hash"] is None
        assert rejected[0]["candidate_family_hash"] is None
    else:
        assert len(rejected[0]["source_unit_hash"]) == 64
        assert len(rejected[0]["candidate_family_hash"]) == 64


def test_overlapping_duplicate_quote_is_rejected_as_ambiguous():
    _, mapping = freeze((located("aaaaa"),))
    (batch,) = llm.plan_discovery(mapping)
    accepted, rejected = validate(batch, response_for(batch, quote="aaaa"))
    assert not accepted
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "quote_missing_or_ambiguous"
    assert len(rejected[0]["candidate_identity_hash"]) == 64


@pytest.mark.parametrize(
    ("source", "quote"),
    [
        ("收到发票后\n支付货款。", "收到发票后支付货款。"),
        ("收到发票后支付货款。", "收到发票后 支付货款。"),
        ("收到发票后\u3000支付货款。", "收到发票后支付货款。"),
    ],
)
def test_whitespace_only_quote_mapping_preserves_original_evidence(source, quote):
    _, mapping = freeze((located(source),))
    (batch,) = llm.plan_discovery(mapping)
    accepted, rejected = validate(batch, response_for(batch, quote=quote))
    assert rejected == ()
    assert len(accepted) == 1
    excerpt = accepted[0].source_excerpts[0]
    assert excerpt.quote == source
    assert excerpt.quote_sha256 == hashlib.sha256(source.encode()).hexdigest()


@pytest.mark.parametrize(
    ("source", "quote"),
    [
        ("验收后付款。验收 后付款。", "验收\n后付款。"),
        ("收到发票后支付货款。", "收到发票前支付货款。"),
        ("收到发票后支付货款。", "收到发票后，支付货款。"),
    ],
)
def test_quote_mapping_still_rejects_ambiguity_and_non_whitespace_edits(source, quote):
    _, mapping = freeze((located(source),))
    (batch,) = llm.plan_discovery(mapping)
    accepted, rejected = validate(batch, response_for(batch, quote=quote))
    assert not accepted
    assert rejected[0]["reason"] == "quote_missing_or_ambiguous"


def test_quote_span_mapping_never_crosses_sections_or_accepts_blank_text():
    assert llm._unique_source_span("验收后付款。", " \n\t") is None
    assert llm._unique_source_span("验收后", "验收后付款。") is None
    assert llm._unique_source_span("aaaaa", "aaaa") is None


def test_redaction_maps_exact_safe_quote_to_original_without_sending_contacts():
    text = "联系人：张某某，电话13812345678，邮箱review@example.test。采购款项验收后支付。"
    _, mapping = freeze((located(text),))
    (batch,) = llm.plan_discovery(mapping)
    safe = batch.sections[0].safe_text
    assert len(safe) == len(text)
    assert llm.redact_discovery_text(safe) == safe
    assert all(value not in safe for value in ("张某某", "13812345678", "review@example.test"))
    accepted, _ = validate(batch, response_for(batch, quote=safe))
    assert accepted[0].source_excerpts[0].quote == text
    assert "13812345678" not in json.dumps(batch.payload(), ensure_ascii=False)


@pytest.mark.parametrize(
    "text",
    [
        "联系电话：(022)12345678",
        "联系电话：（022） 1234 5678",
        "联系电话：022 1234-5678 转123",
        "手机：138 1234 5678",
        "手机：+86 138-1234-5678",
        "客服400-123-4567",
        "客服800 123 4567",
        "电话：12345678",
        "银行账号：6222 1234 5678 1234",
        "系统账号：operator123",
        "联系人： 李某某",
        "姓名：王某某",
    ],
)
def test_formatted_contact_and_account_values_are_masked_with_clean_preflight(text):
    masked = llm.redact_discovery_text(text)
    assert len(masked) == len(text)
    assert "*" in masked
    assert llm.redact_discovery_text(masked) == masked
    assert sum(llm.pii_preflight(text).values()) > 0
    assert sum(llm.pii_preflight(masked).values()) == 0


@pytest.mark.parametrize(
    "text",
    [
        "项目负责人应具有一级建造师证书。",
        "负责人：应到场。",
        "联系人：应具备资格。",
        "负责人须参加答疑会议。",
    ],
)
def test_redaction_preserves_substantive_personnel_requirements(text):
    assert llm.redact_discovery_text(text) == text


def test_locator_natural_order_preserves_adjacent_table_name_mask_and_quote_mapping():
    items = tuple(
        located(
            text,
            locator=f"ooxml/body/2/table/row/0/cell/{column}",
            kind="table_cell",
            table=2,
            row=0,
            column=column,
        )
        for column, text in ((2, "工作内容"), (1, "张某某、李某某"), (0, "联系人"), (3, "设备维护"))
    )
    snapshot, mapping = freeze(items)
    # section IDs/input order are deliberately unrelated to the body locator order.
    mapping["doc-a"] = tuple(reversed(mapping["doc-a"]))
    (batch,) = llm.plan_discovery(mapping)
    assert [section.located.fragment.column for section in batch.sections] == [0, 1, 2, 3]
    name = batch.sections[1]
    assert name.safe_text == "*" * len(name.text)
    assert batch.sections[3].safe_text == "设备维护"
    response = response_for(batch, section_key=name.section_key, quote=name.safe_text)
    accepted, rejected = validate(batch, response)
    assert not rejected
    assert accepted[0].source_excerpts[0].quote == "张某某、李某某"
    assert accepted[0].document_version_ref == snapshot.documents[0].document_version_ref


def test_locator_numbers_sort_as_document_sequence_and_keep_role_requirement_cell():
    items = (
        located("第十段正文", locator="ooxml/body/10/paragraph"),
        located("第二段正文", locator="ooxml/body/2/paragraph"),
        located(
            "负责人",
            locator="ooxml/body/3/table/row/0/cell/0",
            kind="table_cell",
            table=3,
            row=0,
            column=0,
        ),
        located(
            "应具有一级建造师证书",
            locator="ooxml/body/3/table/row/0/cell/1",
            kind="table_cell",
            table=3,
            row=0,
            column=1,
        ),
    )
    _, mapping = freeze(items)
    (batch,) = llm.plan_discovery(mapping)
    assert [section.text for section in batch.sections] == [
        "第二段正文",
        "负责人",
        "应具有一级建造师证书",
        "第十段正文",
    ]
    assert batch.sections[2].safe_text == batch.sections[2].text


def test_all_fragments_have_exhaustive_bounded_coverage_and_overflow_fails_closed():
    items = tuple(
        located("采购说明" + str(index) + "。" * 2000, locator=f"paragraph:{index}")
        for index in range(5)
    )
    snapshot, mapping = freeze(items)
    batches = llm.plan_discovery(mapping)
    # The batch count follows from the authorized batch capacity, not a fixed number.
    per_fragment = len(items[0].fragment.text.encode())
    per_batch = llm.MAX_BATCH_SOURCE_BYTES // per_fragment
    assert len(batches) == -(-5 // per_batch)
    assert per_batch >= 1
    assert sum(len(batch.sections) for batch in batches) == snapshot.documents[0].fragment_count
    assert all(
        sum(len(section.text.encode()) for section in batch.sections) <= llm.MAX_BATCH_SOURCE_BYTES
        for batch in batches
    )
    records = [section.coverage() for batch in batches for section in batch.sections]
    assert all(record["source_sha256"] and record["locator"] for record in records)
    # Overflow still fails closed: one fragment per batch exceeds the batch ceiling.
    oversized = "。" * (llm.MAX_BATCH_SOURCE_BYTES // 3 - 100)
    _, overflowing = freeze(
        tuple(
            located("采购说明" + str(index) + oversized, locator=f"paragraph:{index}")
            for index in range(llm.MAX_DISCOVERY_BATCHES + 1)
        )
    )
    with pytest.raises(ValueError, match="authorized batch capacity"):
        llm.plan_discovery(overflowing)


def test_rule_serialization_and_historical_hash_are_unchanged():
    snapshot, mapping = freeze((located("投标人必须在本市注册。", section="投标人资格要求"),))
    result = discover(snapshot, mapping)
    encoded = result.model_dump(mode="json")
    candidate = encoded["candidates"][0]
    assert "origin" not in candidate
    assert "origin" not in candidate["provenance"][0]
    assert "model_provenance" not in candidate["provenance"][0]
    assert encoded["result_sha256"] == digest(
        {key: value for key, value in encoded.items() if key != "result_sha256"}
    )
    assert DiscoveryResult.model_validate_json(json.dumps(encoded)) == result
    with pytest.raises(ValidationError, match="impersonate"):
        CandidateSource.model_validate_json(
            json.dumps(
                {
                    **candidate["provenance"][0],
                    "origin": "model",
                }
            )
        )


def test_model_and_exact_rule_duplicates_merge_with_truthful_provenance():
    snapshot, mapping = freeze((located("投标人必须在本市注册。", section="投标人资格要求"),))
    rules = discover(snapshot, mapping)
    rule = rules.candidates[0]
    (batch,) = llm.plan_discovery(mapping)
    response = response_for(batch, description=rule.matched_reason)
    content = dict(response.content)
    content["findings"][0]["category"] = rule.category
    response = replace(response, content=content, response_hash=digest(content))
    accepted, _ = validate(batch, response)
    result = llm.merge_model_candidates(rules, accepted)
    assert len(result.candidates) == 1
    assert {source.origin for source in result.candidates[0].provenance} == {"rule", "model"}
    assert result.skill_coverages == rules.skill_coverages


def graph_harness(monkeypatch, *, fail=False, saturating=False, fail_first=False):
    if saturating:
        items = tuple(
            located(
                f"第{index + 1}条 付款条款需要核验，金额、期限和验收条件应当明确。",
                locator=f"paragraph:{index}",
            )
            for index in range(3)
        )
    else:
        items = (located("采购款项在设备验收且收到发票后支付。"),)
    snapshot, mapping = freeze(items)
    rules = discover(snapshot, mapping)
    artifacts = {"rules": rules.model_dump(mode="json")}
    saved = []
    nodes = {}
    run = SimpleNamespace(
        status="running",
        retry_count=0,
        review_task_id="task-a",
        run_id="run-a",
        project_id="project-a",
        snapshot_hash="a" * 64,
        snapshot={"document_requests": [], "prompt_version": FULLTEXT_V1_PROMPT_VERSION},
        publication_id="publication-a",
        revision_id="revision-a",
    )
    # This harness deliberately returns v1 discovery/semantic responses. Freeze
    # its version explicitly instead of depending on the current run default.
    frozen = {
        "document_requests": [],
        "input_snapshot": snapshot.model_dump(mode="json"),
        "prompt_version": FULLTEXT_V1_PROMPT_VERSION,
    }

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def scalars(self, statement):
            kind = statement._where_criteria[-1].right.value
            return [item for item in saved if item.kind == kind]

        def get(self, *_):
            return SimpleNamespace(status="running")

        def commit(self):
            pass

    def store(session, tenant, task, run_id, kind, content):
        reference = kind + ":" + digest(content)
        artifacts[reference] = content
        if not any(item.reference == reference for item in saved):
            saved.append(
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
            nodes[name] = action

        def add_edge(self, *_):
            pass

        def add_conditional_edges(self, *_):
            pass

        def compile(self, **_):
            return nodes

    class Gateway:
        calls = 0

        async def generate_structured(self, request, schema, policy):
            self.calls += 1
            assert policy.max_attempts == 1
            if fail_first and self.calls == 1:
                raise ModelGatewayError(
                    GatewayErrorCode.RESPONSE_INVALID, "synthetic invalid response"
                )
            if fail:
                raise ModelGatewayError(GatewayErrorCode.PROVIDER_ERROR, "unit test failure")
            if saturating:
                sections = request.input_payload["discovery_sections"]
                content = {
                    "schema_version": "v1alpha1",
                    "findings": [
                        {
                            "section_key": section["section_key"],
                            "quote": section["text"][:12],
                            "category": "contract",
                            "description": "细分重扫候选",
                        }
                        for section in sections[:3]
                    ],
                }
                return ModelResponse(
                    call_id=request.call_id,
                    provider="unit-test-provider",
                    model="unit-test-model",
                    profile="test",
                    content=content,
                    usage=ModelUsage(8, 8, 0.0),
                    latency_ms=0,
                    response_hash=digest(content),
                    finish_reason="stop",
                )
            (batch,) = llm.plan_discovery(mapping)
            return response_for(batch)

    gateway = Gateway()
    monkeypatch.setattr(review, "StateGraph", lambda *_: Graph())
    monkeypatch.setattr(review, "_load_run", lambda *_: run)
    monkeypatch.setattr(review, "_snapshot_inputs", lambda *_: (frozen, {}))
    monkeypatch.setattr(review, "snapshot_for_project", lambda *_: (snapshot, mapping))
    monkeypatch.setattr(review, "read_artifact", lambda _s, _t, ref, **_: artifacts[ref])
    monkeypatch.setattr(review, "put_artifact", store)
    review.build_review_graph(
        session_factory=Session,
        principal=Principal("tenant-a", "reviewer", "reviewer", Role.REVIEWER, "session-a"),
        gateway=gateway,
        model_policy=ModelPolicy(
            "test",
            5,
            max_input_tokens=32768,
            max_output_tokens=4096,
        ),
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
    state.update(status="running", discovery_ref="rules")
    return nodes, state, artifacts, saved, gateway


def test_graph_discovery_uses_gateway_persists_coverage_and_resumes_without_repaying(monkeypatch):
    nodes, state, artifacts, saved, gateway = graph_harness(monkeypatch)
    result = asyncio.run(nodes["llm_candidate_discovery"](state))
    assert result.get("status") != "failed"
    discovery = artifacts[result["discovery_ref"]]
    (candidate,) = discovery["candidates"]
    assert candidate["origin"] == "model"
    assert artifacts[result["llm_discovery_ref"]]["status"] == "completed"
    assert gateway.calls == 1
    assert asyncio.run(nodes["llm_candidate_discovery"](state)) == result
    assert gateway.calls == 1
    assert len([row for row in saved if row.kind == "candidate_discovery"]) == 1

    source = candidate["source_excerpts"][0]
    artifacts["model"] = {
        "content": {
            "findings": [
                {
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
            ]
        }
    }
    artifacts["retrieval"] = {
        "results": [
            {
                "work_item_id": candidate["candidate_id"],
                "result": {"hits": []},
            }
        ]
    }
    document_evidence = {
        "evidence_id": "b" * 64,
        "kind": "document",
        "title": "招标原文",
        "quote": source["quote"],
        "source_uri": "artifact://document/" + "a" * 64,
        "source_hash": "a" * 64,
        "page": None,
        "locator": source["locator"],
        "version_status": "unverified",
    }
    monkeypatch.setattr(review, "verify_document_excerpt", lambda *_a, **_k: document_evidence)
    state.update(result, model_findings_ref="model", retrieval_results_ref="retrieval")
    merged = nodes["merge_findings"](state)
    (finding,) = artifacts[merged["rule_findings_ref"]]["findings"]
    assert finding["sources"] == ["model"]
    assert finding["rule_ids"] == []
    assert finding["evidence_status"] == "insufficient_evidence"
    state.update(merged)
    checked = nodes["evidence_check"](state)
    assert checked["status"] == "waiting_human"
    assert checked["pending_review_ids"] == [finding["finding_id"]]


def test_graph_discovery_provider_failure_stops_without_mock_fallback(monkeypatch):
    nodes, state, artifacts, _, gateway = graph_harness(monkeypatch, fail=True)
    result = asyncio.run(nodes["llm_candidate_discovery"](state))
    assert result["status"] == "failed"
    # The provider error code must survive so the bounded retry policy can classify it.
    assert result["errors"][0]["code"] == "provider_error"
    assert gateway.calls == 1
    assert not any(key.startswith("candidate_discovery:") for key in artifacts)


def test_graph_discovery_contract_failure_keeps_the_generic_code(monkeypatch):
    nodes, state, _, _, _ = graph_harness(monkeypatch, fail=True)

    def broken(value):
        raise ValueError("unit test contract failure")

    monkeypatch.setattr(review.llm_discovery, "plan_discovery", broken)
    result = asyncio.run(nodes["llm_candidate_discovery"](state))
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "llm_discovery_failed"
    assert result["errors"][0]["retryable"] is False


def test_saturated_batches_are_subdivided_bounded_and_reused(monkeypatch):
    nodes, state, artifacts, saved, gateway = graph_harness(monkeypatch, saturating=True)
    first = asyncio.run(nodes["llm_candidate_discovery"](state))
    assert gateway.calls == 3
    coverage = artifacts[first["llm_discovery_ref"]]["coverage"]
    assert coverage["status"] == "complete"
    assert coverage["subdivided_batches"] == 1
    assert coverage["subdivision_calls"] == 2
    assert coverage["saturated_batches"] == 0
    assert coverage["batch_count"] == 3
    assert len([row for row in saved if row.kind.startswith("llm_discovery_batch_")]) == 3
    second = asyncio.run(nodes["llm_candidate_discovery"](state))
    assert second == first
    assert gateway.calls == 3


def test_a_failed_discovery_batch_is_boundedly_split_instead_of_failing_the_run(monkeypatch):
    nodes, state, artifacts, saved, gateway = graph_harness(
        monkeypatch, saturating=True, fail_first=True
    )
    result = asyncio.run(nodes["llm_candidate_discovery"](state))
    assert "errors" not in result
    assert result["llm_discovery_ref"]
    assert gateway.calls == 3
    coverage_record = artifacts[result["llm_discovery_ref"]]
    coverage = coverage_record["coverage"]
    assert coverage["status"] == "complete"
    assert coverage["subdivided_batches"] == 1
    assert coverage["failed_batches"] == 0
    parent = next(item for item in coverage_record["batches"] if item.get("subdivision_children"))
    assert parent["status"] == "subdivided"
    assert parent["failure_code"] == "response_invalid"
    assert parent["subdivision_children"]
