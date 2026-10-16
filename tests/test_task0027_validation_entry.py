"""The controlled round's entry point: fixed ceilings, read-only baseline, fail-closed preflight.

These tests cover the two operator entry points of the TASK-0027 controlled round:
``scripts/task0027_ledger_baseline.py`` (read-only ledger facts) and
``scripts/task0027_real_ai_validation_app.py`` (the isolated serving assembly whose ceilings
are code constants). Everything is local: the public-API health probe uses an explicit
synthetic transport, no test opens a socket, reads a credential or reaches a supplier.
"""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import task0027_ledger_baseline as baseline
import task0027_real_ai_validation_app as validation

from bidding_compliance.model_gateway.authorized_runtime import (
    AUTHORIZATION_LIMITS,
    FULL_CAPABILITY_AUTHORIZATION_ID,
    Dec005BudgetLedger,
)
from bidding_compliance.services.real_ai_runtime import (
    FileAuthorizationRegistry,
    resolve_real_runtime_authorization,
)

SCOPE = "b" * 64
APPROVED_DOCUMENT = "d" * 64
HISTORIC_BATCHES = 312
HISTORIC_SETTLED_CNY = Decimal("0.1035070")
EMBEDDING_CEILING = Decimal("0.10")
WIDENING_VARIABLES = (
    "DEC007_LLM_LIMIT",
    "DEC007_EMBEDDING_LIMIT",
    "DEC007_TOTAL_CNY",
    "DEC007_VALIDATION_LLM_LIMIT",
    "TASK0027_LLM_LIMIT",
    "VALIDATION_LLM_LIMIT",
    "LLM_LIMIT",
)


def request_hash(number: int) -> str:
    return f"{number:064x}"


def seed_baseline_ledger(path: Path, *, scope_sha256: str = SCOPE) -> Dec005BudgetLedger:
    """The recorded pre-round state: 0 LLM, 312 settled embedding batches, 0.1035070 CNY."""
    ledger = Dec005BudgetLedger(
        path, scope_sha256=scope_sha256, authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID
    )
    per_batch = Decimal("0.0003318")
    for number in range(HISTORIC_BATCHES - 1):
        reservation = ledger.reserve_external(
            kind="embedding", request_hash=request_hash(number), ceiling=EMBEDDING_CEILING
        )
        ledger.settle_external(reservation, per_batch)
    remainder = HISTORIC_SETTLED_CNY - per_batch * (HISTORIC_BATCHES - 1)
    reservation = ledger.reserve_external(
        kind="embedding", request_hash=request_hash(HISTORIC_BATCHES - 1), ceiling=EMBEDDING_CEILING
    )
    ledger.settle_external(reservation, remainder)
    assert ledger.summary()["llm_calls"] == 0
    assert Decimal(ledger.summary()["charged_or_reserved_cny"]) == HISTORIC_SETTLED_CNY
    return ledger


def healthy_api_transport() -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health"
        return httpx.Response(200, json={"status": "ok", "version": "0.1.0"})

    return httpx.MockTransport(handle)


def preflight_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "DEC007_AUTHORIZATION_ID": FULL_CAPABILITY_AUTHORIZATION_ID,
        "DEC007_LEDGER_PATH": str(tmp_path / "dec007-budget.sqlite3"),
        "DEC007_AUTHORIZATION_REGISTRY": str(tmp_path / "authorization-registry.jsonl"),
        "DASHSCOPE_API_KEY": "example-synthetic-credential",
        "BAILIAN_WORKSPACE_ID": "synthetic-workspace",
    }


def prepared_round(tmp_path: Path) -> dict[str, str]:
    """A round whose ledger, scope and registry all match the documented baseline."""
    environment = preflight_environment(tmp_path)
    resolution = resolve_real_runtime_authorization(environment, private_root=tmp_path)
    seed_baseline_ledger(resolution.ledger_path, scope_sha256=resolution.scope_sha256)
    return environment


