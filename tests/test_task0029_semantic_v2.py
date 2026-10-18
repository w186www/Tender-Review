"""Deterministic v2 support, provenance and privacy boundaries; no supplier calls."""

import asyncio
import hashlib
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError
from test_llm_candidate_discovery import graph_harness
from test_rules_skills import freeze
from test_semantic_batching import Harness, located_sections
from test_task0030_real_rag import CANDIDATE, DOCUMENT, payload

from bidding_compliance.graph import review
from bidding_compliance.model_gateway.contracts import ModelRequest, ModelResponse, ModelUsage
from bidding_compliance.model_gateway.errors import ModelGatewayError, ModelInputError
from bidding_compliance.services import llm_candidate_discovery as llm
from bidding_compliance.services import reports
from bidding_compliance.services.real_ai_runtime import AuthorizedTenderMinimizer, real_ai_policy
from bidding_compliance.services.review_contracts import (
    DISCOVERY_EVIDENCE_PROMPT_VERSION,
    SEMANTIC_EVIDENCE_PROMPT_VERSION,
    candidate_anchor,
    same_source_candidates,
)
from bidding_compliance.services.review_persistence import content_hash
from bidding_compliance.services.review_projection import merge_duplicate_findings
from bidding_compliance.services.semantic_review import (
    duplicate_identity_errors,
    review_support_errors,
    unresolved_conditional_claim,
)


def opinion(assessment="potential_issue", conclusion="supported"):
    return {
        "candidate_id": CANDIDATE,
        "assessment": assessment,
        "title": "付款条件待核",
        "description": "需核对付款条件。",
        "severity": "medium",
        "source_quote_sha256": ["a" * 64],
        "legal_evidence_ids": [],
        "recommendation": "核对原文。",
        "reasoning_summary": "合成验证。",
        "issue_identity": {"subject": "付款", "mechanism": "条件不明", "condition": "验收后"},
        "duplicate_of_candidate_id": None,
        "context_review": {
            "reviewed_quote_sha256": ["a" * 64],
            "counterevidence_quote_sha256": [],
            "conclusion": conclusion,
        },
        "legal_assessments": [],
    }


@pytest.mark.parametrize(
    "conclusion,allowed",
    [
        ("supported", {"potential_issue", "uncertain"}),
        ("qualified", {"potential_issue", "uncertain"}),
        ("contradicted", {"no_issue"}),
        ("unresolved", {"uncertain"}),
    ],
)
@pytest.mark.parametrize("assessment", ["potential_issue", "no_issue", "uncertain"])
def test_context_assessment_matrix_never_silently_accepts_a_contradiction(
    conclusion,
    allowed,
    assessment,
):
    errors = review_support_errors(
        opinion(assessment, conclusion), document_hashes={"a" * 64}, legal_ids=set()
    )
    assert bool(errors) == (assessment not in allowed)


def test_context_requires_all_sent_hashes_and_a_valid_counterevidence_subset():
    model = opinion()
    hashes = {"a" * 64, "b" * 64}
    assert "context_review_incomplete_or_invalid" in review_support_errors(
        model, document_hashes=hashes, legal_ids=set()
    )
    model["context_review"]["reviewed_quote_sha256"] = sorted(hashes)
    model["context_review"]["counterevidence_quote_sha256"] = ["b" * 64]
    assert review_support_errors(model, document_hashes=hashes, legal_ids=set()) == []
    model["context_review"]["counterevidence_quote_sha256"] = ["c" * 64]
    assert "context_review_incomplete_or_invalid" in review_support_errors(
        model, document_hashes=hashes, legal_ids=set()
    )


