"""Import historical DEC ledger/registry data into the PostgreSQL product authority.

The source files are opened read-only. The import is one destination transaction; any
malformed, conflicting or unmappable record aborts it and prints the exception list. Run it
first with ``--dry-run`` on a protected copy, compare the counts/sums, then run it for real
after external sending is stopped and the destination account is provisioned.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.persistence.database import make_engine
from bidding_compliance.services.ledger_migration import (
    LedgerMigrationError,
    migrate_historical_ledgers,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--actor", required=True, help="active tenant user id")
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--authorization-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database-url", help="management database URL; defaults to settings")
    args = parser.parse_args()
    settings = (
        Settings(_env_file=None, database_url=args.database_url)
        if args.database_url
        else Settings()
    )
    engine = make_engine(settings)
    try:
        with Session(engine) as session:
            report = migrate_historical_ledgers(
                session,
                tenant_id=args.tenant,
                authorization_id=args.authorization_id,
                ledger_path=args.ledger,
                registry_path=args.registry,
                actor_id=args.actor,
                purpose=args.purpose,
                provider=args.provider,
                authorization_days=args.authorization_days,
                dry_run=args.dry_run,
            )
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0
    except LedgerMigrationError as exc:
        print(
            json.dumps(
                {"status": "aborted", "exceptions": exc.exceptions},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except (LookupError, ValueError, FileNotFoundError, PermissionError) as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, ensure_ascii=False))
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