def approve_synthetic_document(environment: dict[str, str]) -> None:
    """Step 2 of the ordered operator flow: register one frozen document, nothing else.

    A per-file approval deliberately does not change the ledger scope, so it never
    invalidates the ledger that already carries the prebuild counters.
    """
    registry = FileAuthorizationRegistry(Path(environment["DEC007_AUTHORIZATION_REGISTRY"]))
    registry.approve(
        sha256=APPROVED_DOCUMENT,
        document_id="synthetic-round-document",
        reason="本轮受控验证合成样本",
        approved_by="operator",
    )


def run_preflight(environment: dict[str, str], tmp_path: Path, **overrides):
    arguments = {
        "environment": environment,
        "private_root": tmp_path,
        "online_api_offline_verified": True,
        "client": httpx.Client(transport=healthy_api_transport()),
    }
    arguments.update(overrides)
    return validation.run_preflight(**arguments)  # type: ignore[arg-type]


# ------------------------------------------------------------- the ceilings are constants
def test_round_ceilings_are_the_documented_constants_and_stay_tighter_than_dec007():
    limits = validation.round_limits()
    assert (limits.llm_limit, limits.embedding_limit, limits.total_cny) == (
        4,
        322,
        Decimal("2"),
    )
    assert validation.assert_round_limits_bounded(limits) is limits
    hard = AUTHORIZATION_LIMITS[FULL_CAPABILITY_AUTHORIZATION_ID]
    assert (hard["llm"], hard["embedding"], hard["cny"]) == (300, 800, Decimal("30"))
    assert limits.llm_limit < hard["llm"]
    assert limits.embedding_limit < hard["embedding"]
    assert limits.total_cny < hard["cny"]


def test_no_environment_variable_or_cli_option_can_raise_the_round_ceilings(monkeypatch):
    for name in WIDENING_VARIABLES:
        monkeypatch.setenv(name, "300")
    limits = validation.round_limits()
    assert (limits.llm_limit, limits.embedding_limit, limits.total_cny) == (
        4,
        322,
        Decimal("2"),
    )
    parser = validation.build_parser()
    for argv in (["--llm-limit", "300"], ["--embedding-limit", "800"], ["--total-cny", "30"]):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)


def test_a_ceiling_that_is_not_strictly_tighter_than_dec007_is_refused(monkeypatch):
    monkeypatch.setattr(validation, "ROUND_LLM_LIMIT", 300)
    with pytest.raises(ValueError, match="strictly tighter"):
        validation.assert_round_limits_bounded(validation.round_limits())


# ------------------------------------------------------------------ baseline check script
def test_baseline_check_reports_the_four_values_and_never_writes(tmp_path, capsys):
    path = tmp_path / "dec007-budget.sqlite3"
    seed_baseline_ledger(path)
    before = path.read_bytes()
    assert baseline.main(["--ledger", str(path)]) == 0
    captured = capsys.readouterr()
    assert "llm_calls: 0 (expected 0)" in captured.out
    assert "embedding_batches: 312 (expected 312)" in captured.out
    assert "charged_or_reserved_cny: 0.1035070 (expected 0.1035070)" in captured.out
    assert "unsettled_requests: 0 (expected 0)" in captured.out
    assert "PASS" in captured.out
    assert path.read_bytes() == before  # read-only: the ledger bytes did not change


def test_baseline_mismatch_stops_the_round_without_resetting_the_ledger(tmp_path, capsys):
    path = tmp_path / "dec007-budget.sqlite3"
    ledger = seed_baseline_ledger(path)
    ledger.reserve_external(
        kind="llm", request_hash=request_hash(9000), ceiling=Decimal("0.25")
    )
    before = path.read_bytes()
    assert baseline.main(["--ledger", str(path)]) == 2
    captured = capsys.readouterr()
    assert "STOP" in captured.out + captured.err
    assert "llm_calls: observed 1, expected 0" in captured.out + captured.err
    assert "Do not delete, replace or reset the ledger" in captured.out + captured.err
    assert path.read_bytes() == before
    assert ledger.summary()["llm_calls"] == 1  # nothing was "fixed" by rewriting the file