@pytest.mark.parametrize("conclusion,suppressed", [("supported", False), ("contradicted", True)])
def test_v2_merge_retains_contradictory_no_issue_for_manual_review(
    monkeypatch,
    conclusion,
    suppressed,
):
    nodes, state, artifacts, _, _ = graph_harness(monkeypatch)
    discovered = asyncio.run(nodes["llm_candidate_discovery"](state))
    (found,) = artifacts[discovered["discovery_ref"]]["candidates"]
    source = found["source_excerpts"][0]
    model = opinion("no_issue", conclusion)
    model.update(candidate_id=found["candidate_id"], source_quote_sha256=[source["quote_sha256"]])
    model["context_review"]["reviewed_quote_sha256"] = [source["quote_sha256"]]
    artifacts["semantic-result"] = {"content": {"schema_version": "v1alpha2", "findings": [model]}}
    artifacts["retrieval-result"] = {
        "results": [
            {
                "work_item_id": found["candidate_id"],
                "result": {"hits": []},
            }
        ]
    }
    frozen_inputs = review._snapshot_inputs

    def v2_inputs(*args):
        frozen, context = frozen_inputs(*args)
        return {**frozen, "prompt_version": SEMANTIC_EVIDENCE_PROMPT_VERSION}, context

    monkeypatch.setattr(review, "_snapshot_inputs", v2_inputs)
    monkeypatch.setattr(
        review,
        "verify_document_excerpt",
        lambda *_, **__: {
            "evidence_id": "b" * 64,
            "kind": "document",
            "title": "合成原文",
            "quote": source["quote"],
            "source_uri": "artifact://document/" + source["document_sha256"],
            "source_hash": source["document_sha256"],
            "page": source["page"],
            "locator": source["locator"],
            "version_status": "unverified",
        },
    )
    state.update(
        discovered, model_findings_ref="semantic-result", retrieval_results_ref="retrieval-result"
    )
    merged = nodes["merge_findings"](state)
    findings = artifacts[merged["rule_findings_ref"]]["findings"]
    assert len(findings) == (0 if suppressed else 1)
    if not suppressed:
        assert findings[0]["review_status"] == "pending"
        assert any(
            "no_issue_context_not_contradicted" in conflict["summary"]
            for conflict in findings[0]["conflicts"]
        )


def test_every_exposed_law_needs_a_relation_and_conflicts_cannot_support_a_risk():
    model = opinion()
    identifier = "b" * 64
    assert "legal_assessments_incomplete_or_invalid" in review_support_errors(
        model, document_hashes={"a" * 64}, legal_ids={identifier}
    )
    model["legal_assessments"] = [
        {"evidence_id": identifier, "relation": "conflicts", "reason": "该条允许此情形。"}
    ]
    model["legal_evidence_ids"] = [identifier]
    assert "legal_counterevidence_unresolved" in review_support_errors(
        model, document_hashes={"a" * 64}, legal_ids={identifier}
    )
    model["assessment"] = "uncertain"
    assert review_support_errors(model, document_hashes={"a" * 64}, legal_ids={identifier}) == []


def test_context_hash_capacity_includes_twenty_sources_and_six_related_excerpts():
    hashes = [f"{index:064x}" for index in range(26)]
    model = opinion()
    model["source_quote_sha256"] = [hashes[0]]
    model["context_review"]["reviewed_quote_sha256"] = hashes
    schema = review._analysis_schema(prompt_version=SEMANTIC_EVIDENCE_PROMPT_VERSION)
    validator = Draft202012Validator(schema)
    validator.validate({"schema_version": "v1alpha2", "findings": [model]})
    assert review_support_errors(model, document_hashes=set(hashes), legal_ids=set()) == []
    model["context_review"]["reviewed_quote_sha256"] = [*hashes, "f" * 64]
    with pytest.raises(ValidationError):
        validator.validate({"schema_version": "v1alpha2", "findings": [model]})


def candidate(identifier, *, category="contract", locator="page/1/line/1"):
    return SimpleNamespace(
        candidate_id=identifier,
        category=category,
        matched_reason="付款条件待核",
        source_excerpts=(
            SimpleNamespace(
                document_sha256="a" * 64,
                section_id="section-a",
                locator=locator,
                quote_sha256="b" * 64,
            ),
        ),
    )


