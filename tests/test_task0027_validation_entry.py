"""The controlled round's entry point: fixed ceilings, read-only baseline, fail-closed preflight.

These tests cover the two operator entry points of the TASK-0027 controlled round:
``scripts/task0027_ledger_baseline.py`` (read-only ledger facts) and
``scripts/task0027_real_ai_validation_app.py`` (the isolated serving assembly whose ceilings
are code constants, whose publication/revision are mandatory and whose preflight compares the
prebuilt index manifest and the host offline evidence).

Everything is local and synthetic: the frozen corpus is a three-article snapshot inside
``tmp_path``, the prebuilt index is a real build of that snapshot through a synthetic
embedding transport, the host evidence is produced by the host script over canned docker
output, the public-API health probe uses an explicit synthetic transport and no test opens a
socket, reads a real credential or reaches a supplier.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import task0027_ledger_baseline as baseline
import task0027_real_ai_validation_app as validation
import verify_api_offline_mode as host

from bidding_compliance.legal.contracts import LegalManifest, LegalVersion
from bidding_compliance.legal.corpus import digest, ingest
from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    DashScopeEmbeddingSettings,
)
from bidding_compliance.legal.vector_index import SQLiteVectorIndex, VectorIndexManifest
from bidding_compliance.model_gateway.authorized_runtime import (
    AUTHORIZATION_LIMITS,
    FULL_CAPABILITY_AUTHORIZATION_ID,
    Dec005BudgetLedger,
    MetadataAuditSink,
)
from bidding_compliance.services.real_ai_runtime import (
    FileAuthorizationRegistry,
    resolve_real_runtime_authorization,
)
from bidding_compliance.services.real_embedding_runtime import (
    EMBEDDING_INPUT_PRICE_PER_MILLION,
    ScopedEmbeddingGuard,
    build_authorized_vector_index,
    real_embedding_settings,
)

SCOPE = "b" * 64
APPROVED_DOCUMENT = "d" * 64
HISTORIC_BATCHES = 312
HISTORIC_PREBUILD_CNY = Decimal("0.1035070")
HISTORIC_SETTLED_CNY = Decimal("0.1062161")
HISTORIC_LLM_CALLS = 2
# The two LLM reservations of the recorded phase-one round. Only their sum (the documented
# total minus the prebuild's 0.1035070 CNY) is recorded in the operator's baseline; the split
# between the two reservations is a fixture detail, not a measured value.
HISTORIC_LLM_SETTLED = (Decimal("0.0015000"), Decimal("0.0012091"))
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
PROJECT = "tender-review-demo"
API_CONTAINER_ID = "1" * 64
API_IMAGE = "tender-review-api:demo"
PUBLICATION = "pub-2026-10-16"
REVISION = "rev-2026-10-16"
CORPUS_CLAUSES = 3
# The evidence freshness window is measured against the real clock at preflight time, so the
# synthetic evidence is stamped "now" and staleness tests move the clock, never the stamp.
EVIDENCE_NOW = datetime.now(UTC).replace(microsecond=0)
ARTICLES = ("第一条", "第二条", "第三条")


def request_hash(number: int) -> str:
    return f"{number:064x}"


# --------------------------------------------------------------------- synthetic inputs
def seed_baseline_ledger(path: Path, *, scope_sha256: str = SCOPE) -> Dec005BudgetLedger:
    """The recorded phase-two pre-round state: 2 LLM, 312 settled embedding batches, 0.1062161."""
    ledger = Dec005BudgetLedger(
        path, scope_sha256=scope_sha256, authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID
    )
    per_batch = Decimal("0.0003318")
    for number in range(HISTORIC_BATCHES - 1):
        reservation = ledger.reserve_external(
            kind="embedding", request_hash=request_hash(number), ceiling=EMBEDDING_CEILING
        )
        ledger.settle_external(reservation, per_batch)
    remainder = HISTORIC_PREBUILD_CNY - per_batch * (HISTORIC_BATCHES - 1)
    reservation = ledger.reserve_external(
        kind="embedding", request_hash=request_hash(HISTORIC_BATCHES - 1), ceiling=EMBEDDING_CEILING
    )
    ledger.settle_external(reservation, remainder)
    for offset, settled in enumerate(HISTORIC_LLM_SETTLED):
        reservation = ledger.reserve_external(
            kind="llm",
            request_hash=request_hash(900 + offset),
            ceiling=Decimal("0.25"),
        )
        ledger.settle_external(reservation, settled)
    assert ledger.summary()["llm_calls"] == HISTORIC_LLM_CALLS
    assert Decimal(ledger.summary()["charged_or_reserved_cny"]) == HISTORIC_SETTLED_CNY
    return ledger


def synthetic_corpus(root: Path, *, clauses: int = CORPUS_CLAUSES) -> Path:
    """A frozen snapshot with ``clauses`` short articles, at the repository-relative path."""
    articles = list(ARTICLES[:clauses])
    source = root / "synthetic-law.txt"
    source.write_text(
        "合成法规\n"
        + "".join(
            f"{article} 合成采购规则第{number}项，仅用于离线测试。\n"
            for number, article in enumerate(articles, start=1)
        ),
        encoding="utf-8",
        newline="\n",
    )
    version = LegalVersion.model_validate(
        {
            "law_id": "synthetic-law",
            "title": "合成法规",
            "version": "rev-1",
            "text_path": source.name,
            "text_hash": digest(source.read_bytes()),
            "source_uri": "https://example.gov.cn/synthetic",
            "source_snapshot_path": source.name,
            "source_hash": digest(source.read_bytes()),
            "captured_on": "2026-10-14",
            "verification": "verified",
            "verified_through": "2026-10-14",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "end_status": "confirmed_open",
            "jurisdictions": ["CN/福建"],
            "procurement_types": ["government"],
            "project_types": ["works"],
            "authority": "regulation",
            "verification_note": "仅用于工程测试的合成法规，不是真实法律依据。",
            "expected_articles": articles,
            "applicability": {
                "procurement_methods": ["tender", "non_tender"],
                "buyer_types": ["government_entity", "enterprise", "other"],
                "subject_types": ["works", "goods", "services"],
                "legal_frameworks": ["tendering", "government_procurement"],
            },
        }
    )
    manifest = root / validation.LEGAL_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(LegalManifest(versions=(version,)).model_dump_json(), encoding="utf-8")
    return manifest


def legal_index(root: Path):
    manifest_path = root / validation.LEGAL_MANIFEST
    return ingest(root, LegalManifest.model_validate_json(manifest_path.read_text()))


class SyntheticEmbeddingTransport(httpx.BaseTransport):
    """A synthetic supplier for the prebuild; records every request body."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        values = body["input"]
        self.calls.append(list(values))
        return httpx.Response(
            200,
            json={
                "id": "synthetic-request",
                "model": body["model"],
                "object": "list",
                "usage": {"total_tokens": len(values), "prompt_tokens": len(values)},
                "data": [
                    {
                        "index": position,
                        "object": "embedding",
                        "embedding": [1.0, float(position)]
                        + [0.0] * (body["dimensions"] - 2),
                    }
                    for position in range(len(values))
                ],
            },
        )