def test_an_absent_ledger_is_reported_and_never_created(tmp_path, capsys):
    missing = tmp_path / "not-there" / "dec007-budget.sqlite3"
    assert baseline.main(["--ledger", str(missing)]) == 2
    assert "absent" in capsys.readouterr().err
    assert not missing.exists()


def test_baseline_defaults_follow_the_documented_round_values_and_the_environment(tmp_path):
    path = tmp_path / "dec007-budget.sqlite3"
    seed_baseline_ledger(path)
    assert baseline.main(["--ledger", str(path), "--json"]) == 0
    assert baseline.ROUND_BASELINE == {
        "llm_calls": 0,
        "embedding_batches": 312,
        "charged_or_reserved_cny": Decimal("0.1035070"),
        "unsettled_requests": 0,
    }
    environment = {"DEC007_LEDGER_PATH": str(path)}
    assert baseline.ledger_path_from(environment) == path
    assert (
        baseline.ledger_path_from({}, private_root=tmp_path)
        == tmp_path / "dec007-budget.sqlite3"
    )


# --------------------------------------------------------------------------- preflight
def test_preflight_passes_and_reports_the_round_ceilings_and_ledger_baseline(tmp_path):
    environment = prepared_round(tmp_path)
    outcome = run_preflight(environment, tmp_path)
    report = outcome.report.as_payload()
    assert report["round_limits"] == {"llm_limit": 4, "embedding_limit": 322, "total_cny": "2"}
    assert report["ledger"]["llm_calls"] == 0
    assert report["ledger"]["embedding_batches"] == 312
    assert report["ledger"]["charged_or_reserved_cny"] == "0.1035070"
    assert report["ledger"]["unsettled_requests"] == 0
    assert report["approved_documents"] == {"count": 0, "sha256": []}
    assert report["online_api"]["payload"] == {"status": "ok", "version": "0.1.0"}
    assert "not pinned in this preflight" in report["vector_index"]


def test_preflight_requires_the_operator_confirmation_that_the_public_api_is_offline(tmp_path):
    environment = prepared_round(tmp_path)
    with pytest.raises(validation.PreflightFailed, match="--online-api-offline-verified"):
        run_preflight(environment, tmp_path, online_api_offline_verified=False)


def test_preflight_refuses_an_unreachable_or_unhealthy_public_api(tmp_path):
    environment = prepared_round(tmp_path)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic unreachable public API")

    with pytest.raises(validation.PreflightFailed, match="not reachable"):
        run_preflight(
            environment, tmp_path, client=httpx.Client(transport=httpx.MockTransport(refuse))
        )
    down = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"detail": "synthetic maintenance"})
    )
    with pytest.raises(validation.PreflightFailed, match="health probe failed"):
        run_preflight(environment, tmp_path, client=httpx.Client(transport=down))