@pytest.mark.parametrize("invalid", [None, "source", "identity", "self", "chain"])
def test_duplicate_identity_requires_the_same_fact_and_a_terminal_representative(invalid):
    first, second = candidate("1" * 64), candidate("2" * 64, category="procedure")
    representative, duplicate = opinion(), opinion()
    duplicate["duplicate_of_candidate_id"] = first.candidate_id
    if invalid == "source":
        second.source_excerpts[0].locator = "page/2/line/1"
    elif invalid == "identity":
        duplicate["issue_identity"]["mechanism"] = "审批主体不明"
    elif invalid == "self":
        duplicate["duplicate_of_candidate_id"] = second.candidate_id
    elif invalid == "chain":
        representative["duplicate_of_candidate_id"] = second.candidate_id
    errors = duplicate_identity_errors(
        second,
        duplicate,
        candidates={first.candidate_id: first, second.candidate_id: second},
        models={first.candidate_id: representative, second.candidate_id: duplicate},
    )
    assert bool(errors) == (invalid is not None)


def test_same_source_peers_ignore_category_but_keep_other_positions_separate():
    first = candidate("1" * 64)
    second = candidate("2" * 64, category="procedure")
    other = candidate("3" * 64, locator="page/2/line/1")
    assert candidate_anchor(first) == candidate_anchor(second)
    peers = same_source_candidates([other, second, first])
    assert [item["candidate_id"] for item in peers[first.candidate_id]] == [
        first.candidate_id,
        second.candidate_id,
    ]
    assert len(peers[other.candidate_id]) == 1


def semantic_request():
    return ModelRequest(
        call_id="a" * 64,
        tenant_id="tenant-a",
        review_task_id="task-a",
        node_run_id="node-a",
        prompt_version=SEMANTIC_EVIDENCE_PROMPT_VERSION,
        system_instruction="Evidence only.",
        input_payload=payload(),
        metadata={"semantic_batch": 0},
    )


@pytest.mark.parametrize(
    "field",
    [
        "document_candidates",
        "candidate_legal_evidence",
        "candidate_related_document_evidence",
        "project_context",
        "same_source_candidates",
    ],
)
def test_semantic_cache_identity_binds_each_input_component(field):
    request, schema, policy = (
        semantic_request(),
        review._analysis_schema(prompt_version=SEMANTIC_EVIDENCE_PROMPT_VERSION),
        real_ai_policy(),
    )
    baseline = review._semantic_input_hash(request, schema, policy, prompt_sha256="c" * 64)
    changed = deepcopy(dict(request.input_payload))
    changed[field] = {"different": True}
    assert baseline != review._semantic_input_hash(
        replace(request, input_payload=changed), schema, policy, prompt_sha256="c" * 64
    )
    assert baseline == review._semantic_input_hash(
        replace(request, call_id="b" * 64), schema, policy, prompt_sha256="c" * 64
    )
    assert baseline != review._semantic_input_hash(request, schema, policy, prompt_sha256="d" * 64)
    assert baseline != review._semantic_input_hash(
        request, schema, replace(policy, max_output_tokens=8192), prompt_sha256="c" * 64
    )


@pytest.mark.parametrize(
    "findings",
    [
        [],
        [opinion(), opinion()],
        [
            {**opinion(), "candidate_id": "f" * 64},
        ],
    ],
)
def test_cached_response_uses_the_same_exact_candidate_validation_as_new_results(findings):
    request = semantic_request()
    content = {"schema_version": "v1alpha2", "findings": findings}
    response = ModelResponse(
        call_id=request.call_id,
        provider="synthetic",
        model="synthetic",
        profile=real_ai_policy().profile,
        content=content,
        usage=ModelUsage(1, 1, 0.0),
        latency_ms=0,
        response_hash=content_hash(content),
    )
    with pytest.raises(ModelGatewayError) as invalid:
        review._validate_semantic_response(
            response,
            request,
            review._analysis_schema(
                prompt_version=SEMANTIC_EVIDENCE_PROMPT_VERSION,
            ),
            real_ai_policy(),
        )
    assert invalid.value.diagnostic_code == "semantic_candidate_set_mismatch"


