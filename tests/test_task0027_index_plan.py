"""The read-only index plan: build identity, snapshot delta and cache reuse.

``scripts/task0027_index_plan.py`` answers two operator questions without touching the volume,
the ledger or a supplier: which build id this frozen corpus produces for a given
publication/revision (which is how the recorded phase-one build id is verified), and what a
new legal snapshot changes per clause (which is what decides whether a rebuild is served
entirely from the durable vector cache or would have to embed new legal text).

Everything is local: the synthetic corpora live in ``tmp_path``, the transport refuses every
request in-process, and the one test over the real corpus only ingests it.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
import task0027_index_plan as plan

from bidding_compliance.legal.contracts import LegalIndex, LegalManifest, LegalVersion
from bidding_compliance.legal.corpus import digest, ingest
from bidding_compliance.legal.vector_index import SQLiteVectorIndex
from bidding_compliance.model_gateway.authorized_runtime import Dec005BudgetLedger
from bidding_compliance.services.real_embedding_runtime import ScopedEmbeddingGuard

PUBLICATION = "977826ab-948a-4681-9001-4866c7da3bc2"
REVISION = "fa2407bb-1dff-4da8-b828-bcc846df76ad"
# The recorded phase-one identity of the deployed round: the frozen corpus snapshot, the
# publication/revision and the build id the prebuild wrote into the modelstate volume.
RECORDED_SNAPSHOT = "69d340d65f5e9114c8a2e76f8b3b524b67f47d0cbc0088c4e01d80b7db8729fd"
RECORDED_BUILD_ID = "c7344cac5f45933fb7408701cb63ab2095206600aca952dcf4457130c85865d2"
RECORDED_ONLINE_IDENTITY = "8b05650d7f2d1bd4d089459f957bdd49b6340ddcda388719952e465fae16a723"
ARTICLES = ("第一条", "第二条", "第三条")


def synthetic_corpus(
    root: Path,
    *,
    clauses: int = 3,
    verified_through: str = "2026-10-14",
    suffix: str = "",
) -> LegalIndex:
    """A frozen snapshot in ``root``; ``suffix`` changes every clause text on purpose."""
    articles = list(ARTICLES[:clauses])
    root.mkdir(parents=True, exist_ok=True)
    source = root / "synthetic-law.txt"
    source.write_text(
        "合成法规\n"
        + "".join(
            f"{article} 合成采购规则第{number}项{suffix}，仅用于离线索引计划测试。\n"
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
            "verified_through": verified_through,
            "effective_from": "2020-01-01",
            "effective_to": None,
            "end_status": "confirmed_open",
            "jurisdictions": ["CN"],
            "procurement_types": ["government"],
            "project_types": ["works"],
            "authority": "regulation",
            "verification_note": "仅用于离线索引计划测试的合成法规，不是真实法律依据。",
            "expected_articles": articles,
            "applicability": {
                "procurement_methods": ["tender"],
                "buyer_types": ["government_entity"],
                "subject_types": ["works"],
                "legal_frameworks": ["tendering"],
            },
        }
    )
    manifest = root / plan.DEFAULT_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(LegalManifest(versions=(version,)).model_dump_json(), encoding="utf-8")
    return ingest(root, LegalManifest(versions=(version,)))


def test_the_plan_matches_the_sqlite_planned_build_id(tmp_path):
    """The recomputed formula and the durable store's own planning must agree exactly."""
    index = synthetic_corpus(tmp_path)
    provider = plan.embedding_provider()
    recomputed = plan.planned_identity(
        index, provider, publication_id="pub-a", revision_id="rev-a"
    )
    store = SQLiteVectorIndex(tmp_path / "scratch" / "legal-vectors.sqlite3")
    from bidding_compliance.services.real_embedding_runtime import authorized_vector_plan

    settings = provider.settings
    planned = authorized_vector_plan(
        index,
        max_items=provider.max_batch_items,
        max_item_bytes=settings.max_text_utf8_bytes,
        max_batch_bytes=settings.max_batch_utf8_bytes,
    )
    assert store.planned_build_id(
        index,
        provider,
        publication_id="pub-a",
        revision_id="rev-a",
        clause_ids=planned.clause_ids,
    ) == recomputed["build_id"]
    assert recomputed["authorized_clause_count"] == 3


def test_the_planned_identity_is_offline_and_cannot_send_anything(tmp_path):
    index = synthetic_corpus(tmp_path)
    provider = plan.embedding_provider()
    assert provider.execution_mode == "online"
    assert provider.identity.parameters["execution_mode"] == "online"
    # The plan's own guard refuses the reservation before any transport is consulted;
    # the refusing transport behind it is the second, never-reached line of defence.
    with pytest.raises(AssertionError, match="never reserves a supplier request"):
        provider.embed(["合成查询文本"])
    plan.planned_identity(index, provider, publication_id="pub-a", revision_id="rev-a")


def test_a_metadata_only_change_keeps_every_clause_and_reuses_the_cache(tmp_path):
    """The re-verification case: new snapshot hash, identical clause ids and texts."""
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    baseline = synthetic_corpus(baseline_root, verified_through="2026-10-14")
    current = synthetic_corpus(current_root, verified_through="2026-10-16")
    provider = plan.embedding_provider()
    delta = plan.snapshot_delta(baseline, current, provider=provider)
    assert delta["baseline_snapshot_sha256"] != delta["current_snapshot_sha256"]
    assert delta["added_clause_count"] == 0
    assert delta["removed_clause_count"] == 0
    assert delta["changed_text_clause_count"] == 0
    assert delta["planned_cache_miss_clause_count"] == 0
    assert delta["cache_reuse_complete"] is True
    assert delta["estimated_new_embedding_batches"] == 0
    # The build id still changes: it binds the snapshot hash, not only the clauses.
    before = plan.planned_identity(baseline, provider, publication_id="pub-a", revision_id="rev-a")
    after = plan.planned_identity(current, provider, publication_id="pub-a", revision_id="rev-a")
    assert before["build_id"] != after["build_id"]
    assert before["coverage_sha256"] == after["coverage_sha256"]


