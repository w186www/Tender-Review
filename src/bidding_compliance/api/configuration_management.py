"""Authenticated REST adapters for tenant review configuration releases."""

from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from bidding_compliance.core.config import Settings
from bidding_compliance.core.dates import as_utc
from bidding_compliance.model_gateway.contracts import DataPolicy, ModelPolicy
from bidding_compliance.services import review_configurations

from .configuration_schemas import (
    ConfigurationCatalog,
    ConfigurationDisableRequest,
    ConfigurationDraftRequest,
    ConfigurationPublishRequest,
    ConfigurationRollbackRequest,
    ConfigurationStateResponse,
)
from .projects import DB, User
from .schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/admin/configurations",
    responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 500)},
)


def _runtime_policy(request: Request) -> ModelPolicy:
    engine = getattr(request.app.state, "review_engine", None)
    if engine is not None:
        return cast(ModelPolicy, engine.model_policy)
    settings = cast(Settings, request.app.state.settings)
    return ModelPolicy(
        profile=settings.model_profile,
        timeout_seconds=90,
        max_attempts=2,
        max_input_tokens=64_000,
        max_output_tokens=8_000,
        temperature=0,
        data_policy=DataPolicy.CONFIDENTIAL,
    )


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(403, detail="当前账号无权管理审查配置")
    if isinstance(exc, LookupError):
        return HTTPException(404, detail="配置版本不存在或不可用")
    if isinstance(exc, (FileExistsError, IntegrityError)):
        return HTTPException(409, detail="配置版本已变化，请刷新后重试")
    if isinstance(exc, ValueError):
        terms = ("stale", "changed", "conflict", "current draft", "published", "rollback")
        status = 409 if any(term in str(exc).casefold() for term in terms) else 422
        return HTTPException(status, detail="配置参数无效或状态冲突")
    return HTTPException(500, detail="配置管理暂时不可用")


def _state_response(value: dict[str, Any]) -> ConfigurationStateResponse:
    return ConfigurationStateResponse.model_validate(
        {
            **value,
            "items": [
                {**item, "created_at": as_utc(item["created_at"])} for item in value["items"]
            ],
            "events": [
                {**item, "created_at": as_utc(item["created_at"])} for item in value["events"]
            ],
        }
    )


@router.get("/catalog", response_model=ConfigurationCatalog, operation_id="getConfigurationCatalog")
def get_catalog(principal: User, session: DB, request: Request) -> ConfigurationCatalog:
    try:
        value = review_configurations.configuration_catalog(
            session, principal, _runtime_policy(request)
        )
        return ConfigurationCatalog.model_validate(value)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("", response_model=ConfigurationStateResponse, operation_id="listConfigurations")
def list_configurations(principal: User, session: DB) -> ConfigurationStateResponse:
    try:
        return _state_response(review_configurations.list_configurations(session, principal))
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/drafts",
    response_model=ConfigurationStateResponse,
    status_code=201,
    operation_id="createConfigurationDraft",
)
def create_draft(
    body: ConfigurationDraftRequest,
    principal: User,
    session: DB,
    request: Request,
) -> ConfigurationStateResponse:
    try:
        review_configurations.create_draft(
            session,
            principal,
            request_id=body.request_id,
            expected_sequence=body.expected_sequence,
            expected_draft_sequence=body.expected_draft_sequence,
            expected_legal_publication_id=body.expected_legal_publication_id,
            skill_ids=tuple(body.skill_ids),
            model_policy=body.model_policy.to_policy(),
            runtime_policy=_runtime_policy(request),
            reason=body.reason,
        )
        return _state_response(review_configurations.list_configurations(session, principal))
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/publish",
    response_model=ConfigurationStateResponse,
    operation_id="publishConfiguration",
)
def publish(
    body: ConfigurationPublishRequest, principal: User, session: DB
) -> ConfigurationStateResponse:
    try:
        review_configurations.publish_draft(
            session,
            principal,
            revision_id=body.revision_id,
            expected_sequence=body.expected_sequence,
            request_id=body.request_id,
            reason=body.reason,
        )
        return _state_response(review_configurations.list_configurations(session, principal))
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/deactivate",
    response_model=ConfigurationStateResponse,
    operation_id="deactivateConfiguration",
)
def deactivate(
    body: ConfigurationDisableRequest, principal: User, session: DB
) -> ConfigurationStateResponse:
    try:
        review_configurations.deactivate(
            session,
            principal,
            expected_sequence=body.expected_sequence,
            request_id=body.request_id,
            reason=body.reason,
        )
        return _state_response(review_configurations.list_configurations(session, principal))
    except Exception as exc:
        raise _translate(exc) from exc


@router.post(
    "/rollback",
    response_model=ConfigurationStateResponse,
    operation_id="rollbackConfiguration",
)
def rollback(
    body: ConfigurationRollbackRequest, principal: User, session: DB
) -> ConfigurationStateResponse:
    try:
        review_configurations.rollback(
            session,
            principal,
            revision_id=body.target_revision_id,
            expected_sequence=body.expected_sequence,
            request_id=body.request_id,
            reason=body.reason,
        )
        return _state_response(review_configurations.list_configurations(session, principal))
    except Exception as exc:
        raise _translate(exc) from exc