def test_v2_graph_uses_the_minimizer_and_keeps_omitted_context_visible(monkeypatch):
    related = []
    for i in range(6):
        quote = f"第{i}条" + "合成关联条款。" * 240
        related.append(
            {
                "evidence_id": f"{i:064x}",
                "document_sha256": "a" * 64,
                "section_id": f"related-{i}",
                "section_revision": 1,
                "locator": f"page/{i + 1}/line/2",
                "page": i + 1,
                "quote": quote,
                "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
            }
        )
    harness = Harness(candidates=1, v2=True, related=related)
    result = asyncio.run(harness.node(monkeypatch))
    assert result["model_findings_ref"]
    assert harness.outbound[0]["project_context"] == harness.context
    assert harness.outbound[0]["same_source_candidates"]
    context = harness.artifacts[harness.payload()["related_document_evidence_ref"]]
    assert sum(context["omitted_for_input_capacity"].values()) > 0
    sent = sum(len(items) for items in harness.outbound[0]["related_document_evidence"].values())
    assert sent + sum(context["omitted_for_input_capacity"].values()) == 6
    assert len(harness.calls) == 1


def test_minimizer_whitelists_context_and_redacts_peer_descriptions():
    raw = payload()
    raw["project_context"].update(operator_name="私人姓名", notes="私人备注")
    raw["same_source_candidates"][CANDIDATE][0]["suspected_problem"] = (
        "付款条件待核，电话010-12345678，邮箱person@example.test"
    )
    safe = AuthorizedTenderMinimizer(frozenset({DOCUMENT}))(raw, real_ai_policy().data_policy)
    assert set(safe["project_context"]) == {
        "region",
        "procurement_type",
        "project_type",
        "procurement_method",
        "buyer_type",
        "subject_type",
        "legal_frameworks",
    }
    description = safe["same_source_candidates"][CANDIDATE][0]["suspected_problem"]
    assert "付款条件待核" in description
    assert "010-12345678" not in description and "person@example.test" not in description
    raw["same_source_candidates"][CANDIDATE][0]["private_note"] = "不能外发"
    with pytest.raises(ModelInputError) as denied:
        AuthorizedTenderMinimizer(frozenset({DOCUMENT}))(raw, real_ai_policy().data_policy)
    assert denied.value.diagnostic_code == "same_source_candidate_fields_invalid"


def test_report_follows_the_model_reference_and_checks_snapshot(monkeypatch):
    expected = {"snapshot_hash": "a" * 64, "omitted_for_input_capacity": {CANDIDATE: 2}}
    calls = []

    def read(session, tenant, reference, **scope):
        calls.append((tenant, reference, scope))
        return expected

    monkeypatch.setattr(reports, "read_artifact", read)
    principal = SimpleNamespace(tenant_id="tenant-a")
    result = SimpleNamespace(review_task_id="task-a", run_id="run-a", snapshot_hash="a" * 64)
    content, digest = reports._related_analysis_context(
        None, principal, result, {"related_document_evidence_ref": "exact-ref"}
    )
    assert content == expected and digest == content_hash(expected)
    assert calls == [("tenant-a", "exact-ref", {"review_task_id": "task-a", "run_id": "run-a"})]
    assert reports._related_analysis_context(None, principal, result, {}) == (None, None)
    expected["snapshot_hash"] = "b" * 64
    with pytest.raises(ValueError, match="snapshot mismatch"):
        reports._related_analysis_context(
            None, principal, result, {"related_document_evidence_ref": "exact-ref"}
        )


def test_legacy_duplicate_merge_does_not_invent_an_allowance():
    source = {
        "source_hash": DOCUMENT,
        "locator": "page/1/line/1",
        "quote": "投标人必须使用推荐品牌，合同价格不予调整。",
    }
    one = {
        "finding_id": "1" * 64,
        "category": "technical",
        "title": "强制使用推荐品牌风险",
        "description": source["quote"],
        "source_excerpt": source,
        "severity": "medium",
    }
    two = {**one, "finding_id": "2" * 64}
    merged = merge_duplicate_findings([one, two])
    assert len(merged) == 1
    assert merged[0]["title"] == one["title"]
    assert merged[0]["description"] == source["quote"]
    assert "允许" not in merged[0]["description"]


