"""DEC-005 durable, bounded local authorization; no document text or secrets stored."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from .budget import BudgetReservation
from .errors import GatewayErrorCode, ModelGatewayError

AUTHORIZATION_ID = "DEC-005-2026-10-15"
SEMANTIC_AUTHORIZATION_ID = "DEC-006-2026-10-15"
FULL_CAPABILITY_AUTHORIZATION_ID = "DEC-007-2026-10-16"
HARD_LLM_CALLS = 30
HARD_EMBEDDING_BATCHES = 200
HARD_TOTAL_CNY = Decimal("20")
LLM_RESERVATION_CNY = Decimal("0.25")

# Every entry is one explicit local authorization. A ledger bound to an entry can never
# exceed that entry's ceiling, and earlier authorizations keep their own counters and
# history; a new authorization never resets an exhausted one.
AUTHORIZATION_LIMITS: dict[str, dict[str, Any]] = {
    AUTHORIZATION_ID: {"llm": 30, "embedding": 200, "cny": Decimal("20")},
    SEMANTIC_AUTHORIZATION_ID: {"llm": 15, "embedding": 0, "cny": Decimal("5")},
    # DEC-007 is a separate authorization with its own ledger file and scope; it neither
    # reuses nor resets the DEC-005/DEC-006 counters above. Building and querying share one
    # ledger (no split build/query budgets).
    #
    # 2026-10-16, operator instruction: the original self-imposed ceilings (300 LLM / 800
    # embedding / CNY 30) were low enough to block the final acceptance test and real use
    # after the phase-one round had already recorded 2 LLM calls, 312 embedding batches and
    # 0.1062161 CNY on this same ledger. Only the numbers were raised, to 2000 / 2000 /
    # CNY 200; the authorization id, the ledger file and every recorded row stay exactly as
    # they are (nothing is deleted, replaced or reset, and the counters never decrease).
    # The runaway guards are untouched: one full-ceiling reservation before any networking,
    # no automatic retry (max_attempts=1), concurrency 1 per provider, failed or
    # unknown-usage reservations keep their reservation, and every ceiling is cumulative
    # over the same authorization id.
    FULL_CAPABILITY_AUTHORIZATION_ID: {"llm": 2000, "embedding": 2000, "cny": Decimal("200")},
}


def _reject(message: str) -> ModelGatewayError:
    return ModelGatewayError(GatewayErrorCode.BUDGET_EXCEEDED, message)


class Dec005BudgetLedger:
    """Reserve the full ceiling before networking, atomically across processes/restarts.

    Pending and failed requests retain their ceiling. Counters never decrease. This is
    one explicit local authorization, not an authorization for arbitrary user uploads.
    """

    def __init__(
        self,
        path: Path,
        *,
        scope_sha256: str,
        authorization_id: str = AUTHORIZATION_ID,
        llm_limit: int | None = None,
        embedding_limit: int | None = None,
        total_cny: Decimal | None = None,
    ) -> None:
        if authorization_id not in AUTHORIZATION_LIMITS:
            raise ValueError("unknown local authorization")
        # An omitted ceiling means "exactly what this authorization allows".
        hard = AUTHORIZATION_LIMITS[authorization_id]
        llm_limit = hard["llm"] if llm_limit is None else llm_limit
        embedding_limit = hard["embedding"] if embedding_limit is None else embedding_limit
        total_cny = hard["cny"] if total_cny is None else total_cny
        if (
            len(scope_sha256) != 64
            or any(c not in "0123456789abcdef" for c in scope_sha256)
            or type(llm_limit) is not int
            or not 0 <= llm_limit <= hard["llm"]
            or type(embedding_limit) is not int
            or not 0 <= embedding_limit <= hard["embedding"]
            or not total_cny.is_finite()
            or not 0 <= total_cny <= hard["cny"]
        ):
            raise ValueError("DEC authorization scope and limits must be explicit and bounded")
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.authorization_id = authorization_id
        self.llm_limit = llm_limit
        self.embedding_limit = embedding_limit
        self.total_cny = total_cny
        self.scope_sha256 = scope_sha256
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS authorization "
                "(id TEXT PRIMARY KEY, scope_sha256 TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS requests "
                "(id TEXT PRIMARY KEY, kind TEXT NOT NULL, request_hash TEXT NOT NULL, "
                "ceiling TEXT NOT NULL, charge TEXT NOT NULL, status TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            # Existing rows predate per-authorization accounting and stay with DEC-005.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(requests)")}
            if "authorization_id" not in columns:
                connection.execute(
                    "ALTER TABLE requests ADD COLUMN authorization_id TEXT NOT NULL "
                    f"DEFAULT '{AUTHORIZATION_ID}'"
                )
            connection.execute(
                "INSERT OR IGNORE INTO authorization VALUES (?, ?)",
                (authorization_id, scope_sha256),
            )
            scope = connection.execute(
                "SELECT scope_sha256 FROM authorization WHERE id=?", (authorization_id,)
            ).fetchone()
            if scope != (scope_sha256,):
                raise ValueError("existing DEC ledger has a different scope")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def reserve_external(self, *, kind: str, request_hash: str, ceiling: Decimal) -> str:
        if (
            kind not in {"llm", "embedding"}
            or not ceiling.is_finite()
            or ceiling <= 0
            or ceiling > (LLM_RESERVATION_CNY if kind == "llm" else Decimal("0.10"))
            or len(request_hash) != 64
            or any(c not in "0123456789abcdef" for c in request_hash)
        ):
            raise _reject("External reservation is outside DEC-005 bounds.")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            records = connection.execute(
                "SELECT kind, charge FROM requests WHERE authorization_id=?",
                (self.authorization_id,),
            ).fetchall()
            limit = self.llm_limit if kind == "llm" else self.embedding_limit
            if sum(item[0] == kind for item in records) >= limit:
                raise _reject("DEC external request count exhausted.")
            spent = sum((Decimal(item[1]) for item in records), Decimal(0))
            if spent + ceiling > self.total_cny:
                raise _reject("DEC cumulative supplier budget exhausted.")
            reservation = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO requests(id,kind,request_hash,ceiling,charge,status,authorization_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    reservation,
                    kind,
                    request_hash,
                    str(ceiling),
                    str(ceiling),
                    "reserved",
                    self.authorization_id,
                ),
            )
        return reservation

    def settle_external(self, reservation: str, actual: Decimal) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = connection.execute(
                "SELECT ceiling,status FROM requests WHERE id=? AND authorization_id=?",
                (reservation, self.authorization_id),
            ).fetchone()
            if (
                record is None
                or record[1] != "reserved"
                or not actual.is_finite()
                or actual < 0
                or actual > Decimal(record[0])
            ):
                raise _reject("External usage exceeds its reservation or was already settled.")
            connection.execute(
                "UPDATE requests SET charge=?,status='settled' WHERE id=?",
                (str(actual), reservation),
            )

    def reserve(self, tenant_id: str, task_id: str, amount: Decimal) -> BudgetReservation:
        if not amount.is_finite() or not 0 <= amount <= LLM_RESERVATION_CNY:
            raise _reject("LLM quote exceeds its fixed reservation.")
        request_hash = hashlib.sha256(f"{tenant_id}:{task_id}".encode()).hexdigest()
        identifier = self.reserve_external(
            kind="llm", request_hash=request_hash, ceiling=LLM_RESERVATION_CNY
        )
        return BudgetReservation(identifier, tenant_id, task_id, LLM_RESERVATION_CNY)

    def settle(self, reservation: BudgetReservation, actual: Decimal) -> None:
        self.settle_external(reservation.reservation_id, actual)

    def consume_reservation(self, reservation: BudgetReservation) -> None:
        self.settle_external(reservation.reservation_id, reservation.amount)

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT kind,charge,status FROM requests WHERE authorization_id=?",
                (self.authorization_id,),
            ).fetchall()
            history = connection.execute(
                "SELECT authorization_id, kind, charge FROM requests"
            ).fetchall()
        ledger: dict[str, dict[str, Any]] = {}
        for authorization, kind, charge in history:
            entry = ledger.setdefault(
                authorization, {"llm_calls": 0, "embedding_batches": 0, "charged_cny": Decimal(0)}
            )
            if kind == "llm":
                entry["llm_calls"] += 1
            elif kind == "embedding":
                entry["embedding_batches"] += 1
            entry["charged_cny"] += Decimal(charge)
        return {
            "authorization_id": self.authorization_id,
            "llm_calls": sum(row[0] == "llm" for row in rows),
            "embedding_batches": sum(row[0] == "embedding" for row in rows),
            "charged_or_reserved_cny": str(sum((Decimal(row[1]) for row in rows), Decimal(0))),
            "unsettled_requests": sum(row[2] == "reserved" for row in rows),
            "limits": {
                "llm_calls": self.llm_limit,
                "embedding_batches": self.embedding_limit,
                "total_cny": str(self.total_cny),
            },
            "ledger_history": {
                authorization: {
                    "llm_calls": entry["llm_calls"],
                    "embedding_batches": entry["embedding_batches"],
                    "charged_cny": str(entry["charged_cny"]),
                }
                for authorization, entry in sorted(ledger.items())
            },
        }


class MetadataAuditSink:
    """Persist only explicit metadata keys, never arbitrary request/response mappings."""

    ALLOWED = frozenset(
        {
            "call_id",
            "tenant_id",
            "review_task_id",
            "node_run_id",
            "provider",
            "model",
            "profile",
            "prompt_version",
            "model_config_version",
            "pricing_version",
            "response_hash",
            "input_tokens",
            "output_tokens",
            "usage_source",
            "estimated_cost",
            "latency_ms",
            "retries",
            "fallback_path",
            "failure_category",
            "request_hash",
            "response_sha256",
            "request_id",
            "dimension",
            "batch_size",
            "status",
            "kind",
            "input_sha256",
            "output_sha256",
            "total_tokens",
            "cost_cny",
            "reservation_id",
            "model_revision",
            "request_sha256",
            "usage_tokens",
            "batch_count",
            "dimensions",
            "error_code",
            "authorization_id",
            "event",
            "identity_sha256",
            "mode",
            "items",
            "input_utf8_bytes",
            "reserved_cost_cny",
            "estimated_cost_cny",
        }
    )

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Verify writable storage before any provider call, without recording secrets.
        with self.path.open("ab"):
            pass

    def __call__(self, event: Any) -> None:
        from dataclasses import asdict, is_dataclass

        record = asdict(event) if is_dataclass(event) and not isinstance(event, type) else event
        if not isinstance(record, Mapping) or set(record) - self.ALLOWED:
            raise ValueError("audit record contains a non-metadata field")
        serialized = json.dumps(dict(record), ensure_ascii=False, sort_keys=True)
        if len(serialized.encode()) > 8192:
            raise ValueError("audit metadata exceeds fixed bounds")
        with self.path.open("ab", buffering=0) as handle:
            import os

            handle.write(serialized.encode() + b"\n")
            os.fsync(handle.fileno())
