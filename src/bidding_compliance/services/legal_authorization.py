"""Recheck live identity and independently provisioned global grants before every operation."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.legal.management_contracts import (
    OPERATIONS,
    LegalOperation,
    OperatorCapabilities,
)
from bidding_compliance.persistence.models import LegalOperatorGrant
from bidding_compliance.services.identity import audit
from bidding_compliance.services.legal import require_identity


def require_legal_operation(
    session: Session, principal: Principal, operation: LegalOperation
) -> None:
    require_identity(session, principal)
    if operation not in OPERATIONS:
        raise ValueError("unknown global legal operation")
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.user_id', :actor, true)"), {"actor": principal.user_id}
        )
    grant = session.get(
        LegalOperatorGrant, (principal.tenant_id, principal.user_id), populate_existing=True
    )
    capabilities = (
        OperatorCapabilities.model_validate(
            {
                "active": grant.active,
                "capabilities": grant.capabilities,
            }
        )
        if grant
        else None
    )
    if (
        capabilities is None
        or not capabilities.active
        or operation not in capabilities.capabilities
    ):
        audit(session, principal.tenant_id, principal.user_id, "legal.operator.denied", operation)
        session.commit()
        raise PermissionError("global legal operation forbidden")