def test_v2_quote_order_does_not_change_candidate_identity_or_primary_locator():
    _, mapping = freeze(located_sections(2))
    (batch,) = llm.plan_discovery(mapping)
    request = llm.make_discovery_request(
        batch,
        tenant_id="tenant-a",
        task_id="task-a",
        run_id="run-a",
        snapshot_hash="a" * 64,
        prompt_version=DISCOVERY_EVIDENCE_PROMPT_VERSION,
    )
    references = [
        {"section_key": section.section_key, "quote": section.safe_text[:12]}
        for section in batch.sections
    ]
    results = []
    for refs in (references, list(reversed(references))):
        content = {
            "schema_version": "v1alpha2",
            "findings": [
                {
                    "source_quotes": refs,
                    "category": "contract",
                    "description": "两处付款条件需合并核查。",
                }
            ],
        }
        response = ModelResponse(
            call_id=request.call_id,
            provider="synthetic",
            model="synthetic",
            profile="unit",
            content=content,
            usage=ModelUsage(1, 1, 0.0),
            latency_ms=0,
            response_hash=content_hash(content),
        )
        accepted, rejected = llm.validate_response(
            batch,
            response,
            expected_call_id=request.call_id,
            profile="unit",
            schema=llm.discovery_schema(prompt_version=DISCOVERY_EVIDENCE_PROMPT_VERSION),
            prompt_version=DISCOVERY_EVIDENCE_PROMPT_VERSION,
        )
        assert not rejected
        results.append(accepted[0])
    assert results[0].candidate_id == results[1].candidate_id
    assert results[0].source_excerpts == results[1].source_excerpts
    assert len(results[0].source_excerpts) == 2

    # A stitched cross-section quote is still rejected; sorting never relaxes
    # exact character validation or recovers text absent from its own section.
    content["findings"][0]["source_quotes"] = [
        {
            "section_key": references[0]["section_key"],
            "quote": references[0]["quote"] + references[1]["quote"],
        }
    ]
    invalid = replace(response, content=content, response_hash=content_hash(content))
    accepted, rejected = llm.validate_response(
        batch,
        invalid,
        expected_call_id=request.call_id,
        profile="unit",
        schema=llm.discovery_schema(prompt_version=DISCOVERY_EVIDENCE_PROMPT_VERSION),
        prompt_version=DISCOVERY_EVIDENCE_PROMPT_VERSION,
    )
    assert accepted == ()
    assert rejected[0]["reason"] == "quote_missing_or_ambiguous"


@pytest.mark.parametrize("invalid", ["both_invalid", "second_invalid", "unknown_and_invalid"])
def test_rejected_v2_quote_order_keeps_identity_reason_and_recovery_anchor(invalid):
    _, mapping = freeze(located_sections(2))
    (batch,) = llm.plan_discovery(mapping)
    request = llm.make_discovery_request(
        batch,
        tenant_id="tenant-a",
        task_id="task-a",
        run_id="run-a",
        snapshot_hash="a" * 64,
        prompt_version=DISCOVERY_EVIDENCE_PROMPT_VERSION,
    )
    valid = [
        {"section_key": section.section_key, "quote": section.safe_text[:12]}
        for section in batch.sections
    ]
    refs = deepcopy(valid)
    refs[1]["quote"] = "不在第二个片段里的合成文字"
    if invalid == "both_invalid":
        refs[0]["quote"] = "不在第一个片段里的合成文字"
    elif invalid == "unknown_and_invalid":
        refs[1]["section_key"] = "s999999c999"
        refs[0]["quote"] = "不在第一个片段里的合成文字"

    def validate(references):
        content = {
            "schema_version": "v1alpha2",
            "findings": [
                {
                    "source_quotes": references,
                    "category": "contract",
                    "description": "两处付款条件需合并核查。",
                }
            ],
        }
        response = ModelResponse(
            call_id=request.call_id,
            provider="synthetic",
            model="synthetic",
            profile="unit",
            content=content,
            usage=ModelUsage(1, 1, 0.0),
            latency_ms=0,
            response_hash=content_hash(content),
        )
        return llm.validate_response(
            batch,
            response,
            expected_call_id=request.call_id,
            profile="unit",
            schema=llm.discovery_schema(prompt_version=DISCOVERY_EVIDENCE_PROMPT_VERSION),
            prompt_version=DISCOVERY_EVIDENCE_PROMPT_VERSION,
        )

    accepted, rejected = validate(refs)
    reversed_accepted, reversed_rejected = validate(list(reversed(refs)))
    assert accepted == reversed_accepted == ()
    assert rejected == reversed_rejected
    assert rejected[0]["reason"] == "quote_missing_or_ambiguous"
    repaired, errors = validate(valid)
    assert not errors
    assert rejected[0]["candidate_family_hash"] == llm.candidate_family_hash(repaired[0])


