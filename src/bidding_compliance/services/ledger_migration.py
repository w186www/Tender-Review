"""Read-only, idempotent import of historical JSONL/SQLite authorizations and spend.

The source ledger/registry is never modified. The whole import is one destination
transaction: a malformed or unmappable record aborts it, so no partial history is written.
Re-running the same source is a no-op; a changed source whose row identities conflict is an
error, never a silent overwrite. Reserved/unknown historical spend is charged at its
ceiling and is never released or reset.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bidding_compliance.persistence.database import set_tenant
from bidding_compliance.persistence.models import (
    Document,
    DocumentExternalAuthorization,
    LedgerImport,
    ModelBudgetAccount,
    ModelBudgetReservation,
    User,
)
from bidding_compliance.services.execution_authorization import require_execution_policy
from bidding_compliance.services.identity import audit

DEFAULT_REGISTRY_AUTHORIZATION_DAYS = 30
LEDGER_TABLE = "requests"
LEDGER_COLUMNS = {
    "id",
    "kind",
    "request_hash",
    "ceiling",
    "charge",
    "status",
    "authorization_id",
}
REGISTRY_FIELDS = {"action", "sha256", "document_id", "reason", "approved_at", "approved_by"}


class LedgerMigrationError(RuntimeError):
    def __init__(self, exceptions: list[dict[str, str]]) -> None:
        super().__init__("historical ledger import aborted")
        self.exceptions = exceptions


@dataclass(frozen=True, slots=True)
class SourceLedger:
    path: Path
    sha256: str
    rows: tuple[dict[str, str], ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decimal(
    value: object, *, field: str, record: str, exceptions: list[dict[str, str]]
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        exceptions.append(
            {"source": "ledger", "record": record, "code": "INVALID_AMOUNT", "detail": field}
        )
        return Decimal(0)
    if not parsed.is_finite() or parsed < 0:
        exceptions.append(
            {"source": "ledger", "record": record, "code": "INVALID_AMOUNT", "detail": field}
        )
        return Decimal(0)
    return parsed


def read_source_ledger(path: Path) -> SourceLedger:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError("the source ledger does not exist")
    digest = _sha256_file(resolved)
    with closing(
        sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    ) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if LEDGER_TABLE not in tables:
            raise ValueError("the source ledger has no requests table")
        columns = {
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({LEDGER_TABLE})"
            ).fetchall()
        }
        missing = LEDGER_COLUMNS - columns
        if missing:
            raise ValueError(f"the source ledger is missing columns: {sorted(missing)}")
        rows = tuple(
            dict(row)
            for row in connection.execute(
                "SELECT id, kind, request_hash, ceiling, charge, status, authorization_id "
                "FROM requests ORDER BY id"
            ).fetchall()
        )
    return SourceLedger(resolved, digest, rows)


def read_registry(path: Path) -> tuple[str, tuple[dict[str, str], ...]]:
    resolved = path.resolve()
    if not resolved.is_file():
        return "", ()
    digest = _sha256_file(resolved)
    rows: list[dict[str, str]] = []
    for number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"registry line {number} is not valid JSON") from exc
        if not isinstance(loaded, dict) or set(loaded) != REGISTRY_FIELDS:
            raise ValueError(f"registry line {number} has unexpected fields")
        rows.append({key: str(value) for key, value in loaded.items()})
    return digest, tuple(rows)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _report_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(report).encode()).hexdigest()


def _parse_time(value: str, record: str, exceptions: list[dict[str, str]]) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        exceptions.append(
            {"source": "registry", "record": record, "code": "INVALID_TIMESTAMP"}
        )
        return datetime(1970, 1, 1, tzinfo=UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _existing_reservation(
    session: Session, tenant_id: str, reservation_id: str
) -> ModelBudgetReservation | None:
    return session.get(
        ModelBudgetReservation,
        (tenant_id, reservation_id),
        populate_existing=True,
    )


def _import_ledger_rows(
    session: Session,
    *,
    tenant_id: str,
    authorization_id: str,
    source: SourceLedger,
    exceptions: list[dict[str, str]],
) -> tuple[dict[str, int], dict[str, str], Decimal]:
    counts = {"llm": 0, "embedding": 0, "settled": 0, "unknown": 0, "existing": 0}
    sums = {"charged_cny": "0"}
    new_spent = Decimal(0)
    seen_authorizations: set[str] = set()
    for row in source.rows:
        record = str(row.get("id", ""))
        if not record or len(record) > 64:
            exceptions.append(
                {"source": "ledger", "record": record, "code": "INVALID_REQUEST_ID"}
            )
            continue
        kind = row.get("kind")
        if kind not in {"llm", "embedding"}:
            exceptions.append(
                {"source": "ledger", "record": record, "code": "UNKNOWN_KIND"}
            )
            continue
        request_hash = str(row.get("request_hash", ""))
        if len(request_hash) != 64 or any(c not in "0123456789abcdef" for c in request_hash):
            exceptions.append(
                {"source": "ledger", "record": record, "code": "INVALID_REQUEST_HASH"}
            )
            continue
        ceiling = _decimal(
            row.get("ceiling"), field="ceiling", record=record, exceptions=exceptions
        )
        charge = _decimal(
            row.get("charge"), field="charge", record=record, exceptions=exceptions
        )
        if ceiling <= 0 or charge > ceiling:
            exceptions.append(
                {"source": "ledger", "record": record, "code": "INVALID_AMOUNT_RELATION"}
            )
            continue
        status = str(row.get("status", ""))
        if status == "settled":
            mapped_status, mapped_charge = "settled", charge
        elif status in {"reserved", "dispatched", "unknown"}:
            # Historical reservations without a recorded outcome are charged at their
            # ceiling. Releasing them would silently restore quota that may already
            # have been spent at the supplier.
            mapped_status, mapped_charge = "unknown", ceiling
        elif status == "released":
            mapped_status, mapped_charge = "released", Decimal(0)
        else:
            exceptions.append(
                {"source": "ledger", "record": record, "code": "UNKNOWN_STATUS"}
            )
            continue
        source_authorization = str(row.get("authorization_id") or "")
        if source_authorization:
            seen_authorizations.add(source_authorization)
        existing = _existing_reservation(session, tenant_id, record)
        if existing is not None:
            if (
                existing.kind != kind
                or existing.request_hash != request_hash
                or Decimal(existing.ceiling_cny) != ceiling
                or existing.status != mapped_status
                or Decimal(existing.charge_cny or 0) != mapped_charge
            ):
                exceptions.append(
                    {"source": "ledger", "record": record, "code": "CONFLICTING_HISTORY"}
                )
                continue
            counts["existing"] += 1
            continue
        session.add(
            ModelBudgetReservation(
                tenant_id=tenant_id,
                reservation_id=record,
                authorization_id=authorization_id,
                review_task_id=None,
                review_run_id=None,
                call_id=None,
                kind=kind,
                request_hash=request_hash,
                ceiling_cny=ceiling,
                charge_cny=mapped_charge,
                status=mapped_status,
                source="ledger_import",
                source_ref=str(source.path),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        counts["llm"] += kind == "llm"
        counts["embedding"] += kind == "embedding"
        counts["settled"] += mapped_status == "settled"
        counts["unknown"] += mapped_status == "unknown"
        new_spent += mapped_charge
    sums["charged_cny"] = str(new_spent)
    sums["source_authorization_ids"] = ",".join(sorted(seen_authorizations))
    return counts, sums, new_spent


def _import_registry_rows(
    session: Session,
    *,
    tenant_id: str,
    purpose: str,
    provider: str,
    records: tuple[dict[str, str], ...],
    authorization_days: int,
    exceptions: list[dict[str, str]],
) -> dict[str, int]:
    counts = {"approved": 0, "revoked": 0, "existing": 0}
    policy = require_execution_policy(session, tenant_id, provider=provider, purpose=purpose)
    ttl = min(
        timedelta(days=authorization_days),
        timedelta(seconds=policy.max_authorization_ttl_seconds),
    )
    for index, record in enumerate(records, 1):
        identity = f"{index}:{record.get('sha256', '')}:{record.get('approved_at', '')}"
        action = record.get("action")
        if action not in {"approve", "revoke"}:
            exceptions.append(
                {"source": "registry", "record": identity, "code": "UNKNOWN_ACTION"}
            )
            continue
        sha256 = record.get("sha256", "")
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            exceptions.append(
                {"source": "registry", "record": identity, "code": "INVALID_SHA256"}
            )
            continue
        document_id = record.get("document_id", "")
        document = session.get(Document, (tenant_id, document_id))
        if document is None or document.sha256 != sha256 or document.parse_version < 1:
            exceptions.append(
                {"source": "registry", "record": identity, "code": "UNRESOLVED_DOCUMENT"}
            )
            continue
        approved_at = _parse_time(record.get("approved_at", ""), identity, exceptions)
        approved_by = record.get("approved_by", "")
        reason = record.get("reason", "")[:500]
        authorization_id = hashlib.sha256(
            f"{tenant_id}:{purpose}:{provider}:{identity}".encode()
        ).hexdigest()[:64]
        existing = session.get(
            DocumentExternalAuthorization,
            (tenant_id, authorization_id),
            populate_existing=True,
        )
        if existing is not None:
            counts["existing"] += 1
            continue
        if action == "approve":
            active = session.scalar(
                select(DocumentExternalAuthorization).where(
                    DocumentExternalAuthorization.tenant_id == tenant_id,
                    DocumentExternalAuthorization.project_id == document.project_id,
                    DocumentExternalAuthorization.document_id == document.document_id,
                    DocumentExternalAuthorization.document_sha256 == sha256,
                    DocumentExternalAuthorization.parse_version == document.parse_version,
                    DocumentExternalAuthorization.purpose == purpose,
                    DocumentExternalAuthorization.provider == provider,
                    DocumentExternalAuthorization.state == "active",
                )
            )
            if active is not None:
                exceptions.append(
                    {"source": "registry", "record": identity, "code": "ACTIVE_CONFLICT"}
                )
                continue
            session.add(
                DocumentExternalAuthorization(
                    tenant_id=tenant_id,
                    authorization_id=authorization_id,
                    project_id=document.project_id,
                    document_id=document.document_id,
                    document_sha256=sha256,
                    parse_version=document.parse_version,
                    purpose=purpose,
                    provider=provider,
                    policy_version=policy.policy_version,
                    state="active",
                    reason=reason or "historical registry import",
                    approved_by=approved_by,
                    approved_at=approved_at,
                    expires_at=approved_at + ttl,
                    revoked_by=None,
                    revoked_at=None,
                    revocation_reason=None,
                    source="jsonl_registry",
                    source_record_id=identity,
                )
            )
            counts["approved"] += 1
        else:
            active = session.scalar(
                select(DocumentExternalAuthorization)
                .where(
                    DocumentExternalAuthorization.tenant_id == tenant_id,
                    DocumentExternalAuthorization.project_id == document.project_id,
                    DocumentExternalAuthorization.document_id == document.document_id,
                    DocumentExternalAuthorization.document_sha256 == sha256,
                    DocumentExternalAuthorization.parse_version == document.parse_version,
                    DocumentExternalAuthorization.purpose == purpose,
                    DocumentExternalAuthorization.provider == provider,
                    DocumentExternalAuthorization.state == "active",
                )
                .order_by(DocumentExternalAuthorization.approved_at.desc())
            )
            if active is not None:
                active.state = "revoked"
                active.revoked_by = approved_by
                active.revoked_at = approved_at
                active.revocation_reason = reason or "historical registry revocation"
            else:
                session.add(
                    DocumentExternalAuthorization(
                        tenant_id=tenant_id,
                        authorization_id=authorization_id,
                        project_id=document.project_id,
                        document_id=document.document_id,
                        document_sha256=sha256,
                        parse_version=document.parse_version,
                        purpose=purpose,
                        provider=provider,
                        policy_version=policy.policy_version,
                        state="revoked",
                        reason=reason or "historical registry revocation",
                        approved_by=approved_by,
                        approved_at=approved_at - timedelta(seconds=1),
                        expires_at=approved_at,
                        revoked_by=approved_by,
                        revoked_at=approved_at,
                        revocation_reason=reason or "historical registry revocation",
                        source="jsonl_registry",
                        source_record_id=identity,
                    )
                )
            counts["revoked"] += 1
    return counts


def migrate_historical_ledgers(
    session: Session,
    *,
    tenant_id: str,
    authorization_id: str,
    ledger_path: Path,
    registry_path: Path | None,
    actor_id: str,
    purpose: str,
    provider: str,
    authorization_days: int = DEFAULT_REGISTRY_AUTHORIZATION_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import one source pair; returns a report and commits unless ``dry_run``."""
    if not 1 <= authorization_days <= 3650:
        raise ValueError("registry authorization days are outside the supported range")
    set_tenant(session, tenant_id)
    actor = session.get(User, (tenant_id, actor_id), populate_existing=True)
    if actor is None or not actor.active:
        raise LookupError("the import actor is not an active tenant user")
    account = session.get(
        ModelBudgetAccount,
        (tenant_id, authorization_id),
        populate_existing=True,
        with_for_update=True,
    )
    if account is None:
        raise LookupError("the destination budget account is not provisioned")
    source = read_source_ledger(ledger_path)
    registry_digest, registry_rows = (
        read_registry(registry_path) if registry_path is not None else ("", ())
    )
    existing_import = session.scalar(
        select(LedgerImport).where(
            LedgerImport.tenant_id == tenant_id,
            LedgerImport.authorization_id == authorization_id,
            LedgerImport.source_ledger_sha256 == source.sha256,
            LedgerImport.source_registry_sha256 == (registry_digest or None),
        )
    )
    if existing_import is not None:
        return {
            "applied": False,
            "already_imported": True,
            "source_ledger_sha256": source.sha256,
            "source_registry_sha256": registry_digest,
            "imported_counts": existing_import.imported_counts,
            "imported_sums": existing_import.imported_sums,
            "exceptions": [],
            "account": {
                "limit_cny": str(account.limit_cny),
                "reserved_cny": str(account.reserved_cny),
                "spent_cny": str(account.spent_cny),
            },
        }
    exceptions: list[dict[str, str]] = []
    source_counts, source_sums, new_spent = _import_ledger_rows(
        session,
        tenant_id=tenant_id,
        authorization_id=authorization_id,
        source=source,
        exceptions=exceptions,
    )
    registry_counts = (
        _import_registry_rows(
            session,
            tenant_id=tenant_id,
            purpose=purpose,
            provider=provider,
            records=registry_rows,
            authorization_days=authorization_days,
            exceptions=exceptions,
        )
        if registry_rows
        else {"approved": 0, "revoked": 0, "existing": 0}
    )
    if Decimal(account.spent_cny) + Decimal(account.reserved_cny) + new_spent > Decimal(
        account.limit_cny
    ):
        exceptions.append(
            {
                "source": "destination",
                "record": authorization_id,
                "code": "BUDGET_OVERFLOW",
                "detail": "the imported spend exceeds the provisioned account limit",
            }
        )
    if exceptions:
        session.rollback()
        raise LedgerMigrationError(exceptions)
    account.spent_cny = Decimal(account.spent_cny) + new_spent
    account.updated_at = datetime.now(UTC)
    imported_counts = {**source_counts, **{f"registry_{k}": v for k, v in registry_counts.items()}}
    imported_sums = {
        "charged_cny": str(new_spent),
        "source_ledger_sha256": source.sha256,
        "source_registry_sha256": registry_digest,
    }
    report = {
        "tenant_id": tenant_id,
        "authorization_id": authorization_id,
        "source_ledger_sha256": source.sha256,
        "source_registry_sha256": registry_digest,
        "source_counts": source_counts,
        "source_sums": source_sums,
        "registry_counts": registry_counts,
        "imported_counts": imported_counts,
        "imported_sums": imported_sums,
        "exceptions": [],
        "account": {
            "limit_cny": str(account.limit_cny),
            "reserved_cny": str(account.reserved_cny),
            "spent_cny": str(account.spent_cny),
        },
        "dry_run": dry_run,
    }
    import_id = _report_digest(
        {
            "ledger": source.sha256,
            "registry": registry_digest,
            "tenant": tenant_id,
            "authorization": authorization_id,
        }
    )[:64]
    if not dry_run:
        session.add(
            LedgerImport(
                tenant_id=tenant_id,
                import_id=import_id,
                authorization_id=authorization_id,
                source_ledger_sha256=source.sha256,
                source_registry_sha256=registry_digest or None,
                source_counts=source_counts,
                source_sums=source_sums,
                imported_counts=imported_counts,
                imported_sums=imported_sums,
                report_sha256=_report_digest(report),
                imported_by=actor_id,
                imported_at=datetime.now(UTC),
            )
        )
        audit(
            session,
            tenant_id,
            actor_id,
            "execution_ledger.imported",
            authorization_id,
        )
        session.commit()
    else:
        session.rollback()
    return report
