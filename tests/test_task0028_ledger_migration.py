"""TASK-0028 U05 historical ledger/registry import: idempotent, reconciled, fail-closed."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_identity_projects import sign_in
from test_identity_projects import system as shared_system
from test_ingestion import upload

from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import (
    Document,
    DocumentExternalAuthorization,
    LedgerImport,
    ModelBudgetAccount,
    ModelBudgetReservation,
)
from bidding_compliance.services import ledger_migration
from bidding_compliance.services.execution_authorization import set_execution_policy
from bidding_compliance.services.ledger_migration import (
    LedgerMigrationError,
    migrate_historical_ledgers,
)

system = shared_system
AUTH_ID = "product:test"


def seed_policy(engine, *, budget: str = "10") -> None:
    with Session(engine) as session:
        set_tenant(session, "a")
        set_execution_policy(
            session,
            tenant_id="a",
            actor_id="admin",
            allowed_providers=["bailian"],
            allowed_purposes=["external_review"],
            budget_cny=Decimal(budget),
            max_call_cny=Decimal("0.25"),
            max_embedding_batch_cny=Decimal("0.10"),
            max_authorization_ttl_seconds=3600,
            budget_authorization_id=AUTH_ID,
        )


def source_ledger(path, rows) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS authorization "
            "(id TEXT PRIMARY KEY, scope_sha256 TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, "
            "kind TEXT NOT NULL, request_hash TEXT NOT NULL, ceiling TEXT NOT NULL, "
            "charge TEXT NOT NULL, status TEXT NOT NULL, "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "authorization_id TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO authorization VALUES (?, ?)",
            ("DEC-SYNTHETIC", "a" * 64),
        )
        for row in rows:
            connection.execute(
                "INSERT INTO requests(id,kind,request_hash,ceiling,charge,status,authorization_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    row["id"],
                    row.get("kind", "llm"),
                    row.get("request_hash", "b" * 64),
                    row["ceiling"],
                    row.get("charge", row["ceiling"]),
                    row["status"],
                    row.get("authorization_id", "DEC-SYNTHETIC"),
                ),
            )
        connection.commit()


def prepare_document(system):
    client, engine, _, _ = system
    headers = sign_in(system)
    project, uploaded = upload(system, headers=headers)
    document = uploaded.json()
    with Session(engine) as session:
        set_tenant(session, "a")
        row = session.get(Document, ("a", document["document_id"]))
        row.parse_version = 1
        row.status = "ready"
        session.commit()
    return project, document


def registry_file(path, records) -> None:
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def test_dry_run_and_real_import_preserve_ids_costs_and_unknown(system, tmp_path):
    _, engine, _, _ = system
    seed_policy(engine)
    _, document = prepare_document(system)
    now = datetime.now(UTC).replace(microsecond=0)
    ledger = tmp_path / "dec-synthetic.sqlite3"
    source_ledger(
        ledger,
        [
            {
                "id": "req-settled-llm",
                "kind": "llm",
                "ceiling": "0.25",
                "charge": "0.010",
                "status": "settled",
            },
            {
                "id": "req-settled-embed",
                "kind": "embedding",
                "ceiling": "0.10",
                "charge": "0.050",
                "status": "settled",
            },
            {
                "id": "req-reserved",
                "kind": "llm",
                "ceiling": "0.25",
                "charge": "0.25",
                "status": "reserved",
            },
            {
                "id": "req-unknown",
                "kind": "embedding",
                "ceiling": "0.10",
                "charge": "0.10",
                "status": "unknown",
            },
        ],
    )
    registry = tmp_path / "registry.jsonl"
    registry_file(
        registry,
        [
            {
                "action": "approve",
                "sha256": document["sha256"],
                "document_id": document["document_id"],
                "reason": "历史合成授权",
                "approved_at": (now - timedelta(minutes=10)).isoformat(),
                "approved_by": "reviewer",
            },
            {
                "action": "revoke",
                "sha256": document["sha256"],
                "document_id": document["document_id"],
                "reason": "历史合成撤销",
                "approved_at": (now - timedelta(minutes=5)).isoformat(),
                "approved_by": "reviewer",
            },
        ],
    )
    source_before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    with Session(engine) as session:
        report = migrate_historical_ledgers(
            session,
            tenant_id="a",
            authorization_id=AUTH_ID,
            ledger_path=ledger,
            registry_path=registry,
            actor_id="admin",
            purpose="external_review",
            provider="bailian",
            dry_run=True,
        )
        assert report["dry_run"] is True
        assert report["source_counts"]["settled"] == 2
        assert report["source_counts"]["unknown"] == 2
        assert Decimal(report["source_sums"]["charged_cny"]) == Decimal("0.41")
        assert report["registry_counts"] == {"approved": 1, "revoked": 1, "existing": 0}
        assert not report["exceptions"]
    with Session(engine) as session:
        set_tenant(session, "a")
        assert session.scalar(select(func.count()).select_from(ModelBudgetReservation)) == 0
        assert session.scalar(select(func.count()).select_from(LedgerImport)) == 0
        account = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        assert Decimal(account.spent_cny) == Decimal("0")

    with Session(engine) as session:
        report = migrate_historical_ledgers(
            session,
            tenant_id="a",
            authorization_id=AUTH_ID,
            ledger_path=ledger,
            registry_path=registry,
            actor_id="admin",
            purpose="external_review",
            provider="bailian",
            dry_run=False,
        )
        assert report["dry_run"] is False
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == source_before
    with Session(engine) as session:
        set_tenant(session, "a")
        rows = {row.reservation_id: row for row in session.scalars(select(ModelBudgetReservation))}
        assert set(rows) == {"req-settled-llm", "req-settled-embed", "req-reserved", "req-unknown"}
        assert rows["req-settled-llm"].status == "settled"
        assert Decimal(rows["req-settled-llm"].charge_cny) == Decimal("0.010")
        assert rows["req-reserved"].status == "unknown"
        assert Decimal(rows["req-reserved"].charge_cny) == Decimal("0.25")
        assert rows["req-unknown"].status == "unknown"
        account = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        assert Decimal(account.spent_cny) == Decimal("0.41")
        assert Decimal(account.reserved_cny) == Decimal("0")
        imported = session.scalar(select(LedgerImport))
        assert imported is not None
        assert imported.source_ledger_sha256 == source_before
        assert imported.source_registry_sha256 == hashlib.sha256(registry.read_bytes()).hexdigest()
        assert imported.imported_counts["registry_approved"] == 1
        assert imported.imported_counts["registry_revoked"] == 1
        authorization = session.scalar(select(DocumentExternalAuthorization))
        assert authorization is not None
        assert authorization.state == "revoked"
        assert authorization.source == "jsonl_registry"
        assert authorization.source_record_id

        rerun = migrate_historical_ledgers(
            session,
            tenant_id="a",
            authorization_id=AUTH_ID,
            ledger_path=ledger,
            registry_path=registry,
            actor_id="admin",
            purpose="external_review",
            provider="bailian",
            dry_run=False,
        )
        assert rerun["already_imported"] is True
    with Session(engine) as session:
        set_tenant(session, "a")
        assert session.scalar(select(func.count()).select_from(ModelBudgetReservation)) == 4
        account = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        assert Decimal(account.spent_cny) == Decimal("0.41")
        assert session.scalar(select(func.count()).select_from(LedgerImport)) == 1


def test_malformed_source_aborts_without_partial_history(system, tmp_path):
    _, engine, _, _ = system
    seed_policy(engine)
    ledger = tmp_path / "broken.sqlite3"
    source_ledger(
        ledger,
        [
            {"id": "req-good", "ceiling": "0.10", "charge": "0.01", "status": "settled"},
            {"id": "req-bad", "ceiling": "0.10", "charge": "0.01", "status": "mystery"},
        ],
    )
    with Session(engine) as session:
        with pytest.raises(LedgerMigrationError) as exc:
            migrate_historical_ledgers(
                session,
                tenant_id="a",
                authorization_id=AUTH_ID,
                ledger_path=ledger,
                registry_path=None,
                actor_id="admin",
                purpose="external_review",
                provider="bailian",
            )
        assert exc.value.exceptions[0]["code"] == "UNKNOWN_STATUS"
    with Session(engine) as session:
        set_tenant(session, "a")
        assert session.scalar(select(func.count()).select_from(ModelBudgetReservation)) == 0
        account = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        assert Decimal(account.spent_cny) == Decimal("0")
        assert session.scalar(select(func.count()).select_from(LedgerImport)) == 0


def test_interrupted_import_rolls_back_and_can_be_retried(system, tmp_path, monkeypatch):
    _, engine, _, _ = system
    seed_policy(engine)
    _, document = prepare_document(system)
    ledger = tmp_path / "retry.sqlite3"
    source_ledger(
        ledger,
        [{"id": "req-retry", "ceiling": "0.10", "charge": "0.05", "status": "settled"}],
    )
    registry = tmp_path / "retry-registry.jsonl"
    now = datetime.now(UTC).replace(microsecond=0)
    registry_file(
        registry,
        [
            {
                "action": "approve",
                "sha256": document["sha256"],
                "document_id": document["document_id"],
                "reason": "中断重试授权",
                "approved_at": now.isoformat(),
                "approved_by": "reviewer",
            }
        ],
    )
    original = ledger_migration._import_registry_rows

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(ledger_migration, "_import_registry_rows", fail)
    with Session(engine) as session:
        with pytest.raises(RuntimeError):
            migrate_historical_ledgers(
                session,
                tenant_id="a",
                authorization_id=AUTH_ID,
                ledger_path=ledger,
                registry_path=registry,
                actor_id="admin",
                purpose="external_review",
                provider="bailian",
            )
        session.rollback()
    with Session(engine) as session:
        set_tenant(session, "a")
        assert session.scalar(select(func.count()).select_from(ModelBudgetReservation)) == 0
        account = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        assert Decimal(account.spent_cny) == Decimal("0")
    monkeypatch.setattr(ledger_migration, "_import_registry_rows", original)
    with Session(engine) as session:
        report = migrate_historical_ledgers(
            session,
            tenant_id="a",
            authorization_id=AUTH_ID,
            ledger_path=ledger,
            registry_path=registry,
            actor_id="admin",
            purpose="external_review",
            provider="bailian",
        )
        assert report["imported_counts"]["settled"] == 1
        assert report["imported_counts"]["registry_approved"] == 1
    with Session(engine) as session:
        set_tenant(session, "a")
        assert session.scalar(select(func.count()).select_from(ModelBudgetReservation)) == 1
        account = session.get(ModelBudgetAccount, ("a", AUTH_ID))
        assert Decimal(account.spent_cny) == Decimal("0.05")


def test_registry_revoke_without_a_prior_approve_is_preserved_as_a_deny(system, tmp_path):
    _, engine, _, _ = system
    seed_policy(engine)
    _, document = prepare_document(system)
    now = datetime.now(UTC).replace(microsecond=0)
    ledger = tmp_path / "empty.sqlite3"
    source_ledger(ledger, [])
    registry = tmp_path / "revoke-only.jsonl"
    registry_file(
        registry,
        [
            {
                "action": "revoke",
                "sha256": document["sha256"],
                "document_id": document["document_id"],
                "reason": "仅撤销记录",
                "approved_at": now.isoformat(),
                "approved_by": "reviewer",
            }
        ],
    )
    with Session(engine) as session:
        report = migrate_historical_ledgers(
            session,
            tenant_id="a",
            authorization_id=AUTH_ID,
            ledger_path=ledger,
            registry_path=registry,
            actor_id="admin",
            purpose="external_review",
            provider="bailian",
        )
        assert report["registry_counts"]["revoked"] == 1
    with Session(engine) as session:
        set_tenant(session, "a")
        row = session.scalar(select(DocumentExternalAuthorization))
        assert row is not None
        assert row.state == "revoked"
        assert row.revoked_by == "reviewer"
        assert row.revocation_reason == "仅撤销记录"
