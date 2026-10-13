"""Server-side project authorization before legal retrieval or embedding execution."""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from bidding_compliance.domain.identity import Principal
from bidding_compliance.legal.contracts import RetrievalQuery, RetrievalResult
from bidding_compliance.legal.retrieval import LegalRetriever
from bidding_compliance.persistence.models import AuthSession, Tenant, User
from bidding_compliance.services.projects import find_project


def retrieve_for_project(
    session: Session, principal: Principal, project_id: str, retriever: LegalRetriever,
    *, text: str, review_date: date, include_references: bool = False, limit: int = 10,
) -> RetrievalResult:
    tenant = session.get(Tenant, principal.tenant_id, populate_existing=True)
    user = session.get(User, (principal.tenant_id, principal.user_id), populate_existing=True)
    auth = session.get(
        AuthSession, (principal.tenant_id, principal.session_id), populate_existing=True
    )
    if (
        tenant is None or not tenant.active or user is None or not user.active
        or user.role != principal.role.value or auth is None or auth.revoked
        or auth.user_id != principal.user_id
        or auth.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
    ):
        raise PermissionError("legal retrieval identity unavailable")
    project = find_project(session, principal, project_id)
    query = RetrievalQuery(
        text=text, review_date=review_date, region=project.context["region"],
        procurement_type=project.context["procurement_type"],
        project_type=project.context["project_type"],
        include_references=include_references, limit=limit,
    )
    return retriever.search(query)