def test_preflight_refuses_a_ledger_that_is_not_at_the_documented_baseline(tmp_path):
    environment = prepared_round(tmp_path)
    resolution = resolve_real_runtime_authorization(environment, private_root=tmp_path)
    ledger = Dec005BudgetLedger(
        resolution.ledger_path,
        scope_sha256=resolution.scope_sha256,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    ledger.reserve_external(kind="llm", request_hash=request_hash(1), ceiling=Decimal("0.25"))
    with pytest.raises(validation.PreflightFailed, match="do not delete, replace or reset"):
        run_preflight(environment, tmp_path)


def test_preflight_refuses_a_ledger_of_a_different_scope(tmp_path):
    environment = prepared_round(tmp_path)
    other = tmp_path / "other" / "dec007-budget.sqlite3"
    seed_baseline_ledger(other, scope_sha256="c" * 64)
    environment = {**environment, "DEC007_LEDGER_PATH": str(other)}
    with pytest.raises(validation.PreflightFailed, match="different authorization scope"):
        run_preflight(environment, tmp_path)


def test_preflight_refuses_a_foreign_authorization_identity_or_missing_credentials(tmp_path):
    environment = prepared_round(tmp_path)
    with pytest.raises(validation.PreflightFailed, match="DEC-007 authorization"):
        run_preflight(
            {**environment, "DEC007_AUTHORIZATION_ID": "DEC-005-2026-10-15"}, tmp_path
        )
    without_key = {key: value for key, value in environment.items() if key != "DASHSCOPE_API_KEY"}
    with pytest.raises(validation.PreflightFailed, match="DASHSCOPE_API_KEY"):
        run_preflight(without_key, tmp_path)


# ----------------------------------------------------------------- isolated serving assembly
def test_serving_assembly_binds_the_round_ceilings_and_refuses_to_build_the_index(
    tmp_path, monkeypatch
):
    environment = prepared_round(tmp_path)
    approve_synthetic_document(environment)  # the documented step 2, before serving
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    captured: dict[str, object] = {}

    def fake_retriever_factory(**kwargs):
        captured.update(kwargs)
        return object()

    def fake_engine(**kwargs):
        captured["engine"] = kwargs
        return SimpleNamespace(**kwargs)

    def fake_app(settings, *, review_engine):
        return SimpleNamespace(state=SimpleNamespace(review_engine=review_engine))

    monkeypatch.setattr(validation, "create_real_retriever_factory", fake_retriever_factory)
    monkeypatch.setattr(validation, "AuthorizedRealReviewEngine", fake_engine)
    monkeypatch.setattr(validation, "create_app", fake_app)
    app, outcome = validation.build_app(
        environment=environment,
        private_root=tmp_path,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        client=httpx.Client(transport=healthy_api_transport()),
        online_api_offline_verified=True,
    )
    budget = captured["budget"]
    assert (budget.llm_limit, budget.embedding_limit, budget.total_cny) == (
        4,
        322,
        Decimal("2"),
    )
    assert captured["allow_build"] is False  # serving never builds the index
    assert captured["private_root"] == tmp_path
    assert app.state.external_budget is budget
    assert app.state.deploy_review_mode == "task0027-validation"
    assert app.state.authorization_id == FULL_CAPABILITY_AUTHORIZATION_ID
    assert outcome.report.llm_limit == 4 and outcome.report.embedding_limit == 322
    assert outcome.report.approved_documents == {"count": 1, "sha256": [APPROVED_DOCUMENT]}
    # The engine receives the live document source: a revocation applies without a restart.
    assert callable(captured["engine"]["allowed_document_sha256"])


def test_validation_entry_exits_non_zero_when_a_precondition_fails(tmp_path, monkeypatch, capsys):
    environment = prepared_round(tmp_path)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DEC007_ONLINE_API_URL", "http://synthetic.invalid")
    # A public API that cannot be reached stops the round instead of serving (or calling).
    assert (
        validation.main(
            [
                "--preflight",
                "--online-api-url",
                "http://synthetic.invalid",
                "--online-api-offline-verified",
            ]
        )
        == 2
    )
    assert "not reachable" in capsys.readouterr().err
    # Any failed precondition exits non-zero without serving: the operator URL variable is
    # unreachable here as well, so no app is ever started by this call.
    assert validation.main([]) == 2
    assert "STOP" in capsys.readouterr().err


def test_validation_entry_reads_the_authorization_identity_registry_and_ledger_from_the_environment(
    tmp_path, monkeypatch
):
    environment = prepared_round(tmp_path)
    # The mapping given to the assembly decides; an unrelated process variable is ignored.
    monkeypatch.setenv("DEC007_LEDGER_PATH", str(tmp_path / "decoy.sqlite3"))
    outcome = run_preflight(environment, tmp_path)
    resolution = outcome.resolution
    assert resolution.authorization_id == FULL_CAPABILITY_AUTHORIZATION_ID
    assert resolution.ledger_path == Path(environment["DEC007_LEDGER_PATH"])
    assert resolution.registry_path == Path(environment["DEC007_AUTHORIZATION_REGISTRY"])
    assert outcome.report.registry_path == environment["DEC007_AUTHORIZATION_REGISTRY"]
    assert outcome.report.ledger_path == environment["DEC007_LEDGER_PATH"]
