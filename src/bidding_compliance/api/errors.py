"""Public errors never echo exception details, inputs or stack traces."""

from typing import cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from bidding_compliance.core.tracing import get_request_id

from .schemas import ErrorCode, ErrorResponse

ERRORS: dict[int, tuple[ErrorCode, str]] = {
    400: (ErrorCode.INVALID_REQUEST, "请求无效。"),
    401: (ErrorCode.UNAUTHENTICATED, "请先登录。"),
    403: (ErrorCode.FORBIDDEN, "没有执行此操作的权限。"),
    404: (ErrorCode.NOT_FOUND, "资源不存在或不可见。"),
    405: (ErrorCode.METHOD_NOT_ALLOWED, "不支持此请求方法。"),
    409: (ErrorCode.CONFLICT, "请求与当前资源状态冲突。"),
    413: (ErrorCode.PAYLOAD_TOO_LARGE, "请求内容超过限制。"),
    415: (ErrorCode.UNSUPPORTED_MEDIA_TYPE, "不支持此内容类型。"),
    422: (ErrorCode.VALIDATION_ERROR, "请求参数不符合要求。"),
    429: (ErrorCode.RATE_LIMITED, "请求过于频繁，请稍后重试。"),
    500: (ErrorCode.INTERNAL_ERROR, "服务暂时无法处理请求，请稍后重试。"),
}


class StructuredValidationError(HTTPException):
    """A server-authored, field-specific 422 without exposing arbitrary exception data."""

    def __init__(self, message: str, details: dict[str, object]) -> None:
        super().__init__(status_code=422)
        self.public_message = message
        self.public_details = details


def error_response(status_code: int, details: dict[str, object] | None = None) -> JSONResponse:
    code, message = ERRORS.get(
        status_code, ERRORS[500] if status_code >= 500 else (ErrorCode.HTTP_ERROR, "请求无法处理。")
    )
    body = ErrorResponse(
        code=code, message=message, request_id=get_request_id(), details=details or {}
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def http_error_handler(request: Request, exception: Exception) -> JSONResponse:
    del request
    error = cast(HTTPException, exception)
    if isinstance(error, StructuredValidationError):
        body = ErrorResponse(
            code=ErrorCode.VALIDATION_ERROR,
            message=error.public_message,
            request_id=get_request_id(),
            details=error.public_details,
        )
        response = JSONResponse(status_code=422, content=body.model_dump())
    else:
        response = error_response(error.status_code)
    # Preserve protocol headers, not arbitrary values from exception payloads.
    for key, value in (error.headers or {}).items():
        if key.lower() in {"allow", "retry-after", "www-authenticate"}:
            response.headers[key] = value
    return response


async def validation_error_handler(request: Request, exception: Exception) -> JSONResponse:
    del request
    error = cast(RequestValidationError, exception)
    return error_response(422, {"error_count": len(error.errors())})
