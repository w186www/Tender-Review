"""D05: tenant roles cannot grant themselves global corpus permissions."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_legal_runs import principal
from test_legal_runs import system as legal_system

from bidding_compliance.domain.identity import Principal, Role
from bidding_compliance.legal.management_contracts import OperatorCapabilities
from bidding_compliance.persistence.models import AuditEvent, AuthSession, LegalOperatorGrant, User
from bidding_compliance.services.legal_authorization import require_legal_operation

system = legal_system


@pytest.mark.parametrize("operation", ["ingest", "verify", "publish", "disable", "rollback"])
def test_tenant_admin_has_no_implicit_global_permission(system, operation):
    engine, _, _ = system
    with Session(engine) as db:
        db.get(User, ("a", "u")).role = "admin"
        db.commit()
        actor = Principal("a", "u", "u", Role.ADMIN, "s")
        with pytest.raises(PermissionError, match="global legal operation forbidden"):
            require_legal_operation(db, actor, operation)
        event = db.scalar(select(AuditEvent))
        assert event.action == "legal.operator.denied" and event.resource_id == operation


def test_independent_grant_capabilities_and_cross_tenant_boundary(system):
    engine, _, _ = system
    with Session(engine) as db:
        db.add(
            LegalOperatorGrant(tenant_id="b", user_id="u", active=True, capabilities=["publish"])
        )
        db.commit()
        with pytest.raises(PermissionError):
            require_legal_operation(db, principal(), "publish")
        db.add(LegalOperatorGrant(tenant_id="a", user_id="u", active=True, capabilities=["ingest"]))
        db.commit()
        require_legal_operation(db, principal(), "ingest")
        with pytest.raises(PermissionError):
            require_legal_operation(db, principal(), "verify")
        with pytest.raises(PermissionError):
            require_legal_operation(db, principal(), "publish")


@pytest.mark.parametrize("revocation", ["grant", "capability", "identity", "session"])
def test_live_revocation_is_not_cached(system, revocation):
    engine, _, _ = system
    with Session(engine) as db:
        db.add(
            LegalOperatorGrant(tenant_id="a", user_id="u", active=True, capabilities=["publish"])
        )
        db.commit()
        require_legal_operation(db, principal(), "publish")
        if revocation == "grant":
            db.get(LegalOperatorGrant, ("a", "u")).active = False
        elif revocation == "capability":
            db.get(LegalOperatorGrant, ("a", "u")).capabilities = []
        elif revocation == "identity":
            db.get(User, ("a", "u")).active = False
        else:
            db.get(AuthSession, ("a", "s")).revoked = True
        db.commit()
        with pytest.raises(PermissionError):
            require_legal_operation(db, principal(), "publish")


def test_grant_requires_real_tenant_user_composite_fk(system):
    engine, _, _ = system
    with Session(engine) as db:
        db.add(
            LegalOperatorGrant(
                tenant_id="a", user_id="foreign", active=True, capabilities=["publish"]
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("permissions", [["root"], ["publish", "publish"]])
def test_invalid_global_capability_contract_rejected(permissions):
    with pytest.raises(ValidationError):
        OperatorCapabilities(active=True, capabilities=permissions)
