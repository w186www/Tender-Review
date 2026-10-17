"""DEC-007 per-file authorization: registry, CLI, ledger continuity and the egress gate."""

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import stat
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.domain.rules.models import DiscoveryDocumentRequest
from bidding_compliance.model_gateway.authorization import AuthorizationPolicy
from bidding_compliance.model_gateway.authorized_runtime import (
    AUTHORIZATION_ID,
    AUTHORIZATION_LIMITS,
    FULL_CAPABILITY_AUTHORIZATION_ID,
    SEMANTIC_AUTHORIZATION_ID,
    Dec005BudgetLedger,
)
from bidding_compliance.model_gateway.contracts import ModelRequest
from bidding_compliance.model_gateway.errors import ModelGatewayError
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.services.llm_candidate_discovery import discovery_schema
from bidding_compliance.services.real_ai_runtime import (
    DISCOVERY_PROMPT_VERSION,
    AuthorizedRealReviewEngine,
    AuthorizedTenderMinimizer,
    FileAuthorizationRegistry,
    create_dec005_gateway,
    real_ai_policy,
    resolve_authorized_documents,
    resolve_real_runtime_authorization,
)
from bidding_compliance.services.review_engine import ReviewRequest

REGISTERED = "b" * 64
UNREGISTERED = "f" * 64
REGISTRY_FIELDS = {"action", "sha256", "document_id", "reason", "approved_at", "approved_by"}


def registry(tmp_path: Path) -> FileAuthorizationRegistry:
    return FileAuthorizationRegistry(tmp_path / "authorization-registry.jsonl")


class StubGateway:
    def prompt_sha256(self, version: str) -> str:
        return "a" * 64


def principal() -> Principal:
    return Principal(
        tenant_id="tenant-a", user_id="u", username="u", role=Role.REVIEWER, session_id="s"
    )


def review_request(document_sha256: str) -> ReviewRequest:
    return ReviewRequest(
        review_task_id="task-1",
        project_id="project-1",
        run_id="3f0f2a3e-6f0a-4a3e-8f4b-7c1d2e3f4a5b",
        document_requests=(
            DiscoveryDocumentRequest(
                document_id="doc-1",
                raw_source_sha256=document_sha256,
                parse_version=1,
                context_version=1,
            ),
        ),
        review_date=date(2026, 10, 16),
        prompt_version="task0030-semantic-rag-v1",
        model_profile=real_ai_policy().profile,
    )


def review_engine(
    tmp_path: Path,
    allowed: frozenset[str] | Callable[[], frozenset[str]],
) -> AuthorizedRealReviewEngine:
    settings = Settings(
        _env_file=None, app_env="test", database_url="sqlite:///" + str(tmp_path / "engine.db")
    )
    return AuthorizedRealReviewEngine(
        settings=settings,
        session_factory=sessionmaker(make_engine(settings), expire_on_commit=False),
        gateway=StubGateway(),
        model_policy=real_ai_policy(),
        legal_root=tmp_path,
        authorization=AuthorizationPolicy(
            trusted_calls={}, tenant_providers={}, provider_data_policies={}
        ),
        allowed_document_sha256=allowed,
    )


