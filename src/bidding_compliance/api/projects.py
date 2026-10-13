"""HTTP adapters for identity and tenant-scoped projects."""

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from bidding_compliance.core.config import Settings
from bidding_compliance.domain.identity import Principal
from bidding_compliance.persistence.models import AuthSession
from bidding_compliance.services import identity, projects

from .project_schemas import (
    AccessToken,
    Identity,
    Login,
    Logout,
    ProjectCreate,
    ProjectHistory,
    ProjectList,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(prefix="/api/v1")
bearer = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    engine = cast(Engine | None, request.app.state.engine)
    if engine is None:
        raise HTTPException(500)
    with Session(engine, expire_on_commit=False) as session:
        if engine.dialect.name == "postgresql" and session.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ):
            raise HTTPException(500)
        yield session


DB = Annotated[Session, Depends(get_session)]


def current_principal(
    request: Request,
    session: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None or len(credentials.credentials) > 4096:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    try:
        return identity.authenticate(
            session, cast(Settings, request.app.state.settings), credentials.credentials
        )
    except PermissionError as exc:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"}) from exc


User = Annotated[Principal, Depends(current_principal)]


@router.post("/auth/token", response_model=AccessToken, operation_id="login")
def login(body: Login, request: Request, response: Response, session: DB) -> AccessToken:
    settings = cast(Settings, request.app.state.settings)
    try:
        token = identity.login(
            session, settings, body.tenant_id, body.username, body.password.get_secret_value()
        )
    except PermissionError as exc:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"}) from exc
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return AccessToken(access_token=token, expires_in=settings.auth_ttl_seconds)


@router.get("/auth/me", response_model=Identity, operation_id="getIdentity")
def me(principal: User) -> Identity:
    return Identity(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        username=principal.username,
        role=principal.role,
    )


@router.post("/auth/logout", response_model=Logout, operation_id="logout")
def logout(principal: User, session: DB) -> Logout:
    record = session.get(AuthSession, (principal.tenant_id, principal.session_id))
    if record is None:
        raise HTTPException(401)
    record.revoked = True
    identity.audit(session, principal.tenant_id, principal.user_id, "auth.logout")
    session.commit()
    return Logout()


@router.post(
    "/projects", status_code=201, response_model=ProjectResponse, operation_id="createProject"
)
def create_project(
    body: ProjectCreate,
    principal: User,
    session: DB,
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ProjectResponse:
    try:
        return ProjectResponse.model_validate(
            projects.create_project(session, principal, body.model_dump(), key)
        )
    except PermissionError as exc:
        raise HTTPException(403) from exc
    except FileExistsError as exc:
        raise HTTPException(409) from exc


@router.get("/projects", response_model=ProjectList, operation_id="listProjects")
def list_projects(
    principal: User,
    session: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ProjectList:
    rows = projects.list_projects(session, principal, offset, limit)
    return ProjectList(
        items=[ProjectResponse.model_validate(row) for row in rows], offset=offset, limit=limit
    )


@router.get("/projects/{projectId}", response_model=ProjectResponse, operation_id="getProject")
def get_project(projectId: str, principal: User, session: DB) -> ProjectResponse:
    try:
        return ProjectResponse.model_validate(
            projects.snapshot(projects.find_project(session, principal, projectId))
        )
    except LookupError as exc:
        raise HTTPException(404) from exc


@router.put("/projects/{projectId}", response_model=ProjectResponse, operation_id="updateProject")
def update_project(
    projectId: str, body: ProjectUpdate, principal: User, session: DB
) -> ProjectResponse:
    try:
        return ProjectResponse.model_validate(
            projects.update_project(
                session,
                principal,
                projectId,
                body.expected_version,
                body.model_dump(exclude={"expected_version"}),
            )
        )
    except PermissionError as exc:
        raise HTTPException(403) from exc
    except LookupError as exc:
        raise HTTPException(404) from exc
    except FileExistsError as exc:
        raise HTTPException(409) from exc


@router.get(
    "/projects/{projectId}/versions",
    response_model=ProjectHistory,
    operation_id="getProjectHistory",
)
def project_versions(projectId: str, principal: User, session: DB) -> ProjectHistory:
    try:
        return ProjectHistory(
            items=[
                ProjectResponse.model_validate(row)
                for row in projects.history(session, principal, projectId)
            ]
        )
    except LookupError as exc:
        raise HTTPException(404) from exc