def prebuild_index(
    root: Path,
    environment: dict[str, str],
    *,
    publication_id: str = PUBLICATION,
    revision_id: str = REVISION,
):
    """Build the authorized index for the synthetic corpus and write its manifest."""
    index = legal_index(root)
    ledger = Dec005BudgetLedger(
        root / "prebuild-budget.sqlite3",
        scope_sha256="a" * 64,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    guard = ScopedEmbeddingGuard(ledger)
    key = environment["DASHSCOPE_API_KEY"]
    workspace = environment["BAILIAN_WORKSPACE_ID"]
    provider = DashScopeEmbeddingProvider(
        real_embedding_settings(api_key=key, workspace_id=workspace),
        client=httpx.Client(transport=SyntheticEmbeddingTransport(), trust_env=False),
        guard=guard,
        audit_sink=MetadataAuditSink(root / "embedding-audit.jsonl"),
        input_price_per_million=EMBEDDING_INPUT_PRICE_PER_MILLION,
    )
    manifest, _plan = build_authorized_vector_index(
        index=index,
        provider=provider,
        guard=guard,
        store=SQLiteVectorIndex(root / validation.INDEX_FILE),
        publication_id=publication_id,
        revision_id=revision_id,
    )
    (root / validation.PREBUILT_MANIFEST_FILE).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return manifest


def evidence_document(
    root: Path,
    *,
    mode: str = "offline",
    api_id: str = API_CONTAINER_ID,
    project: str = PROJECT,
    image: str = API_IMAGE,
    command: list[str] | None = None,
    extra_containers: tuple[tuple[str, str, str], ...] = (),
    checked_at: datetime = EVIDENCE_NOW,
):
    """Generate real host evidence over canned docker output; returns (exit code, path)."""
    entries = [
        {
            "ID": api_id,
            "Name": f"{project}-api-1",
            "Project": project,
            "Service": "api",
            "State": "running",
        }
    ]
    documents = {
        api_id: {
            "Id": api_id,
            "Name": f"/{project}-api-1",
            "Image": "sha256:" + "a" * 64,
            "Config": {
                "Image": image,
                "Entrypoint": None,
                "Cmd": command or ["python", "deploy/api_entry.py"],
                "Env": [
                    f"DEPLOY_REVIEW_MODE={mode}",
                    "APP_ENV=staging",
                    "PATH=/usr/bin",
                ],
            },
            "State": {"Status": "running", "Running": True},
        }
    }
    for container_id, name, container_mode in extra_containers:
        entries.append(
            {
                "ID": container_id,
                "Name": name,
                "Project": project,
                "Service": "api",
                "State": "running",
            }
        )
        documents[container_id] = {
            "Id": container_id,
            "Name": f"/{name}",
            "Image": "sha256:" + "b" * 64,
            "Config": {
                "Image": API_IMAGE,
                "Entrypoint": None,
                "Cmd": ["python", "scripts/task0027_real_ai_validation_app.py"],
                "Env": [f"DEPLOY_REVIEW_MODE={container_mode}"],
            },
            "State": {"Status": "running", "Running": True},
        }

    def runner(args):
        if args[0] == "compose":
            return host.CommandResult(0, "\n".join(json.dumps(entry) for entry in entries), "")
        if args[0] == "ps":
            return host.CommandResult(
                0, "\n".join(str(entry["ID"]) for entry in entries), ""
            )
        if args[0] == "inspect":
            document = documents.get(args[-1])
            if document is None:
                return host.CommandResult(1, "", f"Error: No such container: {args[-1]}")
            return host.CommandResult(0, json.dumps([document]), "")
        return host.CommandResult(2, "", "unsupported")

    destination = root / "host-evidence"
    exit_code = host.main(
        [
            "--evidence-dir",
            str(destination),
            "--compose-file",
            "docker-compose.demo.yml",
            "--env-file",
            str(root / "absent.env"),
            "--expected-image-ref",
            API_IMAGE,
        ],
        runner=runner,
        now=lambda: checked_at,
    )
    files = sorted(destination.glob("api-offline-*.json"))
    assert len(files) == 1
    return exit_code, files[0]


class ProbeRecorder:
    """A synthetic public-API health endpoint that records every request it receives."""

    def __init__(self, status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.status_code = status_code

        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.status_code != 200:
                return httpx.Response(self.status_code, json={"detail": "synthetic"})
            return httpx.Response(200, json={"status": "ok", "version": "0.1.0"})

        self.transport = httpx.MockTransport(handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport)


@dataclass(frozen=True, slots=True)
class Round:
    """One prepared controlled round: environment, ledger, corpus, prebuilt index, evidence."""

    root: Path
    environment: dict[str, str]
    evidence: Path

    def arguments(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "private_root": self.root,
            "online_api_offline_verified": True,
            "publication_id": PUBLICATION,
            "revision_id": REVISION,
            "corpus_root": self.root,
            "expected_item_count": CORPUS_CLAUSES,
            "expected_source_item_count": CORPUS_CLAUSES,
            "host_offline_evidence": str(self.evidence),
            "api_container_id": API_CONTAINER_ID,
            "compose_project": PROJECT,
            "now": EVIDENCE_NOW + timedelta(minutes=1),
        }

    def serving_arguments(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.arguments().items()
            if key not in {"now"}
        }

    def preflight(self, **overrides) -> validation.PreflightOutcome:
        recorder = ProbeRecorder()
        arguments = self.arguments()
        arguments["client"] = recorder.client()
        arguments.update(overrides)
        outcome = validation.run_preflight(**arguments)
        # Nothing local ever reaches the network: the probe is the only request there is.
        assert all(request.url.path == "/api/v1/health" for request in recorder.requests)
        return outcome


def rewrite_manifest(
    root: Path, original: VectorIndexManifest, **changes: Any
) -> VectorIndexManifest:
    """A *valid* manifest with the same build identity but a changed recorded value.

    Editing the JSON directly would only prove that the digest check works; these tests pin
    the semantic comparisons (publication, revision, snapshot, identity, counts) instead.
    """
    manifest_path = root / validation.PREBUILT_MANIFEST_FILE
    identity = changes.get("embedding_identity", original.embedding_identity)
    snapshot = changes.get("legal_snapshot_sha256", original.legal_snapshot_sha256)
    publication_id = changes.get("publication_id", original.publication_id)
    revision_id = changes.get("revision_id", original.revision_id)
    rewritten = VectorIndexManifest.create(
        build_id=VectorIndexManifest.build_identity(
            identity, snapshot, publication_id, revision_id, original.coverage_sha256
        ),
        legal_snapshot_sha256=snapshot,
        publication_id=publication_id,
        revision_id=revision_id,
        embedding_identity=identity,
        item_count=changes.get("item_count", original.item_count),
        source_item_count=changes.get("source_item_count", original.source_item_count),
        coverage_sha256=original.coverage_sha256,
        items_sha256=original.items_sha256,
    )
    manifest_path.write_text(rewritten.model_dump_json(indent=2), encoding="utf-8")
    return original


def manifest_bytes(root: Path) -> bytes:
    return (root / validation.PREBUILT_MANIFEST_FILE).read_bytes()


def restore_manifest(root: Path, content: bytes) -> None:
    (root / validation.PREBUILT_MANIFEST_FILE).write_bytes(content)


def preflight_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "DEC007_AUTHORIZATION_ID": FULL_CAPABILITY_AUTHORIZATION_ID,
        "DEC007_LEDGER_PATH": str(tmp_path / "dec007-budget.sqlite3"),
        "DEC007_AUTHORIZATION_REGISTRY": str(tmp_path / "authorization-registry.jsonl"),
        "DASHSCOPE_API_KEY": "example-synthetic-credential",
        "BAILIAN_WORKSPACE_ID": "synthetic-workspace",
        "DEC007_API_CONTAINER_ID": API_CONTAINER_ID,
        "DEPLOY_COMPOSE_PROJECT": PROJECT,
    }


def prepared_round(tmp_path: Path) -> Round:
    """A round whose ledger, scope, corpus, index, evidence and identity all match."""
    environment = preflight_environment(tmp_path)
    resolution = resolve_real_runtime_authorization(environment, private_root=tmp_path)
    seed_baseline_ledger(resolution.ledger_path, scope_sha256=resolution.scope_sha256)
    synthetic_corpus(tmp_path)
    prebuild_index(tmp_path, environment)
    exit_code, evidence = evidence_document(tmp_path)
    assert exit_code == 0
    return Round(root=tmp_path, environment=environment, evidence=evidence)


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


@pytest.fixture(name="round_")
def round_fixture(tmp_path: Path) -> Round:
    return prepared_round(tmp_path)


def patch_probe(monkeypatch, *, status_code: int = 200) -> ProbeRecorder:
    """Replace the CLI's health client so a CLI-level test never opens a socket."""
    recorder = ProbeRecorder(status_code)
    monkeypatch.setattr(validation, "make_probe_client", recorder.client)
    return recorder


def cli_deployment(round_: Round, monkeypatch) -> None:
    """Point the entry point's deployment defaults at the synthetic round under test.

    The one-off container resolves its private root (the ``modelstate`` volume), its corpus
    and its pinned corpus counts from module constants; a CLI-level test overrides exactly
    those three plus the environment mapping (which carries the evidence path, the api
    container id and the compose project). The health client stays the real one.
    """
    monkeypatch.setattr(validation, "PRIVATE_ROOT", round_.root)
    monkeypatch.setattr(validation, "ROOT", round_.root)
    monkeypatch.setattr(validation, "EXPECTED_PREBUILT_ITEM_COUNT", CORPUS_CLAUSES)
    monkeypatch.setattr(validation, "EXPECTED_PREBUILT_SOURCE_ITEM_COUNT", CORPUS_CLAUSES)
    for name, value in round_.environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(validation.HOST_OFFLINE_EVIDENCE_VARIABLE, str(round_.evidence))


def cli_context(round_: Round, monkeypatch) -> ProbeRecorder:
    """The same deployment with the health probe replaced by a synthetic endpoint."""
    cli_deployment(round_, monkeypatch)
    return patch_probe(monkeypatch)


def cli_arguments(round_: Round, *extra: str) -> list[str]:
    return [
        "--preflight",
        "--publication-id",
        PUBLICATION,
        "--revision-id",
        REVISION,
        "--online-api-offline-verified",
        *extra,
    ]


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
    assert (hard["llm"], hard["embedding"], hard["cny"]) == (2000, 2000, Decimal("200"))
    assert limits.llm_limit < hard["llm"]
    assert limits.embedding_limit < hard["embedding"]
    assert limits.total_cny < hard["cny"]


def test_no_environment_variable_or_cli_option_can_raise_the_round_ceilings(monkeypatch):
    for name in WIDENING_VARIABLES:
        monkeypatch.setenv(name, "2000")
    limits = validation.round_limits()
    assert (limits.llm_limit, limits.embedding_limit, limits.total_cny) == (
        4,
        322,
        Decimal("2"),
    )
    parser = validation.build_parser()
    for argv in (
        ["--llm-limit", "2000"],
        ["--embedding-limit", "2000"],
        ["--total-cny", "200"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["--publication-id", PUBLICATION, "--revision-id", REVISION, *argv]
            )


def test_a_ceiling_that_is_not_strictly_tighter_than_dec007_is_refused(monkeypatch):
    monkeypatch.setattr(validation, "ROUND_LLM_LIMIT", 2000)
    with pytest.raises(ValueError, match="strictly tighter"):
        validation.assert_round_limits_bounded(validation.round_limits())


# ------------------------------------------------------------------ baseline check script
def test_baseline_check_reports_the_four_values_and_never_writes(tmp_path, capsys):
    path = tmp_path / "dec007-budget.sqlite3"
    seed_baseline_ledger(path)
    before = path.read_bytes()
    assert baseline.main(["--ledger", str(path)]) == 0
    captured = capsys.readouterr()
    assert "llm_calls: 2 (expected 2)" in captured.out
    assert "embedding_batches: 312 (expected 312)" in captured.out
    assert "charged_or_reserved_cny: 0.1062161 (expected 0.1062161)" in captured.out
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
    assert "llm_calls: observed 3, expected 2" in captured.out + captured.err
    assert "Do not delete, replace or reset the ledger" in captured.out + captured.err
    assert path.read_bytes() == before
    assert ledger.summary()["llm_calls"] == 3  # nothing was "fixed" by rewriting the file


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
        "llm_calls": 2,
        "embedding_batches": 312,
        "charged_or_reserved_cny": Decimal("0.1062161"),
        "unsettled_requests": 0,
    }
    environment = {"DEC007_LEDGER_PATH": str(path)}
    assert baseline.ledger_path_from(environment) == path
    assert (
        baseline.ledger_path_from({}, private_root=tmp_path)
        == tmp_path / "dec007-budget.sqlite3"
    )


# ----------------------------------------------------- publication/revision are mandatory
def test_publication_and_revision_are_mandatory_and_never_defaulted(round_, capsys):
    for argument in ("publication_id", "revision_id"):
        with pytest.raises(validation.PreflightFailed, match="--publication-id"):
            round_.preflight(**{argument: ""})
        with pytest.raises(validation.PreflightFailed, match="--publication-id"):
            round_.preflight(**{argument: "   "})
    # The CLI refuses without them (argparse usage error, non-zero) and prints no verdict.
    with pytest.raises(SystemExit) as exit_info:
        validation.main(["--preflight", "--online-api-offline-verified"])
    assert exit_info.value.code == 2
    printed = capsys.readouterr()
    assert "prebuilt index verified" not in printed.out + printed.err
    assert "--publication-id" in printed.err or "--publication-id" in printed.out


def test_the_index_manifest_constants_are_the_frozen_corpus_counts():
    assert validation.EXPECTED_PREBUILT_ITEM_COUNT == 3112
    assert validation.EXPECTED_PREBUILT_SOURCE_ITEM_COUNT == 3120
    assert validation.PREBUILT_MANIFEST_FILE == "vector-manifest.json"
    assert validation.PREBUILT_INDEX_VERIFIED == "prebuilt index verified"


# --------------------------------------------------------------------------- preflight
def test_preflight_passes_and_reports_the_round_ceilings_ledger_and_index(round_):
    report = round_.preflight().report.as_payload()
    assert report["round_limits"] == {"llm_limit": 4, "embedding_limit": 322, "total_cny": "2"}
    assert report["ledger"]["llm_calls"] == 2
    assert report["ledger"]["embedding_batches"] == 312
    assert report["ledger"]["charged_or_reserved_cny"] == "0.1062161"
    assert report["ledger"]["unsettled_requests"] == 0
    assert report["approved_documents"] == {"count": 0, "sha256": []}
    assert report["online_api"]["payload"] == {"status": "ok", "version": "0.1.0"}
    assert report["operator_offline_confirmed"] is True
    index = report["prebuilt_index"]
    assert index["publication_id"] == PUBLICATION and index["revision_id"] == REVISION
    assert index["item_count"] == CORPUS_CLAUSES
    assert index["source_item_count"] == CORPUS_CLAUSES
    assert len(index["build_id"]) == 64 and len(index["legal_snapshot_sha256"]) == 64
    assert index["manifest_path"].endswith(validation.PREBUILT_MANIFEST_FILE)
    evidence = report["host_offline_evidence"]
    assert evidence["compose_project"] == PROJECT
    assert evidence["api_container_id"] == API_CONTAINER_ID
    assert evidence["deploy_review_mode"] == "offline"
    assert evidence["api_image_reference"] == API_IMAGE
    assert evidence["age_seconds"] == 60.0


def test_the_preflight_prints_the_prebuilt_index_verification_line(round_, monkeypatch, capsys):
    cli_context(round_, monkeypatch)
    assert validation.main(cli_arguments(round_)) == 0
    printed = capsys.readouterr()
    assert validation.PREBUILT_INDEX_VERIFIED in printed.out
    line = next(
        item for item in printed.out.splitlines() if validation.PREBUILT_INDEX_VERIFIED in item
    )
    index = round_.preflight().report.as_payload()["prebuilt_index"]
    assert f"build_id={index['build_id']}" in line
    assert f"item_count={CORPUS_CLAUSES}" in line
    assert f"source_item_count={CORPUS_CLAUSES}" in line
    assert "PASS: preflight complete" in printed.out


def test_a_manifest_of_a_different_publication_or_revision_is_refused(round_, monkeypatch, capsys):
    with pytest.raises(validation.PreflightFailed, match="belongs to publication/revision"):
        round_.preflight(publication_id="pub-other")
    with pytest.raises(validation.PreflightFailed, match="belongs to publication/revision"):
        round_.preflight(revision_id="rev-other")
    # CLI level: a foreign publication exits non-zero and prints no verified line, because
    # the comparison happens before any report (and before any request) exists.
    cli_context(round_, monkeypatch)
    assert validation.main([*cli_arguments(round_), "--publication-id", "pub-other"]) == 2
    printed = capsys.readouterr()
    assert validation.PREBUILT_INDEX_VERIFIED not in printed.out + printed.err
    assert "STOP" in printed.err


def test_a_manifest_with_a_different_item_count_or_snapshot_is_refused(round_):
    original_bytes = manifest_bytes(round_.root)
    original = VectorIndexManifest.model_validate_json(original_bytes)
    try:
        rewrite_manifest(round_.root, original, item_count=CORPUS_CLAUSES - 1)
        with pytest.raises(validation.PreflightFailed, match="item_count"):
            round_.preflight()

        restore_manifest(round_.root, original_bytes)
        rewrite_manifest(round_.root, original, source_item_count=CORPUS_CLAUSES + 1)
        with pytest.raises(validation.PreflightFailed, match="source_item_count"):
            round_.preflight()

        restore_manifest(round_.root, original_bytes)
        rewrite_manifest(round_.root, original, legal_snapshot_sha256="c" * 64)
        with pytest.raises(validation.PreflightFailed, match="different legal snapshot"):
            round_.preflight()

        other_identity = DashScopeEmbeddingSettings(
            enabled=True,
            region="beijing",
            workspace_id="synthetic-workspace",
            model_id="text-embedding-v4",
            dimensions=512,
        ).identity()
        restore_manifest(round_.root, original_bytes)
        rewrite_manifest(round_.root, original, embedding_identity=other_identity)
        with pytest.raises(validation.PreflightFailed, match="different embedding identity"):
            round_.preflight()

        # A manifest whose recorded digest no longer matches its own body is refused too:
        # the file cannot be edited into a "verified" state without recomputing the identity.
        restore_manifest(round_.root, original_bytes)
        tampered = json.loads(original_bytes.decode("utf-8"))
        tampered["item_count"] = CORPUS_CLAUSES - 1
        restore_manifest(round_.root, json.dumps(tampered).encode("utf-8"))
        with pytest.raises(validation.PreflightFailed, match="not a valid manifest"):
            round_.preflight()
    finally:
        restore_manifest(round_.root, original_bytes)


def test_a_missing_manifest_or_index_store_is_refused_without_writing(round_, tmp_path):
    # Neither refusal may create anything: an absent manifest or an absent store is reported,
    # never "initialised", and the store is opened read-only afterwards.
    empty = tmp_path / "no-manifest"
    empty.mkdir()
    with pytest.raises(validation.PreflightFailed, match="manifest is absent"):
        validation.verify_prebuilt_index(
            environment=round_.environment,
            private_root=empty,
            publication_id=PUBLICATION,
            revision_id=REVISION,
            corpus_root=round_.root,
        )
    assert not (empty / validation.PREBUILT_MANIFEST_FILE).exists()

    storeless = tmp_path / "no-store"
    storeless.mkdir()
    (storeless / validation.PREBUILT_MANIFEST_FILE).write_bytes(manifest_bytes(round_.root))
    with pytest.raises(validation.PreflightFailed, match="index store is absent"):
        validation.verify_prebuilt_index(
            environment=round_.environment,
            private_root=storeless,
            publication_id=PUBLICATION,
            revision_id=REVISION,
            corpus_root=round_.root,
            expected_item_count=CORPUS_CLAUSES,
            expected_source_item_count=CORPUS_CLAUSES,
        )
    assert not (storeless / validation.INDEX_FILE).exists()


def test_the_index_check_never_writes_to_the_round_files(round_):
    ledger_path = Path(round_.environment["DEC007_LEDGER_PATH"])
    manifest_path = round_.root / validation.PREBUILT_MANIFEST_FILE
    store_path = round_.root / validation.INDEX_FILE
    before = (ledger_path.read_bytes(), manifest_path.read_bytes(), store_path.read_bytes())
    round_.preflight()
    assert (
        ledger_path.read_bytes(),
        manifest_path.read_bytes(),
        store_path.read_bytes(),
    ) == before


# ------------------------------------------------------- host evidence gates the preflight
def test_the_operator_flag_alone_is_not_evidence(round_):
    with pytest.raises(validation.PreflightFailed, match="host offline evidence is not acceptable"):
        round_.preflight(host_offline_evidence="")
    with pytest.raises(validation.PreflightFailed, match="is absent"):
        round_.preflight(host_offline_evidence=round_.root / "no-such-file.json")
    # The flag keeps its own meaning: without it the round stops even with valid evidence.
    with pytest.raises(validation.PreflightFailed, match="operator confirmation missing"):
        round_.preflight(online_api_offline_verified=False)


def test_a_stale_unknown_or_untrusted_evidence_file_is_refused(round_, monkeypatch, capsys):
    with pytest.raises(validation.PreflightFailed, match="freshness window"):
        round_.preflight(now=EVIDENCE_NOW + timedelta(hours=2))
    with pytest.raises(validation.PreflightFailed, match="future"):
        round_.preflight(now=EVIDENCE_NOW - timedelta(hours=1))

    _exit_code, untrusted = evidence_document(
        round_.root,
        mode="authorized-real",
        checked_at=EVIDENCE_NOW,
    )
    with pytest.raises(validation.PreflightFailed, match="verdict is 'untrusted'"):
        round_.preflight(host_offline_evidence=untrusted)

    other = round_.root / "unknown-evidence"
    other.mkdir()
    unknown = other / "api-offline-20261016T030000Z.json"
    unknown.write_text(
        json.dumps(
            {
                **json.loads(round_.evidence.read_text(encoding="utf-8")),
                "verdict": "unknown",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(validation.PreflightFailed, match="verdict is 'unknown'"):
        round_.preflight(host_offline_evidence=unknown)

    # CLI level: the same refusals exit non-zero and never print the verified line.
    cli_context(round_, monkeypatch)
    monkeypatch.setenv("DEC007_HOST_OFFLINE_EVIDENCE", str(untrusted))
    assert validation.main([*cli_arguments(round_)]) == 2
    printed = capsys.readouterr()
    assert validation.PREBUILT_INDEX_VERIFIED not in printed.out + printed.err
    assert "STOP" in printed.err


def test_evidence_of_another_container_or_project_is_refused(round_):
    _exit_code, foreign = evidence_document(
        round_.root / "foreign",
        api_id="9" * 64,
        checked_at=EVIDENCE_NOW,
    )
    with pytest.raises(validation.PreflightFailed, match="different api container"):
        round_.preflight(host_offline_evidence=foreign)
    with pytest.raises(validation.PreflightFailed, match="different compose project"):
        round_.preflight(compose_project="other-project")
    with pytest.raises(validation.PreflightFailed, match="compose project is required"):
        round_.preflight(compose_project="")
    without_identity = {
        key: value
        for key, value in round_.environment.items()
        if key != "DEC007_API_CONTAINER_ID"
    }
    with pytest.raises(validation.PreflightFailed, match="DEC007_API_CONTAINER_ID"):
        round_.preflight(environment=without_identity, api_container_id=None)
    without_project = {
        key: value for key, value in round_.environment.items() if key != "DEPLOY_COMPOSE_PROJECT"
    }
    with pytest.raises(validation.PreflightFailed, match="DEPLOY_COMPOSE_PROJECT"):
        round_.preflight(environment=without_project, compose_project=None)


def test_the_evidence_freshness_window_is_configurable_and_bounded(round_):
    assert round_.preflight(host_offline_evidence_max_age_seconds=60).report.host_offline_evidence[
        "max_age_seconds"
    ] == 60
    with pytest.raises(validation.PreflightFailed, match="60..3600"):
        round_.preflight(host_offline_evidence_max_age_seconds=30)
    with pytest.raises(validation.PreflightFailed, match="60..3600"):
        round_.preflight(host_offline_evidence_max_age_seconds=7200)
    environment = {**round_.environment, "DEC007_HOST_OFFLINE_EVIDENCE_MAX_AGE_SECONDS": "abc"}
    with pytest.raises(validation.PreflightFailed, match="must be an integer"):
        round_.preflight(environment=environment, host_offline_evidence_max_age_seconds=None)
    default = round_.preflight(
        environment={**round_.environment, "DEC007_HOST_OFFLINE_EVIDENCE_MAX_AGE_SECONDS": "900"}
    )
    assert default.report.host_offline_evidence["max_age_seconds"] == 900


def test_the_evidence_file_is_read_from_the_environment_variable(round_):
    environment = {**round_.environment, "DEC007_HOST_OFFLINE_EVIDENCE": str(round_.evidence)}
    outcome = round_.preflight(environment=environment, host_offline_evidence=None)
    assert outcome.report.host_offline_evidence["path"].endswith(round_.evidence.name)


def test_preflight_refuses_an_unreachable_or_unhealthy_public_api(round_):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic unreachable public API")

    with pytest.raises(validation.PreflightFailed, match="not reachable"):
        round_.preflight(client=httpx.Client(transport=httpx.MockTransport(refuse)))
    down = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"detail": "synthetic maintenance"})
    )
    with pytest.raises(validation.PreflightFailed, match="health probe failed"):
        round_.preflight(client=httpx.Client(transport=down))


def test_preflight_refuses_a_ledger_that_is_not_at_the_documented_baseline(round_):
    resolution = resolve_real_runtime_authorization(round_.environment, private_root=round_.root)
    ledger = Dec005BudgetLedger(
        resolution.ledger_path,
        scope_sha256=resolution.scope_sha256,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    ledger.reserve_external(kind="llm", request_hash=request_hash(1), ceiling=Decimal("0.25"))
    with pytest.raises(validation.PreflightFailed, match="do not delete, replace or reset"):
        round_.preflight()


def test_preflight_refuses_a_ledger_of_a_different_scope(tmp_path, round_):
    other = tmp_path / "other" / "dec007-budget.sqlite3"
    seed_baseline_ledger(other, scope_sha256="c" * 64)
    environment = {**round_.environment, "DEC007_LEDGER_PATH": str(other)}
    with pytest.raises(validation.PreflightFailed, match="different authorization scope"):
        round_.preflight(environment=environment)


def test_preflight_refuses_a_foreign_authorization_identity_or_missing_credentials(round_):
    with pytest.raises(validation.PreflightFailed, match="DEC-007 authorization"):
        round_.preflight(
            environment={**round_.environment, "DEC007_AUTHORIZATION_ID": "DEC-005-2026-10-15"}
        )
    without_key = {
        key: value for key, value in round_.environment.items() if key != "DASHSCOPE_API_KEY"
    }
    with pytest.raises(validation.PreflightFailed, match="DASHSCOPE_API_KEY"):
        round_.preflight(environment=without_key)


def test_a_refused_preflight_touches_no_supplier_and_no_probe(round_):
    recorder = ProbeRecorder()
    with pytest.raises(validation.PreflightFailed):
        validation.run_preflight(
            **{
                **round_.arguments(),
                "publication_id": "pub-other",
                "client": recorder.client(),
            }
        )
    assert recorder.requests == []  # a local refusal never even probes the public API


# ----------------------------------------------------------------- isolated serving assembly
def test_serving_assembly_binds_the_round_ceilings_and_refuses_to_build_the_index(
    round_, monkeypatch
):
    approve_synthetic_document(round_.environment)  # the documented step 2, before serving
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
        **{
            **round_.serving_arguments(),
            "transport": httpx.MockTransport(lambda request: httpx.Response(200, json={})),
            "client": ProbeRecorder().client(),
        }
    )
    budget = captured["budget"]
    assert (budget.llm_limit, budget.embedding_limit, budget.total_cny) == (
        4,
        322,
        Decimal("2"),
    )
    assert captured["allow_build"] is False  # serving never builds the index
    assert captured["private_root"] == round_.root
    assert app.state.external_budget is budget
    assert app.state.deploy_review_mode == "task0027-validation"
    assert app.state.authorization_id == FULL_CAPABILITY_AUTHORIZATION_ID
    assert outcome.report.llm_limit == 4 and outcome.report.embedding_limit == 322
    assert outcome.report.approved_documents == {"count": 1, "sha256": [APPROVED_DOCUMENT]}
    # The engine receives the live document source: a revocation applies without a restart.
    assert callable(captured["engine"]["allowed_document_sha256"])


def test_validation_entry_exits_non_zero_when_a_precondition_fails(round_, monkeypatch, capsys):
    cli_deployment(round_, monkeypatch)
    # A public API that cannot be reached stops the round instead of serving (or calling);
    # this call uses the real client, so the host name really is unresolvable.
    assert (
        validation.main(
            [*cli_arguments(round_), "--online-api-url", "http://synthetic.invalid"]
        )
        == 2
    )
    assert "not reachable" in capsys.readouterr().err
    # Any failed precondition exits non-zero without serving: the evidence file is gone, so
    # no app is ever started by this call (the evidence check precedes the health probe).
    monkeypatch.setenv("DEC007_HOST_OFFLINE_EVIDENCE", str(round_.root / "gone.json"))
    assert validation.main(cli_arguments(round_)) == 2
    assert "STOP" in capsys.readouterr().err


def test_validation_entry_reads_the_authorization_identity_registry_and_ledger_from_the_environment(
    round_, monkeypatch
):
    # The mapping given to the assembly decides; an unrelated process variable is ignored.
    monkeypatch.setenv("DEC007_LEDGER_PATH", str(round_.root / "decoy.sqlite3"))
    outcome = round_.preflight()
    resolution = outcome.resolution
    assert resolution.authorization_id == FULL_CAPABILITY_AUTHORIZATION_ID
    assert resolution.ledger_path == Path(round_.environment["DEC007_LEDGER_PATH"])
    assert resolution.registry_path == Path(round_.environment["DEC007_AUTHORIZATION_REGISTRY"])
    assert outcome.report.registry_path == round_.environment["DEC007_AUTHORIZATION_REGISTRY"]
    assert outcome.report.ledger_path == round_.environment["DEC007_LEDGER_PATH"]
