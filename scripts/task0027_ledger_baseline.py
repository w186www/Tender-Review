"""Read-only DEC-007 budget-ledger baseline check for the TASK-0027 controlled round.

The script reports the four values an operator must see before a paid call is allowed --
LLM request count, embedding batch count, cumulative charged-or-reserved CNY and unsettled
reservations -- and compares them with the documented pre-round baseline. It opens the
ledger with SQLite's ``mode=ro`` URI: the file is never created, never modified and never
rewritten, so a mismatch is *reported and the round stops*; it is never "fixed" by
deleting, replacing or resetting the ledger.

    python scripts/task0027_ledger_baseline.py                  # ledger from the environment
    python scripts/task0027_ledger_baseline.py --ledger <path> --json

Exit codes: 0 the baseline matches, 2 mismatch or unreadable/absent ledger (stop).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bidding_compliance.model_gateway.authorized_runtime import (  # noqa: E402
    FULL_CAPABILITY_AUTHORIZATION_ID,
)
from bidding_compliance.services.real_ai_runtime import (  # noqa: E402
    DEC007_LEDGER_FILE,
)

# The one private root the server assemblies use inside the modelstate volume: inside the
# container this is ``/app/.verification/private`` (the volume root), which is where the
# recorded phase-one ledger and registry live. The explicit DEC007_LEDGER_PATH variable still
# wins, so a different round can point elsewhere.
PRIVATE_ROOT = ROOT / ".verification" / "private"

# The phase-two pre-round baseline of the TASK-0027 controlled round, measured read-only on
# the recorded DEC-007 ledger: the phase-one round reserved two LLM requests, the full-corpus
# prebuild recorded exactly 312 embedding batches, and the settled-and-reserved total is
# 0.1062161 CNY with no reservation in flight. A mismatch means the ledger moved since the
# baseline was recorded: report it and stop, never delete or reset the ledger.
ROUND_BASELINE: dict[str, Any] = {
    "llm_calls": 2,
    "embedding_batches": 312,
    "charged_or_reserved_cny": Decimal("0.1062161"),
    "unsettled_requests": 0,
}


class BaselineCheckFailed(RuntimeError):
    """The ledger is absent, unreadable or does not match the expected baseline."""


@dataclass(frozen=True, slots=True)
class LedgerFacts:
    """What the ledger file says about one authorization, read-only."""

    path: Path
    authorization_id: str
    llm_calls: int
    embedding_batches: int
    charged_or_reserved_cny: Decimal
    unsettled_requests: int
    scope_sha256: str | None
    history: dict[str, dict[str, Any]]

    def as_payload(self) -> dict[str, Any]:
        return {
            "ledger": str(self.path),
            "authorization_id": self.authorization_id,
            "llm_calls": self.llm_calls,
            "embedding_batches": self.embedding_batches,
            "charged_or_reserved_cny": str(self.charged_or_reserved_cny),
            "unsettled_requests": self.unsettled_requests,
            "scope_sha256": self.scope_sha256,
            "ledger_history": self.history,
        }


def read_ledger_facts(ledger_path: Path, *, authorization_id: str) -> LedgerFacts:
    """Read the durable counters of one authorization without touching the file.

    A missing file is reported instead of being created: "the ledger is not there" is a
    stop condition for this round, never a reason to initialise a fresh quota.
    """
    resolved = Path(ledger_path).resolve()
    if not resolved.is_file():
        raise BaselineCheckFailed(
            f"the DEC ledger is absent at {resolved}; stop and report instead of "
            "initialising a fresh quota"
        )
    try:
        with sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=5) as connection:
            rows = connection.execute(
                "SELECT kind, charge, status FROM requests WHERE authorization_id=?",
                (authorization_id,),
            ).fetchall()
            scope_row = connection.execute(
                "SELECT scope_sha256 FROM authorization WHERE id=?", (authorization_id,)
            ).fetchone()
            history_rows = connection.execute(
                "SELECT authorization_id, kind, charge FROM requests"
            ).fetchall()
    except sqlite3.Error as exc:
        raise BaselineCheckFailed(f"the DEC ledger is unreadable at {resolved}") from exc
    history: dict[str, dict[str, Any]] = {}
    for authorization, kind, charge in history_rows:
        entry = history.setdefault(
            authorization, {"llm_calls": 0, "embedding_batches": 0, "charged_cny": Decimal(0)}
        )
        if kind == "llm":
            entry["llm_calls"] += 1
        elif kind == "embedding":
            entry["embedding_batches"] += 1
        entry["charged_cny"] += Decimal(charge)
    return LedgerFacts(
        path=resolved,
        authorization_id=authorization_id,
        llm_calls=sum(row[0] == "llm" for row in rows),
        embedding_batches=sum(row[0] == "embedding" for row in rows),
        charged_or_reserved_cny=sum((Decimal(row[1]) for row in rows), Decimal(0)),
        unsettled_requests=sum(row[2] == "reserved" for row in rows),
        scope_sha256=scope_row[0] if scope_row is not None else None,
        history={
            authorization: {**entry, "charged_cny": str(entry["charged_cny"])}
            for authorization, entry in sorted(history.items())
        },
    )


def baseline_differences(facts: LedgerFacts, expected: dict[str, Any]) -> list[str]:
    """Human-readable differences; an empty list means the baseline matches exactly."""
    differences = []
    for field in ("llm_calls", "embedding_batches", "unsettled_requests"):
        observed, wanted = getattr(facts, field), expected[field]
        if observed != wanted:
            differences.append(f"{field}: observed {observed}, expected {wanted}")
    observed_cny, wanted_cny = facts.charged_or_reserved_cny, expected["charged_or_reserved_cny"]
    if observed_cny != wanted_cny:
        differences.append(
            f"charged_or_reserved_cny: observed {observed_cny}, expected {wanted_cny}"
        )
    return differences


def check_baseline(
    ledger_path: Path, *, authorization_id: str, expected: dict[str, Any]
) -> LedgerFacts:
    """Facts for a matching baseline; raises :class:`BaselineCheckFailed` otherwise."""
    facts = read_ledger_facts(ledger_path, authorization_id=authorization_id)
    differences = baseline_differences(facts, expected)
    if differences:
        raise BaselineCheckFailed(
            "the DEC ledger does not match the documented baseline: " + "; ".join(differences)
        )
    return facts


def ledger_path_from(environment: dict[str, str], *, private_root: Path = PRIVATE_ROOT) -> Path:
    """The ledger the server assembly would use: explicit variable, else the default file."""
    override = environment.get("DEC007_LEDGER_PATH", "").strip()
    return Path(override) if override else private_root / DEC007_LEDGER_FILE


def decimal_argument(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a decimal amount") from exc
    if not parsed.is_finite() or parsed < 0:
        raise argparse.ArgumentTypeError("the expected amount must be finite and non-negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ledger", type=Path, default=None, help="ledger path (read-only)")
    parser.add_argument(
        "--authorization-id",
        default=os.environ.get("DEC007_AUTHORIZATION_ID", "").strip()
        or FULL_CAPABILITY_AUTHORIZATION_ID,
    )
    parser.add_argument("--private-root", type=Path, default=PRIVATE_ROOT)
    parser.add_argument("--expect-llm", type=int, default=ROUND_BASELINE["llm_calls"])
    parser.add_argument("--expect-embedding", type=int, default=ROUND_BASELINE["embedding_batches"])
    parser.add_argument(
        "--expect-cny",
        type=decimal_argument,
        default=ROUND_BASELINE["charged_or_reserved_cny"],
    )
    parser.add_argument(
        "--expect-unsettled", type=int, default=ROUND_BASELINE["unsettled_requests"]
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ledger = args.ledger or ledger_path_from(os.environ, private_root=args.private_root)
    expected = {
        "llm_calls": args.expect_llm,
        "embedding_batches": args.expect_embedding,
        "charged_or_reserved_cny": args.expect_cny,
        "unsettled_requests": args.expect_unsettled,
    }
    try:
        facts = read_ledger_facts(ledger, authorization_id=args.authorization_id)
        differences = baseline_differences(facts, expected)
    except BaselineCheckFailed as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        print(
            "Stop the round and report to the operator. Do not delete, replace or reset "
            "the ledger: restoring the quota that way is exactly what DEC-007 forbids.",
            file=sys.stderr,
        )
        return 2
    if args.json:
        expected_payload = {
            **expected,
            "charged_or_reserved_cny": str(expected["charged_or_reserved_cny"]),
        }
        print(
            json.dumps(
                {
                    "expected": expected_payload,
                    "observed": facts.as_payload(),
                    "differences": differences,
                    "baseline_matches": not differences,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"ledger: {facts.path}")
        print(f"authorization: {facts.authorization_id}")
        print(f"llm_calls: {facts.llm_calls} (expected {expected['llm_calls']})")
        print(
            f"embedding_batches: {facts.embedding_batches} "
            f"(expected {expected['embedding_batches']})"
        )
        print(
            "charged_or_reserved_cny: "
            f"{facts.charged_or_reserved_cny} (expected {expected['charged_or_reserved_cny']})"
        )
        print(
            f"unsettled_requests: {facts.unsettled_requests} "
            f"(expected {expected['unsettled_requests']})"
        )
        for authorization, entry in facts.history.items():
            print(
                f"ledger_history {authorization}: llm_calls={entry['llm_calls']} "
                f"embedding_batches={entry['embedding_batches']} charged_cny={entry['charged_cny']}"
            )
        if differences:
            print("STOP: the DEC ledger does not match the documented baseline:")
            for difference in differences:
                print(f"  - {difference}")
            print(
                "Stop the round and report to the operator. Do not delete, replace or reset "
                "the ledger: restoring the quota that way is exactly what DEC-007 forbids."
            )
            return 2
        print("PASS: the ledger matches the documented pre-round baseline.")
    return 0 if not differences else 2


if __name__ == "__main__":
    raise SystemExit(main())
