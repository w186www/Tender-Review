"""Explicit migration/bootstrap CLI; credentials come only from the environment/getpass."""

import argparse
import getpass
from uuid import uuid4

from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Role
from bidding_compliance.persistence.database import make_engine, migrate, set_tenant
from bidding_compliance.persistence.models import Tenant, User
from bidding_compliance.services.identity import PASSWORDS, audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit database and identity administration")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("migrate")
    bootstrap = commands.add_parser("bootstrap")
    bootstrap.add_argument("--tenant", required=True)
    bootstrap.add_argument("--tenant-name", required=True)
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--role", choices=[r.value for r in Role], required=True)
    args = parser.parse_args()
    engine = make_engine(Settings())
    try:
        if args.action == "migrate":
            migrate(engine)
        else:
            if not (
                1 <= len(args.tenant) <= 64
                and 1 <= len(args.username) <= 100
                and 1 <= len(args.tenant_name) <= 200
            ):
                raise ValueError("identity field length invalid")
            password = getpass.getpass("New account password (12+ characters): ")
            if len(password) < 12 or len(password) > 1024:
                raise ValueError("password length invalid")
            if password != getpass.getpass("Confirm password: "):
                raise ValueError("password confirmation failed")
            with Session(engine) as session:
                if session.get(Tenant, args.tenant) is None:
                    session.add(Tenant(tenant_id=args.tenant, name=args.tenant_name, active=True))
                    session.flush()
                set_tenant(session, args.tenant)
                user = User(
                    tenant_id=args.tenant,
                    user_id=str(uuid4()),
                    username=args.username,
                    password_hash=PASSWORDS.hash(password),
                    role=args.role,
                    active=True,
                )
                session.add(user)
                audit(session, args.tenant, None, "identity.bootstrap", user.user_id)
                session.commit()
        print("Identity administration completed.")
        return 0
    except Exception:  # CLI errors intentionally exclude credentials, SQL and exception messages.
        print("Identity administration failed; check configuration and database state.")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
