"""Side-effect-free application factory; no model/database connections at startup."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from bidding_compliance import __version__
from bidding_compliance.core.config import Settings

from .errors import http_error_handler, validation_error_handler
from .middleware import RequestContextMiddleware
from .schemas import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    app = FastAPI(
        title="招标文件智能合规审查 API",
        version=__version__,
        debug=False,
        docs_url="/docs" if configuration.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if configuration.docs_enabled else None,
    )
    app.state.settings = configuration
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/api/v1/health", response_model=HealthResponse, operation_id="getHealth")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app
