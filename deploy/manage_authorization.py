"""Operator CLI for the DEC-007 per-file external-processing approvals.

The registry is an append-only JSONL audit trail: every operation appends exactly one line
and nothing is rewritten, so who approved which file, when, with which reason and which
document identity stays auditable. Only the file SHA-256, the document identity, the
reason, the timestamp and the operator are recorded; document content is never read.

    python deploy/manage_authorization.py approve \
        --sha256 <64 lowercase hex> --document <document-id> --reason "面试演示"
    python deploy/manage_authorization.py list [--json]
    python deploy/manage_authorization.py revoke --sha256 <64 lowercase hex> --reason "收回"

The registry path comes from ``--registry`` or ``DEC007_AUTHORIZATION_REGISTRY``; there is
no implicit default location, so an approval can never be written to an unintended file.
Approving a file never touches the budget ledger or its counters, and the API process must
be restarted so the assembly reads the extended registry.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bidding_compliance.services.real_ai_runtime import (  # noqa: E402
    FileAuthorizationRegistry,
)


def registry_path(explicit: str | None) -> Path:
    value = (explicit or os.environ.get("DEC007_AUTHORIZATION_REGISTRY", "")).strip()
    if not value:
        raise SystemExit("--registry or DEC007_AUTHORIZATION_REGISTRY is required")
    return Path(value)


def operator(explicit: str | None) -> str:
    value = (
        explicit
        or os.environ.get("DEC007_AUTHORIZATION_ACTOR", "")
        or os.environ.get("USER", "")
        or os.environ.get("USERNAME", "")
        or "unattributed"
    ).strip()
    return value or "unattributed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--registry", default=None, help="registry file (default DEC007_AUTHORIZATION_REGISTRY)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def sub_command(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        # Accepted on either side of the sub-command: a suppressed default never
        # overwrites a value that was already given before it.
        sub.add_argument("--registry", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        return sub

    approve = sub_command("approve", "record one file as authorized for egress")
    approve.add_argument("--sha256", required=True, help="file SHA-256, 64 lowercase hex")
    approve.add_argument("--document", required=True, help="document identity to record")
    approve.add_argument("--reason", required=True, help="why this file is authorized")
    approve.add_argument("--actor", default=None, help="operator identity (default from env)")

    revoke = sub_command("revoke", "withdraw one previously authorized file")
    revoke.add_argument("--sha256", required=True, help="file SHA-256, 64 lowercase hex")
    revoke.add_argument("--reason", required=True, help="why the authorization is withdrawn")
    revoke.add_argument("--document", default=None, help="override the recorded document id")
    revoke.add_argument("--actor", default=None, help="operator identity (default from env)")

    listing = sub_command("list", "print the audit trail and effective allowlist")
    listing.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser


def last_document(registry: FileAuthorizationRegistry, sha256: str) -> str:
    recorded = [
        record["document_id"] for record in registry.records() if record["sha256"] == sha256
    ]
    return recorded[-1] if recorded else "unrecorded"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = FileAuthorizationRegistry(registry_path(args.registry))
        if args.command == "list":
            allowed = sorted(registry.allowed_sha256())
            records = [dict(record) for record in registry.records()]
            if args.json:
                print(
                    json.dumps(
                        {"registry": str(registry.path), "allowed": allowed, "records": records},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            print(f"registry: {registry.path}")
            for record in records:
                print(
                    " ".join(
                        (
                            record["action"],
                            record["sha256"],
                            record["document_id"],
                            record["approved_at"],
                            record["approved_by"],
                            record["reason"],
                        )
                    )
                )
            print(f"approved files: {len(allowed)}")
            return 0
        if args.command == "approve":
            record = registry.approve(
                sha256=args.sha256,
                document_id=args.document,
                reason=args.reason,
                approved_by=operator(args.actor),
            )
        else:
            document = args.document or last_document(registry, args.sha256)
            record = registry.revoke(
                sha256=args.sha256,
                document_id=document,
                reason=args.reason,
                approved_by=operator(args.actor),
            )
    except ValueError as exc:
        # A malformed registry or hash fails closed with an operator-readable message.
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(dict(record), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