@pytest.mark.parametrize(
    "text,conflict",
    [
        ("该条款全面禁止使用替代品牌。", True),
        ("不应概括为全面禁止替代品牌。", False),
        ("不能认定该条款排斥竞争。", False),
        ("并非全面禁止替代；但该条款一律禁止其他品牌。", True),
        ("未发现付款问题。该品牌条款全面禁止替代。", True),
        ("只有替代资料未通过评审时，才不得使用其他品牌。", False),
    ],
)
def test_conditional_guard_keeps_negation_and_conditions_within_each_sentence(text, conflict):
    is_conflict = unresolved_conditional_claim(text, ["投标人可选用同等性能的其他品牌。允许替代。"])
    assert is_conflict is conflict
    assert not unresolved_conditional_claim(text, ["投标人必须使用推荐品牌。"])
    assert not unresolved_conditional_claim(text, ["投标人不允许使用其他品牌。"])


@pytest.mark.parametrize("field", ["title", "description", "reasoning_summary", "recommendation"])
def test_v2_merge_checks_each_output_field_for_conditional_conflicts(monkeypatch, field):
    # This test checks graph wiring. Sentence interpretation has separate cases above.
    nodes, state, artifacts, _, _ = graph_harness(monkeypatch)
    discovered = asyncio.run(nodes["llm_candidate_discovery"](state))
    (found,) = artifacts[discovered["discovery_ref"]]["candidates"]
    source = found["source_excerpts"][0]
    model = opinion()
    model.update(candidate_id=found["candidate_id"], source_quote_sha256=[source["quote_sha256"]])
    model["context_review"]["reviewed_quote_sha256"] = [source["quote_sha256"]]
    marker = "本字段的合成条件冲突"
    model[field] = marker
    artifacts["semantic-fields"] = {"content": {"schema_version": "v1alpha2", "findings": [model]}}
    artifacts["retrieval-fields"] = {
        "results": [
            {
                "work_item_id": found["candidate_id"],
                "result": {"hits": []},
            }
        ]
    }
    frozen_inputs = review._snapshot_inputs

    def v2_inputs(*args):
        frozen, context = frozen_inputs(*args)
        return {**frozen, "prompt_version": SEMANTIC_EVIDENCE_PROMPT_VERSION}, context

    seen = []

    def guard(text, quotes):
        seen.append(text)
        return text == marker

    monkeypatch.setattr(review, "_snapshot_inputs", v2_inputs)
    monkeypatch.setattr(review, "unresolved_conditional_claim", guard)
    monkeypatch.setattr(
        review,
        "verify_document_excerpt",
        lambda *_, **__: {
            "evidence_id": "b" * 64,
            "kind": "document",
            "title": "合成原文",
            "quote": source["quote"],
            "source_uri": "artifact://document/" + source["document_sha256"],
            "source_hash": source["document_sha256"],
            "page": source["page"],
            "locator": source["locator"],
            "version_status": "unverified",
        },
    )
    state.update(
        discovered, model_findings_ref="semantic-fields", retrieval_results_ref="retrieval-fields"
    )
    merged = nodes["merge_findings"](state)
    (finding,) = artifacts[merged["rule_findings_ref"]]["findings"]
    assert marker in seen
    assert finding["review_status"] == "pending"
    assert any(
        "conditional_context_requires_reassessment" in conflict["summary"]
        for conflict in finding["conflicts"]
    )