def test_a_text_change_is_reported_as_new_embedding_batches(tmp_path):
    """A rewrite of any clause text is visible as a cache miss needing a new batch."""
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    baseline = synthetic_corpus(baseline_root)
    current = synthetic_corpus(current_root, suffix="（2026年修订）")
    provider = plan.embedding_provider()
    delta = plan.snapshot_delta(baseline, current, provider=provider)
    # A rewritten clause text is a different clause identity here (ids derive from the text),
    # so it shows up as one removal plus one addition, not as a same-id text change.
    assert delta["changed_text_clause_count"] == 0
    assert delta["removed_clause_count"] == 3 and delta["added_clause_count"] == 3
    assert delta["planned_cache_miss_clause_count"] == 3
    assert delta["cache_reuse_complete"] is False
    assert delta["estimated_new_embedding_batches"] == 1


def test_the_script_reproduces_the_recorded_phase_one_build_id(tmp_path, capsys, monkeypatch):
    """The recorded index identity is recomputable from the frozen corpus, offline.

    This is the check that makes the deployed index identity auditable before any volume is
    read: the frozen corpus (3120 clauses, 3112 paid), the online embedding identity and the
    recorded publication/revision must produce exactly the build id the phase-one prebuild
    wrote. A corpus or identity change breaks it and must be re-measured, not accepted.
    """
    import task0027_index_plan

    monkeypatch.setattr(
        "sys.argv",
        [
            "task0027_index_plan.py",
            "--corpus-root",
            str(plan.ROOT),
            "--manifest",
            plan.DEFAULT_MANIFEST,
            "--publication-id",
            PUBLICATION,
            "--revision-id",
            REVISION,
            "--expect-build-id",
            RECORDED_BUILD_ID,
        ],
    )
    assert task0027_index_plan.main() == 0
    printed = capsys.readouterr().out
    assert RECORDED_BUILD_ID in printed
    assert RECORDED_SNAPSHOT in printed
    assert RECORDED_ONLINE_IDENTITY in printed
    assert "3112/3120" in printed


def test_the_script_refuses_a_different_build_id_without_printing_pass(
    tmp_path, capsys, monkeypatch
):
    import task0027_index_plan

    synthetic_corpus(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "task0027_index_plan.py",
            "--corpus-root",
            str(tmp_path),
            "--publication-id",
            "pub-a",
            "--revision-id",
            "rev-a",
            "--expect-build-id",
            "e" * 64,
        ],
    )
    assert task0027_index_plan.main() == 2
    captured = capsys.readouterr()
    assert "STOP" in captured.err and "not the expected" in captured.err
    assert "PASS" not in captured.out


def test_the_script_requires_publication_and_revision(tmp_path, capsys, monkeypatch):
    import task0027_index_plan

    synthetic_corpus(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "task0027_index_plan.py",
            "--corpus-root",
            str(tmp_path),
            "--publication-id",
            "",
            "--revision-id",
            "rev-a",
        ],
    )
    assert task0027_index_plan.main() == 2
    assert "--publication-id" in capsys.readouterr().err


def test_the_delta_report_is_read_only(tmp_path):
    """Neither the baseline nor the current root gains a file: nothing is built."""
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    baseline = synthetic_corpus(baseline_root)
    current = synthetic_corpus(current_root, verified_through="2026-10-16")

    def tree() -> dict[Path, bytes]:
        return {
            path: path.read_bytes()
            for root in (baseline_root, current_root)
            for path in root.rglob("*")
            if path.is_file()
        }

    before = tree()
    provider = plan.embedding_provider()
    plan.snapshot_delta(baseline, current, provider=provider)
    plan.planned_identity(current, provider, publication_id="pub-a", revision_id="rev-a")
    assert tree() == before
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_the_no_egress_guard_and_transport_refuse_everything(tmp_path):
    synthetic_corpus(tmp_path)
    provider = plan.embedding_provider()
    assert provider.execution_mode == "online"
    with pytest.raises(AssertionError, match="never reserves"):
        plan.embedding_provider()._guard.reserve_external(  # noqa: SLF001 - pins no-egress wiring
            kind="embedding", request_hash="1" * 64, ceiling=Decimal("0.10")
        )
    ledger = Dec005BudgetLedger(tmp_path / "ledger.sqlite3", scope_sha256="0" * 64)
    guard = ScopedEmbeddingGuard(ledger)
    guard.approve(["合成查询文本"])
    assert ledger.summary()["embedding_batches"] == 0  # planning never reserves


def test_the_plan_json_is_machine_readable(tmp_path, capsys, monkeypatch):
    import task0027_index_plan

    synthetic_corpus(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "task0027_index_plan.py",
            "--corpus-root",
            str(tmp_path),
            "--publication-id",
            "pub-a",
            "--revision-id",
            "rev-a",
            "--json",
        ],
    )
    assert task0027_index_plan.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["current"]["publication_id"] == "pub-a"
    assert payload["current"]["revision_id"] == "rev-a"
    assert payload["current"]["embedding_execution_mode"] == "online"
    assert len(payload["current"]["build_id"]) == 64
    assert len(payload["current"]["coverage_sha256"]) == 64
    assert payload["current"]["planned_batch_count"] == 1
