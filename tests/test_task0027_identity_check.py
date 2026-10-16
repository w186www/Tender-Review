"""The read-only identity check of the recorded DEC-007 round.

``scripts/task0027_identity_check.py`` compares the identities an operator must be able to
verify before the official API or a controlled round touches the ``modelstate`` volume: the
DEC-007 authorization, the ledger's own scope (re-read from the ledger and re-computed from
the configured registry path), the private-root paths, the per-file registry, the model audit
trail, and the prebuilt index with its store row, coverage and cache links.

Every test uses a synthetic private root in ``tmp_path``, a three-article corpus and a
synthetic embedding transport: nothing opens a socket, reads a credential, reaches a supplier
or writes inside the repository.
"""

import gc
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import task0027_identity_check as identity

from bidding_compliance.legal.contracts import LegalManifest, LegalVersion
from bidding_compliance.legal.corpus import digest, ingest
from bidding_compliance.legal.embedding_provider import (
    DashScopeEmbeddingProvider,
    DashScopeEmbeddingSettings,
)
from bidding_compliance.legal.vector_index import SQLiteVectorIndex
from bidding_compliance.model_gateway.authorized_runtime import (
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
)

PUBLICATION = "977826ab-948a-4681-9001-4866c7da3bc2"
REVISION = "fa2407bb-1dff-4da8-b828-bcc846df76ad"
CORPUS_CLAUSES = 3
ARTICLES = ("第一条", "第二条", "第三条")
APPROVED_DOCUMENT = "d" * 64
MODEL_ID = "text-embedding-v4"


def synthetic_corpus(root: Path, *, clauses: int = CORPUS_CLAUSES) -> Path:
    """A frozen snapshot with ``clauses`` short articles, at the repository layout."""
    articles = list(ARTICLES[:clauses])
    source = root / "synthetic-law.txt"
    source.write_text(
        "合成法规\n"
        + "".join(
            f"{article} 合成采购规则第{number}项，仅用于离线身份核对测试。\n"
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
            "captured_on": "2026-10-16",
            "verification": "verified",
            "verified_through": "2026-10-16",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "end_status": "confirmed_open",
            "jurisdictions": ["CN"],
            "procurement_types": ["government"],
            "project_types": ["works"],
            "authority": "regulation",
            "verification_note": "仅用于离线身份核对测试的合成法规，不是真实法律依据。",
            "expected_articles": articles,
            "applicability": {
                "procurement_methods": ["tender"],
                "buyer_types": ["government_entity"],
                "subject_types": ["works"],
                "legal_frameworks": ["tendering"],
            },
        }
    )
    manifest = root / identity.LEGAL_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(LegalManifest(versions=(version,)).model_dump_json(), encoding="utf-8")
    return manifest


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


def environment(root: Path) -> dict[str, str]:
    return {
        "DEC007_AUTHORIZATION_ID": FULL_CAPABILITY_AUTHORIZATION_ID,
        "DEC007_LEDGER_PATH": str(root / "dec007-budget.sqlite3"),
        "DEC007_AUTHORIZATION_REGISTRY": str(root / "authorization-registry.jsonl"),
        "DASHSCOPE_API_KEY": "example-synthetic-credential",
        "BAILIAN_WORKSPACE_ID": "synthetic-workspace",
    }