@pytest.mark.parametrize("kind", ["candidate_discovery", "llm_candidate_discovery"])
def test_report_artifact_lookup_accepts_only_unique_intact_content(kind):
    row = SimpleNamespace(
        content={"status": "synthetic"}, content_hash=content_hash({"status": "synthetic"})
    )

    class Session:
        rows = []

        def scalars(self, statement):
            parameters = statement.compile().params.values()
            assert {"tenant-a", "task-a", "run-a", kind}.issubset(parameters)
            return self.rows

    session = Session()
    principal = SimpleNamespace(tenant_id="tenant-a")
    scope = {"review_task_id": "task-a", "run_id": "run-a", "kind": kind}
    assert reports._optional_run_artifact(session, principal, **scope) is None
    session.rows = [row]
    assert reports._optional_run_artifact(session, principal, **scope) is row
    session.rows = [row, row]
    with pytest.raises(ValueError, match="ambiguous"):
        reports._optional_run_artifact(session, principal, **scope)
    session.rows = [row]
    row.content["status"] = "changed"
    with pytest.raises(ValueError, match="unavailable or changed"):
        reports._optional_run_artifact(session, principal, **scope)


@pytest.mark.parametrize("caller", ["locations", "coverage"])
def test_report_locations_and_coverage_reject_ambiguous_artifacts(caller):
    content = {"candidates": [], "coverage": {}}
    row = SimpleNamespace(content=content, content_hash=content_hash(content))

    class Session:
        def scalar(self, statement):
            return 0  # Unknown-call COUNT remains a normal scalar query.

        def scalars(self, statement):
            return [row, row]

    session = Session()
    principal = SimpleNamespace(tenant_id="tenant-a")
    with pytest.raises(ValueError, match="ambiguous"):
        if caller == "locations":
            reports._resolve_source_locations(
                session,
                principal,
                project_id="project-a",
                review_task_id="task-a",
                run_id="run-a",
                snapshot={},
                finding={},
            )
        else:
            result = SimpleNamespace(review_task_id="task-a", run_id="run-a")
            reports._product_execution(session, principal, result)


@pytest.mark.parametrize("model_count,expected", [(0, "not_applicable"), (1, "unknown")])
def test_missing_legacy_coverage_preserves_its_explicit_fallback(
    monkeypatch, model_count, expected
):
    class Session:
        def scalar(self, statement):
            return 0

        def scalars(self, statement):
            return []

        def get(self, *args):
            return SimpleNamespace()

    monkeypatch.setattr(
        reports, "_runtime_projection", lambda *args: {"model_candidate_count": model_count}
    )
    result = SimpleNamespace(review_task_id="task-a", run_id="run-a")
    summary = reports._product_execution(Session(), SimpleNamespace(tenant_id="tenant-a"), result)
    assert summary["coverage_status"] == expected


def test_product_execution_follows_the_frozen_coverage_reference(monkeypatch):
    calls = []

    def read(_session, tenant, reference, **scope):
        calls.append((tenant, reference, scope.get("review_task_id"), scope.get("run_id")))
        return {"coverage": {}, "batches": []}

    class Session:
        def scalar(self, _statement):
            return 0

        def scalars(self, _statement):
            raise AssertionError("must not select coverage by kind when a frozen reference exists")

    monkeypatch.setattr(reports, "read_artifact", read)
    result = SimpleNamespace(review_task_id="task-a", run_id="run-a")
    summary = reports._product_execution(
        Session(),
        SimpleNamespace(tenant_id="tenant-a"),
        result,
        coverage_ref="coverage-ref",
    )
    assert calls == [("tenant-a", "coverage-ref", "task-a", "run-a")]
    assert summary["coverage_status"] == "complete"
