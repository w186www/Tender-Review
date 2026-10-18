"""Provision one tenant's product execution policy and its single budget account.

This is an operator command, not a tenant HTTP API. It must connect with a controlled
management role; the runtime role is not granted policy/account writes. The policy, the
account limit and the audit event are committed in one transaction.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.persistence.database import make_engine, set_tenant
from bidding_compliance.persistence.models import ModelBudgetAccount, ModelExecutionPolicy
from bidding_compliance.services.execution_authorization import set_execution_policy


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("invalid decimal amount") from exc
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError("amount must be finite")
    return parsed


def _commands(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("at least one value is required")
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", help="management database URL; defaults to settings")
    sub = parser.add_subparsers(dest="command", required=True)
    set_parser = sub.add_parser("set-policy")
    set_parser.add_argument("--tenant", required=True)
    set_parser.add_argument("--actor", required=True, help="active tenant admin user id")
    set_parser.add_argument("--providers", required=True, type=_commands)
    set_parser.add_argument("--purposes", required=True, type=_commands)
    set_parser.add_argument("--budget-cny", required=True, type=_decimal)
    set_parser.add_argument("--max-call-cny", required=True, type=_decimal)
    set_parser.add_argument("--max-embedding-batch-cny", required=True, type=_decimal)
    set_parser.add_argument("--max-authorization-ttl-seconds", required=True, type=int)
    set_parser.add_argument(
        "--budget-authorization-id",
        required=True,
        help="the same PRODUCT_BUDGET_AUTHORIZATION_ID the product runtime uses",
    )
    set_parser.add_argument("--disable", action="store_true")
    show_parser = sub.add_parser("show")
    show_parser.add_argument("--tenant", required=True)
    args = parser.parse_args()

    settings = (
        Settings(_env_file=None, database_url=args.database_url)
        if args.database_url
        else Settings()
    )
    engine = make_engine(settings)
    try:
        with Session(engine) as session:
            if args.command == "set-policy":
                policy = set_execution_policy(
                    session,
                    tenant_id=args.tenant,
                    actor_id=args.actor,
                    allowed_providers=args.providers,
                    allowed_purposes=args.purposes,
                    budget_cny=args.budget_cny,
                    max_call_cny=args.max_call_cny,
                    max_embedding_batch_cny=args.max_embedding_batch_cny,
                    max_authorization_ttl_seconds=args.max_authorization_ttl_seconds,
                    active=not args.disable,
                    budget_authorization_id=args.budget_authorization_id,
                )
                account = session.get(
                    ModelBudgetAccount,
                    (args.tenant, args.budget_authorization_id),
                    populate_existing=True,
                )
                print(
                    json.dumps(
                        {
                            "tenant_id": policy.tenant_id,
                            "policy_version": policy.policy_version,
                            "active": policy.active,
                            "providers": policy.allowed_providers,
                            "purposes": policy.allowed_purposes,
                            "budget_cny": str(policy.budget_cny),
                            "account_limit_cny": str(account.limit_cny) if account else None,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 0
            set_tenant(session, args.tenant)
            policy = session.get(
                ModelExecutionPolicy, args.tenant, populate_existing=True
            )
            if policy is None:
                raise LookupError("execution policy is not configured")
            print(
                json.dumps(
                    {
                        "tenant_id": policy.tenant_id,
                        "policy_version": policy.policy_version,
                        "active": policy.active,
                        "providers": sorted(policy.allowed_providers),
                        "purposes": sorted(policy.allowed_purposes),
                        "budget_cny": str(policy.budget_cny),
                        "max_call_cny": str(policy.max_call_cny),
                        "max_embedding_batch_cny": str(policy.max_embedding_batch_cny),
                        "max_authorization_ttl_seconds": (
                            policy.max_authorization_ttl_seconds
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
    except (PermissionError, ValueError, LookupError) as exc:
        print(f"execution policy command failed: {exc}")
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