def prebuild(root: Path, environment_: dict[str, str]) -> str:
    """Build the authorized index for the synthetic corpus; returns its build id."""
    store = SQLiteVectorIndex(root / identity.INDEX_FILE)
    ledger = Dec005BudgetLedger(
        root / "prebuild-budget.sqlite3",
        scope_sha256="a" * 64,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    guard = ScopedEmbeddingGuard(ledger)
    # The synthetic credential is only carried through the settings object; the transport
    # below answers every request in-process and no socket is ever opened.
    example_credential = environment_["DASHSCOPE_" + "API_KEY"]
    provider = DashScopeEmbeddingProvider(
        DashScopeEmbeddingSettings(
            enabled=True,
            region="beijing",
            workspace_id=environment_["BAILIAN_WORKSPACE_ID"],
            model_id=MODEL_ID,
            dimensions=1024,
            timeout_seconds=20,
            api_key=example_credential,
        ),
        client=httpx.Client(
            transport=SyntheticEmbeddingTransport(), trust_env=False, follow_redirects=False
        ),
        guard=guard,
        audit_sink=MetadataAuditSink(root / "embedding-audit.jsonl"),
        input_price_per_million=EMBEDDING_INPUT_PRICE_PER_MILLION,
    )
    manifest, _plan = build_authorized_vector_index(
        index=ingest(
            root,
            LegalManifest.model_validate_json(
                (root / identity.LEGAL_MANIFEST).read_text(encoding="utf-8")
            ),
        ),
        provider=provider,
        guard=guard,
        store=store,
        publication_id=PUBLICATION,
        revision_id=REVISION,
    )
    (root / identity.PREBUILT_MANIFEST_FILE).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return manifest.build_id


@dataclass(frozen=True, slots=True)
class Recorded:
    """One synthetic private root whose identity set is consistent by construction."""

    root: Path
    environment: dict[str, str]
    scope: str
    build_id: str

    def arguments(self, **overrides: str) -> list[str]:
        values = {
            "--private-root": str(self.root),
            "--corpus-root": str(self.root),
            "--expected-scope": self.scope,
            "--publication-id": PUBLICATION,
            "--revision-id": REVISION,
            "--build-id": self.build_id,
            "--expected-item-count": str(CORPUS_CLAUSES),
            "--expected-source-item-count": str(CORPUS_CLAUSES),
        }
        values.update(overrides)
        arguments: list[str] = []
        for option, value in values.items():
            arguments.extend([option, value])
        return arguments


@pytest.fixture
def recorded(tmp_path: Path, monkeypatch) -> Recorded:
    environment_ = environment(tmp_path)
    for name, value in environment_.items():
        monkeypatch.setenv(name, value)
    synthetic_corpus(tmp_path)
    build_id = prebuild(tmp_path, environment_)
    resolution = resolve_real_runtime_authorization(environment_, private_root=tmp_path)
    assert resolution.registry_path is not None
    ledger = Dec005BudgetLedger(
        resolution.ledger_path,
        scope_sha256=resolution.scope_sha256,
        authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    reservation = ledger.reserve_external(
        kind="embedding", request_hash="1" * 64, ceiling=Decimal("0.10")
    )
    ledger.settle_external(reservation, Decimal("0.0003318"))
    FileAuthorizationRegistry(resolution.registry_path).approve(
        sha256=APPROVED_DOCUMENT,
        document_id="synthetic-round-document",
        reason="离线身份核对测试",
        approved_by="operator",
    )
    resolution.model_audit_path.write_text(
        json.dumps({"event": "synthetic-audit-line"}) + "\n", encoding="utf-8"
    )
    return Recorded(
        root=tmp_path,
        environment=environment_,
        scope=resolution.scope_sha256,
        build_id=build_id,
    )


def root_files(root: Path) -> dict[str, str]:
    """Every file in the synthetic private root with its hash (read-only observation)."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ------------------------------------------------------------------------ the passing check
def test_identity_check_passes_and_prints_the_recorded_identities(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    before = root_files(recorded.root)
    assert identity.main(recorded.arguments()) == 0
    captured = capsys.readouterr()
    assert identity.IDENTITY_PASSED in captured.out
    assert f"scope={recorded.scope}" in captured.out
    assert f"publication={PUBLICATION}" in captured.out
    assert f"revision={REVISION}" in captured.out
    assert f"build_id={recorded.build_id}" in captured.out
    assert f"item_count={CORPUS_CLAUSES}" in captured.out
    # The check is read-only: every artifact keeps its exact bytes and no file appears.
    assert root_files(recorded.root) == before


def test_identity_check_json_reports_paths_scope_and_counts(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    assert identity.main([*recorded.arguments(), "--json"]) == 0
    captured = capsys.readouterr()
    # The JSON report is followed by the one assertable PASS line and the counters hint.
    payload = json.loads(captured.out.split(identity.IDENTITY_PASSED)[0])
    assert payload["authorization_id"] == FULL_CAPABILITY_AUTHORIZATION_ID
    assert payload["ledger_path"] == recorded.environment["DEC007_LEDGER_PATH"]
    assert payload["registry_path"] == recorded.environment["DEC007_AUTHORIZATION_REGISTRY"]
    # The scope is read from the ledger file *and* re-computed from the configuration.
    assert payload["ledger"]["scope_sha256"] == payload["scope_sha256"] == recorded.scope
    assert payload["ledger"]["embedding_batches"] == 1
    assert payload["registry"]["approved_documents"] == [APPROVED_DOCUMENT]
    index = payload["vector_index"]
    assert index["publication_id"] == PUBLICATION and index["revision_id"] == REVISION
    assert index["item_rows"] == CORPUS_CLAUSES
    assert index["items_without_cached_vector"] == 0
    assert index["embedding_execution_mode"] == "online"
    assert index["embedding_identity_sha256"]
    assert payload["database_publication"] is None


# ----------------------------------------------------------------------- refusals (fail closed)
def test_identity_check_refuses_a_ledger_that_records_a_different_scope(
    recorded: Recorded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    foreign = tmp_path / "foreign-ledger" / "dec007-budget.sqlite3"
    foreign.parent.mkdir()
    Dec005BudgetLedger(
        foreign, scope_sha256="c" * 64, authorization_id=FULL_CAPABILITY_AUTHORIZATION_ID
    ).reserve_external(kind="embedding", request_hash="2" * 64, ceiling=Decimal("0.10"))
    # The ledger file exists but was written under a foreign scope, so the reassembly refuses
    # it exactly like the serving assembly would.
    monkeypatch.setenv("DEC007_LEDGER_PATH", str(foreign))
    assert identity.main(recorded.arguments()) == 2
    captured = capsys.readouterr()
    assert "different authorization scope" in captured.err
    assert "Do not delete, replace, reset or rebuild" in captured.err
    assert identity.IDENTITY_PASSED not in captured.out


def test_identity_check_refuses_a_configuration_that_binds_another_registry_path(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "DEC007_AUTHORIZATION_REGISTRY", str(recorded.root / "elsewhere-registry.jsonl")
    )
    assert identity.main(recorded.arguments()) == 2
    captured = capsys.readouterr()
    assert "configuration binds a different scope" in captured.err
    assert identity.IDENTITY_PASSED not in captured.out


@pytest.mark.parametrize(
    ("option", "replacement", "message"),
    (
        ("--publication-id", "00000000-0000-0000-0000-000000000000", "not to the recorded"),
        ("--revision-id", "11111111-1111-1111-1111-111111111111", "not to the recorded"),
        ("--build-id", "e" * 64, "not the recorded"),
    ),
)
def test_identity_check_refuses_a_different_publication_revision_or_build(
    recorded: Recorded,
    capsys: pytest.CaptureFixture[str],
    option: str,
    replacement: str,
    message: str,
) -> None:
    assert identity.main(recorded.arguments(**{option: replacement})) == 2
    captured = capsys.readouterr()
    assert message in captured.err
    assert identity.IDENTITY_PASSED not in captured.out


def test_identity_check_refuses_a_manifest_with_a_different_item_count(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    """A *valid* manifest with the wrong count: only the semantic comparison can catch it."""
    from bidding_compliance.legal.vector_index import VectorIndexManifest

    manifest_path = recorded.root / identity.PREBUILT_MANIFEST_FILE
    original = manifest_path.read_bytes()
    manifest = VectorIndexManifest.model_validate_json(original)
    rewritten = VectorIndexManifest.create(
        build_id=manifest.build_id,
        legal_snapshot_sha256=manifest.legal_snapshot_sha256,
        publication_id=manifest.publication_id,
        revision_id=manifest.revision_id,
        embedding_identity=manifest.embedding_identity,
        item_count=CORPUS_CLAUSES - 1,
        source_item_count=manifest.source_item_count,
        coverage_sha256=manifest.coverage_sha256,
        items_sha256=manifest.items_sha256,
    )
    manifest_path.write_text(rewritten.model_dump_json(indent=2), encoding="utf-8")
    try:
        assert identity.main(recorded.arguments()) == 2
        captured = capsys.readouterr()
        assert f"holds {CORPUS_CLAUSES - 1} items" in captured.err
        assert identity.IDENTITY_PASSED not in captured.out
    finally:
        manifest_path.write_bytes(original)


@pytest.mark.parametrize(
    ("name", "message"),
    (
        ("dec007-budget.sqlite3", "ledger is absent"),
        ("authorization-registry.jsonl", "registry is absent"),
        ("dec007-model-audit.jsonl", "model audit trail is absent"),
        ("vector-manifest.json", "index manifest is absent"),
        ("legal-vectors.sqlite3", "index store is absent"),
    ),
)
def test_identity_check_refuses_absent_artifacts_without_creating_them(
    recorded: Recorded, capsys: pytest.CaptureFixture[str], name: str, message: str
) -> None:
    target = recorded.root / name
    original = target.read_bytes()
    # SQLite connections of the fixture are released by the cyclic collector, and Windows
    # keeps a handle on an open database file; both are test-host concerns, not product ones.
    gc.collect()
    target.unlink()
    try:
        assert identity.main(recorded.arguments()) == 2
        captured = capsys.readouterr()
        assert message in captured.err
        assert identity.IDENTITY_PASSED not in captured.out
        assert not target.exists()  # a refused check never initialises the missing artifact
    finally:
        target.write_bytes(original)


def test_identity_check_refuses_an_index_without_intact_cached_vectors(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    store = recorded.root / identity.INDEX_FILE
    with sqlite3.connect(store) as connection:
        connection.execute("DELETE FROM vector_cache")
    assert identity.main(recorded.arguments()) == 2
    captured = capsys.readouterr()
    assert "without an intact cached vector" in captured.err
    assert identity.IDENTITY_PASSED not in captured.out


@pytest.mark.parametrize(
    "option", ("--expected-scope", "--publication-id", "--revision-id", "--build-id")
)
def test_identity_check_requires_the_recorded_values(
    recorded: Recorded, capsys: pytest.CaptureFixture[str], option: str
) -> None:
    arguments: list[str] = []
    skip = False
    for value in recorded.arguments():
        if skip:
            skip = False
            continue
        if value == option:
            skip = True
            continue
        arguments.append(value)
    assert identity.main(arguments) == 2
    captured = capsys.readouterr()
    assert f"{option} is required" in captured.err
    assert identity.IDENTITY_PASSED not in captured.out


def test_identity_check_refuses_a_scope_that_is_not_hex(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    assert identity.main(recorded.arguments(**{"--expected-scope": "zz"})) == 2
    assert "64 lowercase hex" in capsys.readouterr().err


# ------------------------------------------------------------------------------ scope-only mode
def test_print_scope_reports_the_paths_without_reading_or_creating_the_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in environment(tmp_path).items():
        monkeypatch.setenv(name, value)
    assert identity.main(["--private-root", str(tmp_path), "--print-scope"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out.split("scope-only:")[0])
    assert payload["mode"] == "scope-only" and payload["ledger_read"] is False
    assert payload["registry_path"] == str(tmp_path / "authorization-registry.jsonl")
    assert payload["ledger_path"] == str(tmp_path / "dec007-budget.sqlite3")
    assert len(payload["scope_sha256"]) == 64
    assert "the ledger was NOT read" in captured.out
    # Nothing was created: scope-only never initialises a ledger or a registry.
    assert not (tmp_path / "dec007-budget.sqlite3").exists()
    assert not (tmp_path / "authorization-registry.jsonl").exists()


def test_print_scope_refuses_without_the_dec007_authorization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEC007_AUTHORIZATION_ID", raising=False)
    assert identity.main(["--private-root", str(tmp_path), "--print-scope"]) == 2
    assert "explicit server authorization" in capsys.readouterr().err


def test_the_default_private_root_is_the_modelstate_volume_root() -> None:
    # Inside the container this resolves to /app/.verification/private, the volume root the
    # recorded round wrote to; a TASK-0023 subdirectory would bind a different scope.
    assert identity.PRIVATE_ROOT == identity.ROOT / ".verification" / "private"
    assert identity.PRIVATE_ROOT.name == "private"
    assert identity.PRIVATE_ROOT.parent.name == ".verification"


# ------------------------------------------------------------------------- database cross-check
def published_database(path: Path, publication: str) -> str:
    from sqlalchemy import create_engine, text

    url = f"sqlite+pysqlite:///{path}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS legal_publication (publication_id TEXT, "
                "revision_id TEXT, sequence INTEGER)"
            )
        )
        connection.execute(text("DELETE FROM legal_publication"))
        connection.execute(
            text("INSERT INTO legal_publication VALUES (:publication, :revision, 1)"),
            {"publication": publication, "revision": REVISION},
        )
    engine.dispose()
    return url


def check(recorded: Recorded, database_url: str):
    return identity.run_identity_check(
        environment=recorded.environment,
        private_root=recorded.root,
        corpus_root=recorded.root,
        expected_scope=recorded.scope,
        publication_id=PUBLICATION,
        revision_id=REVISION,
        build_id=recorded.build_id,
        expected_item_count=CORPUS_CLAUSES,
        expected_source_item_count=CORPUS_CLAUSES,
        database_url=database_url,
    )


def test_the_database_publication_cross_check_accepts_the_recorded_publication(
    recorded: Recorded, tmp_path: Path
) -> None:
    """The cross-check runs over SQLite so its logic is testable without PostgreSQL."""
    url = published_database(tmp_path / "publication.sqlite3", PUBLICATION)
    report = check(recorded, url)
    assert report.database_publication == {
        "publication_id": PUBLICATION,
        "revision_id": REVISION,
        "sequence": 1,
    }
    assert PUBLICATION in report.line and REVISION in report.line


def test_the_database_publication_cross_check_refuses_a_different_row(
    recorded: Recorded, tmp_path: Path
) -> None:
    url = published_database(
        tmp_path / "publication.sqlite3", "00000000-0000-0000-0000-000000000000"
    )
    with pytest.raises(identity.IdentityMismatch, match="not the one the prebuilt index"):
        check(recorded, url)