def load_cli():
    path = Path(__file__).resolve().parents[1] / "deploy" / "manage_authorization.py"
    spec = importlib.util.spec_from_file_location("manage_authorization_cli", path)
    if spec is None or spec.loader is None:
        raise AssertionError("the authorization CLI is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dec007_is_an_independent_authorization_with_its_own_ledger(tmp_path):
    assert AUTHORIZATION_LIMITS[AUTHORIZATION_ID] == {
        "llm": 30,
        "embedding": 200,
        "cny": Decimal("20"),
    }
    assert AUTHORIZATION_LIMITS[SEMANTIC_AUTHORIZATION_ID] == {
        "llm": 15,
        "embedding": 0,
        "cny": Decimal("5"),
    }
    assert AUTHORIZATION_LIMITS[FULL_CAPABILITY_AUTHORIZATION_ID] == {
        "llm": 2000,
        "embedding": 2000,
        "cny": Decimal("200"),
    }

    legacy = Dec005BudgetLedger(
        tmp_path / "dec005-budget.sqlite3",
        scope_sha256="1" * 64,
        authorization_id=AUTHORIZATION_ID,
    )
    legacy.reserve("tenant-a", "review", Decimal("0.01"))
    assert legacy.summary()["llm_calls"] == 1

    full = Dec005BudgetLedger(
        tmp_path / "dec007-budget.sqlite3",
        scope_sha256="2" * 64,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    summary = full.summary()
    assert summary["llm_calls"] == 0 and summary["embedding_batches"] == 0
    assert summary["limits"] == {"llm_calls": 2000, "embedding_batches": 2000, "total_cny": "200"}
    assert legacy.summary()["llm_calls"] == 1  # the earlier authorization is untouched

    for overrides in (
        {"llm_limit": 2001},
        {"embedding_limit": 2001},
        {"total_cny": Decimal("200.01")},
    ):
        with pytest.raises(ValueError):
            Dec005BudgetLedger(
                tmp_path / "dec007-over.sqlite3",
                scope_sha256="3" * 64,
                authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
                **overrides,
            )


def test_registry_is_append_only_audited_and_validated(tmp_path):
    path = tmp_path / "authorization-registry.jsonl"
    store = FileAuthorizationRegistry(path)
    assert store.allowed_sha256() == frozenset()
    record = store.approve(
        sha256=REGISTERED, document_id="doc-1", reason="合成演示样本", approved_by="operator"
    )
    assert record["action"] == "approve" and re.fullmatch(
        r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", record["approved_at"]
    )
    store.approve(sha256="c" * 64, document_id="doc-2", reason="第二个样本", approved_by="operator")
    store.revoke(sha256="c" * 64, document_id="doc-2", reason="不再需要", approved_by="operator")
    assert store.allowed_sha256() == frozenset({REGISTERED})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        assert set(json.loads(line)) == REGISTRY_FIELDS
    assert REGISTERED in lines[0]
    reloaded = FileAuthorizationRegistry(path)
    assert reloaded.allowed_sha256() == frozenset({REGISTERED})
    assert len(reloaded.records()) == 3
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    for bad in ("B" * 64, "b" * 63, "z" * 64, ""):
        with pytest.raises(ValueError, match="64 lowercase hex"):
            store.approve(sha256=bad, document_id="doc-3", reason="坏哈希", approved_by="operator")
    with pytest.raises(ValueError, match="reason"):
        store.approve(sha256=REGISTERED, document_id="doc-3", reason="   ", approved_by="operator")
    with pytest.raises(ValueError, match="document identity"):
        store.approve(sha256=REGISTERED, document_id="a b", reason="带空格", approved_by="operator")
    with pytest.raises(ValueError, match="operator identity"):
        store.approve(sha256=REGISTERED, document_id="doc-3", reason="无操作员", approved_by="")
    assert path.read_text(encoding="utf-8").splitlines() == lines  # nothing was appended


def test_corrupt_or_unknown_registry_entries_fail_closed(tmp_path):
    path = tmp_path / "authorization-registry.jsonl"
    path.write_text('{"action": "approve"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        FileAuthorizationRegistry(path)
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        FileAuthorizationRegistry(path)
    unknown = {
        "action": "grant",
        "sha256": REGISTERED,
        "document_id": "doc-1",
        "reason": "未知动作",
        "approved_at": "2026-10-16T00:00:00+00:00",
        "approved_by": "operator",
    }
    path.write_text(json.dumps(unknown) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown action"):
        FileAuthorizationRegistry(path)
    unknown["action"] = "approve"
    unknown["approved_at"] = "whenever"
    path.write_text(json.dumps(unknown) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid timestamp"):
        FileAuthorizationRegistry(path)


def test_authorized_documents_are_the_union_and_never_auto_approved(tmp_path):
    store = registry(tmp_path)
    store.approve(
        sha256=REGISTERED, document_id="doc-1", reason="合成样本", approved_by="operator"
    )
    union = resolve_authorized_documents(registry=store, environment_hashes={"a" * 64, ""})
    assert union == frozenset({"a" * 64, REGISTERED})
    assert UNREGISTERED not in union
    assert resolve_authorized_documents(registry=store, environment_hashes=()) == frozenset(
        {REGISTERED}
    )
    assert resolve_authorized_documents(registry=None, environment_hashes={"a" * 64}) == frozenset(
        {"a" * 64}
    )
    assert resolve_authorized_documents(registry=None, environment_hashes=()) == frozenset()
    with pytest.raises(ValueError, match="64 lowercase hex"):
        resolve_authorized_documents(registry=store, environment_hashes={"not-a-hash"})
    with pytest.raises(ValueError, match="explicit approved document hashes"):
        AuthorizedTenderMinimizer(frozenset())


def test_minimizer_refuses_an_unregistered_document(tmp_path):
    minimizer = AuthorizedTenderMinimizer(frozenset({REGISTERED}))
    policy = real_ai_policy().data_policy
    section = {
        "section_key": "s000000c000",
        "text": "合成片段内容。",
        "document_sha256": UNREGISTERED,
    }
    with pytest.raises(ValueError, match="outside authorized scope"):
        minimizer({"discovery_sections": [section]}, policy)
    section["document_sha256"] = REGISTERED
    assert minimizer({"discovery_sections": [section]}, policy) == {
        "discovery_sections": [{"section_key": "s000000c000", "text": "合成片段内容。"}]
    }


def test_unregistered_document_is_denied_before_any_gateway_work(tmp_path):
    store = registry(tmp_path)
    store.approve(
        sha256=REGISTERED, document_id="doc-1", reason="合成样本", approved_by="operator"
    )
    allowed = resolve_authorized_documents(registry=store, environment_hashes=())
    engine = review_engine(tmp_path, allowed)

    # The refusal names the authorization on purpose: the API layer maps that to 403 so the
    # workbench can say "this file is not authorized" instead of "the data changed".
    with pytest.raises(PermissionError, match="not authorized for external processing"):
        engine._freeze_run(principal(), review_request(UNREGISTERED))
    with pytest.raises(PermissionError):
        engine._freeze_run(principal(), review_request("a" * 64))

    outcome = "registered-file-was-denied"
    try:
        engine._freeze_run(principal(), review_request(REGISTERED))
    except PermissionError:
        outcome = "registered-file-was-denied"
    except Exception:
        outcome = "runtime-state-unavailable"
    assert outcome == "runtime-state-unavailable"


def test_legacy_authorization_identity_and_scope_are_preserved(tmp_path):
    with pytest.raises(ValueError, match="explicit server authorization"):
        resolve_real_runtime_authorization({}, private_root=tmp_path)
    legacy = resolve_real_runtime_authorization(
        {"DEC005_AUTHORIZATION_ID": AUTHORIZATION_ID, "DEC005_ALLOWED_DOCUMENT_SHA256": "a" * 64},
        private_root=tmp_path,
    )
    assert legacy.authorization_id == SEMANTIC_AUTHORIZATION_ID
    assert legacy.registry is None and legacy.registry_path is None
    assert legacy.ledger_path == tmp_path / "dec005-budget.sqlite3"
    assert legacy.model_audit_path == tmp_path / "model-audit.jsonl"
    assert legacy.allowed_documents == frozenset({"a" * 64})
    assert legacy.scope_sha256 == hashlib.sha256(
        json.dumps(
            {
                "authorization": SEMANTIC_AUTHORIZATION_ID,
                "tenant": "tenant-a",
                "documents": ["a" * 64],
                "provider": "bailian-cn-beijing",
                "model": "qwen3.8-flash",
                "embedding": "text-embedding-v4/1024",
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def test_approving_a_file_never_resets_or_invalidates_the_ledger(tmp_path):
    registry_path = tmp_path / "authorization-registry.jsonl"
    store = FileAuthorizationRegistry(registry_path)
    store.approve(
        sha256=REGISTERED, document_id="doc-1", reason="首个样本", approved_by="operator"
    )
    environment = {
        "DEC007_AUTHORIZATION_ID": FULL_CAPABILITY_AUTHORIZATION_ID,
        "DEC007_AUTHORIZATION_REGISTRY": str(registry_path),
        "DEC007_LEDGER_PATH": str(tmp_path / "dec007-budget.sqlite3"),
        "DEC005_ALLOWED_DOCUMENT_SHA256": "a" * 64,
    }
    first = resolve_real_runtime_authorization(environment, private_root=tmp_path)
    assert first.authorization_id == FULL_CAPABILITY_AUTHORIZATION_ID
    assert first.allowed_documents == frozenset({"a" * 64, REGISTERED})
    assert first.registry_path == registry_path
    assert first.ledger_path == tmp_path / "dec007-budget.sqlite3"
    assert first.model_audit_path == tmp_path / "dec007-model-audit.jsonl"

    ledger = Dec005BudgetLedger(
        first.ledger_path,
        scope_sha256=first.scope_sha256,
        authorization_id=first.authorization_id,
    )
    ledger.reserve_external(kind="embedding", request_hash="e" * 64, ceiling=Decimal("0.10"))
    assert ledger.summary()["embedding_batches"] == 1
    ledger_bytes = first.ledger_path.read_bytes()

    store.approve(sha256="c" * 64, document_id="doc-2", reason="第二个样本", approved_by="operator")
    second = resolve_real_runtime_authorization(environment, private_root=tmp_path)
    assert second.allowed_documents == frozenset({"a" * 64, REGISTERED, "c" * 64})
    assert second.scope_sha256 == first.scope_sha256
    assert first.ledger_path.read_bytes() == ledger_bytes
    reopened = Dec005BudgetLedger(
        second.ledger_path,
        scope_sha256=second.scope_sha256,
        authorization_id=second.authorization_id,
    )
    assert reopened.summary()["embedding_batches"] == 1


def dec007_environment(tmp_path: Path, registry_path: Path) -> dict[str, str]:
    return {
        "DEC007_AUTHORIZATION_ID": FULL_CAPABILITY_AUTHORIZATION_ID,
        "DEC007_AUTHORIZATION_REGISTRY": str(registry_path),
        "DEC007_LEDGER_PATH": str(tmp_path / "dec007-budget.sqlite3"),
    }


def freeze_outcome(engine: AuthorizedRealReviewEngine, sha256: str) -> str:
    """Separate the permission gate from the unrelated runtime state of a stub engine."""
    try:
        engine._freeze_run(principal(), review_request(sha256))
    except PermissionError:
        return "denied-before-egress"
    except Exception:
        return "runtime-state-unavailable"
    return "frozen"


def test_running_process_sees_approvals_and_revocations_without_a_restart(tmp_path):
    path = tmp_path / "authorization-registry.jsonl"
    running = FileAuthorizationRegistry(path)  # the process that is already serving
    assert running.allowed_sha256() == frozenset()
    operator = FileAuthorizationRegistry(path)  # a second process: the operator CLI
    operator.approve(
        sha256=REGISTERED, document_id="doc-1", reason="登记合成样本", approved_by="operator"
    )
    assert running.allowed_sha256() == frozenset({REGISTERED})
    assert [record["action"] for record in running.records()] == ["approve"]

    operator.revoke(
        sha256=REGISTERED, document_id="doc-1", reason="收回授权", approved_by="operator"
    )
    assert running.allowed_sha256() == frozenset()
    assert [record["action"] for record in running.records()] == ["approve", "revoke"]


def test_engine_denies_egress_after_an_external_revocation_of_a_running_process(tmp_path):
    registry_path = tmp_path / "authorization-registry.jsonl"
    FileAuthorizationRegistry(registry_path).approve(
        sha256=REGISTERED, document_id="doc-1", reason="登记合成样本", approved_by="operator"
    )
    resolution = resolve_real_runtime_authorization(
        dec007_environment(tmp_path, registry_path), private_root=tmp_path
    )
    # The API process starts while the file is approved and freezes only the *source*.
    engine = review_engine(tmp_path, resolution.allowed_document_source)
    assert engine.allowed_document_sha256 == frozenset({REGISTERED})
    engine._require_authorized_documents({REGISTERED})  # the gate _invoke shares: no raise
    assert freeze_outcome(engine, REGISTERED) == "runtime-state-unavailable"
    assert freeze_outcome(engine, UNREGISTERED) == "denied-before-egress"

    # The operator revokes from outside the process: no restart, no cache to invalidate.
    FileAuthorizationRegistry(registry_path).revoke(
        sha256=REGISTERED, document_id="doc-1", reason="收回授权", approved_by="operator"
    )
    assert engine.allowed_document_sha256 == frozenset()
    assert freeze_outcome(engine, REGISTERED) == "denied-before-egress"
    with pytest.raises(PermissionError):
        engine._require_authorized_documents({REGISTERED})

    # The ledger scope is unaffected by approvals and revocations: nothing was reset.
    reopened = Dec005BudgetLedger(
        resolution.ledger_path,
        scope_sha256=resolution.scope_sha256,
        authorization_id=resolution.authorization_id,
    )
    assert reopened.summary()["limits"]["embedding_batches"] == 2000


def test_minimizer_refuses_a_revoked_document_at_the_next_egress_decision(tmp_path):
    registry_path = tmp_path / "authorization-registry.jsonl"
    FileAuthorizationRegistry(registry_path).approve(
        sha256=REGISTERED, document_id="doc-1", reason="登记合成样本", approved_by="operator"
    )
    resolution = resolve_real_runtime_authorization(
        dec007_environment(tmp_path, registry_path), private_root=tmp_path
    )
    minimizer = AuthorizedTenderMinimizer(resolution.allowed_document_source)
    policy = real_ai_policy().data_policy
    section = {
        "section_key": "s000000c000",
        "text": "合成片段内容。",
        "document_sha256": REGISTERED,
    }
    assert minimizer({"discovery_sections": [section]}, policy) == {
        "discovery_sections": [{"section_key": "s000000c000", "text": "合成片段内容。"}]
    }

    # A second approved file keeps the allowlist non-empty, so the next assertions exercise
    # the per-file membership check itself and not only the fail-closed empty case.
    other = "d" * 64
    FileAuthorizationRegistry(registry_path).approve(
        sha256=other, document_id="doc-2", reason="第二份合成样本", approved_by="operator"
    )
    FileAuthorizationRegistry(registry_path).revoke(
        sha256=REGISTERED, document_id="doc-1", reason="收回授权", approved_by="operator"
    )
    with pytest.raises(ValueError, match="outside authorized scope"):
        minimizer({"discovery_sections": [section]}, policy)
    section["document_sha256"] = other
    assert minimizer({"discovery_sections": [section]}, policy) == {
        "discovery_sections": [{"section_key": "s000000c000", "text": "合成片段内容。"}]
    }

    # With every file revoked nothing may leave the host at all.
    FileAuthorizationRegistry(registry_path).revoke(
        sha256=other, document_id="doc-2", reason="全部收回", approved_by="operator"
    )
    with pytest.raises(ValueError, match="no document is currently authorized"):
        _ = minimizer.allowed


def test_gateway_sends_nothing_after_an_external_revocation(tmp_path):
    registry_path = tmp_path / "authorization-registry.jsonl"
    FileAuthorizationRegistry(registry_path).approve(
        sha256=REGISTERED, document_id="doc-1", reason="登记合成样本", approved_by="operator"
    )
    resolution = resolve_real_runtime_authorization(
        dec007_environment(tmp_path, registry_path), private_root=tmp_path
    )
    calls: list[dict[str, object]] = []

    def handle(wire: httpx.Request) -> httpx.Response:
        calls.append(json.loads(wire.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"schema_version": "v1alpha1", "findings": []})
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )

    gateway, authorization, budget = create_dec005_gateway(
        api_key="example-synthetic-credential",
        workspace_id="contract-workspace",
        tenant_id="tenant-a",
        allowed_document_sha256=resolution.allowed_document_source,
        ledger_path=resolution.ledger_path,
        audit_path=resolution.model_audit_path,
        authorization_id=resolution.authorization_id,
        scope_documents=resolution.environment_documents,
        authorization_registry=resolution.registry_path,
        transport=httpx.MockTransport(handle),
    )
    request = ModelRequest(
        call_id="revocation-call",
        tenant_id="tenant-a",
        review_task_id="review-task",
        node_run_id="bounded-node",
        prompt_version=DISCOVERY_PROMPT_VERSION,
        system_instruction="client-supplied instructions must be ignored",
        input_payload={
            "discovery_sections": [
                {
                    "section_key": "s000000c000",
                    "document_sha256": REGISTERED,
                    "text": "合成条款疑点，联系人：张三。",
                }
            ]
        },
    )
    authorization.trusted_calls["revocation-call"] = (
        "tenant-a",
        "review-task",
        "bounded-node",
    )
    assert (
        asyncio.run(
            gateway.generate_structured(request, discovery_schema(), real_ai_policy())
        ).provider
        == "bailian"
    )
    assert len(calls) == 1 and budget.summary()["llm_calls"] == 1

    # The process keeps running; the operator withdraws the authorization from outside.
    FileAuthorizationRegistry(registry_path).revoke(
        sha256=REGISTERED, document_id="doc-1", reason="收回授权", approved_by="operator"
    )
    authorization.trusted_calls["revocation-call"] = (
        "tenant-a",
        "review-task",
        "bounded-node",
    )
    with pytest.raises(ModelGatewayError):
        asyncio.run(gateway.generate_structured(request, discovery_schema(), real_ai_policy()))
    assert len(calls) == 1  # nothing left the host after the revocation
    assert budget.summary()["llm_calls"] == 1


def test_authorization_cli_approves_lists_and_revokes_with_audit_lines(
    tmp_path, capsys, monkeypatch
):
    cli = load_cli()
    path = tmp_path / "authorization-registry.jsonl"
    monkeypatch.delenv("DEC007_AUTHORIZATION_REGISTRY", raising=False)
    assert (
        cli.main(
            [
                "--registry",
                str(path),
                "approve",
                "--sha256",
                REGISTERED,
                "--document",
                "doc-1",
                "--reason",
                "面试演示",
                "--actor",
                "operator",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["action"] == "approve" and payload["sha256"] == REGISTERED

    # The registry option is accepted after the sub-command as well.
    assert (
        cli.main(
            [
                "approve",
                "--sha256",
                "d" * 64,
                "--document",
                "doc-2",
                "--registry",
                str(path),
                "--reason",
                "第二种写法",
                "--actor",
                "operator",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert cli.main(["--registry", str(path), "list"]) == 0
    listing = capsys.readouterr().out
    assert REGISTERED in listing and "approved files: 2" in listing
    assert cli.main(["--registry", str(path), "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["allowed"] == [REGISTERED, "d" * 64]

    assert (
        cli.main(
            [
                "revoke",
                "--sha256",
                REGISTERED,
                "--reason",
                "收回",
                "--registry",
                str(path),
                "--actor",
                "operator",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert FileAuthorizationRegistry(path).allowed_sha256() == frozenset({"d" * 64})
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3

    monkeypatch.setenv("DEC007_AUTHORIZATION_REGISTRY", str(path))
    assert (
        cli.main(["approve", "--sha256", "e" * 64, "--document", "doc-3", "--reason", "环境变量"])
        == 0
    )
    assert FileAuthorizationRegistry(path).allowed_sha256() == frozenset({"d" * 64, "e" * 64})

    assert (
        cli.main(
            [
                "--registry",
                str(path),
                "approve",
                "--sha256",
                "bad",
                "--document",
                "doc-4",
                "--reason",
                "坏哈希",
            ]
        )
        == 2
    )
    assert "refused" in capsys.readouterr().err
    assert FileAuthorizationRegistry(path).allowed_sha256() == frozenset({"d" * 64, "e" * 64})


def test_authorization_cli_defaults_to_the_same_registry_file_as_the_assemblies(
    monkeypatch, capsys, tmp_path
):
    """Without a flag or variable the CLI writes where the running API reads.

    The DEC-007 ledger scope binds the registry *path*, so a different default would refuse
    the existing ledger ("existing DEC ledger has a different scope") instead of using it;
    the fallback is therefore the same private root the server assemblies resolve
    (``/app/.verification/private`` inside the container). Every command prints the resolved
    path to stderr, and an explicit flag or environment variable still wins.
    """
    cli = load_cli()
    monkeypatch.delenv("DEC007_AUTHORIZATION_REGISTRY", raising=False)
    resolution = resolve_real_runtime_authorization(
        {"DEC007_AUTHORIZATION_ID": FULL_CAPABILITY_AUTHORIZATION_ID},
        private_root=cli.DEFAULT_PRIVATE_ROOT,
    )
    assert resolution.registry_path is not None
    assert cli.registry_path(None) == resolution.registry_path
    assert cli.registry_path("") == resolution.registry_path
    assert cli.registry_path("   ") == resolution.registry_path
    explicit = tmp_path / "explicit.jsonl"
    assert cli.registry_path(str(explicit)) == explicit
    assert cli.registry_path("   ") != explicit  # blank values never become a path
    # Listing a registry that does not exist yet is a valid, read-only no-op: it reports the
    # resolved path on stderr and never creates the file.
    default = resolution.registry_path
    assert not default.exists()
    assert cli.main(["list"]) == 0
    printed = capsys.readouterr()
    assert str(default) in printed.err
    assert "approved files: 0" in printed.out
    assert not default.exists()
